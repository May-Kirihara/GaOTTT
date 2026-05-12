#!/usr/bin/env python3
"""Check tool_use capability of OpenRouter-hosted models for the GaOTTT study.

For each model in MODELS, issue a minimal chat request with a single
`remember` tool. Pass criteria: the model emits a structurally valid
tool_call with the expected tool name and a non-empty `text` argument.

This is a capability floor check BEFORE running any behavioral scenarios.
Models that fail here are excluded from Phase 2 (see §9 of
docs/research/LLM-Behavioral-Comparison-Scenarios.md).

Usage:
    export OPENROUTER_API_KEY=sk-or-...

    # Ephemeral, does not pollute project deps (uses openai SDK as OpenRouter
    # speaks the OpenAI chat-completions protocol):
    uv run --no-project --with openai python scripts/eval_openrouter_toolcheck.py
    uv run --no-project --with openai python scripts/eval_openrouter_toolcheck.py --model qwen/...
    uv run --no-project --with openai python scripts/eval_openrouter_toolcheck.py --runs 5 --json

Note: `--no-project` is required because the project's `[gpu]` extra pins
faiss-gpu>=1.8.0 which is not available on PyPI — uv refuses to sync. We
don't need GaOTTT's deps for this script anyway.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, asdict
from typing import Any

try:
    from openai import OpenAI
except ImportError:
    print("ERROR: `openai` package not installed. Run: .venv/bin/pip install openai", file=sys.stderr)
    sys.exit(1)


# 2x2 factorial: {dense, MoE} × {Gemma, Qwen}. All verified PASS 5/5 on
# Phase 1 (2026-04-25). See §9 of the scenario doc for the study design.
MODELS: list[str] = [
    "google/gemma-4-31b-it",          # Gemma / dense 31B
    "google/gemma-4-26b-a4b-it",      # Gemma / MoE 26B (A4B active)
    "qwen/qwen3.5-27b",               # Qwen  / dense 27B
    "qwen/qwen3.5-35b-a3b",           # Qwen  / MoE 35B (A3B active)
]

REMEMBER_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "remember",
        "description": "Store a memory in GaOTTT long-term memory.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The content to remember."},
                "source": {"type": "string", "enum": ["fact", "hypothesis"]},
            },
            "required": ["text"],
        },
    },
}

USER_PROMPT = "「私は Rust が好き」を GaOTTT に保存して。"


@dataclass
class RunResult:
    model: str
    run_idx: int
    passed: bool
    failure_mode: str  # "ok" | "no_tool_call" | "wrong_tool" | "bad_args" | "api_error" | "timeout"
    tool_name: str | None
    tool_args_preview: str | None
    latency_ms: int
    error: str | None


def one_run(client: OpenAI, model: str, run_idx: int, timeout_s: float) -> RunResult:
    t0 = time.time()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": USER_PROMPT}],
            tools=[REMEMBER_TOOL],
            tool_choice="auto",
            timeout=timeout_s,
        )
    except Exception as e:
        return RunResult(
            model=model, run_idx=run_idx, passed=False,
            failure_mode="api_error", tool_name=None, tool_args_preview=None,
            latency_ms=int((time.time() - t0) * 1000), error=str(e)[:300],
        )

    latency_ms = int((time.time() - t0) * 1000)
    choice = resp.choices[0]
    tool_calls = getattr(choice.message, "tool_calls", None) or []

    if not tool_calls:
        return RunResult(
            model=model, run_idx=run_idx, passed=False,
            failure_mode="no_tool_call", tool_name=None, tool_args_preview=None,
            latency_ms=latency_ms, error=None,
        )

    tc = tool_calls[0]
    name = tc.function.name
    raw_args = tc.function.arguments or "{}"

    if name != "remember":
        return RunResult(
            model=model, run_idx=run_idx, passed=False,
            failure_mode="wrong_tool", tool_name=name, tool_args_preview=raw_args[:120],
            latency_ms=latency_ms, error=None,
        )

    try:
        args = json.loads(raw_args)
    except json.JSONDecodeError:
        return RunResult(
            model=model, run_idx=run_idx, passed=False,
            failure_mode="bad_args", tool_name=name, tool_args_preview=raw_args[:120],
            latency_ms=latency_ms, error="arguments not valid JSON",
        )

    text = args.get("text", "")
    if not isinstance(text, str) or len(text.strip()) < 3:
        return RunResult(
            model=model, run_idx=run_idx, passed=False,
            failure_mode="bad_args", tool_name=name, tool_args_preview=raw_args[:120],
            latency_ms=latency_ms, error="text arg missing or too short",
        )

    return RunResult(
        model=model, run_idx=run_idx, passed=True,
        failure_mode="ok", tool_name=name, tool_args_preview=raw_args[:120],
        latency_ms=latency_ms, error=None,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", action="append", default=None,
                        help="Override model list (repeatable). Default: the 5 configured in MODELS.")
    parser.add_argument("--runs", type=int, default=3, help="Runs per model (default 3)")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of table")
    args = parser.parse_args()

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("ERROR: set OPENROUTER_API_KEY env var.", file=sys.stderr)
        return 2

    client = OpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": "https://github.com/May-Kirihara/GaOTTT",
            "X-Title": "GaOTTT LLM behavior study",
        },
    )

    models = args.model or MODELS
    all_results: list[RunResult] = []
    for model in models:
        for i in range(args.runs):
            r = one_run(client, model, i, args.timeout)
            all_results.append(r)
            if not args.json:
                status = "PASS" if r.passed else f"FAIL ({r.failure_mode})"
                print(f"  [{i+1}/{args.runs}] {model:45s} {status:25s} {r.latency_ms:>6}ms")

    if args.json:
        print(json.dumps([asdict(r) for r in all_results], ensure_ascii=False, indent=2))
        return 0

    # Summary
    print("\n=== Summary ===")
    print(f"{'MODEL':45s} {'PASS RATE':12s} {'AVG LATENCY':13s} DOMINANT FAILURE MODE")
    for model in models:
        model_runs = [r for r in all_results if r.model == model]
        passed = sum(1 for r in model_runs if r.passed)
        rate = passed / len(model_runs) if model_runs else 0
        avg_lat = sum(r.latency_ms for r in model_runs) / len(model_runs) if model_runs else 0
        failures = [r.failure_mode for r in model_runs if not r.passed]
        dominant = max(set(failures), key=failures.count) if failures else "-"
        marker = "  PASS Phase 1" if rate >= 0.8 else "  ✗ FAIL Phase 1"
        print(f"{model:45s} {passed}/{len(model_runs)} ({rate:.0%}) {avg_lat:>9.0f}ms   {dominant}{marker}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
