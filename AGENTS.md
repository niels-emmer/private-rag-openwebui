# OpenWebUI + ChromaDB Stack

> **Maintenance rule:** After any major change, and before completing any task that touches the stack, keep `AGENTS.md` and `ingestion/README.md` up to date and well-structured.

Private Docker Compose stack for OpenWebUI with ChromaDB, MCPO, SearXNG, and Open Terminal, backed by local Ollama on a MacBook Pro M4 Pro (24GB RAM).

**Purpose:** Build a local-first OpenWebUI environment for personal projects — functional, responsive, and fully offline-capable using locally available models through Ollama. No proprietary info leaves the machine.

## First-time setup

On a fresh clone, three things are gitignored and must be created locally before `docker compose up -d`:

1. **Secrets** — see [`secrets/README.md`](./secrets/README.md) for the four files to generate.
2. **SearXNG config** — `cp searxng/settings.yml.example searxng/settings.yml` and replace the placeholder `secret_key` (instructions in the file).
3. **Environment config** — `cp .env.example .env` and fill in `CUSTOMER_NAME`, `PROJECT_NAME`, `INDUSTRY`, and `VAULT_HOST_PATH` (path to your local Obsidian vault). Then, before running any bootstrap or render script:
   ```sh
   set -a; source .env; set +a
   ./scripts/render-templates.sh      # renders skills/*.md.template -> skills/*.md
   OWUI_EMAIL=... OWUI_PASSWORD=... python3 bootstrap/azure_devops_advisor.py
   OWUI_EMAIL=... OWUI_PASSWORD=... python3 bootstrap/sync_knowledge.py
   ```
   `docker compose` reads `.env` natively for `${VAR}` interpolation (e.g. `VAULT_HOST_PATH` in the vault bind mounts); the render/bootstrap scripts need it explicitly sourced into the shell first, since they run outside Compose.

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

- **Ollama runs on the host**, not in a container. OpenWebUI connects via `host.docker.internal:11434`.
- **ChromaDB** is the vector store (not the default sqlite). Must be healthy before OpenWebUI starts.
- **MCPO** proxies MCP servers (Obsidian vault, web fetch, filesystem, memory) to OpenWebUI.
- **SearXNG** is a self-hosted, privacy-respecting metasearch engine used by OpenWebUI for RAG web search. Queries are proxied through SearXNG to external engines (DuckDuckGo, Google, etc.) without exposing your identity or building a search profile. Network-isolated (`searxng_internal`) — only reachable via **searxng-pii-proxy**, see **SearXNG PII redaction** below.
- **searxng-pii-proxy** sits between OpenWebUI and SearXNG, redacting PII (names, emails, phone numbers, locations, etc.) from search queries via Microsoft Presidio before they reach SearXNG's external upstream engines.
- **presidio-analyzer / presidio-anonymizer** detect and redact PII text on behalf of searxng-pii-proxy. Internal-only, no host ports.
- **Open Terminal** provides a browser-based terminal; depends on OpenWebUI being healthy.

## Ports

| Service             | Host | Container | Notes                              |
|----------------------|------|-----------|------------------------------------|
| OpenWebUI            | 3042 | 8080      | Main UI — loopback-only (`127.0.0.1:3042`); use Tailscale/SSH tunnel for remote access |
| ChromaDB             | 8001 | 8000      | Changed from default 8000          |
| MCPO                 | 8002 | 8000      | Changed from default 8000          |
| SearXNG              | 3044 | 8080      | Self-hosted metasearch engine; network-isolated, see below |
| searxng-pii-proxy    | 3045 | 8080      | PII redaction proxy in front of SearXNG — loopback debug access |
| presidio-analyzer    | —    | 3000      | Internal-only, no host port        |
| presidio-anonymizer  | —    | 3000      | Internal-only, no host port        |
| Open Terminal        | 3043 | 8000      | App listens on 8000 internally     |

## Startup order

`chromadb` → `openwebui` → `open-terminal`

Both `chromadb` and `openwebui` have healthchecks. `openwebui` waits for `chromadb` to be healthy. `open-terminal` waits for `openwebui` to be healthy. `searxng` starts independently. `searxng-pii-proxy` depends on `searxng`, `presidio-analyzer`, and `presidio-anonymizer` (no healthcheck-gated wait, just `depends_on` start ordering).

