# Operations — Performance Testing (7 階層テストスイート)

`tests/perf/` に常駐する **構造的回帰を即時検知するためのテストスイート**。
2026-05-14 完成、設計案は memory id=55579286、commitment id=faf61f5f-6d8a-47e7-a5e2-43346dec1817。

> **★ いつ走らせるか**
> retrieval geometry を触った / config default を変えた / hot path を書き換えた / 新機能を入れた、いずれかに該当する変更を作ったら **必ず実行**:
> ```bash
> .venv/bin/python -m pytest tests/perf/ -q
> ```
> 38 tests / 約 7.4 秒 / ruff clean。本番 DB は **触らない**（全テストが `tmp_path` で隔離した StubEmbedder engine を立ち上げる）。

## 7 階層フレームワーク

「動作する → 仕様通り → 正しい結果 → 時間で壊れない → 整合性 → 速い → 回帰しない」の階段。各 Tier は対応する事件群が起こったときに鳴ることを意図して切ってある。

| 階層 | 目的 | 例 | カバー事件 | tests/perf/ ファイル |
|---|---|---|---|---|
| 1. Smoke | 動作する | サーバー起動 / 25 MCP tools / BM25 build | startup 失敗、tool 名 typo | `test_tier1_startup.py`, `test_tier1_mcp_roundtrip.py`, `test_tier1_bm25_build.py` |
| 2. Functional | 仕様通り | source_filter / tag_filter / dedup / Phase D | (既存 `tests/integration/` で網羅) | — |
| 3. Retrieval Quality | 正しい結果 | known-text extraction、Surface/Semantic/Source-mix | top1 hub 化、cluster 全滅 | `test_tier3_retrieval_quality.py` |
| 4. Dynamics | 時間で壊れない | anti-hub / displacement runaway / 世代安定性 | hub chunk 独占、displacement 暴走 | `test_tier4_dynamics.py` |
| 5. Ops Integrity | 整合性 | FAISS↔SQLite サイズ一致 / BM25 invariant / WAL 暴走 | **2026-05-14 FAISS 空 (vec=15 vs doc=31k)** / **MCP ingest WAL 7.6 GB 暴走** | `test_tier5_faiss_sqlite_size.py`, `test_tier5_bm25_size.py`, `test_tier5_bulk_ingest_timing.py` |
| 6. Performance | latency/throughput | p50/p95/p99 / ingest / startup / compact | hot path に O(N²) 混入 | `test_tier6_performance.py` |
| 7. Regression Golden | 版間で劣化なし | 30-chunk golden corpus / 11 query / Surface×Semantic×Cross-vocab | Phase 跨ぎで retrieval が暗黙退行 | `test_tier7_golden_regression.py` + `golden_corpus/` |

## どの Tier を走らせるか — 変更タイプ別

| 変更したもの | 走らせるべき Tier |
|---|---|
| MCP tool 追加 / 名称変更 | Tier 1 (round-trip) + Tier 2 (既存 integration) |
| 新 service 関数 | Tier 1 + Tier 2 |
| FAISS / BM25 / SQLite 更新ロジック | **Tier 5 必須**、Tier 7 |
| seed pool / wave / RRF 配合変更 | **Tier 3 + Tier 4 + Tier 7 必須**、`scripts/diag_recall.py` で snapshot/diff |
| ingest / chunker 変更 | Tier 5 (bulk timing) + Tier 7 |
| config default 変更 | Tier 4 + Tier 6 + Tier 7 |
| 新依存追加 / startup 経路変更 | Tier 1 + Tier 6 (cold/warm startup) |
| hot path optimization | Tier 6 + `perf_baseline.py` で前後比較 |
| docs だけ | (走らせなくて良い) |

迷ったら **全部走らせる**: `.venv/bin/python -m pytest tests/perf/ -q` で 7.4 秒。

## golden corpus (Tier 7)

`tests/perf/golden_corpus/synthetic_chunks.jsonl` — 5 topic cluster × 5 chunk + 3 cross-vocabulary (JP/mixed) + 2 distractor = **30 chunks**。
`queries.json` — 11 query (surface 5 / semantic-cluster 3 / cross-vocabulary 2 / source-mix 1)。

corpus を拡張するときは `tests/perf/golden_corpus/README.md` の手順に従う:
1. 新 chunk を `synthetic_chunks.jsonl` に追加（id は安定保持）
2. 少なくとも 1 query をその id を expected に追加
3. Tier 7 を走らせ、新 chunk が既存 query 期待を crowd-out するなら fixture を見直す

