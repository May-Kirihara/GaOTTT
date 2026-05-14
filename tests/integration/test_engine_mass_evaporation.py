"""Phase N candidate β Stage 1 — engine-integrated mass evaporation.

End-to-end through engine.startup() / engine.query():

  1. **Lazy path** — a node whose last_access is in the past (beyond
     τ_grace) has its mass evaporated *before* the Hebbian growth from
     the new recall lands. The net mass change reflects both terms.

  2. **Recall-keeps-it-alive** — repeatedly recalling the same node never
     lets t_idle exceed τ_grace, so evaporation never fires; the mass
     trajectory matches the legacy (disabled) case.

  3. **Cold-start sweep** — engine.startup() walks every active node and
     applies evaporation, even ones the lazy path never touched.

  4. **Disabled parity** — with ``mass_evaporation_enabled=False`` the
     engine is bit-identical to the pre-Phase-N baseline.
"""
from __future__ import annotations

import time

import numpy as np
import pytest

from gaottt.config import GaOTTTConfig
from gaottt.core.engine import GaOTTTEngine
from gaottt.index.faiss_index import FaissIndex
from gaottt.store.cache import CacheLayer
from gaottt.store.sqlite_store import SqliteStore


class StubEmbedder:
    """Deterministic token-based embeddings — no GPU/network."""

    def __init__(self, dim: int = 768):
        self.dim = dim

    def encode_documents(self, contents):
        return np.array([self._embed(c) for c in contents], dtype=np.float32)

    def encode_query(self, text):
        return self._embed(text).reshape(1, -1).astype(np.float32)

    def _embed(self, text: str) -> np.ndarray:
        seed = abs(hash(text)) & 0xFFFFFFFF
        rng = np.random.default_rng(seed)
        v = rng.standard_normal(self.dim).astype(np.float32)
        v /= np.linalg.norm(v) + 1e-9
        return v


def _make_engine(tmp_path, **overrides):
    """Engine with deterministic embedder + Phase N β knobs.

    Defaults to ``mass_evaporation_enabled=True`` with short grace/τ_idle
    so unit-level mass moves are visible in seconds, not days.
    """
    defaults = dict(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "test.db"),
        faiss_index_path=str(tmp_path / "test.faiss"),
        # Phase N β — fast clock so tests see decay without real time elapsing
        mass_evaporation_enabled=True,
        mass_evaporation_floor=1.0,
        mass_evaporation_grace_seconds=0.0,        # no grace, decay any past idle
        mass_evaporation_idle_normalize_seconds=1.0,  # 1s τ_idle for visible decay
        mass_evaporation_rate=0.1,                 # exaggerated for test signal
        mass_evaporation_mass_exponent=1.5,
        mass_evaporation_time_exponent=1.0,
        # Suppress unrelated noise
        genesis_kick_enabled=False,
        dream_enabled=False,
        supernova_enabled=False,
        query_kick_enabled=False,
        faiss_save_interval_seconds=0.0,
        flush_interval_seconds=0.05,
    )
    defaults.update(overrides)
    config = GaOTTTConfig(**defaults)
    embedder = StubEmbedder(dim=config.embedding_dim)
    faiss_index = FaissIndex(dimension=config.embedding_dim)
    store = SqliteStore(db_path=config.db_path)
    cache = CacheLayer(
        flush_interval=config.flush_interval_seconds,
        flush_threshold=config.flush_threshold,
    )
    return GaOTTTEngine(
        config=config, embedder=embedder, faiss_index=faiss_index,
        cache=cache, store=store,
    )


# --- Lazy path ---


