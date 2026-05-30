"""Phase Q — Orbital Mechanics, Tier 4 (real-RURI) production-grade invariants.

This is the real-RURI perf-suite counterpart of the synthetic Stage 3 unit
suite (``tests/unit/test_phase_q_orbital.py``) and the StubEmbedder Stage 2
integration suite (``tests/integration/test_engine_phase_q_orbital_tick.py``).
Where those assert the gravity math and the engine wiring on deterministic toy
embeddings, this drives the **continuous orbital tick over a real RURI-embedded
corpus** and asserts the three invariants the plan promised at production
scale:

1. **Boundedness / stability** — under the full orbit force stack (tangential
   seed + velocity-Verlet + small constant friction + mass-dependent anchor β +
   *real* neighbor gravity), the continuous tick keeps displacement ≤
   ``max_displacement_norm`` and velocity ≤ ``orbital_max_velocity``, with no
   NaN/inf and genuine motion. This is the orbit-mode counterpart of
   ``test_displacement_stays_in_physical_bounds`` (the relax-mode runaway guard)
   and reproduces the Stage 3 honest finding — neighbor gravity's 1/r² close
   encounters need the displacement clamp — on real embedding geometry.
2. **Closed ellipse** — a node seeded with tangential velocity orbits its *own*
   real anchor (|d| oscillates between r_min > 0 and a bounded r_max) instead of
   collapsing through the origin (the radial-only straight line) or running
   away. Exercises the whole tick path end-to-end at real scale: lively filter →
   ``faiss_index.get_vectors`` (real anchor per node) → ``update_orbital_state``
   Verlet → cache write-back.
3. **Self-limiting lively set** — the §2.1 computational-cost safety valve: the
   tick injects no energy (only recall does), so with constant friction the
   lively set ``|v| > orbital_lively_v_min`` shrinks over time and the O(L²)
   per-tick cost is self-bounding. This is the claim that makes the continuous
   clock affordable on a 40K-node corpus.

All defaults are OFF; these tests opt in to the orbit bundle explicitly. See
docs/wiki/Plans-Phase-Q-Orbital-Mechanics.md §2.1, §3, §4.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from tests.perf._helpers import make_engine


GOLDEN_DIR = Path(__file__).parent / "golden_corpus"
CHUNKS_PATH = GOLDEN_DIR / "synthetic_chunks.jsonl"


def _load_chunks() -> list[dict]:
    with CHUNKS_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


async def _ingest_corpus(eng) -> list[str]:
    """Ingest the real-RURI golden corpus; return the engine node ids."""
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


def _seed_perpendicular_orbits(eng, ids, *, r: float, speed: float) -> None:
    """Seed each id with displacement along one axis and velocity along a
    *different* axis (perpendicular) so angular momentum L = d × v ≠ 0 and the
    node traces an ellipse about its own anchor rather than a straight line
    through it. Deterministic — no RNG — so the golden-corpus run stays
    reproducible (project rule: no random in fixtures)."""
    dim = eng.config.embedding_dim
    for i, nid in enumerate(ids):
        a = (2 * i) % dim
        b = (2 * i + 1) % dim
        if b == a:
            b = (a + 1) % dim
        d = np.zeros(dim, dtype=np.float32)
        d[a] = r
        v = np.zeros(dim, dtype=np.float32)
        v[b] = speed
        eng.cache.set_displacement(nid, d)
        eng.cache.set_velocity(nid, v)


def _cool(eng, ids) -> None:
    """Force the given ids fully cold (zero displacement + velocity) so they
    stay out of the lively set."""
    dim = eng.config.embedding_dim
    z = np.zeros(dim, dtype=np.float32)
    for nid in ids:
        eng.cache.set_displacement(nid, z.copy())
        eng.cache.set_velocity(nid, z.copy())


def _lively_count(eng, ids, v_min: float) -> int:
    n = 0
    for nid in ids:
        v = eng.cache.get_velocity(nid)
        if v is not None and float(np.linalg.norm(v)) > v_min:
            n += 1
    return n


# ---------------------------------------------------------------------------
# 1. Boundedness / stability of the continuous tick on real geometry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_orbit_tick_clamp_bounds_enabled_neighbor_gravity(tmp_path):
    """With tick neighbor gravity EXPLICITLY enabled, the continuous tick over
    the real RURI-embedded corpus stays inside its physical clamps and never
    diverges — the ``max_displacement_norm`` clamp is the runaway backstop.

    Rollout finding (2026-05-30, isolated copy of the 41K production field):
    ``_orbital_tick`` hands the *lively set itself* to update_orbital_state as
    the N-body neighbours. In RURI's narrow high-cosine space those neighbour-
    gravity vectors point alike and sum *coherently* (measured net |a|~10–640 vs
    the anchor's ~0.005), so neighbour gravity dominates and drives displacement
    hard onto the clamp rather than gently perturbing the orbit. Because that
    regime is unsafe for production, neighbour gravity in the tick is OFF by
    default (pure self-anchor — see the ellipse / self-limiting tests below).
    This test pins the *enabled* path: even under the coherent-sum blow-up the
    finite clamp holds (no NaN/inf, displacement <= max_displacement_norm,
    velocity <= orbital_max_velocity, and the set genuinely moves). It is the
    orbit-mode counterpart of the relax-mode
    ``test_displacement_stays_in_physical_bounds``."""
    eng = make_engine(
        tmp_path,
        genesis_kick_enabled=False,       # control the seed explicitly
        orbital_tick_enabled=True,
        orbital_tick_neighbor_gravity_enabled=True,  # exercise the coupled path
        orbital_integrator="verlet",
        orbital_tangential_alpha=0.8,     # angular momentum (knob is documented)
        orbital_friction=0.005,           # recommended orbit-bundle friction
        orbital_max_velocity=0.05,        # production velocity clamp (under test)
        orbital_anchor_strength=0.02,
        mass_anchor_extra_strength=1.0,   # β enabled — mass-dependent anchor
        mass_anchor_threshold=3.0,
        max_displacement_norm=2.0,        # finite runaway backstop (§4, required)
        orbital_lively_v_min=0.001,
        dream_interval_seconds=999.0,     # background loop never fires; we drive
    )
    await eng.startup()
    try:
        ids = await _ingest_corpus(eng)
        assert len(ids) >= 5, "need a non-trivial N-body set for real chaos"

        # Strong, established masses so neighbor gravity is a real perturbation
        # (heavy bodies → 1/r² close encounters), exercising the displacement
        # clamp as the runaway backstop rather than a decorative cap.
        for nid in ids:
            st = eng.cache.get_node(nid)
            if st is not None:
                st.mass = 5.0
                eng.cache.set_node(st, dirty=True)

        _seed_perpendicular_orbits(eng, ids, r=0.4, speed=0.03)
        seed_disp = {nid: eng.cache.get_displacement(nid).copy() for nid in ids}

        max_disp = 0.0
        max_vel = 0.0
        for _ in range(300):
            eng._orbital_tick()
            for nid in ids:
                d = eng.cache.get_displacement(nid)
                v = eng.cache.get_velocity(nid)
                assert np.all(np.isfinite(d)), f"{nid} displacement went non-finite"
                assert np.all(np.isfinite(v)), f"{nid} velocity went non-finite"
                max_disp = max(max_disp, float(np.linalg.norm(d)))
                max_vel = max(max_vel, float(np.linalg.norm(v)))

        # Runaway backstop holds: no node ever crosses the displacement clamp.
        assert max_disp <= eng.config.max_displacement_norm + 1e-5, (
            f"displacement clamp breached: {max_disp} > "
            f"{eng.config.max_displacement_norm}"
        )
        # Velocity clamp holds throughout (no per-step amplification).
        assert max_vel <= eng.config.orbital_max_velocity + 1e-6, (
            f"velocity clamp breached: {max_vel} > {eng.config.orbital_max_velocity}"
        )
        # The tick did real work — the lively set genuinely moved off its seed.
        moved = any(
            not np.allclose(eng.cache.get_displacement(nid), seed_disp[nid])
            for nid in ids
        )
        assert moved, "no node moved — the continuous tick is a silent no-op"
    finally:
        await eng.shutdown()


# ---------------------------------------------------------------------------
# 2. Closed ellipse around the node's own real anchor
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_orbit_tick_traces_closed_ellipse_on_real_anchors(tmp_path):
    """Seeded with a tangential velocity, a node orbits its own real RURI anchor
    as a bounded ellipse: |d| oscillates between a non-zero minimum (it never
    falls through the origin, which a purely radial L=0 seed would) and a
    bounded maximum near the semi-major axis.

    Neighbor gravity is isolated (``gravity_G=0``) so the only central force is
    the node's own Hooke anchor — the Bertrand harmonic limit — making the
    expected ellipse analytic (same isolation as the unit suite). This is also
    the **production-default tick regime** post-rollout-fix: with
    ``orbital_tick_neighbor_gravity_enabled=False`` (default) the tick zeroes
    gravity_G internally, so a default tick on any field is exactly this pure
    self-anchor orbit. The value here is the *end-to-end tick path* on real
    anchors: ``_orbital_tick`` must read the right anchor per node from FAISS,
    integrate it with velocity-Verlet, and write it back, yielding a genuine
    orbit (not drift, not collapse)."""
    omega = math.sqrt(0.02)
    r = 0.4
    vt = 0.3 * omega          # semi-minor ≈ vt/ω = 0.3, semi-major = r = 0.4
    period = 2 * math.pi / omega

    eng = make_engine(
        tmp_path,
        genesis_kick_enabled=False,
        orbital_tick_enabled=True,
        orbital_integrator="verlet",
        gravity_G=0.0,                    # isolate the harmonic anchor
        orbital_friction=0.0,             # conservative → persistent ellipse
        orbital_max_velocity=1.0,         # well above the orbital speed (no clip)
        orbital_anchor_strength=0.02,
        mass_anchor_extra_strength=0.0,   # β off → k_eff = k constant
        max_displacement_norm=50.0,       # effectively free (avoids §4 warning)
        orbital_lively_v_min=0.0001,
        dream_interval_seconds=999.0,
    )
    await eng.startup()
    try:
        ids = await _ingest_corpus(eng)
        # A small lively set (≥2 required by update_orbital_state); the rest cold.
        orbit_ids = ids[:4]
        _cool(eng, ids)
        _seed_perpendicular_orbits(eng, orbit_ids, r=r, speed=vt)

        # Track per-node min/max radius over ~1.2 periods.
        rmin = {nid: math.inf for nid in orbit_ids}
        rmax = {nid: 0.0 for nid in orbit_ids}
        for _ in range(int(period * 1.2)):
            eng._orbital_tick()
            for nid in orbit_ids:
                rn = float(np.linalg.norm(eng.cache.get_displacement(nid)))
                rmin[nid] = min(rmin[nid], rn)
                rmax[nid] = max(rmax[nid], rn)

        for nid in orbit_ids:
            # Ellipse, not a line through the origin: r_min stays well above 0
            # (analytic semi-minor ≈ 0.3).
            assert rmin[nid] > 0.15, (
                f"{nid} collapsed toward the origin (r_min={rmin[nid]:.3f}) — "
                "tangential seed lost, orbit degenerated to a radial line"
            )
            # Bounded near the semi-major axis (analytic ≈ 0.4).
            assert rmax[nid] < 0.6, (
                f"{nid} unbounded (r_max={rmax[nid]:.3f}) — orbit not closed"
            )
    finally:
        await eng.shutdown()


# ---------------------------------------------------------------------------
# 3. Friction self-limits the lively set (§2.1 cost safety-valve)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_orbit_tick_friction_self_limits_lively_set(tmp_path):
    """The continuous tick injects no energy, so constant friction must return
    kicked nodes to "cold" — bounding the lively set ``L`` and with it the
    O(L²) per-tick cost. This is the §2.1 safety valve that makes the continuous
    clock affordable: #2 (a little friction) is the very thing that keeps #1
    (continuous integration) cheap.

    Neighbor gravity is isolated so each seeded node is an independent damped
    harmonic oscillator about its real anchor; friction (0.005/step) bleeds the
    orbital energy E = ½|v|² + ½k|d|² monotonically in trend. We assert that the
    initially-lively set shrinks to empty over the horizon and that its total
    energy has net-decayed."""
    k = 0.02
    eng = make_engine(
        tmp_path,
        genesis_kick_enabled=False,
        orbital_tick_enabled=True,
        orbital_integrator="verlet",
        gravity_G=0.0,                    # isolate friction's effect on the well
        orbital_friction=0.005,           # the recommended orbit-bundle friction
        orbital_max_velocity=1.0,
        orbital_anchor_strength=k,
        mass_anchor_extra_strength=0.0,   # β off → clean E bookkeeping (k const)
        max_displacement_norm=50.0,
        orbital_lively_v_min=0.001,
        dream_interval_seconds=999.0,
    )
    await eng.startup()
    try:
        ids = await _ingest_corpus(eng)
        live_ids = ids[:6]                # a small lively set; the rest cold
        _cool(eng, ids)
        # speed=0.01 (10× v_min) is a kicked-but-modest orbit; under friction
        # 0.005 it crosses v_min at ~955 ticks (measured), so 1500 ticks drains
        # it cold with margin. A bigger kick just needs proportionally longer.
        _seed_perpendicular_orbits(eng, live_ids, r=0.4, speed=0.01)

        v_min = eng.config.orbital_lively_v_min

        def total_energy() -> float:
            e = 0.0
            for nid in live_ids:
                d = eng.cache.get_displacement(nid)
                v = eng.cache.get_velocity(nid)
                e += 0.5 * float(np.dot(v, v)) + 0.5 * k * float(np.dot(d, d))
            return e

        start_lively = _lively_count(eng, live_ids, v_min)
        start_energy = total_energy()
        assert start_lively == len(live_ids), "seed should make all of them lively"

        # Run past the measured ticks-to-cold (~955) with margin so the whole
        # in-phase set drains below v_min and freezes out of the lively set.
        for _ in range(1500):
            eng._orbital_tick()

        end_lively = _lively_count(eng, live_ids, v_min)
        end_energy = total_energy()

        # The lively set self-limited: friction returned the kicked nodes to cold.
        assert end_lively < start_lively, (
            f"lively set did not shrink ({start_lively} → {end_lively}); "
            "friction is not bounding L → the continuous tick is not self-limiting"
        )
        assert end_lively == 0, (
            f"{end_lively} nodes still lively after 1500 ticks — friction too weak "
            "to drain the orbit (M would not bound on a real corpus)"
        )
        # Net energy dissipation (thermodynamic slow-spiral-inward end state).
        assert end_energy < start_energy * 0.1, (
            f"orbital energy barely bled: {start_energy:.4g} → {end_energy:.4g}"
        )
    finally:
        await eng.shutdown()
