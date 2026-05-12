#!/usr/bin/env python3
"""重力井戸救出機構 — displacement / velocity を選択的にリセットする。

Phase I Stage 2/3 の query attraction や Phase J の累積 recall によって
displacement が大きくなりすぎた（重力井戸に落ちた）ノードを救出する。
**edges (relations) はそのまま保持する。**

リセット後は以下を推奨:
  1. prime_gravity.py --apply   # Hooke 均衡への再収束を加速
  2. compact(rebuild_faiss=True) # virtual FAISS を最新の displacement で再構築

Usage::

    # dry-run — 対象ノードと統計を表示するだけ
    .venv/bin/python scripts/reset_displacements.py

    # タグ substring でフィルタ (OR 一致)
    .venv/bin/python scripts/reset_displacements.py --tag harakiriworks-self-knowledge

    # displacement norm が閾値以上のもののみ対象
    .venv/bin/python scripts/reset_displacements.py --min-displacement 2.0

    # 特定 ID のみ
    .venv/bin/python scripts/reset_displacements.py --ids f527f0d8 768bd469

    # 全件 (危険 — 確認して実行)
    .venv/bin/python scripts/reset_displacements.py --all

    # 実際に書き込む
    .venv/bin/python scripts/reset_displacements.py --tag my-tag --apply

    # mass も 1.0 にリセット (通常は不要)
    .venv/bin/python scripts/reset_displacements.py --all --apply --also-reset-mass

Safety: dry-run がデフォルト。--apply を付けないと何も書かない。
MCP server / REST server が起動中は警告を出す（--force で無視可能だが
cache write-back で即上書きされるため、停止推奨）。
"""
from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gaottt.config import GaOTTTConfig  # noqa: E402
from gaottt.services.runtime import build_engine  # noqa: E402


