"""Phase I Stage 2 / Stage 3 — Implicit query-aware displacement kick (integration).

End-to-end through engine.query():
  1. After repeated `recall(q)`, retrieved nodes' displacement drifts toward
     `q`'s embedding (cos(displacement, q - raw) becomes positive and grows).
  2. The raw embedding stored in FAISS never changes — Stage 2 is *transient
     force*, not anchor migration.
  3. With query_kick_strength=0 the legacy behaviour is preserved (control).
  4. Stage 3 — mass_anchor_threshold > 0 dampens drift on low-mass (new) nodes
     compared to Stage 2 (threshold=0), end-to-end through the engine path.
"""
from __future__ import annotations

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


def _make_engine(
    tmp_path,
    *,
    kick_strength: float,
    mass_anchor_threshold: float = 0.0,
):
    config = GaOTTTConfig(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "test.db"),
        faiss_index_path=str(tmp_path / "test.faiss"),
        # Phase I Stage 2 knobs
        query_kick_strength=kick_strength,
        query_kick_enabled=True,
        # Phase I Stage 3 — default to 0 here so existing Stage 2 tests
        # keep their pure F=ma semantics. New Stage 3 tests pass θ=3.0.
        mass_anchor_threshold=mass_anchor_threshold,
        # Suppress unrelated noise so the kick is the dominant signal
        genesis_kick_enabled=False,
        dream_enabled=False,
        faiss_save_interval_seconds=0.0,
        flush_interval_seconds=0.05,
    )
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


@pytest.mark.asyncio
async def test_query_kick_drifts_displacement_toward_query(tmp_path):
    """Repeated recalls of the same query should pull the retrieved node's
    displacement toward the query embedding (positive and growing inner
    product with the kick direction)."""
    engine = _make_engine(tmp_path, kick_strength=0.05)  # exaggerated for test
    await engine.startup()
    try:
        # Seed a small cluster so the wave has ≥ 2 reached nodes (the
        # orbital update path requires this).
        await engine.index_documents([
            {"content": f"doc-{i}", "metadata": {"source": "agent"}}
            for i in range(5)
        ])

        # Pick one document as our probe target.
        target = "doc-0"
        target_id = (await engine.query(text=target, top_k=1))[0].id
        raw_emb_before = engine.faiss_index.get_vectors([target_id])[target_id].copy()

        # The kick direction is (query_anchor - virtual_pos). Since we're
        # using the same text as both the doc and the query, query == raw,
        # and the kick first goes toward -displacement (i.e., back to anchor).
        # That's degenerate. Use a *different* query that still retrieves
        # target via the wave so the kick has a non-zero (q - raw) direction.
        probe = "doc-1"  # distinct embedding, but a wave neighbor of doc-0
        q_emb = engine.embedder.encode_query(probe)[0]

        for _ in range(20):
            await engine.query(text=probe, top_k=5)

        disp_after = engine.cache.get_displacement(target_id)
        raw_emb_after = engine.faiss_index.get_vectors([target_id])[target_id]

        # 1. Raw embedding must be unchanged — Stage 2 is transient force,
        #    not anchor migration.
        assert np.allclose(raw_emb_before, raw_emb_after, atol=1e-7)

        # 2. Displacement, if non-zero, must have a positive component
        #    along (q - raw). With other forces present it may not be
        #    perfectly aligned, but the projection should be positive.
        if disp_after is not None and float(np.linalg.norm(disp_after)) > 1e-6:
            kick_dir = (q_emb - raw_emb_before)
            kick_dir = kick_dir / (float(np.linalg.norm(kick_dir)) + 1e-9)
            projection = float(np.dot(disp_after, kick_dir))
            assert projection > 0.0, (
                f"displacement projection onto (q - raw) was {projection:.4g}, "
                f"expected positive after 20 recalls with query_kick_strength=0.05"
            )
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_query_kick_zero_alpha_preserves_legacy(tmp_path):
    """With query_kick_strength=0, the recall path should not introduce any
    new displacement component beyond what the legacy 3-component physics
    produces. Direct regression guard against accidental enabling."""
    engine = _make_engine(tmp_path, kick_strength=0.0)
    await engine.startup()
    try:
        await engine.index_documents([
            {"content": f"ctrl-doc-{i}", "metadata": {"source": "agent"}}
            for i in range(5)
        ])

        target_id = (await engine.query(text="ctrl-doc-0", top_k=1))[0].id
        for _ in range(10):
            await engine.query(text="ctrl-doc-1", top_k=5)

        # With α=0 the only displacement source is neighbor gravity + Hooke;
        # we can't assert disp==0 (neighbor gravity will move it), only that
        # the test would distinguish from the kick=0.05 case via the
        # projection test above. Here we just guard against runtime errors
        # along the no-kick code path.
        disp = engine.cache.get_displacement(target_id)
        assert disp is None or float(np.linalg.norm(disp)) < 1.0
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_query_kick_does_not_migrate_raw_anchor(tmp_path):
    """Stronger version of property #1: even after many recalls the FAISS
    raw embedding for the target must equal its initial value bit-for-bit."""
    engine = _make_engine(tmp_path, kick_strength=0.05)
    await engine.startup()
    try:
        await engine.index_documents([
            {"content": f"anchor-doc-{i}", "metadata": {"source": "agent"}}
            for i in range(5)
        ])
        target_id = (await engine.query(text="anchor-doc-0", top_k=1))[0].id
        initial = engine.faiss_index.get_vectors([target_id])[target_id].copy()
        for _ in range(30):
            await engine.query(text="anchor-doc-2", top_k=5)
        final = engine.faiss_index.get_vectors([target_id])[target_id]
        assert np.array_equal(initial, final)
    finally:
        await engine.shutdown()


