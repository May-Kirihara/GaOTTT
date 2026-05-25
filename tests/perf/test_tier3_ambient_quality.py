"""Tier 3.5 — Ambient quality (Refinement Stage 5 + Lateral Association Stage 6).

Real RURI v3 310m against an ambient-shape JA fixture. For each query in
``golden_corpus/ambient_queries.json`` the test seeds the corpus, runs
``services.memory.ambient_recall``, and asserts per-axis expectations:

  - **direct**:   the expected memory id appears in ``result.direct``
  - **persona**:  Refinement Stage 1 — the query-conditioned persona slot
                  picks the expected ``id`` and ``kind``
  - **exclude**:  Refinement Stage 2 — ``exclude_tags`` keeps the tagged
                  memory out of every slot
  - **lateral**:  Lateral Association Stage 6 — measured in a separate
                  test (``test_ambient_lateral_lensing_baseline``) because
                  it needs pre-warming recalls to build displacement before
                  the lensing slot has something to bend with

Plus two independent baselines used as Stage 1 / Stage 3 prereqs:
  - ``test_ambient_lateral_lensing_baseline``      — Stage 6a literal
    baseline for lateral lensing surface rate
  - ``test_ambient_session_repetition_baseline``   — Stage 1 prereq: 3
    consecutive calls return BYTE-IDENTICAL surfaces today (the
    white-noise bug). When Stage 1 lands, this assertion flips to
    "surfaces should diverge" and forces an update here.

Tier 5 lives outside CI by design: the perf suite is the **検証 step** of
the 仮説 → 実装 → 検証 loop, deliberately manual ([Operations —
Performance Testing](../../docs/wiki/Operations-Performance-Testing.md)).
On a failure the test prints a heatmap-style summary (axis × query × what
went wrong) so a regression is easy to triage.

The corpus is intentionally small (~12 memories) — large enough to host
distractors, small enough that BM25 calibration thresholds are bypassed
(`ambient_bm25_min_score=0.0`) so we measure the slot logic itself, not
the gate. Add queries to ``ambient_queries.json`` to extend coverage.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gaottt.services import memory as memory_service
from tests.perf._helpers import make_engine


GOLDEN_DIR = Path(__file__).parent / "golden_corpus"
CORPUS_PATH = GOLDEN_DIR / "ambient_corpus.jsonl"
QUERIES_PATH = GOLDEN_DIR / "ambient_queries.json"

# A larger direct_k than production (default 2) so the corpus's 6 agent
# docs all have a chance to surface; the assertions are about *presence*
# in direct, not strict top-1 ranking.
DIRECT_K = 5


def _load_corpus() -> list[dict]:
    with CORPUS_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _load_queries() -> list[dict]:
    with QUERIES_PATH.open(encoding="utf-8") as f:
        return json.load(f)


async def _seed_engine(eng):
    """Populate the engine with the ambient corpus.

    Returns ``fixture_to_engine`` so assertions can map the human-friendly
    fixture ids back to whatever engine ids the index_documents call
    assigned.
    """
    corpus = _load_corpus()
    fixture_ids = [c["id"] for c in corpus]
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
    return dict(zip(fixture_ids, engine_ids)), corpus


@pytest.mark.asyncio
async def test_ambient_quality_golden_corpus(tmp_path):
    """Run every ambient-shape golden query and assert its slot axis.

    All failures are collected and reported together — a single regression
    in any axis leaves the others informative.
    """
    queries = _load_queries()
    eng = make_engine(
        tmp_path,
        # Ambient gate calibration is corpus-scale dependent; the tiny
        # fixture would never clear the production threshold. Disable the
        # gate so the test measures the slot logic itself.
        ambient_gate_use_bm25=False,
        ambient_min_score=0.0,
        # The perf helper disables persona_boost as noise for non-persona
        # tiers; re-enable for the persona-axis assertions
        # (collect_active_persona_ids returns empty when boost is off).
        persona_boost_enabled=True,
        # The perf helper sets wave_initial_k=3 (tight). On a 12-doc corpus
        # that's not enough seeds to host every target — broaden the seed
        # pool so the assertions test slot composition, not wave reach.
        wave_initial_k=12,
    )
    await eng.startup()
    try:
        fixture_to_engine, _ = await _seed_engine(eng)

        failures: list[str] = []
        report: list[str] = []
        for q in queries:
            axis = q["axis"]
            ambient_kwargs: dict = {"query": q["query"], "direct_k": DIRECT_K}
            if "exclude_tags" in q:
                ambient_kwargs["exclude_tags"] = q["exclude_tags"]

            resp = await memory_service.ambient_recall(eng, **ambient_kwargs)
            direct_ids = {m.id for m in resp.direct}
            lensing_ids = [m.id for m in resp.lensing]
            persona_id = resp.persona.id if resp.persona is not None else None
            persona_kind = resp.persona.kind if resp.persona is not None else None

            line = (
                f"  [{axis}] {q['query']!r}  "
                f"direct={len(direct_ids)}  "
                f"lensing={len(lensing_ids)}  "
                f"persona={persona_kind or '-'}"
            )
            report.append(line)

            if axis == "direct":
                expected = fixture_to_engine.get(q["expected_direct_id"])
                if expected is None:
                    failures.append(f"{q['query']!r}: expected fixture missing in index")
                elif expected not in direct_ids:
                    failures.append(
                        f"{q['query']!r}: expected direct {q['expected_direct_id']} "
                        f"(engine={expected[:8]}…) not in direct {sorted(d[:8] for d in direct_ids)}"
                    )
            elif axis == "persona":
                expected = fixture_to_engine.get(q["expected_persona_id"])
                if expected is None:
                    failures.append(f"{q['query']!r}: expected persona fixture missing")
                elif persona_id != expected:
                    failures.append(
                        f"{q['query']!r}: persona picked {persona_id[:8] if persona_id else 'None'}… "
                        f"expected {q['expected_persona_id']} (engine={expected[:8]}…)"
                    )
                elif persona_kind != q.get("expected_persona_kind"):
                    failures.append(
                        f"{q['query']!r}: persona kind {persona_kind!r} "
                        f"expected {q['expected_persona_kind']!r}"
                    )
            elif axis == "exclude":
                excluded = fixture_to_engine.get(q["expected_excluded_id"])
                if excluded is None:
                    failures.append(f"{q['query']!r}: expected excluded fixture missing")
                elif excluded in direct_ids:
                    failures.append(
                        f"{q['query']!r}: excluded {q['expected_excluded_id']} "
                        f"still in direct hits"
                    )
                elif excluded in lensing_ids:
                    failures.append(
                        f"{q['query']!r}: excluded {q['expected_excluded_id']} "
                        f"appeared in lensing"
                    )
                elif persona_id == excluded:
                    failures.append(
                        f"{q['query']!r}: excluded {q['expected_excluded_id']} "
                        f"occupied persona slot"
                    )
            elif axis == "lateral":
                # Lateral Association Stage 6 — measured in a separate test
                # that pre-warms displacement first. The main test runs from
                # a cold corpus where lensing has no displacement to bend.
                continue
            else:
                failures.append(f"{q['query']!r}: unknown axis {axis!r}")

        print("\nAmbient quality heatmap:")
        for line in report:
            print(line)
        if failures:
            print(f"\nFailures ({len(failures)}/{len(queries)}):")
            for f in failures:
                print(f"  - {f}")
        assert not failures, (
            f"{len(failures)}/{len(queries)} ambient-quality assertions failed"
        )
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_ambient_quality_breakdown_exposes_signals(tmp_path):
    """Refinement Stage 3 — when ``expose_breakdown=True`` every surfaced
    slot in the ambient block carries a populated breakdown so the caller
    can see why it surfaced. Quick existence check at production
    granularity (real RURI, real BM25-tokenized corpus)."""
    eng = make_engine(
        tmp_path,
        ambient_gate_use_bm25=False,
        ambient_min_score=0.0,
    )
    await eng.startup()
    try:
        await _seed_engine(eng)
        resp = await memory_service.ambient_recall(
            eng, query="Phase L hybrid retrieval BM25 RRF",
            direct_k=3, expose_breakdown=True,
        )
        assert resp.direct, "direct must be non-empty for this assert chain"
        for m in resp.direct:
            assert m.breakdown is not None, (
                f"direct slot {m.id[:8]}… missing breakdown with expose_breakdown=True"
            )
            # Real recall populates raw + virtual cosine; saturation defaults to 1.0.
            assert m.breakdown.virtual_cosine != 0.0, (
                "real recall must populate virtual_cosine"
            )
    finally:
        await eng.shutdown()


# --- Lateral Association Stage 6 baseline tests -------------------------------
# These are deliberately written as BASELINE measurements: they print rich
# heatmap output and assert only the current behavior. The plan recommends
# baselining BEFORE Stage 1 / Stage 3 land so the diff after each stage shows
# literal improvement (see Plans-Ambient-Recall-Lateral-Association.md).
#
# When Stage 1 (novelty decay) lands → flip the assertion in
# test_ambient_session_repetition_baseline from "identical" to "divergent".
# When Stage 3 (lensing top-K) lands → tighten lateral_hits_min in
# test_ambient_lateral_lensing_baseline.

# Pre-warming queries: cross-topic recalls used to build natural displacement
# before measuring lateral lensing. Each call updates simulation (passive=False
# default in services.recall), so wave-bent associations accumulate. Without
# this step the lensing slot has no displacement to surface — a fresh corpus
# has raw_cosine ≈ virtual_cosine everywhere.
_PREWARM_QUERIES = [
    "Phase L hybrid retrieval BM25 RRF",
    "Phase J persona-anchored seed boost",
    "Phase O TTT observability ScoreBreakdown",
    "Phase M mass conservation self-force",
    "ambient_recall slot composition lensing",
]


async def _prewarm_displacement(eng, queries: list[str]):
    """Run a few cross-topic recalls to build natural displacement before the
    lateral measurement. Uses ``passive=False`` so the engine actually
    updates the simulation (mass, displacement, co-occurrence)."""
    for q in queries:
        await memory_service.recall(eng, q, top_k=5, passive=False)


@pytest.mark.asyncio
async def test_ambient_lateral_lensing_baseline(tmp_path):
    """Stage 6a baseline — for abstract queries that have no direct lexical
    match, the lensing slot should surface one of the
    ``expected_lensing_candidates`` after pre-warming displacement.

    Today's baseline: lensing top-1 only is permitted by config, so the hit
    rate may be 0/N. The test prints per-query results and asserts only
    "the test ran, prewarming succeeded" — Stage 3 (lensing top-K) will
    raise ``lateral_hits_min`` from 0 to a real threshold.
    """
    queries = _load_queries()
    lateral_queries = [q for q in queries if q["axis"] == "lateral"]
    if not lateral_queries:
        pytest.skip("no lateral queries in golden corpus")

    eng = make_engine(
        tmp_path,
        ambient_gate_use_bm25=False,
        ambient_min_score=0.0,
        persona_boost_enabled=True,
        wave_initial_k=12,
    )
    await eng.startup()
    try:
        fixture_to_engine, _ = await _seed_engine(eng)
        await _prewarm_displacement(eng, _PREWARM_QUERIES)

        report: list[str] = []
        hits = 0
        for q in lateral_queries:
            resp = await memory_service.ambient_recall(
                eng, query=q["query"], direct_k=2, expose_breakdown=True,
            )
            lensing_ids = [m.id for m in resp.lensing]
            expected_engine_ids = {
                fixture_to_engine.get(fid)
                for fid in q["expected_lensing_candidates"]
            }
            expected_engine_ids.discard(None)
            # Stage 3 — hit if ANY of the top-K lensing picks lands on an
            # expected candidate (was top-1-only at Stage 6a baseline).
            hit = any(lid in expected_engine_ids for lid in lensing_ids)
            if hit:
                hits += 1
            gap_strs = [
                f"+{m.lensing_gap:.3f}"
                for m in resp.lensing
                if m.lensing_gap is not None
            ]
            short_ids = [lid[:8] + "…" for lid in lensing_ids] or ["None"]
            report.append(
                f"  [lateral] {q['query']!r}\n"
                f"    lensing[{len(lensing_ids)}]={short_ids} "
                f"gaps={gap_strs or ['N/A']} hit={hit} "
                f"(expected one of {q['expected_lensing_candidates']})"
            )

        print("\nLateral lensing baseline:")
        for line in report:
            print(line)
        print(f"  Hit rate: {hits}/{len(lateral_queries)}")

        # Stage 6a baseline: just confirm the measurement ran. Stage 3 will
        # tighten this to e.g. ``hits >= len(lateral_queries) // 2``.
        lateral_hits_min = 0
        assert hits >= lateral_hits_min, (
            f"Lateral hit rate {hits}/{len(lateral_queries)} below minimum "
            f"{lateral_hits_min} — baseline impossible? Inspect heatmap above."
        )
    finally:
        await eng.shutdown()


@pytest.mark.asyncio
async def test_ambient_session_repetition_baseline(tmp_path):
    """Stage 1 sub-step 0 — passive recall must be deterministic across
    consecutive identical calls.

    **History (2026-05-25)**: Stage 6a observed direct slot VARYING across
    3 consecutive ambient_recall calls. ``scripts/probe_ambient_nondeterminism.py``
    localized the cause to ``state.return_count`` being mutated even with
    ``passive=True`` (engine.py:1019-1033 was not gated). Saturation
    (``1 / (1 + return_count * saturation_rate)``) feeds final_score, so
    each ambient turn was silently rotating the direct slot. The fix gates
    the return_count + habituation blocks by ``not passive`` — passive
    recall is now field-state-pure (mass, displacement, co-occurrence
    AND return_count all stable). See Plans-Ambient-Recall-Lateral-Association.md
    Stage 1 sub-step 0.

    Post-fix baseline:
      - persona stable    (Heavy Persona Dominance, addressed separately by
        Refinement follow-up (b) ``ambient_persona_mass_weight``)
      - direct stable     (passive recall side-effect free, the bug fix)
      - lensing stable    (None on fresh corpus — no displacement yet)

    Stage 1 sub-step 1 (novelty decay implementation) will RE-introduce
    direct variation, but in a *controlled* way driven by transcript-derived
    ``recently_surfaced_ids``. When that lands, this test stays at the
    deterministic baseline (novelty decay only fires when a
    ``recently_surfaced`` argument is passed) and a NEW test asserts the
    decay path moves the direct surfaces.
    """
    eng = make_engine(
        tmp_path,
        ambient_gate_use_bm25=False,
        ambient_min_score=0.0,
        persona_boost_enabled=True,
        wave_initial_k=12,
    )
    await eng.startup()
    try:
        await _seed_engine(eng)
        query = "Phase L Stage 1 の hybrid retrieval について教えて"
        surfaces: list[tuple] = []
        for _ in range(3):
            resp = await memory_service.ambient_recall(
                eng, query=query, direct_k=2,
            )
            surfaces.append((
                tuple(m.id for m in resp.direct),
                tuple(m.id for m in resp.lensing),
                resp.persona.id if resp.persona is not None else None,
            ))

        print("\nSession repetition baseline (3 consecutive calls, same query):")
        for i, s in enumerate(surfaces):
            direct_str = tuple(d[:8] + "…" for d in s[0])
            lensing_str = tuple(lid[:8] + "…" for lid in s[1]) or ("None",)
            persona_str = (s[2][:8] + "…") if s[2] else "None"
            print(
                f"  call {i + 1}: direct={direct_str} "
                f"lensing={lensing_str} persona={persona_str}"
            )
        persona_ids = [s[2] for s in surfaces]
        direct_sets = [frozenset(s[0]) for s in surfaces]
        persona_stable = len(set(persona_ids)) == 1
        direct_varies = len(set(direct_sets)) > 1
        print(
            f"  Persona stable across calls: {persona_stable}  "
            f"(Heavy Persona Dominance — Refinement follow-up (b) territory)"
        )
        print(
            f"  Direct varies across calls:  {direct_varies}  "
            f"(uncontrolled non-determinism — Stage 1 investigation target)"
        )

        # Stage 1 sub-step 0 post-fix baseline: BOTH slots must now be stable
        # across identical passive calls. Direct rotation will return only
        # when Stage 1 sub-step 1 lands controlled (transcript-aware) novelty
        # decay, gated by a ``recently_surfaced`` argument the hook supplies.
        assert persona_stable, (
            "Persona slot was expected to be stable across identical "
            "ambient_recall calls (Heavy Persona Dominance). If varying, "
            "investigate whether persona ranking gained an unintended random "
            "tie-breaker."
        )
        assert not direct_varies, (
            "Direct slot was expected to be stable across identical passive "
            "ambient_recall calls (post-2026-05-25 fix: return_count no "
            "longer mutates under passive=True). If now varying, either: "
            "(a) novelty decay (Stage 1 sub-step 1) landed and is firing "
            "without recently_surfaced input — bug, or "
            "(b) a NEW side-effect path was introduced into passive recall. "
            "See Plans-Ambient-Recall-Lateral-Association.md Stage 1 sub-step 0."
        )
    finally:
        await eng.shutdown()
