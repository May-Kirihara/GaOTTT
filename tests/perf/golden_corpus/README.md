# Golden corpus — Tier 7 regression baseline

A small, hand-curated set of synthetic chunks + queries with **frozen
expected top-K answers**. The point isn't realism — it's that the same
inputs must produce the same (or compatible) outputs across versions.
When the engine drifts (RRF scale change, BM25 tokenizer swap, source
filter regression), Tier 7 fails first.

## Files

- `synthetic_chunks.jsonl` — one JSON object per line:
  ```json
  {"id": "chunk_001", "content": "...", "source": "synthetic", "tags": ["topic-X"]}
  ```
  `id` is the *fixture* id used to identify a chunk in expectations;
  the engine assigns its own UUID at ingest time. The mapping
  (fixture_id → engine_id) is built by the test fixture.

- `queries.json` — JSON array of query records:
  ```json
  [
    {
      "query": "exact lexical phrase X",
      "expected_top": ["chunk_001", "chunk_007"],
      "note": "BM25 should dominate"
    }
  ]
  ```
  `expected_top` is the *acceptable* set — the test asserts that
  every fixture id in this list appears in the engine's top-K. The
  threshold (default 3) is set by the test. JSON (not YAML) so no
  extra test dependency.

## Stage 2 corpus (2026-05-14)

30 chunks across 5 topic clusters (5 chunks each) + 3 cross-vocabulary
(JP/mixed) + 2 distractors. 11 queries covering 3 axes:

| Axis | Queries | Match shape |
|---|---|---|
| `surface` | 5 | `expected_top` — exact id must appear |
| `semantic-cluster` | 3 | `expected_top_any` — any cluster member acceptable |
| `cross-vocabulary` | 2 | `expected_top_any` — JP or EN form acceptable |
| `source-mix` | 1 | `expected_top_any` — cluster not entirely shut out |

Topic clusters (chunk_id prefix):

- `chunk_00X / 01X` — Eleventy / static site (5)
- `chunk_002 / 02X` — Sicily / WWII Mediterranean (5)
- `chunk_003 / 03X` — Neuro / astrocyte (5)
- `chunk_004 / 04X` — FAISS / retrieval (5)
- `chunk_005 / 05X` — Cooking / Italian (5)
- `chunk_06X` — Cross-vocabulary (JP/mixed) (3)
- `chunk_07X` — Distractors (2)

## Adding to the corpus (Stage 2+)

1. Add a chunk to `synthetic_chunks.jsonl` with a stable `id`.
2. Add at least one query in `queries.json` whose `expected_top`
   includes that `id`.
3. Run `tests/perf/test_tier7_golden_regression.py` — if it fails on
   an existing query, decide whether the new chunk legitimately
   crowds the prior expectation (update `expected_top`) or whether
   the engine just regressed.

The "did we regress" judgment requires reading the failure carefully.
That's the point — a passing Tier 7 is a *checked* claim that today's
behaviour matches yesterday's, not a syntactic guarantee.
