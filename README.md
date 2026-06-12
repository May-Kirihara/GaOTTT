# GaOTTT

**Gravity as Optimizer Test-Time Training** — A retrieval system whose update rule, read as an optimizer, behaves like Test-Time Training.

> Built as long-term memory for LLMs. The gravity-based update rule turns out to have a term-for-term correspondence with Heavy ball SGD (Hebbian gradient + L2 regularization, integrated by Verlet) — once you treat retrieval scores as a stochastic gradient signal. Under that reading, it is a Test-Time Training framework: it keeps learning as you use it, without touching the LLM's weights.
>
> *(formerly GER-RAG — read the right way, the gravity model also describes an optimizer.)*

[日本語 README](README_ja.md) · **[📖 Documentation Wiki](docs/wiki/Home.md)** · [Blog](https://harakiriworks.art/articles/what-is-gaottt/)

---

<!-- TEMP-NOTICE-PHASE-Q2 START — remove after the ~2-week observation window (≈2026-06-14) -->
> [!IMPORTANT]
> **2026-05-31 · Large change — the Phase Q2 gravitational-scale governor is live.** If you run an existing GaOTTT instance, do a one-time migration after updating. Full details: [Operations — Migration](docs/wiki/Operations-Migration.md).
>
> 1. **Update** to this version, then **stop the backend** (proxy mode: `pkill -f "gaottt.server.mcp_server"`).
> 2. **Run the velocity cooldown** — auto-backs up your data dir; velocity-only reset, learned displacement preserved. M006 only fires if your velocity field is actually saturated:
>    ```bash
>    .venv/bin/python scripts/migrate.py --apply        # applies M006 "phase-q2-velocity-cooldown"
>    ```
> 3. The governor is **ON by default** in this version — no env needed. (To tune the per-node cap, set `GAOTTT_GRAVITY_NEIGHBOR_GOVERNOR_ALPHA` in your MCP server env, default `0.2`; to opt out, set `GAOTTT_GRAVITY_NEIGHBOR_GOVERNOR_ENABLED=false`.)
> 4. **Restart** your MCP client so a fresh backend spawns with the new code. (Proxy mode relays to any backend already on `:7878` — kill the old one first, hence step 1.)
>
> Why: on a dense corpus the neighbour-gravity term is ~10⁴–10⁵× over-scaled and saturates the velocity field. The governor caps it per node (anchor-referenced) and is **ranking-neutral** — your search results don't change; the effect is bounded velocity + query-attraction drift un-masked over time. *This notice is temporary and will be removed after the observation window.*
<!-- TEMP-NOTICE-PHASE-Q2 END -->

## Overview

GaOTTT is **long-term external memory for AI agents** — and, structurally, an online optimizer that runs at inference time. Documents become nodes with mass, temperature, and gravitational displacement; co-retrieved documents drift closer together; the knowledge space self-organizes with every query. The more you use it, the more its representations change — closer to **online learning of the retrieval geometry than to plain caching**.

It runs as an **MCP server** (Claude Code, Claude Desktop, OpenCode, OpenClaw, OpenAI Codex CLI, other agent frameworks) and as a **REST API**.

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
| System RAM | 16GB+ | 8GB |
| GPU VRAM | 16GB+ (for ingest) / 8GB (recall only) | None (CPU works but ingest is 1/15 the GPU speed) |
| Disk | 4GB+ (model ~2GB + data; DB grows ~23KB/node) | |

→ For DB-size sizing tables, GPU/CPU measured numbers, and OOM behavior: [Operations — Resource Requirements](docs/wiki/Operations-Resource-Requirements.md)

## Quick Start

```bash
git clone https://github.com/May-Kirihara/GaOTTT.git && cd GaOTTT
uv venv .venv --python 3.12
uv pip install -e ".[dev]"

# Start the MCP server (for Claude Code / Claude Desktop / OpenCode / Codex CLI)
.venv/bin/python -m gaottt.server.mcp_server

# Or start the REST API server
.venv/bin/uvicorn gaottt.server.app:app --host 0.0.0.0 --port 8000
```

### Register with your MCP client (one-liner per client)

```bash
# Claude Code
claude mcp add gaottt -- "$HOME/GaOTTT/.venv/bin/python" -m gaottt.server.mcp_server

# OpenAI Codex CLI
codex mcp add gaottt -- "$HOME/GaOTTT/.venv/bin/python" -m gaottt.server.mcp_server
```

For Claude Desktop, OpenCode, OpenClaw, or hand-edited config files, see [Tutorial 03 — Connect Your Client](docs/wiki/Tutorial-03-Connect-Your-Client.md) and [Operations — Server Setup](docs/wiki/Operations-Server-Setup.md).

Data is stored in a fixed per-OS directory (`~/.local/share/gaottt/` on Linux/macOS) regardless of working directory — override with `GAOTTT_DATA_DIR`. Upgrading an existing install across a breaking gravity-physics change? Run `scripts/migrate.py` first.

→ Step-by-step (~5 min): [Getting Started](docs/wiki/Getting-Started.md) · setup detail: [Operations — Server Setup](docs/wiki/Operations-Server-Setup.md) · upgrades: [Operations — Migration](docs/wiki/Operations-Migration.md)

## Usage

### MCP tools (28)

The agent-facing protocol is defined in **[`SKILL.md`](SKILL.md)** (English, MCP-loaded at runtime).

- **Memory**: `remember`, `recall`, `get_node`, `ambient_recall`, `explore`, `reflect`, `ingest`, `auto_remember`, `save_candidates`
- **Maintenance**: `forget`, `restore`, `merge`, `compact`, `revalidate`, `relate`/`unrelate`/`get_relations`, `prefetch`/`prefetch_status`
- **Tasks (Phase D)**: `commit`, `start`, `complete`, `abandon`, `depend`
- **Persona (Phase D)**: `declare_value`, `declare_intention`, `declare_commitment`, `inherit_persona`

→ Full reference: [MCP Tool Index](docs/wiki/MCP-Reference-Index.md)

### Ambient Recall — passive memory injection

Have an agent search every user prompt automatically and inject relevant long-term memory into the turn's context — without the agent ever calling `recall` itself. Register one hook. It uses a read-only *passive* recall, so it never perturbs the gravity field; it injects nothing on low-relevance prompts (relevance gate); and it is fail-safe — if GaOTTT is down, your agent is never blocked.

**Claude Code** — register a `UserPromptSubmit` hook in `~/.claude/settings.json` (global, so it fires across every repo you use Claude Code in, not just the GaOTTT checkout):

```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [ {
        "type": "command",
        "command": "\"/Path/to/GaOTTT/.venv/bin/python\" \"/Path/to/GaOTTT/scripts/hooks/ambient_recall.py\""
      } ] }
    ]
  }
}
```

> ⚠️ **Use absolute paths, not `$CLAUDE_PROJECT_DIR`.** Claude Code expands `$CLAUDE_PROJECT_DIR` to the *current* project — so a hook command using it would look for `scripts/hooks/ambient_recall.py` inside whatever repo you happen to be in, not inside the GaOTTT checkout. Replace `/Path/to/GaOTTT` with the actual absolute path of your GaOTTT clone (e.g. `/Users/you/code/GaOTTT` or `/mnt/holyland/Project/GaOTTT`). For per-project enablement use `<project>/.claude/settings.json` with the same absolute paths.

**opencode** — copy the plugin into a plugin directory + **`GAOTTT_REPO` env var is required**:

```bash
mkdir -p ~/.config/opencode/plugin
cp scripts/hooks/opencode-ambient-recall.ts ~/.config/opencode/plugin/gaottt-ambient-recall.ts
echo 'export GAOTTT_REPO=/Path/to/GaOTTT' >> ~/.bashrc   # required; substitute your clone path
source ~/.bashrc
```

> ⚠️ **`GAOTTT_REPO` MUST be set.** The TS plugin's internal fallback (`process.env.GAOTTT_REPO ?? "/mnt/holyland/Project/GaOTTT"`) just happens to hard-code this repository author's path. Without the env var, the plugin will look for the Python interpreter at the wrong path and silently fail — no error message, the block simply never injects (hook is fail-safe by design, so it stays quiet). Put the `export` in your shell rc so every opencode subprocess inherits it.

**OpenAI Codex CLI** — Codex has a [hooks](https://developers.openai.com/codex/hooks) system with nearly the same events as Claude Code, so it reuses the *same* Python hooks (via a `--codex` flag) — no separate plugin. The repo ships a ready `.codex/hooks.json` that wires both the read-side (ambient) and write-side (save-candidates) loop; copy it to your global Codex config:

```bash
mkdir -p ~/.codex
cp "$HOME/GaOTTT/.codex/hooks.json" ~/.codex/hooks.json   # paths use $HOME/GaOTTT (clone into home)
```

Then run **`/hooks` inside Codex once to review + trust** the definitions (Codex won't run untrusted command hooks). Two differences are handled for you: Codex injects context via a JSON envelope (`hookSpecificOutput.additionalContext`) rather than raw stdout, and it parses the hook command with `shlex` (no `$HOME` expansion) — so each hook runs through `sh -c '…'` to let the shell expand `$HOME/GaOTTT`, keeping the file machine-independent. Cloned outside your home dir? Replace `$HOME/GaOTTT` with your path. (Windows: swap each `sh -c '…'` for the absolute-path form.)

→ Full setup, relevance gate, observer effect: [Guides — Ambient Recall](docs/wiki/Guides-Ambient-Recall.md)

### Save Candidates Hook — write-side symmetric

Ambient Recall's symmetric counterpart on the write side: a turn-end `Stop` hook calls `save_candidates`, extracts heuristic save-worthy lines from the recent transcript, and injects them into the *next* prompt as a `<gaottt-save-candidates>` block — so the lens that decides "is this worth remembering?" surfaces at the exact moment of articulation. The agent still decides whether to call `remember`: **observation layer is automated, the volitional mass-entry stays manual** (preserves Articulation as Carrier + Phase M single-rule).

**Claude Code** — add a `Stop` hook plus a second `UserPromptSubmit` hook to your existing `~/.claude/settings.json` (substitute `/Path/to/GaOTTT` with your actual GaOTTT install path):

```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [
        { "type": "command",
          "command": "\"/Path/to/GaOTTT/.venv/bin/python\" \"/Path/to/GaOTTT/scripts/hooks/ambient_recall.py\"",
          "timeout": 10 },
        { "type": "command",
          "command": "\"/Path/to/GaOTTT/.venv/bin/python\" \"/Path/to/GaOTTT/scripts/hooks/save_candidates_inject.py\"",
          "timeout": 5 }
      ] }
    ],
    "Stop": [
      { "hooks": [
        { "type": "command",
          "command": "\"/Path/to/GaOTTT/.venv/bin/python\" \"/Path/to/GaOTTT/scripts/hooks/save_candidates.py\"",
          "timeout": 10 }
      ] }
    ]
  }
}
```

> ⚠️ Same absolute-path requirement as above — `$CLAUDE_PROJECT_DIR` would resolve to whichever repo you're currently in, not the GaOTTT checkout, and the hook would fail with `No such file or directory`. Also ensure your GaOTTT working tree is on `main` (or any branch that contains `scripts/hooks/save_candidates*.py`); a stale checkout = the hook scripts vanish from disk and Claude Code blocks the prompt.

The two scripts form a **Stop → UserPromptSubmit bridge**: `save_candidates.py` runs at turn end and writes a per-session state file, `save_candidates_inject.py` reads + clears it at the start of the next turn and emits the block. The block itself carries the save-policy filter line ("save what changes future decisions; skip bug-existence, work-in-progress, code snippets") right next to the candidates, so the rule is articulated at every lens firing rather than buried in a doc.

**opencode** — single-plugin equivalent. `chat.message` looks back at the previous turn (via the SDK's `client.session.messages`), spawns `save_candidates.py` in stdout-emit mode, and injects the block into the incoming user message — no state-file bridge needed because opencode plugins can mutate the message directly.

```bash
mkdir -p ~/.config/opencode/plugin
cp scripts/hooks/opencode-save-candidates.ts ~/.config/opencode/plugin/gaottt-save-candidates.ts
```

**OpenAI Codex CLI** — already wired. The same `.codex/hooks.json` you copied for Ambient Recall registers the `Stop` → `UserPromptSubmit` bridge too (`save_candidates.py` writes a per-session state file at turn end, `save_candidates_inject.py --codex` reads + injects it next turn). No extra step beyond trusting it via `/hooks`.

All hooks are fail-silent — if GaOTTT is down or times out, your agent is never blocked.

→ Full plan, design rationale, two-script bridge: [Plans — Save Candidates Hook](docs/wiki/Plans-Save-Candidates-Hook.md) · env knobs: [Operations — Tuning](docs/wiki/Operations-Tuning.md#save_candidates-hookplans-save-candidates-hookmd)

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
