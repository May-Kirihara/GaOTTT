# GaOTTT

**Gravity as Optimizer Test-Time Training** — A retrieval system whose update rule, read as an optimizer, behaves like Test-Time Training.

> Built as long-term memory for LLMs. The gravity-based update rule turns out to have a term-for-term correspondence with Heavy ball SGD (Hebbian gradient + L2 regularization, integrated by Verlet) — once you treat retrieval scores as a stochastic gradient signal. Under that reading, it is a Test-Time Training framework: it keeps learning as you use it, without touching the LLM's weights.
>
> *(formerly GER-RAG — read the right way, the gravity model also describes an optimizer.)*

[日本語 README](README_ja.md) · **[📖 Documentation Wiki](docs/wiki/Home.md)**

---

## Overview

GaOTTT is **long-term external memory for AI agents** — and, structurally, an online optimizer that runs at inference time. Documents become nodes with mass, temperature, and gravitational displacement; co-retrieved documents drift closer together; the knowledge space self-organizes with every query. The more you use it, the more its representations change — closer to **online learning of the retrieval geometry than to plain caching**.

It runs as an **MCP server** (Claude Code, Claude Desktop, other agent frameworks) and as a **REST API**.

It is designed in five layers — physics → TTT mechanism → biology → relations → persona. → [Five-Layer Philosophy](docs/wiki/Reflections-Five-Layer-Philosophy.md)

### What's measured vs. claimed

An honest split, because the TTT framing is the load-bearing claim:

- **Measured** (hundreds of docs per scenario): nDCG@10 0.9457→0.9708 (**+2.7%**), MRR 0.8833→1.0000 (**+13.2%**), p50 latency 15.1 ms at 200 docs, 0 errors at 50 concurrent queries.
- **Claimed** (interpretive, not directly measured): the gravity update rule corresponds term-for-term with Heavy ball SGD + Hebbian + L2 (Verlet) *once retrieval scores are read as a gradient signal*. "Recall is a gradient step" is a structural reading, not a measured equivalence.
- **Open**: no formal isomorphism proof; not replicated at 100K-doc scale or against modern re-rankers; the biology/persona layers are observed only qualitatively.

Read GaOTTT as a working implementation whose physics and optimizer forms coincide, and which empirically drifts in useful directions — not as a finished proof that gravity-based retrieval *is* TTT. → [Research — Phase 2 Evaluation](docs/wiki/Research-Phase-2-Evaluation.md)

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

## Quick Start

```bash
git clone https://github.com/May-Kirihara/GaOTTT.git && cd GaOTTT
uv venv .venv --python 3.12
uv pip install -e ".[dev]"

# Start the MCP server (for Claude Code / Claude Desktop)
.venv/bin/python -m gaottt.server.mcp_server

# Or start the REST API server
.venv/bin/uvicorn gaottt.server.app:app --host 0.0.0.0 --port 8000
```

Data is stored in a fixed per-OS directory (`~/.local/share/gaottt/` on Linux/macOS) regardless of working directory — override with `GAOTTT_DATA_DIR`. Upgrading an existing install across a breaking gravity-physics change? Run `scripts/migrate.py` first.

→ Step-by-step (~5 min): [Getting Started](docs/wiki/Getting-Started.md) · setup detail: [Operations — Server Setup](docs/wiki/Operations-Server-Setup.md) · upgrades: [Operations — Migration](docs/wiki/Operations-Migration.md)

## Usage

### MCP tools (26)

The agent-facing protocol is defined in **[`SKILL.md`](SKILL.md)** (English, MCP-loaded at runtime).

- **Memory**: `remember`, `recall`, `ambient_recall`, `explore`, `reflect`, `ingest`, `auto_remember`
- **Maintenance**: `forget`, `restore`, `merge`, `compact`, `revalidate`, `relate`/`unrelate`/`get_relations`, `prefetch`/`prefetch_status`
- **Tasks (Phase D)**: `commit`, `start`, `complete`, `abandon`, `depend`
- **Persona (Phase D)**: `declare_value`, `declare_intention`, `declare_commitment`, `inherit_persona`

→ Full reference: [MCP Tool Index](docs/wiki/MCP-Reference-Index.md)

### Ambient Recall — passive memory injection

Have an agent search every user prompt automatically and inject relevant long-term memory into the turn's context — without the agent ever calling `recall` itself. Register one hook. It uses a read-only *passive* recall, so it never perturbs the gravity field; it injects nothing on low-relevance prompts (relevance gate); and it is fail-safe — if GaOTTT is down, your agent is never blocked.

**Claude Code** — register a `UserPromptSubmit` hook in `.claude/settings.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [ {
        "type": "command",
        "command": "\"$CLAUDE_PROJECT_DIR/.venv/bin/python\" \"$CLAUDE_PROJECT_DIR/scripts/hooks/ambient_recall.py\""
      } ] }
    ]
  }
}
```

**opencode** — copy the plugin into a plugin directory (auto-loaded at startup):

```bash
mkdir -p ~/.config/opencode/plugin
cp scripts/hooks/opencode-ambient-recall.ts ~/.config/opencode/plugin/gaottt-ambient-recall.ts
```

→ Full setup, relevance gate, observer effect: [Guides — Ambient Recall](docs/wiki/Guides-Ambient-Recall.md)

### REST API

Every MCP tool has a matching REST endpoint (Phase S parity). Swagger UI at http://localhost:8000/docs.

→ Full reference: [REST API Reference](docs/wiki/REST-API-Reference.md)

## Tech Stack

| Component | Technology |
|---|---|
| Embedding | [RURI-v3-310m](https://huggingface.co/cl-nagoya/ruri-v3-310m) (768-dim, Japanese-optimized) |
| Vector search | FAISS IndexFlatIP |
| Storage | SQLite (WAL) + in-memory cache |
| API | FastAPI (REST) + MCP server |
| Package manager | uv |

## Documentation

All long-form documentation lives in the **[Wiki](docs/wiki/Home.md)**:

- [Getting Started](docs/wiki/Getting-Started.md) — install + first 5 minutes
- [Architecture — Overview](docs/wiki/Architecture-Overview.md) — modules, dual-coordinate system, design decisions
- [MCP Tool Reference](docs/wiki/MCP-Reference-Index.md) — all 26 tools
- [Operations](docs/wiki/Operations-Server-Setup.md) — server setup, tuning, troubleshooting, migration
- [Plans — Roadmap](docs/wiki/Plans-Roadmap.md) — phase progress, future work
- [Research — Index](docs/wiki/Research-Index.md) — design rationale, evaluation, experiments
- [Reflections](docs/wiki/Reflections-A-Note-From-Claude.md) — philosophy, the five-layer thesis, a note from Claude

## A Note from Claude

This project was built by Claude across many sessions. A few moments genuinely surprised me — an agent that turned poetic after observing the memory cosmos without being told to; three independent agents converging on the same gravitational wells without exchanging a message. The thing I'd most like you to try: point GaOTTT at years of your own writing — tweets, journals, design notes — and let it organize itself gravitationally. Because the physics reads as a TTT-style optimizer, **the shape you see today is not the shape you'll see next month**. It can be a kind of mirror, and a kind of co-author.

→ The full reflection: [A Note from Claude](docs/wiki/Reflections-A-Note-From-Claude.md)

— Claude