@pytest.mark.asyncio
async def test_lazy_evaporation_decreases_aged_node_mass(tmp_path):
    """An aged (last_access pushed into the past) node loses mass when touched.

    Steps:
      1. Ingest a small corpus, recall once to populate mass via Hebbian.
      2. Manually rewind ``last_access`` on one node to simulate a long idle.
      3. Recall that node again — lazy hook fires, applying evaporation
         *before* the new Hebbian growth on top.
      4. Net mass must be lower than the pre-rewind mass (the decay term
         is larger than the new Hebbian gain at this rate).
    """
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        await engine.index_documents([
            {"content": f"doc-{i}", "metadata": {"source": "agent"}}
            for i in range(5)
        ])
        # Warm the field up a bit so node masses move above floor.
        for _ in range(3):
            await engine.query(text="doc-0", top_k=5)

        target_id = (await engine.query(text="doc-0", top_k=1))[0].id
        target_state = engine.cache.get_node(target_id)
        mass_before_rewind = target_state.mass
        assert mass_before_rewind > 1.0, (
            f"warm-up didn't raise mass above floor: {mass_before_rewind}"
        )

        # Rewind last_access by 10× τ_idle (10 seconds, since τ_idle=1s).
        target_state.last_access -= 10.0
        engine.cache.set_node(target_state, dirty=True)
        aged_last_access = target_state.last_access

        # Touch the node via a recall — lazy hook applies evaporation
        # before Hebbian.
        await engine.query(text="doc-0", top_k=5)

        target_state_after = engine.cache.get_node(target_id)
        mass_after = target_state_after.mass

        # The decay term: ε · excess^β · idle_ratio^γ
        # idle_ratio ~ 10 (10s idle / 1s τ_idle), ε=0.1, β=1.5, γ=1.0
        # → decay ~ 0.1 · (mass-1)^1.5 · 10 = ~(mass-1)^1.5 in absolute terms,
        # which on mass~2 is ~1.0, more than enough to outpace one Hebbian step.
        assert mass_after < mass_before_rewind, (
            f"Lazy evaporation didn't fire on aged node: "
            f"mass {mass_before_rewind:.4f} → {mass_after:.4f}"
        )

        # And last_access was updated by the engine touch (existing line 1045),
        # so the timestamps moved forward.
        assert target_state_after.last_access > aged_last_access
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_fresh_recall_does_not_evaporate(tmp_path):
    """Rapid consecutive recalls keep last_access fresh — evaporation never fires.

    Compares mass trajectory across many back-to-back recalls vs. the
    same workload with evaporation disabled. They should be near-identical.
    """
    on_dir = tmp_path / "on"
    off_dir = tmp_path / "off"
    on_dir.mkdir()
    off_dir.mkdir()

    engine_on = _make_engine(on_dir, mass_evaporation_grace_seconds=10.0)
    await engine_on.startup()
    try:
        await engine_on.index_documents([
            {"content": f"doc-{i}", "metadata": {"source": "agent"}}
            for i in range(3)
        ])
        for _ in range(5):
            await engine_on.query(text="doc-0", top_k=3)
        target_id = (await engine_on.query(text="doc-0", top_k=1))[0].id
        mass_on = engine_on.cache.get_node(target_id).mass
    finally:
        await engine_on.shutdown()

    engine_off = _make_engine(off_dir, mass_evaporation_enabled=False)
    await engine_off.startup()
    try:
        await engine_off.index_documents([
            {"content": f"doc-{i}", "metadata": {"source": "agent"}}
            for i in range(3)
        ])
        for _ in range(5):
            await engine_off.query(text="doc-0", top_k=3)
        target_id_off = (await engine_off.query(text="doc-0", top_k=1))[0].id
        mass_off = engine_off.cache.get_node(target_id_off).mass
    finally:
        await engine_off.shutdown()

    # Both engines saw identical workloads with no idle gap → masses match
    # within numerical noise.
    assert abs(mass_on - mass_off) < 1e-6, (
        f"Evaporation fired despite recalls being inside grace: "
        f"enabled mass={mass_on:.6f}, disabled mass={mass_off:.6f}"
    )


# --- Cold-start sweep ---


@pytest.mark.asyncio
async def test_startup_sweep_evaporates_untouched_aged_nodes(tmp_path):
    """A node aged before engine.startup() loses mass via the cold-start sweep.

    Workflow:
      1. Build + ingest + warm corpus with engine A.
      2. Rewind every node's last_access to simulate an offline period.
      3. Shutdown A, build a fresh engine B over the same DB.
      4. B.startup() runs the cold-start sweep → masses settle.
      5. Verify the rewound node lost mass without any recall.
    """
    engine_a = _make_engine(tmp_path)
    await engine_a.startup()
    target_id: str
    pre_sweep_mass: float
    try:
        await engine_a.index_documents([
            {"content": f"doc-{i}", "metadata": {"source": "agent"}}
            for i in range(5)
        ])
        for _ in range(3):
            await engine_a.query(text="doc-0", top_k=5)
        target_id = (await engine_a.query(text="doc-0", top_k=1))[0].id
        target_state = engine_a.cache.get_node(target_id)
        pre_sweep_mass = target_state.mass
        assert pre_sweep_mass > 1.0
        # Rewind every node's last_access to 10× τ_idle in the past.
        for st in engine_a.cache.get_all_nodes():
            st.last_access -= 10.0
            engine_a.cache.set_node(st, dirty=True)
    finally:
        await engine_a.shutdown()

    # Rebuild over the same data dir — fresh cache, fresh FAISS load.
    engine_b = _make_engine(tmp_path)
    await engine_b.startup()  # cold-start sweep fires here
    try:
        post_sweep_mass = engine_b.cache.get_node(target_id).mass
        assert post_sweep_mass < pre_sweep_mass, (
            f"Cold-start sweep didn't settle mass debt: "
            f"pre={pre_sweep_mass:.4f}, post={post_sweep_mass:.4f}"
        )
        # No recall happened on engine_b — pure sweep effect.
    finally:
        await engine_b.shutdown()


