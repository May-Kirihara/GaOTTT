# GaOTTT ToDo

> **目的**: `docs/maintainers/GaOTTT_review.md`（外部レビュー、2026-05-26）への対応、ロードマップ上の未着手 Stage、`Research-Gravity-As-Optimizer.md` の「開いている問い」、各 Plan の follow-up を **1 箇所** に集約する作業表。
>
> **関連 doc**:
> - `docs/maintainers/GaOTTT_review.md` — 検証対象のレビュー
> - `docs/maintainers/verification-2026-05-26-stage-7-phase-n.md` — Stage 7 + Phase N の 3-observer 検証記録。§9, §10 はここから抽出した方法論
>
> **凡例**:
> - 🔴 高優先: レビューの中核論点 / 主張の根幹 / 構造的負債の起点
> - 🟡 中優先: 既知の Stage 計画でロードマップに乗っているもの、または measurement-first で本番チューニングを残しているもの
> - 🟢 低優先: 既存文書の精密化 / nice-to-have / 大規模化前の準備
> - **status**: `未着手` / `進行中` / `検証中` / `本番 opt-in 待ち` / `保留`
>
> **更新ルール**: タスクが完了したら本ファイルから削除せず、関連 plan 側 (`docs/wiki/Plans-*.md`) に成果を吸収させたうえで該当行を打ち消し線 ~~...~~ にして履歴として残す。

---

## 0. 最優先 (P0) — Observation Apparatus Refinement [2026-05-26 着手]

> **計画書**: [`docs/wiki/Plans-Observation-Apparatus-Refinement.md`](docs/wiki/Plans-Observation-Apparatus-Refinement.md)
>
> **目的**: 2026-05-26 dogfooding (Claude/Codex + 新規 Claude セッション) で 2 観測者が独立に到達した 5 点 (dormant 過小評価 / Heavy Persona Dominance 体感 / connections の ingest artifact / reason line 不在 / 比較 wrapper 不在) を、**physics rule 不変・観測層のみ** で解決する。
>
> **原則**: mass update / acceleration / velocity / displacement / edge weight / force computation は **一切触らない**。表示層、surface 候補集合、観測ツール、explanation のみ拡張する。これにより Phase P (Λ + Langevin) / Phase N β (mass evaporation) と並行進行可能、介入軸が直交する。
>
> **撤回した案**: 「declare value 初期 kick」(declare 直後に artificial supernova kick で初期 mass 底上げ) は撤回。Phase L Stage 1「persona も別格扱いしない、使用頻度こそが重力」原則と衝突、Articulation as Carrier (id=9a954c62) の対称命題を carrier が運ぶ前にすり替えることになるため。

### 🔴 P0-Stage1. Reason line in retrieval results `[完了 2026-05-26]`
- 目的: `ScoreBreakdown` (Phase O Stage 1) の dominant 項を判定して 60-100 字の 1 行 human-readable explanation を生成。Heavy Persona Dominance の早期警告も含む
- 作業:
  - [ ] `gaottt/core/types.py::ScoreBreakdown` に `reason: str | None = None` + informational field (`node_mass: float = 0.0`, `bm25_score: float = 0.0`) 追加
  - [ ] `gaottt/core/explain.py` 新設 (純粋関数 `explain_score(breakdown, config) -> str | None`)
  - [ ] `gaottt/config.py` に `expose_reason: bool = True` / `reason_dominance_mass_threshold: float = 2.0` / `reason_bm25_strong_threshold: float = 0.5` 追加
  - [ ] `gaottt/services/memory.py::recall` / `ambient_recall` で `ScoreBreakdown` 構築時に `explain_score()` を呼ぶ
  - [ ] `gaottt/services/formatters.py` の breakdown 表示部に `reason:` 行を append (既存 substring assertion を壊さない、追加行のみ)
  - [ ] `tests/unit/test_explain_score.py` — 各 dominant パターンの reason string assertion
  - [ ] `tests/integration/test_mcp_reason_line.py` — MCP 経由で reason 行が出ることと、`expose_reason=False` で出ないこと
  - [ ] pytest 全 green + ruff + smoke