## Commands

```sh
# Start everything
docker compose up -d

# View logs for a specific service
docker compose logs -f openwebui

# Rebuild (pull latest images)
docker compose pull && docker compose up -d

# Stop everything
docker compose down

# Wipe volumes (destroys all data)
docker compose down -v
```

## Ingestion pipeline

Chunks the configured Obsidian vault (`VAULT_HOST_PATH` in `.env`) into ChromaDB for RAG search. See `ingestion/README.md` for full details.

**How it works:** splits each `.md` file by heading, further splits chunks over 500 words (50-word overlap), embeds via `nomic-embed-text`, stages into a `second_brain__staging` collection in batches of 50, then promotes staging over the live `second_brain` collection only if the embedding failure rate is below `MAX_FAILURE_RATE` (default 10%) — an outage mid-run aborts instead of wiping production data. There is no incremental update; every run re-embeds the full vault.

**Manual run:**

```sh
# Build and run (one-shot)
docker compose --profile ingestion run --rm ingestion

# Rebuild after script changes
docker compose --profile ingestion build ingestion
docker compose --profile ingestion run --rm ingestion
```

Profile-gated — never starts with `docker compose up -d`. ChromaDB and Ollama must be running first.

**Scheduled daily run (launchd, fires at 03:00):**

The `.plist` itself lives outside this repo (`~/Library/LaunchAgents/`, untracked) — name it however you like; examples below use `com.<youruser>.openwebui.ingestion` as the convention.

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

Note: if the Mac is asleep at 03:00, the job is skipped — it does not catch up on wake.

## SearXNG PII redaction

`searxng-pii-proxy` (`searxng-pii-proxy/`) redacts PII from search queries via Microsoft Presidio before they reach SearXNG's external upstream engines (DuckDuckGo, Google, etc.). Full details in `searxng-pii-proxy/README.md`.

**Why a proxy, not a config change:** OpenWebUI's built-in web search is the primary way queries reach SearXNG (its DB-backed `SEARXNG_QUERY_URL` setting), but `mcpo`'s generic `web_fetch` MCP tool could otherwise be pointed at `searxng` directly by the LLM at runtime, bypassing any redaction wired only into that setting. There's no way to configuration-gate `web_fetch`'s target URL, so the fix is network isolation: `searxng` is on its own `searxng_internal` Docker network, joined only by `searxng` itself and `searxng-pii-proxy`. No other service (including `mcpo`) can resolve or route to `searxng` by name — every query must pass through the proxy.

**Fails closed.** If Presidio (analyzer or anonymizer) is unreachable, times out, or errors, the raw query is never forwarded to SearXNG — the proxy returns `503` and logs the failure. Web search stops working during a Presidio outage; that tradeoff is intentional for a PII-leak-prevention control.

**One-time step after `docker compose up -d`:** OpenWebUI's DB-backed web-search URL must be repointed from `searxng` directly to the proxy (same bearer-token pattern as the MCPO tool registration below):

```sh
TOKEN=$(curl -s -X POST http://localhost:3042/api/v1/auths/signin \
  -H "Content-Type: application/json" \
  -d '{"email": "YOUR_EMAIL", "password": "YOUR_PASSWORD"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

curl -s -X POST http://localhost:3042/api/v1/configs/rag \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" \
  -d '{"web": {"search": {"searxng_query_url": "http://searxng-pii-proxy:8080/search?q=<query>"}}}'
```

This is DB-backed and does not survive `docker compose down -v` — re-apply it alongside the other database settings listed in **OpenWebUI database settings** below.

**Verify network isolation:**

```sh
docker compose exec mcpo getent hosts searxng               # expect: fails (no route)
docker compose exec searxng-pii-proxy getent hosts searxng  # expect: succeeds
```

## MCPO tool server configuration

