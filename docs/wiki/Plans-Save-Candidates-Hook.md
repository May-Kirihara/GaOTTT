# Plans — Save Candidates Hook

> 注: これは physics Phase ではなく [Ambient Recall](Guides-Ambient-Recall.md) の **write-side 対称機能**。Phase レター非消費の独立ドキュメント（[Plans — Ambient Recall Enrichment](Plans-Ambient-Recall-Enrichment.md) と同枠）。
> 状態: **v1 (Claude Code) + v2 (opencode plugin) 完了 (2026-05-27)** — backend service / MCP tool / REST endpoint / Claude Code Stop+UserPromptSubmit bridge / opencode chat.message plugin / 733 tests / live e2e + recursive 確認すべて green。**save-policy harness** ((A) formatter の block header + (C) tool docstring の 2 箇所に判断 filter を articulate) も同日完了。memory id `93035d35` (save-policy)、`4d7a2981` (option A inject timing)、`0f63bdab` (transcript tool_result trap lesson) の 3 件が cycle-3 配当。v3 (codex CLI) は codex の hook spec 成熟待ち。
> 関連: [Plans — Ambient Recall Enrichment](Plans-Ambient-Recall-Enrichment.md), [Plans — Observation Apparatus Refinement](Plans-Observation-Apparatus-Refinement.md), [Guides — Ambient Recall](Guides-Ambient-Recall.md), [MCP Reference — Memory](MCP-Reference-Memory.md), [Architecture — Overview](Architecture-Overview.md)
> 発端: 2026-05-27 のユーザー対話で「auto-remember を perplexity トリガーで?」という問いから派生。perplexity は Messages API で取れない (per-token logprob 非公開) ので、**Stop hook で turn 終了時に `auto_remember` を走らせ候補を `<gaottt-save-candidates>` block として次 prompt に注入** する案に着地。同時に「観測層 (lens) は自動化、physics 層 (`remember` 呼び出し) は能動的判断のまま」という Observation vs Physics boundary（GaOTTT memory id 701e7822）と Articulation as Carrier（id 9a954c62）の整合性が決定要因となった。

## v1 完了報告 (2026-05-27)

実装したもの:
- **backend**: `gaottt/services/memory.save_candidates()` + Pydantic `SaveCandidatesRequest/Body/Response` + `gaottt/services/formatters.format_save_candidates()` (`<gaottt-save-candidates>` block / `(保存候補なし)` sentinel)
- **transport**: MCP tool `save_candidates` (tool 数 26→27) + REST `POST /save_candidates` (parity)
- **hooks**: `scripts/hooks/save_candidates.py` (Stop 側、`auto_remember` を呼び state file に block を書く) + `scripts/hooks/save_candidates_inject.py` (UserPromptSubmit 側、state file 読み → inject → 削除)
- **bridge**: per-session state file (`~/.gaottt/save_candidates/<session_id>.txt`) で Stop event の output を次 turn の UserPromptSubmit にハンドオフ (Claude Code Stop hook stdout は次 prompt に auto-inject されないため必須)
- **tests**: 11 unit + 4 integration + 2 REST parity + 2 MCP round-trip + Tier 1 contract 26→27 + 4 regression (tool_result trap)、計 23 + 既存 706 = 730 passed
- **save-policy harness**: (A) `format_save_candidates` の block header 3 行目に判断 filter 行を inject、(C) `save_candidates` MCP tool docstring に Save filter clause + memory id pointer。**policy 自体を判断の瞬間に articulate** する recursive 適用

## v2 完了報告 (opencode plugin、2026-05-27)

実装したもの:
- **`scripts/hooks/save_candidates.py` 拡張**: `GAOTTT_SAVE_CANDIDATES_EMIT` 環境変数 (default `state` / オプトイン `stdout`) を追加。`stdout` モードでは state file を書かず block を直接 stdout に流す ([opencode-ambient-recall.ts](../../scripts/hooks/opencode-ambient-recall.ts) と同じパターン)。既存 Claude Code パスは default のままなので影響なし
- **opencode plugin `scripts/hooks/opencode-save-candidates.ts`**: `chat.message` hook 1 本で「前ターン (user N-1, assistant N-1) を `client.session.messages` から fetch → `[role] text` 文字列に整形 → `save_candidates.py` を `EMIT=stdout` で spawn → block を current user message の末尾に append」を同期実行。Claude Code の Stop → state-file → UserPromptSubmit-inject の 2 hook chain を、opencode の権限モデル (chat.message から message text を直接編集できる) を活かして **1 hook に潰した** 設計
- **tests**: 既存 11 unit + 新 3 unit (`_EMIT_MODE` parsing / `stdout` writes-to-stdout-not-state / `state` writes-to-state-not-stdout) で計 14 unit + 既存 719 = **733 passed**
- **install path**: グローバルなら `~/.config/opencode/plugin/`、プロジェクトなら `<project>/.opencode/plugin/` に `.ts` を symlink (`ln -s /Path/to/GaOTTT/scripts/hooks/opencode-save-candidates.ts ~/.config/opencode/plugin/`)。opencode 起動時に自動ロード。**`export GAOTTT_REPO=/Path/to/GaOTTT` を shell rc に追加するのが必須** — TS plugin の fallback (`process.env.GAOTTT_REPO ?? "/mnt/holyland/Project/GaOTTT"`) は作者 machine の path が hard-coded されているだけで、他人の machine では env なしでは wrong path で silent fail する