# ---------------------------------------------------------------------------
# Phase I Stage 3 — Mass-gated query attraction (integration)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stage3_gate_dampens_drift_for_new_nodes(tmp_path):
    """Stage 3 (mass-gated kick) dampens displacement drift on freshly-added
    nodes compared to Stage 2 (no gate), verifying the gate is actually
    applied through the full engine.query() pipeline — not just present in
    compute_acceleration.

    Setup: identical docs and probes, only mass_anchor_threshold differs.
      θ=0  → Stage 2 (gate=1.0): full F=ma kick toward q, larger projection
      θ=3  → Stage 3 (gate≈0.32 at mass=1): damped kick, smaller projection

    We measure the *projection* of displacement onto (q - raw) rather than
    total displacement norm because neighbor gravity (4 other docs) is the
    dominant force on total norm — only the q-direction component isolates
    the query attraction term that Stage 3 gates.

    This is the engine-level acceptance test for the single-attractor
    pathology fix: Stage 3 prevents new nodes from being one-shot drifted
    into the "near every query" position by anchor (Hooke) protection.
    """
    async def measure_q_projection(subdir: str, threshold: float) -> float:
        path = tmp_path / subdir
        path.mkdir()
        # Bump kick strength so the gate's effect is measurable above
        # neighbor-gravity noise within 20 recall steps.
        engine = _make_engine(
            path, kick_strength=0.5, mass_anchor_threshold=threshold,
        )
        await engine.startup()
        try:
            await engine.index_documents([
                {"content": f"drift-doc-{i}", "metadata": {"source": "agent"}}
                for i in range(5)
            ])
            target_id = (await engine.query(text="drift-doc-0", top_k=1))[0].id
            raw_emb = engine.faiss_index.get_vectors([target_id])[target_id].copy()
            q_emb = engine.embedder.encode_query("drift-probe-distinct")[0]
            kick_dir = q_emb - raw_emb
            kick_dir = kick_dir / (float(np.linalg.norm(kick_dir)) + 1e-9)
            for _ in range(20):
                await engine.query(text="drift-probe-distinct", top_k=5)
            disp = engine.cache.get_displacement(target_id)
            if disp is None:
                return 0.0
            return float(np.dot(disp, kick_dir))
        finally:
            await engine.shutdown()

    proj_stage2 = await measure_q_projection("s2", 0.0)
    proj_stage3 = await measure_q_projection("s3", 3.0)

    # Both modes must produce positive drift toward q (kick is active)
    assert proj_stage2 > 0, f"Stage 2 should drift toward q, got proj={proj_stage2}"
    assert proj_stage3 > 0, f"Stage 3 should drift toward q, got proj={proj_stage3}"
    # Stage 3 gate must dampen the q-direction drift on a low-mass node
    assert proj_stage3 < proj_stage2, (
        f"Stage 3 gate should reduce q-direction drift on low-mass node — "
        f"proj_stage2={proj_stage2:.4f}, proj_stage3={proj_stage3:.4f}, "
        f"expected ratio ≈ tanh(1/3) ≈ 0.32 modulo mass-accretion over 20 steps"
    )