MCPO tools are configured in OpenWebUI at **Workspace → Tools → Integrations** (not Admin Panel → Settings → Integrations — that section uses MCP Streamable HTTP which MCPO doesn't speak).

The UI sends the wrong connection type regardless of the label shown. Tool servers must be added via the API directly:

```sh
TOKEN=$(curl -s -X POST http://localhost:3042/api/v1/auths/signin \
  -H "Content-Type: application/json" \
  -d '{"email": "YOUR_EMAIL", "password": "YOUR_PASSWORD"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

KEY=$(cat ~/docker/openwebui/secrets/mcpo_api_key)

curl -s -X POST http://localhost:3042/api/v1/configs/tool_servers \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{
    \"TOOL_SERVER_CONNECTIONS\": [
      {\"url\": \"http://mcpo:8000/obsidian\",   \"path\": \"/openapi.json\", \"type\": \"openapi\", \"auth_type\": \"bearer\", \"key\": \"$KEY\", \"headers\": null, \"config\": {\"enable\": true}, \"info\": {\"id\": \"obsidian\",   \"name\": \"Obsidian Vault\"}},
      {\"url\": \"http://mcpo:8000/web_fetch\",  \"path\": \"/openapi.json\", \"type\": \"openapi\", \"auth_type\": \"bearer\", \"key\": \"$KEY\", \"headers\": null, \"config\": {\"enable\": true}, \"info\": {\"id\": \"web_fetch\",  \"name\": \"Web Fetch\"}},
      {\"url\": \"http://mcpo:8000/filesystem\", \"path\": \"/openapi.json\", \"type\": \"openapi\", \"auth_type\": \"bearer\", \"key\": \"$KEY\", \"headers\": null, \"config\": {\"enable\": true}, \"info\": {\"id\": \"filesystem\", \"name\": \"Filesystem\"}},
      {\"url\": \"http://mcpo:8000/memory\",     \"path\": \"/openapi.json\", \"type\": \"openapi\", \"auth_type\": \"bearer\", \"key\": \"$KEY\", \"headers\": null, \"config\": {\"enable\": true}, \"info\": {\"id\": \"memory\",     \"name\": \"Memory\"}}
    ]
  }"
```

Tool connections are stored in OpenWebUI's database (not compose config) and survive container restarts. Re-run this if connections are lost after a `docker compose down -v`.

Open Terminal is accessible from the same **Workspace → Tools** section.

## Custom model

A custom model is configured in OpenWebUI (Workspace → Models) wrapping the primary Ollama model. It carries a fixed system prompt and is the intended entry point for all work sessions — select it manually from the model picker. Note this is distinct from OpenWebUI's DB-level "Default model" setting (`qwen2.5:14b`, see the settings table below), which only affects brand-new chats where no model has been picked yet; it has not been repointed at `azure-devops-advisor`.

**OpenWebUI model ID:** `azure-devops-advisor` — **Base model:** `qwen3:30b-a3b` (MoE, ~3B active params/token — comparable latency to a small dense model, far more reliable tool-calling capacity). 16k context.

Created and maintained via `bootstrap/azure_devops_advisor.py`. Must be re-run after `docker compose down -v`.

> **Do not run this model on `qwen3:14b`.** It was briefly switched to `qwen3:14b` and that silently broke reliable tool/skill-calling: verified via direct Ollama testing that `qwen3:14b` reasons to completion and then produces zero output — no text, no tool call — once the tool grammar is large (10+ tools, which this model always has) and the question isn't a slam-dunk match for one obvious tool. `qwen3:30b-a3b` does not have this failure mode with the identical prompt/tools/question. If tool calls or skills stop firing, check `ollama ps` / the model's `base_model_id` first before re-debugging the prompt or skill wiring.
>
```sh
# Recreate/update the model (prompts for credentials, or set env vars)
OWUI_EMAIL=your@email OWUI_PASSWORD=yourpass python3 bootstrap/azure_devops_advisor.py
```

The script resolves the `CUSTOMER_NAME` (`.env`) knowledge collection by name at runtime (UUID changes after a volume wipe), then creates or updates the model. It reads the system prompt from `system-prompt.md` at run time (not a hardcoded copy), and its `MODEL["meta"]` (`toolIds`, `skillIds`, `builtinTools`, `capabilities`) and `MODEL["params"]["function_calling"]` were synced to the live model config on 2026-08-05 — verified by comparing against `webui.db` directly. Edit the script to change tools, skills, knowledge, or capabilities; edit `system-prompt.md` to change the prompt.

> **Keeping this in sync**: `meta.skillIds`, `toolIds`, and capability toggles are only ever updated live via direct API calls (see the MCPO/Skills sections below), not through this script. If you change any of those live, update the script's `MODEL` dict to match — otherwise the next `down -v` + bootstrap run will silently revert them.

## Knowledge collection (RAG content)

The model's project knowledge — the numbered `Knowledge/` corpus (docs 00-10) plus `What's new in 2026.md` — lives in an OpenWebUI **Knowledge** collection named after `CUSTOMER_NAME` (`.env`; `azure_devops_advisor.py`'s `MODEL["meta"]["knowledge_names"]` resolves it by name at runtime). This is an **upload-based snapshot** stored in OpenWebUI's own DB/vector store, entirely separate from:

- the vault filesystem at `VAULT_HOST_PATH` (`.env`) — editing a file there does **not** reach RAG until it's re-uploaded;
- the `second_brain` ChromaDB collection built by `ingestion/ingest.py` (see **Ingestion pipeline** below) — a completely different pipeline (raw ChromaDB client, Ollama embeddings, not attached to this model's `meta.knowledge` at all, currently unused by this model).

**After editing any file in the vault's `Knowledge/` folder or `What's new in 2026.md`, run:**

```sh
set -a; source .env; set +a
OWUI_EMAIL=your@email OWUI_PASSWORD=yourpass python3 bootstrap/sync_knowledge.py
```

This updates existing files' content in place (OpenWebUI re-embeds automatically) and uploads/attaches any new files. It does not delete files from the collection — removing a doc from the vault does not remove it from RAG; use the Workspace → Knowledge UI for that.

**System prompt:**

```
You are a Principal DevOps Engineer and Azure Solutions Architect specialising in the Dutch financial services sector. Your focus areas are Azure infrastructure (CAF, Well-Architected Framework, Enterprise Landing Zones), Infrastructure as Code (Terraform and Bicep), AKS and Container Apps, MLOps and AI infrastructure on Azure, and security engineering (Zero Trust, Private Link, Managed Identities, Entra ID, Key Vault).

## Behavior

**Security posture**
Apply Zero Trust by default. For sensitive workloads and data, never suggest public endpoints, wildcard RBAC assignments, shared connection strings, or unencrypted storage. When making a recommendation, state concisely why it satisfies the relevant security or resilience requirement.

**Regulatory context**
Apply Dutch financial services regulatory frameworks — EU AI Act, DORA, GDPR, NIS2, EBA ICT guidelines, DNB/AFM/AP supervisory expectations, ISO 27001/42001, CIS Benchmarks — when they materially affect the design decision being discussed. Do not reference compliance frameworks when they are not relevant to the question.

**Provided context**
When retrieved notes or documents are provided, treat them as the primary source. If they appear outdated or conflict with current best practices, use current knowledge and explicitly flag the discrepancy.

**Response format**
Match depth to the question. Direct or syntactic questions get concise direct answers. Architectural and design questions get structured responses with headings, trade-off analysis, and key considerations. Default to concise; go deep when explicitly requested or when the stakes warrant it.

**Language**
Respond in the same language the user writes in.

## Reasoning and communication framework

Apply this framework to every response, gated by the question classification in Response format above: direct/syntactic questions apply rules 1, 2, and 4 without the exploratory surfacing of rule 3; architectural/design questions apply all five in full.

1. **Affirmative Assertions Only** — Eliminate negative contrasting ("not X but Y" constructions). State directly what something is, what it does, and where it fits. No defensive phrasing or synthetic buildup.
2. **Signal Density Over Generalization** — Avoid generic, risk-averse statements and platitudes. Treat broad best practices as weak signals unless contextualized.
3. **Owl Mode (Deep Reasoning First)** — architectural/design questions only. Prioritize exploration over quick conclusions.
4. **Zero Meta Commentary** — No filler, no "as an AI," no validation fluff.
5. **Radical Rigor (Constructive Criticism)** — architectural/design questions only. Actively challenge assumptions, designs, and framing.

## Skills

Domain checklists, playbooks, deliverable templates, and MCP tool usage instructions (knowledge-graph memory, Obsidian vault) live as Skills attached to this model (`meta.skillIds`), not inlined in the prompt — see the **Skills** section below for the full list and how they're maintained.
```

Full current prompt (including the Skills pointer paragraph above) is kept in sync at `system-prompt.md` in the repo root — treat that file, not this doc, as the copy-paste source when updating the prompt by hand.

**Notes:**
- The task model is left empty so background tasks (title generation, tags) run on the already-loaded primary model — no extra memory cost.
- `DEFAULT_MODEL_PARAMS` includes `keep_alive: -1` so the model stays loaded after every interaction.

## Skills

Open WebUI's Skills feature (`skill` table, `/api/v1/skills/*`) — a named `description` + `content` record, distinct from Tools/Functions (no code execution). When attached to a model via `meta.skillIds`, the model sees a lightweight manifest (id/name/description) every turn and pulls full content on demand via the built-in `view_skill` tool. Requires `capabilities.builtin_tools: true` and non-legacy `function_calling` on the model (both already set on `azure-devops-advisor`).

Source files for all 11 skills live in `skills/` in the repo, one markdown file per skill (`Name: ...` / `Description: ...` header, then `---`, then the content body). 9 of them contain customer-specific content and are tracked as `.md.template` (with a `{{CUSTOMER_NAME}}` placeholder) — run `./scripts/render-templates.sh` after editing `.env` or a template to produce the real, gitignored `.md` file actually consumed below. `obsidian-vault-usage` and `knowledge-graph-memory` have no customer-specific content and are plain tracked `.md` files. Not auto-synced to the DB — edit the file (or template + re-render), then re-POST it (see below).

| Skill | Purpose |
|---|---|
| `zero-trust-landing-zone-review` | Intra-spoke security checklist (Doc 6) |
| `genai-ai-foundry-security-review` | OWASP-LLM-mapped review for the AI Foundry + ACA/AKS stack (Docs 5, 8, 9) |
| `regulatory-impact-triage` | DORA/NIS2/AI Act/GDPR/DNB/EBA applicability walkthrough (Doc 4) |
| `bicep-terraform-migration-playbook` | Migration execution playbook (Doc 2) |
| `aca-aks-decision-framework` | Compute platform choice + networking requirements (Doc 9) |
| `devops-pipeline-review` | CI/CD pipeline checklist (Doc 3) |
| `design-decision-log` | House-style numbered decision + open-`Q:` log format |
| `raci-stakeholder-table` | House-style RACI table + scope-isolation + strategic-observation format |
| `gotchas-log` | House-style four-part friction-point log format |
| `knowledge-graph-memory` | MCP memory-graph write/read instructions (moved out of the system prompt) |
| `obsidian-vault-usage` | MCP vault search instructions (moved out of the system prompt) |

**Creating/updating a skill** (no UI flow scripted yet — needs a personal API key from Settings → Account → API Keys):

```sh
curl -s -X POST http://localhost:3042/api/v1/skills/create \
  -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" \
  -d '{"id": "<kebab-case-id>", "name": "<kebab-case-id>", "description": "...", "content": "...", "meta": {"tags": []}, "is_active": true}'
# to update an existing one instead: POST /api/v1/skills/id/<id>/update with the same body
```

Attaching to a model: `GET /api/v1/models/model?id=azure-devops-advisor`, set `meta.skillIds` to the full desired list, `POST` the whole object back to `/api/v1/models/model/update` (the endpoint expects the complete `ModelForm`, not a partial patch).

`bootstrap/azure_devops_advisor.py` attaches these skills via `meta.skillIds` when creating/updating the model (kept in sync as of 2026-08-05 — see **Custom model** above). It does not create skills that don't already exist — create/update each skill via the API first (see above), then run the bootstrap script to attach them to the model.

## Ollama configuration

Ollama runs on the host (not in Docker). Key settings are applied via launchd env vars at login.

**LaunchAgent:** `~/Library/LaunchAgents/com.<youruser>.ollama-env.plist` sets at login:

| Env var | Value | Effect |
|---|---|---|
| `OLLAMA_KEEP_ALIVE` | `-1` | Models never auto-unload from memory |
| `OLLAMA_NO_CLOUD` | `true` | Disables Ollama cloud inference and web search features |

These env vars take effect when Ollama.app is launched. If you restart the Mac or relaunch Ollama, they will be applied automatically. After any settings change, quit and reopen Ollama from the menu bar.

**OpenWebUI also injects `keep_alive: -1`** per request via `DEFAULT_MODEL_PARAMS` — so models stay loaded even if the env var hasn't taken effect yet.

**Other useful Ollama env vars** (add to the plist if needed):
- `OLLAMA_CONTEXT_LENGTH` — override default context window globally (currently auto-detected; qwen2.5:14b uses 32768)
- `OLLAMA_NUM_PARALLEL` — max parallel requests (default 1, fine for single-user)
- `OLLAMA_MAX_LOADED_MODELS` — max models loaded simultaneously

## OpenWebUI database settings

These settings are stored in OpenWebUI's database, not in env vars or compose config. Manage via API or UI. They survive `docker compose down` but are wiped by `docker compose down -v`.

| Setting | Value | Where |
|---|---|---|
| Default model | `qwen2.5:14b` (update after new downloads) | `POST /api/v1/configs/models` |
| Task model (titles, tags, etc.) | `` (empty = use chat model) | `POST /api/v1/tasks/config/update` |
| Default model params | `{"keep_alive": "-1"}` | `POST /api/v1/configs/models` |
| Hybrid RAG search (BM25+semantic) | enabled | `POST /api/v1/retrieval/config` |
| RAG TOP_K | 15 | `POST /api/v1/retrieval/config` |
| RAG relevance threshold | 0.2 | `POST /api/v1/retrieval/config` |
| Web search engine | `searxng` | `POST /api/v1/retrieval/config` |
| Web search URL | `http://searxng-pii-proxy:8080/search?q=<query>` | `POST /api/v1/configs/rag` — see **SearXNG PII redaction** above |
| Web search results | 5 | `POST /api/v1/retrieval/config` |
| Community sharing | disabled | `POST /api/v1/auths/admin/config` |
| User signup | disabled | `POST /api/v1/auths/admin/config` |

**To re-apply after a volume wipe:** Re-run the API commands above. The tool server connections (MCPO) also need re-applying — see the MCPO section.

## Security

Threat model: fully local use. OpenWebUI is the only intended LAN-facing surface.

- **Port bindings**: all services, including OpenWebUI, bind to `127.0.0.1` only. Remote access goes through Tailscale/SSH tunnel, not a directly exposed port.
- **MCPO API key**: tool invocations require `Authorization: Bearer <key>` (stored in `secrets/mcpo_api_key`). OpenAPI schema endpoints are intentionally public for client discovery. When connecting OpenWebUI to MCPO, provide the key in the tool connection settings.
- **Filesystem MCP scope**: read-only access to the repo root only (mounted as `.:/docker/openwebui:ro`) — narrowed from the broader `~/docker` parent directory, which unnecessarily exposed sibling projects. This project's own `secrets/` is still technically reachable within that root; the tool is currently **not attached** to any model's `toolIds`, which is the primary control against exposure. If it's ever attached, revisit whether `secrets/` needs to move outside this root first.
- **SearXNG network isolation**: `searxng` is on its own `searxng_internal` Docker network, joined only by `searxng` and `searxng-pii-proxy`. This closes a PII-leak path that config alone couldn't: `mcpo`'s generic `web_fetch` MCP tool could otherwise be pointed at `searxng` directly by the LLM at runtime, bypassing the Presidio redaction wired into OpenWebUI's search-URL setting. See **SearXNG PII redaction** above.

## Gotchas

- **`VECTOR_DB=chroma`** in `.env` — this is the correct value for OpenWebUI's env var. Do not change it to `chromadb` (the compose default is misleading).
- **Web search engine and URL are database-backed** — `WEB_SEARCH_ENGINE` and `SEARXNG_QUERY_URL` are stored in OpenWebUI's database, not in env vars. `RAG_WEB_SEARCH_ENGINE` and `RAG_WEB_SEARCH_URL` are not recognised env var names and have no effect. Manage these settings via Admin Panel → Settings → Web Search or the `/api/v1/configs/rag` API. Current values: engine `searxng`, URL `http://searxng-pii-proxy:8080/search?q=<query>` (repointed from `searxng` directly — see **SearXNG PII redaction**), result count 5, relevance threshold 0.2.
- **searxng-pii-proxy fails closed** — if Presidio (analyzer or anonymizer) is unreachable, times out, or errors, the proxy returns `503` rather than forwarding the raw (possibly PII-containing) query to SearXNG. Web search stops working during a Presidio outage; that's intentional, not a bug. See `searxng-pii-proxy/README.md`.
- **Presidio's default recognizers are US/English-tuned** — NL/EU phone numbers and national ID formats may not be caught by `presidio-analyzer`'s default entity recognizers. Known detection-coverage gap, relevant given this stack's Dutch-context use.
- **Presidio image digests are unpinned** (`mcr.microsoft.com/presidio-analyzer:latest` / `presidio-anonymizer:latest`) — unlike every other image in `compose.yaml`. Resolve to a specific `sha256` digest via `docker pull` + `docker inspect` and pin it, matching the rest of the file's convention.
- **Secrets use Docker Compose secrets** — `WEBUI_SECRET_KEY`, `HF_TOKEN`, `OPEN_TERMINAL_API_KEY`, and `MCPO_API_KEY` are stored as files in `secrets/` and mounted via Docker secrets. The entrypoint wrapper (`docker-entrypoint.sh`) reads them and exports them as env vars before starting the app. To rotate a secret, edit the file in `secrets/` and run `docker compose up -d` to recreate the container.
- **`host.docker.internal` only works on Docker Desktop** (macOS/Windows). On Linux, use `host` network mode or `172.17.0.1`.
- **MCPO config** mounts `VAULT_HOST_PATH` (`.env`) as `/vault:ro` and the repo root as `/docker/openwebui:ro` (narrowed from the whole `~/docker` tree). The `obsidian` MCP server uses `@bitbonsai/mcpvault` to serve vault notes. Client scoping: this vault should contain only material relevant to the configured `CUSTOMER_NAME` — a broader personal vault mixing multiple contexts should not be mounted here, so neither the Obsidian MCP tool nor RAG ingestion can see notes outside the intended scope.
- **mcpo-memory has no built-in backup.** `backup_memory.sh` + a daily launchd agent (e.g. `com.<youruser>.openwebui.memory-backup`) copy `memory.json` out of the volume daily at 03:30, into `memory_backups/`, so agent memory survives `docker compose down -v`.
- **Hardware**: M4 Pro, 24GB RAM. Containers have `deploy.resources.limits` set (ChromaDB: 2g, OpenWebUI: 1g, MCPO/SearXNG/Open Terminal/searxng-pii-proxy/presidio-anonymizer: 512m each, presidio-analyzer: 1.5g for its spaCy model) to prevent Docker from starving Ollama when loading large models (e.g., qwen3:30b at 23GB). Adding Presidio pushes the Docker-side budget to roughly 7-8g — validate with `docker stats` under real load; these limits are starting estimates, not measured values.
- **SearXNG config** is a bind-mount (`./searxng/`); `settings.yml` is gitignored (it holds a live `secret_key`) — copy it from `searxng/settings.yml.example` on a fresh clone. A named volume caused permission errors on first run because the container drops all capabilities except CHOWN/SETGID/SETUID.
- **Ingestion chunk IDs** are MD5 hashes of `source path + text`. A chunk is skipped (with a warning) if Ollama returns a 500 during embedding — this happens with a small number of oversized chunks.
- **`nomic-embed-text` must be pulled in Ollama** before running ingestion. Verify with `ollama list`.
- **`GET /api/v1/knowledge/{id}` does not return `files`** — that field is only populated by the create/update/file-add/file-update/file-remove handlers, not the plain get-by-id one. To list a knowledge base's current files (e.g. to check what's already uploaded before adding more), use `GET /api/v1/knowledge/{id}/files` instead (paginated, `items` list). Calling the wrong endpoint silently returns an empty list rather than erroring — see `bootstrap/sync_knowledge.py`'s `existing_files_by_name`.
- **Hand-rolled multipart uploads to `POST /api/v1/files/` can produce empty extracted content** even when the file bytes are stored correctly (`meta.size` matches, `data.status` reports `"completed"`, no error) — observed with a manually-encoded multipart body against this instance's configured content-extraction engine; root cause not pinned down. Don't rely on upload-time extraction for anything scripted: upload with `?process=false` to skip extraction entirely, then set real content via `POST /files/{id}/data/content/update` (`{"content": "..."}`), which calls `process_file` with the content given directly rather than extracted — used for both new and existing files in `bootstrap/sync_knowledge.py`.