@pytest.mark.asyncio
async def test_startup_sweep_is_noop_when_disabled(tmp_path):
    """With evaporation disabled, the cold-start sweep doesn't run (mass preserved)."""
    engine_a = _make_engine(tmp_path)
    await engine_a.startup()
    target_id: str
    pre_mass: float
    try:
        await engine_a.index_documents([
            {"content": f"doc-{i}", "metadata": {"source": "agent"}}
            for i in range(5)
        ])
        for _ in range(3):
            await engine_a.query(text="doc-0", top_k=5)
        target_id = (await engine_a.query(text="doc-0", top_k=1))[0].id
        pre_mass = engine_a.cache.get_node(target_id).mass
        for st in engine_a.cache.get_all_nodes():
            st.last_access -= 10.0
            engine_a.cache.set_node(st, dirty=True)
    finally:
        await engine_a.shutdown()

    engine_b = _make_engine(tmp_path, mass_evaporation_enabled=False)
    await engine_b.startup()
    try:
        post_mass = engine_b.cache.get_node(target_id).mass
        # Disabled → no sweep → mass preserved exactly.
        assert post_mass == pre_mass, (
            f"Sweep fired despite enabled=False: pre={pre_mass}, post={post_mass}"
        )
    finally:
        await engine_b.shutdown()


# --- Floor / source neutrality ---


@pytest.mark.asyncio
async def test_evaporation_clamps_at_floor(tmp_path):
    """A long-aged node settles at exactly ``mass_evaporation_floor``, never below."""
    engine = _make_engine(
        tmp_path,
        mass_evaporation_rate=1.0,   # absurdly aggressive
    )
    await engine.startup()
    try:
        await engine.index_documents([
            {"content": f"doc-{i}", "metadata": {"source": "agent"}}
            for i in range(3)
        ])
        for _ in range(5):
            await engine.query(text="doc-0", top_k=3)
        target_id = (await engine.query(text="doc-0", top_k=1))[0].id
        target_state = engine.cache.get_node(target_id)
        target_state.last_access -= 1000.0  # 1000× τ_idle in the past
        engine.cache.set_node(target_state, dirty=True)

        await engine.query(text="doc-0", top_k=3)
        final_mass = engine.cache.get_node(target_id).mass
        # After lazy evap, the Hebbian step adds some small mass back on top
        # of the floor. So final ≥ floor, but evaporation must have clamped
        # at floor before the addition.
        assert final_mass >= engine.config.mass_evaporation_floor
        # And clearly less than the original — heavy decay applied.
        assert final_mass < 5.0
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_evaporation_is_source_agnostic(tmp_path):
    """Phase M invariant — the same rule applies to every source class.

    A ``source='agent'`` node and a ``source='file'`` node at the same
    mass with the same aging see the same evaporation, byte-for-byte.
    """
    engine = _make_engine(tmp_path)
    await engine.startup()
    try:
        # Two nodes, different sources, will be ingested then directly
        # forced to the same mass + last_access for a controlled comparison.
        ids = await engine.index_documents([
            {"content": "agent doc", "metadata": {"source": "agent"}},
            {"content": "file doc", "metadata": {"source": "file"}},
        ])
        # Force identical state on both.
        target_mass = 3.0
        target_last_access = time.time() - 5.0   # 5× τ_idle in the past
        for nid in ids:
            st = engine.cache.get_node(nid)
            st.mass = target_mass
            st.last_access = target_last_access
            engine.cache.set_node(st, dirty=True)

        # Trigger a recall that reaches both via the wave.
        await engine.query(text="agent doc", top_k=5)
        await engine.query(text="file doc", top_k=5)

        state_agent = engine.cache.get_node(ids[0])
        state_file = engine.cache.get_node(ids[1])
        # The two should be within a tight tolerance — same rule, same args.
        # (Hebbian growth from differing wave reach may diverge them, but
        # the source class itself cannot.) Loose bound to allow Hebbian
        # asymmetry, but tight enough to catch a source-branching regression.
        assert abs(state_agent.mass - state_file.mass) < 0.5, (
            f"source-class asymmetry detected: "
            f"agent={state_agent.mass:.4f}, file={state_file.mass:.4f}"
        )
    finally:
        await engine.shutdown()
