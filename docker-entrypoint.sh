#!/bin/bash
# Docker secrets entrypoint wrapper
# Reads secrets from /run/secrets/ and exports them as environment variables,
# then execs the original entrypoint/command.
#
# Secret file name → env var mapping:
#   webui_secret_key       → WEBUI_SECRET_KEY
#   hf_token               → HF_TOKEN
#   open_terminal_api_key  → OPEN_TERMINAL_API_KEY
#   mcpo_api_key           → MCPO_API_KEY

set -e

# Read each known secret and export as the corresponding env var
if [ -f /run/secrets/webui_secret_key ]; then
  export WEBUI_SECRET_KEY=$(cat /run/secrets/webui_secret_key)
fi

if [ -f /run/secrets/hf_token ]; then
  export HF_TOKEN=$(cat /run/secrets/hf_token)
fi

if [ -f /run/secrets/open_terminal_api_key ]; then
  export OPEN_TERMINAL_API_KEY=$(cat /run/secrets/open_terminal_api_key)
fi

if [ -f /run/secrets/mcpo_api_key ]; then
  export MCPO_API_KEY=$(cat /run/secrets/mcpo_api_key)
fi

# Execute the original entrypoint with all arguments
exec "$@"
