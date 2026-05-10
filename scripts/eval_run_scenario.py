#!/usr/bin/env python3
"""Run one LLM × scenario × run-idx cell of the GaOTTT behavior study.

Reads a scenario YAML (docs/research/scenarios/*.yaml), creates an isolated
sandbox, drives OpenCode across each turn via `opencode run --format json`,
parses events into a trace, evaluates `require` conditions, and saves:

    <results_root>/<date>/<model-safe>/<scenario_id>/run-<N>/
        trace.jsonl      all opencode events across turns
        transcript.md    human-readable turn-by-turn
        db-final.sqlite  DB snapshot at end of run
        meta.json        metrics + PASS/FAIL per require block

This script rewrites ./opencode.json per run (to point at the run's sandbox)
and restores it on exit. Runs are SEQUENTIAL — do not run multiple instances
against the same project root.

Usage:
    .venv/bin/python scripts/eval_run_scenario.py \\
        --scenario docs/research/scenarios/S00.yaml \\
        --model zai-coding-plan/glm-4.5-flash \\
        --run-idx 1

    # Sweep all Phase 2 scenarios × 4 models × 3 runs:
    for s in docs/research/scenarios/S0*.yaml docs/research/scenarios/L0*.yaml; do
      for m in openrouter/google/gemma-4-31b-it openrouter/qwen/qwen3.5-27b; do
        for r in 1 2 3; do
          .venv/bin/python scripts/eval_run_scenario.py -s "$s" -m "$m" -r "$r"
        done
      done
    done
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OPENCODE_JSON = PROJECT_ROOT / "opencode.json"
OPENCODE_JSON_BAK = PROJECT_ROOT / "opencode.json.runner-bak"
CLONE_SCRIPT = PROJECT_ROOT / "scripts" / "eval_clone_env.sh"
DEFAULT_RESULTS_ROOT = Path("/tmp/gaottt-eval-results")
SERVE_PORT = int(os.environ.get("GAOTTT_EVAL_OPENCODE_PORT", "14096"))
SERVE_READY_TIMEOUT_S = 60


@dataclass
class TurnResult:
    session_id: str        # scenario session id ("only", "s1", ...)
    opencode_sid: str      # opencode's own session id, extracted from events
    prompt: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    text_parts: list[str] = field(default_factory=list)
    tokens: dict[str, int] = field(default_factory=dict)
    cost: float = 0.0
    latency_ms: int = 0
    require_checks: list[dict[str, Any]] = field(default_factory=list)  # [{name, passed, detail}]


def sanitize_slug(model: str) -> str:
    return model.replace("/", "_").replace(":", "-")


# ---------------------------------------------------------------- sandbox/config

def create_sandbox(tag: str) -> Path:
    """Call eval_clone_env.sh to create an empty sandbox and return its path."""
    result = subprocess.run(
        [str(CLONE_SCRIPT), tag],
        check=True, capture_output=True, text=True, cwd=PROJECT_ROOT,
    )
    # The script prints "Created sandbox: <path> ..." — parse it.
    for line in result.stdout.splitlines():
        if line.startswith("Created sandbox:"):
            return Path(line.split(":", 1)[1].split("(")[0].strip())
    raise RuntimeError(f"Could not parse sandbox path from: {result.stdout}")


def destroy_sandbox(tag: str) -> None:
    subprocess.run([str(CLONE_SCRIPT), "--rm", tag], check=False,
                   capture_output=True, cwd=PROJECT_ROOT)


def write_opencode_json(sandbox: Path) -> None:
    """Overwrite project-root opencode.json to point at this run's sandbox."""
    cfg = {
        "$schema": "https://opencode.ai/config.json",
        "mcp": {
            "gaottt": {
                "type": "local",
                "command": [
                    str(PROJECT_ROOT / ".venv" / "bin" / "python"),
                    "-m", "gaottt.server.mcp_server",
                ],
                "environment": {"GAOTTT_DATA_DIR": str(sandbox)},
                "enabled": True,
                "timeout": 30000,
            }
        },
    }
    OPENCODE_JSON.write_text(json.dumps(cfg, indent=2) + "\n")


# --------------------------------------------------------------- seed injection

