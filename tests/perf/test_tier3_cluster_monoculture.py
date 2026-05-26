"""Tier 3 — Cluster monoculture measurement (Stage 6.1 baseline + acceptance).

Measures cohort dominance in ``recall`` / ``ambient_recall`` top-K results
across heterogeneous queries. Stage 6.1 anti-hub aims to reduce monoculture
by penalising repeated cohort_ids in top-K composition.

The test is structured as a **baseline measurement** (Lateral Association
observation period style). It prints rich per-query numbers so the same
test run before and after Stage 6.1 implementation produces a literal
diff. Assertions are deliberately loose pre-Stage-6.1 (only sanity floors);
they tighten once the knob ``direct_hit_anti_hub_lambda > 0`` lands and the
baseline numbers improve.

Corpus design:
  - hub cohort "hub-philosophy" — 6 chunks (the same shape as production's
    cycle-2 self-knowledge cluster: many similar memos sharing one cohort)
  - target A "phase-l"          — 2 chunks about Phase L BM25 hybrid
  - target B "phase-m"          — 2 chunks about Phase M mass conservation
  - target C "lateral"          — 2 chunks about Lateral Association

The hub cohort is engineered to vocabularly overlap with each target query
just enough that, without anti-hub, recall top-K tends to fill with hub
chunks at the expense of the on-topic target.

Three queries (one per target). For each:
  - ``unique_cohorts(top_k)`` — higher = more diverse
  - ``max_cohort_dominance(top_k)`` — count of the most-represented cohort,
    lower = less monoculture
  - ``target_hit_rate`` — fraction of queries whose top-K contains at least
    one on-topic target chunk

The hub cohort_id is pre-assigned in metadata (no supernova path needed)
so the measurement does not depend on Phase K's batching mechanics.
"""
from __future__ import annotations

import pytest

from gaottt.services import memory as memory_service
from tests.perf._helpers import make_engine


# ---------- Corpus -------------------------------------------------------------

HUB_COHORT = "hub-philosophy-cohort"
PHASE_L_COHORT = "phase-l-cohort"
PHASE_M_COHORT = "phase-m-cohort"
LATERAL_COHORT = "lateral-cohort"


def _hub_chunks() -> list[dict]:
    """The hub cluster — six self-knowledge-philosophy chunks under one cohort.

    Each chunk references the three target topics in passing so vocabulary
    overlap with the target queries is real (this is why hub chunks tend to
    win raw cosine in production)."""
    base = [
        "GaOTTT 五層論 第2期で物理から人格まで literal に降ろした philosophy memo。",
        "Phase G/H の write-behind と genesis kick が観測した structural discovery。",
        "Phase I retrieval = gradient step の literal 対応関係まとめ。",
        "Phase J 人格層 declared value/intention/commitment を retrieval geometry に翻訳。",
        "Phase K stellar supernova cohort で集合的記憶生成を物理化。",
        "Phase M mass conservation Articulation as Carrier の literal 実装。",
    ]
    return [
        {
            "content": (
                f"[hub-{i}] {body} "
                "Phase L hybrid retrieval, Phase M mass conservation, "
                "Lateral Association も同じ五層論の射影。"
            ),
            "metadata": {
                "source": "agent",
                "tags": ["cycle-2", "philosophy", "hub-test"],
                "cohort_id": HUB_COHORT,
                "original_id": f"hub-original-{i}",
            },
        }
        for i, body in enumerate(base)
    ]


def _target_chunks(cohort: str, prefix: str, lines: list[str]) -> list[dict]:
    return [
        {
            "content": f"[{prefix}-{i}] {line}",
            "metadata": {
                "source": "agent",
                "tags": [prefix, "target-test"],
                "cohort_id": cohort,
                "original_id": f"{prefix}-original-{i}",
            },
        }
        for i, line in enumerate(lines)
    ]


CORPUS_BUILDERS = {
    "hub": _hub_chunks,
    "phase-l": lambda: _target_chunks(
        PHASE_L_COHORT, "phase-l",
        [
            "Phase L Stage 1 — Hybrid Retrieval。raw FAISS ∪ virtual FAISS ∪ BM25 の 3-way 統合を RRF (Cormack 2009) で fuse。",
            "Phase L の hybrid_bm25_enabled=False で 1 行 rollback。LLM 不要・ローカル完結の lexical 信号。",
        ],
    ),
    "phase-m": lambda: _target_chunks(
        PHASE_M_COHORT, "phase-m",
        [
            "Phase M Stage 1 — Mass Conservation。is_self_force(a, b) で chunk 間の内輪 mass inflation を遮断。",
            "Phase M の mass_bh_enabled=True で連続 bh_factor = tanh((m-θ)/σ) が attractor onset を司る。",
        ],
    ),
    "lateral": lambda: _target_chunks(
        LATERAL_COHORT, "lateral",
        [
            "Lateral Association Stage 1a — passive recall の return_count mutation を遮断、deterministic baseline 確立。",
            "Lateral Association Stage 1b — novelty decay で session 内 surface 反復に session-scope decay を適用。",
        ],
    ),
}


