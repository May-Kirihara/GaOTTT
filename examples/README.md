# examples/

End-to-end examples for embedding GaOTTT into your own software.

## rest-client-python

Minimal Python client for the GaOTTT **REST API**. Use this when you
want to give your application (running in a separate process / repo /
host) a long-term-memory backend without going through MCP.

→ [`rest-client-python/`](rest-client-python/) · [`README`](rest-client-python/README.md)

```
your app  ──HTTP──►  GaOTTT REST server  ──►  isolated knowledge space
(python)              uvicorn + FastAPI       GAOTTT_DATA_DIR=/srv/your-app
```

Quick start:

```bash
# Terminal 1: isolated server (does NOT touch production memory)
bash examples/rest-client-python/run_local_server.sh

# Terminal 2: six-scenario demo
.venv/bin/python examples/rest-client-python/example_usage.py
```

## Why REST instead of MCP?

| | REST | MCP |
|---|---|---|
| **For** | application code, services, CLIs | LLM agents (Claude Code, opencode) |
| **Auth** | none — add Caddy/nginx in front | none — add Caddy/nginx in front |
| **Response** | raw JSON (Pydantic) | human-readable strings |
| **Coverage** | ~40 endpoints (incl. admin) | ~28 tools (no destructive ops) |

Both transports share the same service layer (`gaottt/services/*.py`),
so behaviour is identical modulo formatting. The REST API is the
recommended integration point for non-LLM code.

## Isolation model

Each GaOTTT backend process loads one `GAOTTT_DATA_DIR` and keeps its
own SQLite DB, FAISS index, cache, gravity field, BM25 index, and
dream loop. **Process boundary = knowledge-space boundary = security
boundary.**

```bash
# Spin up isolated spaces by varying data_dir + port:
GAOTTT_DATA_DIR=/srv/gaottt/myapp    python -m uvicorn gaottt.server.app:app --port 8001 &
GAOTTT_DATA_DIR=/srv/gaottt/client-A python -m uvicorn gaottt.server.app:app --port 8002 &
```

This is the **PoC path** for multi-tenant / multi-repo deployments:
zero code changes, hard physical isolation. The trade-off is memory
(RURI model ~1.5 GB per process); when that becomes painful, graduate
to the planned engine-pool design (Phase MT-1 in
`docs/wiki/Plans-Roadmap.md`).

## What's next

- Full REST API reference: [`docs/wiki/REST-API-Reference.md`](../docs/wiki/REST-API-Reference.md)
- Operations / server setup: [`docs/wiki/Operations-Server-Setup.md`](../docs/wiki/Operations-Server-Setup.md)
- Tuning hyperparameters: [`docs/wiki/Operations-Tuning.md`](../docs/wiki/Operations-Tuning.md)
