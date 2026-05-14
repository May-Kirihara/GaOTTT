# tests/perf — GaOTTT 性能・品質検証スイート

**仮説 → 実装 → 検証** の **検証フェーズ** で手動実行する、real RURI v3 310m を使った 7 階層テストスイート。production-grade な数値で「実装した変更が現実的に何を改善したか／劣化させたか」を測る。

> **★ CI で自動実行しない** — 手動 verification tool。実装が一段落したら走らせる。

## 使い方

```bash
# 全 38 tests を real RURI で走らせる (model load 含めて 15-20 秒)
.venv/bin/python -m pytest tests/perf/ -v

# 特定 Tier だけ
.venv/bin/python -m pytest tests/perf/test_tier6_*.py -v -s   # perf 数値も print

# 仮説検証ワークフロー (before/after の差分を見たい時)
.venv/bin/python scripts/perf_baseline.py --label before
#   ...仮説に基づいて実装...
.venv/bin/python scripts/perf_baseline.py --label after
.venv/bin/python scripts/perf_diff.py    # 直近 2 baseline diff、>25% で exit 1
```

## 7 階層

7.4 → 14.5 秒 で全件、`.venv/bin/python -m pytest tests/perf/ -q`。RURI model は session 単位で 1 回だけ load (`_helpers.get_shared_embedder` の singleton)。

| 階層 | 目的 | 例 | tests/perf/ ファイル |
|---|---|---|---|
| 1. Smoke | 動作する | サーバー起動、25 MCP tools、BM25 build | `test_tier1_*` |
| 2. Functional | 仕様通り | source_filter, tag_filter, dedup, Phase D | `tests/integration/` で既存 |
| 3. Retrieval Quality | 正しい結果 | surface top-5 厳格、semantic cluster、source-mix sanity | `test_tier3_retrieval_quality.py` |
| 4. Dynamics | 時間で壊れない | anti-hub diversity, displacement bound, top-set stability | `test_tier4_dynamics.py` |
| 5. Ops Integrity | 整合性 | FAISS↔SQLite size invariant, BM25 size, bulk timing | `test_tier5_*` |
| 6. Performance | latency/throughput | recall p50<60ms, p95<120ms, p99<250ms, ingest>500 docs/sec | `test_tier6_performance.py` |
| 7. Regression Golden | 版間で劣化なし | golden corpus 30 chunks × 11 queries で engine.query top-5 | `test_tier7_*` + `golden_corpus/` |

## 実装フローでの位置

CLAUDE.md「実装フロー」の step 7 にあたる。新機能・hot path 変更・retrieval geometry に手を入れた変更を実装したら:

1. 仮説を立てる (例:「BM25 の RRF weight を調整したら surface match の top1 が改善するはず」)
2. 実装する
3. **`pytest tests/perf/` で 検証** — 仮説通りに動いたか、副作用は無いか
4. 数値が動いたら `scripts/perf_baseline.py` で before/after を取って `perf_diff.py` で diff

回帰したら設計を疑う、進歩したら memory に save。

## 関連スクリプト

- `scripts/diag_recall.py` — engine.query / BM25 / raw FAISS の per-query JSON snapshot + diff
- `scripts/perf_baseline.py` — Tier 6 metrics を `tests/perf/baselines/` に snapshot (real RURI)
- `scripts/perf_diff.py` — 2 baseline を diff、regression threshold で exit 1

## SoT

設計の根拠と未来の展望は memory id=55579286 (`gaottt.recall(query="性能テストスイート 7階層", source_filter=["agent"])`)。Stage 1/2/3 完了履歴は id=c356abe5 / id=3eb313b9。意図の整理 (CI 不要、手動 verification) は 2026-05-14 めいさん指摘の結果。
