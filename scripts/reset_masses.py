#!/usr/bin/env python3
"""Phase M Stage 1 — 質量リセット (mass を全ノード共通の初期値に戻す)。

Mass Conservation 規則 (`mass_conservation_enabled=True`) を本番 DB に
ロールアウトする時の一回限り操作。旧規則下で蓄積した chunk 内輪取引
inflation を一度ゼロにしてから、新規則で「外から引かれた量」だけを
これから積む。

**displacement / velocity / edges / cohort_id / source は触らない**。
mass の数値だけを value (既定 1.0) にする。

Usage::

    # dry-run (件数だけ表示、書き込まない)
    .venv/bin/python scripts/reset_masses.py

    # 実際に書き込む (既定 1.0)
    .venv/bin/python scripts/reset_masses.py --apply

    # 任意の値で書き込む
    .venv/bin/python scripts/reset_masses.py --value 1.5 --apply

Safety:
  * 走らせる前に **他の MCP / REST プロセスを停止すること** —
    起動中だと cache write-back で reset が即座に上書きされる。
    --force を付けない限り検出時にエラー終了する。
  * destructive — 戻せない (mass 履歴は残らない)。事前に DB backup を取る。
"""
from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gaottt.config import GaOTTTConfig  # noqa: E402
from gaottt.services.runtime import build_engine  # noqa: E402


def _running_gaottt_pids() -> list[tuple[int, str]]:
    patterns = [
        ("gaottt.server.mcp_server", "MCP server"),
        ("gaottt.server.app", "REST server"),
    ]
    found: list[tuple[int, str]] = []
    for pattern, label in patterns:
        try:
            out = subprocess.check_output(
                ["pgrep", "-f", pattern], stderr=subprocess.DEVNULL,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
        for line in out.decode().splitlines():
            line = line.strip()
            if line.isdigit():
                found.append((int(line), label))
    return found


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reset every node's mass to a fixed value (Phase M Stage 1).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--value", type=float, default=1.0,
        help="リセット後の mass 値 (既定 1.0)。",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="実際に書き込む。指定しない場合は dry-run。",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="起動中のサーバープロセスを無視して続行する (推奨せず)。",
    )
    args = parser.parse_args()

    if args.value < 0.0:
        print("ERROR: --value は 0.0 以上を指定してください", file=sys.stderr)
        sys.exit(2)

    if args.apply:
        procs = _running_gaottt_pids()
        if procs and not args.force:
            desc = ", ".join(f"pid={p} ({lb})" for p, lb in procs)
            print(
                f"WARNING: 起動中の GaOTTT サーバープロセスを検出: {desc}\n"
                "  cache write-back で reset が即上書きされます。先に停止してください:\n"
                "    pkill -f gaottt.server.mcp_server\n"
                "    pkill -f gaottt.server.app\n"
                "  停止せず続行するには --force を指定してください。",
                file=sys.stderr,
            )
            sys.exit(3)

    config = GaOTTTConfig.from_config_file()
    # 観察を汚さないために dream / FAISS save を無効化して走る
    config.dream_enabled = False
    config.faiss_save_interval_seconds = 0.0

    engine = build_engine(config)
    await engine.startup()

    masses = np.array(
        [s.mass for s in engine.cache.get_all_nodes() if not s.is_archived]
    )
    print(f"アクティブノード総数: {len(masses)}")
    if len(masses):
        print(
            f"  mass: min={masses.min():.2f}  median={np.median(masses):.2f}  "
            f"p99={np.percentile(masses, 99):.2f}  max={masses.max():.2f}",
        )

    if not args.apply:
        print(
            f"\n[dry-run] {len(masses)} 件の mass を {args.value} にリセットします。"
            "\n実際に書き込むには --apply を付けてください。",
        )
        await engine.shutdown()
        return

    affected = await engine.reset_masses(args.value)
    print(f"\n[apply] {affected} 件の mass を {args.value} にリセット完了。")
    print("[apply] cache → SQLite に flush 中 ...")
    await engine.cache.flush_to_store(engine.store)
    print("[apply] flush 完了。MCP / REST を再起動してください。")
    await engine.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
