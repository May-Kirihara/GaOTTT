# Plans — Observation Apparatus Round 2 (dogfooding review 2026-06-12 起点)

**Status: Stage A-E 実装完了 (2026-06-12 同日)** / branch: `feat/observation-apparatus-round-2` / 実装は secondopinion-MCP (GLM) 委託、Claude Code はレビュー・受け入れ・commit を担当

> **実装記録 (2026-06-12)**: 全 4 バッチ完了 — バッチ 1 (D+B) / 2 (A) / 3 (C) / 4 (E1+E2)。GLM は 2 回 ReadTimeout (~5.5 分壁) で落ちたが、いずれも code 本体は working tree に残っており、残作業 (バッチ 2: テスト一式 / バッチ 4: ヒューリスティック較正 + docs) はレビュー側で補完。**E2 の実装時変更 2 点**: (1) dump score を記号比率単独 → `max(記号比率, 長 ASCII 識別子トークン比率)` に較正 — GLM 自身のテストが「code/state-dict は英字主体で記号比率 0.16 にしかならない」盲点を暴いた。(2) OFF sentinel を `None` → `1.0` に変更 — `float | None = None` default は `GAOTTT_<FIELD>` env 自動マップ対象外 (scalar default のみ env-settable、`config.from_config_file` 参照) のため、E1 と同じ float 規約に統一。最終: 803 unit/integration passed + perf 71 passed + rest/mcp smoke green。

> **Stage E default-ON 昇格 (2026-06-12 同日午後)**: opt-in を `~/.config/gaottt/config.json` で本番反映 (proxy backend の env 継承トラップ回避のため env でなく config.json 経由) → backend kill→respawn で live 化 → MCP 実機評価 (memory id=fa1d03a8) で E1/E2 の意図どおりの分離を確認 (E2: true dump 0.97-1.0 / readable code ≤0.40 / 自然文 <0.05 で 0.45 は clean gap、E1: near-tie で agent source 浮上)。めいさんの「旧 ambient は会話ログ raw chunk 支配で実用性低かった、本番設定値に焼く」判断で **code default を `1.0`(OFF) → `0.5` / `0.45`(ON) に昇格**。redundant になった config.json は削除、single source of truth = code default。legacy 挙動は両 knob を `1.0` で復帰。`docs/wiki/Operations-Tuning.md` / `Guides-Ambient-Recall.md` の default 列更新済み。

## 背景

[Dogfooding レビュー 2026-06-12](../research/dogfooding-review-2026-06-12.md)(セッション復元 + 自由探索の実走) で観測された摩擦 9 件のうち、**physics 起因はゼロ、8 件が観測装置・interface 層の穴**だった。本 plan はその中から費用対効果の高い 4 件 (P1/P2/P4/P6) と、同セッションの hook 注入 3 回分の受け手観察 (後述 §肌感覚) から導いた ambient S/N 改善 2 件を、physics 不変のまま 5 Stage で解決する。

[Observation Apparatus Refinement](Plans-Observation-Apparatus-Refinement.md)(Stage 1-4、2026-05-26) の直接の続編。哲学的判定基準も同一 — **force computation / mass update に source class を入れたら Phase M 単一規則違反、表示・注入層の lens に留めるなら OK**([境界判定の記録](Plans-Observation-Apparatus-Refinement.md))。

## 注入コンテキストの肌感覚レビュー (Stage E の根拠)

2026-06-12 セッションで hook 注入を受け手として 3 回観察 (ambient_recall ×2、save_candidates ×1) した評価:

| 観点 | 評価 | 根拠 |
|---|---|---|
| **分量** | ✅ 適切 | 1 block 20-35 行、slot 上限 (direct 2 / lensing ≤2 / persona 1) が効いており context を圧迫しない。問題は分量ではなく S/N |
| **位置** | ✅ 適切 | UserPromptSubmit 注入 = ターン思考開始前に前提知識が届く正しい位置。save_candidates が「次ターン先頭」なのも、agent が行動できる位置として正しい |
| **文言** | ✅ ほぼ完成形 | 「ユーザーの発話ではなく、参考のための前提知識」「観察層: lens で見せています、save するかは agent の判断」という前置きは認識論的スタンスを正確に設定し、プロジェクト哲学をそのまま体現している。provenance (`source · certainty · age`) も簡潔で有用 |
| **slot 中身の S/N** | ⚠️ ここだけ弱い | 下記 3 点 |

