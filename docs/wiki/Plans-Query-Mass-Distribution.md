# Query as Mass Distribution — Multi-Source Query

> ステータス: **Stage 1-2 実装完了・両フラグ default ON（2026-05-21）**
>
> physics Phase ではない（physics rule を一切変えず seeding のみ変更）— Phase レター非消費。[Ambient Recall](Guides-Ambient-Recall.md) / [Hardening](Plans-Hardening-Concurrency-Persistence.md) と同じ非 phase feature 扱い（Phase N 候補繰り下げの P/Q/R 予約とも衝突しない）。
>
> 関連: [Architecture — Overview](Architecture-Overview.md), [Architecture — Gravity Model](Architecture-Gravity-Model.md), [Ambient Recall](Guides-Ambient-Recall.md), [Plans — Ambient Recall Enrichment](Plans-Ambient-Recall-Enrichment.md), [Plans — Roadmap](Plans-Roadmap.md)

## 背景 — なぜ pooled embedding が un-physical か

GaOTTT のクエリパスはほぼ全段が物理に忠実である。wave 伝播はノード毎の力を加算的に重ね合わせ（`propagate_gravity_wave` の `new_force = old_force + child_force`）、`compute_acceleration` の 4 項も加算的に合成される。重力は **superposition（重ね合わせ）** の系である — 複数の質量があれば、合成場は各場のベクトル和になる。

ところがクエリ埋め込みの 1 箇所だけが非物理だった。`engine._query_internal` は

```python
query_vec = self.embedder.encode_query(text)   # プロンプト全体 → 1 ベクトル
```

でプロンプト全体を 1 つの pooled ベクトルに潰す。これはトークン埋め込みの**平均** — プロンプトを「重心に置いた単一点質量」とみなしている。**重力は質量を平均しない。場を重ね合わせる。** pooling はこのパイプラインで唯一の非物理ステップだった。

### 症状 — 複合プロンプトが重い語に引っ張られる

2026-05-21 の opencode ambient recall 本番観察で顕在化した。プロンプト:

> 「philharmonic と GaOTTT の記憶を使って、harakiriworks の web サイトを SPA で作って」

これは **2 つの要求の合成**である — メタ指示（「GaOTTT の記憶を使って」）と実タスク（「harakiriworks の SPA」）。pooled な 1 ベクトルは両者の重心で、コーパス内で語彙的に重い側（このコーパスは GaOTTT 自身の開発履歴なので「GaOTTT」「記憶」が至るところにある）に引っ張られ、実タスクが溺れた。retrieval のバグではなく、**クエリだけ平均で潰しているという物理的不整合**の症状である。

## 中核アイデア — クエリを質量分布として扱う

プロンプトを節に分割し、各節を独立した **点質量** として扱う。pooling で潰さず、**seed pool レベルで superpose する**:

```
プロンプト
   ↓ segment_query()  （正規表現、句読点ベース、LLM 不要）
[節1] [節2] … [節N]      ← N 個の点質量（N は multi_source_max_segments で上限）
   ↓ encode_queries()  （RURI で 1 回 batch embed）
[v1] [v2] … [vN]         ← N 個のクエリベクトル
   ↓ 各 vi が _union_pool を引く（raw ∪ virtual）
[pool1] [pool2] … [poolN]  + [BM25 pool]（全文、1 回）
   ↓ _rrf_fusion （Cormack 2009、rank-only・scale 不変）
融合 seed pool             ← 場の superposition
   ↓ wave は 1 回だけ伝播
reached
```

複数の節の場が交差する点（複数の per-segment pool に現れる doc）は RRF 和が高くなる — これが「重力レンズの交点」を**無償で**与える。「GaOTTT にも website にも関係する記憶」というまさに欲しい sweet spot が拾える。

**物理（`compute_acceleration`）と scoring の anchor は pooled な `query_vec`（centroid）のまま。** Multi-source が変えるのは *seeding*（どのノードが wave に入るか）だけで、physics rule は一切変えない。Phase M「source 分岐ゼロの単一規則」不変、rollback は単一フラグ。

### 三層語彙

- **物理**: 質量の平均ではなく **場の重ね合わせ**。複合プロンプトは複合的な重力源。
- **TTT 機構**: seed pool が *multi-anchor gradient seed* になる。勾配シグナルの種が複数アンカーから供給される。
- **生物**: プロンプトが 1 つのブレンドされた概念ではなく、**複数の意味アセンブリ**を同時に発火させることに対応する。

## 設計判断の記録

