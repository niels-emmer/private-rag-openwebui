## What does this change?

<!-- A concise description of what changed and why. Link any related issue. -->

Fixes #

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Documentation (`README.md`, `AGENTS.md`, service-level `README.md`s)
- [ ] Infrastructure / `compose.yaml` change
- [ ] Other (describe above)

## How was this tested?

<!-- What did you run, and against what? e.g. `docker compose up -d` locally,
     `pytest` in searxng-pii-proxy, a manual ingestion run, etc. -->

## Checklist

- [ ] I read [`CONTRIBUTING.md`](./CONTRIBUTING.md) and [`AGENTS.md`](../AGENTS.md).
- [ ] I updated `AGENTS.md` / `ingestion/README.md` / other docs if this change affects them (see the maintenance rule at the top of `AGENTS.md`).
- [ ] I did not commit secrets, `.env`, or a live `searxng/settings.yml`.
- [ ] If I changed `searxng-pii-proxy`, I ran its test suite (`pytest -v`).
- [ ] If I changed an image reference in `compose.yaml`, I pinned it to a `sha256` digest, matching the existing convention.