S/N の実測内訳 (3 注入分):

1. **direct hits 6 件中 5 件が chat-history (openai / claude-web) の raw chunk** — state-dict キーのダンプ、無関係なテストコード断片、依頼定型句(「ありがとう！まとめてもらえると嬉しいです」)の lexical 一致。有用だったのは 1 件 (過去の Plans レビュー依頼チャット) のみ。ingest された会話コーパス 14.6k docs が日本語会話文の lexical 空間を支配している構造
2. **persona slot 3 回中 2 回が文脈無関係** (harakiriworks / LMS の高 mass intention) — 既知の [Ambient Persona Mass Dominance](Plans-Ambient-Recall-Refinement.md) 問題、`ambient_persona_mass_weight` knob は導入済み・本番 tuning 未実施 (**2026-07-02 default 昇格で解決済、E3 節参照**)
3. **lensing は 3 slot 中もっとも有用** (exploration report ラウンド 8 を文脈通りに引いた) — ただし resonance は全件 0.00 (claude-code purge 後の共起再蓄積が薄い、観測継続)

結論: **器 (分量・位置・文言) は完成しており、注ぐ中身の選別だけが課題**。これが Stage E。

## Stage 一覧

| Stage | 内容 | 解消摩擦 | 層判定 | 規模 | config default |
|---|---|---|---|---|---|
| A | `get_node` MCP 露出 + SKILL.md mismatch 修正 | レビュー §2.2 | 観測層 ✓ (passive read) | 小 | — (新ツール) |
| B | `reason:` 行を compact/ids/list でも保持 | §2.1, §2.4 | 観測層 ✓ | 極小 | ON |
| C | save_candidates の instruction-surface strip | §2.5 | interface 層 ✓ | 小 | ON (無条件 hygiene) |
| D | `dormant_source_classes` に exploration-report / compaction 追加 | §2.7 | 観測層 ✓ | 極小 | ON |
| E | ambient slot の S/N 改善 (E1 会話 source damping / E2 dump-shape gate / E3 persona tuning) | §肌感覚 | 観測層 ✓ | 中 | **OFF** (knob、measurement-first) |

実装順序の推奨: **D → B → C → A → E**(リスク昇順。D/B は 1 委託にまとめて良い)。

---

## Stage A — `get_node` MCP 露出

### 問題

`reflect(hot_topics)` で id と mass が**見えている**ノードに、recall の言い換え 3 回でも到達できない事象 (lexically 強い chat-history ノードが seed pool を占拠)。anti-hub (pool 内 rerank) では救えない — **pool を迂回する fetch-by-id 経路が存在しない**。

裏取り済みの事実:
- REST `GET /node/{node_id}` は存在する (`server/app.py:271`) が、返すのは**物理状態のみ** (mass/temperature/last_access/sim_history/displacement_norm)。content を返さない
- content は `store.get_document(doc_id)` (`store/base.py:20`) で取得可能
- SKILL.md が `recall(text=..., top_k=1, mode="detail")` という**実装に存在しない引数**を案内している (doc-impl mismatch)

### 実装

1. `core/types.py` — `GetNodeResponse` 追加: `id / content / source / tags / metadata / certainty / emotion / mass / temperature / last_access / displacement_norm`(フィールドは `get_document` の返却 dict と `NodeState` から合成。既存 `NodeResponse` は変更しない)
2. `services/memory.py` — `async def get_node(engine, node_id) -> GetNodeResponse | None`。**read-only by construction**: `store.get_document` + `engine.cache.get_node` + `engine.get_displacement_norm` の合成のみ。mass update / co-occurrence / displacement 一切なし (`_dormant_surface` と同じ passive 原則)。archived ノードは None (REST 404 と同じ扱い)
3. `services/formatters.py` — `format_node_detail`: full content + provenance 行 + 物理状態 1 行。**既存 formatter の出力行は変更しない**(追加のみ)
4. `server/mcp_server.py` — ツール `get_node(node_id: str)` 追加 (薄いラッパ)。**27 → 28 tools**: `instructions=` 文字列更新
5. `server/app.py` — `GET /node/{node_id}` の `NodeResponse` を**追加フィールドで拡張**するのではなく、`GET /node/{node_id}/detail` を新設して `GetNodeResponse` を返す (既存 `/node` の shape・既存テスト・visualize 系 consumer を一切触らないため)。parity 鉄則: MCP ツールと同じ commit で
6. SKILL.md **両方** (`SKILL.md` + `.claude/skills/gaottt/SKILL.md` に cp) — `get_node` 節追加、`recall(text=...)` 記述を `get_node(node_id=...)` に修正、「27 MCP tools」→ 28
7. Wiki: `MCP-Reference-Memory.md` に仕様、`MCP-Reference-Index.md` に行 + ツール選択フロー (「id が分かっている → get_node」分岐)、`REST-API-Reference.md` に `/node/{id}/detail` 行
8. `CLAUDE.md` / `README.md` / `README_ja.md` の「27 ツール」表記を 28 に更新

