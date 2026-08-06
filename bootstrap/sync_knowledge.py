#!/usr/bin/env python3
"""
Sync the configured Obsidian vault's Knowledge/ docs (plus the root
"What's new in 2026.md" survey) into OpenWebUI's Knowledge collection named
after CUSTOMER_NAME (.env), which is what actually feeds RAG for the Azure
DevOps Advisor model.

That collection is an upload-based snapshot (see AGENTS.md), not a live
sync of the vault folder — editing the vault files alone does not reach
RAG until this script (or an equivalent manual re-upload) runs.

For each local file:
  - If a file with the same name already exists in the collection, its
    content is updated in place via POST /files/{id}/data/content/update
    (OpenWebUI re-embeds it into the knowledge collection automatically).
  - Otherwise it's uploaded as a new file and attached to the collection.

Usage:
    set -a; source .env; set +a
    OWUI_EMAIL=your@email OWUI_PASSWORD=yourpass python3 bootstrap/sync_knowledge.py

Requires:
    - OpenWebUI running at http://localhost:3042
    - .env sourced (CUSTOMER_NAME, VAULT_HOST_PATH)
    - The CUSTOMER_NAME knowledge collection already created in OpenWebUI
    - Admin or write-access credentials (prompted if env vars not set)
"""

import json
import mimetypes
import os
import sys
import urllib.request
import urllib.error
import uuid

BASE_URL = "http://localhost:3042"
KNOWLEDGE_NAME = os.environ["CUSTOMER_NAME"]

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VAULT_DIR = os.environ["VAULT_HOST_PATH"]
KNOWLEDGE_DIR = os.path.join(VAULT_DIR, "Knowledge")

# Explicit file list, not a directory walk — keeps this in sync with exactly
# what's meant to be in the Knowledge collection (mirrors what's already
# uploaded there today: 00-09 + the survey doc, now +10).
FILES_TO_SYNC = sorted(
    os.path.join(KNOWLEDGE_DIR, f)
    for f in os.listdir(KNOWLEDGE_DIR)
    if f.endswith(".md")
) + [os.path.join(VAULT_DIR, "What's new in 2026.md")]


def api(method, path, payload=None, token=None, raw_body=None, content_type=None):
    url = BASE_URL + path
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if raw_body is not None:
        data = raw_body
        headers["Content-Type"] = content_type
    elif payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    else:
        data = None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"HTTP {e.code} on {method} {path}: {body[:300]}", file=sys.stderr)
        raise


def signin(email, password):
    result = api("POST", "/api/v1/auths/signin", {"email": email, "password": password})
    return result["token"]


def resolve_knowledge(token, name):
    resp = api("GET", "/api/v1/knowledge/", token=token)
    collections = resp if isinstance(resp, list) else resp.get("items", resp.get("data", []))
    for c in collections:
        if c["name"] == name:
            return c["id"]
    raise SystemExit(f"Knowledge collection '{name}' not found — create it in OpenWebUI first.")


def existing_files_by_name(token, knowledge_id):
    # GET /{id} does NOT populate `files` in this OpenWebUI version (only
    # create/update/file-add/etc. handlers do) — the real listing endpoint
    # is /{id}/files, paginated (default 30/page, plenty for this corpus).
    detail = api("GET", f"/api/v1/knowledge/{knowledge_id}/files", token=token)
    return {f["filename"]: f["id"] for f in (detail.get("items") or []) if f}


def update_file_content(token, file_id, content):
    # Sets file.data.content directly via process_file(content=...),
    # bypassing text extraction entirely — the reliable path for both
    # updating existing files and seeding brand-new ones (see upload_new_file).
    api("POST", f"/api/v1/files/{file_id}/data/content/update", {"content": content}, token=token)


def upload_new_file(token, path):
    filename = os.path.basename(path)

    # process=false skips server-side text extraction on upload entirely.
    # A hand-rolled multipart body sent through this path was observed to
    # produce empty extracted content (file stored correctly, size matched,
    # but data.content came back "" with status "completed") — root cause
    # not pinned down, so don't rely on upload-time extraction at all.
    # This call only needs to create the File row; update_file_content()
    # (called right after, in main()) sets the real content directly.
    content_type = mimetypes.guess_type(filename)[0] or "text/markdown"
    placeholder = b"placeholder"

    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode() + placeholder + f"\r\n--{boundary}--\r\n".encode()

    result = api(
        "POST",
        "/api/v1/files/?process=false",
        raw_body=body,
        content_type=f"multipart/form-data; boundary={boundary}",
        token=token,
    )
    return result["id"]


def attach_file(token, knowledge_id, file_id):
    api("POST", f"/api/v1/knowledge/{knowledge_id}/file/add", {"file_id": file_id}, token=token)


def main():
    email = os.environ.get("OWUI_EMAIL") or input("OpenWebUI email: ")
    password = os.environ.get("OWUI_PASSWORD") or input("OpenWebUI password: ")

    print("Signing in...")
    token = signin(email, password)

    print(f"Resolving knowledge collection '{KNOWLEDGE_NAME}'...")
    knowledge_id = resolve_knowledge(token, KNOWLEDGE_NAME)
    print(f"  -> {knowledge_id}")

    print("Fetching current file list...")
    existing = existing_files_by_name(token, knowledge_id)
    print(f"  {len(existing)} files currently in the collection")

    for path in FILES_TO_SYNC:
        filename = os.path.basename(path)
        if not os.path.isfile(path):
            print(f"  SKIP {filename}: not found at {path}")
            continue

        with open(path, encoding="utf-8") as f:
            content = f.read()

        if filename in existing:
            print(f"  Updating content: {filename}")
            update_file_content(token, existing[filename], content)
        else:
            print(f"  Uploading new file: {filename}")
            file_id = upload_new_file(token, path)
            update_file_content(token, file_id, content)
            attach_file(token, knowledge_id, file_id)

    print(f"Done. Verify in OpenWebUI: Workspace -> Knowledge -> {KNOWLEDGE_NAME}.")


if __name__ == "__main__":
    main()
