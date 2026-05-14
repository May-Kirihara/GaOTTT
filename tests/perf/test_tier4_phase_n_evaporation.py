"""Tier 4 — Phase N candidate β Stage 1 mass evaporation dynamics.

Real RURI, real corpus. Three contracts:

A. **Co-existence with Phase I Stage 2 driven resonance** — evaporation
   enabled MUST NOT break the mass-accumulator contract that
   ``test_tier4_phase_o_resonance.py`` locked in. Recall keeps the node
   active enough that t_idle < τ_grace, so evap never fires during a
   tight resonance loop. (Track A's regression cohort stays green even
   with Phase N β in the mix.)

B. **Monotonic decay under simulated aging** — rewinding ``last_access``
   on a node and then re-touching it via recall produces a strictly
   smaller mass than the un-aged path with the same recall pattern.

C. **Floor saturation** — extreme aging (1000× τ_idle) settles a node
   at exactly ``mass_evaporation_floor`` after lazy evap, regardless of
   the Hebbian growth that lands on top.

All tests use the perf-suite's shared RURI singleton via
``tests.perf._helpers.make_engine``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gaottt.services import memory as mem_svc
from tests.perf._helpers import make_engine


GOLDEN_DIR = Path(__file__).parent / "golden_corpus"
CHUNKS_PATH = GOLDEN_DIR / "synthetic_chunks.jsonl"

RESONANCE_QUERY = "Eleventy Pipeline"
TOP_K = 5

# Fast-clock evaporation config — short τ_idle / τ_grace so a few
# seconds of aging produce visible decay in the test timeframe.
FAST_EVAP_OVERRIDES = dict(
    mass_evaporation_enabled=True,
    mass_evaporation_floor=1.0,
    mass_evaporation_grace_seconds=0.0,
    mass_evaporation_idle_normalize_seconds=1.0,
    mass_evaporation_rate=0.05,
    mass_evaporation_mass_exponent=1.5,
    mass_evaporation_time_exponent=1.0,
)


def _load_chunks() -> list[dict]:
    with CHUNKS_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


async def _ingest_corpus(eng):
    chunks = _load_chunks()
    documents = [
        {
            "content": c["content"],
            "metadata": {
                "source": c.get("source", "synthetic"),
                "tags": c.get("tags", []),
                "golden_fixture_id": c["id"],
            },
        }
        for c in chunks
    ]
    return await eng.index_documents(documents)


@pytest.mark.asyncio
async def test_evaporation_does_not_break_driven_resonance(tmp_path):
    """Phase O Stage 2 driven resonance still works with Phase N β enabled.

    Recall in a tight loop keeps t_idle small, so evaporation never fires
    on the hot node. Mass should still accumulate monotonically across the
    three recalls just like in ``test_tier4_phase_o_resonance.py``.
    """
    eng = make_engine(
        tmp_path,
        query_kick_enabled=True,
        query_kick_strength=0.05,
        training_delta_enabled=True,
        # Phase N β on, but with a real-time grace so back-to-back recalls
        # stay inside it.
        mass_evaporation_enabled=True,
        mass_evaporation_grace_seconds=60.0,
        mass_evaporation_idle_normalize_seconds=60.0,
        mass_evaporation_rate=0.05,
    )
    await eng.startup()
    try:
        await _ingest_corpus(eng)
        top1_id: str | None = None
        deltas: list[float] = []
        for _ in range(3):
            r = await mem_svc.recall(
                engine=eng, query=RESONANCE_QUERY, top_k=TOP_K,
                force_refresh=True, auto_route=False,
            )
            assert r.items
            assert r.training_delta is not None
            if top1_id is None:
                top1_id = r.items[0].id
            deltas.append(r.training_delta.mass_changes[top1_id])

        # Same lower-bound contract Track A uses: every recall pushes Δmass forward.
        for i, d in enumerate(deltas):
            assert d >= 1e-4, (
                f"Driven resonance broken by Phase N β: recall #{i+1} "
                f"Δmass={d:.6f} below floor — evaporation likely fired during grace."
            )
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_aged_node_mass_strictly_decreases_vs_fresh(tmp_path):
    """Same recall pattern, but one engine sees an artificially aged
    node before the final recall. The aged engine's final mass must be
    strictly smaller — proving evaporation actually fires through the
    real-RURI seed/wave path.
    """
    eng = make_engine(tmp_path, **FAST_EVAP_OVERRIDES)
    await eng.startup()
    try:
        await _ingest_corpus(eng)
        for _ in range(3):
            await mem_svc.recall(
                engine=eng, query=RESONANCE_QUERY, top_k=TOP_K,
                force_refresh=True, auto_route=False,
            )
        r = await mem_svc.recall(
            engine=eng, query=RESONANCE_QUERY, top_k=1,
            force_refresh=True, auto_route=False,
        )
        target_id = r.items[0].id
        target_state = eng.cache.get_node(target_id)
        mass_warm = target_state.mass
        assert mass_warm > 1.0

        # Age the target.
        target_state.last_access -= 100.0  # 100× τ_idle
        eng.cache.set_node(target_state, dirty=True)

        # Touch via recall — lazy evap fires before the new Hebbian growth.
        await mem_svc.recall(
            engine=eng, query=RESONANCE_QUERY, top_k=TOP_K,
            force_refresh=True, auto_route=False,
        )
        mass_aged = eng.cache.get_node(target_id).mass
        assert mass_aged < mass_warm, (
            f"Aged-then-recalled mass {mass_aged:.4f} is not lower than "
            f"warm-only mass {mass_warm:.4f} — evaporation didn't fire "
            f"through the real recall path."
        )
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_extreme_aging_clamps_at_floor(tmp_path):
    """A node aged 1000× τ_idle settles to floor on next touch, regardless
    of subsequent Hebbian growth.

    This is the "cold legacy hub" scenario — Phase N β's whole reason to
    exist. The lazy hook applies first, clamps the mass to floor, then
    the Hebbian step adds a small amount on top.
    """
    eng = make_engine(
        tmp_path,
        **{**FAST_EVAP_OVERRIDES, "mass_evaporation_rate": 1.0},  # extreme decay
    )
    await eng.startup()
    try:
        await _ingest_corpus(eng)
        # Pull a target into the cache via a normal recall.
        r = await mem_svc.recall(
            engine=eng, query=RESONANCE_QUERY, top_k=1,
            force_refresh=True, auto_route=False,
        )
        target_id = r.items[0].id

        # Force the target's mass high and age it extremely.
        target_state = eng.cache.get_node(target_id)
        target_state.mass = 20.0          # Heavy hub-like value
        target_state.last_access -= 1000.0
        eng.cache.set_node(target_state, dirty=True)

        # Touch.
        await mem_svc.recall(
            engine=eng, query=RESONANCE_QUERY, top_k=TOP_K,
            force_refresh=True, auto_route=False,
        )
        final_mass = eng.cache.get_node(target_id).mass

        # After lazy evap clamps at floor=1.0, the Hebbian step adds at most
        # `eta · force · (1 - 1/m_max)` ≈ small. Final mass is bounded above
        # by floor + small Hebbian increment.
        assert final_mass >= eng.config.mass_evaporation_floor
        assert final_mass < 2.0, (
            f"Extreme aging didn't clamp: final mass {final_mass:.4f} "
            f"on a node aged 1000× τ_idle. Lazy hook may be skipping."
        )
    finally:
        await eng.shutdown()
