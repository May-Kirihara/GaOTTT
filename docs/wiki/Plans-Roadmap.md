# Plans — Roadmap

GaOTTT の Phase 進捗と未実装機能の俯瞰。

## 進捗サマリ

| Phase | 内容 | 状態 |
|---|---|---|
| **Phase 1-2** | 重力変位、軌道力学、共起 BH、馴化、3D 可視化 | ✅ 完了 |
| **Phase A** | F1 auto_remember, F4 TTL, F5 forget/restore | ✅ 完了 |
| **Phase B** | F2/F2.1 衝突合体, F3 有向リレーション, F7 情動・確信度 | ✅ 完了 |
| **Phase C** | F6 バックグラウンド prefetch | ✅ 完了 |
| **Phase D** | 人格保存基盤 + タスク管理 | ✅ 完了 |
| **Phase S** | REST × MCP 共有サービス層に集約、REST を MCP parity まで引き上げ | ✅ 完了（2026-04-22） |
| **Phase G** | 新規 memory への重力法則の起動時適用（軌道捕獲 + 夢 + 全件 priming） | ✅ 完了（2026-05-10） — Stage 1 (G.1 軌道捕獲) + Stage 2 (G.2 夢) + Stage 0 (priming) を実装。Stage 3 (G.3 重心アンカー) は homogenization リスクで永久保留。新規 doc の surface 改善は構造的に Phase H の領域と判明 |
| **Phase H** | Wave seed redesign — 新規 / sparse class が wave 入口で排除される問題の修正 | ✅ 完了（2026-05-10〜13）— Stage 1 (H.3 mass-aware boost) + Stage 2 (H.4 source-aware seed filtering) + Stage 3 (H.1 dynamic wave_k) + Stage 4 (H.2 virtual FAISS) 全段完了。本番 DB の filter=none top1 score が 5.6x 改善、一部クエリで初の agent surface 達成。残った agent surface 課題は displacement の方向問題で、Phase G の構造的限界。Stage 5 (2026-05-13): wave 中の per-frontier neighbor 探索を raw → virtual FAISS に切り替え（`wave_neighbor_use_virtual=True`）+ virtual FAISS write-behind 導入（`virtual_faiss_save_interval_seconds=60`）。seed pool だけ raw∪virtual で per-frontier が raw のみという設計上の不整合を解消、「星同士の引力」原則を wave 全段で literal に |
| **Phase I** | Free Star Movement — displacement boundary 解除 + query-aware displacement + mass-aware physics | ✅ 完了（2026-05-11〜14）— Stage 1 (boundary removal: `max_displacement_norm` 0.3 → 1e6) で Hooke + decay + velocity cap の物理的均衡を実観測。Stage 2 (implicit query-aware kick: `compute_acceleration` に 4 項目追加、`α=0.01`) で TTT 解釈の「retrieval = gradient step」が実装として literal に成立。Stage 3 (mass-gated kick: `gate = tanh(m/θ)`, `θ=3.0`) で新規ノードを anchor が保護、単一アトラクタ pathology を物理的矯正。**Stage 4 (mass-dependent Hooke: `k_eff = k · (1 + β · (1 - tanh(m/θ)))`, `β=0.0` opt-in default、2026-05-14)** で Stage 3 の対称形を Hooke 側に拡張、軽い星を anchor 側からも守る generational physics を完成 — 観察 pathology 無しの prophylactic refinement なので β=0 default、Stage 3 単独で 1-2 週間運用後に活性化判断。本番 acceptance で「dense mature agent cluster vs sparse new agent cluster」は別軸と判明し Phase J へ。Stage 1 [長期検証 ✅ (2026-05-12)](Plans-Phase-I-Free-Star-Movement.md#stage-1--長期検証-結果-2026-05-12) — 24,025 active nodes で max=0.60 / p99=0.54 / `|d|≥0.8` で 0 nodes、boundary 1e6 は理論通り redundant を確認 |
| **Phase J** | Persona-Anchored Retrieval — declared identity が retrieval geometry を曲げる | ✅ **完遂**（2026-05-13）— Stage 1: auto-detect graph traversal + seed step boost。Stage 2: explicit `persona_context` + `tag_filter` で seed/final 両段階の force-inject。Stage 3: forced 内 query-aware ordering (raw_score 順) + prefetch/explore parity。retrieval geometry の三段構造 (pool 入場 / pool 内 rerank / forced 内 ordering) が完成 |
| **Phase K** | Stellar Supernova Cohort — index 時に batch 内全員へ相互 edge + outward velocity | ✅ Stage 1 完了（2026-05-13）— Phase J Stage 1 acceptance での seed pool 入場権問題を、retrieval rerank ではなく **記憶生成の物理** で解決。1 batch の `remember` = 1 超新星爆発として読み、batch 内 N 件に N×(N-1)/2 本の co-occurrence edge と centroid からの outward velocity を付与。Phase G genesis kick の集合版、Articulation as Carrier の複数性を物理化。`supernova_enabled=False` で rollback |
| **Phase L** | Hybrid Retrieval — embedder の semantic ranking 限界を別 metric tensor (BM25 lexical) の重ね合わせで突破 | ✅ Stage 1 完了（2026-05-14）— [Plans](Plans-Phase-L-Hybrid-Retrieval.md)。「最も literal な解」基準で **A. Hybrid retrieval** を採用、Stage 1 = BM25 union seed (numpy in-memory + char 3-gram tokenizer + `_union_pool` 3-way 拡張 + **RRF fusion** + Phase J Stage 3 forced ordering 段にも RRF)。本番 acceptance: Surface 7/7 ✅ / Semantic 整合 strict 4/7 (Phase J Stage 3 時 0-1/7 から +3-4 改善) / top3 緩和 7/7、MCP transport 経由 strict 6/7。Sudachi は optional extra、BM25 disk persistence は別 stage、wave neighbor への BM25 拡張なし。LLM 不要・ローカル完結・rollback flag 1 つで完全 off。**Stage 2 起草済**（2026-05-13）— 別 embedder (BGE-M3) で意味空間 cosine を 4-way (raw + virtual × 2 embedder) に拡張、BM25 と合わせ 5-way RRF fusion、forced ordering も 3-way RRF。D1-D6 全 (a) 確定済み。**着手は Phase M Stage 1 完了 + 1-2 週観測後**（2026-05-13 判断、mass 偏在が cleaner になってから ensemble metric の効果分離を計測する方針） |
| **Phase M** | Mass Conservation — 「自己関与は mass を生まない」単一規則で source 偏在を構造的に矯正 | ✅ Stage 1 実装完了（2026-05-13）— [Plans](Plans-Phase-M-Mass-Conservation.md)。Phase L Stage 1 acceptance で観測された「source=file/tweet が agent 知識の top1 を奪う」構造的問題の根を追跡し、**1 file = 91 chunks 平均の内輪取引による mass inflation** を発見。「**外部からの引力でのみ mass が増える**」という熱力学第一法則の literal な実装で source 分岐なしに矯正。`is_self_force(a, b) = (original_id 一致 or cohort_id 一致)` の単一規則で全 source に普遍適用。**Articulation as Carrier (id=9a954c62) の literal な物理実装**になる稀な設計同型 — 「**言葉にした上で誰かに引かれることで mass を持つ**」、persona も例外ではない (使用頻度こそが重力)。実装: `propagate_gravity_wave` の per-parent attribution、`engine._update_simulation` の self-force filter、共起 BH 削除 → `compute_mass_bh_acceleration` (連続 `tanh((m-θ)/σ)` factor)、`reset_masses` (REST `/admin/reset_masses` + `scripts/reset_masses.py`、MCP 非露出)。**ロールアウトは versioned migration 化** ([Operations — Migration](Operations-Migration.md)) — M002 (BH 残滓 cleanup) → M003 (mass reset、wizard で必ず聞く) → M004 (corpus-scale cosmic-bang ignition、Newton 1 法則で永遠に止まる cold state を点火) の 3 critical step を wizard 式で順番に確認。テスト 278 全 green、bench p50=48.3ms、smoke REST+MCP 各 6/6。`mass_bh_theta=5.0`/`mass_bh_sigma=1.5` は暫定、本番 mass reset 後 1-2 週観測で Stage 2 で確定。**Phase L Stage 2 より先に着手** |

## 累積 MCP ツール数

**26 ツール** + **11 reflect aspect**

詳細: [MCP Reference Index](MCP-Reference-Index.md)

## 計画書

- [Backend Phase A/B/C](Plans-Backend-Phase-A-B-C.md) — F1〜F7 の機能ロードマップ
- [Phase D — Persona & Tasks](Plans-Phase-D-Persona-Tasks.md) — 人格層追加の設計
- [Phase G — Memory Genesis](Plans-Phase-G-Memory-Genesis.md) — 軌道捕獲 + 夢 + 全件 priming で新規 memory を gravity 場に sink させる（完了）
- [Phase H — Wave Seed Redesign](Plans-Phase-H-Wave-Seed-Redesign.md) — wave seed が raw cosine 固定で sparse class を排除する問題の修正（完了）
- [Phase I — Free Star Movement](Plans-Phase-I-Free-Star-Movement.md) — displacement boundary 解除と query-aware displacement + mass-dependent Hooke（Stage 1-4 完了、Stage 4 は opt-in default）
- [Phase J — Persona-Anchored Retrieval](Plans-Phase-J-Persona-Anchored-Retrieval.md) — declared identity から `fulfills`/`derived_from` で繋がるノードを seed step で gravity boost（Stage 1 完了）
- [Phase K — Stellar Supernova Cohort](Plans-Phase-K-Stellar-Supernova-Cohort.md) — 1 batch の `remember` を超新星爆発として読み、batch 内全員へ相互 edge + outward velocity（Stage 1 完了）
- [Phase L — Hybrid Retrieval](Plans-Phase-L-Hybrid-Retrieval.md) — embedder の hidden ranking 限界を BM25 lexical metric の union seed で構造的に拡張（Stage 1 完了、Stage 2 起草中 — BGE-M3 ensemble で意味空間も二重化）
- [Phase M — Mass Conservation](Plans-Phase-M-Mass-Conservation.md) — 「自己関与は mass を生まない」単一規則で mass 蓄積の chunk 内輪取引を構造的に矯正、Articulation as Carrier の literal な物理実装（Stage 1 実装完了、本番ロールアウト待ち）
- **Phase N (β 起草済、確定待ち)** — Phase N は 3 候補が競合する予約地で、**Plans 化された最初の案を Phase N 確定**、残りは Phase P/Q/R に繰り下げる規約。2026-05-15 時点で β のみ Plans 化済 — 着手 (Stage 1 実装) は Phase M Stage 2 (mass reset 後 1-2 週観測 + θ 確定) と並行可能 (default OFF で merge、本番 opt-in は Phase M Stage 2 後):
  - **(N-α) RRF-scale aware mass boost** (未起草) — Phase L Stage 1 (RRF) と Phase H Stage 1 (`α × log(1+mass)`) の score scale 不整合 (2026-05-14 発見: cosine スケール想定の α が RRF スケール ~0.03 に対し過剰、mass の重い無関係 chunk が semantic を上書き) を構造的に解消。暫定対処は `wave_seed_mass_alpha = 0.0` で seed boost 完全 disable ([Operations — Troubleshooting](Operations-Troubleshooting.md) §「ファイルで登録した文書が recall に出てこない」)。設計案: (a) RRF score の正規化 / (b) rank-based boost / (c) Phase H の意図 (heavy node lift) を別レイヤーに移す。`wave_initial_k=3` の見直し (大規模 corpus に対し小さすぎる) も同時検討。
  - **(N-β) Mass Evaporation (Hawking radiation 類比)** ✅ **起草済 (2026-05-15)** — [Plans](Plans-Phase-N-Mass-Evaporation.md)。Phase M で「自己関与は mass を生まない」(入力側) を literal 化したので、対称形として「使われない mass は自然減衰する」(出力側) を物理化する。命名は Hawking 類比だが数学は恒星 luminosity + Ebbinghaus の混合 (literal Hawking だと direction が逆になる罠を回避、Phase M の「source 分岐ゼロ」と同じ「名前は homage、数学は問題を解くもの」姿勢)。単一規則: `mass -= ε · (mass - M_floor)^β · (t_idle/τ_idle)^γ · dt`。動機は 2026-05-15 GLM playthrough Figure 0 が独立検出した「hot_topics 上位が legacy bulk-ingest debt で固まっている」観察。Phase O Stage 5 dormant の母集団復元も副次予測 (仮説 2)。**Stage 1 (lazy 実装 + default OFF) は Phase M Stage 2 を待たずに着手可能**、本番 opt-in (Stage 1.5) は Phase M Stage 2 後。
  - **(N-γ) Muon thought experiment** — query attraction の Muon 化思考実験 ([Research — Muon Thought Experiment](Research-Muon-Thought-Experiment.md))。`compute_acceleration` 第 4 項のみに toggle で適用、acceptance で「観測 conformism が和らぐか」を計測。Phase L acceptance の hybrid retrieval geometry が落ち着いてから着手するのが順序的に自然
- [Phase O — TTT Observability](Plans-Phase-O-TTT-Observability.md) — LLM caller を TTT loop の participant に昇格させる observability layer。Phase I Stage 2 で literal 成立した「retrieval = gradient step」を caller-side に閉じる。5 stage: score breakdown / training delta trailer / query routing / list mode / dormant surface。**全 5 stage 完了 (2026-05-14)**: Stage 1 で forward pass (gradient) を、Stage 2 で backward pass (parameter update) を、Stage 3 で query routing (surface form classifier + reflect 並走) を、Stage 4 で list mode (service 層 80字 truncate で context 経済) を、Stage 5 で dormant surface (counter-importance sampling で「埋もれる自由」の対をなす「思い出される自由」) を caller に露出。`ScoreBreakdown` / `TrainingDelta` / `RoutingHint` Pydantic model、`RecallRequest.mode` / `ExploreRequest.mode` で opt-in モード、MCP/REST 両側 parity。`expose_score_breakdown=False` / `training_delta_enabled=False` / `auto_route_enabled=False` で legacy fallback、Stage 4-5 は default `detail` / `serendipity` (opt-in)。Stage 3 の classifier も Stage 5 の `dormant_source_classes` 列挙も **query intent layer の filter / routing** であって physics rule (mass / Hooke / kick) は一切触らない — Phase M の「source 分岐ゼロの単一規則」を全 stage で侵さない
- [Observation Apparatus Refinement](Plans-Observation-Apparatus-Refinement.md) ✅ **Stage 1-4 実装完了 (2026-05-26)** — 2026-05-26 dogfooding (Claude/Codex + 新規 Claude セッション) で 2 観測者が独立に到達した 5 点 (dormant 過小評価 / Heavy Persona Dominance 体感 / connections の ingest artifact / reason line 不在 / 比較 wrapper 不在) を、**physics rule 不変・観測層のみ** で解決する 4 stage 計画。Stage 1: reason line (`ScoreBreakdown.reason` で 1 行 human-readable explanation、dominance artifact 早期警告)、Stage 2: ambient dormant slot (`ambient_recall()` に `dormant_whisper` 1 件を BM25 floor 強めで混ぜる)、Stage 3: `scripts/compare_retrieval.py` (recall / explore / dormant / ambient を横並びにする read-only 観測ツール)、Stage 4: `reflect(aspect="connections")` の source-aware bucket 表示 (force computation には触らない、表示 lens のみ)。dogfooding 過程で出た **「declare value 初期 kick」案は撤回** ([[feedback_no_source_branching]] / Phase L Stage 1「persona も別格扱いしない」と衝突)。Phase P (acceleration 拡張) / Phase N β (mass update) と **並行に進められる** — 介入軸が直交、本計画は Phase O 後続の観測層のみ。physics Phase ではないので Phase レター非消費
- [Phase P — Pressure Terms](Plans-Phase-P-Pressure-Terms.md) ✅ **Stage 1 (Langevin) 実装完了 (2026-05-27、default OFF)** — Cosmological Λ (長距離斥力) + Langevin Temperature (熱的揺らぎ) を gravity への対抗 pressure として導入。Phase M (mass 増の単一規則) — Phase N β (mass 減の単一規則) に続く **「mass 値そのものに頼らず geometry 側で mass dominance を解く」** 第 3 法則。Stage 7.1 anti-hub の scope 外として残った individual-node high-mass dominance (ffe48a30 等の singleton hub) を、ranking 層ではなく **acceleration / displacement step** で構造的に押し返す。**Phase N の "残り候補" 規約と独立** — Phase P は Pressure Terms を確定し、N-α (RRF-scale aware mass boost) は phase letter を消費しない ranking-layer fix、N-γ (Muon) は Q/R に繰り下げ ([Plans-Phase-P §11](Plans-Phase-P-Pressure-Terms.md#11-phase-n-の-残り候補-との関係))。**P-α (Λ) と P-β (Langevin) は数学的に直交、両方 default OFF で並列実装**。Stage 1 = Langevin (smaller blast radius、先), Stage 2 = Λ (acceleration loop 拡張, 後)。本番 opt-in 順は Phase N β Stage 1.5 完了 + 1-2 週観測後
- [Hardening — Concurrency & Persistence](Plans-Hardening-Concurrency-Persistence.md) — 2026-05-18 網羅コードレビュー由来。proxy mode (N agents → engine 1 プロセス) で顕在化する並行性・永続化の正確性バグを機構で閉じる。physics Phase ではないので Phase レター非消費。**Stage 1 完了 (2026-05-18)**: C1 (displacement 消失 → column-preserving upsert) / C3 (explore の共有 gamma 破壊 → per-call gamma_override) / C4 (reset の prefetch 未無効化) を修正 + teeth-having 回帰、487 passed。C2 (並行 recall の lost-update 説) は調査の結果バグでないと判明 (mutation phase は asyncio 下でアトミック) し no-op 確定。Stage 2-4 = HIGH/MEDIUM/LOW catalogue
- [Ambient Recall](Guides-Ambient-Recall.md) — `recall(passive=True)`（read-only / 摂動なしの観察 — mass・displacement・co-occurrence・`last_access` を一切書かない）+ Claude Code `UserPromptSubmit` フック / opencode `chat.message` プラグインによる受動的文脈注入。明示的に recall を呼ばなくても長期記憶が自動で効く。observer effect (P7-Z) を機構で閉じる。physics Phase ではないので Phase レター非消費。**完了（2026-05-21）**
- [Ambient Recall Enrichment](Plans-Ambient-Recall-Enrichment.md) — 上記の read-side 拡張。注入を「フラットな top-k」から「構造化スロット」（直接ヒット / 重力レンズ枠 / 理由の連鎖 / 矛盾フラグ / 人格行 / メタ注釈）に。`services/memory.ambient_recall()` + 新 MCP ツール `ambient_recall` + REST `/ambient_recall`。physics Phase 非消費。**Stage 1-4 実装完了（2026-05-21）** — 538 passed。Stage 4 で relevance gate を本番校正に基づき `virtual_score` → BM25 語彙一致に差し替え（dense cosine は 32k コーパスで on/off-topic 分離不能と実証）。フックは `ambient_recall` 呼び出しに差し替え済
- [Query as Mass Distribution (Multi-Source Query)](Plans-Query-Mass-Distribution.md) — クエリを単一の pooled centroid ではなく N 個の点質量（節分割）として扱い、seed pool 段で superpose（per-segment `_union_pool` を RRF 融合、wave は 1 回）。複合プロンプトが語彙的に重い側に引っ張られる問題（2026-05-21 opencode ambient 本番観察）を、pooling という唯一の非物理ステップの修正として解決。physics rule 不変（centroid は scoring / TTT anchor のまま）なので Phase レター非消費。`multi_source_enabled` / `multi_source_ambient_enabled` 両 default ON（2026-05-21 実 RURI perf 検証後 — 複合クエリ recall ~2× / p95 ~40ms）。**Stage 1-2 実装完了（2026-05-21）**
- [REST × MCP Unification Plan (Phase S)](https://github.com/May-Kirihara/GaOTTT/blob/main/docs/maintainers/rest-mcp-unification-plan.md) — 保守者向け、Phase S0–S6 の作業計画

## 未実装 / 検討中

### Phase E 候補（ユーザー次第）

- **`engine.compact()` の定期自動実行** — 現状は手動。write-behind ループに組み込む or cron で MCP `compact` を叩く運用
- **prefetch キャッシュキーの embedding 量子化** — 現状は `(query_text, top_k)` 完全一致。「類似クエリでも hit」させたい場合は embedding を粗量子化
- **マルチユーザー状態分離** — NodeState, CacheLayer にユーザーIDディメンション追加
- **PostgreSQL 移行** — `store/base.py` の StoreBase に対して Postgres 実装を追加
- **認証** — FastAPI ミドルウェアで API キー or OAuth2
- **IndexIVFFlat 移行** — 100K 件超で FAISS インデックスを IVF に切り替え

### 研究 / 検討中の代替実装

- **[Embedder Comparison (RURI vs RikkaBotan)](Plans-Embedder-Comparison.md)** — JA-EN bilingual + static + MRL の代替 embedder と現状 RURI の比較評価。**❌ Phase A STOP (2026-05-25)** — RikkaBotan は quantized/fp32 ともに static 構造の限界で discriminative power 不足、pure cross-lingual probe で RURI 全条件勝利 (RURI 5/5 vs RikkaBotan 3/5)、Phase B/C 進行根拠なし。**副次成果**: RURI の pure cross-lingual を小規模 (5 distinct topics) で 5/5 実機確認、`project_ruri_crosslingual_behavior` の知見を「条件付き」に更新する根拠を獲得 (production scale での挙動は needle-in-haystack で別途検証の余地あり)
- **[Ambient Recall Refinement (Phase A 由来)](Plans-Ambient-Recall-Refinement.md)** — Phase A 中の ambient block literal 観察で見つかった 5 つの quality refinement。**🟢 Stage 1-5 + follow-up (b) 完了 (2026-05-25)**。Stage 1: query-conditioned persona slot (`mass × cos` re-rank) / Stage 2: tag-based exclusion (`exclude_tags` API + `GAOTTT_AMBIENT_EXCLUDE_TAGS`) / Stage 3: score breakdown in ambient block (`expose_breakdown` + Phase O Stage 1 流用) / Stage 4: multi-turn context window in hook (`GAOTTT_AMBIENT_HISTORY_TURNS`) / Stage 5: ambient quality measurement Tier (`tests/perf/test_tier3_ambient_quality.py` + golden corpus 12 seed × 6 query)。本番 acceptance で発見した Heavy Persona Dominance (`mass=2.82` の単一 intention が query 横断で persona slot 独占) には follow-up (b) で `ambient_persona_mass_weight: float = 1.0` knob を追加 (`score = (mass ** w) × cos`、`w=0` で `relevance_dominant` / `w≈0.3` で log-scale 近似を subsumes)、既定 `1.0` で Stage 1 完全互換、本番 tuning は measurement-first で別ターン
- **[Ambient Recall Lateral Association (「〇〇といえば〜だったよな」)](Plans-Ambient-Recall-Lateral-Association.md)** — Refinement 完遂後の Claude Code self-use + GLM acceptance + hook 観察から導かれた v3 plan。設計目的の literal な言語化「ambient recall は『〇〇といえば〜だったよな』感覚の機構化」(めいさん 2026-05-25) を北極星に、6 stage で **session 内反復 / lexical 釣れ / lensing sparse / composed query 不透明 / lensing 妥当性 signal 欠落** の 5 root cause に対処。Stage 1: session-aware novelty decay (`GAOTTT_AMBIENT_NOVELTY_TURNS` + hook transcript 解析) / Stage 2: direct hits の topic vs lexical anchor 分離 / Stage 3: lensing top-1 → top-K dynamic / Stage 4: composed query opt-in 可視化 (hook-only) / Stage 5: lensing resonance signal / Stage 6: lateral measurement Tier (golden corpus 拡張)。**🟢 Stage 6a baseline + Stage 1 (Step 1a passive gate bug fix + Step 1b transcript-aware novelty decay) + Stage 3 (lensing top-K) + Stage 5 (lensing resonance 5a cooccurrence) + Stage 4 (composed query opt-in 可視化) 完了 (2026-05-25)**。**🟢 Stage 7.1 / 7.2 完了 (2026-05-26 dogfooding follow-up)** — Stage 7.1: direct-hit anti-hub (`direct_hit_anti_hub_lambda`、`cohort_id` MMR、既定 OFF、acceptance: avg_unique 2.67→4.00 / avg_max_dom 2.33→2.00 @ λ=0.4) / Stage 7.2: dormant distribution-relative cut (`dormant_mass_percentile`、既定 None=legacy、`scripts/diag_dormant.py` で本番分布診断)。残: Stage 2 + 全 stage の production dogfooding + Stage 7 本番 opt-in tuning (measurement-first, λ / percentile を本番 baseline で確定)

### マルチエージェント実験から派生したアイディア

- **共有メモリでの "ベイスン吸引" を緩和する仕組み** — `explore(avoid_recently_recalled=True)` フラグ
- **`reflect(aspect="agent_activity", since=...)`** — 他エージェントが最近触ったノードを表示
- **コラボレーション可視化** — 「誰が誰の記憶に relate を作ったか」のフロー可視化

### 拡張時の注意点

- `store/base.py` の StoreBase インターフェースを崩さない（abstract method の追加は OK）
- embedding の L2 正規化は必須
- RURI-v3 のプレフィックス（「検索クエリ: 」「検索文書: 」）は省略不可
- displacement BLOB は 768 次元 float32（3KB/ノード）
- 既存 DB は起動時に ALTER TABLE で自動マイグレーション（追加列は必ず DEFAULT 付き）
- MCP ツールのシグネチャ変更は禁止。新引数は必ずオプショナル
- ベンチ走行時は本番 DB を触らないよう [`isolated benchmark`](Operations-Isolated-Benchmark.md) を使う

## 関連

- [Architecture — Overview](Architecture-Overview.md) — 設計判断の表
- [Plans — Backend Phase A/B/C](Plans-Backend-Phase-A-B-C.md) — Phase A〜C 詳細
- [Plans — Phase D — Persona & Tasks](Plans-Phase-D-Persona-Tasks.md) — Phase D 詳細
