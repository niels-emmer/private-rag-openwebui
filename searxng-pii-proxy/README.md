# SearXNG PII Redaction Proxy

Sits between OpenWebUI and SearXNG. Redacts PII (names, emails, phone numbers,
locations, etc.) from the `q` search parameter via Microsoft Presidio before
forwarding the request to SearXNG, so raw customer PII never reaches the
external search engines SearXNG queries.

## Files

| File | Purpose |
|------|---------|
| `Dockerfile` | Python 3.12-slim image running the proxy via uvicorn |
| `app.py` | FastAPI app implementing `/search`, calling Presidio, forwarding to SearXNG |
| `requirements.txt` | Pinned deps (`fastapi`, `httpx`, `uvicorn`) plus test-only `pytest`/`respx` |
| `tests/test_pii_anonymizer.py` | Unit tests, Presidio calls mocked via `respx` |

## How it works

1. Receives `GET`/`POST /search` (the only endpoint any caller in this stack
   needs — OpenWebUI's built-in web search hits exactly this path).
2. Sends the `q` parameter to Presidio Analyzer's `/analyze` endpoint to
   detect PII entities.
3. If entities are found, sends `q` + the detected entities to Presidio
   Anonymizer's `/anonymize` endpoint, which returns the text with entities
   replaced by `<ENTITY_TYPE>` placeholders (e.g. `<PERSON>`, `<EMAIL_ADDRESS>`).
4. Forwards the request to the real SearXNG container with `q` replaced by
   the redacted text — all other params (`format`, `categories`, `language`,
   `pageno`, etc.) pass through unchanged.
5. Returns SearXNG's response back to the caller unmodified.

**Fails closed.** If Presidio (analyzer or anonymizer) is unreachable, times
out, or errors, the raw query is never forwarded to SearXNG — the proxy
returns `503` and logs the failure instead. This means web search stops
working during a Presidio outage; that tradeoff is intentional for a
PII-leak-prevention control.

Why this proxy exists instead of just changing OpenWebUI's search URL
directly to SearXNG: OpenWebUI's built-in web search is the primary path to
SearXNG, but `mcpo`'s generic `web_fetch` MCP tool could otherwise reach
`searxng` directly and bypass any redaction — see the network segmentation
(`searxng_internal` network) described in `AGENTS.md`, which makes `searxng`
unreachable from anywhere except this proxy.

## Configuration

All settings are env vars with defaults that match the compose stack:

| Variable | Default | Description |
|----------|---------|-------------|
| `PRESIDIO_ANALYZER_URL` | `http://presidio-analyzer:3000` | Presidio Analyzer service base URL |
| `PRESIDIO_ANONYMIZER_URL` | `http://presidio-anonymizer:3000` | Presidio Anonymizer service base URL |
| `SEARXNG_URL` | `http://searxng:8080` | Real SearXNG service base URL |
| `PRESIDIO_TIMEOUT_SECONDS` | `5` | Timeout per Presidio call before failing closed |

## Running tests

```sh
cd searxng-pii-proxy
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/pytest -v
```

## Gotchas

- **US/English-tuned detection.** Presidio's default recognizers are tuned
  for US formats (e.g. `US_SSN`, US phone numbers). NL/EU phone numbers and
  national ID numbers may not be caught by default — this is a
  detection-coverage gap to be aware of for a Dutch-context deployment, not
  something this proxy compensates for.
- **Only `/search` is implemented.** This is deliberately not a general
  reverse proxy for all of SearXNG's paths (`/`, `/config`,
  `/autocompleter`, etc.) — nothing in this stack calls those, and adding
  them would be unnecessary surface area for a single-purpose control.
- **Presidio image digests are unpinned in `compose.yaml`** (`:latest`) pending
  resolution to a specific `sha256` digest, unlike every other image in this
  stack — see the TODO in `compose.yaml`.
