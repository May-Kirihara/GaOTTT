# tests/perf — GaOTTT 性能・品質テストスイート

7 階層フレームワーク（設計案 id=55579286、2026-05-14）の実装。本日の事件群
（FAISS 空 / MCP ingest WAL 暴走 / RRF scale 不整合 / hub chunk）を
**次回ベースラインで即検知** できる状態を目指す。

## 7 階層

| 階層 | 目的 | 例 | このディレクトリでの fixture 名 |
|---|---|---|---|
| 1. Smoke | 動作する | サーバー起動、25 MCP tools、BM25 build | `test_tier1_*` |
| 2. Functional | 仕様通り | source_filter, tag_filter, dedup, Phase D | `tests/integration/` で既存 |
| 3. Retrieval Quality | 正しい結果 | known-text extraction, multi-query, source-mix | `test_tier3_*` |
| 4. Dynamics | 時間で壊れない | 世代テスト, hub 検出, displacement 暴走 | `test_tier4_*` |
| 5. Ops Integrity | 整合性 | FAISS↔SQLite サイズ一致, WAL 暴走防止, bulk timing | `test_tier5_*` |
| 6. Performance | latency/throughput | p50/p99, ingest tput, startup, memory | `test_tier6_*` |
| 7. Regression Golden | 版間で劣化なし | golden corpus, score scale baseline | `test_tier7_*` + `golden_corpus/` |

## 段階着手 (実装履歴)

- **Stage 1** (commitment id=faf61f5f、2026-05-14 完了): Tier 1 + Tier 5 + Tier 7 雛形
- **Stage 2** (同日完了): Tier 3 + Tier 4 + `scripts/diag_recall.py`
- **Stage 3** (同日完了): Tier 6 + `scripts/perf_baseline.py` + `scripts/perf_diff.py` + `.github/workflows/perf-tests.yml`

実装状況: **38 tests pass / 7.4s / ruff clean**。

## 実行

```bash
# 全 perf テスト (pytest が自動収集)
.venv/bin/python -m pytest tests/perf/ -q

# 特定 Tier だけ
.venv/bin/python -m pytest tests/perf/test_tier1_*.py -v
.venv/bin/python -m pytest tests/perf/test_tier5_*.py -v
```

本番 DB 非接続。各テストは `tmp_path` で隔離 engine を立ち上げ、
`tests/integration/test_engine_archive_ttl.py::StubEmbedder`
（トークン重なりで類似度が決まる決定論的 embedder）を再利用する。

## 命名規約

- `test_tier<N>_<short_name>.py` — N は 1-7
- ヘルパ stub / fixture は `_helpers.py` に集約（必要になったら）
- golden corpus は `golden_corpus/` 直下（synthetic_chunks.jsonl + queries.yaml）

## 関連スクリプト

- `scripts/diag_recall.py` — engine.query / BM25 / raw FAISS の per-query JSON snapshot + diff
- `scripts/perf_baseline.py` — Tier 6 metrics を `tests/perf/baselines/` に snapshot
- `scripts/perf_diff.py` — 2 baseline を diff、regression threshold で exit 1

## CI

`.github/workflows/perf-tests.yml` — push/PR で `tests/perf/` 全件 + perf_baseline を artifact 化。回帰 gate は default disabled (チームで threshold 合意してから enable)。

## SoT

設計の根拠と未来の展望は memory id=55579286 (`gaottt.recall(query="性能テストスイート 7階層", source_filter=["agent"])`)。Stage 1/2/3 完了履歴は id=c356abe5 (Stage 1) と Stage 2/3 完了 memory。
