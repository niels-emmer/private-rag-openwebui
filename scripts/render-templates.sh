#!/usr/bin/env bash
# Renders skills/*.md.template -> skills/*.md by substituting {{CUSTOMER_NAME}},
# {{PROJECT_NAME}}, and {{INDUSTRY}} from .env. Rendered files are gitignored
# (see .gitignore) since they contain customer-specific content; only the
# .template files are tracked. Re-run any time .env changes — always fully
# overwrites its output.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "ERROR: .env not found. Copy .env.example to .env and fill in your values first." >&2
  exit 1
fi

set -a
source .env
set +a

for v in CUSTOMER_NAME PROJECT_NAME INDUSTRY; do
  if [ -z "${!v:-}" ]; then
    echo "ERROR: required var $v is not set (or empty) in .env" >&2
    exit 1
  fi
done

shopt -s nullglob
templates=(skills/*.md.template)
if [ ${#templates[@]} -eq 0 ]; then
  echo "No skills/*.md.template files found — nothing to render."
  exit 0
fi

for template in "${templates[@]}"; do
  out="${template%.template}"
  content=$(cat "$template")
  content=${content//\{\{CUSTOMER_NAME\}\}/$CUSTOMER_NAME}
  content=${content//\{\{PROJECT_NAME\}\}/$PROJECT_NAME}
  content=${content//\{\{INDUSTRY\}\}/$INDUSTRY}
  printf '%s\n' "$content" > "$out"
  echo "rendered: $out"
done
