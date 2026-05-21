"""Phase M Stage 1 — Mass Conservation (integration tests).

End-to-end via ``engine.index_documents`` + ``engine.query``:

  * Same-``original_id`` chunks ("internal trade") do NOT inflate each
    other's mass through wave-propagation contributions.
  * Phase K supernova cohort behaves the same way via ``cohort_id``.
  * The ``mass_conservation_enabled=False`` rollback path restores the
    pre-Phase-M behaviour (sibling chunks DO inflate each other's mass).
"""
from __future__ import annotations

import hashlib

import numpy as np
import pytest

from gaottt.config import GaOTTTConfig
from gaottt.core.engine import GaOTTTEngine
from gaottt.index.faiss_index import FaissIndex
from gaottt.store.cache import CacheLayer
from gaottt.store.sqlite_store import SqliteStore


class _TokenStubEmbedder:
    """Token-sum deterministic embedder. Shared words → similar vectors;
    used so a query can deliberately co-activate sibling chunks in the
    same wave."""

    def __init__(self, dim: int = 32):
        self._dim = dim
        self._cache: dict[str, np.ndarray] = {}

    def _vec(self, token: str) -> np.ndarray:
        cached = self._cache.get(token)
        if cached is not None:
            return cached
        seed = int.from_bytes(hashlib.md5(token.encode()).digest()[:8], "big")
        rng = np.random.default_rng(seed)
        v = rng.standard_normal(self._dim).astype(np.float32)
        v /= np.linalg.norm(v) + 1e-9
        self._cache[token] = v
        return v

    def _embed(self, text: str) -> np.ndarray:
        toks = [t.lower() for t in text.split() if t.strip()]
        if not toks:
            return np.zeros(self._dim, dtype=np.float32)
        v = sum(self._vec(t) for t in toks)
        n = np.linalg.norm(v)
        return (v / n).astype(np.float32) if n > 0 else v.astype(np.float32)

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        return np.stack([self._embed(t) for t in texts])

    def encode_query(self, text: str) -> np.ndarray:
        return self._embed(text).reshape(1, -1)


def _build_engine(tmp_path, *, mass_conservation: bool) -> GaOTTTEngine:
    config = GaOTTTConfig(
        embedding_dim=32,
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "gaottt.db"),
        faiss_index_path=str(tmp_path / "gaottt.faiss"),
        # Small seed pool + permissive wave so most siblings are reached
        # as wave children (i.e. with a real ``parent_id`` attribution),
        # not as seeds (which attribute to ``SEED_PARENT_ID`` and never
        # get filtered).
        wave_initial_k=2,
        wave_max_depth=3,
        wave_seed_mass_alpha=0.0,
        # Permissive neighbor radius so siblings actually propagate.
        wave_gravity_a_min=0.001,
        wave_attenuation=0.5,
        # Mute moving parts that would write back / dream over our state.
        genesis_kick_enabled=False,
        supernova_enabled=False,  # opt out per-test so cohort_id stays controlled
        dream_enabled=False,
        faiss_save_interval_seconds=0.0,
        flush_interval_seconds=999.0,
        virtual_faiss_enabled=False,
        hybrid_bm25_enabled=False,
        # Phase M Stage 1 — the flag under test.
        mass_conservation_enabled=mass_conservation,
        mass_bh_enabled=False,  # decouple from the BH so we test mass-update only
    )
    return GaOTTTEngine(
        config=config,
        embedder=_TokenStubEmbedder(dim=32),
        faiss_index=FaissIndex(dimension=32),
        cache=CacheLayer(flush_interval=999.0),
        store=SqliteStore(db_path=config.db_path),
    )


@pytest.fixture
async def engine_conservation_on(tmp_path):
    eng = _build_engine(tmp_path, mass_conservation=True)
    await eng.startup()
    try:
        yield eng
    finally:
        await eng.shutdown()


@pytest.fixture
async def engine_conservation_off(tmp_path):
    eng = _build_engine(tmp_path, mass_conservation=False)
    await eng.startup()
    try:
        yield eng
    finally:
        await eng.shutdown()


# ---------------------------------------------------------------------------
# Same-original_id chunks do not inflate each other
# ---------------------------------------------------------------------------