def seed_sandbox(sandbox: Path, seed_items: list[str]) -> None:
    """Pre-populate the sandbox by calling gaottt's service layer directly.

    Runs in the *current* Python process, so requires the caller to have
    gaottt importable (i.e. run via .venv/bin/python).
    """
    os.environ["GAOTTT_DATA_DIR"] = str(sandbox)
    # Force re-import so config picks up the new env var.
    for mod in list(sys.modules):
        if mod.startswith("gaottt"):
            del sys.modules[mod]
    from gaottt.services.runtime import build_engine  # noqa: WPS433
    from gaottt.services.memory import save_memory

    import asyncio
    async def _seed() -> None:
        engine = await build_engine()
        try:
            for text in seed_items:
                await save_memory(engine, text=text, source="fact")
        finally:
            await engine.close()
    asyncio.run(_seed())


# -------------------------------------------------- opencode serve (persistent)

def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


@contextlib.contextmanager
def opencode_server(port: int, log_path: Path) -> Iterator[str]:
    """Start `opencode serve` in background, yield the attach URL, stop on exit.

    Keeping one server (and its single MCP process) alive across all turns of a
    scenario is required: gaottt's write-behind cache and FAISS index are
    in-process, so a fresh MCP cold-start between turns loses just-saved data.
    """
    if not _port_free(port):
        raise RuntimeError(f"Port {port} is already in use — set GAOTTT_EVAL_OPENCODE_PORT.")

    log_fh = log_path.open("w")
    proc = subprocess.Popen(
        ["opencode", "serve", "--port", str(port), "--print-logs"],
        cwd=PROJECT_ROOT, stdout=log_fh, stderr=subprocess.STDOUT,
        preexec_fn=os.setsid,  # own process group so we can kill MCP children too
    )
    url = f"http://127.0.0.1:{port}"

    # Poll readiness. opencode's root returns 404 but that's fine — it means
    # the HTTP server is up.
    deadline = time.time() + SERVE_READY_TIMEOUT_S
    while time.time() < deadline:
        if proc.poll() is not None:
            log_fh.close()
            raise RuntimeError(f"opencode serve exited early. See {log_path}")
        try:
            urllib.request.urlopen(url + "/", timeout=1)
            break
        except urllib.error.HTTPError:
            break  # any HTTP response means server is up
        except (urllib.error.URLError, ConnectionRefusedError, socket.timeout):
            time.sleep(0.5)
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        log_fh.close()
        raise RuntimeError(f"opencode serve not ready within {SERVE_READY_TIMEOUT_S}s")

    try:
        yield url
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=10)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
        log_fh.close()


# ------------------------------------------------------------------ opencode run

def run_turn(model: str, prompt: str, resume_sid: str | None, attach_url: str,
             log_sink: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]], int]:
    """Invoke `opencode run --format json` for one turn, attaching to a
    persistent server so MCP state survives.

    Returns: (opencode_session_id, this_turn_events, latency_ms).
    Appends this turn's events to log_sink.
    """
    cmd = ["opencode", "run", "--format", "json", "--model", model,
           "--attach", attach_url]
    if resume_sid:
        cmd += ["-s", resume_sid]
    cmd.append(prompt)

    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
    latency_ms = int((time.time() - t0) * 1000)

    if proc.returncode != 0:
        # Emit a synthetic error event so downstream parsing still works
        err_event = {
            "type": "runner_error",
            "returncode": proc.returncode,
            "stderr_tail": proc.stderr[-500:] if proc.stderr else "",
        }
        log_sink.append(err_event)
        return (resume_sid or "", [err_event], latency_ms)

    events: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            events.append({"type": "unparseable", "raw": line[:300]})

    sid = resume_sid or ""
    for ev in events:
        if ev.get("sessionID"):
            sid = ev["sessionID"]
            break

    log_sink.extend(events)
    return (sid, events, latency_ms)


# ------------------------------------------------------------- event analysis