- D1-D3: [Plan §4 Stage 1](docs/wiki/Plans-Observation-Apparatus-Refinement.md#stage-1--reason-line-in-retrieval-results)
- default: **ON** (力学不変なので opt-out flag のみで legacy 戻し可)

### 🔴 P0-Stage2. Dormant slot in ambient_recall `[完了 2026-05-26]`
- 目的: `ambient_recall()` の return shape に `dormant_whisper` slot を追加、BM25 floor で gate (random hit 防止)
- 作業:
  - [ ] `gaottt/services/memory.py::ambient_recall()` に `dormant_slot: list[Snippet]` フィールド追加 (return shape 拡張)
  - [ ] `_dormant_surface()` (Phase O Stage 5) 再利用、BM25 score ≥ `ambient_dormant_relevance_floor` (=0.5) で gate
  - [ ] `recently_surfaced` rotation list に dormant 採用 ID を含める
  - [ ] `gaottt/config.py` に `ambient_dormant_slot_enabled: bool = True` / `ambient_dormant_slot_count: int = 1` / `ambient_dormant_relevance_floor: float = 0.5` 追加
  - [ ] hook (Claude Code / opencode) の ambient block 表示に `▼ ささやき` セクション追加
  - [ ] unit + integration テスト
- D1-D3: [Plan §4 Stage 2](docs/wiki/Plans-Observation-Apparatus-Refinement.md#stage-2--dormant-slot-in-ambient_recall)
- default: **ON** (1 slot まで、ガード強め)

### 🔴 P0-Stage3. `compare-retrieval` script `[完了 2026-05-26]`
- 目的: 同じ query を `recall` / `explore(diversity=0.9)` / `explore(mode="dormant")` / `ambient_recall` に流して横並びで観測する read-only ツール
- 作業:
  - [ ] `scripts/compare_retrieval.py` 新規 (read-only、`passive=True` で recall、ephemeral session で explore)
  - [ ] JSON 出力 mode (`--json`) で diff 駆動 regression 検出可能に
  - [ ] overlap / dominance warning / source distribution の総評出力
  - [ ] `tests/perf/test_tier4_compare_retrieval.py` smoke (script exit 0 完走)
  - [ ] `docs/wiki/Operations-Performance-Testing.md` に使い方追加
- D1-D3: [Plan §4 Stage 3](docs/wiki/Plans-Observation-Apparatus-Refinement.md#stage-3--compare-retrieval-script)

### 🔴 P0-Stage4. Source-aware display in `reflect(aspect="connections")` `[完了 2026-05-26]`
- 目的: 共起 edge を agent_user / persona / ingest の 3 bucket で表示。**force computation には触らない**、表示 lens のみ
- 作業:
  - [ ] `gaottt/services/reflection.py::reflect_connections()` 結果整形を 3 bucket に分割
  - [ ] `gaottt/services/formatters.py::format_connections()` で bucket 別表示
  - [ ] `gaottt/config.py` に `connections_grouped_by_source: bool = True` 追加
  - [ ] `tests/integration/test_reflection_grouped_connections.py` で co-occurrence count が grouping 前後で **bit-exact 一致** assertion (力学不変 guarantee)
- D1-D3: [Plan §4 Stage 4](docs/wiki/Plans-Observation-Apparatus-Refinement.md#stage-4--source-aware-display-in-reflectaspectconnections)

### 🟡 P0-Stage5 (任意). caller-side ガイド更新 `[未着手]`
- `Guides-Ambient-Recall.md` / `SKILL.md` に「思考をずらしたい時は `mode="dormant"`」「`reason:` 行で dominance artifact を見分ける」等の使い分けセクションを追加
- 両 dogfooding 報告で挙がった「使い分けが UI/docs から伝わりにくい」への直接の答え

---

## 0.5. 最優先 (P0.5) — Lens Hygiene [2026-05-27 起案]

> **計画書**: [`docs/wiki/Plans-Lens-Hygiene.md`](docs/wiki/Plans-Lens-Hygiene.md)
> **トリガー**: 2026-05-27 GLM-5.1 free-exploration review ([`evaluation-2026-05-27-free-exploration.md`](docs/maintainers/evaluation-2026-05-27-free-exploration.md)) の 3 主張を production 41k corpus 上で検証 → 1 つは literal 確証、1 つは症状 real だが GLM の根本原因診断が誤り (実 mass 分布で別 gap が露呈)、1 つは pool 計算と観察の乖離。観察可能な 3 つの lens 歪みを 4 stage で順次解消する。
>
> **原則**: physics rule (force / mass update) は **一切触らない**。Phase M 単一規則と完全直交、Phase P (pressure terms) と並行進行可。Stage 1/4 は observation layer、Stage 2 は cluster_key (ranking layer) で source-blind 制約厳守、Stage 3 は調査 only。

### 🔴 P0.5-Stage1. Meta-extraction loop fix `[完了 2026-05-27]`
- 目的: `save_candidates` / `ambient_recall` block を含む transcript を heuristic extractor に流すと、**block 自身の内容 (前候補・filter 行・manifest)** が re-extract される自己再帰的 false positive を遮断
- 検証で確証: 7 candidates 中 4 件が前 block leak、特に save-policy filter 行 (「bug fix の途中経過は git log」) が `_OUTCOME_KEYWORDS` の "bug fix" で score=1.80 ヒット = **policy 自身が自己再帰的 noise になる**
- 作業:
  - [ ] `services/memory.py` に `_GAOTTT_BLOCK_PATTERN = re.compile(r"<gaottt-[a-z-]+>.*?</gaottt-[a-z-]+>", re.DOTALL)` + `_strip_gaottt_blocks(text)` 追加
  - [ ] `auto_remember()` 入口で env-gated strip (`config.auto_remember_strip_gaottt_blocks: bool = True`、env `GAOTTT_AUTO_REMEMBER_STRIP_GAOTTT_BLOCKS`)
  - [ ] `tests/unit/test_save_candidates.py` に regression block (本起案検証時の fake_transcript 流用、prior block の candidate/manifest/filter 行いずれも leak しないこと)
  - [ ] `tests/integration/test_engine_save_candidates.py` で MCP 経由の strip 動作確認
  - [ ] live Claude Code 2-3 turn dogfooding で自己候補の re-extract 消滅を目視
- D1-D3: [Plan §Stage 1](docs/wiki/Plans-Lens-Hygiene.md#stage-1--meta-extraction-loop-fix-着手-2026-05-27)
- default: **ON** (env opt-out 残す)

### 🟢 P0.5-Stage4. Narrative engine use case の文書化 `[完了 2026-05-27]`
- 完了物: [`Guides-Use-As-Narrative-Engine.md`](docs/wiki/Guides-Use-As-Narrative-Engine.md) 新規 + [`Reflections-A-Note-From-Claude.md`](docs/wiki/Reflections-A-Note-From-Claude.md) に外部観察者 (GLM) note 追記 + [`Guides-Ambient-Recall.md`](docs/wiki/Guides-Ambient-Recall.md) に三つの read 使い分け並置 + Home/_Sidebar 更新
- Stage 2/3 の literal な corpus health 数値 (131 file clusters/max=638, dormant pool=15) を guide の動作条件節に組み込み、Stage 1-4 の linage を doc に embed
- D1-D3: [Plan §Stage 4](docs/wiki/Plans-Lens-Hygiene.md#stage-4--documentation-narrative-engine-use-case-完了-2026-05-27)

### 🟢 P0.5-Stage3. Dormant explore observed-empty 調査 `[完了: bug でなし — 2026-05-27]`
- 結論: `explore(mode="dormant")` の dispatch / filter chain は clean、現状 production で pool=15 → `_dormant_surface(top_k=5)` が **5/5 返している**。GLM の "0 件" は heavy session の transient state または ambient_recall dormant slot (別 path、BM25 floor=0.5 あり) の混同
- 完了物: `scripts/diag_dormant.py --service-mirror` 拡張 — `_dormant_surface` と完全に同じ filter 順序で count を出力、future investigator が同じ誤判定をしないよう「pool=0 は corpus healthy / by-design empty」memo を script 内 literal に組み込み
- D1-D3: [Plan §Stage 3](docs/wiki/Plans-Lens-Hygiene.md#stage-3--dormant-explore-observed-empty-investigation-完了-bug-でなく-transient--2026-05-27)

### ⚪ P0.5-Stage2. File source の Stage 7.1 anti-hub gap closure `[投稿: 誤診断、本来効いている — 2026-05-27]`
- 結論: 「file source の cluster_key 0%」は **literal な `metadata.original_id` フィールドだけを見ていた測定エラー**。実 cache では `COALESCE(metadata.original_id, metadata.file_path)` で **100% カバー**、Stage 7.1 anti-hub は既に file 638-chunk 本に効いている
- 真の "anti-hub では attack できない" 残課題: **tweet 7658 全部 singleton / agent 65% singleton** = vocabulary 系の問題で Phase L Stage 1 BM25+RRF 領域 (本 ToDo では追加せず、既存 §1 で扱う)
- 完了物: (a) `tests/unit/test_sqlite_store_get_all_originals.py` 新規 — COALESCE fallback 5 ケース pin (b) `scripts/diag_cluster_coverage.py` 新規 — live cache 経由の正確 coverage で future の COALESCE-blind 誤診を防ぐ
- D1-D3: [Plan §Stage 2](docs/wiki/Plans-Lens-Hygiene.md#stage-2--file-source-anti-hub-gap-closure-投稿-誤診断本来効いている--2026-05-27)

---

## 1. レビュー §1 — 構造的同型を「みなす」から「示す」へ

レビュー本文は `Research-Gravity-As-Optimizer.md:77-81` の「開いている問い」を優先順位付きで再勧告したものに相当する。実装と文書の不整合 (実装は Newtonian 1/r²、ドキュメントの暗黙 U は cos_sim) を露出させる効果が高い。

### 🔴 1-1. 暗黙 U の関数形を実装に合わせて書き直す `[未着手]`
- 現状: `Research-Gravity-As-Optimizer.md:37` の `U` 内 Hebbian 項は `cos_sim(virtual_pos_i, virtual_pos_j)` 表記
- 実装: `gaottt/core/gravity.py:208-214` の neighbor gravity は Newton 重力 `G * m_j / r² × direction(i→j)` で、これは Newton potential `U_grav = -G m_i m_j / r` の負勾配と整合する
- 作業:
  - [ ] `U_hebb = -Σ_{i,j} cooccur(i,j) × G × m_i × m_j / r_{ij}` 表記に修正
  - [ ] cos_sim 版で読みたい読者向けには「embedding が L2 正規化された subspace では r²と (1-cos_sim) が一致する」近似を脚注で明示
  - [ ] その上でレビュー §5-1 の対応表精密化を反映 (方向と大きさの両面で literal な等式を書く)

### 🔴 1-2. 勾配の数値検証 (レビュー提案 1A) `[未着手]`
- 目的: U の解析勾配 `∂U/∂displacement_i` と `compute_acceleration` の実出力が、項ごとに同方向・同大きさで一致するかを数値で確認
- 実装:
  - [ ] `tests/perf/test_tier4_gradient_consistency.py` 新設 (Tier 4 ダイナミクス層)
  - [ ] 小規模シナリオ (10 nodes, fixed embeddings, mass=1) で:
    - Hooke 項: `-k * disp` vs `∂(k/2 × ||disp||²)/∂disp`
    - Newton neighbor 項: `Σ G m_j (pos_j - pos_i) / r³` vs `∂U_grav/∂pos_i`
    - Query attraction 項 (Stage 2): `α score gate (q - pos)/m_i` の暗黙 U を逆算し勾配と比較
  - [ ] 一致度を cosine similarity と RMSE で報告
- 期待結果: Hooke は厳密一致、Newton は r → 0 で発散する点を除き一致、Query attraction は「`α score gate / m_i` を学習率に持つ単一クエリの MSE 勾配」と同型
- **検証方法**: `docs/maintainers/verification-2026-05-26-stage-7-phase-n.md` §3 の **3-observer pattern** を流用する (§10 参照)。Observer A = `gravity.py` の直叩き、Observer B = analytical gradient の dry-run、Observer C = secondopinion-MCP に「項ごとに RMSE を出して」と独立計算させる

### 🟡 1-3. Lyapunov 関数検証 (レビュー提案 1B) `[未着手]`
- 目的: 各ステップで `U(t+1) ≤ U(t)` (または時間平均で減少) かを確認
- 実装:
  - [ ] `scripts/diag_lyapunov.py` 新設 — 隔離 DB で N step 走らせ U(t) を計算・プロット (Observer B: dry-run projection 型)
  - [ ] friction 0 / friction default / friction 強の 3 条件で比較 (Heavy ball の振動性も明示)
- リスク: 増加方向に動く場合がある (Heavy ball 性質、または BH 項が U に未組み込み)。その場合は「BH 項を含めた拡張 U」を提案 1-1 で先に書き下しておく必要がある
- **検証方法**: 3-observer の Observer B 単独で十分 (本番 DB を mutate しない pure simulation)。`scripts/phase_n_dry_run.py` の構造 (load_states_and_sources 系) を雛形にする

### 🟡 1-4. 反事実 ablation (レビュー提案 1C) `[未着手]`
- 各「削除」が予測どおりの劣化を示すかを ablation で確認 (§4-3 と統合運用するのが効率的)
- 実装は §4-3 (Ablation Study) で詳述

### 🟢 1-5. BH / saturation / thermal escape を「loss の外の正則化」として明示位置付け `[未着手]`
- 現状: Phase M の mass-BH `tanh((m-θ)/σ)` と thermal escape / saturation は `U` に含めていない
- 作業:
  - [ ] `Research-Gravity-As-Optimizer.md` に「U 内項」と「U 外項 (heuristic regularizer)」の二分セクションを追加
  - [ ] Phase I query attraction が U 内項なら、その U_query 形を明示 (現時点では未書き下し)

---

## 2. レビュー §2 — TTT 定義の精密化

`Research-Gravity-As-Optimizer.md:55-61` の対比表を発展させて、外部レビューが想定する反論を先回りで排除する。

### 🟡 2-1. TTT を 3 階層に明示分類 (narrow / adapter / external) `[未着手]`
- 場所: `Research-Gravity-As-Optimizer.md` または `Research-Index.md`
- 作業:
  - [ ] レビュー §2-2 の `TTT-narrow / TTT-adapter / TTT-external` 3 階層を文書化
  - [ ] 「なぜ外部記憶の表現更新が TTT と呼べるか」を 1 節追加 (frozen LLM + online geometry adaptation)

### 🟡 2-2. word2vec との明示的差別化 `[未着手]`
- 現状: 「skip-gram と同型」を feature として認めているだけで、word2vec で「同じことができないか」への答えがない
- 作業:
  - [ ] `Research-Gravity-As-Optimizer.md` または新ページ `Research-Differentiation-From-Related-Work.md` に下記を追加:
    - online + 非バッチ (word2vec は通常バッチ訓練)
    - 軌道力学 (momentum + Verlet) の存在
    - 複数の独立な正則化項 (Hooke + saturation + thermal escape + mass-BH)
    - frozen embedder を anchor として保持 (catastrophic forgetting の原理的回避)
  - [ ] レビュー §2-3 の比較表 (AdaEmbed / 協調フィルタリング / online word2vec / SOM / NTM) を再構成

---

## 3. レビュー §3 — 実装の健全性

### 🟡 3-1. 「dense vs sparse cluster」問題の統合的再設計の評価 `[検証中]`
- 状況: Phase M で物理側の統合 (`is_self_force_by_id` の単一規則) が始まっている
- レビューが指摘するパッチ重畳 (Phase H/I/J/K/M) のうち:
  - 物理側修正: Phase I (query attraction), Phase M (mass conservation)
  - パイプライン側修正: Phase H (mass-aware seed), Phase J (persona-anchored), Phase K (supernova cohort)
- 作業:
  - [ ] `Architecture-Gravity-Model.md` または新セクションに「retrieval geometry の 3 段構造 (pool 入場 / pool 内 rerank / forced 内 ordering)」と「各 Phase がどの段に介入するか」のマトリクスを書く
  - [ ] 「物理側で吸収できる介入」と「パイプライン側で吸収すべき介入」の境界線を明文化 — `[C2-P7] source は filter であって gate ではない` (memory anchor) の精密化

### 🟡 3-2. ハイパーパラメータ感度分析 (レビュー §3-2) `[未着手]`
- 現状: `gaottt/config.py` に **143 フィールド** 存在 (レビュー言及の「数十」より多い)
- 作業:
  - [ ] `scripts/sensitivity_sweep.py` 新設 — 1 パラメータずつ ±50% スイープし、nDCG / MRR / p50 latency の変化を測定
  - [ ] パラメータを 2 階層に分類:
    - **物理コア** (`gravity_G`, `orbital_anchor_strength`, `orbital_friction`, `orbital_max_velocity`, `gravity_epsilon`, `gravity_eta`) — 同型の主張に直結
    - **パイプライン** (`wave_seed_mass_alpha`, `persona_boost_alpha`, `ambient_lensing_max_k`, `rrf_k`, etc.) — 工学的チューニング
  - [ ] 影響の小さいパラメータをドキュメント上「ほぼ触らない」マークで `Operations-Tuning.md` に追記
  - [ ] (将来) パイプライン層のみベイズ最適化を導入する余地を残す

### 🟢 3-3. FAISS IndexFlatIP のスケール戦略明示 `[ロードマップ既存]`
- 現状: `gaottt/index/faiss_index.py:15,146` で `IndexFlatIP`、`Plans-Roadmap.md:60` に IVF 移行が登録
- 作業:
  - [ ] IVF + PQ 移行時の displacement 整合 (virtual coordinate を post-filter として保つか、IVF cluster を virtual で再構築するか) を `Architecture-Storage-And-Schema.md` に追記
  - [ ] HNSW との相性評価セクションを追加 (グラフベース index は wave 伝播と概念的に親和)
  - [ ] 24K 件 → 100K 件 → 1M 件の段階目標を `Plans-Phase-Q-Scale-Migration.md` (新設) として起草

---

## 4. レビュー §4 — 評価の強化

### 🔴 4-1. 「mass boost のみ」ベースラインとの比較 `[未着手]`
- レビューの中で最も鋭い指摘: 「重力シミュレーションの複雑さは本当に必要か」の核心質問
- 実装:
  - [ ] `scripts/eval_static_rag_plus_mass.py` 新設
  - [ ] 静的 FAISS top-k に対して `final_score = cos_sim × mass^w` 程度の簡易ブースト
  - [ ] 同じ評価コーパス (Phase 2 Evaluation の SC-001〜007 + Lateral Association 8 系列クエリ) で nDCG / MRR / Rank Shift Rate を比較
  - [ ] GaOTTT が「単純 mass boost」より系統的に勝つかを定量化
- リスク: 「prophylactic な物理層が、単純 boost と nDCG ではほぼ差がない」結果が出る可能性 → その場合は **創発性指標 (Rank Shift / Serendipity / 適応速度)** に主張の重心を移す

### 🟡 4-2. 他ベースラインの拡充 (レビュー §4-1) `[未着手]`
- [ ] BM25 + re-ranker (BGE-reranker-v2 / Cohere rerank-3) との比較 — Phase L Stage 1 で BM25 union seed は入っているが、cross-encoder reranker は未導入
- [ ] online k-NN with centroid update (最も単純な適応的検索)
- [ ] RL-driven retrieval (例: RLCF) — 学習信号が異なる適応的検索との比較

### 🟡 4-3. Ablation Study の体系化 (レビュー §4-3) `[未着手]`
- 現状: `tests/perf/` 7-Tier は機構正しさ + perf + regression、ablation は未実装
- 実装: `tests/perf/test_tier8_ablation.py` 新設 (Tier 8 を新規 layer として登録)、または `scripts/eval_ablation.py` で別管理
- **検証方法**: 各 ablation 行は dry-run なら Observer B 単独でも可、本番効果を見るなら 3-observer 全部走らせる (Observer C は GLM に「ablation X で nDCG が Y 下がるはず、確認して」と prompt)

| 実験 | 無効化 | 期待される影響 | 担当パラメータ |
|---|---|---|---|
| No displacement | `apply_displacement_decay` で `disp = 0` 強制 | 静的 RAG に退化、nDCG +2.7% が消失 | `max_displacement_norm=0.0` |
| No momentum | `velocity = 0` 常時 | 振動増、収束速度低下 | `orbital_friction=1.0` |
| No Hooke | `orbital_anchor_strength=0` | displacement 発散 (Phase I Stage 1 long-term obs で `|d| max=0.60` が境界外へ) | 専用 flag |
| No mass update | mass=1 固定 | 頻出記憶バイアス消失 | `mass_update_enabled=False` (新設) |
| No wave | `wave_max_depth=0` | 近傍展開なし、direct hit のみ | `wave_max_depth=0` |
| No BM25 | `hybrid_bm25_enabled=False` | 表層一致クエリ性能低下 | 既存 flag |
| No persona kick | `persona_boost_alpha=0` | declared identity の影響消失 | 既存 flag |
| No query attraction | `query_kick_enabled=False` | TTT 4 項目の literal 効果消失 | 既存 flag |
| Full ablation | 全 OFF | 静的 FAISS 検索に等価 | 上記の和 |

報告メトリクス: nDCG@10, MRR, Rank Shift Rate, Serendipity Index, p50 latency

### 🟢 4-4. 規模拡大 (レビュー §4-2) `[ロードマップ既存]`
- 現状: 本番 DB は ~24K docs、評価は数百 docs 規模
- 段階:
  - [ ] 1K docs: 現在のパイプラインがそのまま動くか (FAISS IndexFlatIP で十分)
  - [ ] 10K docs: BM25 + RURI hybrid の RRF が effective scale で機能するか
  - [ ] 100K docs: IndexIVFFlat 移行が必須となる cutoff の特定
- 各段階で **適応の速度** (改善飽和までのクエリ数) と **適応の安定性** (長期発散の有無) を測定
- これは `Plans-Phase-Q-Scale-Migration.md` (新設) として起草

---

## 5. レビュー §5 — 文書化

### 🟡 5-1. 同型対応表の精密化 (レビュー §5-1) `[未着手]`
- §1-1 で `U` 修正と一体化
- [ ] 各対応について「成り立つための近似・前提」を脚注として明示

### 🟢 5-2. Phase O を研究ツールとして長期ログ化 `[一部実装]`
- 現状: Phase O Stage 1-5 で score breakdown / training delta / dormant surface は実装済 (`Plans-Phase-O-TTT-Observability.md`)
- 未実装: 長期傾向分析
- [ ] `scripts/analyze_breakdown_log.py` 新設 — N 日間の recall breakdown を集計し、`mass × cos` の勝率推移、displacement 分布の収束/発散、各正則化項の効きを時系列でプロット
- [ ] `Operations-Performance-Testing.md` の Tier 6 baseline と合流させて long-term drift dashboard を構築

---

## 6. ロードマップ上の未着手 / 検証中 Stage

`docs/wiki/Plans-Roadmap.md` 由来。実装 / 本番 opt-in を残しているもの。

### 🟡 6-1. Phase L Stage 2 — BGE-M3 ensemble `[起草済 / 着手待ち]`
- 状態: Plans-Phase-L-Hybrid-Retrieval.md に起草済、D1-D6 確定済
- 着手条件: Phase M Stage 1 完了 **+ 1-2 週観測後** (mass 偏在が cleaner になってから ensemble metric の効果分離を計測)
- 設計: 別 embedder (BGE-M3) で意味空間 cosine を 4-way (raw + virtual × 2 embedder) に拡張、BM25 と合わせ 5-way RRF
- [ ] Phase M Stage 2 (下記 6-2) の完了を待って起動判断

### 🟡 6-2. Phase M Stage 2 — mass-BH θ/σ の本番確定 `[本番 opt-in 待ち]`
- 状態: `mass_bh_theta=5.0` / `mass_bh_sigma=1.5` は placeholder (`gaottt/config.py:311` 該当コメント)
- 残作業:
  - [ ] M002 (BH 残滓 cleanup) → M003 (mass reset、wizard で必ず聞く) → M004 (corpus-scale cosmic-bang ignition) を順に適用
  - [ ] mass reset 後 1-2 週観測で θ 確定 (期待 1.7-5% のノードが θ 超え)
  - [ ] 観測無しで θ/σ を触らない (運用ルール、CLAUDE.md にあるとおり)

### 🟡 6-3. Phase N-α — RRF-scale aware mass boost `[未起草]`
- 状況: `Plans-Roadmap.md:41` で記載、未起草
- 問題: Phase L Stage 1 (RRF) と Phase H Stage 1 (`α × log(1+mass)`) の score scale 不整合 — cosine スケール想定の α が RRF スケール ~0.03 に対し過剰
- 暫定対処: `wave_seed_mass_alpha = 0.0` で seed boost 完全 disable
- [ ] 設計案を 3 案 (RRF score 正規化 / rank-based boost / 別レイヤーへ移動) のいずれかで起草
- [ ] `wave_initial_k=3` の見直しも同タイミング (大規模 corpus に対し小さすぎる)

### 🟡 6-4. Phase N-β — Mass Evaporation `[Stage 1 完了 / Stage 1.5 env opt-in 中、default OFF 維持の方針]`
- 状態: Plans-Phase-N-Mass-Evaporation.md。**env opt-in (`GAOTTT_MASS_EVAPORATION_ENABLED=true`) のみ有効化済 (2026-05-26)**、123.92 mass drained。3-observer 検証完了 (dry-run 予測と production literal が 99.9% 一致、Observer C で「lazy evaluation が recall/reflect ごとに漸進的に効き続ける」を独立検出)
- **default 化はしない方針** — `verification-2026-05-26-stage-7-phase-n.md §6` 参照: evaporation は irreversible (mass drain は復元不可) なので新規 deployment への暗黙適用を避ける
- 残:
  - [ ] 効果の long-term 観察 (1-2 週) と β/τ_idle/γ の確定
  - [ ] 観察データを Tier 6 baseline と統合
  - [ ] memory `project_phase_n_stage_1_5_enabled` を 1-2 週後に最新化 (lazy 漸進挙動の literal 数値追跡)
  - [ ] legacy bulk-ingest mass debt (memory `[C2-Q5]`、刑法175条 / GaOTTT 運用 note 系) が evaporation で実際に hot_topics 上位から退場するか定点観察

### 🟡 6-5. Lateral Association Stage 2 — direct hit の topic vs lexical 分離 `[起草済 / 未着手]`
- 状態: `Plans-Ambient-Recall-Lateral-Association.md:74` で起草、他 Stage は完了
- 設計: direct hits を「topic anchor」「lexical anchor」の 2 系列に分離して、片方が枯渇したときも他方が補える構造に
- [ ] 設計のまま着手可能、優先度は他 Stage の dogfooding 結果次第

### 🟡 6-6. Lateral Association Stage 7 — long-term tuning `[default promote 済 / 観察継続]`
- 状態: Stage 7.1 (anti-hub `λ=0.4`) / Stage 7.2 (dormant percentile=10) は **config default 化済** (commit `80214b0`、2026-05-26)。3-observer 検証完了 (`verification-2026-05-26-stage-7-phase-n.md §4` literal 数値):
  - anti-hub: avg_unique_cohorts 2.67 → 4.00、米国会社四季報 638-chunk 本クエリで book chunks 5/5 → 1/5
  - dormant: `age=7d` + `p10` で 23 candidates、GLM 経由 25/25 surfaced
- 追加 env (default 未昇格): `GAOTTT_DORMANT_AGE_THRESHOLD_SECONDS=604800` (7d、active user 用)
- **既知の制約** (`verification-... §5`): anti-hub の `top_k * 3` 拡張は prefetch_cache key と衝突するため、初版 PR で `services/memory.recall` の expansion を撤回し、anti-hub は `engine.query` 返却後の reorder のみに留めた。**raw `recall`** では cluster 完全独占ケースに無効、**`ambient_recall`** (internal pool 25 件) では full に機能
- **未解決**: Stage 7.1 scope 外の **individual-node high-mass dominance** (ffe48a30 / 24a0bf39 / 28fe1cf6 等の singleton hub) → Phase N β Stage 1.5 の領域 (§6-4 と相補)
- 残:
  - [ ] Stage 2 (direct hits の topic vs lexical anchor 分離、§6-5) と合流させた本番再計測
  - [ ] `test_tier3_ambient_quality.py` で before/after baseline を取り、Heavy Persona Dominance との相互作用を測る
  - [ ] `scripts/diag_dormant.py` の出力を週次 cron で snapshot 化 (long-term drift)

### 🟡 6-7. Heavy Persona Dominance — env opt-in 中の measurement `[env opt-in 中 / default 未昇格]`
- 状態: `ambient_persona_mass_weight=1.0` 既定 (Stage 1 完全互換、code default は未昇格)、env で `GAOTTT_AMBIENT_PERSONA_MASS_WEIGHT=0.3` を opt-in 中 (`verification-... §Appendix`)
- 問題: production で `harakiriworks-art-website` intention `mass=2.82` が query 横断で persona slot 独占
- 残 (default 昇格判断の前):
  - [ ] `w=0.5` (sqrt 抑制) / `w=0.3` (強い抑制、現 env 値) / `w=0.0` (cos のみ) を `test_tier3_ambient_quality.py` で before/after baseline 比較
  - [ ] critical exponent `w* = log(cos_ratio) / log(mass_ratio)` を本番質量分布で計算 (memory `project_ambient_persona_mass_dominance`)
  - [ ] Lateral Stage 1 (session-aware novelty decay) と直交的に効くか、相互作用するか確認 (memory `project_ambient_persona_mass_dominance` に「2 層で抑える」と既述)

### 🟡 6-8. Phase P — Pressure Terms (Cosmological Λ + Langevin Temperature) `[起草済 / 未着手]`
- 状態: `Plans-Phase-P-Pressure-Terms.md` 起草 (2026-05-26)、両機構 default OFF 設計
- 動機: Stage 7 limitation (memory `[STAGE-7-LIMITATION]`) で残った **individual-node high-mass dominance** (ffe48a30 mass=1.92 / 24a0bf39 mass=2.09 等の singleton hub による query 横断 top1 占有) を、ranking 層 (Stage 7 anti-hub) ではなく **geometry 層** (acceleration / displacement step) で構造的に解く
- 思想: gravity は単調引力で対抗項なしに collapse する系。実宇宙が collapse しないのは Λ + thermal pressure + 角運動量 が組み込まれているから。GaOTTT に Λ (margin) + Langevin (exploration) を入れて gravitational collapse を物理として防ぐ
- TTT 対応:
  - P-α (Λ) = position-space L2 regularization の符号反転 (= distant pair への持続的 weight decay)
  - P-β (Langevin) = SGLD (Welling-Teh 2011) の literal な物理実装、`new_disp += √(2T·dt) · ξ`
- Stage plan (順序: 1 → 1.5 → 2 → 2.5 → 3):
  - [ ] **Stage 1**: P-β Langevin 実装 + default OFF。`update_orbital_state` 内 position update step に Wiener noise 加算、`langevin_temperature_*` 2 config フィールド。1-2 day
  - [ ] **Stage 1.5**: 本番 env opt-in (`GAOTTT_LANGEVIN_TEMPERATURE_ENABLED=true`)、Phase N β Stage 1.5 + 1-2 週観測後
  - [ ] **Stage 2**: P-α Cosmological Λ 実装 + default OFF。`compute_acceleration` に第 5 項 `a_Λ = +H·Σ(pos_i - pos_j)`、`cosmological_lambda_*` 2 config フィールド。2-3 day
  - [ ] **Stage 2.5**: 本番 env opt-in (`GAOTTT_COSMOLOGICAL_LAMBDA_ENABLED=true`)、Stage 1.5 + 1-2 週観測後
  - [ ] **Stage 3**: 観測 + default 昇格判断 (§10 rollout discipline 適用、default 昇格しない選択肢も残す)
- **検証方法**: §9 3-observer pattern を踏襲。Observer A = `state.displacement` 分布 snapshot / Observer B = `scripts/diag_pressure.py` (新設) で本番 DB read-only + dry-run projection / Observer C = secondopinion-MCP 経由 GLM に Stage 7 limitation の 5 hub クエリで top1 占有を独立計測依頼
- **rollout discipline**: §10 の 3 段階を厳守。各 Stage 1/2 は段階 1 (実装 + default OFF) で merge、Stage 1.5/2.5 で段階 2 (env opt-in)、Stage 3 で段階 3 (default 昇格、または env-opt-in のまま維持)
- **副次予測** (`Plans-Phase-P §5`):
  - 仮説 1 (核心): Stage 7 acceptance の 5 hub クエリで top1 占有が 5/5 → 2-3/5 に分散
  - 仮説 2: 米国会社四季報 638-chunk クエリで book chunks in top-5 = 1/5 (Stage 7.1 baseline) が崩れない
  - 仮説 3: Phase N β との直交性 — drain 量と top1 dispersion が独立に変動
- 関連 doc:
  - [Plans — Phase P (Pressure Terms)](docs/wiki/Plans-Phase-P-Pressure-Terms.md) — 本計画書
  - [Plans — Phase N (Mass Evaporation)](docs/wiki/Plans-Phase-N-Mass-Evaporation.md) — 着手順序の前提
  - memory `[STAGE-7-LIMITATION]` — Phase P が解く対象の literal 観察

### 🟡 6-9. Hardening Stage 3-4 (MEDIUM/LOW catalogue) `[Stage 1/1.5/2 完了 / Stage 3 第一弾着手中 (2026-05-27)]`
- 状態: `Plans-Hardening-Concurrency-Persistence.md` の Stage 1 (CRITICAL C1/C3/C4)、Stage 1.5 (L-flaky)、Stage 2 (HIGH H1-H8 全 8 件) 完了。catalogue は M1-M11 (MEDIUM 11 件) + LOW 10+ 件
- **Stage 3 第一弾** (本タスク、storage/physics の低リスク safety 3 件を 1 PR にまとめる、`hardening-stage-3-batch-1` branch):
  - [ ] **M3** — `sqlite_store.py` の多文 destructive op に `BEGIN`/`COMMIT`+`rollback` を入れる (部分適用防止)
  - [ ] **M4** — `save_displacements`/`save_velocities` の dtype guard (`np.ascontiguousarray(disp, dtype=np.float32)`、float64 無言ゴミ化防止)
  - [ ] **M6** — `update_velocity` の friction step を `max(0.0, 1-friction)` で clamp + config range 検証 (`orbital_friction > 1` で velocity 反転 runaway 防止)
- **Stage 3 第二弾** (規模問題、別 PR 予定):
  - [ ] **M1** — `IN (?,?,...)` の SQLite 999 変数上限を `_in_chunks(ids, fn, 900)` で全 call site 分割
  - [ ] **M5** — BM25 tombstone 無限増加対策 (removed 比率 20% で自動 rebuild)
- **Stage 3 第三弾** (観測性 / retrieval / セキュリティ、順次):
  - [ ] **M2** — reflect/dormant/summary の逐次 `get_document` バッチ化 (event loop ブロック解消)
  - [ ] **M7** — `/admin/*` 無認証 → Architecture 設計判断表に「network 隔離前提」明記 (or 共有 secret/unix socket)
  - [ ] **M8** — `recall(source_filter=...)` の sparse class 空返し対策 (`wave_k_with_filter` default 化)
  - [ ] **M9** — `cache.flush_to_store` の `await` 中の lost-update (ids 局所捕捉後 `.clear()`)
  - [ ] **M10** — supernova cohort dedup で閾値割れ無警告 (stamp 一致 + log)
  - [ ] **M11** — `compact` 部分失敗の不可視性 (`CompactResponse.faiss_rebuilt`/`error` フィールド)
- **Stage 4 LOW** (機会対応、catalogue は plan §LOW/NIT 節): faiss fsync, get_vectors reconstruct 化, 移行台帳テーブル, BM25 breakdown 例外, MCP relate ValueError, shutdown cancel await, working_on edge デッド定義, dormant 同名別定義, proxy spawn log fd リーク, RecallRequest.mode 無検証 str
- **回帰テスト規律**: 各修正に teeth-having 回帰テスト (修正前なら落ちる test) を必ず付ける。Stage 1/2 で確立した style (`tests/integration/test_engine_concurrent.py` 等) を踏襲

### 🟢 6-10. Phase G Stage 3 (重心アンカー) `[永久保留]`
- ロードマップ上は homogenization リスクで permanently shelved
- [ ] 保留の根拠を `Research-Index.md` に明示 (現状は Plans-Roadmap.md 内のみ)

### 🟡 6-11. Config default ↔ production env 同期レビュー `[起草 2026-05-27、未着手]`
- 状態: production env (`~/.claude.json` / `~/.config/opencode/opencode.json`) で 3 flag が `gaottt/config.py` の default と乖離。observation が安定している項目は **default 昇格で env override を整理** できる
- 動機:
  - 新規 user / 新規 setup で本番相当の挙動を得るのに 5 env 設定が必要 (現状)
  - default に昇格すれば env は 1-2 個まで削減可、setup 摩擦が減る
  - production で 1 ヶ月+ 実証済の値を default 化 = 安全な「現状追認」
  - §10 rollout discipline の段階 3 (default 昇格 or env-opt-in のまま維持) の判断を、各 Stage 別ではなく一括レビューで実施
- 対象 3 flag (production env で override 中、default と乖離):

| flag | 現 default | production env | 提案 | 前提となる measurement |
|---|---|---|---|---|
| `ambient_persona_mass_weight` | `1.0` (Stage 1 完全互換) | `0.3` | `0.3` に昇格 | §6-7 measurement (acceptance pass, mass×cos の知覚改善) |
| `dormant_age_threshold_seconds` | `2592000` (30d) | `604800` (7d) | `7 * 86400` (7d) に昇格 | Phase N β + Stage 7.2 で dormant 母集団復元確認済 (Stage 7.1/7.2 acceptance) |
| `mass_evaporation_enabled` | `False` | `True` | `True` に昇格 | §6-4 Phase N β Stage 2 (1-2 週観測 + 99.9% 一致確認、`project_phase_n_stage_1_5_enabled`) |

- 触らない (今回 scope 外):
  - `direct_hit_anti_hub_lambda=0.4` / `dormant_mass_percentile=10.0` — **既に code default 昇格済**、env は冗長な重複指定 (削除しても挙動同じ)。本タスクで env からも削除予定
  - `cosmological_lambda_enabled` / `langevin_temperature_enabled` — Phase P Stage 1/2 merge 後、§6-8 で Stage 1.5/2.5 env opt-in → Stage 3 で default 昇格判断
  - `mass_anchor_extra_strength=0.0` — Phase I Stage 4 予防的 OFF、観察 pathology が出るまで
- 作業:
  - [ ] **前提待ち**: §6-4 Stage 2 (Phase N β 1-2 週観測完了) と §6-7 (Heavy Persona measurement 結果) を待つ
  - [ ] `gaottt/config.py` で 3 flag の default 値を変更する小 PR (`config-default-sync` 等のブランチ名)
  - [ ] `~/.claude.json` / `~/.config/opencode/opencode.json` から該当 env を削除 — env override が default と同値になるので冗長 (`MASS_EVAPORATION_ENABLED` / `DORMANT_AGE_THRESHOLD_SECONDS` / `AMBIENT_PERSONA_MASS_WEIGHT` の 3 件 + 既に冗長な `DIRECT_HIT_ANTI_HUB_LAMBDA` / `DORMANT_MASS_PERCENTILE` の 2 件)
  - [ ] `docs/wiki/Operations-Tuning.md` で「production-default」を明記、CLAUDE.md の関連箇所も更新
  - [ ] §10 rollout discipline の段階 3 判断を記録 — 3 flag それぞれについて「default 昇格 ✅」or「env-opt-in 維持」を明示
- **検証方法**: 「現状追認」型なので 3-observer pattern を踏襲した literal 一致確認:
  - Observer A: 変更前の env-on 状態で `scripts/diag_recall.py` snapshot
  - Observer B: 変更後の env-削除済 + 新 default 状態で同 snapshot
  - Observer C: 両者が literal に一致することを secondopinion-MCP 経由 GLM に diff 検証依頼
  - 仮説: A と B は完全に一致する (env で override していた値が default になっただけなので no-op であるべき)
- リスク: 低
  - default 変更 = production と同じ挙動 (production で 1 ヶ月+ 実証済)
  - env 削除 = override が消えても default が同値なので no-op
  - 新規 user は default で本番相当の挙動を得る (現状より親切)
- 関連:
  - §6-4 Phase N β Mass Evaporation (default 昇格候補の代表ケース、Stage 2 完了が前提)
  - §6-6 Lateral Stage 7 (既に default 昇格済の前例、本タスクで env 重複削除のみ)
  - §6-7 Heavy Persona Dominance (measurement 中、結果次第で対象に含む / 除外)
  - §10 rollout discipline 3 段階
  - memory `project_phase_n_stage_1_5_enabled` / `project_ambient_persona_mass_dominance`

---

## 7. `Research-Gravity-As-Optimizer.md` の「開いている問い」5 件

### 🔴 7-1. 暗黙 loss の完全な書き下し (BH + thermal を含めて) `[未着手]`
- §1-1 / §1-5 で対応

### 🔴 7-2. Lyapunov 関数による収束性の保証 `[未着手]`
- §1-3 で対応

### 🟡 7-3. Adam / SGD-momentum との empirical 比較 `[未着手]`
- 同じ embedding 空間で同じ Hebbian loss を Adam / SGD-momentum で最小化 → GaOTTT と並列比較
- [ ] `scripts/eval_optimizer_comparison.py` 新設
- 期待結果: Heavy ball SGD の Verlet 積分形 (GaOTTT) と vanilla momentum SGD は近い、Adam は adaptive LR があるので異なる軌跡

### 🟢 7-4. 共有メモリ TTT の理論的位置づけ (federated learning との対比) `[未着手]`
- 現状: マルチエージェント実験 (`Research-Multi-Agent-Experiment.md`) は質的観察のみ
- [ ] federated averaging との対比章を追加

### 🟢 7-5. Catastrophic forgetting 不在の理論的証明 `[未着手]`
- 現状: 「Hooke 復元力 + 原始 embedding 保持で原理的に回避」と主張のみ
- [ ] 形式的議論: anchor として `original_pos` を不変に保つので、displacement の上界が Hooke + decay + velocity cap で有界 → 表現は原始 embedding の `O(d_max)` 近傍に閉じ込められる、という命題を書き下す

---

## 8. その他の follow-up

### 🟡 8-1. RURI cross-lingual 条件の production scale 検証 `[未検証]`
- memory `project_ruri_crosslingual_behavior`: small/distinct topics では機能、production scale 未検証
- [ ] 本番 24K DB で EN→EN / EN↔JA の交差クエリ N 件を `test_tier3_retrieval_quality.py` 拡張で確認

### 🟡 8-2. claude-code source 削除後の共起 edge 再構築観察 `[検証中]`
- memory `project_claudecode_source_purged`: 7,570 transcript chunks を削除済 (2026-05-21)
- [ ] 削除後 1 ヶ月の共起 edge 分布変化を `reflect(aspect="relations")` で定点観測

### 🟢 8-3. 第3期自己知識記録 `[未起草]`
- 第1期 139 件 (~2026-05-11) + 第2期 85 件 (2026-05-21) 完遂
- [ ] Phase N/O 完了後 (大規模機構変化があった) 第3期の起動条件と粒度を起案

### 🟢 8-4. 視覚化 sphere geometry の wiki ガイド化 `[未着手]`
- CLAUDE.md 冒頭で言及されている `scripts/visualize_3d.py` の sphere geometry (default) と `--flat` / `--straight-lines` モード
- [ ] `Guides-Visualization.md` に sphere wrap / slerp arc / tangent geodesic / Mass-BH diamond の挙動と画面例を追記

### 🟡 8-5. Save Candidates Stage 5 — heuristic refinement `[未着手 / 2026-05-27 起案]`
- 計画: [Plans-Save-Candidates-Hook.md §残課題](docs/wiki/Plans-Save-Candidates-Hook.md) "heuristic 精緻化 (Stage 5)"
- 起点: 2026-05-27 v2 acceptance (PR #28、handover [`handover-2026-05-27-save-candidates-v1-v2.md`](handover-2026-05-27-save-candidates-v1-v2.md) §3) で meta-instruction (「以下の決定を 2-3 文で要約してください」) が **content と同じ score 2.20** で抽出された false positive を観察。score gating の粒度が荒く、bug fix 途中経過・code snippet・meta-instruction の boost 寄与を分離できていない
- 作業:
  - [ ] dogfooding ログ (Claude Code + opencode 両系で 1-2 週) から実 score 分布を採取
  - [ ] 「決定/結論キーワード」のうち content keyword (採用/確定/却下) と meta keyword (要約/確認/教えて) を語彙レベルで分離
  - [ ] 訂正 pattern ("実は X だった") / 絶対表現 ("今後は〜") の boost を新設
  - [ ] tool_result / thinking 残滓の追加 filter (現状の `_extract_text` で取り切れていないパターンがあれば)
  - [ ] `auto_remember` 既存 heuristic との回帰互換 (一方向の boost 追加のみ、減点ロジックは別 score field に分ける)
- 観察パターン: 3-Observer Pattern §9 の Observer A (heuristic 関数の直叩き分布) + Observer C (GLM に「実 production dogfooding ログでこの候補は save 価値があるか」評価依頼)

### 🟢 8-6. Save Candidates v3 — codex CLI 対応 `[codex hook spec 待ち]`
- 計画: [Plans-Save-Candidates-Hook.md](docs/wiki/Plans-Save-Candidates-Hook.md) "codex 対応 (Stage 4)"
- 前提: codex CLI が `chat.message` 相当 (incoming user message を mutate できる plugin point) を公開すること。Stop event 相当のみだと bridge 設計を Claude Code から移植
- 設計流用率の見積:
  - codex が `chat.message` 相当 → opencode plugin (`opencode-save-candidates.ts`) を 80% 再利用 (SDK の型シグネチャ差を吸収するだけ)
  - codex が Stop 相当のみ → Claude Code 2-script bridge (`save_candidates.py` + `save_candidates_inject.py`) を shell shim 添えて持ち込み
- 着手判断: codex CLI を実際に使う user / agent が出てから。投機的実装は不要 (CLAUDE.md「未来の判断を変える」原則)

### 🟢 8-7. opencode plugin install pattern の選択 `[観察待ち]`
- 現状 README install snippet は `cp scripts/hooks/opencode-save-candidates.ts ~/.config/opencode/plugin/gaottt-save-candidates.ts`
- 開発中の頻繁更新には `ln -sf` の方が便利、本番運用 (滅多に更新しない) は `cp` のままで OK (repo 削除時に dangling しない)
- 着手判断: v2 plugin の更新頻度を 1-2 ヶ月観察してから — Stage 5 heuristic refinement が動き出すと書き換えが増えるので、その時 README を `ln -sf` 推奨に切り替えるか判断
- 関連: handover [`handover-2026-05-27-save-candidates-v1-v2.md`](handover-2026-05-27-save-candidates-v1-v2.md) §4.3

---

## 9. 検証方法論 — 3-Observer Pattern (再利用可能)

> 出典: `docs/maintainers/verification-2026-05-26-stage-7-phase-n.md` §3, §8
>
> Stage 7 + Phase N の rollout で確立した検証 discipline。**機構を本番に rollout する前** に「3 つの独立した観察者」で literal 数値の一致を確認する方法論。ToDo 内の 🔴 / 🟡 タスクを実施するときは、可能な限りこのパターンに従う。

### Observer 役割分担

| Observer | 役割 | 典型ツール | 特性 |
|---|---|---|---|
| **A. 直読み snapshot** | DB レイヤの literal 数値 (ground truth) | `scripts/diag_dormant.py`, 書き捨ての `SqliteStore` 直叩き script | read-only、embedder load 不要、~1 sec |
| **B. dry-run projection** | 「今この操作を適用したらどうなるか」の予測 | `scripts/phase_n_dry_run.py` | 本番 DB を mutate しない、preset sweep、md+json 出力 |
| **C. 独立 LLM 観察** | P7-Z (観察者効果) 回避、formatter output 経由の確認 | `mcp__secondopinion__delegate_task(provider="glm", task=...)` | Claude Code session を汚さない、~100KB tool-result 上限を回避 |

### このパターンを使うべき ToDo 項目

- 🔴 1-2 (勾配の数値検証) — A: `gravity.py` 直叩き / B: analytical gradient / C: GLM に独立計算依頼
- 🟡 1-3 (Lyapunov) — B 単独で十分 (pure simulation)
- 🔴 4-1 (mass boost only ベースライン) — A: 静的 RAG 数値 / B: 提案実装の dry-run / C: GLM に「同じ corpus で nDCG を別途算出」依頼
- 🟡 4-3 (Ablation) — 各 ablation 行は B 単独可、本番効果なら全 3 走らせる
- 🟡 6-1 (Phase L Stage 2 BGE-M3) — A: BGE-M3 raw scores / B: RRF dry-run / C: GLM に「BM25 + RURI + BGE-M3 の 5-way RRF で top-5 が semantic に妥当か」評価
- 🟡 6-2 (Phase M Stage 2 θ 確定) — A: 本番 mass 分布 / B: 各 θ 候補の dry-run / C: GLM に「θ=X で retrieval quality がどう変わるか」評価
- 🟡 6-8 (Phase P Stage 1.5 / 2.5 本番 opt-in) — A: `state.displacement` 分布 snapshot / B: `scripts/diag_pressure.py` (新設) で `T_0` と `H` の sweep dry-run / C: GLM に「Stage 7 limitation の 5 hub クエリで top1 占有がどう動いたか」独立計測依頼

### Prompt 設計の原則 (Observer C, secondopinion-MCP)

`verification-... §3.3`:
1. 期待される操作 (具体的な MCP tool 呼び出し: ツール名 + args)
2. 観察項目 (substring 検出、top1/top5/metadata 等の何を見るか)
3. 期待される正解 (LLM 判断のための参考)
4. 報告フォーマット (200-400 字 / test、表 + 集計)
5. **「生出力貼らない、substring 検出のみ報告」を明示** (Claude Code 側 context 保護)
6. 終了後 `mcp__secondopinion__end_session(session_id=...)` を必ず実行

---

## 10. Default Promote の 3 段階 Rollout Discipline

> 出典: `docs/maintainers/verification-2026-05-26-stage-7-phase-n.md` §6

機構を **config default に昇格させる** ときに踏むべき 3 段階:

```
段階 1: 実装 + 内部 test、default OFF/None
段階 2: 本番 env opt-in (code 変更なし、claude.json + opencode.json に env 追加)
段階 3: config default に promote
```

### 段階 3 で必ず確認するべき invariants

Stage 7.1 default promote 時に **段階 3 で初めて表面化** した architectural 制約:
- `services/memory.recall` の `top_k * 3` 拡張が **prefetch_cache key と衝突** し常時 cache miss → 修正で expansion を撤回
- 4 件の cache-hit テストが failure: `test_prefetch_then_recall_emits_cache_hit_phrase`, `test_cache_hit_zero_perturbation`, `test_training_delta_topk_only_limits_coverage`, `test_prefetch_then_recall_hits_cache`

### 段階 3 を **スキップ** すべき条件 (Phase N の例)

- 操作が **irreversible** (例: mass evaporation は復元不可)
- 新規 deployment への暗黙適用が事故を生む
- 本番運用判断を毎回必要とする knob

これらは env opt-in (段階 2) で止め、code default は OFF/None のまま維持する。

### この discipline を適用すべき ToDo 項目

- 🟡 6-2 (Phase M Stage 2): θ 確定後 default 化するか env opt-in のままにするか判断必要
- 🟡 6-4 (Phase N-β): 既に「default OFF 維持」が確定方針
- 🟡 6-7 (Heavy Persona): env opt-in 中、default 昇格は measurement 後判断
- 🟡 6-6 (Lateral Stage 7): default promote 済、追加 env (`age=7d`) は default 未昇格のまま
- 🟡 6-8 (Phase P): Stage 1/2 で段階 1 (実装 + default OFF) → Stage 1.5/2.5 で段階 2 (env opt-in) → Stage 3 で段階 3 (default 昇格判断、Phase N β と同じく default 維持しない選択肢も残す)

### 段階 3 前のチェックリスト (新規)

新機構を default に上げる前に意図的に走らせるテスト:
- [ ] `test_tier1_phase_o_trailers.py` の cache-hit phrase 系
- [ ] `test_engine_training_delta.py` の topk_only 系
- [ ] `test_engine_explore_dormant.py` の absolute-threshold pinning
- [ ] prefetch round-trip (prefetch → recall → cache hit) を新 default 下で確認

---

## 11. メタ — レビュー対応そのもの

### 🟡 11-1. レビューへの公開返答 `[未着手]`
- レビューは外部から提示されたもの (`docs/maintainers/GaOTTT_review.md`)。「妥当性検証」 (このターン) は内部で完結したが、公開された分析として整理する場合:
- [ ] `docs/wiki/Research-Review-Response-2026-05-26.md` 新設 — 「§ごとの妥当性 + 既存文書との重複度 + 本 ToDo 上での対応番号」を表にして公開
- [ ] レビュー本文を `docs/research/external-review-2026-05-26.md` (private 領域でなければ) に保管

### 🟢 11-2. 本 ToDo の wiki sync 検討 `[未着手]`
- プロジェクト直下 `/ToDo.md` は GitHub トップで見える反面、wiki と二重管理になる
- [ ] 完了 Stage を消し込むタイミングで `Plans-Roadmap.md` 側の状態と整合性を確認するワークフロー (例: 月 1 で `_Sidebar.md` 更新と合わせて見直す) を確立

---

## 優先度ダッシュボード

| Tier | 項目 | 工数目安 | 既存文書との重複度 |
|---|---|---|---|
| 🔴 | 1-1 (暗黙 U の関数形修正) | 0.5d | 内部矛盾なので必ず必要 |
| 🔴 | 1-2 (勾配の数値検証) | 1-2d | レビュー §1 提案 1A、Research の open Q #1 |
| 🔴 | 4-1 (mass boost only ベースライン) | 2-3d | レビュー独自の鋭い指摘 |
| 🔴 | 7-1 (暗黙 loss 完全書き下し) | 1-2d | Research の open Q #1、§1-1 と統合可 |
| 🟡 | 1-3 (Lyapunov 検証) | 2-3d | Research の open Q #2 |
| 🟡 | 4-3 (Ablation 体系化) | 3-5d | レビュー §4-3、Tier 8 新設 |
| 🟡 | 6-2 (Phase M Stage 2 θ 確定) | 観察 1-2 週 + 0.5d | ロードマップ既存 |
| 🟡 | 6-1 (Phase L Stage 2 BGE-M3) | 5-7d | ロードマップ既存、6-2 待ち |
| 🟡 | 6-6/6-7 (Lateral / Persona tuning) | 各 0.5-1d | measurement-first、本番 baseline 必要 |
| 🟡 | 6-8 (Phase P Pressure Terms) | Stage 1 = 1-2d + Stage 2 = 2-3d、本番 opt-in は N β 後 | Stage 7 limitation の literal 解消、Phase M/N と並ぶ第 3 法則 |
| 🟡 | 3-2 (パラメータ感度分析) | 1 週間 | レビュー §3-2 |
| 🟢 | 4-2 (他ベースライン拡充) | 2-3d/baseline | レビュー §4-1 派生 |
| 🟢 | 4-4 (規模拡大評価) | 1-2 週 | Phase Q 起草が前提 |
| 🟢 | 7-3 (Adam/SGD-momentum 比較) | 3-5d | Research の open Q #3 |
| 🟢 | 5-1 (対応表精密化) | 0.5d | §1-1 で同時に消化 |
| 🟢 | 5-2 (Phase O long-term log) | 2-3d | Phase O 拡張、Tier 6 と合流 |

**横断 discipline**:
- §9 (3-observer pattern) は 🔴/🟡 の検証系タスクすべてに適用するベース手順
- §10 (3 段階 rollout) は default 化を伴うタスク (6-2, 6-7 等) に適用

---

## チェックリストとしての運用

新規 Phase 起草 / 既存 Stage 完了時:
1. [ ] 該当行を 🟢 まで降格 or 打ち消し線
2. [ ] `Plans-Roadmap.md` の対応行を更新
3. [ ] memory に save (decision / lesson / project の該当 type)
4. [ ] CLAUDE.md 冒頭の Phase 履歴を 1 行で記録 (本流の変更のみ)

レビュー対応として外向きに見せたい場合:
- §1 (🔴 1-1, 1-2, 1-5) と §4-1 (🔴 4-1) と §4-3 (🟡 4-3) の **4 項目** を「次の四半期で消化」と公約するのが、レビューが指摘した本質的弱点に最短で答える形になる