### テスト

- unit: service `get_node` (存在 / 不在 / archived)
- integration: MCP round-trip (`test_mcp_tools.py` 形式)、**get_node 前後で対象ノードの mass / displacement が不変**であることの assert (passive 検証)
- `test_rest_parity.py`: `/node/{id}/detail` round-trip
- `tests/perf/` Tier 1: **ツール数 assert が 27 のままなら 28 に更新**(grep `27` で確認)

### 受け入れ

`reflect(hot_topics)` で見えた id を `get_node` に渡して content が返る。`scripts/rest_smoke.py` + `scripts/mcp_smoke.py` 両 green。

---

## Stage B — `reason:` 行を全 output_mode に

### 問題

dominance が一番起きやすい triage 場面 (`output_mode="compact"`/`"ids"`) で、まさに dominance を警告する `reason: high mass persona proximity — possible dominance artifact` が `recall_trailer_verbose_modes` の token 経済設計に巻き込まれて消えている。breakdown (複数行) と訓練差分 (trailer) を落とすのは正しいが、reason は 1 行で診断価値が突出して高い。

### 実装

1. `config.py` — `recall_reason_line_modes: tuple[str, ...]` を新設、default は**全 mode**(`("full", "detail", "compact", "ids", "list")`)。既存 `recall_trailer_verbose_modes` は breakdown / trailer 専用として不変
2. `services/formatters.py`(+ 必要なら `services/memory.py` の mode 分岐) — reason 行の emit 条件を新 config に付け替え。compact/ids への追加は**行の追加**であり既存行の書式変更ではない (formatter 鉄則整合)
3. Wiki: `Operations-Tuning.md` に新ハイパラ行、`Plans-Observation-Apparatus-Refinement.md` に Stage 1 拡張の追記

### テスト

- 既存の compact/ids substring テストが green のまま (追加行は既存 assert を壊さない)
- 新規: compact 出力に `reason:` が含まれる assert / config で空 tuple にすると消える assert

---

## Stage C — save_candidates の instruction-surface strip

### 問題

save 候補 top1 (score=4.40, source=user 扱い) が、**Skill ツールが注入した SKILL.md 本文の断片**だった。`<gaottt-*>` block・skill 注入・system-reminder はユーザー発話でも agent 発話でもない instruction surface であり、候補抽出の入力に入ってはならない。[Instruction Surface Hygiene](Plans-Instruction-Surface-Hygiene.md) S0-S4 の直接の続き。

### 実装

1. `scripts/hooks/` の transcript reader (save_candidates.py が使う共通読み出し層 — Claude Code .jsonl / opencode / Codex rollout の 3 形式すべてが通る箇所) に strip 関数を追加:
   - `<gaottt-ambient-recall>…</gaottt-ambient-recall>` / `<gaottt-save-candidates>…</gaottt-save-candidates>` block
   - `<system-reminder>…</system-reminder>` block
   - skill 注入 turn (Claude Code では「Base directory for this skill:」で始まる user turn、等 — 3 frontend の形式差は実装時に transcript 実物で確認)
2. 無条件適用 (knob 不要 — 注入テキストが候補になる正しいケースは存在しない)。frontend parity: backend script 1 箇所の修正で 3 frontend に効く
3. Wiki: `Plans-Save-Candidates-Hook.md` に追記、`Guides-Ambient-Recall.md` の該当節

