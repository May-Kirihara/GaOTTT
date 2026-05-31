# 🌱 はじめての GaOTTT (3/6) — AI クライアントに接続

GaOTTT はパソコンに入りました。次は、あなたが使っている **AI クライアント** に「GaOTTT を使ってね」と教えます。

← [前: Install](Tutorial-02-Install-GaOTTT.md) ｜ → [次: First Conversation](Tutorial-04-First-Conversation.md)

---

## どのクライアントを使いますか？

GaOTTT は **MCP (Model Context Protocol)** を話すので、MCP 対応クライアントならどれでも繋げられます。自分が使うものの節まで飛んでください：

| クライアント | こんな方に | セクション |
|---|---|---|
| **Claude Desktop** | Claude を普段のデスクトップアプリで使っている | [A. Claude Desktop](#a-claude-desktop) |
| **Claude Code** | CLI でコーディングエージェントとして使っている | [B. Claude Code](#b-claude-code) |
| **OpenCode** | `opencode` で OSS なコーディング CLI を使っている | [C. OpenCode](#c-opencode) |
| **OpenClaw** | メッセージング経由のパーソナル AI アシスタント | [D. OpenClaw](#d-openclaw) |
| **Codex CLI** | OpenAI の `codex` CLI でコーディングエージェントを使っている | [E. Codex CLI](#e-codex-cli) |

迷ったら **Claude Desktop** が一番セットアップが簡単です。

---

## 共通の準備: 自分のユーザー名だけ控える

Tutorial-02 の手順どおり進めていれば、GaOTTT は **`~/GaOTTT`**（=ホームディレクトリ直下）に入っています。なので **Python のフルパスは決まっています**:

| OS | Python のフルパス |
|---|---|
| **macOS** | `/Users/あなたのユーザー名/GaOTTT/.venv/bin/python` |
| **Linux** | `/home/あなたのユーザー名/GaOTTT/.venv/bin/python` |
| **Windows** | `C:\Users\あなたのユーザー名\GaOTTT\.venv\Scripts\python.exe` |

`あなたのユーザー名` の部分だけ、ターミナルで `whoami` の出力に置き換えてください:

```bash
whoami
```

例: `taro` と出たら、上の表の `あなたのユーザー名` を `taro` に置き換えます。

> 💡 シェルから直接実行できる場合（Claude Code / OpenClaw / Codex CLI など）は `$HOME/GaOTTT/...` と書けばユーザー名を埋めなくても通ります（シェルがホームディレクトリに自動展開してくれます）。**JSON / TOML 設定ファイルでは展開してくれない** のでフルパスが必要。
>
> 💡 **Windows で JSON に書くときの注意**: `\` は JSON では `\\`（バックスラッシュ 2 つ）に書きます。例: `C:\\Users\\taro\\GaOTTT\\.venv\\Scripts\\python.exe`

---

## A. Claude Desktop

### 1. Claude Desktop を完全に終了

- Mac: `Cmd + Q`（赤いボタンで閉じるだけだとまだ動いています）
- Windows: タスクバーの Claude を右クリック → 「閉じる」

### 2. 設定ファイルを開く

**Mac**: ターミナルで

```bash
open ~/Library/Application\ Support/Claude/
```

**Windows**: エクスプローラーのアドレスバーに

```
%APPDATA%\Claude
```

`claude_desktop_config.json` を **テキストエディタ** で開きます（Mac はテキストエディット、Windows はメモ帳）。ファイルが無ければ新規作成。

### 3. 設定を書く

ファイルが空、または `{}` だけなら、以下を貼り付けて **`あなたのユーザー名` の部分だけ `whoami` の出力に置き換え** ます。

**macOS**:

```json
{
  "mcpServers": {
    "gaottt": {
      "command": "/Users/あなたのユーザー名/GaOTTT/.venv/bin/python",
      "args": ["-m", "gaottt.server.mcp_server"]
    }
  }
}
```

**Windows**（バックスラッシュは JSON では `\\` と 2 つ重ねる）:

```json
{
  "mcpServers": {
    "gaottt": {
      "command": "C:\\Users\\あなたのユーザー名\\GaOTTT\\.venv\\Scripts\\python.exe",
      "args": ["-m", "gaottt.server.mcp_server"]
    }
  }
}
```

すでに `mcpServers` があるなら、その中に `gaottt` の項目だけ追加してください（カンマの位置に注意）。保存したら **Claude Desktop を起動**。

### 成功の目印 ✅

入力欄の左下に **小さなハンマー🔨アイコン**（または「ツール」表示）が出ていて、クリックすると `gaottt` の名前と `remember` / `recall` など 27 個のツールが並びます。

→ [ステップ 6: 動作確認](#-ステップ-6-ai-に話しかけて確認) に飛ぶ

---

## B. Claude Code

Claude Code は CLI から MCP サーバーを登録できます。**Claude Code 起動中でも OK**。

### 登録コマンド（macOS / Linux）

```bash
claude mcp add gaottt -- "$HOME/GaOTTT/.venv/bin/python" -m gaottt.server.mcp_server
```

### 登録コマンド（Windows PowerShell）

```powershell
claude mcp add gaottt -- "$HOME\GaOTTT\.venv\Scripts\python.exe" -m gaottt.server.mcp_server
```

### スコープを選びたい場合

- **プロジェクトローカル**（デフォルト）: 現在のディレクトリだけで有効
- **ユーザー全体**: `--scope user` を足すと、どのフォルダで起動しても有効

```bash
claude mcp add --scope user gaottt -- "$HOME/GaOTTT/.venv/bin/python" -m gaottt.server.mcp_server
```

### 確認

```bash
claude mcp list
```

`gaottt` が出ていれば成功。Claude Code を起動したあと、プロンプトで `/mcp` と打つと接続状況を確認できます。

→ [ステップ 6: 動作確認](#-ステップ-6-ai-に話しかけて確認) に飛ぶ

---

## C. OpenCode

OpenCode (https://opencode.ai) は `opencode.json` （または `opencode.jsonc`）を編集します。

### 1. 設定ファイルを開く

**プロジェクトごとに使う** なら作業フォルダの `opencode.json`。**どこでも使う** なら:

- macOS / Linux: `~/.config/opencode/opencode.json`
- Windows: `%APPDATA%\opencode\opencode.json`

ファイルが無ければ新規作成。

### 2. `mcp` セクションを書く

**macOS / Linux**（`/Users/...` か `/home/...` を自分の OS に合わせる）:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "gaottt": {
      "type": "local",
      "command": ["/Users/あなたのユーザー名/GaOTTT/.venv/bin/python", "-m", "gaottt.server.mcp_server"],
      "enabled": true
    }
  }
}
```

**Windows**（`\\` で 2 つ重ねるのを忘れずに）:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "gaottt": {
      "type": "local",
      "command": ["C:\\Users\\あなたのユーザー名\\GaOTTT\\.venv\\Scripts\\python.exe", "-m", "gaottt.server.mcp_server"],
      "enabled": true
    }
  }
}
```

保存したら OpenCode を起動（または再起動）。

### 成功の目印 ✅

OpenCode の TUI で `/mcp` や `/tools` でツール一覧を見たとき、`gaottt` の 27 個のツールが見えていれば成功。

> 💡 **GaOTTT のデータは「どこに」保存される？**
> OpenCode の設定には `cwd` がありませんが、GaOTTT は自動で `~/.local/share/gaottt/` (Linux/macOS) または `%LOCALAPPDATA%\gaottt\` (Windows) にデータを作ります。別の場所に置きたければ `"environment": {"GAOTTT_DATA_DIR": "/your/path"}` を同セクションに追加してください。

→ [ステップ 6: 動作確認](#-ステップ-6-ai-に話しかけて確認) に飛ぶ

---

## D. OpenClaw

OpenClaw (https://github.com/openclaw/openclaw) では **2 つ** セットアップします。MCP 登録で「ツールを呼べる」ようにして、Skill 配置で「いつ・どう呼ぶか」を読ませる形です。

### 1. MCP サーバーを登録

ターミナルで:

**macOS / Linux**

```bash
openclaw mcp set gaottt '{"command":"'"$HOME"'/GaOTTT/.venv/bin/python","args":["-m","gaottt.server.mcp_server"]}'
```

**Windows PowerShell**

```powershell
openclaw mcp set gaottt "{`"command`":`"$HOME\GaOTTT\.venv\Scripts\python.exe`",`"args`":[`"-m`",`"gaottt.server.mcp_server`"]}"
```

登録できたか確認:

```bash
openclaw mcp list
```

`gaottt` が出ていれば OK。これで `~/.openclaw/config.json` の `mcp.servers.gaottt` に書き込まれます。

### 2. SKILL.md を配置（推奨）

OpenClaw は SKILL.md を読んで「GaOTTT をどう使うか」を理解します。GaOTTT リポジトリの `SKILL.md` を OpenClaw のスキルフォルダにコピー:

**macOS / Linux**

```bash
mkdir -p ~/.openclaw/skills/gaottt
cp ~/GaOTTT/SKILL.md ~/.openclaw/skills/gaottt/SKILL.md
```

**Windows PowerShell**

```powershell
New-Item -ItemType Directory -Force -Path "$HOME\.openclaw\skills\gaottt"
Copy-Item "$HOME\GaOTTT\SKILL.md" "$HOME\.openclaw\skills\gaottt\SKILL.md"
```

OpenClaw はセッション開始時にスキルをスキャンするので、**コピー後にエージェントを再起動** してください。

### 成功の目印 ✅

OpenClaw エージェントに「GaOTTT のツール使える？」と聞いて、`remember` / `recall` などが呼べる応答が返れば成功。

→ 次のステップへ

---

## E. Codex CLI

OpenAI Codex CLI (https://github.com/openai/codex) は `~/.codex/config.toml`（または プロジェクト直下の `.codex/config.toml`）の `[mcp_servers.<name>]` セクションで MCP サーバーを登録します。CLI からワンライナーで追加するか、設定ファイルを直接編集するか、どちらも可能。

### 方法 1: `codex mcp add`（推奨、ワンライナー）

**macOS / Linux**

```bash
codex mcp add gaottt -- "$HOME/GaOTTT/.venv/bin/python" -m gaottt.server.mcp_server
```

**Windows PowerShell**

```powershell
codex mcp add gaottt -- "$HOME\GaOTTT\.venv\Scripts\python.exe" -m gaottt.server.mcp_server
```

### 方法 2: `~/.codex/config.toml` を直接編集

`~/.codex/config.toml` を開いて、自分の OS に合わせて追記（`あなたのユーザー名` を `whoami` の出力に置き換え）:

**macOS**:

```toml
[mcp_servers.gaottt]
command = "/Users/あなたのユーザー名/GaOTTT/.venv/bin/python"
args = ["-m", "gaottt.server.mcp_server"]
# データを別の場所に置きたい場合だけ:
# env = { GAOTTT_DATA_DIR = "/your/path" }
# 初回起動で RURI モデルロードに ~30s 掛かるので default の 10s では足りない場合:
# startup_timeout_sec = 60
```

**Linux**: 上の `/Users/` を `/home/` に置き換えるだけ。

**Windows**: TOML では Windows パスの `\` をエスケープせず `'...'`（シングルクォート）で囲んで `'C:\Users\あなたのユーザー名\GaOTTT\.venv\Scripts\python.exe'` と書けます。

保存したら Codex CLI を再起動。

### 3. SKILL.md の取り扱い（推奨）

GaOTTT の `SKILL.md`（「いつ・どう gaottt ツールを呼ぶか」のプロトコル仕様）は **MCP の `instructions` フィールド経由でランタイムに自動配信されます** — Claude Code / Claude Desktop / OpenCode と同じ仕組みで、Codex CLI 側でも追加配置なしで読まれます。

Codex CLI の **AGENTS.md** 経由で常時文脈に乗せたい（プロンプトレベルで強く意識させたい）場合は、以下のどちらか:

**(a) リポジトリ単位で読ませる** — GaOTTT を呼ぶプロジェクトの直下に `AGENTS.md` を置き、SKILL.md を参照:

```bash
cat > AGENTS.md <<'EOF'
# Agent Instructions

このリポジトリで作業する際は、長期記憶 MCP server `gaottt` を活用してください。
プロトコル仕様: ~/GaOTTT/SKILL.md
EOF
```

**(b) グローバルに読ませる** — `~/.codex/AGENTS.md` に追記（既存内容を保ったまま、末尾に GaOTTT セクションを足す）:

```bash
cat >> ~/.codex/AGENTS.md <<'EOF'

## GaOTTT (long-term memory)

If the gaottt MCP server is connected, use it as long-term memory across sessions.
Protocol spec: ~/GaOTTT/SKILL.md
EOF
```

> 💡 `AGENTS.override.md` を使うとオリジナルの `AGENTS.md` を残したまま上書きできます。Codex CLI は global → project ルート → cwd の順に concatenate するので、project の AGENTS.md は global を補強する形で書けます。

### 4. Ambient Recall / 自動保存フック（任意・推奨）

Claude Code / OpenCode と同じ **ambient recall（読み側）+ save candidates（書き側）の自動ループ** を Codex CLI でも使えます。Codex は [hooks](https://developers.openai.com/codex/hooks) という仕組み（Claude Code とほぼ同じイベント体系）を持っていて、`~/.codex/hooks.json`（グローバル）または `<repo>/.codex/hooks.json`（プロジェクト単位）で登録します。

- **`UserPromptSubmit`** → `ambient_recall.py --codex`：毎ターンの発話を見て、関連する長期記憶を `<gaottt-ambient-recall>` ブロックとして文脈に自動注入（passive・非破壊）。
- **`UserPromptSubmit`** → `save_candidates_inject.py --codex`：前ターンに抽出した保存候補を `<gaottt-save-candidates>` ブロックとして提示。
- **`Stop`** → `save_candidates.py`：ターン終了時に直近のやりとりを heuristic で走査し、保存候補を per-session state file に書く（次ターンの inject 側が読む）。

> 💡 **Codex と Claude Code の唯一の差** は出力形式です。Claude Code は hook の raw stdout をそのまま文脈に注入しますが、Codex は **JSON エンベロープ**（`{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ...}}`）を読みます。`--codex` フラグ（または `GAOTTT_HOOK_OUTPUT=codex`）がこのエンベロープ形式に切り替えます。transcript の読み取りも Codex の rollout JSONL（`event_msg` / `user_message`）に対応済みなので、マルチターン履歴もそのまま効きます。

同梱の `.codex/hooks.json` は README と同じ `$HOME/GaOTTT` 規約（GaOTTT を**ホーム直下に clone**: `git clone … && cd GaOTTT`）でパスを書いてあります。**この規約に従えば書き換えなしでそのまま使えます**。別パスに clone した場合は、雛形内の 2 つの `$HOME/GaOTTT` を実際の repo パスに置換してから `~/.codex/hooks.json` にコピーしてください（下記 `sed` 例）。Codex は command を shlex で分解するだけで `$HOME` を展開しないため、各 hook は `sh -c '…'` 経由で起動してシェルに展開させています。

**インストール（グローバル、全プロジェクトで有効）**:

```bash
mkdir -p ~/.codex
cp "$HOME/GaOTTT/.codex/hooks.json" ~/.codex/hooks.json
```

> ⚠️ **`$HOME/GaOTTT` 以外に clone した場合**: 雛形内のパスを置換してからコピーしてください:
> ```bash
> sed 's#\$HOME/GaOTTT#/your/actual/path/to/GaOTTT#g' .codex/hooks.json > ~/.codex/hooks.json
> ```

**inject hook の推奨 timeout は 2s**（state file を 1 回 read するだけなので 5s は過大です。同梱雛形は既に 2s に設定済み）。

**プロジェクト単位だけで良い場合** は、GaOTTT を呼ぶプロジェクトの直下に同じ `.codex/hooks.json` を置くだけ（GaOTTT repo 内で codex を動かすなら同梱の雛形がそのまま効きます）。

> 💡 **Windows**: `sh -c '…'` が使えないので、各 `command` を絶対パス形式（`"C:\Users\<name>\GaOTTT\.venv\Scripts\python.exe" "C:\Users\<name>\GaOTTT\scripts\hooks\ambient_recall.py" --codex`、TOML なら `commandWindows` フィールド）に置き換えてください。

保存したら **Codex CLI 内で `/hooks` を実行して、各 hook 定義を確認 → trust** してください（Codex は未信頼の command hook を実行しません）。`[features]` で hooks を無効化していなければ（default 有効）これで動きます。

> ⚠️ hooks は MCP backend（proxy mode の port 7878）に接続して動きます。上の **1./2. で gaottt を MCP server として登録済み**であれば、最初の Codex セッションで backend が自動起動するので追加作業は不要です。backend が落ちている/遅いときは hook は黙って何も注入せず、発話をブロックすることは決してありません（fail-safe）。

**無効化**: `GAOTTT_AMBIENT_RECALL=0`（読み側）/ `GAOTTT_SAVE_CANDIDATES_ENABLED=0`（書き側）を hook の `command` に付けるか、`~/.codex/hooks.json` から該当エントリを消すだけ。チューニング用 env は [Operations — Tuning](Operations-Tuning.md) と各 hook スクリプト冒頭の docstring を参照。

### 成功の目印 ✅

Codex CLI のセッション内で MCP ツール一覧（`/tools` 等）を見たとき、`gaottt` の 27 個のツール（`remember`, `recall`, ...）が見えていれば成功。あるいは「gaottt の `reflect` を aspect=summary で呼んで」と頼んで結果が返ればOK。

フックを入れた場合は、**12 文字以上の発話を 1 回送って**みて、関連記憶があれば `<gaottt-ambient-recall>` ブロックが文脈に乗る（Codex の UI 上は developer context として現れる）こと、ターンを終えると次の発話で `<gaottt-save-candidates>` が出ることを確認できれば OK。

> 💡 **proxy mode について**: GaOTTT の MCP サーバーは default で proxy mode（軽量 stdio shim → HTTP backend）で動くので、Claude Code / OpenCode 等と **同じ backend プロセス（port 7878）を共有** します。N 個のエージェントで合計 ~3-4 GB の RAM が 1 backend で済む仕組み。詳細は [Operations — Server Setup](Operations-Server-Setup.md) 「起動モード」節。

→ [ステップ 6: 動作確認](#-ステップ-6-ai-に話しかけて確認) に飛ぶ

---

## 🎯 ステップ 6: AI に話しかけて確認

（どのクライアントでも共通）入力欄にこう入力してみてください:

```
GaOTTT memory が使えるか確認したいので、reflect ツールを aspect="summary" で呼んでみてもらえる？
```

### こう見えたら成功 ✅

エージェントが `reflect` ツールを呼んで、こんな感じの結果を返します:

```
Memory Summary:
  Total memories: 0
  Active (mass > 1): 0
  Displaced by gravity: 0
  Co-occurrence edges: 0
  Sources: {}
