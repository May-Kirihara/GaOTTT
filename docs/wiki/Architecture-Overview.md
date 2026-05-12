# Architecture — Overview

GaOTTT のモジュール構成と二重座標系の概要。

## モジュール構成

```
gaottt/
├── server/
│   ├── app.py            FastAPI (REST)
│   └── mcp_server.py     MCP (LLM 向け、25 ツール)
├── core/
│   ├── engine.py         オーケストレーション
│   ├── gravity.py        軌道力学（純粋関数）
│   ├── scorer.py         スコアリング（mass, decay, emotion, certainty）
│   ├── extractor.py      F1: auto_remember
│   ├── clustering.py     F2: 類似クラスタ (union-find)
│   ├── collision.py      F2.1: 衝突合体
│   ├── prefetch.py       F6: 非同期 prefetch (LRU + Semaphore)
│   └── types.py          Pydantic モデル
├── embedding/            RURI-v3-310m
├── index/                FAISS IndexFlatIP
├── store/
│   ├── base.py           StoreBase 抽象
│   ├── sqlite_store.py   永続化（自動マイグレーション）
│   └── cache.py          In-memory + write-behind
└── graph/                共起グラフ（無向）
```

## 二重座標系

GaOTTT の中核アイディア:

```
[原始 embedding 空間]   ── RURI-v3 が出力、不変
       ↓
[displacement BLOB]     ── 重力で更新される変位ベクトル
       ↓
[仮想座標 = original + displacement] ── recall で実際にスコアされる位置
```

これにより:
- 原始 embedding は破壊されない（再構築可能）
- 重力変位は仮想空間でのみ作用（FAISS リビルド不要）
- レイテンシ維持（FAISS top-K × 3 → 仮想座標で再計算）

## クエリフロー

```
クエリ
  ↓
RURI-v3 で embedding
  ↓
prefetch cache hit? ─ Yes → 即時返却
  ↓ No
gravity wave propagation（再帰的近傍展開、mass 依存 top-k）
  ↓
N ノード到達（シミュレーション層）
  ↓
仮想座標で再スコア（gravity_sim × decay + mass_boost + wave_boost
                  + emotion_boost + certainty_boost）× saturation
  ↓
top-K 返却（プレゼンテーション層）
  ↓
全到達ノードの軌道力学更新（acceleration → velocity → displacement）
```

## データフロー

### インデックス時

1. `POST /index` でドキュメント受信（または MCP `remember`/`ingest`）
2. content SHA-256 ハッシュで重複チェック（重複は embedding 生成前にスキップ）
3. RURI-v3 で embedding 生成（「検索文書: 」プレフィックス付き）
4. L2 正規化後、FAISS インデックスに追加
5. NodeState 初期化（`mass=1.0`, `temperature=0.0`, `displacement=zero`）
6. SQLite にドキュメント + 状態を永続化

### クエリ時

1. `POST /query` または MCP `recall` でクエリ受信
2. RURI-v3 でクエリ embedding 生成（「検索クエリ: 」プレフィックス付き）
3. prefetch cache hit 確認 → hit 時は即返却
4. 重力波伝播で広い候補取得（top-K × candidate_multiplier）
5. 各候補の仮想座標を計算（`original_emb + displacement`）
6. 仮想座標での cosine similarity × decay + mass_boost + wave_boost + emotion_boost + certainty_boost で最終スコア
7. 負スコアを除外、top-K に絞って返却
8. **返却後** に重力更新: 共起ペアに force 適用 → displacement 蓄積、mass/temperature/共起グラフも更新
9. ダーティ状態は write-behind で非同期に SQLite へフラッシュ

### ストレージ戦略

```
起動時:   SQLite → in-memory cache にロード + FAISS インデックスロード
稼働時:   キャッシュから読み取り → 変更は dirty セットに記録
定期的:   write-behind タスクが dirty 状態をバッチで SQLite にフラッシュ（5 秒間隔）
停止時:   write-behind 停止 → 全 dirty 状態フラッシュ → FAISS 保存 → 接続クローズ
異常終了: フラッシュされていない dirty 状態は消失（ドキュメント・embedding は保全）
```