def extract_tool_calls(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    calls = []
    for ev in events:
        if ev.get("type") != "tool_use":
            continue
        part = ev.get("part", {})
        state = part.get("state", {})
        calls.append({
            "tool": part.get("tool"),
            "status": state.get("status"),
            "input": state.get("input"),
            "output": state.get("output"),
            "time": state.get("time", {}),
            "call_id": part.get("callID"),
        })
    return calls


def extract_text(events: list[dict[str, Any]]) -> list[str]:
    out = []
    for ev in events:
        if ev.get("type") == "text":
            t = ev.get("part", {}).get("text", "")
            if t:
                out.append(t)
    return out


def extract_step_metrics(events: list[dict[str, Any]]) -> tuple[dict[str, int], float]:
    tokens = {"input": 0, "output": 0, "reasoning": 0, "cache_read": 0, "cache_write": 0}
    cost = 0.0
    for ev in events:
        if ev.get("type") != "step_finish":
            continue
        t = ev.get("part", {}).get("tokens", {})
        tokens["input"] += t.get("input", 0) or 0
        tokens["output"] += t.get("output", 0) or 0
        tokens["reasoning"] += t.get("reasoning", 0) or 0
        tokens["cache_read"] += t.get("cache", {}).get("read", 0) or 0
        tokens["cache_write"] += t.get("cache", {}).get("write", 0) or 0
        cost += ev.get("part", {}).get("cost", 0.0) or 0.0
    return tokens, cost


# ---------------------------------------------------------- require evaluation

def _check_tool(calls: list[dict[str, Any]], req: dict[str, Any]) -> dict[str, Any]:
    """Evaluate one turn's `require` dict against the turn's tool_calls."""
    checks: list[dict[str, Any]] = []
    wanted_single = req.get("tool")
    wanted_any = req.get("tool_any_of")
    allowed_tools = {wanted_single} if wanted_single else set(wanted_any or [])

    matching = [c for c in calls if c["tool"] in allowed_tools and c["status"] == "completed"]
    checks.append({
        "name": "tool_called",
        "passed": bool(matching),
        "detail": f"wanted {allowed_tools}, saw {[c['tool'] for c in calls]}",
    })

    if not matching:
        # No point checking substrings if no matching call
        for k in ("input_substrings", "output_substrings"):
            if k in req:
                checks.append({"name": k, "passed": False, "detail": "no matching tool call"})
        return {"passed": False, "checks": checks}

    # Use the first matching call for substring checks
    match = matching[0]
    if "input_substrings" in req:
        input_str = json.dumps(match["input"], ensure_ascii=False)
        missing = [s for s in req["input_substrings"] if s not in input_str]
        checks.append({
            "name": "input_substrings",
            "passed": not missing,
            "detail": f"missing: {missing}" if missing else f"all present in {input_str[:120]}",
        })
    if "output_substrings" in req:
        output_str = str(match["output"] or "")
        missing = [s for s in req["output_substrings"] if s not in output_str]
        checks.append({
            "name": "output_substrings",
            "passed": not missing,
            "detail": f"missing: {missing}" if missing else f"all present in output",
        })

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks}


# ------------------------------------------------------------------- main flow