def _shared_doc_chunks(n: int) -> list[dict]:
    # Heavy shared vocabulary so sibling chunks crowd each other in the
    # wave; ``filler{i}`` is a unique token per chunk to make embeddings
    # distinct (FAISS would otherwise see exact-duplicate vectors).
    return [
        {
            "content": f"shared vocabulary token gravity mass chunk filler{i}",
            "metadata": {"source": "file", "original_id": "doc-A"},
        }
        for i in range(n)
    ]


async def test_same_original_siblings_do_not_inflate_mass(engine_conservation_on):
    eng = engine_conservation_on
    ids = await eng.index_documents(_shared_doc_chunks(8))
    initial = {nid: eng.cache.get_node(nid).mass for nid in ids}

    # Many recalls of words shared by every chunk → wave fans out across siblings.
    for _ in range(10):
        await eng.query(text="gravity mass token", top_k=3)

    # Phase M Stage 1: every sibling-to-sibling co-occurrence is filtered
    # out of the mass update. Only the seed (query) force survives, so
    # mass should rise only modestly — the dominant inflation path is gone.
    after = {nid: eng.cache.get_node(nid).mass for nid in ids}
    gains = [after[nid] - initial[nid] for nid in ids]
    assert max(gains) < 1.0, (
        "Same-original siblings should accrue at most a small "
        "seed-only mass bump; got gains=" + repr(gains)
    )


async def test_rollback_off_lets_siblings_inflate(tmp_path):
    """When the flag is off we restore pre-Phase-M behaviour: sibling
    chunks DO drive each other's mass up via wave contributions.

    Each engine gets its own data directory so dedup-by-content-hash on
    the SQLite store cannot silently swallow the second batch.
    """
    (tmp_path / "on").mkdir()
    (tmp_path / "off").mkdir()
    on = _build_engine(tmp_path / "on", mass_conservation=True)
    off = _build_engine(tmp_path / "off", mass_conservation=False)
    await on.startup()
    await off.startup()
    try:
        docs = _shared_doc_chunks(8)
        ids_on = await on.index_documents(docs)
        ids_off = await off.index_documents(docs)
        for _ in range(10):
            await on.query(text="gravity mass token", top_k=3)
            await off.query(text="gravity mass token", top_k=3)

        gain_on = max(
            on.cache.get_node(nid).mass - 1.0 for nid in ids_on
        )
        gain_off = max(
            off.cache.get_node(nid).mass - 1.0 for nid in ids_off
        )
        # With the flag off the wave still mass-updates sibling contributions
        # so the maximum gain must exceed the conservation-on run.
        assert gain_off > gain_on, (
            f"expected conservation-off ({gain_off}) > conservation-on ({gain_on})"
        )
    finally:
        await on.shutdown()
        await off.shutdown()


# ---------------------------------------------------------------------------
# Supernova cohort: cohort_id collisions count as self-force
# ---------------------------------------------------------------------------

async def test_supernova_cohort_internal_force_is_filtered(tmp_path):
    """When supernova fires, batch members share a ``cohort_id``. Their
    intra-cohort co-occurrence should NOT pump each other's mass."""
    eng = _build_engine(tmp_path, mass_conservation=True)
    eng.config.supernova_enabled = True
    eng.config.supernova_min_cohort_size = 2
    eng.config.supernova_initial_weight = 1.0
    eng.config.supernova_velocity_alpha = 0.0  # no outward push: keeps the test tight
    eng.config.genesis_kick_enabled = False
    await eng.startup()
    try:
        ids = await eng.index_documents([
            # Each doc has a distinct original_id (no shared file), so the
            # ONLY self-force path is cohort_id. Sharing words across docs
            # ensures the wave actually touches the siblings.
            {
                "content": f"phase m cohort token sibling{i} filler{i}",
                "metadata": {"source": "agent"},
            }
            for i in range(8)
        ])
        cohort_ids = {eng.cache.get_cohort(nid) for nid in ids}
        assert len(cohort_ids) == 1 and None not in cohort_ids, (
            f"expected one shared cohort_id, got {cohort_ids}"
        )

        for _ in range(10):
            await eng.query(text="phase m cohort token", top_k=3)

        gains = [eng.cache.get_node(nid).mass - 1.0 for nid in ids]
        assert max(gains) < 1.0, (
            "Cohort siblings should not inflate each other; gains=" + repr(gains)
        )
    finally:
        await eng.shutdown()


# ---------------------------------------------------------------------------
# Mass-based BH acceleration (D5) — direct unit-level check
# ---------------------------------------------------------------------------

