# Handover — Save Candidates Hook v1 + v2 (2026-05-27)

> **読者**: 次に save_candidates hook の挙動・heuristic・install pattern を触る Claude / 保守者
> **立場**: 2026-05-27 のセッションで v1 (Claude Code Stop-bridge) と v2 (opencode chat.message plugin) を一気に実装・本番投入・PR #28 化した直後の記録
> **目的**: コード・git log・PR description・[Plans-Save-Candidates-Hook.md](../wiki/Plans-Save-Candidates-Hook.md) からは derive しにくい知見と運用上の罠だけを残す

## 1. 何をしたか（要点）

| 層 | 実装 | 帰着 |
|---|---|---|
| backend | `services/memory.save_candidates()` + formatter + Pydantic | tool 数 26→27、MCP/REST parity |
| Claude Code v1 | Stop hook + UserPromptSubmit-inject の 2 script bridge | per-session state file (`~/.gaottt/save_candidates/<sid>.txt`) |
| opencode v2 | `opencode-save-candidates.ts` (chat.message 1 plugin) + Python に `EMIT=stdout` mode | state file 不要、message text 直接 mutate |
| harness | (A) formatter header line 3 に judgment filter / (C) MCP tool docstring に save filter clause | Articulation as Carrier の **policy 自体への** 自己適用 |
| 罠修正 | `_extract_text` で `type=="text"` 以外 (tool_result/thinking/tool_use) を skip | bash output flood が heuristic を silent 化していたのを解決 |

完成物: PR #28、e8cd1fe、34 files、+1763/-26、733 passed (1 skip)。

## 2. 設計判断で「明示的に書かれていないけれど効いている」3 点

### 2.1 v1 と v2 で **2 hook bridge vs 1 hook collapse** という形状差は CLI 制約の literal な投影
- Claude Code: Stop hook stdout が次 prompt に **auto-inject されない** ので state file が durable bridge として必須
- opencode: `chat.message` で **message text を直接 mutate できる** ので state file 不要、1 plugin で完結
- これは設計選好ではなく、各 CLI が用意した hook surface の literal な反映。codex v3 で codex が `chat.message` 相当を公開したら opencode 設計を 80% 再利用できる、逆に Stop 相当しか無ければ Claude Code 設計を持ち込む

### 2.2 `GAOTTT_SAVE_CANDIDATES_EMIT` は **default `state`** にした (rollback ゼロコスト)
- opencode plugin が新規追加されるだけで、既存 Claude Code 動作は完全に bit-identical
- 1 環境変数の opt-in なので、もし v2 plugin が production で問題を出しても `~/.config/opencode/plugin/gaottt-save-candidates.ts` を消すだけで rollback
- 「設計判断: emit mode は opt-in 環境変数」は [Architecture-Overview の設計判断表](../wiki/Architecture-Overview.md) に同日記載

### 2.3 `opencode-save-candidates.ts` は **MCP client を TS で再実装しない**
- ambient_recall plugin の single-source-of-truth 原則と同じ — Python script を spawn し、MCP call/auth/fail-safe は Python 側 1 箇所のみ
- spawn cost ~0.5s steady を受け入れる代わりに、保守箇所が 2 倍にならない
- 副作用として、save_candidates のロジック更新 (heuristic 改修等) は `save_candidates.py` 1 file の編集だけで両 CLI に伝わる

## 3. Live acceptance で見えた heuristic の挙動

opencode v2 acceptance を secondopinion-MCP / GLM-5.1 で実施し、turn 1 で「Next.js 採用決定」プロンプトを送ったところ、turn 2 の block に 3 件抽出された:

```
1. [score=2.20, source=agent, tags=['design-decision']] **[turn 1 task]**: 以下の決定を 2-3 文で要約してください:
2. [score=2.20, source=agent, tags=['design-decision']] 「Web framework として Next.js を採用することを決定した…」
3. [score=2.20, source=agent, tags=['design-decision']] [assistant] Next.js を Web framework に採用…
```

**観察**:
- meta-instruction (`以下の決定を 2-3 文で要約してください`) が **content と同じ score 2.20** で抽出された — heuristic は「決定/結論キーワード + 数値」を見るので、テスト用のメタ文も literal にマッチしてしまう
- これは false positive ではなく **score gating の粒度が荒い** という Stage 5 refinement の素地。production では agent が判断 filter で skip するので致命傷ではないが、bug fix の途中経過や code snippet を score 0.5 程度に落とせると save 判断の認知負荷がさらに下がる
- 同セッションの実 dogfooding でも `score=0.70` の「数値を含む（メトリクス候補）」 + 「適度な長さ」だけで surface する候補が多く、heuristic の精緻化余地は明確

ToDo.md §8 に Stage 5 として記載 (本ハンドオーバ作成と同時に追記、後述)。

## 4. 運用上の罠 4 点