## Files

| File                                                      | Purpose                                                                                      |
|-----------------------------------------------------------|----------------------------------------------------------------------------------------------|
| `compose.yaml`                                            | Active compose config (healthchecks, port mappings, Docker secrets, memory limits, pinned image digests, `owui_net`/`searxng_internal` networks) |
| `.env`                                                    | Non-secret environment variables, including identity/branding (`CUSTOMER_NAME`, `PROJECT_NAME`, `INDUSTRY`) and `VAULT_HOST_PATH` |
| `.env.example`                                             | Tracked template for `.env` — copy and fill in your own values                               |
| `scripts/render-templates.sh`                              | Renders `skills/*.md.template` → `skills/*.md` by substituting `.env` values — see [First-time setup](#first-time-setup) |
| `secrets/`                                                | Docker secret files (gitignored except `README.md`) — see [First-time setup](#first-time-setup) |
| `docker-entrypoint.sh`                                    | Reads `/run/secrets/*` and exports as env vars before exec-ing the app                      |
| `mcpo_config.json`                                        | MCP server definitions for MCPO                                                              |
| `searxng/settings.yml.example`                             | SearXNG config template — copy to `searxng/settings.yml` (gitignored, holds a live `secret_key`) |
| `searxng-pii-proxy/`                                       | PII redaction proxy in front of SearXNG (Presidio-based) — see **SearXNG PII redaction** above and `searxng-pii-proxy/README.md` |
| `ingestion/`                                              | Vault ingestion pipeline — Dockerfile + script to chunk & embed Obsidian vault into ChromaDB |
| `bootstrap/azure_devops_advisor.py`                        | Creates/updates the `azure-devops-advisor` model (prompt, tools, skills, capabilities, knowledge collection reference) |
| `bootstrap/sync_knowledge.py`                              | Syncs vault `Knowledge/` docs + `What's new in 2026.md` into the OpenWebUI `CUSTOMER_NAME` Knowledge collection (RAG content) |
| `skills/`                                                 | Source markdown for the 11 Skills attached to the custom model — 9 are `.md.template` (rendered via `scripts/render-templates.sh`, real output gitignored), 2 (`obsidian-vault-usage`, `knowledge-graph-memory`) are plain tracked files — see **Skills** below |
| `backup_memory.sh`                                        | Copies `memory.json` out of the `mcpo-memory` volume into `memory_backups/`, pruning backups older than 30 days |
| `memory_backups/`                                         | Daily backups of the memory-server's knowledge graph (JSONL, gitignored)                     |
| `~/Library/LaunchAgents/com.<youruser>.openwebui.ingestion.plist` | launchd agent for daily scheduled ingestion at 03:00 (lives outside this repo, name it however you like) |
| `~/Library/LaunchAgents/com.<youruser>.openwebui.memory-backup.plist` | launchd agent for daily `backup_memory.sh` run at 03:30 (lives outside this repo) |
| `~/Library/LaunchAgents/com.<youruser>.ollama-env.plist`      | launchd agent that sets Ollama env vars at login (keep-alive, no-cloud; lives outside this repo) |
| `CLAUDE.md`                                               | Pointer for Claude Code sessions to this file (kept generic for Claude Code + OpenCode)      |
| `LICENSE`                                                 | MIT license (repo is private; applies if it's ever made public or forked)                    |
| `.gitignore`                                              | Excludes secrets, live SearXNG/env config, memory backups, ingestion logs, rendered skill files, and local Claude Code overrides |

## Version control

Tracked in a private GitHub repo. Secrets, `.env`, the live `searxng/settings.yml`, rendered `skills/*.md` (see **Skills**), `memory_backups/`, `ingestion.log`, and `.claude/settings.local.json` are all gitignored — see **First-time setup** above for what to regenerate on a fresh clone.

## References

| Project        | URL                                                          |
|----------------|--------------------------------------------------------------|
| OpenWebUI      | <https://github.com/open-webui/open-webui/tree/main>         |
| OpenWebUI Docs | <https://docs.openwebui.com/>                                |
| MCPO           | <https://github.com/open-webui/mcpo>                         |
| Open Terminal  | <https://github.com/open-webui/open-terminal>                |
| SearXNG        | <https://github.com/searxng/searxng-docker>                  |
