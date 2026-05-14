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

**25 ツール** + **11 reflect aspect**

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
- **Phase N (未起草、tuning target)** — RRF-scale aware mass boost。Phase L Stage 1 (RRF) と Phase H Stage 1 (`α × log(1+mass)`) の score scale 不整合(2026-05-14 発見: cosine スケール想定の α が RRF スケール ~0.03 に対し過剰、mass の重い無関係 chunk が semantic を上書き)を構造的に解消。暫定対処は `wave_seed_mass_alpha = 0.0` で seed boost 完全 disable([Operations — Troubleshooting](Operations-Troubleshooting.md) 「ファイルで登録した文書が recall に出てこない」節)。Phase N では (a) RRF score の正規化 / (b) rank-based boost / (c) Phase H の意図(heavy node lift)を別レイヤーに移す、のいずれかを設計予定。同時に `wave_initial_k=3` の見直し(大規模 corpus に対し小さすぎる)も検討。
- [SKILL.md Improvement](Plans-SKILL-MD-Improvement.md) — 二層語彙、パターンカタログ
- [REST × MCP Unification Plan (Phase S)](https://github.com/May-Kirihara/GaOTTT/blob/main/docs/maintainers/rest-mcp-unification-plan.md) — 保守者向け、Phase S0–S6 の作業計画

## 未実装 / 検討中

### Phase E 候補（ユーザー次第）

- **`engine.compact()` の定期自動実行** — 現状は手動。write-behind ループに組み込む or cron で MCP `compact` を叩く運用
- **prefetch キャッシュキーの embedding 量子化** — 現状は `(query_text, top_k)` 完全一致。「類似クエリでも hit」させたい場合は embedding を粗量子化
- **マルチユーザー状態分離** — NodeState, CacheLayer にユーザーIDディメンション追加
- **PostgreSQL 移行** — `store/base.py` の StoreBase に対して Postgres 実装を追加
- **認証** — FastAPI ミドルウェアで API キー or OAuth2
- **IndexIVFFlat 移行** — 100K 件超で FAISS インデックスを IVF に切り替え

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
