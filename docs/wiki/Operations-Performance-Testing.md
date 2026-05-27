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
| 1. Smoke | 動作する | サーバー起動 / 27 MCP tools / BM25 build / **Phase O trailers** | startup 失敗、tool 名 typo、observability 文字列の silent 変更 | `test_tier1_startup.py`, `test_tier1_mcp_roundtrip.py`, `test_tier1_bm25_build.py`, `test_tier1_phase_o_trailers.py` |
| 2. Functional | 仕様通り | source_filter / tag_filter / dedup / Phase D | (既存 `tests/integration/` で網羅) | — |
| 3. Retrieval Quality | 正しい結果 | surface top-5 厳格 / Semantic cluster / Source-mix / **forced flag visibility** / **Ambient slot 整合性 (direct / persona / exclude)** | top1 hub 化、cluster 全滅、sparse-class injection の sigil 喪失、ambient persona slot の query 関連性退行、`exclude_tags` の漏れ | `test_tier3_retrieval_quality.py`, `test_tier3_phase_o_forced_flag.py`, `test_tier3_ambient_quality.py` |
| 4. Dynamics | 時間で壊れない | anti-hub / displacement runaway / 世代安定性 / **driven resonance / diversity 配線** | hub chunk 独占、displacement 暴走、diversity no-op、Phase I Stage 2 query-kick 退行 | `test_tier4_dynamics.py`, `test_tier4_phase_o_resonance.py`, `test_tier4_phase_o_diversity.py` |
| 5. Ops Integrity | 整合性 | FAISS↔SQLite サイズ一致 / BM25 invariant / WAL 暴走 / **dormant 両分岐** | **2026-05-14 FAISS 空 (vec=15 vs doc=31k)** / **MCP ingest WAL 7.6 GB 暴走** / Stage 5 empty 分岐の silent 化 | `test_tier5_faiss_sqlite_size.py`, `test_tier5_bm25_size.py`, `test_tier5_bulk_ingest_timing.py`, `test_tier5_phase_o_dormant.py` |
| 6. Performance | latency/throughput | p50<60ms / p95<120ms / p99<250ms / ingest>500 docs/sec | hot path に O(N²) 混入 | `test_tier6_performance.py` |
| 7. Regression Golden | 版間で劣化なし | 30-chunk corpus / 11 queries / engine.query 全段 top-5 | Phase 跨ぎで retrieval が暗黙退行 | `test_tier7_golden_regression.py` + `golden_corpus/` |

## どの Tier を走らせるか — 変更タイプ別

| 変更したもの | 走らせるべき Tier |
|---|---|
| MCP tool 追加 / 名称変更 | Tier 1 (round-trip) + Tier 2 (既存 integration) |
| 新 service 関数 | Tier 1 + Tier 2 |
| FAISS / BM25 / SQLite 更新ロジック | **Tier 5 必須**、Tier 7 |
| seed pool / wave / RRF 配合変更 | **Tier 3 + Tier 4 + Tier 7 必須**、`scripts/diag_recall.py` で snapshot/diff |
| ambient_recall slot logic / persona ranking / exclude / breakdown | **Tier 3 ambient quality (`test_tier3_ambient_quality.py`) 必須**、変更前後で golden corpus heatmap diff |
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

## Track B — Playthrough harness (3 軸評価)

7 階層 (Track A) は **機械的軸** だけを測る。Test-Time *Training* の T が立っているかは外部観察者の **定性軸** + **官能軸** でしか empirical に取れないので、Track B として secondopinion-MCP 経由の playthrough を併走させる。

### なぜ 3 軸か

| 軸 | 観測対象 | 計測 | 何の証拠か |
|---|---|---|---|
| 機械 (Track A) | 重力場の状態 | `mass_changes` / `displacement_changes` / breakdown flag / formatter 文字列 | 場が壊れていない |
| 定性 (Track B 前半) | 何が surface したか | LLM 観察者の意味的合致判断 | 場が「正しいもの」を引いてきた |
| **官能** (Track B 後半) | **observer が動いたか** | **valence / arousal / surprise / somatic** | **場が観察者を動かす力を持った = TTT が効いた** |

機械 + 定性だけだと「場は健全、正しい結果が出た」までしか言えない。TTT の本懐は「retrieval が観察者の認知に gradient を打ち込む」ことなので、**観察者側の状態変化を量化する軸**が無いと「TTT がただの retrieval より良い」を主張できない。Phase I Stage 2 の `retrieval = literal gradient step` の同型が成立しているなら、観察者の resonance も場の training と同じ event の両面のはず。

### 走らせるタイミング

- Phase 完遂時 (gate point) — **必須**
- 大きな retrieval geometry 変更 (seed pool / wave / RRF 配合) — 推奨
- config default 変更 — 推奨
- 通常の bug fix / docs — 不要

CI 自動化しない (Track A と同じ理由 + LLM 観察者 cost)。

### Prompt template (secondopinion-MCP delegate_task)