opencode plugin の設計判断:
- **Stop event を待たず chat.message で次ターン開始時に計算** — opencode の plugin hook 一覧で turn-end 相当を持つ確実な API が公式に列挙されていないため、Claude Code の 2-hook bridge を「次ターン chat.message 開始時の lookback」に再投影。UX は完全に同じ (block は新しい user 入力の直前/直後に visible)
- **state file を一切作らない** — opencode は chat.message ハンドラから直接 message text を mutate できるので、Claude Code 用の `~/.gaottt/save_candidates/<session>.txt` ブリッジは不要。バイナリ的に短命
- **Python script を spawn する設計をキープ** (TS で MCP client を再実装しない) — `ambient_recall.ts` と同じ "single source of truth" 原則 ([opencode-ambient-recall.ts:5-21](../../scripts/hooks/opencode-ambient-recall.ts))。MCP call / 認証 / fail-safe ロジックは Python 側 1 箇所のみ

実証されたもの (live Claude Code + recursive 確認):
1. Stop event 発火 → save_candidates.py 起動 → MCP backend で候補抽出 → state file 書き込み ✅
2. UserPromptSubmit 発火 → save_candidates_inject.py 起動 → state file 読み → block を次 prompt に inject → state file 削除 ✅
3. filter 行が block 同じ位置に visible → agent の save 判断が爆速化 (前ターン 1/3 save → 今ターン 0/3 即決) ✅
4. **recursive 動作**: 自分自身の articulation の場で policy が articulate される (Articulation as Carrier の literal 自己適用)

bug を踏んだ + 修正したもの:
- **transcript tool_result trap** (memory `0f63bdab`): Claude Code JSONL の `type=user` record は `tool_result` block (bash output / Read 結果) を含むので naive な extractor は human text と混同して silent fail する。`type=="text"` の明示 filter で修正。regression test 4 件追加。**lesson**: hook script の integration test は transcript 文字列を直接渡すだけでなく、JSONL parse を含めた live transcript fixture が必要

## 背景 — なぜ「auto_remember を手動で呼ぶ」では足りないか

現行 `auto_remember` MCP tool は transcript を渡すと候補を返す純粋関数だが、agent が **能動的に呼ぶ** ことを前提にしている。実運用では:

- agent は ambient_recall（read 側）には毎ターン触れるが、`auto_remember`（write 側）は呼び忘れる
- 重要な決定・撤回・対立を「articulate した瞬間」に保存ガイドが visible でないと、save の意思決定が遅れる / 漏れる
- 結果として ambient recall が surface できる「決定」「失敗」「理由」memory が痩せていく（[Plans — Ambient Recall Enrichment](Plans-Ambient-Recall-Enrichment.md) §「書き込み側の前提」で指摘された symmetric gap）

中核の設計原理: **`auto_remember` を毎 turn 自動 surface するが、`remember` 呼び出しは agent の能動的判断に残す**。observation layer (候補を浮かべる lens) と physics layer (mass の入口 = articulation の volitional moment) の境界を保つ。

## 中核アイデア — Stop hook で turn 終了時に候補を surface

新サービス関数 `services/memory.save_candidates()` が:

1. 直近 transcript（hook 側で抽出）を `auto_remember()` に渡して候補 N 件を得る
2. （optional）active な declared value/intention を 1 件 ambient context として添える
3. **整形済み `<gaottt-save-candidates>` block string** を返す

Stop hook（Claude Code: shell + 既存 Python script を流用、opencode: TS plugin v2）が turn 終了時に発火 → MCP `save_candidates` を呼ぶ → 返ってきた block を **次 prompt 先頭に注入** (`UserPromptSubmit` で stdout、ambient_recall hook と同じ pattern)。

agent は次 turn 開始時に block を読み、「これは save する価値あるか」を判断して `remember` を能動的に呼ぶ。

### option A 採用（option B 不採用）

| 案 | inject タイミング | 採否 |
|---|---|---|
| **A** | turn 終了 hook → **次 prompt 先頭** に block 注入 | ✓ 採用 |
| **B** | turn 終了 hook → **その turn の output 末尾** に block 追加 | ✗ 不採用 |