| # | 判断 | 理由 / 却下した代替案 |
|---|---|---|
| **D1** | superposition は **seed pool 段**で行う（per-segment `_union_pool` を RRF 融合）。力場段（`compute_acceleration`）では行わない | 力場 superposition は query-attraction 項を N 重に適用 → displacement runaway リスク（Tier 4 が監視）、かつ physics 関数に分岐が入る。N 本の独立 wave は wave コストが N 倍で ambient の ~0.5s 予算を超える。seed pool 段なら安価（N×FAISS search のみ）・物理忠実・opt-in 安全（rollback = 単一フラグ） |
| **D2** | 分割は **正規表現（句読点ベース）**。Sudachi は segmenter に使わない | Sudachi は形態素 tokenizer であって文分割器ではない。かつ `bm25-sudachi` は **optional extra** — 分割が optional パッケージに hard-depend するとデフォルトインストールが壊れる。正規表現分割は決定論的・ゼロ依存・<1ms |
| **D3** | config-gate のみ。`RecallRequest` に新フィールドを足さない | `hybrid_bm25_enabled` 等と同じ。MCP ツールシグネチャ凍結、parity surface 最小化。per-call override は将来の Stage 3 で検討（§Open questions） |
| **D4** | `multi_source_enabled`（recall 用）と `multi_source_ambient_enabled`（ambient 用）の **2 フラグ**（両方 default ON、2026-05-21 実 RURI perf 検証後）| ambient は毎ターン発火するのでフラグを分離（perf 隔離）。実 RURI 計測で複合クエリ recall は ~2× / p95 ~40ms と判明、Tier 6 ゲート（120ms）に余裕があり両方 ON で確定。`False` 側に倒せば各経路を個別ロールバック |
| **D5** | BM25 は全文で 1 回。分割しない | BM25 は query term ごとに加算的に compose するので、そもそも centroid drag が起きない（dense pooling 固有の問題）。dense（raw+virtual）だけを分割すれば十分。RRF-of-RRF を避けられる |
| **D6** | centroid（pooled `query_vec`）は scoring と TTT anchor に引き続き使う | physics rule を一切変えない。Phase M 不変。multi-source は seeding のみ。rollback が単一 vector seeding への clean revert になる。**この feature が非 phase 扱いである根拠** — 重力モデルの規則は不変 |

## Stage 構成

- **Stage 1（本ドキュメント、完了）** — `core/segmentation.py`、`config` フラグ、`_multi_source_pool` + `propagate_gravity_wave` の `segment_vectors` 引数、`engine.query`/`_query_internal` の統合、`training_delta.intent_centers` 観測値。`recall` / `explore` が config-gate で multi-source seeding。
- **Stage 2（完了）** — `ambient_recall` も multi-source seeding（`multi_source_ambient_enabled`、実装は Stage 1 で同梱、2026-05-21 の実 RURI perf 検証後 default ON）。重力レンズ枠の交点強化は `_pick_lensing` が `virtual−raw` gap を見るため自動（複数節が共同で曲げた doc を自然に優先 — コード変更不要）。
- **Stage 3（将来）** — observability 深化（どの節がどのノードを引いたかの per-segment attribution）、`RecallRequest` per-call override、節ごとの重み付き融合。

## パフォーマンス戦略（ambient パスの ~0.5s 予算）

1. **wave は 1 回**（D1）。高コストな `propagate_gravity_wave` の neighbor 展開と `_update_simulation` は legacy と同じく 1 回。multi-source が増やすのは seed FAISS search のみ（FlatIP index 上で数 ms）。
2. **embed は 1 回の batch**。`encode_queries` が N 節を 1 回の RURI forward pass で埋め込む。N 回別々に `encode` するのが回帰になる。
3. **N を 4 上限**（`multi_source_max_segments`）。FAISS search は `N × O(corpus)`、上限つきで予測可能。
4. **ambient フラグは別**（perf 隔離のため独立フラグ）。2026-05-21 の実 RURI 計測（複合クエリ recall ~2× / p95 ~40ms、予算内）を経て両フラグ default ON に確定。
5. **prefetch cache は不変**。cache key は `(text, k, wave_depth, wave_k)`、segmentation は `text` の純関数なので cache 整合は保たれる。

検証ゲート（実施済 2026-05-21）: 実 RURI で複合クエリ recall を計測 — single-source p50 15.3ms / p95 16.7ms、multi-source p50 31.8ms / p95 39.6ms。~2× だが Tier 6 ゲート（`p95 < 120ms`）・ambient フック予算（~500ms）に余裕があり、両フラグ default ON で確定。

## ロールバック

`multi_source_enabled=False`（および `multi_source_ambient_enabled=False`）で seed 段は単一 vector の legacy 経路に bit-for-bit 復帰。`segment_vectors=None` が `propagate_gravity_wave` に渡り、`_union_pool(qv, …)` がそのまま走る。

## Open questions

1. **per-call override** — `RecallRequest.multi_source: bool | None` を将来足すか（既知の複合プロンプトやデバッグ用）。Stage 1 では parity surface 最小化のため見送り、Stage 3 候補。
2. **節の重み付け** — 長い／先頭の節を重く扱うか。RRF は意図的に rank-only（scale 不変）なので重みを表現できない。Stage 1 は全節等価、weighted fusion は Stage 2 の候補（チューニングノブが増える）。
3. **per-segment attribution** — どの節がどのノードを引いたかを `training_delta` に出すと観測価値が高いが payload が膨らむ。Stage 3 へ。Stage 1 はスカラー `intent_centers` のみ。

## Reflections

クエリは 1 つの意図ではなく、小さな星座である。pooling はその星座を重心の 1 点に潰していた。Multi-Source Query は「物理に忠実に直したら retrieval が良くなった」場所 — GaOTTT が「物理として書いたら最適化器として読めた」プロジェクトなら、これはその逆向きの一手である。
