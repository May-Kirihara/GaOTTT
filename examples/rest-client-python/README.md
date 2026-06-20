# examples/rest-client-python

Minimal Python client for the GaOTTT **REST API**, for when you want to
give your own application (running in a separate process / repo / host)
a long-term-memory backend **without** going through MCP.

This is the simplest way to embed GaOTTT into a non-LLM application:
a Python service that reads/writes a project-scoped knowledge space.

## Files

| File | Purpose |
|---|---|
| `gaottt_client.py` | Drop-in client class. ~250 LOC, single dependency (`httpx`). |
| `example_usage.py` | Six-scenario walkthrough (remember/recall, bulk index, tag filter, relations, reflect, forget/restore). |
| `run_local_server.sh` | Boots a local REST server against an isolated `/tmp` DB so you can poke without touching production memory. |
| `requirements.txt` | Just `httpx`. |

## Quick start

Terminal 1 — start an isolated server (does NOT touch your real memory):

```bash
bash examples/rest-client-python/run_local_server.sh
# → http://localhost:8001/docs
```

Terminal 2 — run the demo:

```bash
.venv/bin/python examples/rest-client-python/example_usage.py
```

Both scripts are safe to re-run; the server deduplicates identical
content.

## Point the client at a remote / production server

```python
from gaottt_client import GaOTTTClient

client = GaOTTTClient(
    base_url="https://gaottt.myapp.example.com",
    api_key="sk_...",        # only if you've put an auth proxy in front
    timeout=30.0,
)
```

The stock GaOTTT REST server has **no auth and no TLS**. For anything
beyond localhost, put Caddy / nginx / Cloudflare Tunnel in front of it
and pass the proxy's bearer token as `api_key=` here.

## Running multiple isolated knowledge spaces

Each backend process binds to its own `GAOTTT_DATA_DIR`, giving you
hard process-level isolation. Spin up as many as you need:

```bash
# Space A — "myapp"
GAOTTT_DATA_DIR=/srv/gaottt/myapp \
  python -m uvicorn gaottt.server.app:app --host 0.0.0.0 --port 8001 &

# Space B — "client-A"  (completely separate DB, FAISS, gravity field)
GAOTTT_DATA_DIR=/srv/gaottt/client-A \
  python -m uvicorn gaottt.server.app:app --host 0.0.0.0 --port 8002 &
```

```python
myapp = GaOTTTClient("http://gaottt-host:8001")
client_a = GaOTTTClient("http://gaottt-host:8002")

myapp.remember("myapp secret sauce ...")
client_a.recall("secret sauce")   # → no hits (different process, different DB)
```

Each process loads its own copy of the RURI embedding model (~1.5 GB
RAM). 10+ concurrent spaces → consider the engine-pool design (Phase MT-1)
instead of N processes.

## Available methods

Full docstrings in `gaottt_client.py`. Highlights:

| Method | Endpoint | Purpose |
|---|---|---|
| `remember(content, ...)` | `POST /remember` | Store one memory |
| `recall(query, ...)` | `POST /recall` | Gravity-biased retrieval (default) |
| `query(text, ...)` | `POST /query` | Legacy raw-FAISS search (no gravity) |
| `explore(query, ...)` | `POST /explore` | Serendipity / dormant exploration |
| `index(documents)` | `POST /index` | Bulk insert pre-chunked docs |
| `forget(ids)` / `restore(ids)` | `POST /forget` / `/restore` | Soft archive + undo |
| `revalidate(id)` | `POST /revalidate` | Refresh certainty decay clock |
| `relate(src, dst, type)` | `POST /relations` | Directed edge (`supersedes`, `derived_from`, `contradicts`, or custom) |
| `get_relations(id)` | `GET /relations/{id}` | List edges |
| `get_node(id)` / `get_node_detail(id)` | `GET /node/{id}[/detail]` | Physical state (+ content) |
| `reflect(aspect)` | `POST /reflect/{aspect}` | Any of: summary, hot_topics, dormant, duplicates, persona, tasks_*, ... |
| `summary()` / `hot_topics()` | (shorthands) | Most common reflect calls |
| `compact(...)` | `POST /compact` | Maintenance (TTL expiry, optional FAISS rebuild) |

For anything else (admin endpoints, `/ingest` from server-side paths,
`/ambient_recall`, ...), call the REST API directly or extend the
client — every endpoint is documented at `/docs` (Swagger UI).

## Differences from the MCP interface

| | REST | MCP |
|---|---|---|
| Use case | Application code | LLM agents (Claude Code, opencode) |
| Auth | None (add proxy) | None (add proxy) |
| Response shape | Raw Pydantic JSON | Human-readable formatted strings |
| Tool count | ~40 endpoints | ~28 tools |
| `/reset`, `/admin/*` | Available (REST-only by design) | Hidden (LLM should not reset) |

The service layer (`gaottt/services/*.py`) is shared — both transports
call the same functions. You get identical behaviour modulo formatting.

## Troubleshooting

**`ERROR: cannot reach GaOTTT server`** — server isn't up. Run
`run_local_server.sh` first, or check `GAOTTT_URL` env var.

**Recall returns 0 hits right after `remember`** — first-hit cold cache
can take a moment. The example inserts a 0.5 s sleep after bulk writes.
For one-off writes it should be instant (Phase G genesis kick).

**`/ingest` returns 404 or errors** — `/ingest` takes a **server-side
path**, not an uploaded file. For client-side content use `index()`.
See "bulk insert" in `example_usage.py` step 2.

**Want OpenAPI-generated typed clients for other languages?** Pull
`http://host:8001/openapi.json` and feed it to
[openapi-generator](https://openapi-generator.tech/) — gives you
TypeScript / Go / Rust / Java clients with full type coverage.