A 採用の理由（GaOTTT memory id 4d7a2981 に記録済）:

1. **既存 ambient_recall hook と pattern 統一** — harness 側 shim の型が再利用可能（Claude Code stop hook / opencode plugin / codex 将来対応すべて「次 prompt 注入」だけ知ってればよい）
2. **二段 filter** — 判断が 1 turn 遅れる代わりに「次の文脈で見たときにまだ価値があるか」の追加 filter になる。今 surprising でも次 turn で context として消化済みなら save 不要、という volitional moment の保護
3. **observation/physics boundary に整合** — 観測層 (lens で見せる) は自動化、physics 層 (`remember` 呼び出し = mass 入口) は能動的判断のまま。Articulation as Carrier 前提を崩さない

## サービス / ツールの形

- `core/types.py` — `SaveCandidatesRequest` (MCP) / `SaveCandidatesBody` (REST) / `SaveCandidatesResponse` (`candidates: list[AutoRememberCandidate]`, `count: int`, optional `persona_hint: AmbientPersona | None`)。Pydantic 既存型を再利用 (AutoRememberCandidate, AmbientPersona)
- `services/memory.py` — `save_candidates()`: 内部で `auto_remember()` 呼び出し + persona collector (Phase J の `collect_active_persona_ids` 再利用) + emotional/correction 語彙の score boost (v1 は heuristic 据え置き、v2 で精緻化)
- `services/formatters.py` — `format_save_candidates()`: `<gaottt-save-candidates>` block string。`format_ambient` と同型の構造
- `server/mcp_server.py` — 新 MCP tool `save_candidates` (薄いラッパ)。`instructions=` 更新
- `server/app.py` — REST `POST /save_candidates` (**parity 鉄則**: 同コミットで)
- `scripts/hooks/save_candidates.py` — Stop hook 本体 Python script。`scripts/hooks/ambient_recall.py` と同じく Claude Code (`{transcript_path}`) と opencode (`{transcript}`) を payload shape で switching
- `.claude/hooks/stop.sh` — Claude Code から save_candidates.py を呼ぶ shell shim（既存 `.claude/hooks/ambient_recall.sh` と同型）

## Block 形式

```
<gaottt-save-candidates>
GaOTTT が直前ターンから抽出した save 候補です。
（観察層: lens で見せています、save するかは agent の判断）。

▼ 候補 (上位 N 件、score 順)
 1. [score 0.78, suggested_source=agent] 重力レンズ枠は raw/virtual cosine gap で...
    reason: 決定文、絶対表現 ("確定")
 2. [score 0.65, suggested_source=hypothesis] 次回 perplexity トリガーは...
    reason: 仮説文、未来形

▼ いま誰として
 · intention: ... (ambient_recall persona slot と同じ shape)

<!-- save-candidates count=2 -->
</gaottt-save-candidates>
```

候補ゼロのときは sentinel `(保存候補なし)` を返し、hook 側で block タグの有無を見て emit 判断 (ambient_recall と同じ fail-silent pattern)。

## Stage 構成

| Stage | 対象 | 規模 | 依存 |
|---|---|---|---|
| 1 | backend (`save_candidates()` service + MCP/REST tool + formatter) | 中 | なし |
| 2 | Claude Code stop hook (`scripts/hooks/save_candidates.py` + `.claude/hooks/stop.sh`) | 小 | Stage 1 |
| 3 | opencode plugin (`scripts/hooks/opencode-save-candidates.ts`) | 小 | Stage 1, opencode plugin API 調査 |
| 4 | codex 対応 | TBD | codex hook 仕様待ち |
| 5 | 候補抽出 heuristic 精緻化 (emotion 語彙 / 訂正 pattern / 絶対表現 boost) | 小 | Stage 2 dogfooding |

v1 = Stage 1 + Stage 2 (1 PR)。Stage 3-5 は別 PR。

### Stage 1-2 (v1) の実装順 — CLAUDE.md §「実装フロー」準拠

1. `core/types.py` に Pydantic モデル追加
2. `services/memory.py` に `save_candidates()` 追加 (`auto_remember` 内部呼び出し + persona collector)
3. `services/formatters.py` に `format_save_candidates()` 追加
4. `server/mcp_server.py` で MCP tool 公開 + `instructions=` 更新
5. `server/app.py` で REST endpoint 公開 (parity)
6. `scripts/hooks/save_candidates.py` (本体) + `.claude/hooks/stop.sh` (shim)
7. tests (unit / integration / REST parity / MCP smoke)
8. scripts/rest_smoke.py + scripts/mcp_smoke.py 更新
9. docs (SKILL.md / wiki/MCP-Reference-* / wiki/REST-API-Reference.md / wiki/Operations-Server-Setup.md / wiki/_Sidebar.md / wiki/Home.md)