```

最初は何も入ってないので **0 ばかり** で正解です。
**これであなたの AI と GaOTTT が繋がりました** 🎉

### ツールが呼べない / 🔨 が出ない場合

- クライアントを **完全終了** してから起動し直す（Claude Desktop は `Cmd + Q`、他は TUI を抜けてから再起動）
- 設定ファイルの JSON 構文をチェック（カンマの位置、ダブルクォート、波括弧）
- Python のフルパスが合っているか（`whoami` / `echo $HOME` で出た名前・パスで書けてるか）
- `.venv/bin/python -m gaottt.server.mcp_server` をターミナルで直接実行してエラーが出ないか確認
- → 詰まったら [6. When Stuck](Tutorial-06-When-Stuck.md)

---

## 次のステップ

最初の記憶を保存して、思い出せるか試してみましょう。

→ [次へ: 最初の会話](Tutorial-04-First-Conversation.md)

> 💡 **オプション**: ここまでで Claude が **明示的に頼めば** `remember` / `recall` できる状態になりました。さらに「黙ってても自動で記憶を引く / 保存候補を浮かべる」フックも入れられます（Claude Code / opencode のみ対応）。基本の確認が済んでから、[Tutorial-05 発展編](Tutorial-05-Everyday-Use.md#-発展-自動で記憶を引かせる--保存候補を浮かべる-オプション) を見てください。

---

### 💡 何が起きたか（興味があれば）

- MCP クライアントは起動時（または登録時）に `gaottt` サーバーを **子プロセスとして起動** し、stdio で JSON-RPC を話します
- クライアント側から見ると、GaOTTT が提供する **27 種類のツール**（remember, recall, explore...）が自分の関数セットに増えた状態になります
- どのクライアントでも動作は同じ — 同じ DB (`~/.local/share/gaottt/gaottt.db`) を共有するので、Claude Desktop で保存した記憶を OpenCode から呼び出す、といった **クライアント横断の記憶** ができます（※同時起動時の注意は [Architecture-Concurrency](Architecture-Concurrency.md)）