def test_compute_mass_bh_acceleration_pulls_low_mass_toward_heavy():
    from gaottt.core.gravity import compute_mass_bh_acceleration

    config = GaOTTTConfig(
        embedding_dim=3,
        gravity_G=1.0,
        gravity_epsilon=1e-9,
        mass_bh_enabled=True,
        mass_bh_theta=5.0,
        mass_bh_sigma=1.5,
    )
    # Light node at origin, heavy attractor offset along +x.
    pos_i = np.array([0.0, 0.0, 0.0], dtype=np.float32)
    heavy_pos = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    light_pos = np.array([-1.0, 0.0, 0.0], dtype=np.float32)
    neighbors = [(heavy_pos, 10.0), (light_pos, 1.0)]

    acc = compute_mass_bh_acceleration(pos_i, neighbors, config)
    # bh_factor(1.0, 5, 1.5) = 0 (below θ-2σ) → light contributes nothing.
    # bh_factor(10.0, 5, 1.5) = tanh((10-5)/1.5) ≈ tanh(3.33) ≈ 0.9970.
    # Magnitude = G * m * factor / r² ≈ 1 * 10 * 0.997 / 1 ≈ 9.97 along +x.
    assert acc[0] > 9.0, f"expected strong +x pull, got {acc}"
    assert abs(acc[1]) < 1e-6 and abs(acc[2]) < 1e-6
    # Direction must be toward the heavy attractor, not the light one.
    assert acc[0] > 0.0


def test_compute_mass_bh_acceleration_disabled_returns_zero():
    from gaottt.core.gravity import compute_mass_bh_acceleration

    config = GaOTTTConfig(embedding_dim=3, mass_bh_enabled=False)
    pos_i = np.zeros(3, dtype=np.float32)
    neighbors = [(np.array([1.0, 0.0, 0.0], dtype=np.float32), 100.0)]
    acc = compute_mass_bh_acceleration(pos_i, neighbors, config)
    assert np.allclose(acc, 0.0)


# ---------------------------------------------------------------------------
# H8 — collision-resistant original_id fallback
#
# The implicit fallback (no explicit original_id) must NOT group two
# unrelated docs that merely share a non-absolute file_path basename; doing
# so would make is_self_force_by_id treat them as same-document and suppress
# their genuine external-referral mass as "internal trade".
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_h8_ambiguous_file_path_does_not_group_unrelated_docs(tmp_path):
    eng = _build_engine(tmp_path, mass_conservation=True)
    await eng.startup()
    try:
        a = await eng.index_documents(
            [{"content": "alpha project readme", "metadata": {"file_path": "README.md"}}]
        )
        b = await eng.index_documents(
            [{"content": "beta project readme", "metadata": {"file_path": "README.md"}}]
        )
        oid_a = eng.cache.get_original(a[0])
        oid_b = eng.cache.get_original(b[0])
        # A bare basename is not a global identity → each falls back to its
        # own node id, so the two unrelated docs are NOT self-force peers.
        assert oid_a == a[0]
        assert oid_b == b[0]
        assert oid_a != oid_b, (
            "unrelated docs sharing basename 'README.md' were grouped as "
            "same-original — false self-force (H8 regression)"
        )
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_h8_absolute_path_still_groups_siblings(tmp_path):
    """Control: an UNAMBIGUOUS absolute file_path still groups chunks of
    the same file (Phase M chunk-grouping preserved)."""
    eng = _build_engine(tmp_path, mass_conservation=True)
    await eng.startup()
    try:
        abs_fp = "/srv/corpus/doc.md"
        ids = await eng.index_documents([
            {"content": "chunk one body", "metadata": {"file_path": abs_fp}},
            {"content": "chunk two body", "metadata": {"file_path": abs_fp}},
        ])
        assert eng.cache.get_original(ids[0]) == abs_fp
        assert eng.cache.get_original(ids[1]) == abs_fp
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_h8_explicit_original_id_always_honored(tmp_path):
    """An explicitly-supplied original_id is honored verbatim regardless of
    file_path — the loader's normal path is unaffected by H8."""
    eng = _build_engine(tmp_path, mass_conservation=True)
    await eng.startup()
    try:
        ids = await eng.index_documents([{
            "content": "explicit id doc",
            "metadata": {"original_id": "session-42#3", "file_path": "notes.md"},
        }])
        assert eng.cache.get_original(ids[0]) == "session-42#3"
    finally:
        await eng.shutdown()