## レイテンシ予算

ambient_recall と同じく毎ターン発火するので steady-state を守る。`auto_remember` 本体は heuristic 抽出 (regex + scoring) で **embedder / FAISS / wave 全部不使用**、~10ms 帯。persona collector は cache 参照のみで <1ms。block formatter <1ms。**目標 steady-state ~50ms 以下**（hook overhead 含む）。`GAOTTT_SAVE_CANDIDATES_TIMEOUT=3.0` を deadline。

ambient_recall (~500ms steady) と直列実行すると合計 ~550ms が UserPromptSubmit / Stop の両 hook で消費されるが、別フェーズで実行 (Stop = turn 終了時、UserPromptSubmit = 次 turn 開始時) なので user 体感の遅延は加算されない。

## ロールバック

- env `GAOTTT_SAVE_CANDIDATES_ENABLED=0` で hook 完全無効化 (default on)
- MCP/REST tool は config flag `save_candidates_enabled=True` (default on) で disable 可
- hook script だけ削除すれば backend は無変更で動く (ambient_recall に影響なし)

## テスト

- `tests/unit/test_save_candidates.py` — formatter の block string shape、persona slot 有無での出力差、候補 0 件で sentinel
- `tests/integration/test_engine_save_candidates.py` — StubEmbedder で `save_candidates()` サービス round-trip、auto_remember 結果が正しく拾われる
- `tests/integration/test_rest_parity.py` に `save_candidates` endpoint round-trip 追加 (httpx.AsyncClient + ASGITransport)
- `tests/integration/test_mcp_tools.py` に MCP round-trip 追加
- `scripts/rest_smoke.py` + `scripts/mcp_smoke.py` 両方で新シナリオ
- **live acceptance**: Claude Code stop hook を有効化し、3-5 turn の dogfooding で実際の候補品質を目視確認。secondopinion-MCP 経由ではなく、Claude Code 本体で（hook 自体の動作確認なので副作用は許容）

## 野心版 (v2 以降)

- **opencode plugin (Stage 3)**: `scripts/hooks/opencode-save-candidates.ts` を `opencode-ambient-recall.ts` ひな型に書く。opencode の Stop / session.message.complete 相当 hook 仕様を調査してから着手
- **codex 対応 (Stage 4)**: OpenAI codex CLI の hook system 成熟待ち。wrapper script (`expect` で stdout boundary 監視) は実装重い割に保守地獄なので不採用。codex が `chat.message` 相当 (incoming user message を mutate できる plugin point) を公開した時点で opencode plugin 設計を 80% 再利用可能
- **heuristic 精緻化 (Stage 5)**: emotion 語彙 / 訂正 pattern ("実は X だった") / 絶対表現 ("今後は〜") / decision marker ("確定", "採用") の score boost。dogfooding ログから false positive / false negative を測ってから着手
- **preemptive injection (別計画)**: 「同じ失敗を繰り返す前に」を真にやるには、agent のドラフト応答や tool 呼び出しを query にした recall が必要。本計画 (Stop hook = post-turn) の範囲外、`PreToolUse` 等の別 hook 点で別ドキュメント

## 未解決の問い

1. **候補数 N** — default 3? 5? ambient_recall の direct_k=2 と揃える? token budget vs surface 率のトレードオフ、dogfooding で決める
2. **重複防止** — 直前 N turn で同じ候補が surface してたら抑止すべきか (ambient_recall の `recently_surfaced` と同型の機構)。v1 はやらない、Stage 5 で検討
3. **persona slot 必要か** — ambient_recall に既に persona slot がある以上、save_candidates block にも persona を出すのは冗長か。dogfooding で判断
4. **score 閾値** — `auto_remember` の score 下限を save_candidates 専用に上げるか (gate を強くして surface 率を下げる)。v1 は据え置き、Stage 5

## 関連

- [Plans — Ambient Recall Enrichment](Plans-Ambient-Recall-Enrichment.md) — read 側、本計画はその write 側 symmetric
- [Plans — Observation Apparatus Refinement](Plans-Observation-Apparatus-Refinement.md) — 観測層のみで physics rule 不変、本計画の設計哲学と同型
- [Guides — Ambient Recall](Guides-Ambient-Recall.md) — hook の fail-safe / 観測者効果の原則、本計画も同じ規律を継承
- [MCP Reference — Memory](MCP-Reference-Memory.md) — `auto_remember` 既存 tool の docs、本計画で `save_candidates` を追加
- [Architecture — Overview](Architecture-Overview.md) — 設計判断表に「observation vs physics boundary を hook 層に適用」を着手時に追記