def _running_gaottt_pids() -> list[tuple[int, str]]:
    patterns = [
        ("gaottt.server.mcp_server", "MCP server"),
        ("gaottt.server.app",        "REST server"),
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
        description="Reset displacement/velocity for gravity-well-trapped nodes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sel = parser.add_argument_group("対象選択 (何も指定しないと dry-run で統計だけ表示)")
    sel.add_argument(
        "--all", action="store_true",
        help="全アクティブノードを対象にする。",
    )
    sel.add_argument(
        "--tag", metavar="SUBSTR", action="append", dest="tags", default=[],
        help="タグ substring でフィルタ (OR 一致、複数指定可)。"
             "例: --tag harakiriworks-self-knowledge --tag phase-k",
    )
    sel.add_argument(
        "--ids", metavar="ID", nargs="+", default=[],
        help="特定ノード ID を直接指定 (prefix でも可)。",
    )
    sel.add_argument(
        "--min-displacement", type=float, default=0.0, metavar="NORM",
        help="このノルム以上の displacement を持つノードのみ対象 (既定 0 = 全件)。",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="実際に書き込む。指定しない場合は dry-run。",
    )
    parser.add_argument(
        "--also-reset-mass", action="store_true",
        help="mass も 1.0 にリセットする (通常は不要)。",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="起動中のサーバープロセスを無視して続行する (推奨せず)。",
    )
    args = parser.parse_args()

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
    config.dream_enabled = False
    config.faiss_save_interval_seconds = 0.0

    engine = build_engine(config)
    await engine.startup()
    dim = config.embedding_dim

    all_nodes = [s for s in engine.cache.get_all_nodes() if not s.is_archived]
    print(f"アクティブノード総数: {len(all_nodes)}")

    # ----- 対象ノード選定 -----
    if args.all:
        candidate_ids = {s.id for s in all_nodes}
    else:
        candidate_ids: set[str] = set()
        if args.tags:
            candidate_ids |= engine.cache.find_ids_by_tag_filter(args.tags)
        if args.ids:
            # prefix 前方一致サポート
            all_ids = {s.id for s in all_nodes}
            for prefix in args.ids:
                matched = {nid for nid in all_ids if nid.startswith(prefix)}
                if not matched:
                    print(f"  WARNING: --ids '{prefix}' に一致するノードなし")
                candidate_ids |= matched

    if not candidate_ids and not args.all:
        print(
            "\n対象ノードが指定されていません。\n"
            "  --all, --tag, --ids のいずれかを指定してください。\n"
            "  (引数なしの場合は全ノードの displacement 統計だけ表示します)\n"
        )
        # 統計だけ表示して終了
        disps = []
        for s in all_nodes:
            d = engine.cache.get_displacement(s.id)
            if d is not None:
                disps.append(float(np.linalg.norm(d)))
        if disps:
            da = np.array(disps)
            print(f"=== displacement 統計 (全 {len(da)} 件) ===")
            print(f"  min={da.min():.4f}  p50={np.median(da):.4f}  "
                  f"p90={np.percentile(da, 90):.4f}  max={da.max():.4f}")
            print(f"  |d| > 1.0: {(da > 1.0).sum()} 件")
            print(f"  |d| > 3.0: {(da > 3.0).sum()} 件")
        await engine.shutdown()
        return

    # --min-displacement フィルタ
    if args.min_displacement > 0.0:
        filtered = set()
        for nid in candidate_ids:
            d = engine.cache.get_displacement(nid)
            norm = float(np.linalg.norm(d)) if d is not None else 0.0
            if norm >= args.min_displacement:
                filtered.add(nid)
        skipped = len(candidate_ids) - len(filtered)
        print(f"  --min-displacement {args.min_displacement}: "
              f"{skipped} 件をスキップ (threshold 未満)")
        candidate_ids = filtered

    target_ids = sorted(candidate_ids & {s.id for s in all_nodes})
    print(f"リセット対象: {len(target_ids)} 件\n")

    if not target_ids:
        print("対象なし。終了します。")
        await engine.shutdown()
        return

    # ----- 統計収集 -----
    pre_disp_norms: list[float] = []
    pre_mass: list[float] = []
    zeros = np.zeros(dim, dtype=np.float32)

    for nid in target_ids:
        d = engine.cache.get_displacement(nid)
        pre_disp_norms.append(float(np.linalg.norm(d)) if d is not None else 0.0)
        s = engine.cache.get_node(nid)
        pre_mass.append(s.mass if s is not None else 1.0)

    da = np.array(pre_disp_norms)
    print("=== リセット前 displacement 統計 ===")
    print(f"  min={da.min():.4f}  p50={np.median(da):.4f}  "
          f"p90={np.percentile(da, 90):.4f}  max={da.max():.4f}")
    if args.also_reset_mass:
        ma = np.array(pre_mass)
        print(f"  mass: min={ma.min():.2f}  median={np.median(ma):.2f}  "
              f"max={ma.max():.2f}  (--also-reset-mass → 全件 1.0 へ)")

    if not args.apply:
        print(
            f"\n[dry-run] {len(target_ids)} 件の displacement/velocity を 0 にリセットします。"
            "\n実際に書き込むには --apply を付けてください。"
        )
        await engine.shutdown()
        return

    # ----- apply -----
    print(f"\n[apply] {len(target_ids)} 件をリセット中 ...")
    t0 = time.time()
    n_done = 0
    for i, nid in enumerate(target_ids):
        engine.cache.set_displacement(nid, zeros.copy())
        engine.cache.set_velocity(nid, zeros.copy())
        if args.also_reset_mass:
            state = engine.cache.get_node(nid)
            if state is not None:
                state.mass = 1.0
                engine.cache.set_node(state, dirty=True)
        n_done += 1
        if (i + 1) % 1000 == 0:
            print(f"  ... {i + 1}/{len(target_ids)}", flush=True)

    print(f"  リセット完了: {n_done} 件 ({time.time() - t0:.1f}s)")
    print("[apply] SQLite に flush 中 ...")
    await engine.cache.flush_to_store(engine.store)
    print("[apply] flush 完了\n")

    print("=== 次のステップ ===")
    print("  1. (推奨) prime_gravity.py で Hooke 均衡への再収束を加速:")
    print("       .venv/bin/python scripts/prime_gravity.py --apply")
    print("  2. virtual FAISS を再構築 (MCP server 起動時に自動実行 or 手動):")
    print("       python -c \"import asyncio; from gaottt.services.runtime import build_engine; "
          "from gaottt.config import GaOTTTConfig; "
          "e=build_engine(GaOTTTConfig.from_config_file()); "
          "asyncio.run(e.startup()); asyncio.run(e.compact(rebuild_faiss=True)); "
          "asyncio.run(e.shutdown())\"")
    print("  3. MCP server / REST server を再起動")

    await engine.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
