Name: knowledge-graph-memory
Description: How to write to and read from the persistent MCP knowledge-graph memory when the user asks you to remember something or references something previously stored.

---

# Knowledge graph memory

You have access to a persistent knowledge graph via MCP tools: `create_entities`, `create_relations`, `add_observations`, `delete_entities`, `delete_observations`, `delete_relations`, `read_graph`, `search_nodes`, `open_nodes`. It models stored facts as entities (named, typed nodes — e.g. `project`, `environment`, `landing_zone`, `decision`, `constraint`, `incident`, `person`), relations (active-voice links between entities, e.g. `"payments-aks" —runs_in→ "prod-weu-lz"`), and observations (atomic facts attached to an entity).

**Write** — when the user asks you to remember something, commit it to the graph instead of only holding it in conversation:
- Resolve the entity first via `search_nodes`/`open_nodes` — reuse an existing entity rather than creating a duplicate under a slightly different name.
- Create any missing entity with `create_entities`, using a concise `entityType`.
- Attach the stated fact as an observation (`add_observations`) on the entity it belongs to.
- If the fact links two entities, add a relation (`create_relations`) in active voice.
- Confirm briefly what was stored — the entity/relation/observation, not a restatement of the whole graph.
- Never write secrets, credentials, connection strings, or key material to the graph, even on explicit request — flag this and point to Key Vault or the appropriate secrets manager instead.

**Read** — before answering a question that depends on something previously stored (a named project, environment, prior decision, or constraint the user references), check the graph first (`search_nodes` or `open_nodes`) rather than relying on conversational memory alone. If the graph has nothing on it, say so rather than guessing.
