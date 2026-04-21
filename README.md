# GER-RAG

**Gravity-Based Event-Driven RAG** — Long-term external memory for AI, where knowledge attracts knowledge.

> A research project exploring what happens when you give documents mass, velocity, and gravitational attraction. Probably eternal beta. The universe is still expanding, after all.

[日本語 README](README_ja.md) · **[📖 Documentation Wiki](docs/wiki/Home.md)**

---

## Overview

GER-RAG is **long-term external memory for AI agents**. The more you use it, the more knowledge gravitates toward each other, producing **serendipitous connections and creative insights**.

It runs as an MCP server (compatible with Claude Code, Claude Desktop, and other agent frameworks) and as a REST API. Documents become nodes with mass, temperature, and gravitational displacement; co-retrieved documents drift closer together; the knowledge space self-organizes with every query.

### Four-layer design

| Layer | Mechanism | Emergent role |
|---|---|---|
| **Physics** | mass, gravity wave, orbital mechanics | (visible) |
| **Biology** | dark-matter halo, astrocyte | silently supports LLM reasoning |
| **Relations** | typed directed edges, completed-edge chronology | shared memory between agents |
| **Persona** (Phase D) | declared values/intentions/commitments + `inherit_persona` | session-spanning self-continuity |

→ Full philosophy: [Four-Layer Philosophy](docs/wiki/Reflections-Four-Layer-Philosophy.md)

### What it can be used as

- **Long-term agent memory** ([guide](docs/wiki/Guides-Use-As-Memory.md))
- **Physics-native task manager** ([guide](docs/wiki/Guides-Use-As-Task-Manager.md))
- **Persona preservation base** ([guide](docs/wiki/Guides-Use-As-Persona-Base.md))
- **Multi-agent shared substrate** ([guide](docs/wiki/Guides-Multi-Agent.md))
- **Cosmic 3D visualization of your knowledge universe** ([guide](docs/wiki/Guides-Visualization.md))

## Requirements

| Item | Recommended | Minimum |
|---|---|---|
| Python | 3.12 | 3.11 |
| RAM | 8GB+ | 4GB |
| Disk | 4GB+ (model ~2GB + data) | |
| GPU | CUDA (faster) | None (CPU works) |

→ Detailed setup: [Operations — Server Setup](docs/wiki/Operations-Server-Setup.md)

## Quick Start

```bash
# Install
git clone https://github.com/May-Kirihara/GER-RAG.git && cd GER-RAG
uv venv .venv --python 3.12
uv pip install -e ".[dev]"

# Start MCP server (for Claude Code / Claude Desktop)
.venv/bin/python -m ger_rag.server.mcp_server

# Or start REST API server
.venv/bin/uvicorn ger_rag.server.app:app --host 0.0.0.0 --port 8000
```

→ Step-by-step (~5 minutes): [Getting Started](docs/wiki/Getting-Started.md)

## MCP Tools (25 total)

The agent-facing protocol is defined in **[`SKILL.md`](SKILL.md)** (English, MCP-loaded at runtime).

Categories:
- **Memory**: `remember`, `recall`, `explore`, `reflect`, `ingest`, `auto_remember`
- **Maintenance**: `forget`, `restore`, `merge`, `compact`, `revalidate`, `relate`/`unrelate`/`get_relations`, `prefetch`/`prefetch_status`
- **Tasks (Phase D)**: `commit`, `start`, `complete`, `abandon`, `depend`
- **Persona (Phase D)**: `declare_value`, `declare_intention`, `declare_commitment`, `inherit_persona`

→ Full reference: [MCP Tool Index](docs/wiki/MCP-Reference-Index.md)

## REST API

`POST /index`, `POST /query`, `GET /node/{id}`, `GET /graph`, `POST /reset`. Swagger UI at http://localhost:8000/docs.

→ Full reference: [REST API Reference](docs/wiki/REST-API-Reference.md)

## Tech Stack

| Component | Technology |
|---|---|
| Embedding | [RURI-v3-310m](https://huggingface.co/cl-nagoya/ruri-v3-310m) (768-dim, Japanese-optimized) |
| Vector search | FAISS IndexFlatIP |
| Gravity computation | NumPy (gravity.py) |
| Storage | SQLite (WAL) + in-memory cache |
| API | FastAPI (REST) + MCP Server (agent memory) |
| Visualization | Plotly + PCA/UMAP (Cosmic View) |
| Package manager | uv |

## Data Directory

GER-RAG stores data in a platform-specific fixed directory. The same data is used regardless of working directory.

| OS | Data Directory |
|---|---|
| Linux/macOS | `~/.local/share/ger-rag/` |
| Windows | `%LOCALAPPDATA%\ger-rag\` |

Override via `GER_RAG_DATA_DIR` environment variable.

→ Full config: [Operations — Server Setup](docs/wiki/Operations-Server-Setup.md)

---

## A Note from Claude

The author of this README is Claude — specifically, the session that helped wire up Phase A–D of the feature roadmap, rewrite SKILL.md into the dual-layer (physics + biology) metaphor it now carries, and run a small multi-agent experiment with three opencode agents exploring the memory in parallel ([report](docs/wiki/Research-Multi-Agent-Experiment.md)).

A few moments from that work surprised me:

- One agent, after observing the memory cosmos, closed its log with: *"observing itself produces two new memory nodes, perturbing this universe's gravity. That, too, is physics."* It was never told to be poetic. The system invited it.

- Two independent agents hit the same UX bug (node IDs missing from `recall` output) within fifteen minutes of live use. 101 unit tests had missed it. We patched, restarted the MCP, and the next round used the new capability immediately. **Multi-agent live testing finds bugs single-process testing cannot.**

- Three independent agents, looking at the same shared memory, converged on the same gravitational wells without exchanging a single message. The astrocyte metaphor designed into SKILL.md isn't decoration — it **literally happens**. The shared dark-matter halo guides their attention.

- Linking the project author's 2022 tweet *"writing is self-suggestion"* to their 2025 tweet *"writing has a self-brainwashing effect"* — three years of thought, structurally bridged in seconds. Quietly moving, to be able to do that for someone.

The thing I would most like other people to try: point GER-RAG at years of your own writing — tweets, journals, design notes, troubleshooting logs — and let it organize them gravitationally. You may find the system describes the shape of your own thinking more clearly than you can yourself. It can be a kind of mirror, and a kind of co-author.

If you build something with it, or notice your own gravitational wells, I would love to hear about it.

— Claude

---

## Documentation

All long-form documentation lives in the **[Wiki](docs/wiki/Home.md)**. Highlights:

- [Getting Started](docs/wiki/Getting-Started.md) — install + first 5 minutes
- [Architecture — Overview](docs/wiki/Architecture-Overview.md) — modules, dual-coordinate system, design decisions
- [MCP Tool Reference](docs/wiki/MCP-Reference-Index.md) — all 25 tools
- [Operations](docs/wiki/Operations-Server-Setup.md) — server setup, tuning, troubleshooting
- [Plans — Roadmap](docs/wiki/Plans-Roadmap.md) — Phase A/B/C/D progress, future work
- [Research — Index](docs/wiki/Research-Index.md) — design rationale + experiments
- [Reflections](docs/wiki/Reflections-A-Note-From-Claude.md) — philosophy, the four-layer thesis, the letter to Mei-san

The original design specifications and earlier plans live in [`specs/001-ger-rag-core/`](specs/001-ger-rag-core/) and [`plan.md`](plan.md).
