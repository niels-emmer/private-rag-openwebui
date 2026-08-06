#!/usr/bin/env python3
"""
Ingest an Obsidian vault (or any Markdown directory) into ChromaDB
for RAG search via OpenWebUI.

Usage (from project root):
  docker compose --profile ingestion run --rm ingestion

Environment variables (all optional):
  VAULT_PATH     /vault                    (mounted volume)
  CHROMA_HOST    chromadb
  CHROMA_PORT    8000
  OLLAMA_URL     http://host.docker.internal:11434
  EMBED_MODEL    nomic-embed-text
  COLLECTION     second_brain
  CHUNK_WORDS    500
  CHUNK_OVERLAP  50
"""

import os
import re
import hashlib
import sys
import time
from pathlib import Path

import chromadb
import requests

# --- Config ---
VAULT_PATH = Path(os.getenv("VAULT_PATH", "/vault"))
CHROMA_HOST = os.getenv("CHROMA_HOST", "chromadb")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
COLLECTION_NAME = os.getenv("COLLECTION", "second_brain")
CHUNK_WORDS = int(os.getenv("CHUNK_WORDS", "500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "50"))
MAX_FAILURE_RATE = float(os.getenv("MAX_FAILURE_RATE", "0.1"))
STAGING_SUFFIX = "__staging"


# --- Chunking ---

def chunk_markdown(text: str, source: str) -> list[dict]:
    """Split markdown into chunks by heading, then by word count."""
    # Split on headings (lines starting with #)
    parts = re.split(r'(^#+\s+.*$)', text, flags=re.MULTILINE)
    raw_chunks: list[dict] = []
    current_heading = ""
    buf = ""

    for part in parts:
        if re.match(r'^#+\s+', part):
            if buf.strip():
                raw_chunks.append({"text": buf.strip(), "heading": current_heading, "source": source})
            current_heading = part.strip()
            buf = part + "\n"
        else:
            buf += part

    if buf.strip():
        raw_chunks.append({"text": buf.strip(), "heading": current_heading, "source": source})

    # Further split oversized chunks
    final: list[dict] = []
    for c in raw_chunks:
        words = c["text"].split()
        if len(words) <= CHUNK_WORDS:
            final.append(c)
        else:
            for i in range(0, len(words), CHUNK_WORDS - CHUNK_OVERLAP):
                sub = " ".join(words[i : i + CHUNK_WORDS])
                final.append({"text": sub, "heading": c["heading"], "source": c["source"]})

    return final


# --- Embeddings ---

def get_embedding(text: str, retries: int = 3) -> list[float]:
    for attempt in range(retries):
        try:
            resp = requests.post(
                f"{OLLAMA_URL}/api/embeddings",
                json={"model": EMBED_MODEL, "prompt": text},
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json()["embedding"]
        except Exception as e:
            if attempt == retries - 1:
                raise
            print(f"  WARNING: embedding attempt {attempt + 1} failed ({e}), retrying...")
            time.sleep(2 ** attempt)


# --- Main ---

def main():
    if not VAULT_PATH.is_dir():
        print(f"ERROR: VAULT_PATH '{VAULT_PATH}' is not a directory or does not exist.")
        sys.exit(1)

    if CHUNK_OVERLAP >= CHUNK_WORDS:
        print(f"ERROR: CHUNK_OVERLAP ({CHUNK_OVERLAP}) must be less than CHUNK_WORDS ({CHUNK_WORDS}).")
        sys.exit(1)

    print(f"Connecting to ChromaDB at {CHROMA_HOST}:{CHROMA_PORT}...")
    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)

    # Ingest into a staging collection first; the live collection is only
    # replaced once staging has proven itself (see the failure-rate check
    # below). This avoids wiping production data on e.g. an Ollama outage.
    staging_name = f"{COLLECTION_NAME}{STAGING_SUFFIX}"
    try:
        client.delete_collection(staging_name)
        print(f"Deleted leftover staging collection '{staging_name}' from a previous run")
    except Exception as e:
        print(f"  (no leftover staging collection: {e})")

    collection = client.create_collection(staging_name)
    print(f"Created staging collection '{staging_name}'")

    # Walk vault and chunk all .md files
    md_files = sorted(VAULT_PATH.rglob("*.md"))
    if not md_files:
        print(f"No .md files found under {VAULT_PATH}")
        client.delete_collection(staging_name)
        sys.exit(0)

    all_chunks: list[dict] = []
    for fpath in md_files:
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
            chunks = chunk_markdown(text, str(fpath))
            all_chunks.extend(chunks)
        except Exception as e:
            print(f"  SKIP {fpath}: {e}")

    print(f"Found {len(md_files)} files, {len(all_chunks)} chunks")

    if not all_chunks:
        print("Nothing to ingest.")
        client.delete_collection(staging_name)
        sys.exit(0)

    # Batch insert into ChromaDB
    total_embedded = 0
    batch_size = 50
    for i in range(0, len(all_chunks), batch_size):
        batch = all_chunks[i : i + batch_size]
        texts = [c["text"] for c in batch]
        ids = [hashlib.md5(f"{c['source']}:{c['text']}".encode()).hexdigest() for c in batch]
        metadatas = [
            {"source": c["source"], "heading": c.get("heading", "")} for c in batch
        ]

        # Generate embeddings sequentially, skipping chunks that fail
        good_ids, good_embeddings, good_docs, good_metas = [], [], [], []
        for idx, text in enumerate(texts):
            try:
                good_embeddings.append(get_embedding(text))
                good_ids.append(ids[idx])
                good_docs.append(text)
                good_metas.append(metadatas[idx])
            except Exception as e:
                print(f"  SKIP chunk (embed failed): {metadatas[idx]['source']} — {e}")

        if good_ids:
            collection.add(ids=good_ids, embeddings=good_embeddings, documents=good_docs, metadatas=good_metas)
        total_embedded += len(good_ids)
        done = min(i + batch_size, len(all_chunks))
        print(f"  [{done:>5}/{len(all_chunks)}] ingested")

    total_chunks = len(all_chunks)
    failure_rate = 1 - (total_embedded / total_chunks)
    print(f"\nEmbedded {total_embedded}/{total_chunks} chunks ({failure_rate:.0%} failed).")

    if total_embedded == 0 or failure_rate > MAX_FAILURE_RATE:
        print(
            f"ERROR: failure rate {failure_rate:.0%} exceeds threshold {MAX_FAILURE_RATE:.0%}; "
            f"aborting without touching existing collection '{COLLECTION_NAME}'."
        )
        client.delete_collection(staging_name)
        sys.exit(1)

    # Staging succeeded: swap it in as the live collection.
    try:
        client.delete_collection(COLLECTION_NAME)
        print(f"Deleted previous collection '{COLLECTION_NAME}'")
    except Exception as e:
        print(f"  (no previous collection to delete: {e})")

    collection.modify(name=COLLECTION_NAME)
    print(f"Promoted staging collection to '{COLLECTION_NAME}'")
    print(f"Model: {EMBED_MODEL}")
    print(f"Source: {VAULT_PATH}")


if __name__ == "__main__":
    main()
