#!/usr/bin/env python3
"""
Bootstrap script for the Azure DevOps Advisor custom model.

Run after a `docker compose down -v` to recreate the model with its
tools, knowledge, capabilities, and system prompt.

Usage:
    python3 bootstrap/azure_devops_advisor.py

Requires:
    - OpenWebUI running at http://localhost:3042
    - .env sourced (CUSTOMER_NAME, INDUSTRY)
    - The knowledge collection named after CUSTOMER_NAME (.env) already
      created in OpenWebUI
    - Admin credentials (prompted if OWUI_EMAIL/OWUI_PASSWORD not set)

The system prompt is loaded from system-prompt.md (repo root) at run time —
that file is the single source of truth; do not hardcode a copy here.
"""

import json
import os
import sys
import urllib.request
import urllib.error

BASE_URL = "http://localhost:3042"
CUSTOMER_NAME = os.environ["CUSTOMER_NAME"]
INDUSTRY = os.environ.get("INDUSTRY", "Dutch financial services")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SYSTEM_PROMPT_PATH = os.path.join(SCRIPT_DIR, "..", "system-prompt.md")

with open(SYSTEM_PROMPT_PATH, encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read().rstrip("\n")

# Desired model definition — knowledge ID is resolved at runtime by name.
MODEL = {
    "id": "azure-devops-advisor",
    "base_model_id": "qwen3:30b-a3b",
    "name": "Azure DevOps Advisor",
    "params": {
        "system": SYSTEM_PROMPT,
        "function_calling": "native",
    },
    "meta": {
        "description": f"Principal DevOps Engineer & Azure Solutions Architect for {INDUSTRY}. Zero Trust, IaC, MLOps, regulatory compliance.",
        "capabilities": {
            "file_context": True,
            "vision": True,
            "file_upload": True,
            "web_search": True,
            "image_generation": True,
            "code_interpreter": True,
            "terminal": False,
            "citations": True,
            "status_updates": True,
            "memory": False,
            "builtin_tools": True,
        },
        # Knowledge collections attached to the model (resolved by name at runtime).
        "knowledge_names": [
            CUSTOMER_NAME,
        ],
        "toolIds": [
            "server:memory",
            "server:web_fetch",
            # Read/search-only slice of the obsidian server (9 of 16 tools) —
            # keeps tool count down for qwen3 tool-calling reliability, see
            # obsidian-vault-usage skill and the qwen3:14b tool-calling gotcha.
            "server:obsidian|tool_read_note_post,tool_search_notes_post,tool_list_directory_post,"
            "tool_read_multiple_notes_post,tool_get_notes_info_post,tool_get_frontmatter_post,"
            "tool_get_vault_stats_post,tool_list_all_tags_post,tool_wiki_link_post",
        ],
        "defaultFeatureIds": [
            "web_search",
            "code_interpreter",
        ],
        "skillIds": [
            "zero-trust-landing-zone-review",
            "genai-ai-foundry-security-review",
            "regulatory-impact-triage",
            "bicep-terraform-migration-playbook",
            "aca-aks-decision-framework",
            "devops-pipeline-review",
            "design-decision-log",
            "raci-stakeholder-table",
            "gotchas-log",
            "knowledge-graph-memory",
            "obsidian-vault-usage",
        ],
        "builtinTools": {
            "time": False,
            "knowledge": False,
            "chats": False,
            "subagents": False,
            "memory": False,
            "notes": False,
            "tasks": False,
            "automations": False,
            "calendar": False,
            "notifications": False,
        },
    },
    "access_grants": [],
    "is_active": True,
}


def api(method, path, payload=None, token=None):
    url = BASE_URL + path
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"HTTP {e.code} on {method} {path}: {body[:200]}", file=sys.stderr)
        raise


def signin(email, password):
    result = api("POST", "/api/v1/auths/signin", {"email": email, "password": password})
    return result["token"]


def resolve_knowledge(token, names):
    resp = api("GET", "/api/v1/knowledge/", token=token)
    collections = resp if isinstance(resp, list) else resp.get("items", resp.get("data", []))
    index = {c["name"]: c["id"] for c in collections}
    resolved = []
    for name in names:
        if name not in index:
            print(f"  WARNING: knowledge collection '{name}' not found — skipping.")
            continue
        resolved.append({
            "id": index[name],
            "name": name,
            "type": "collection",
            "description": next((c.get("description", "") for c in collections if c["name"] == name), ""),
        })
    return resolved


def create_or_update(token, model_def):
    model_id = model_def["id"]
    try:
        existing = api("GET", f"/api/v1/models/model?id={model_id}", token=token)
    except urllib.error.HTTPError:
        existing = None

    if existing:
        print(f"  Model '{model_id}' exists — updating.")
        return api("POST", "/api/v1/models/model/update", model_def, token=token)
    else:
        print(f"  Model '{model_id}' not found — creating.")
        return api("POST", "/api/v1/models/create", model_def, token=token)


def main():
    email = os.environ.get("OWUI_EMAIL") or input("OpenWebUI email: ")
    password = os.environ.get("OWUI_PASSWORD") or input("OpenWebUI password: ")

    print("Signing in...")
    token = signin(email, password)

    print("Resolving knowledge collections...")
    knowledge = resolve_knowledge(token, MODEL["meta"].pop("knowledge_names"))
    MODEL["meta"]["knowledge"] = knowledge
    for k in knowledge:
        print(f"  '{k['name']}' → {k['id']}")

    print("Applying model definition...")
    result = create_or_update(token, MODEL)
    print(f"  id:            {result['id']}")
    print(f"  name:          {result['name']}")
    print(f"  base_model_id: {result['base_model_id']}")
    print(f"  tools:         {result['meta'].get('toolIds', [])}")
    print(f"  skills:        {result['meta'].get('skillIds', [])}")
    print(f"  knowledge:     {[k['name'] for k in result['meta'].get('knowledge', [])]}")
    print(f"  defaults:      {result['meta'].get('defaultFeatureIds', [])}")
    print(f"  func_calling:  {result['params'].get('function_calling')}")
    print("Done.")


if __name__ == "__main__":
    main()
