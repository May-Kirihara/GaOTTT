# Plans — Ambient Recall Enrichment

> 注: これは physics Phase ではなく [Ambient Recall](Guides-Ambient-Recall.md)（受動的文脈注入）の **read-side 拡張**。Phase レター非消費の独立ドキュメント（[Roadmap](Plans-Roadmap.md) の [Hardening](Plans-Hardening-Concurrency-Persistence.md) と同じ扱い）。
> 状態: **Stage 1-4 実装完了 (2026-05-21)** — `services/memory.ambient_recall()` + 新 MCP ツール `ambient_recall` + REST `POST /ambient_recall` + フック差し替え。直接ヒット ① / 重力レンズ ② / メタ注釈 ③ / 理由の連鎖 ④ / 矛盾フラグ ⑤ / 人格行 ⑥ 全スロット稼働。Stage 4 で relevance gate を `virtual_score` → BM25 語彙一致に差し替え（本番校正で dense cosine の分離不能を実証、下記）。`pytest tests/` 538 passed / 1 skipped、ruff は documented pre-existing 3 件のみ。書き込み側（決定/失敗記憶の規約）と preemptive injection は未着手（下記参照）。
> 関連: [Guides — Ambient Recall](Guides-Ambient-Recall.md), [MCP Reference — Memory](MCP-Reference-Memory.md), [Phase J — Persona-Anchored Retrieval](Plans-Phase-J-Persona-Anchored-Retrieval.md), [Phase O — TTT Observability](Plans-Phase-O-TTT-Observability.md), [Architecture — Overview](Architecture-Overview.md)
> 発端: 2026-05-21 の ambient recall live acceptance。フックは正しく発火したが、surface された記憶は「関連はするが質問の核心ではない」もの中心だった（"niceboat の今のアーキテクチャ" に対し、gate を通したのは回収率テーブル `virtual_score 0.78`、アーキテクチャ doc 一覧は `virtual_score 0.047`）。同セッションの Claude 側リフレクションで「注入が面白い／有用なのは、LLM が自力で安く再構成できない知識のとき」という整理が出た。本計画はその整理を機構に落とす。

## 背景 — なぜ「フラットな top-k」では足りないか

現行 ambient recall は `recall(passive=True)` の top-k をそのまま `<gaottt-ambient-recall>` ブロックに流す。これは「ヒントとしては効くが、その場で答えを構成できる密度には届かない」。live acceptance で観測された構造的限界:

- **relevance gate は「話題が近い」しか測れない** — `virtual_score` 最大の記憶が surface するが、それが「判断に効く記憶」とは限らない。
- **ファイルパス・現在のコードは注入価値が低い** — LLM が grep で数秒で取れる。注入が効くのは *自力で再構成できない* 知識: 決定の理由、行き止まり、構造的アナロジー、人格。
- **生チャンクは低密度** — 300字 truncate された会話ログは情報密度が低い。

中核の設計原理: **注入の価値は「LLM が自力で取れなさ」に比例する**。本計画は注入を「フラットな top-k」から「数スロットの構造ブロック」に変え、各スロットを *再構成しにくい知識* に割り当てる。

## 中核アイデア — 注入を構造化スロットに

新サービス関数 `services/memory.ambient_recall()` が、1 回の passive recall（`top_k≈10` 内部）+ in-memory グラフ参照で **構造化された AmbientRecallResponse** を組み立てる。フック / MCP / REST は薄いラッパのまま。

### スロット設計

| # | スロット | 中身 | 再利用する既存機構 | 新規実装 | Stage |
|---|---|---|---|---|---|
| ① | 直接ヒット | passive recall の top 2（`final_score` 順） | `recall(passive=True)` | — | 1 |
| ② | 重力レンズ枠 | `virtual_cosine − raw_cosine` の gap 最大の 1 件 | `score_breakdown` の raw/virtual cosine | gap 計算・選択・noise floor | 1 |
| ③ | メタ注釈 | 各行に `source · certainty · age` | F7 `certainty`・timestamp | formatter（必要なら `MemoryItem` に field 追加） | 1 |
| ④ | 理由の連鎖 | surface した記憶の `derived_from`/`supersedes` を 1-hop | typed-edge グラフ・`get_relations` | ambient path での traversal | 2 |
| ⑤ | 矛盾フラグ | surface 記憶（や wave 近傍）の `contradicts` ペア | `contradicts` edge type | tension 検出 | 2 |
| ⑥ | 人格行 | active な declared value/intention 1 行 | Phase J persona machinery（`collect_active_persona_ids`） | persona slot | 3 |

### 重力レンズ枠（②） — GaOTTT 固有の枠

