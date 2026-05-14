# Operations — Performance Testing (7 階層テストスイート)

`tests/perf/` に常駐する **仮説 → 実装 → 検証** ループの検証フェーズ用テストスイート。real RURI v3 310m embedder を使い、production-grade な数値で実装の影響を測る。

> **★ CI に組み込まない**: これは手動 verification tool。実装が一段落したら開発者が deliberately 走らせる。"自動化された安全網" ではなく "仮説検証のための measurement step"。

## いつ走らせるか

CLAUDE.md「実装フロー」の step 7 にあたる。新機能・hot path 変更・retrieval geometry に手を入れた変更を実装したら:

```bash
.venv/bin/python -m pytest tests/perf/ -q       # 全 38 tests、~15s (RURI load 込み)
```

仮説 → 実装 → 検証ループの **検証** はこれで完結。CI で勝手に走らせるとシグナルが薄まる ("PR merge したら通った" は何の保証にもならない)。

## 7 階層フレームワーク

各 Tier は対応する事件群が起こったときに鳴ることを意図して切ってある。

| 階層 | 目的 | 例 | カバー事件 | tests/perf/ ファイル |
|---|---|---|---|---|
| 1. Smoke | 動作する | サーバー起動 / 25 MCP tools / BM25 build | startup 失敗、tool 名 typo | `test_tier1_startup.py`, `test_tier1_mcp_roundtrip.py`, `test_tier1_bm25_build.py` |
| 2. Functional | 仕様通り | source_filter / tag_filter / dedup / Phase D | (既存 `tests/integration/` で網羅) | — |
| 3. Retrieval Quality | 正しい結果 | surface top-5 厳格 / Semantic cluster / Source-mix | top1 hub 化、cluster 全滅 | `test_tier3_retrieval_quality.py` |
| 4. Dynamics | 時間で壊れない | anti-hub / displacement runaway / 世代安定性 | hub chunk 独占、displacement 暴走 | `test_tier4_dynamics.py` |
| 5. Ops Integrity | 整合性 | FAISS↔SQLite サイズ一致 / BM25 invariant / WAL 暴走 | **2026-05-14 FAISS 空 (vec=15 vs doc=31k)** / **MCP ingest WAL 7.6 GB 暴走** | `test_tier5_faiss_sqlite_size.py`, `test_tier5_bm25_size.py`, `test_tier5_bulk_ingest_timing.py` |
| 6. Performance | latency/throughput | p50<60ms / p95<120ms / p99<250ms / ingest>500 docs/sec | hot path に O(N²) 混入 | `test_tier6_performance.py` |
| 7. Regression Golden | 版間で劣化なし | 30-chunk corpus / 11 queries / engine.query 全段 top-5 | Phase 跨ぎで retrieval が暗黙退行 | `test_tier7_golden_regression.py` + `golden_corpus/` |

## どの Tier を走らせるか — 変更タイプ別

| 変更したもの | 走らせるべき Tier |
|---|---|
| MCP tool 追加 / 名称変更 | Tier 1 (round-trip) + Tier 2 (既存 integration) |
| 新 service 関数 | Tier 1 + Tier 2 |
| FAISS / BM25 / SQLite 更新ロジック | **Tier 5 必須**、Tier 7 |
| seed pool / wave / RRF 配合変更 | **Tier 3 + Tier 4 + Tier 7 必須**、`scripts/diag_recall.py` で snapshot/diff |
| ingest / chunker 変更 | Tier 5 (bulk timing) + Tier 7 |
| config default 変更 | Tier 4 + Tier 6 + Tier 7 |
| 新依存追加 / startup 経路変更 | Tier 1 + Tier 6 |
| hot path optimization | Tier 6 + `perf_baseline.py` で前後比較 |
| docs だけ | (走らせなくて良い) |

迷ったら **全部走らせる**: `.venv/bin/python -m pytest tests/perf/ -q` で ~15 秒。

## 観測される real RURI 数値 (2026-05-14 基準)

| metric | 観測値 | budget |
|---|---|---|
| recall p50 (200 doc) | ~35ms | < 60ms (CLAUDE.md target < 50ms に ~70% headroom) |
| recall p95 | ~56ms | < 120ms |
| recall p99 | ~85ms | < 250ms |
| ingest throughput (500 doc) | ~1200 docs/sec | > 500 docs/sec |
| engine init (model in singleton) | ~0.02s | < 30s |
| compact (200 docs) | ~0.01s | < 30s |

CLAUDE.md "p50 < 50ms" target は実 user latency。観測値 ~35ms は target 内 (~70% headroom)。

## golden corpus (Tier 7)

