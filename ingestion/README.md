# Ingestion Pipeline

Chunks the configured Obsidian vault (`VAULT_HOST_PATH` in `.env`) into ChromaDB for RAG search in OpenWebUI.

## Files

| File | Purpose |
|------|---------|
| `Dockerfile` | Python 3.12-slim image with `chromadb==1.5.9` and `requests==2.32.3` |
| `ingest.py` | Walks the vault, chunks Markdown by heading, embeds via Ollama, stores in ChromaDB |

## How it works

1. Walks all `.md` files under `VAULT_PATH` (`/vault`, mounted from `VAULT_HOST_PATH` in `.env`) — scope this to just the material relevant to this stack's persona; a broader personal vault mixing multiple contexts should not be mounted here
2. Splits each file into chunks by heading (`#`, `##`, `###`, etc.)
3. Further splits any chunk exceeding `CHUNK_WORDS` (default: 500) with `CHUNK_OVERLAP` (default: 50) word overlap
4. Generates an embedding for each chunk via Ollama's `/api/embeddings` endpoint using `nomic-embed-text`
5. Inserts chunks into a **staging** collection (`<COLLECTION>__staging`) in batches of 50, with MD5-hashed IDs (namespaced by source path) and `{source, heading}` metadata
6. Only after staging succeeds (failure rate below `MAX_FAILURE_RATE`) is the live collection deleted and staging promoted to take its place — an outage mid-run leaves the previous live collection untouched instead of wiping it

## Running

```sh
# First time or after compose changes (builds the image)
docker compose --profile ingestion run --rm ingestion

# After changes to ingest.py only
docker compose --profile ingestion build ingestion
docker compose --profile ingestion run --rm ingestion
```

The service is **profile-gated** — it never starts with `docker compose up -d`. You must invoke it explicitly with `--profile ingestion`.

ChromaDB and Ollama must both be running before you start an ingestion run.

## Configuration

All settings are env vars with defaults that match the compose stack:

| Variable | Default | Description |
|----------|---------|-------------|
| `VAULT_PATH` | `/vault` | Path to the mounted Markdown directory |
| `CHROMA_HOST` | `chromadb` | ChromaDB service hostname |
| `CHROMA_PORT` | `8000` | ChromaDB service port |
| `OLLAMA_URL` | `http://host.docker.internal:11434` | Ollama base URL |
| `EMBED_MODEL` | `nomic-embed-text` | Ollama embedding model |
| `COLLECTION` | `second_brain` | ChromaDB collection name |
| `CHUNK_WORDS` | `500` | Max words per chunk before splitting |
| `CHUNK_OVERLAP` | `50` | Word overlap between split chunks (must be less than `CHUNK_WORDS`) |
| `MAX_FAILURE_RATE` | `0.1` | Abort without touching the live collection if more than this fraction of chunks fail to embed |

## Scheduled daily run (launchd)

A launchd plist can be installed at `~/Library/LaunchAgents/com.<youruser>.openwebui.ingestion.plist` (lives outside this repo — name it however you like) to run the ingestion at **03:00 daily**.

```sh
# Enable (survives reboots)
launchctl load ~/Library/LaunchAgents/com.<youruser>.openwebui.ingestion.plist

# Check status (- in PID column = idle, 0 = last exit clean)
launchctl list | grep <youruser>.openwebui

# Trigger a manual run immediately
launchctl start com.<youruser>.openwebui.ingestion

# Watch live output
tail -f ingestion.log   # from the repo root

# Disable the schedule
launchctl unload ~/Library/LaunchAgents/com.<youruser>.openwebui.ingestion.plist
```

> If the Mac is asleep at 03:00, the job is skipped — launchd does not catch up on wake.

## Gotchas

- **Full re-embed on every run.** There is no diffing or incremental update — a large vault means every chunk gets re-embedded each run, into a staging collection that's only promoted to live if it succeeds (see `MAX_FAILURE_RATE` above). No wipe of the live collection happens on a failed run.
- **ID collisions (narrow).** Chunk IDs are MD5 hashes of `<source path>:<chunk text>`, so they're namespaced per file — identical text in two *different* files does **not** collide. Byte-identical chunk text repeated *within the same file* (e.g. duplicated boilerplate) will still produce the same ID and overwrite.
- **Embeddings are sequential.** Each chunk is embedded one at a time via the Ollama HTTP API. A large vault will take a while.
- **`nomic-embed-text` must be pulled in Ollama** before running. Verify with `ollama list`.
- **A leftover `<COLLECTION>__staging` collection** from an aborted run is automatically deleted at the start of the next run.