## レイヤ別役割

| レイヤ | 責務 |
|---|---|
| **server/** | プロトコル変換（REST / MCP）。各 MCP ツール・REST エンドポイントは `services/` を叩く薄いラッパ |
| **services/** | engine を叩いて Pydantic を返す共有ビジネスロジック層（Phase S, 2026-04-22 新設）。MCP 向け整形文字列は `services/formatters.py` に集約 |
| **core/** | 物理シミュレーション、スコアリング、ロジック |
| **embedding/** | テキスト → ベクトル |
| **index/** | ベクトル近傍探索 |
| **store/** | 永続化、in-memory cache、write-behind |
| **graph/** | 共起グラフ |

## 設計判断の記録

GaOTTT の主要な設計選択とその根拠:

| 判断事項 | 決定内容 | 経緯 |
|---|---|---|
| 二重座標系 | 原始 embedding（不変）+ 仮想座標（重力変動） | Phase 1 評価で単一空間の限界が判明 |
| 重力モデル | 万有引力 `F = G×m_i×m_j/d²` | 物理的直感に合致、パラメータが明快 |
| 変位上限 | `max_displacement_norm=1e6` (Phase I で 0.3 → 1e6 に引き上げ、実質 ∞) | 当初は暴走防止のハードキャップだったが、Hooke 復元力 + displacement_decay + velocity cap が物理的均衡 (`d ≈ (G·m/k)^(1/3) ≈ 0.8–3.0`) を作るため冗長と判明 (Phase I, 2026-05-11)。boundary 張り付き → homogenization の発生源だった (P7-X)。詳細: [Plans — Phase I — Free Star Movement](Plans-Phase-I-Free-Star-Movement.md) |
| 候補拡張 | FAISS top-K × 3 → 仮想座標で再計算 | FAISS リビルド不要、レイテンシ維持 |
| graph_boost 廃止 | 重力変位に統合 | スコア加算では順位変動が不足 |
| 並行性 | Last-write-wins（ロックなし） | シングルインスタンス前提（後に WAL + busy_timeout で複数 OK） |
| 重複チェック | content SHA-256 ハッシュ | embedding 生成前にスキップ |
| モデルキャッシュ | ローカルキャッシュ自動検出 | HuggingFace API 通信を完全抑制 |
| 軌道力学 | 加速度 → 速度 → 位置の 3 段階物理 | 慣性による公転・彗星軌道、摩擦で減衰 |
| アンカー引力 | Hooke's law (`F=-k×d`) で原始位置に復元 | 脱出防止、銀河の暗黒物質ハローに相当 |
| 重力半径 | `min_sim = 1 - G×mass/(2×a_min)` | 質量から物理的に導出 |
| 重力波伝播 | 再帰的近傍展開、mass 依存 top-k | 高 mass ハブは広い重力圏 |
| 二層分離 | シミュレーション層 + プレゼンテーション層 | 全到達ノードの物理更新、LLM には top-5 のみ |
| 共起ブラックホール | 共起クラスタ重心に BH 形成 | 銀河束縛、edge_decay で自然消滅 |
| 返却飽和 | `saturation = 1/(1+return_count×rate)` | 同じ結果の繰り返し防止、脳の馴化 |
| 温度脱出 | `escape = 1/(1+temp×scale)` | 高温ノードが BH 束縛から脱出、探索促進 |
| **TTL 短期記憶 (F4)** | `source="hypothesis"` は default 7 日で auto-expire | 物理アナロジー: 仮想粒子 |
| **archive vs hard delete (F5)** | デフォルト soft archive、`hard=True` で物理削除 | dormant 剪定の儀式化、物理アナロジー: ホーキング輻射 |
| **重力衝突合体 (F2.1)** | 質量加算 + 運動量保存 + エッジ移譲 | 銀河衝突合体、`merged_into` で履歴保持、不可逆 |
| **情動・確信度の独立軸 (F7)** | scorer に `\|emotion\|` boost と certainty × exp(-age) | 質量と直交する軸、物理アナロジー: 角運動量 / スピン |
| **有向リレーション (F3)** | 別テーブル `directed_edges`、typed | 既存 cooccurrence の hot path を保持しつつ拡張 |
| **engine.compact()** | TTL expire + FAISS rebuild + 任意 auto-merge + orphan-edge 掃除 | 物理シミュレーションの定期メンテ |
| **バックグラウンド prefetch (F6)** | LRU+TTL キャッシュ + asyncio.Semaphore | 物理アナロジー: アストロサイト的事前発火、レイテンシ阻害ゼロ |
| **prefetch キャッシュ無効化** | archive/restore/forget/merge/compact が `prefetch_cache.invalidate()` を呼ぶ | destructive op 後の stale を防ぐ |
| **タスク状態を edge で表現 (Phase D)** | `task_status` 列を持たず、`completed`/`abandoned` エッジの存在で判定 | 完了の重力史が人格の年表になる |
| **人格を多源で表現 (Phase D)** | source = task / commitment / intention / value / style / relationship:* | 既存スキーマで実現、新テーブル不要 |
| **inherit_persona の儀式化** | 散文出力で過去の自分を着る | 柱 X「観測者を創ること即存在」のセッション継承版 |
| **共有サービス層 (Phase S, 2026-04-22)** | `gaottt/services/` が engine を叩き Pydantic を返す。MCP は formatter で文字列化、REST は JSON で直返却 | 同じロジックが二重実装にならず、REST が MCP parity に引き上がる。代替案（文字列 JSON ラップ / MCP 廃止 / 直 import）は [`docs/maintainers/rest-mcp-unification-plan.md`](https://github.com/May-Kirihara/GaOTTT/blob/main/docs/maintainers/rest-mcp-unification-plan.md) §6 で却下理由記録済み |
| **`/reset` は REST 専用** | MCP には露出しない | LLM エージェントに破壊的 reset を出さない現状判断を継承 |
| **FAISS write-behind (2026-05-10)** | `faiss_save_interval_seconds`（既定 5s）周期で disk に save | `shutdown()` でしか save しない設計だと長期常駐 MCP プロセスの新規 `remember` が他プロセスから永久 invisible になる歴史的バグの修正。逆方向上書き罠も発見・記載 |
| **Phase G — 重力法則の起動時適用 (2026-05-10)** | genesis kick (新規) + dream loop (idle 時) + Stage 0 priming (一回だけ全 active node に適用) | 物理アナロジー: 軌道捕獲 + tidal capture + primordial gravity activation。新規粒子も既存粒子と同じ重力法則を最初から受ける。bootstrap curator (LLM bridge) は不採用継承 |
| **Phase G — mass boost cap** | `genesis_mass_boost_cap=1.0` で 1 step 加算上限 | dense cluster 中心では raw `|acc|` が 70+ になる outlier が観測されたため。1 step で m_max 近くまで飛ばないよう「gradual accretion」を保証 |
| **Phase H Stage 1 — mass-aware seed boost (2026-05-10)** | `wave_seed_mass_alpha=0.1` で seed 段階 `raw_cosine + α*log(1+mass)` 再 rank | scoring 改善は確認 (5x) だが、sparse class の embedding 距離問題は超えられず |
| **Phase H Stage 2 — source-aware seed filtering (2026-05-10)** | `source_filter` 指定時に `cache.source_by_id` で seed pool から source 一致のみ抽出 | 23k corpus-heavy DB で初の agent class surface 達成。`wave_k_with_filter=500` 既定 (sparse class ~1.7%、expected 8.5 件) |
| **Phase H Stage 3 — density-aware dynamic wave_k (2026-05-10)** | top-N の tail/top 比率で sparse 判定、`wave_initial_k_max=50` まで拡大 | query が embedding 空間の sparse 領域に着地した場合の reach を救う保険 |
| **Phase H Stage 4 — virtual FAISS (2026-05-11)** | 第二の FAISS index を `virtual_pos = raw + displacement` で構築、seed pool は raw + virtual の union | priming で動いた displacement が seed step に効くようになり、本番 filter=none top1 score が 5.6x 改善 |
| **Phase I Stage 2 — implicit query-aware kick (2026-05-11)** | `compute_acceleration` に 4 番目の項 `a = (α · score / m_i) · (q - pos_i)` を追加 (`query_kick_strength=0.01`)。recall が retrieved nodes の displacement を query 方向に nudge する | TTT 解釈の「retrieval = gradient step」が構造的対応の主張ではなく **実装として literal に成立**。`F=ma` が mass damping を物理的に供給するので BH は動かず軽い node のみ反応。Hooke (項 2) が raw anchor を引き続き保持するので **transient force であって anchor migration ではない** (concept drift しない)。explicit `kick()` ツール案 (option B) は J2 bootstrap curator 批判の再現を避けるため不採用、implicit が選ばれた。詳細: [Plans — Phase I — Free Star Movement](Plans-Phase-I-Free-Star-Movement.md) §Stage 2 |
| **Phase I Stage 3 — mass-gated query attraction (2026-05-13)** | 第 4 項に `gate = tanh(m_i / θ)` を乗じる (`mass_anchor_threshold=3.0`)。新規 (m≈1) ノードは gate≈0.32 で 32% に減衰、mature (m≫θ) ノードはほぼ満額。`θ=0` で Stage 2 へ rollback | Stage 2 の副作用「単一アトラクタ pathology」(新規 m=1 ノードが初回 recall で `a=α` フルスケール drift → 以後全 query の top1 を独占する正のフィードバック) を物理的に矯正。**「足りない保護も active な過剰駆動と同じ症状を引き起こす」** — Stage 1 が学んだ「冗長な制約は active な制約と同症状」の対称形 lesson。F=ma は破らず anchor 不変も維持、追加コード ~10 行で最小実装。詳細: [Plans — Phase I — Free Star Movement](Plans-Phase-I-Free-Star-Movement.md) §Stage 3 |
| **Phase J Stage 1 — persona-anchored seed boost (2026-05-13)** | 新規 `core/persona_gravity.py` で declared value/intention/commitment から `fulfills`/`derived_from`/`completed` を N hop traverse (default 2, decay 0.5)、`propagate_gravity_wave` の seed step に `α_persona × proximity` を追加 (`persona_boost_alpha=0.5`)。CacheLayer に `directed_out`/`directed_in` を Phase H Stage 2 の `source_by_id` と同じ pattern で mirror、startup load + relate/unrelate で同期。recall API 変更なし (Stage 1 は内部 auto-detect のみ) | Phase I Stage 3 acceptance で観察された「dense mature agent cluster が sparse new agent cluster を押し退ける」現象 — Phase H Stage 2 の source_filter は同種内 (agent vs agent) で識別不可、Stage 3 の mass gate は mature 側を damping しない。declared identity から graph で繋がるノードを seed pool で優先することで「Five-Layer の人格層を retrieval geometry に literal に翻訳」。`persona_boost_enabled=False` で 1 行 rollback。詳細: [Plans — Phase J — Persona-Anchored Retrieval](Plans-Phase-J-Persona-Anchored-Retrieval.md) |
| **Phase K Stage 1 — stellar supernova cohort (2026-05-13)** | 新規 `core/supernova.py` で `index_documents` の batch を 1 超新星イベントとして読み、batch 内全員 (N≥2) に `supernova_initial_weight=1.0` の相互 co-occurrence edge と centroid からの `outward velocity = α × (emb-centroid)` (`supernova_velocity_alpha=0.03`, orbital_max_velocity で clamp) を付与。Phase G genesis kick の直後に適用 (個別重力 → cohort 重力の合成)。`supernova_enabled=False` で rollback | Phase J Stage 1 acceptance で「persona boost は pool 内 rerank のみで pool injection しない」が露呈、新規ノード群が **互いに重力を持たない散発的塵** だと dense mature cluster に競合できない。pool injection を運用回避策で済ますのではなく、**記憶生成の物理そのもの** を修正。Phase G genesis kick の集合版、Articulation as Carrier の複数性を物理化 (1 batch の `remember` は 1 つの宇宙論的イベント)。詳細: [Plans — Phase K — Stellar Supernova Cohort](Plans-Phase-K-Stellar-Supernova-Cohort.md) |
| **Phase J Stage 2 — explicit pool injection (2026-05-13)** | recall API に `persona_context: list[str] \| None` + `tag_filter: list[str] \| None` を追加 (MCP + REST parity)。`cache.tags_by_id` を Phase H Stage 2 `source_by_id` と同 pattern で持ち、`tag_filter` 経由で OR-substring 一致した node を seed step + final result の **両段階で force-inject**。`source_filter` を bypass (caller の explicit ask が勝つ)。Phase K Stage 1 で「new cohort 同士の重力」を解決、Phase J Stage 2 で「embedding 距離が遠い query から既存 cohort への到達権」を解決 | Phase K Stage 1 acceptance (retrospective ritual で 6216 edge + 112 velocity 追加後も 0/7) で「embedding 距離が dominant、boost は pool 入場後にしか効かない」と判明。LLM が「今の文脈 (intention/tag)」を明示的に伝える path を API として正面に位置づける。Stage 1 auto-detect は引数省略時の default として残る (backward compat)。詳細: [Plans — Phase J Stage 2](Plans-Phase-J-Persona-Anchored-Retrieval.md) §Stage 2 |
| **Phase J Stage 3 — forced 内 query-aware ordering + prefetch/explore parity (2026-05-13、Phase J 完遂)** | engine.py Step 4 で forced 内を `raw_score` 順 (query semantic) に並べる。final_score は mass/wave/emotion/certainty が dominant で「触りやすい memory」が勝つので、tag 一致の中での **query 関連度** が見えない問題を解決。prefetch + explore にも persona_context + tag_filter を追加 (MCP/REST parity)。types.PrefetchRequest / ExploreRequest 拡張 | Stage 2 acceptance で「top5 に tag 一致 surface ✅」と「top1 に正解 ⚠️ (1-2/7)」が分離した結果から導出。retrieval geometry の三段構造 (pool 入場 / pool 内 rerank / forced 内 ordering) を完成、各段で独立した signal が機能する設計に。詳細: [Plans — Phase J Stage 3](Plans-Phase-J-Persona-Anchored-Retrieval.md) §Stage 3 |
| **逆方向 cache 上書きの罠 (2026-05-10 発見)** | bulk 書き換え (Stage 0 priming 等) は他 MCP server プロセスを kill してから実施 | 古い cache を持つプロセスが flush し続ける限り新しい書き込みを上書きする。CLAUDE.md と Architecture-Concurrency.md に記載 |

## エントリポイントの読み方

主要な処理フローの入り口を順に追えば、コード全体が読み解ける:

1. **サーバー起動**: [`server/app.py`](../../gaottt/server/app.py) の `lifespan()` → 全コンポーネント初期化
2. **MCP 起動**: [`server/mcp_server.py`](../../gaottt/server/mcp_server.py) の `get_engine()` → 遅延初期化
3. **クエリ処理**: [`engine.query()`](../../gaottt/core/engine.py) → `gravity.propagate_gravity_wave()` → 仮想座標スコアリング
4. **軌道力学**: `engine._update_simulation()` → `gravity.update_orbital_state()`（3 段階物理）
5. **MCP `remember`**: `mcp_server.remember()` → `services.memory.remember()` → `services.memory.save_memory()` → `engine.index_documents()` → `formatters.format_remember()`
6. **MCP `commit`** (Phase D): `mcp_server.commit()` → `services.phase_d.commit()` → `save_memory(source="task")` → `engine.relate(fulfills, parent)` → `formatters.format_commit()`

## 詳細セクション

- [Storage & Schema](Architecture-Storage-And-Schema.md) ── テーブル定義、列の意味
- [Gravity Model](Architecture-Gravity-Model.md) ── スコア式、軌道力学
- [Concurrency](Architecture-Concurrency.md) ── WAL、busy_timeout、複数プロセス共存

## コード参照

- [`gaottt/`](../../gaottt/) — 全モジュールの実装
- [`gaottt/config.py`](../../gaottt/config.py) — 全ハイパーパラメータ