### テスト

- unit: strip 関数 (block 除去 / 通常テキスト不変 / block が複数・入れ子風の場合)
- 既存の save_candidates atomic テスト群が green のまま

---

## Stage D — `dormant_source_classes` 拡張

### 問題

`dormant_source_classes = ("agent", "value", "intention", "commitment", "note", "reference")`(`config.py:746`)。exploration-report / compaction は「self-authored で低頻度アクセス」の典型 — 2026-06-12 の最大の発見素材 (十柱レポート) は dormant 経路では構造的に永遠に出なかった。

### 実装

1. `config.py` の tuple に `"exploration-report"`, `"compaction"` を追加。コメントに根拠 (percentile 昇格時と同じ: *dormant surfacing is an observation-layer filter, not a force/mass rule*)
2. Wiki: `Operations-Tuning.md` の該当行更新

### テスト

- unit: dormant 対象 source set の assert 更新
- 本番 acceptance (任意): `explore(mode="dormant")` 数回で exploration-report が混ざることの目視

---

## Stage E — ambient slot の S/N 改善 (knob、default OFF)

### 哲学境界の確認

ambient_recall の slot 選択は `exclude_tags` / novelty decay / `ambient_persona_min_relevance` と同じ**観測・注入層**。source class をここで重み付けしても force/mass update には一切入らない (= Phase M 単一規則不変)。ただし [No source branching](Plans-Observation-Apparatus-Refinement.md) の精神に従い、**default OFF の knob として導入し、1-2 週の本番観測で効果を測ってから opt-in する**(Stage 7 anti-hub と同じ rollout パターン)。

### E1 — 会話 source damping

- `config.py`: `ambient_conversational_source_factor: float = 1.0`(1.0 = OFF)、`ambient_conversational_sources: tuple[str, ...] = ("openai", "claude-web", "claude-code")`
- `services/memory.py` の ambient slot ranking (direct / lensing 候補スコア) に `score *= factor if source in conversational_sources`。**recall 本体には触れない**(ambient_recall 専用パス)
- 推奨初期値 0.5、env `GAOTTT_AMBIENT_CONVERSATIONAL_SOURCE_FACTOR` で claude.json / opencode.json に opt-in 登録

### E2 — dump-shape gate

- `config.py`: `ambient_dump_symbol_ratio: float = 1.0`(>= 1.0 = OFF — 実装時変更: None default は GAOTTT_* env 自動マップ対象外 [scalar default のみ env-settable] のため、E1 と同じ float 規約に統一)
- ambient slot 候補の content 先頭 N 文字の記号・識別子比率 (非和文・非英単語文字の割合) が閾値超なら slot から skip (state-dict キー羅列、生コード断片を注入しない)。実装は軽量 heuristic で良い (正規表現 1 本 + 比率計算)。落とした候補は次点繰り上げ
- 推奨初期値 0.45 (実装時に手元の dump 実例 — apitest / residual_layer chunk — で較正)

### E3 — persona slot tuning (2026-07-02 default 昇格で解決)

当初の計画: `ambient_persona_mass_weight`(導入済み knob) の本番 tuning を measurement-first で実施 — `scripts/compare_retrieval.py` で代表 query 10 本の persona slot を weight 0.0 / 0.5 / 1.0 で比較 → 1 週間観測 → 値確定。

**実績 (2026-07-02)**: measurement-first の形式は踏まず、env opt-in で w=0.3 を運用した**本番体感** (ユーザーが「毎回 harakiriworks に関連付けられる」と申告、症状継続) を最優先して default 昇格を決定。env 単独の w=0.3 では dense 日本語 embeddings の cos≈0.52 が旧 `min_relevance=0.5` floor を slip して症状が継続したため、`ambient_persona_mass_weight: 1.0→0.3` と `ambient_persona_min_relevance: 0.5→0.65` の **両 knob を同時に code default 化**。詳細・テスト・measurement-first skip の開示は [Plans — Ambient Recall Refinement](Plans-Ambient-Recall-Refinement.md) 「Follow-up (b) follow-through — 2026-07-02 default 昇格」節。事後 baseline 測定を推奨 (ToDo 6-7)。

### テスト