## Tier 6 baseline / regression detection

```bash
# Baseline 取得 — tests/perf/baselines/<UTC>_<git_sha>_<label>.json に保存
.venv/bin/python scripts/perf_baseline.py --label "phase-X-pre"

# ... コード変更 ...

# 再取得
.venv/bin/python scripts/perf_baseline.py --label "phase-X-post"

# 直近 2 baseline を diff、>25% regression で exit 1
.venv/bin/python scripts/perf_diff.py
```

Measured metrics (StubEmbedder、200 doc / 100 recall):
- `cold_startup_seconds`、`warm_startup_seconds`
- `ingest_seconds`、`ingest_docs_per_sec`
- `recall_p50_ms`、`recall_p95_ms`、`recall_p99_ms`
- `compact_seconds`

threshold は `--threshold 0.10` などで上書き可。CI gate に組むなら `perf-tests.yml` のコメントアウト節を参照。

> **注意**: `perf_baseline.py` は StubEmbedder ベース (md5-seeded random)。実 RURI embedder + 本番に近い corpus で測りたいときは [Operations — Isolated Benchmark](Operations-Isolated-Benchmark.md) (`scripts/run_benchmark_isolated.sh`) を併用。両者は補完関係。

## diag_recall.py — per-query 3 layer snapshot

retrieval 挙動の **per-query 詳細** (engine.query top-K、BM25 top-K、raw FAISS top-K) を JSON snapshot として取り、版間で diff できる:

```bash
# 単発
.venv/bin/python scripts/diag_recall.py snapshot \
    --query "Eleventy Pipeline" --top-k 5 \
    --data-dir /tmp/gaottt-diag --out /tmp/before.json

# golden corpus 全 query を 1 ファイルに
.venv/bin/python scripts/diag_recall.py snapshot \
    --queries-file tests/perf/golden_corpus/queries.json \
    --data-dir /tmp/gaottt-diag --out /tmp/before.json

# ... 変更 ...

.venv/bin/python scripts/diag_recall.py diff /tmp/before.json /tmp/after.json
```

diff は query ごとに `engine_top` / `bm25_top` / `raw_faiss_top` の id 集合差分 + reorder を出力。
**read-only**、`--data-dir` で本番 DB と隔離。本番に当てたい場合は `--data-dir` を省略すると `from_config_file()` で読みに行く (write 操作はしないが、他プロセスと compact が衝突する瞬間は避ける)。

## CI

`.github/workflows/perf-tests.yml` — push / PR で:
1. ruff check on `tests/perf/` + perf scripts
2. `pytest tests/perf/`
3. `perf_baseline.py` で artifact 化 (`perf-baseline-<sha>`)

regression gate は **default disabled**。チームで threshold (0.25 / 0.30 等) 合意してから workflow の末尾コメントアウトを外す。

## 既知の特性

- **Tier 3 で plain `engine.query` には top-K precision を期待しない** — random embedder の cosine 雑音下では final_score (mass + wave + cosine) が支配する。surface match を top-K に出したいなら `tag_filter` 注入で Phase J Stage 2 + Phase L Stage 1 RRF 経路に乗せる (Path B parameter)。test_tier3 で Path A (widened pool) と Path B (tag_filter) を両方 assert しているのはこの理由。
- **Tier 4 displacement bound は equilibrium 7× headroom (20.0)** — CLAUDE.md "d ≈ (G·m/k)^(1/3) ≈ 0.8–3.0" を根拠とする honest bound。equilibrium 収束過程を runaway と誤検知しないように first5 vs last5 比較ではなく config cap + practical bound の 2 段。
- **Tier 5 BM25 size は compact 不要で即時 invariant** — engine が remember/forget/merge で BM25 を同期更新する。FAISS は `compact(rebuild_faiss=True)` 後に invariant が strict equality。
- **flaky tests は `tests/integration/test_engine_query_kick.py`** (stochastic dynamics)。`tests/perf/` には flaky test は無い。

## 参照

- 設計案: gaottt memory id=55579286 (`recall(query="性能テストスイート 7階層", source_filter=["agent"])`)
- Stage 1 完了: id=c356abe5
- Stage 2/3 完了: id=3eb313b9
- commitment: id=faf61f5f-6d8a-47e7-a5e2-43346dec1817 (2026-05-28 期限、本日完遂)
- 関連: [Operations — Isolated Benchmark](Operations-Isolated-Benchmark.md), [Operations — Tuning](Operations-Tuning.md), [Operations — Troubleshooting](Operations-Troubleshooting.md)
