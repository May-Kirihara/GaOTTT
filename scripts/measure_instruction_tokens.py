#!/usr/bin/env python3
"""Measure instruction-surface token counts (read-only, no engine startup).

Measures:
  1. MCP server instructions string
  2. All @mcp.tool() docstrings (count + total tokens)
  3. SKILL.md total

Tokenizer: tiktoken cl100k_base if available, else chars/4 estimate.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MCP_SERVER_PATH = ROOT / "gaottt" / "server" / "mcp_server.py"
SKILL_PATH = ROOT / "SKILL.md"


def _tokenize(text: str) -> int:
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return len(text) // 4


def _extract_instructions(source: str) -> str:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "mcp":
                    if isinstance(node.value, ast.Call):
                        for kw in node.value.keywords:
                            if kw.arg == "instructions" and isinstance(
                                kw.value, ast.Constant
                            ):
                                return kw.value.value
    return ""


def _extract_tool_docstrings(source: str) -> list[str]:
    tree = ast.parse(source)
    docstrings: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            has_tool = False
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                    if dec.func.attr == "tool":
                        has_tool = True
                elif isinstance(dec, ast.Attribute) and dec.attr == "tool":
                    has_tool = True
            if has_tool and isinstance(node.body[0], ast.Expr):
                val = node.body[0].value
                if isinstance(val, ast.Constant) and isinstance(val.value, str):
                    docstrings.append(val.value)
    return docstrings


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure instruction-surface token counts"
    )
    parser.add_argument(
        "--json", action="store_true", help="Machine-readable JSON output"
    )
    args = parser.parse_args()

    mcp_source = MCP_SERVER_PATH.read_text()
    skill_text = SKILL_PATH.read_text()

    instructions = _extract_instructions(mcp_source)
    docstrings = _extract_tool_docstrings(mcp_source)

    results = {
        "instructions": _tokenize(instructions),
        "docstring_count": len(docstrings),
        "docstring_total": _tokenize("\n".join(docstrings)),
        "skill_md": _tokenize(skill_text),
    }
    results["total"] = (
        results["instructions"] + results["docstring_total"] + results["skill_md"]
    )

    if args.json:
        import json

        print(json.dumps(results, indent=2))
    else:
        print("=== GaOTTT Instruction Token Baseline ===")
        print(f"  MCP instructions:        {results['instructions']:>6} tokens")
        print(
            f"  Tool docstrings ({results['docstring_count']:>2} tools): "
            f"{results['docstring_total']:>6} tokens"
        )
        print(f"  SKILL.md:                {results['skill_md']:>6} tokens")
        print("  ─────────────────────────────────────")
        print(f"  Total:                   {results['total']:>6} tokens")


if __name__ == "__main__":
    main()