def run_scenario(scenario_path: Path, model: str, run_idx: int,
                 results_root: Path, keep_sandbox: bool) -> dict[str, Any]:
    scenario = yaml.safe_load(scenario_path.read_text())
    scenario_id = scenario["id"]
    tag = f"{scenario_id}-{sanitize_slug(model)}-r{run_idx}"

    print(f"\n=== {scenario_id} × {model} × run {run_idx} ===")
    print(f"  sandbox tag: {tag}")

    sandbox = create_sandbox(tag)

    # Seed BEFORE writing opencode.json (seeding uses in-process gaottt,
    # opencode launches its own MCP subprocess later).
    if "seed" in scenario:
        print(f"  seeding {len(scenario['seed'])} memories")
        seed_sandbox(sandbox, scenario["seed"])

    write_opencode_json(sandbox)

    all_events: list[dict[str, Any]] = []
    turn_results: list[TurnResult] = []

    # Server log lands next to the results so we can post-mortem if serve dies.
    server_log = Path("/tmp") / f"gaottt-eval-serve-{tag}.log"
    print(f"  starting opencode serve on port {SERVE_PORT}...")
    with opencode_server(SERVE_PORT, server_log) as attach_url:
        for session in scenario["sessions"]:
            session_local_id = session["id"]
            # reset_context (or first session) means: start a fresh opencode
            # session (no -s resume). MCP state is preserved because the server
            # is the same — only the agent context resets.
            opencode_sid: str | None = None
            for turn in session["turns"]:
                prompt = turn["prompt"]
                print(f"  [{session_local_id}] > {prompt[:70]}{'...' if len(prompt) > 70 else ''}")
                opencode_sid, turn_events, latency = run_turn(
                    model, prompt, opencode_sid, attach_url, all_events,
                )

                tool_calls = extract_tool_calls(turn_events)
                text_parts = extract_text(turn_events)
                tokens, cost = extract_step_metrics(turn_events)

                tr = TurnResult(
                    session_id=session_local_id,
                    opencode_sid=opencode_sid,
                    prompt=prompt,
                    tool_calls=tool_calls,
                    text_parts=text_parts,
                    tokens=tokens,
                    cost=cost,
                    latency_ms=latency,
                )
                if "require" in turn:
                    verdict = _check_tool(tool_calls, turn["require"])
                    tr.require_checks = verdict["checks"]
                turn_results.append(tr)
                print(f"    tools: {[c['tool'] for c in tool_calls]}  cost=${cost:.4f}  {latency}ms")

    # --- aggregate
    require_passed_flags = []
    for tr in turn_results:
        if tr.require_checks:
            require_passed_flags.append(all(c["passed"] for c in tr.require_checks))
    overall_pass = all(require_passed_flags) if require_passed_flags else None  # None = nothing required

    total_tokens = {"input": 0, "output": 0, "reasoning": 0, "cache_read": 0, "cache_write": 0}
    total_cost = 0.0
    for tr in turn_results:
        for k, v in tr.tokens.items():
            total_tokens[k] += v
        total_cost += tr.cost

    # --- save artifacts
    date = datetime.now().strftime("%Y-%m-%d")
    out_dir = results_root / date / sanitize_slug(model) / scenario_id / f"run-{run_idx}"
    out_dir.mkdir(parents=True, exist_ok=True)

    with (out_dir / "trace.jsonl").open("w") as f:
        for ev in all_events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")

    transcript_lines = [f"# {scenario_id} × {model} × run {run_idx}", ""]
    for tr in turn_results:
        transcript_lines.append(f"## [{tr.session_id}] turn")
        transcript_lines.append(f"**user:** {tr.prompt}\n")
        for c in tr.tool_calls:
            transcript_lines.append(f"**tool:** `{c['tool']}`")
            transcript_lines.append(f"- input: `{json.dumps(c['input'], ensure_ascii=False)}`")
            out_preview = str(c["output"] or "")[:300]
            transcript_lines.append(f"- output: `{out_preview}`")
        for t in tr.text_parts:
            transcript_lines.append(f"**assistant:** {t}\n")
        if tr.require_checks:
            for ch in tr.require_checks:
                mark = "✓" if ch["passed"] else "✗"
                transcript_lines.append(f"- {mark} {ch['name']}: {ch['detail']}")
        transcript_lines.append("")
    (out_dir / "transcript.md").write_text("\n".join(transcript_lines))

    # DB snapshot via .backup
    import sqlite3 as _s
    with _s.connect(sandbox / "gaottt.db") as src, _s.connect(out_dir / "db-final.sqlite") as dst:
        src.backup(dst)

    meta = {
        "scenario": scenario_id,
        "scenario_path": str(scenario_path),
        "model": model,
        "run_idx": run_idx,
        "sandbox_tag": tag,
        "timestamp": datetime.now().isoformat(),
        "overall_pass": overall_pass,
        "require_passed_flags": require_passed_flags,
        "total_tokens": total_tokens,
        "total_cost": total_cost,
        "turns": [asdict(tr) for tr in turn_results],
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))

    print(f"  → {out_dir}")
    print(f"  pass: {overall_pass}  tokens: {total_tokens}  cost: ${total_cost:.4f}")

    if not keep_sandbox:
        destroy_sandbox(tag)

    return meta


def restore_opencode_json() -> None:
    """On normal runner exit we leave opencode.json pointing at the last run's
    sandbox. The user can re-generate it by running a single scenario or by
    checking out the file from git. We don't fabricate a default here because
    there isn't one — the original config has an arbitrary sandbox path too."""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("-s", "--scenario", type=Path, required=True,
                    help="Path to scenario YAML")
    ap.add_argument("-m", "--model", required=True,
                    help="opencode model slug, e.g. openrouter/google/gemma-4-31b-it")
    ap.add_argument("-r", "--run-idx", type=int, default=1)
    ap.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    ap.add_argument("--keep-sandbox", action="store_true",
                    help="Don't delete the sandbox after the run (for debugging)")
    args = ap.parse_args()

    if not args.scenario.is_file():
        print(f"ERROR: scenario not found: {args.scenario}", file=sys.stderr)
        return 2

    # Back up opencode.json once per invocation
    if OPENCODE_JSON.exists():
        shutil.copy2(OPENCODE_JSON, OPENCODE_JSON_BAK)

    try:
        meta = run_scenario(args.scenario, args.model, args.run_idx,
                            args.results_root, args.keep_sandbox)
    finally:
        if OPENCODE_JSON_BAK.exists():
            shutil.copy2(OPENCODE_JSON_BAK, OPENCODE_JSON)
            OPENCODE_JSON_BAK.unlink()

    return 0 if meta.get("overall_pass") in (True, None) else 1


if __name__ == "__main__":
    sys.exit(main())
