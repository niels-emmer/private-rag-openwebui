# Contributing

Thanks for your interest in this project. It started as a personal, self-hosted OpenWebUI + ChromaDB stack and was generalized for public use, so contributions are welcome but the project intentionally stays small and opinionated.

## Before you start

- For anything non-trivial (new services, architectural changes, new dependencies), please open an issue first to discuss the approach before writing code — this avoids wasted work on changes that don't fit the project's local-first, single-user scope.
- For small fixes (typos, doc corrections, obvious bugs), a pull request without a prior issue is fine.
- Read [`AGENTS.md`](../AGENTS.md) first — it's the maintained source of truth for architecture, commands, and gotchas, and is written to be actionable for both humans and AI coding agents (Claude Code, OpenCode, etc.).

## Development setup

Follow the [Getting started](../README.md#getting-started) section of the README to bring up the stack locally. You'll need Docker, Docker Compose, and Ollama running on the host.

## Making changes

- Keep changes scoped — this repo favors small, focused pull requests over large ones.
- If you touch `compose.yaml`, `AGENTS.md`, or `ingestion/README.md`, keep the docs in sync with the change (see the maintenance rule at the top of `AGENTS.md`).
- Match the existing style: no unnecessary abstractions, no speculative configuration options, comments only where the *why* isn't obvious from the code.
- If you change the `searxng-pii-proxy` service, run its test suite:
  ```sh
  cd searxng-pii-proxy
  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
  .venv/bin/pytest -v
  ```
- Never commit real secrets, API keys, `.env`, or a live `searxng/settings.yml` — all are gitignored for a reason. Double-check `git status`/`git diff` before pushing.

## Submitting a pull request

1. Fork the repo and create a branch from `main`.
2. Make your changes, keeping commits focused and well-described.
3. Fill out the pull request template — it asks what changed, why, and how it was tested.
4. Open the PR against `main`. A maintainer will review and may ask for changes.

## Reporting bugs and requesting features

Use the issue templates under **Issues → New issue**. For security vulnerabilities, do **not** open a public issue — see [`SECURITY.md`](./SECURITY.md) instead.

## Code of conduct

This project follows the [Contributor Covenant](./../CODE_OF_CONDUCT.md). By participating, you're expected to uphold it.
