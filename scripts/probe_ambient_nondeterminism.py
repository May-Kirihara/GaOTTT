"""Probe — localize the source of direct-slot non-determinism in ambient_recall.

Lateral Association Plan, Stage 1 sub-step 0 (Plans-Ambient-Recall-Lateral-Association.md).

Hypothesis under test:
  H1 (return_count side-effect) — passive=True suppresses mass/displacement/
     co-occurrence updates, BUT `state.return_count` is incremented for the
     top-K presented nodes and decayed for all reached nodes (engine.py
     ~1015-1033, NOT gated by `passive`). `saturation = 1 / (1 + return_count
     * saturation_rate)` multiplies into final_score (engine.py ~891), so each
     ambient call drops the saturation of the just-surfaced nodes and the next
     call ranks a different top-K. This is the dominant source of direct-slot
     rotation.

  H2 (multi_source segmentation) — deterministic regex split, ruled out by
     reading segment_query (gaottt/core/segmentation.py). Listed for completeness.

  H3 (RRF / set iteration) — dict iteration is insertion-ordered, `sorted` is
     stable. Deterministic given identical inputs. Listed for completeness.

  H4 (time-based decay micro-shift) — `decay = compute_decay(state.last_access,
     now, ...)`. passive recall DOES NOT update `state.last_access`
     (_update_simulation is gated). So `last_access` is stable across calls,
     and `now` advances by ~0.1s/call. compute_decay over ~0.1s is essentially
     1.0; effect should be below ranking noise.

Procedure:
  Identical engine + corpus + query, 3 consecutive ambient_recall calls.
  Between calls, dump:
    - top-K direct ids
    - per-id (return_count, saturation, final_score, raw_score)
  Then run a controlled experiment:
    - Reset return_count to 0 between calls.
    - If direct slot composition becomes STABLE → H1 confirmed.

Run:
  .venv/bin/python scripts/probe_ambient_nondeterminism.py
"""
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from gaottt.services import memory as memory_service
from tests.perf._helpers import make_engine


CORPUS_PATH = (
    Path(__file__).resolve().parents[1]
    / "tests/perf/golden_corpus/ambient_corpus.jsonl"
)
QUERY = "Phase L Stage 1 の hybrid retrieval について教えて"
DIRECT_K = 2


def _load_corpus() -> list[dict]:
    with CORPUS_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


async def _seed_engine(eng):
    corpus = _load_corpus()
    docs = [
        {
            "content": c["content"],
            "metadata": {
                "source": c["source"],
                "tags": c.get("tags", []),
                "ambient_fixture_id": c["id"],
            },
        }
        for c in corpus
    ]
    engine_ids = await eng.index_documents(docs)
    return dict(zip([c["id"] for c in corpus], engine_ids))


def _snapshot_state(eng, ids):
    """Capture (return_count, saturation, last_access) for given node ids."""
    snap = {}
    for nid in ids:
        s = eng.cache.get_node(nid)
        if s is None:
            continue
        rc = s.return_count
        sat = 1.0 / (1.0 + rc * eng.config.saturation_rate)
        snap[nid] = {
            "return_count": rc,
            "saturation": sat,
            "last_access": s.last_access,
            "mass": s.mass,
        }
    return snap


async def _run_one_call(eng, label, prev_snap=None):
    """Run ambient_recall once and print a diff vs prev_snap."""
    resp = await memory_service.ambient_recall(
        eng, query=QUERY, direct_k=DIRECT_K, expose_breakdown=True,
    )
    direct = resp.direct
    direct_ids = [m.id for m in direct]
    snap = _snapshot_state(eng, direct_ids)
    print(f"\n[{label}] direct top-{DIRECT_K}:")
    for m in direct:
        bd = m.breakdown
        sat_now = snap[m.id]["saturation"]
        rc_now = snap[m.id]["return_count"]
        sat_prev = None
        rc_prev = None
        if prev_snap and m.id in prev_snap:
            sat_prev = prev_snap[m.id]["saturation"]
            rc_prev = prev_snap[m.id]["return_count"]
        prev_str = (
            f" (prev: rc={rc_prev:.3f} sat={sat_prev:.4f})"
            if rc_prev is not None else ""
        )
        bd_sat = bd.saturation if bd is not None else "N/A"
        print(
            f"  id={m.id[:8]}…  raw={m.virtual_score:.4f}  "
            f"final={m.final_score:.4f}  bd_sat={bd_sat:.4f}  "
            f"rc={rc_now:.3f} sat={sat_now:.4f}{prev_str}"
        )
    return direct_ids, snap


async def _experiment_natural(eng):
    """3 consecutive calls, no intervention. Baseline reproduction."""
    print("\n" + "=" * 70)
    print("EXPERIMENT A — natural (no intervention)")
    print("=" * 70)
    prev = None
    seen = []
    for i in range(3):
        ids, snap = await _run_one_call(eng, f"call {i+1}", prev)
        seen.append(tuple(ids))
        prev = snap
    print(f"\n  Direct composition across 3 calls: {seen}")
    print(f"  Unique compositions: {len(set(seen))}")
    return seen


async def _experiment_reset_return_count(eng, doc_ids):
    """3 consecutive calls, with return_count reset to 0 between each.

    If direct composition becomes stable → H1 (return_count saturation) is
    confirmed as the dominant source.
    """
    print("\n" + "=" * 70)
    print("EXPERIMENT B — return_count forcibly reset to 0 before each call")
    print("=" * 70)
    seen = []
    for i in range(3):
        # Reset return_count for every cached node before the call.
        for nid in doc_ids:
            s = eng.cache.get_node(nid)
            if s is not None:
                s.return_count = 0.0
                eng.cache.set_node(s, dirty=True)
        ids, _snap = await _run_one_call(eng, f"call {i+1} (rc reset)")
        seen.append(tuple(ids))
    print(f"\n  Direct composition across 3 calls (rc reset): {seen}")
    print(f"  Unique compositions: {len(set(seen))}")
    return seen


async def main():
    with tempfile.TemporaryDirectory() as tmp:
        eng = make_engine(
            Path(tmp),
            ambient_gate_use_bm25=False,
            ambient_min_score=0.0,
            persona_boost_enabled=True,
            wave_initial_k=12,
        )
        await eng.startup()
        try:
            print("Probe: ambient_recall direct-slot non-determinism")
            print(f"  query: {QUERY!r}")
            print(f"  direct_k: {DIRECT_K}")

            fixture_to_engine = await _seed_engine(eng)
            doc_ids = list(fixture_to_engine.values())

            natural = await _experiment_natural(eng)
            controlled = await _experiment_reset_return_count(eng, doc_ids)

            print("\n" + "=" * 70)
            print("VERDICT")
            print("=" * 70)
            nat_unique = len(set(natural))
            ctrl_unique = len(set(controlled))
            print(f"  Natural unique compositions:     {nat_unique}")
            print(f"  rc-reset unique compositions:    {ctrl_unique}")
            if nat_unique > 1 and ctrl_unique == 1:
                print(
                    "  → H1 CONFIRMED: return_count accumulation drives the "
                    "direct-slot rotation. With return_count pinned at 0, the "
                    "composition is stable."
                )
            elif nat_unique > 1 and ctrl_unique > 1:
                print(
                    "  → H1 NOT FULLY EXPLANATORY: residual non-determinism "
                    "remains even after return_count reset. Inspect further."
                )
            elif nat_unique == 1:
                print(
                    "  → BASELINE NOT REPRODUCED in this fixture. The natural "
                    "experiment was already stable — fixture corpus may be "
                    "too small for the rotation pressure to fire."
                )
        finally:
            await eng.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