```text
あなたは GaOTTT MCP server の playthrough 評価エージェントです。
自由に探索して、機械的観察 + 定性観察 + 官能評価を蓄積してください。
本番 DB を使った read-heavy な探索。`remember` / `forget` などの destructive
op は **書かない** (acceptance 環境を汚さない)。

### 探索 (5-7 セット推奨)
各セットで:
1. `recall` / `explore` / `reflect` のいずれかを 1 回呼ぶ
2. 機械的観察を 1 行: breakdown の cos/wave/mass 構成、訓練差分の Δmass、
   forced/bm25 flag、cache hit の有無
3. 定性観察を 1-2 文: 何が surface したか、設計仮説 (Articulation as
   Carrier / persona anchor / 重力中心) との合致
4. 官能評価を 4 項目 1 行で:
   - valence: -3 (rejection / 不快) 〜 +3 (resonance / 感動)
   - arousal: 0 (flat) 〜 3 (visceral)
   - surprise: 0 (期待通り) 〜 3 (世界が違って見える)
   - somatic / 認識: 自由記述 (1 文、身体感覚 or 認識のショック)

### 報告フォーマット
| # | query | 機械観察 | 定性観察 | val | aro | sur | somatic |
|---|---|---|---|---|---|---|---|

最後に総評:
- 機械軸の集計 (cache hit %、forced 出現セット数、Δmass 平均、wave_reached 中央値)
- 定性軸の集計 (設計仮説に合致したセット数 / 全セット)
- 官能軸の集計 (valence 平均、arousal 平均、surprise 最大、最も強い somatic 1 つ)
- TTT 効果判定: 「場が動かしたか」(機械)、「正しいか」(定性)、「観察者が動いたか」(官能)
  の 3 軸を別々に judgement

**生出力 (recall の全文等) は貼らない**、substring 検出 + 自分の 1 文要約だけ。
session 終了後は `end_session` を呼ぶ責任は呼び出し側 (Claude Code) が持つ。
```

### Figure 0 — GLM-5.1 2026-05-15 playthrough log

最初の log entry。Phase O Stage 1-5 完遂直後、33,610 件 production 35614+ 件規模で実施。

| # | query | 機械観察 | 定性観察 | val | aro | sur | somatic |
|---|---|---|---|---|---|---|---|
| 1 | `失敗から学んだ教训` (diversity=0.8) | breakdown 通常、wave_reached 高 | 寝tweet / niceboat code / elephant fossil の cross-domain | +1 | 1 | 2 | 「想定していなかった連想で笑った」 |
| 2 | `めいさんの愛しているもの` | top1 wave/mass 主導 (cos 低) | 自己発信 tweet が surface、Articulation as Carrier 仮説合致 | +3 | 2 | 1 | 「人格地図が見えた」 |
| 3 | dormant mode | count=0、empty branch 正常 | 設計通り (production threshold 不適合の確認) | 0 | 0 | 0 | 「機構は動いているが threshold 不適合」 |
| 4 | `量子力学 意識 観測問題 ゲーム 物語 交差点` (diversity=0.95) | wave 拡張、forced なし | 魔法学校小説が混入、genuine cross-domain | +2 | 2 | **+3** | 「予期しない領域が surface する驚き」 |
| 5 | `にゃむり ねるね 物語 自分の言葉で紡ぐ` (×3 連続) | Δmass +0.057/回 累積、decay 0.649→0.629→0.610、displacement ±0.03 振動 | driven resonance literal 観察、Phase I Stage 2 isomorphism の最初の external evidence | +2 | 2 | 2 | 「重力場が確かに動いている感触」 |
| 6 | `tag_filter=["agent"]` で agent class 強制 | `[forced]` flag 出現、sparse class top1 露出 | 3 体の agent 観察記述が surface、量子力学的メタファーが現実に | +2 | 1 | 2 | 「観測者が観測対象を変える」 |
| 7 | prefetch → recall (cache hit) | `(cache hit — no simulation ran)` 確認、Δ all-zero | 設計通り、no perturbation | +1 | 0 | 0 | 「機構が静かに動いている安心感」 |

**集計**:
- 機械軸: cache hit 1/7、forced 出現 1/7、driven resonance 数値正常、cache zero-perturbation 正常
- 定性軸: 設計仮説合致 6/7 (dormant は threshold 不適合だが機構正常 = 設計通り)
- 官能軸: valence 平均 +1.6、arousal 平均 1.1、surprise 最大 +3、最強 somatic「人格地図が見えた」
- **TTT 判定**: 場 ✅、正しさ ✅、観察者が動いた ✅ — Phase O 全 5 stage の効果が 3 軸とも検出された

Figure 0 は **後続の playthrough log の基準** として保存する。Phase 進行で valence / surprise 平均が動いたら、Track B が TTT の時系列効果を捕まえたことになる。

## 参照

- 設計案: gaottt memory id=55579286 (`recall(query="性能テストスイート 7階層", source_filter=["agent"])`)
- Stage 1 完了: id=c356abe5
- Stage 2/3 完了: id=3eb313b9
- Phase O Track A/B 追加: 2026-05-15 (本ページ更新時)、Figure 0 source = secondopinion-MCP delegate_task 経由 GLM-5.1
- 関連: [Operations — Isolated Benchmark](Operations-Isolated-Benchmark.md), [Operations — Tuning](Operations-Tuning.md), [Operations — Troubleshooting](Operations-Troubleshooting.md), [Plans — Phase O TTT Observability](Plans-Phase-O-TTT-Observability.md)