物理アナロジーとして命名する。**重力レンズ**: 質量場が光（クエリ）の経路を曲げ、直線視線上にない天体（記憶）を見せる。raw embedding 的にはクエリから遠いのに、Phase I/J の displacement が場の重力でクエリ近傍まで引き寄せた記憶 = **場が学習した類推**。`virtual_cosine`（displacement 込み）が高く `raw_cosine` が低い、その gap が大きいほど「テキストには無いが場が結びつけた」度合いが強い。

普通の RAG はクエリ類似度でしか引けない。この枠は **学習された重力的連想**で引く — ambient recall を *セレンディピティ・エンジン* にする中核。raw / virtual 両 cosine は既に `score_breakdown` に出ているので計算コストはゼロ。別 `explore` を足さず、同じ recall の候補プール（`top_k≈10`）から選ぶ（レイテンシ維持）。

## サービス / ツールの形

- `core/types.py` — `AmbientRecallRequest`（MCP）/ `AmbientRecallBody`（REST）/ `AmbientRecallResponse`（スロットを構造化フィールドで保持: `direct[]`, `lensing`, `reasoning[]`, `tensions[]`, `persona`）。
- `services/memory.py` — `ambient_recall()`: 内部で `recall(passive=True, top_k=10)` を 1 回 → スロット組み立て → `AmbientRecallResponse`。**passive 必須**（観察者効果、[Guides](Guides-Ambient-Recall.md) 参照）。
- `services/formatters.py` — `format_ambient()`: `<gaottt-ambient-recall>` ブロックの構造化整形。
- `server/mcp_server.py` — 新 MCP ツール `ambient_recall`（薄いラッパ）。`instructions=` 更新。
- `server/app.py` — REST `POST /ambient_recall`（**parity 鉄則**: 同コミットで）。
- `scripts/hooks/ambient_recall.py` — `recall` ではなく新 `ambient_recall` ツールを呼ぶよう差し替え。relevance gate / fail-safe / `os.write` 出力はそのまま。

> 主たる消費者はフックだが、LLM が明示的に `ambient_recall` を呼ぶ用途（「この話題の前提を一括で」）もあるので MCP/REST 両露出は parity 通り妥当。`/reset` のような例外にはしない。

## Stage 構成

| Stage | 対象 | 規模 | 依存 |
|---|---|---|---|
| 1 | 構造化エンベロープ + ①直接ヒット + ②重力レンズ + ③メタ注釈。`ambient_recall()` サービス + `format_ambient` + 新 MCP/REST + フック差し替え | 中 | なし |
| 2 | ④理由の連鎖 + ⑤矛盾フラグ（typed-edge traversal を ambient path に） | 小〜中 | Stage 1 |
| 3 | ⑥人格行 | 小 | Stage 1、Phase J |
| 4 | **語単位 BM25「強一致」gate** — gate 信号を 4 ラウンド校正で確定 | 小 | Stage 1 |

Stage 1 が最も novel（重力レンズ）かつ既存データ再利用のみ。Stage 2/3 は加算的。

### Stage 4 — 語単位 BM25「強一致」gate（2026-05-21、本番校正由来）

当初の relevance gate は「候補プールの最大 `virtual_score`」だった。Stage 1-3 完了後、本番 32k コーパスで gate 信号を **4 ラウンド**校正した:

1. **`virtual_score`（dense cosine）** — ✗ off-topic も on-topic も ~0.6 に集まり温度ノイズ（±0.1）に埋没。`max` でも `max−median` margin でも gap +0.02。32k 規模では無関係クエリでも cosine ~0.65 の最近傍が必ず存在する。
2. **char-3gram BM25 raw** — ✗ クエリ長依存。「映画を3つ教えてください」のような長い off-topic（raw 52）が簡潔な on-topic（49）を上回る。日本語の共通形態素が char-3gram で大量に拾われる。
3. **char-3gram BM25 normalized（raw/語数）** — ✗ 短い 1-token クエリで破綻（「卵焼き」norm 5.0）。
4. **語単位（Sudachi）BM25** — ✓ 「卵焼き」が単一の語トークンになり共通 3-gram の積み増しが消える。off-topic を ≤~29 に抑え込み、強い on-topic は ≥~34。`ambient_bm25_min_score=32.0` で確定。

**核心の発見**: この 32k コーパスはユーザーの生活+仕事まるごとで、真の "off-topic" は存在しない（「卵焼き」も雑談メモに語として実在）。gate が分けられるのは「on/off-topic」ではなく「**強一致 vs 弱一致**」— 高精度・低再現で、その話題を実質的に議論したことがあるプロンプトでだけ発火する。

実装: `config.ambient_gate_tokenizer="sudachi"` の専用 word-level BM25 index（`engine.ambient_gate_index`）を Phase L の char-3gram `bm25_index` とは独立に持つ。startup で全 content から構築、`remember` で逐次追加、`compact` で再構築。`bm25-sudachi` extra 未導入なら構築されず `virtual_score` gate にフォールバック。`virtual_score` は recall *ランキング* の信号としては正しいまま（[[feedback-gate-on-virtual-score]]）— 二値の relevance *gate* は別問題、というのが学び。

