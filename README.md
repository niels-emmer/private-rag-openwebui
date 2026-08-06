# Private RAG Stack for OpenWebUI

A self-hosted, fully local Retrieval-Augmented Generation (RAG) stack built around [OpenWebUI](https://github.com/open-webui/open-webui) and [Ollama](https://ollama.com/), with a ChromaDB vector store, MCP tool integrations, and a privacy-preserving web search path. Everything runs on your own machine — no proprietary data, documents, or queries leave the host.

The stack ships with a working example configuration: an "Azure DevOps Advisor" persona that answers questions grounded in a knowledge base and an Obsidian vault. The persona, prompt, and skills are entirely customizable — swap them for your own domain, documents, and system prompt.

## Introduction

This project packages a local-first AI assistant environment as a single Docker Compose stack. It's designed for people who want:

- A private ChatGPT-style interface (OpenWebUI) talking to models running locally via Ollama.
- Retrieval-augmented answers grounded in your own documents (a knowledge base plus an optional Obsidian vault), instead of relying purely on model memory.
- Agentic tool access (filesystem, web fetch, a knowledge-graph memory, vault search) via the Model Context Protocol (MCP), proxied through [MCPO](https://github.com/open-webui/mcpo).
- Private web search — queries are routed through a self-hosted SearXNG instance, with a PII-redaction proxy in front of it so personal data never reaches upstream search engines (DuckDuckGo, Google, etc.).
- A reusable pattern: a "customer"/"project" identity, a persona system prompt, and a set of Skills, all templated so the same stack can be re-purposed for a different domain by editing one `.env` file.

Nothing here talks to a cloud LLM API. The only network egress by default is outbound web-search traffic (already PII-redacted) and package downloads at build time.

## Features

- **Local-only inference** — Ollama runs on the host and serves all chat and embedding requests; no API keys, no per-token billing, no data leaving the machine.
- **ChromaDB vector store** — OpenWebUI's default SQLite-backed vector store is swapped for a dedicated ChromaDB container for RAG search.
- **MCP tool access** — via MCPO, the model can use:
  - **Obsidian vault search** — read-only semantic/full-text access to a local Obsidian vault.
  - **Web fetch** — retrieve and read arbitrary URLs.
  - **Filesystem** — read-only access scoped to the repo root.
  - **Knowledge-graph memory** — a persistent entity/relation graph the model can read and write across sessions.
- **Privacy-preserving web search** — a self-hosted SearXNG metasearch engine, network-isolated so it's reachable only through a Presidio-based PII-redaction proxy. Search queries are scrubbed of names, emails, phone numbers, and locations before they reach external search engines. The proxy fails closed: if PII detection is unavailable, the query is dropped rather than forwarded unredacted.
- **A custom persona model** — an example model definition (prompt, tools, skills, knowledge) is created and kept in sync via a bootstrap script, wrapping a base Ollama model with a fixed system prompt.
- **Skills** — OpenWebUI's Skills feature provides on-demand checklists, playbooks, and tool-usage instructions to the model without bloating the system prompt on every turn. Ships with 11 example skills (9 templated for easy re-branding, 2 generic).
- **Knowledge base sync** — a bootstrap script uploads/updates a folder of Markdown docs into an OpenWebUI Knowledge collection used for RAG.
- **Vault ingestion pipeline** — a separate, profile-gated pipeline that chunks an entire Obsidian vault by heading, embeds it via Ollama, and loads it into a ChromaDB collection — a second, independent RAG path for full-vault semantic search (distinct from the curated Knowledge collection above).
- **Browser-based terminal** — [Open Terminal](https://github.com/open-webui/open-terminal) gives the model (or you) a sandboxed shell reachable from the OpenWebUI workspace.
- **Secrets via Docker Compose secrets** — API keys and the WebUI signing secret are file-based secrets, not plaintext env vars, and are easy to rotate.
- **Templated identity** — a single `.env` (`CUSTOMER_NAME`, `PROJECT_NAME`, `INDUSTRY`) drives the Knowledge collection name and skill content via a render script, so the stack can be re-branded for a new domain without hand-editing every file.
- **Loopback-only by default** — every service binds to `127.0.0.1`; remote access is expected to go through Tailscale or an SSH tunnel, never a directly exposed port.

## Architecture

```
host (macOS)          docker containers
─────────────────────────────────────────
Ollama (port 11434) ──> openwebui (3042)
                         chromadb  (8001)
                         mcpo      (8002)  ──X (no route, isolated net)
                         searxng-pii-proxy (3045) ──> searxng (3044, searxng_internal only)
                                            ├──> presidio-analyzer
                                            └──> presidio-anonymizer
                         open-terminal (3043)
```

| Component | Role |
|---|---|
| **Ollama** | Runs on the host (not containerized) and serves chat + embedding models. OpenWebUI reaches it via `host.docker.internal:11434`. |
| **OpenWebUI** | The chat UI and application server. Only intended LAN-facing surface; binds to loopback and is reached remotely via Tailscale/SSH tunnel. |
| **ChromaDB** | Vector store backing OpenWebUI's RAG search (replaces the default SQLite store). Must be healthy before OpenWebUI starts. |
| **MCPO** | Proxies MCP servers (Obsidian vault, web fetch, filesystem, memory) as OpenAPI tool endpoints OpenWebUI can call. Bearer-token authenticated; isolated from `searxng`. |
| **SearXNG** | Self-hosted, privacy-respecting metasearch engine used for RAG web search. Network-isolated — reachable only from `searxng-pii-proxy`. |
| **searxng-pii-proxy** | FastAPI proxy sitting in front of SearXNG. Redacts PII from search queries via Microsoft Presidio before they reach external search engines; fails closed on Presidio outage. |
| **presidio-analyzer / presidio-anonymizer** | Detect and redact PII text on behalf of `searxng-pii-proxy`. Internal-only, no host ports. |
| **Open Terminal** | Browser-based terminal exposed as an OpenWebUI workspace tool. |
| **ingestion** (profile-gated) | One-shot/scheduled job that chunks an Obsidian vault, embeds it via Ollama, and loads it into a `second_brain` ChromaDB collection. Never starts with `docker compose up -d`. |

Startup order is healthcheck-gated: `chromadb` → `openwebui` → `open-terminal`. `searxng` starts independently; `searxng-pii-proxy` depends on `searxng` and both Presidio containers.

Full details — ports, security model, MCPO tool registration, custom model configuration, Skills, gotchas — live in [`AGENTS.md`](./AGENTS.md), which is the maintained source of truth for this repo (kept tool-agnostic so both Claude Code and OpenCode work well from it).

## Prerequisites

- **Docker** and **Docker Compose** (v2, the `docker compose` plugin).
- **[Ollama](https://ollama.com/)** installed and running on the host — not in a container. Pull at least a chat model and an embedding model:
  ```sh
  ollama pull qwen3:30b-a3b        # or any chat model of your choice
  ollama pull nomic-embed-text     # required by the ingestion pipeline and RAG embeddings
  ```
- **macOS with Docker Desktop** is the tested/primary target (`host.docker.internal` resolution, launchd scheduling examples). On Linux, use `--network host` or `172.17.0.1` in place of `host.docker.internal`, and swap launchd examples for `cron`/`systemd` timers.
- Enough RAM to run your chosen model plus the container stack alongside it. The reference setup (M4 Pro, 24GB RAM) runs a ~23GB model with the containers capped at roughly 7–8GB combined — size your own model choice accordingly.
- **Python 3** (for the bootstrap scripts and `openssl`/`curl` used in setup).
- Optionally, an **Obsidian vault** (or any folder of Markdown files) if you want vault search and/or ingestion — this is optional; the stack works without it.
- Optionally, **[Tailscale](https://tailscale.com/)** or another VPN/tunnel if you want to reach OpenWebUI from outside the host — every service binds to loopback only by default.

## Getting started

### 1. Clone

```sh
git clone <this-repo-url> private-rag-openwebui
cd private-rag-openwebui
```

### 2. Configure secrets

Four Docker secrets are gitignored and must be generated locally (see [`secrets/README.md`](./secrets/README.md)):

```sh
for f in webui_secret_key mcpo_api_key open_terminal_api_key; do
  openssl rand -hex 32 > "secrets/$f"
done
echo "your-hf-token" > secrets/hf_token   # only needed for gated HuggingFace models
```

### 3. Configure SearXNG

```sh
cp searxng/settings.yml.example searxng/settings.yml
# then replace the placeholder secret_key inside the file (instructions included)
```

### 4. Configure environment / customize the persona

```sh
cp .env.example .env
```

Edit `.env` and fill in:

| Variable | Purpose |
|---|---|
| `CUSTOMER_NAME` | Drives the OpenWebUI Knowledge collection name and templated skill content — this is your re-branding lever |
| `PROJECT_NAME` | Project identifier, surfaced in generated config |
| `INDUSTRY` | Descriptive metadata only (model description/README context) |
| `VAULT_HOST_PATH` | Path to your local Obsidian vault (or any Markdown folder) — mounted read-only. Omit vault-dependent features if you don't have one. |

Then render the templated Skills and run the bootstrap scripts:

```sh
set -a; source .env; set +a
./scripts/render-templates.sh      # renders skills/*.md.template -> skills/*.md
```

### 5. Start the stack

```sh
docker compose up -d
```

This brings up OpenWebUI, ChromaDB, MCPO, SearXNG + the PII proxy + Presidio, and Open Terminal. The ingestion service is profile-gated and does **not** start here (see below).

### 6. Wire up the model, tools, and knowledge base

These are OpenWebUI database-backed settings and must be (re-)applied after every `docker compose down -v`:

```sh
# Create/update the example persona model (prompt, tools, skills, knowledge ref)
OWUI_EMAIL=you@example.com OWUI_PASSWORD=yourpass python3 bootstrap/azure_devops_advisor.py

# Upload/sync your knowledge-base docs into the Knowledge collection
OWUI_EMAIL=you@example.com OWUI_PASSWORD=yourpass python3 bootstrap/sync_knowledge.py
```

Then, following the API examples in [`AGENTS.md`](./AGENTS.md):
- Repoint OpenWebUI's web-search URL to `http://searxng-pii-proxy:8080/search?q=<query>` (**SearXNG PII redaction**).
- Register the MCPO tool servers (Obsidian, web fetch, filesystem, memory) under Workspace → Tools (**MCPO tool server configuration**) — must be done via the API, the Admin Panel UI sends the wrong connection type.
- Apply the recommended RAG/search/admin defaults (**OpenWebUI database settings**).

### 7. Customize for your own use case

This repo ships with a working example (an "Azure DevOps Advisor" persona for Dutch financial services). To repurpose it:

- Edit `system-prompt.md` for the persona's system prompt, then re-run `bootstrap/azure_devops_advisor.py`.
- Edit or replace the files in `skills/` for domain-specific checklists/playbooks (or delete the ones you don't need and drop them from the model's `meta.skillIds` in the bootstrap script).
- Point `.env`'s `VAULT_HOST_PATH` at your own vault, and populate a `Knowledge/` folder inside it with the docs you want in RAG, then run `bootstrap/sync_knowledge.py`.
- Swap the base Ollama model referenced in `bootstrap/azure_devops_advisor.py` for whichever local model you've pulled.

### Optional: vault ingestion pipeline

A separate pipeline (`ingestion/`) chunks your entire vault and embeds it into a ChromaDB `second_brain` collection — full details in [`ingestion/README.md`](./ingestion/README.md). It's independent of the curated Knowledge collection above and is not attached to the example model by default.

```sh
docker compose --profile ingestion run --rm ingestion
```

### Everyday commands

```sh
docker compose up -d                       # start everything
docker compose logs -f openwebui           # tail logs for a service
docker compose pull && docker compose up -d  # pull latest images and recreate
docker compose down                        # stop everything, keep data
docker compose down -v                     # stop and wipe all volumes (destroys data)
```

## References

| Project | URL |
|---|---|
| OpenWebUI | <https://github.com/open-webui/open-webui> |
| OpenWebUI Docs | <https://docs.openwebui.com/> |
| MCPO | <https://github.com/open-webui/mcpo> |
| Open Terminal | <https://github.com/open-webui/open-terminal> |
| Ollama | <https://ollama.com/> |
| ChromaDB | <https://www.trychroma.com/> |
| SearXNG | <https://github.com/searxng/searxng-docker> |
| Microsoft Presidio | <https://github.com/microsoft/presidio> |
| Model Context Protocol (MCP) | <https://modelcontextprotocol.io/> |

See [`AGENTS.md`](./AGENTS.md) for the full architectural detail, security model, gotchas, and maintenance notes — it's the single source of truth for both human and AI-agent sessions working in this repo.

## Credits

Built on top of the excellent work of the [OpenWebUI](https://github.com/open-webui) team and the broader open-source projects this stack composes: Ollama, ChromaDB, SearXNG, and Microsoft Presidio.

## License

[MIT](./LICENSE)
