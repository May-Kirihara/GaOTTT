"""Measure ambient_recall lateral association mechanisms on production DB.

3-part experiment:
  Part 1: 6 queries × 1 call — lensing fire rate + resonance distribution
  Part 2: 3 consecutive calls (same query) — novelty decay without recently_surfaced
  Part 3: manual recently_surfaced injection — verify Stage 1 decay
"""
from __future__ import annotations

import asyncio
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gaottt.config import GaOTTTConfig
from gaottt.services.runtime import build_engine
from gaottt.services.memory import ambient_recall


async def main():
    cfg = GaOTTTConfig()
    print(f"DB: {cfg.db_path}", file=sys.stderr)
    engine = build_engine(cfg)
    await engine.startup()
    print(f"Cache nodes: {len(engine.cache.nodes)}", file=sys.stderr)

    try:
        # ── Part 1 ──────────────────────────────────────────
        queries_p1 = [
            "Phase L hybrid retrieval BM25 RRF",
            "GaOTTT の重力場と TTT 機構の関係",
            "Phase M Mass Conservation の self-force filter",
            "persona-anchored seed boost と heavy persona dominance",
            "Phase O TTT observability の ScoreBreakdown",
            "harakiriworks-art-website の Speckit ワークフロー",
        ]

        p1_gate_suppressed = 0
        p1_lensing_counts = {0: 0, 1: 0, 2: 0}
        p1_resonances: list[float] = []
        p1_personas: list[str] = []

        print("\n=== Part 1 ===", file=sys.stderr)
        for q in queries_p1:
            resp = await ambient_recall(
                engine, query=q, direct_k=2, expose_breakdown=True,
            )
            if resp.count == 0:
                p1_gate_suppressed += 1
                p1_lensing_counts[0] += 1
                p1_personas.append("(gate-suppressed)")
                print(f"  [{q[:40]}] GATE SUPPRESSED", file=sys.stderr)
                continue

            n_lens = len(resp.lensing)
            p1_lensing_counts[n_lens] += 1

            for lm in resp.lensing:
                if lm.lensing_resonance is not None:
                    p1_resonances.append(lm.lensing_resonance)

            persona_tag = ""
            if resp.persona:
                persona_tag = f"{resp.persona.kind}: {resp.persona.content[:20]}"
            else:
                persona_tag = "(no persona)"
            p1_personas.append(persona_tag)

            d0_memo = resp.direct[0].excerpt[:30] if resp.direct else "(none)"
            print(
                f"  [{q[:40]}] direct={len(resp.direct)} lensing={n_lens} "
                f"persona={persona_tag[:30]} d0={d0_memo}",
                file=sys.stderr,
            )

        print("\nPart 1 集計:")
        print(f"  Gate-suppressed: {p1_gate_suppressed}/6")
        print(f"  Lensing 0 picks: {p1_lensing_counts[0]}/6, "
              f"1 picks: {p1_lensing_counts[1]}/6, "
              f"2 picks: {p1_lensing_counts[2]}/6")
        print(f"  Resonance 値の生リスト: {p1_resonances}")
        print(f"  Persona slot (per query):")
        for i, q in enumerate(queries_p1):
            print(f"    {i+1}. {q[:50]}: {p1_personas[i]}")

        unique_personas = set(p for p in p1_personas if p not in ("(no persona)", "(gate-suppressed)"))
        fixed = len(unique_personas) <= 1
        print(f"  Persona 固定? {fixed} (unique={len(unique_personas)})")

        # ── Part 2 ──────────────────────────────────────────
        print("\n=== Part 2 ===", file=sys.stderr)
        q2 = "Phase L hybrid retrieval について教えて"
        p2_directs: list[list[str]] = []

        for call_i in range(3):
            resp = await ambient_recall(engine, query=q2, direct_k=2)
            d0 = resp.direct[0].excerpt[:25] if len(resp.direct) > 0 else "(none)"
            d1 = resp.direct[1].excerpt[:25] if len(resp.direct) > 1 else "(none)"
            p2_directs.append([d0, d1])
            print(f"  call {call_i+1}: 1={d0}  2={d1}", file=sys.stderr)

        rotation = p2_directs[0][0] != p2_directs[1][0] or p2_directs[0][0] != p2_directs[2][0]

        print("\nPart 2 (3 連続):")
        for i in range(3):
            print(f"  call {i+1}: 1={p2_directs[i][0]}, 2={p2_directs[i][1]}")
        print(f"  Direct slot rotation: {rotation}")

        # ── Part 3 ──────────────────────────────────────────
        print("\n=== Part 3 ===", file=sys.stderr)
        resp0 = await ambient_recall(engine, query=q2, direct_k=2)
        if resp0.direct:
            id1 = resp0.direct[0].memory_id
            id1_excerpt = resp0.direct[0].excerpt[:25]
        else:
            print("  Part 3: no direct hits, cannot proceed", file=sys.stderr)
            await engine.shutdown()
            return

        print(f"  Decayed id: {id1[:8]}… (excerpt: {id1_excerpt})", file=sys.stderr)

        resp3 = await ambient_recall(
            engine, query=q2, direct_k=2,
            recently_surfaced={id1: 1},
        )
        new_d0 = resp3.direct[0].excerpt[:25] if resp3.direct else "(none)"
        new_d0_id = resp3.direct[0].memory_id if resp3.direct else ""
        rotation3 = new_d0_id != id1

        print(f"  New direct[0]: {new_d0}", file=sys.stderr)

        print("\nPart 3 (manual decay):")
        print(f"  Decayed id: {id1[:8]}…")
        print(f"  New direct[0]: {new_d0}")
        print(f"  Rotation occurred: {rotation3}")

    finally:
        await engine.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
