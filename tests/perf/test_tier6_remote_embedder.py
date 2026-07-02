"""Tier 6 — RemoteEmbedder numerical equivalence (REAL RURI required).

This is a skeleton with a module-level skip marker. It is part of the
仮説 -> 実装 -> 検証 manual verification loop (see
``docs/wiki/Operations-Performance-Testing.md``) and is deliberately **not**
run in CI. Run it manually with a running embedding service::

    .venv/bin/python -m gaottt.embedding.service --port 7879 &
    GAOTTT_EMBEDDER_ENDPOINT=http://127.0.0.1:7879 \\
    .venv/bin/python -m pytest tests/perf/test_tier6_remote_embedder.py -v -s

Numerical equivalence between the in-process ``RuriEmbedder`` and a
``RemoteEmbedder`` pointed at the service is verified in three stages
(implementation plan §MV1-4):

    1. ``np.allclose(in_process, remote, atol=1e-5)``
    2. cosine difference < 1e-6
    3. golden queries (``tests/perf/golden_corpus/queries.json``) top-K
       agreement via ``engine.query``

Bit-exact equality is NOT required — service-side batching can change the
batch shape without changing the per-vector result.
"""
from __future__ import annotations

import pytest

# Module-level skip: the bodies are placeholders to be implemented in a later
# session that has real RURI available. Collection succeeds and every test is
# reported as skipped, which is the WP-4 acceptance for this file.
pytestmark = pytest.mark.skip(
    reason="requires real RURI + a running embedding service; "
    "run manually per Operations-Performance-Testing"
)


def test_remote_encode_documents_allclose():
    """np.allclose(in_process, remote, atol=1e-5) for encode_documents."""
    # TODO: implement with real RURI in a later session.
    pass


def test_remote_encode_documents_cosine_diff():
    """cosine difference < 1e-6 for encode_documents."""
    # TODO: implement with real RURI in a later session.
    pass


def test_remote_topk_agreement_golden_queries():
    """engine.query top-K agreement between in-process and remote on the
    golden queries in tests/perf/golden_corpus/queries.json."""
    # TODO: load tests/perf/golden_corpus/queries.json and compare top-K.
    pass
