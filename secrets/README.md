# Secrets

Docker Compose secrets, mounted read-only into containers at `/run/secrets/*` and exported as env vars by `docker-entrypoint.sh`. This directory's other contents are gitignored — only this README is tracked.

Create each file with a single line, no trailing newline needed:

| File | Used by | How to generate |
|---|---|---|
| `webui_secret_key` | OpenWebUI (`WEBUI_SECRET_KEY`) | `openssl rand -hex 32` |
| `mcpo_api_key` | mcpo (`MCPO_API_KEY`, bearer auth for tool calls) | `openssl rand -hex 32` |
| `open_terminal_api_key` | Open Terminal (`OPEN_TERMINAL_API_KEY`) | `openssl rand -hex 32` |
| `hf_token` | OpenWebUI (`HF_TOKEN`, for gated HuggingFace models) | Personal access token from <https://huggingface.co/settings/tokens> |

```sh
for f in webui_secret_key mcpo_api_key open_terminal_api_key; do
  openssl rand -hex 32 > "secrets/$f"
done
echo "your-hf-token" > secrets/hf_token
```

To rotate a secret later, overwrite the file and run `docker compose up -d` to recreate the affected container(s).
