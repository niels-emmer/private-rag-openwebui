# Security Policy

## Supported versions

This is a personal, self-hosted infrastructure project rather than a versioned library — there is no release/support matrix. Security fixes are applied to the `main` branch only. Always run the latest `main`.

## Threat model

This stack is designed for **fully local, single-user use**. See [`AGENTS.md`](../AGENTS.md#security) for the current threat model in detail. In short:

- OpenWebUI is the only service intended to be reachable beyond the host itself, and even then only via Tailscale/SSH tunnel — every container binds to `127.0.0.1` by default. Do not expose ports publicly without understanding the implications.
- Secrets (`WEBUI_SECRET_KEY`, `MCPO_API_KEY`, `OPEN_TERMINAL_API_KEY`, `HF_TOKEN`) are provided as Docker Compose secrets under `secrets/`, which is gitignored. Never commit real secret values.
- MCP tool calls through MCPO require a bearer token; the OpenAPI schema endpoints are intentionally public for client discovery only.
- Web search is routed through a network-isolated SearXNG instance behind a PII-redaction proxy (Microsoft Presidio) that fails closed — see [`searxng-pii-proxy/README.md`](../searxng-pii-proxy/README.md).

If you deploy this stack in a different trust environment (multi-user, LAN-exposed, cloud-hosted), you are responsible for re-assessing these assumptions — they are not enforced by the code itself.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Instead, use GitHub's private vulnerability reporting for this repository:

1. Go to the **Security** tab of this repository.
2. Click **Report a vulnerability** to open a private advisory.

This lets maintainers discuss and fix the issue before it's publicly disclosed. If private reporting is unavailable, contact the maintainer via their GitHub profile ([@niels-emmer](https://github.com/niels-emmer)).

Please include:
- A description of the vulnerability and its potential impact.
- Steps to reproduce (config, commands, request payloads, etc.).
- Any relevant logs or output (redact anything sensitive first).

## Known, accepted risk areas

Tracked openly rather than treated as vulnerabilities, since they're documented trade-offs:

- **Presidio's default recognizers are US/English-tuned** — non-US phone number and national ID formats may not be redacted from web-search queries. See [`AGENTS.md`](../AGENTS.md#gotchas).
- **Presidio image digests are currently unpinned** (`:latest`) in `compose.yaml`, unlike every other image in the stack — tracked as a TODO there.
- **The `filesystem` MCP tool** is scoped read-only to the repo root but is not attached to any model by default; if you attach it, revisit whether `secrets/` needs to move outside that root first.