### 4.1 `tool_result` block 罠 (修正済 + 再発防止 4 regression test)
- Claude Code transcript の `type=user` record は `tool_result` block (bash output / Read 結果) を含む
- 当初 `_extract_text` は `c.get("text") or c.get("content")` の or-fallback で `tool_result.content` を読みに行き、長大な bash output で heuristic を flood → silent fail
- 修正: `c.get("type") != "text"` で skip。`thinking` / `tool_use` も同様
- memory id `0f63bdab` (HOOK-DESIGN-LESSON)。**lesson**: hook script の test は transcript 文字列を直接渡すだけでなく、JSONL 全体を parse する live fixture を入れること

### 4.2 backend (proxy mode HTTP) は **PR merge では更新されない**
- 今回 PR #28 は **backend 内部に新ロジックを追加していない** ので restart 不要 (v1 の MCP tool は今 session 開始前から backend に乗っていた、v2 は完全に client-side の Python script + TS plugin)
- だが将来 `services/memory.save_candidates()` 本体や `auto_remember` を触るときは **`ps -ef | grep streamable-http` で起動時刻が新コミットより古ければ kill** が必要
- memory id `feedback_backend_kill_on_code_deploy`、CLAUDE.md「code deploy 時の backend 再起動」節

### 4.3 opencode plugin install は **copy** (symlink ではない)
- 現在 `~/.config/opencode/plugin/gaottt-save-candidates.ts` は repo の `scripts/hooks/opencode-save-candidates.ts` の **cp された copy**
- repo を更新しても `~/.config/opencode/plugin/` 側は更新されない → 開発中の頻繁更新には `ln -sf` 推奨
- 本番運用 (= 滅多に更新しない) は cp で OK、むしろ symlink を踏むと repo 削除時に dangling になる
- README install snippet は `cp` で書いてある — そのまま使う前提で documented

### 4.4 opencode plugin は **turn 1 で silent** (これは by design)
- `chat.message` が前 turn を look back する設計なので、session の最初の user message では `client.session.messages` に previous assistant message が存在せず exit 0
- これを bug と勘違いしないこと。`GAOTTT_SAVE_CANDIDATES_DEBUG=/tmp/sc.log` で trace 確認すると `skip: no previous exchange (likely first turn)` と出る

## 5. Articulation as Carrier の対称閉合

今回の完成で `Articulation as Carrier` (memory `9a954c62`) の **read 側と write 側の対称な observation lens** が揃った状態になった:

| | read 側 | write 側 |
|---|---|---|
| 機構 | ambient_recall | save_candidates |
| 観察対象 | 既存 memory (過去) | 直前 turn の articulation (現在) |
| Claude Code | UserPromptSubmit hook | Stop + UserPromptSubmit-inject (bridge) |
| opencode | chat.message plugin | chat.message plugin |
| Articulation as Carrier の役割 | "言葉にしたものを再び引っ張る" | "言葉にしたものを保存候補として見せる" |
| physics 層 | recall は重力場を nudge する (Phase I Stage 2) | remember は agent の能動的判断のまま (mass 入口を automate しない) |

**設計の核心**: observation/physics boundary (memory `701e7822`) を **両側で対称に守る**。read で重力場を見ても、write で候補を見ても、いずれも mass の入口は agent が articulate して remember を呼んだ瞬間のみ。lens は両側に automated、physics は両側で manual。

## 6. 次セッションで触ると良いこと（優先度別）

ToDo.md §8 に新規行を追加 (本セッションと同時に commit 予定):

- **🟡 Stage 5 — heuristic refinement (false positive 低減)**: meta-instruction や bug fix 途中経過の score を 0.5 程度に下げる。emotion 語彙 / 訂正 pattern ("実は X だった") / 絶対表現 ("今後は〜") / decision marker ("確定", "採用") の score boost。dogfooding ログ (本セッションでも観察済) からスコア分布を作って閾値を決める
- **🟢 codex v3 — codex CLI hook spec 待ち**: chat.message 相当を codex が公開したら opencode plugin を 80% 再利用、Stop 相当のみなら Claude Code 設計を移植
- **🟢 plugin install pattern**: 開発中の頻繁更新を想定するなら README install snippet を `ln -sf` 推奨に変える。本番用途 (滅多に更新しない) は現状の `cp` のままで OK。どちらに振るかは「v2 plugin の更新頻度」観察待ち

無視して良い (本 PR で完結):
- backend restart (v2 は client-side のみ、PR merge では restart 不要)
- 既存 Claude Code 動作の検証 (default `EMIT=state` で bit-identical、回帰テスト緑)
- Wiki sync (main merge 時に GitHub Action が自動)

## 7. PR / commit pointer

- PR: https://github.com/May-Kirihara/GaOTTT/pull/28
- Commit: `e8cd1fe` `feat(save-candidates): Stop-hook write-side symmetry + opencode plugin v2`
- Plans (SoT): [`docs/wiki/Plans-Save-Candidates-Hook.md`](../wiki/Plans-Save-Candidates-Hook.md) — v1 + v2 両方の完了報告を所持
- 関連 memory id:
  - `9a954c62` Articulation as Carrier
  - `701e7822` Observation vs Physics boundary
  - `93035d35` Save policy (user durable preference)
  - `4d7a2981` Option A inject timing
  - `0f63bdab` Transcript tool_result trap lesson