QUERIES = [
    {
        "key": "phase-l",
        "query": "Phase L hybrid retrieval BM25 RRF",
        "target_cohort": PHASE_L_COHORT,
    },
    {
        "key": "phase-m",
        "query": "Phase M mass conservation self-force",
        "target_cohort": PHASE_M_COHORT,
    },
    {
        "key": "lateral",
        "query": "Lateral Association Stage 1a 1b novelty decay",
        "target_cohort": LATERAL_COHORT,
    },
]


# ---------- Measurement helpers -----------------------------------------------


def _cohorts_of(engine, ids: list[str]) -> list[str | None]:
    return [engine.cache.get_cohort(nid) for nid in ids]


def _summary_for(items, engine, k: int) -> dict:
    top = items[:k]
    ids = [it.id for it in top]
    cohorts = _cohorts_of(engine, ids)
    real = [c for c in cohorts if c is not None]
    unique = len(set(cohorts))
    if real:
        max_dom = max(real.count(c) for c in set(real))
    else:
        max_dom = 0
    return {
        "unique": unique,
        "max_dominance": max_dom,
        "cohorts": cohorts,
        "ids": ids,
    }


# ---------- Test ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_cluster_monoculture_baseline(tmp_path):
    """Stage 6.1 baseline — measure cohort dominance in recall top-K across
    heterogeneous queries.

    Pre-Stage-6.1: ``direct_hit_anti_hub_lambda=0.0`` (default). No penalty,
    hub dominance expected. The test prints raw numbers and asserts only
    sanity floors so it remains green.

    Post-Stage-6.1: re-run with ``direct_hit_anti_hub_lambda > 0`` and a
    tighter monoculture floor; baseline diff documents the improvement.
    """
    eng = make_engine(
        tmp_path,
        # Larger seed pool than the perf default so all 12 chunks have a
        # chance to surface; the measurement is about ranking inside the
        # pool, not wave reach.
        wave_initial_k=12,
        # We pre-set cohort_id in metadata; no supernova batching needed.
        supernova_enabled=False,
        # Default anti-hub OFF (this *is* the baseline run).
        # direct_hit_anti_hub_lambda=0.0,
    )
    await eng.startup()
    try:
        # Index every cohort as its own batch so cohort_id metadata sticks.
        for name, builder in CORPUS_BUILDERS.items():
            await eng.index_documents(builder())

        per_query: list[dict] = []
        target_hits = 0
        for q in QUERIES:
            rr = await memory_service.recall(
                eng, q["query"], top_k=5, passive=True, auto_route=False,
            )
            s5 = _summary_for(rr.items, eng, k=5)
            s3 = _summary_for(rr.items, eng, k=3)
            on_topic_in_top5 = q["target_cohort"] in s5["cohorts"]
            if on_topic_in_top5:
                target_hits += 1
            per_query.append({
                "query": q["query"],
                "target": q["target_cohort"],
                "top3": s3,
                "top5": s5,
                "on_topic_top5": on_topic_in_top5,
            })

        # ---- Print heatmap ----
        print("\nCluster monoculture baseline:")
        for row in per_query:
            t5 = row["top5"]
            cohort_labels = [
                "hub" if c == HUB_COHORT else
                "PL" if c == PHASE_L_COHORT else
                "PM" if c == PHASE_M_COHORT else
                "LA" if c == LATERAL_COHORT else
                "-" for c in t5["cohorts"]
            ]
            print(
                f"  [{row['target'].split('-')[0]:>6}] {row['query']!r}\n"
                f"    top5 cohorts = {cohort_labels}  "
                f"unique={t5['unique']}  max_dom={t5['max_dominance']}  "
                f"on_topic={row['on_topic_top5']}"
            )
        avg_unique5 = sum(r["top5"]["unique"] for r in per_query) / len(per_query)
        avg_max5 = sum(r["top5"]["max_dominance"] for r in per_query) / len(per_query)
        print(
            f"  Aggregate top-5: avg_unique_cohorts={avg_unique5:.2f}  "
            f"avg_max_dominance={avg_max5:.2f}  "
            f"target_hit_rate={target_hits}/{len(QUERIES)}"
        )

        # ---- Sanity floors (loose; baseline keeps the test green) ----
        # Every query must surface SOMETHING (at least 1 unique cohort).
        for row in per_query:
            assert row["top5"]["unique"] >= 1, (
                f"top-5 contained no cohort-tagged result for {row['query']!r}; "
                f"corpus seeding failed?"
            )
        # max_dominance can be up to 5 pre-Stage-6.1 (full hub takeover).
        assert max(r["top5"]["max_dominance"] for r in per_query) <= 5, (
            "top-5 has >5 entries from a single cohort — measurement bug"
        )
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_cluster_monoculture_anti_hub_enabled(tmp_path):
    """Stage 6.1 acceptance — with ``direct_hit_anti_hub_lambda > 0`` the
    cohort dominance should drop AND target hit rate should not regress.

    Same corpus + queries as the baseline. Numerical bounds derived from
    the baseline run (``avg_unique=2.67, avg_max_dom=2.33`` at lambda=0)
    plus a margin: we require avg_unique to *increase* and avg_max_dom to
    *decrease* under lambda=0.4 (the recommended starting point).
    """
    eng = make_engine(
        tmp_path,
        wave_initial_k=12,
        supernova_enabled=False,
        direct_hit_anti_hub_lambda=0.4,
    )
    await eng.startup()
    try:
        for name, builder in CORPUS_BUILDERS.items():
            await eng.index_documents(builder())

        per_query: list[dict] = []
        target_hits = 0
        for q in QUERIES:
            rr = await memory_service.recall(
                eng, q["query"], top_k=5, passive=True, auto_route=False,
            )
            s5 = _summary_for(rr.items, eng, k=5)
            if q["target_cohort"] in s5["cohorts"]:
                target_hits += 1
            per_query.append({
                "query": q["query"], "target": q["target_cohort"], "top5": s5,
            })

        print("\nCluster monoculture WITH anti-hub (λ=0.4):")
        for row in per_query:
            t5 = row["top5"]
            cohort_labels = [
                "hub" if c == HUB_COHORT else
                "PL" if c == PHASE_L_COHORT else
                "PM" if c == PHASE_M_COHORT else
                "LA" if c == LATERAL_COHORT else
                "-" for c in t5["cohorts"]
            ]
            print(
                f"  [{row['target'].split('-')[0]:>6}] {row['query']!r}\n"
                f"    top5 cohorts = {cohort_labels}  "
                f"unique={t5['unique']}  max_dom={t5['max_dominance']}"
            )
        avg_unique5 = sum(r["top5"]["unique"] for r in per_query) / len(per_query)
        avg_max5 = sum(r["top5"]["max_dominance"] for r in per_query) / len(per_query)
        print(
            f"  Aggregate top-5: avg_unique_cohorts={avg_unique5:.2f}  "
            f"avg_max_dominance={avg_max5:.2f}  "
            f"target_hit_rate={target_hits}/{len(QUERIES)}"
        )

        # ---- Stage 6.1 acceptance ----
        # Baseline at λ=0: avg_unique=2.67, avg_max_dom=2.33.
        # With λ=0.4 we want measurable improvement, NOT degraded target hit.
        assert avg_unique5 > 2.67, (
            f"anti-hub failed to increase diversity: avg_unique={avg_unique5:.2f}"
        )
        assert avg_max5 < 2.33, (
            f"anti-hub failed to reduce monoculture: avg_max_dom={avg_max5:.2f}"
        )
        assert target_hits == len(QUERIES), (
            f"anti-hub broke target hits: {target_hits}/{len(QUERIES)}"
        )
        # Strict floor: no single cohort should fill >2 of top-5 under λ=0.4
        # given a 4-cohort corpus.
        worst = max(r["top5"]["max_dominance"] for r in per_query)
        assert worst <= 2, (
            f"single cohort still owns {worst} of top-5 under anti-hub"
        )
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_anti_hub_works_via_original_id_when_no_cohort(tmp_path):
    """Stage 7.1 extended — anti-hub must engage on ``original_id`` clusters
    too, not just ``cohort_id``.

    Production observation (2026-05-26, 26k corpus): cohort_id coverage = 0%
    (one-at-a-time remember() never reaches supernova batch threshold), but
    ``original_id`` covers 57.8% of active memos in multi-member clusters
    (largest = 638-chunk book). Anti-hub must work in this dominant case
    to be useful in production.

    Seeds a "book"-shaped corpus: 6 chunks sharing one ``original_id``
    (no cohort_id), plus 3 distractor singletons each with their own
    unique original_id (= the doc_id default). Without anti-hub the hub
    fills top-5; with λ=0.4 it should be capped.
    """
    book_original_id = "/abs/path/to/big-book.md"

    def _book_chunks() -> list[dict]:
        return [
            {
                "content": (
                    f"[book-chunk-{i}] 教科書 Phase L hybrid retrieval, "
                    "Phase M mass conservation, Lateral Association を "
                    "包括的に解説する章。"
                ),
                "metadata": {
                    "source": "file",
                    "tags": ["textbook", "book-test"],
                    # No cohort_id — simulating one-at-a-time ingest.
                    # ``original_id`` is what file ingest sets to file_path.
                    "original_id": book_original_id,
                },
            }
            for i in range(6)
        ]

    def _singleton(prefix: str, content: str) -> dict:
        return {
            "content": content,
            "metadata": {
                "source": "agent",
                "tags": [prefix],
                # No original_id — engine.index_documents fills it with
                # doc_id (so each is its own length-1 cluster).
            },
        }

    eng = make_engine(
        tmp_path,
        wave_initial_k=12,
        supernova_enabled=False,
        direct_hit_anti_hub_lambda=0.4,
    )
    await eng.startup()
    try:
        await eng.index_documents(_book_chunks())
        await eng.index_documents([
            _singleton("phase-l", "Phase L hybrid retrieval BM25 RRF の独立 memo"),
            _singleton("phase-m", "Phase M mass conservation self-force の独立 memo"),
            _singleton("lateral", "Lateral Association Stage 1 novelty decay の memo"),
        ])

        # Heterogeneous queries that all have lexical overlap with the book
        queries = [
            "Phase L hybrid retrieval BM25",
            "Phase M mass conservation",
            "Lateral Association Stage 1",
        ]
        per_query: list[dict] = []
        for q in queries:
            rr = await memory_service.recall(
                eng, q, top_k=5, passive=True, auto_route=False,
            )
            ids = [it.id for it in rr.items[:5]]
            originals = [eng.cache.get_original(nid) for nid in ids]
            cohorts = [eng.cache.get_cohort(nid) for nid in ids]
            book_count = sum(1 for o in originals if o == book_original_id)
            per_query.append({
                "query": q,
                "originals": [o[-30:] if o else None for o in originals],
                "cohorts": cohorts,
                "book_count": book_count,
            })

        print("\nOriginal_id anti-hub baseline (λ=0.4, cohort_id=None for all):")
        for row in per_query:
            print(
                f"  {row['query']!r}\n"
                f"    originals(suffix)={row['originals']}\n"
                f"    cohorts={row['cohorts']}\n"
                f"    book chunks in top-5 = {row['book_count']}"
            )
        max_book = max(r["book_count"] for r in per_query)
        avg_book = sum(r["book_count"] for r in per_query) / len(per_query)
        print(f"  Aggregate: max book chunks in any top-5 = {max_book}, avg = {avg_book:.2f}")

        # All cohorts should be None (we never set them).
        for row in per_query:
            assert all(c is None for c in row["cohorts"]), (
                f"cohort_id leaked into a memo for {row['query']!r}"
            )
        # Anti-hub via original_id should cap a single book at ≤ 2 of top-5.
        # (Pre-Stage-7.1-extension, before original_id was added to the
        # cluster key, this would be 5/5.)
        assert max_book <= 2, (
            f"anti-hub via original_id failed: a single book occupies "
            f"{max_book} of top-5 (expected ≤ 2)"
        )
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_ambient_direct_cluster_diversity_baseline(tmp_path):
    """Stage 6.1 ambient slot baseline — measure cohort uniqueness in
    ``ambient_recall.direct`` (the slot the production hook surfaces).

    direct_k=5 (production runs direct_k=2; widening here lets the
    monoculture be visible. Production observation in
    ``project_lateral_association_observation`` shows the same shape with
    direct_k=2 because the same hub cohort fills both slots).
    """
    eng = make_engine(
        tmp_path,
        wave_initial_k=12,
        supernova_enabled=False,
        ambient_gate_use_bm25=False,
        ambient_min_score=0.0,
    )
    await eng.startup()
    try:
        for name, builder in CORPUS_BUILDERS.items():
            await eng.index_documents(builder())

        per_query: list[dict] = []
        for q in QUERIES:
            resp = await memory_service.ambient_recall(
                eng, query=q["query"], direct_k=5,
            )
            cohorts = [eng.cache.get_cohort(m.id) for m in resp.direct]
            real = [c for c in cohorts if c is not None]
            max_dom = max(real.count(c) for c in set(real)) if real else 0
            per_query.append({
                "query": q["query"],
                "cohorts": cohorts,
                "unique": len(set(cohorts)),
                "max_dominance": max_dom,
                "target_in": q["target_cohort"] in cohorts,
            })

        print("\nAmbient direct cluster diversity baseline:")
        for row in per_query:
            print(
                f"  {row['query']!r}\n"
                f"    direct cohorts = {row['cohorts']}\n"
                f"    unique={row['unique']}  max_dom={row['max_dominance']}  "
                f"target_in={row['target_in']}"
            )

        # Loose floor — at least one direct slot was filled per query.
        for row in per_query:
            assert row["unique"] >= 1, (
                f"ambient direct slot empty for {row['query']!r}; seeding bug?"
            )
    finally:
        await eng.shutdown()