`tests/perf/golden_corpus/synthetic_chunks.jsonl` — 5 topic cluster × 5 chunk + 3 cross-vocabulary (JP/mixed) + 2 distractor = **30 chunks**。
`queries.json` — 11 query (surface 5 / semantic-cluster 3 / cross-vocabulary 2 / source-mix 1)。

real RURI で `engine.query` top-5 に expected fixture が landed することを assert (Stage 1 の BM25 直叩きから昇格、2026-05-14)。

corpus を拡張するときは `tests/perf/golden_corpus/README.md` の手順に従う:
1. 新 chunk を `synthetic_chunks.jsonl` に追加 (id は安定保持)
2. 少なくとも 1 query をその id を expected に追加
3. Tier 7 を走らせ、新 chunk が既存 query 期待を crowd-out するなら fixture を見直す

## Tier 6 baseline / regression detection (仮説→実装→検証 ループ用)

仮説に基づいて実装する前後で数値を取り、diff で確認する典型ワークフロー:

```bash
# 1. 実装前の baseline
.venv/bin/python scripts/perf_baseline.py --label phase-X-pre

# 2. 仮説に基づいて実装

# 3. 実装後の baseline
.venv/bin/python scripts/perf_baseline.py --label phase-X-post

# 4. 直近 2 baseline を diff、>25% regression で exit 1
.venv/bin/python scripts/perf_diff.py
```

Measured metrics (real RURI、200 doc / 100 recall):
- `cold_startup_seconds`、`warm_startup_seconds`
- `ingest_seconds`、`ingest_docs_per_sec`
- `recall_p50_ms`、`recall_p95_ms`、`recall_p99_ms`
- `compact_seconds`

threshold は `--threshold 0.10` などで上書き可。

baseline file の commit は **意味のある節目だけ** (Phase 完遂、大型 refactor)。毎回 commit すると `tests/perf/baselines/` がパンクする。詳細: `tests/perf/baselines/README.md`。

## diag_recall.py — per-query 3 layer snapshot

retrieval 挙動の **per-query 詳細** (engine.query top-K、BM25 top-K、raw FAISS top-K) を JSON snapshot として取り、版間で diff できる:

```bash
# 単発
.venv/bin/python scripts/diag_recall.py snapshot \
    --query "Eleventy Pipeline" --top-k 5 \
    --data-dir ./.diag-tmp --out ./.diag-before.json

# golden corpus 全 query を 1 ファイルに
.venv/bin/python scripts/diag_recall.py snapshot \
    --queries-file tests/perf/golden_corpus/queries.json \
    --data-dir ./.diag-tmp --out ./.diag-before.json

# ... 変更 ...

.venv/bin/python scripts/diag_recall.py diff ./.diag-before.json ./.diag-after.json
```

diff は query ごとに `engine_top` / `bm25_top` / `raw_faiss_top` の id 集合差分 + reorder を出力。
**read-only**、`--data-dir` で本番 DB と隔離。本番に当てたい場合は `--data-dir` を省略すると `from_config_file()` で読みに行く (write 操作はしないが、他プロセスと compact が衝突する瞬間は避ける)。

## 既知の特性

- **Tier 3 path A は plain `engine.query` の top-5 contract** — real RURI で semantic match が機能するので strict (StubEmbedder 時の widened-pool hack は撤廃)。Path B は `tag_filter` 注入で Phase J Stage 2 + Phase L Stage 1 RRF re-rank 経路。両方が動くことが production parity の確認。
- **Tier 4 displacement bound は equilibrium 7× headroom (20.0)** — CLAUDE.md "d ≈ (G·m/k)^(1/3) ≈ 0.8–3.0" を根拠とする honest bound。equilibrium 収束過程を runaway と誤検知しないように config cap + practical bound の 2 段。
- **Tier 5 BM25 size は compact 不要で即時 invariant** — engine が remember/forget/merge で BM25 を同期更新する。FAISS は `compact(rebuild_faiss=True)` 後に invariant が strict equality。
- **RURI model は session 単位で 1 回 load** — `_helpers.get_shared_embedder()` の singleton。最初の test だけ ~5-10 秒、それ以降は memory 参照のみ。pytest -n parallel は使わない (model singleton 共有を壊す)。

## 参照

- 設計案: gaottt memory id=55579286 (`recall(query="性能テストスイート 7階層", source_filter=["agent"])`)
- Stage 1 完了: id=c356abe5
- Stage 2/3 完了: id=3eb313b9
- 関連: [Operations — Isolated Benchmark](Operations-Isolated-Benchmark.md), [Operations — Tuning](Operations-Tuning.md), [Operations — Troubleshooting](Operations-Troubleshooting.md)
