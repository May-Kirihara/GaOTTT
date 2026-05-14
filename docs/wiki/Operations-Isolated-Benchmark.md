# Operations — Isolated Benchmark

ベンチマークを **本番 DB を触らずに** 走らせる隔離実行スクリプト。

> **使い分け**: 開発時の日常的な perf 退行検知は [Operations — Performance Testing](Operations-Performance-Testing.md) (`tests/perf/` の Tier 6、StubEmbedder ベース、~7 秒で 38 tests) を先に走らせる。**実 RURI embedder + 本番に近い corpus** で確認したいとき、または latency の絶対値が CLAUDE.md "p50 < 50ms" を満たすか検証したいときに **このページの `scripts/run_benchmark_isolated.sh`** を使う。両者は補完関係。

## なぜ隔離するか

通常のベンチマークは大量のクエリと記憶操作を行うため、本番 GaOTTT DB（数千〜数万件のあなた自身の記憶）を汚染する可能性がある。隔離スクリプトは `/tmp/gaottt-bench/` で完全に独立した DB を使用。

## 起動

```bash
# 200 件で隔離ベンチ（既定）
.venv/bin/bash scripts/run_benchmark_isolated.sh

# 件数を変える
.venv/bin/bash scripts/run_benchmark_isolated.sh 1000

# 別ポートで実行（既定 8765）
BENCH_PORT=8800 ./scripts/run_benchmark_isolated.sh

# 別ディレクトリに退避
BENCH_DIR=/tmp/my-bench ./scripts/run_benchmark_isolated.sh
```

## 挙動

1. `GAOTTT_DATA_DIR=/tmp/gaottt-bench` を設定して uvicorn を起動 → 本番 DB は不可触
2. 200 件（or 指定数）の文書をベンチ DB に投入
3. SC-001〜SC-007 + Baseline drift を実行
4. 結果は `/tmp/gaottt-bench/report.json` に保存
5. ベンチ DB は確認用に残す（`rm -rf /tmp/gaottt-bench` で消去）

## 評価される項目

| ID | 内容 | 基準 |
|---|---|---|
| SC-001 | クエリレイテンシ | p50 < 50ms |
| SC-002 | 質量蓄積 | 反復検索で mass↑ |
| SC-003 | 時間減衰 | 直近アクセス boost |
| SC-004 | 共起グラフ | エッジ形成 |
| SC-005 | 並行性 | 50 同時クエリで 0 エラー |
| SC-006 | 永続化 | 状態保存 |
| Baseline | Static RAG vs GaOTTT | スコア drift 確認 |

## 現状の数値（Phase D 完了時点）

```
SC-001 Latency:        p50=15.1ms, p95=16.7ms, p99=26.2ms (200 docs)
SC-005 Concurrency:    50 succeeded, 0 failed
全 7 項目 PASS
```

## 開発フロー

```bash
# 1. 単体 + 統合テスト
.venv/bin/python -m pytest tests/ -q

# 2. ★ 7 階層 perf テストスイート (StubEmbedder、構造的回帰を素早く検知)
.venv/bin/python -m pytest tests/perf/ -q

# 3. このページの isolated bench (実 RURI、絶対値の確認)
rm -rf /tmp/gaottt-bench
.venv/bin/bash scripts/run_benchmark_isolated.sh
```

→ 関連: [Performance Testing (7 階層)](Operations-Performance-Testing.md), [Tuning](Operations-Tuning.md), [Troubleshooting](Operations-Troubleshooting.md)