- unit: E1 factor 適用の有無で slot 順位が変わる / 1.0 で bit-exact に legacy 一致。E2 dump 判定 (日本語文 / 英文 / state-dict 羅列 / コード断片のフィクスチャ)
- integration: ambient_recall round-trip で OFF 時に既存出力不変
- `tests/perf/` Tier 3 (quality) 手動実行で regression なし確認

### ロールアウト

code merge (OFF) → env opt-in で 1-2 週 dogfooding (Lateral Association observation 期間と合流可) → 効果あれば code default 昇格を別途判断 (Phase Q governor の昇格と同じ 2 段階)。**→ 実績 (2026-06-12)**: config.json opt-in → 同日の MCP 実機評価で効果確認 → `0.5`/`0.45` を code default に昇格 (上記実装記録の Stage E default-ON 節)。dogfooding 期間は短縮されたが、評価が production の実 surfaced content に対する直接 measurement だったため判断材料は十分と判断。

---

## 委託ワークフロー (secondopinion-MCP)

実装は `mcp__secondopinion__delegate_task`(provider=glm) に Stage 単位で委託、Claude Code は packet 作成・diff レビュー・テスト/スモーク実行・docs 整合確認・commit を担当する。

### バッチ構成

| バッチ | Stage | 委託の独立性 |
|---|---|---|
| 1 | D + B | config + formatter のみ、依存なし。最初に流して委託ループの調子を見る |
| 2 | A | 本丸。types → service → formatter → MCP + REST 同 commit → SKILL.md ×2 → docs。packet にはレビュー §2.2 の裏取り事実 (NodeResponse が content を持たない / get_document の存在 / `/detail` 新設方針) を明記 |
| 3 | C | hook 層。transcript 3 形式の実物パス (`~/.claude/projects/...` 等) を packet に含め、フィクスチャで検証させる |
| 4 | E1 + E2 | ambient 専用パス。「recall 本体に触れない」「1.0 / None で bit-exact legacy」を acceptance に明記 |

### packet に必ず含める制約 (全バッチ共通)

- **uv 使用、pip 禁止**。pytest は `.venv/bin/python -m pytest tests/ -q`、lint は `ruff check gaottt/ tests/`
- **MCP と REST は同 commit で parity**(Stage A)。formatter は**既存行の書式変更禁止・追加のみ**。MCP 新引数は optional のみ
- 新 config は **DEFAULT 付き**で既存 DB / 既存呼び出しを壊さない
- 終了報告は「変更ファイル一覧 + テスト結果 (pass/fail 数) + 設計判断 3 行以内」の summary のみ (生 diff 貼らない — Claude Code 側 context 保護)
- 完了後 Claude Code 側で: diff レビュー → `pytest tests/ -q` → `rest_smoke.py` + `mcp_smoke.py` → 該当 Tier の `tests/perf/` 手動実行 → docs チェックリスト → commit

### 受け入れ (plan 全体)

1. 全 suite green + smoke 両 green + perf Tier 1/3 手動 green
2. Stage A: 本番 DB read-only で hot_topics の id → `get_node` → content 取得を実証 (secondopinion 経由の acceptance、backend kill ルール適用)
3. Stage E: OFF 状態で本番挙動 bit-exact、opt-in 後 1-2 週の ambient block 体感を dogfooding メモに記録
4. ドキュメント更新チェックリスト (CLAUDE.md 記載の 13 項目) 消化

## 見送り・後続 (本 plan のスコープ外)

- **P3** hot_topics の bucket 化 — Stage E1/E2 で ambient 側の S/N が上がった後、同型 pattern を reflect 側に展開するか判断
- **P5** ambient BM25 gate の会話定型句 damping — E1 (source damping) が同じ症状のより安い対処である可能性が高い。E1 の観測結果を見てから
- **P7** session-restore routing hint — lens として有効だが、auto-route 周りの設計と合わせて別 plan
- **P8** explore の passive default 化 — **physics に触る哲学議論** (「触れたものが重くなる」は設計の核)。当面は SKILL.md の運用規律 (言い換え連打は `passive=true`) で対処し、デフォルト変更はめいさんと議論
- **P9** resonance 無発火 — 改善ではなく観測 (`diag_assoc_halo.py` 定点)