## 書き込み側の前提 — ④⑤ が空にならないために

surface できるのは **そう書かれた記憶だけ**。「決定 X を理由 Y で」「X は失敗・撤回」が保存されていなければ ④（理由の連鎖）⑤（矛盾フラグ）は永遠に空。読み取り側と同じ重さで write-side を整える:

- **規約**: `tags=["decision"]` / `tags=["dead-end"]`（新 source class にするか tag 規約にするかは未解決 — 下記）。
- **`auto_remember` 拡張**: 「決定文・撤回文」を抽出するパターンを追加。
- **SKILL.md / CLAUDE.md の保存ガイド** に「決定は理由ごと、失敗は原因ごと、撤回は `supersedes`/`contradicts` エッジごと」を明記（既に一部あり、ambient recall 文脈で補強）。

これは Stage 2 の *価値* の前提だが、Stage 2 の *実装* はブロックしない（エッジが無ければ空スロットを出さないだけ）。並行トラックとして扱う。

## レイテンシ予算

ambient recall は毎ターン発火するため steady-state を守る。Stage 1〜3 すべて **1 回の passive recall（`top_k=10`）+ in-memory グラフ／persona 参照**で構成し、別 `explore` や追加 recall を足さない。目標 steady-state ~0.5–0.7s（現行 passive recall ~0.5s + 構造化のオーバーヘッドは無視可能）。フックの `GAOTTT_AMBIENT_TIMEOUT`（既定 6.0s）は据え置き。

## ロールバック

- スロット単位の config フラグ（`ambient_lensing_enabled` 等）— 個別 off で legacy 挙動。
- フック側 env で `ambient_recall` ツール → 旧 `recall(passive=True)` に戻せる退避路を残す。
- 新ツール追加・既存 `recall` の挙動は不変なので、Stage 1 マージは既存利用を一切壊さない。

## テスト

- `tests/unit/` — 重力レンズの gap 選択（raw/virtual cosine から正しく最大 gap を選ぶ、noise floor 未満は枠を空に）、スロット組み立て。
- `tests/integration/test_engine_ambient_recall.py` — StubEmbedder で `ambient_recall()` サービスの round-trip、各スロットが期待通り埋まる／空く。
- MCP round-trip + `tests/integration/test_rest_parity.py` に `ambient_recall` 追加。
- `scripts/rest_smoke.py` / `scripts/mcp_smoke.py` 両方。
- **live acceptance**: フック経由で本番バックエンドに対し、発端の "niceboat アーキテクチャ" 系クエリを投げ、重力レンズ枠が「テキスト的に遠いが構造的に近い」記憶を拾えているかを目視確認。

## 野心版（v1 の外）— preemptive injection

「私が同じ失敗を *繰り返す前に*」を真にやるには、user prompt ではなく **アシスタントのドラフト回答やツール呼び出し** を query にした recall が要る → `PreToolUse` / `Stop` 等の別フック点。本計画（read-side、user-prompt-triggered）の範囲外。別ドキュメントで起草する。

## 未解決の問い

1. **決定/失敗記憶の表現** — 新 `source` class（`decision`）にするか `tags` 規約か。source 追加は `KNOWN_EDGE_TYPES` 同様に影響範囲が広い。tag 規約が軽いが検索保証が弱い。
2. **重力レンズ枠の noise floor** — gap 最大でも `virtual_score` が低すぎる記憶は単なる外れ値。「gap 最大 *かつ* `virtual_score ≥ floor`」の floor 値は本番コーパスで校正（[Guides](Guides-Ambient-Recall.md) の MIN_SCORE 校正と同様）。
3. **人格行の頻度** — 毎ターンか、N ターンに 1 回か。毎ターンは安定だがトークン定常コスト。
4. **メタ注釈の `age`** — `certainty` は F7 で既出だが `age`（作成/最終アクセスからの経過）を `MemoryItem` に出すか、`ambient_recall` サービス内で算出するか。

## 関連

- [Guides — Ambient Recall](Guides-Ambient-Recall.md) — v1 ambient recall（本計画が拡張する土台）
- [Phase J — Persona-Anchored Retrieval](Plans-Phase-J-Persona-Anchored-Retrieval.md) — ⑥人格行が再利用する persona machinery
- [Phase O — TTT Observability](Plans-Phase-O-TTT-Observability.md) — `score_breakdown`（②が使う raw/virtual cosine の出自）
- [Architecture — Overview](Architecture-Overview.md) — 設計判断表に「ambient_recall = 構造化スロット注入」「重力レンズ枠」を着手時に追記
