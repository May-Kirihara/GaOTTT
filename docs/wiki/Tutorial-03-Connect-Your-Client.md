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

迷ったら **Claude Desktop** が一番セットアップが簡単です。

---

## 共通の準備: パスを 2 つ控える

どのクライアントでも以下の 2 つを使います。ターミナルで実行して、結果をメモしておいてください。

```bash
whoami
```

例: `taro` と出たら、以下では `あなたのユーザー名` を `taro` に置き換えます。

```bash
# macOS / Linux
echo "$HOME/GaOTTT/.venv/bin/python"

# Windows (PowerShell)
echo "$HOME\GaOTTT\.venv\Scripts\python.exe"
```

この出力が GaOTTT を起動する **Python のフルパス** です。以下の設定例の `python のフルパス` をこれに置き換えてください。

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

ファイルが空、または `{}` だけなら、以下をそのまま貼り付けます（`python のフルパス` は先ほど控えたものに置き換え）:

```json
{
  "mcpServers": {
    "gaottt": {
      "command": "python のフルパス",
      "args": ["-m", "gaottt.server.mcp_server"]
    }
  }
}
```

すでに `mcpServers` があるなら、その中に `gaottt` の項目だけ追加してください（カンマの位置に注意）。保存したら **Claude Desktop を起動**。

### 成功の目印 ✅

入力欄の左下に **小さなハンマー🔨アイコン**（または「ツール」表示）が出ていて、クリックすると `gaottt` の名前と `remember` / `recall` など 25 個のツールが並びます。

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

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "gaottt": {
      "type": "local",
      "command": ["python のフルパス", "-m", "gaottt.server.mcp_server"],
      "enabled": true
    }
  }
}
```

保存したら OpenCode を起動（または再起動）。

### 成功の目印 ✅

OpenCode の TUI で `/mcp` や `/tools` でツール一覧を見たとき、`gaottt` の 25 個のツールが見えていれば成功。

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

---

### 💡 何が起きたか（興味があれば）

- MCP クライアントは起動時（または登録時）に `gaottt` サーバーを **子プロセスとして起動** し、stdio で JSON-RPC を話します
- クライアント側から見ると、GaOTTT が提供する **25 種類のツール**（remember, recall, explore...）が自分の関数セットに増えた状態になります
- どのクライアントでも動作は同じ — 同じ DB (`~/.local/share/gaottt/gaottt.db`) を共有するので、Claude Desktop で保存した記憶を OpenCode から呼び出す、といった **クライアント横断の記憶** ができます（※同時起動時の注意は [Architecture-Concurrency](Architecture-Concurrency.md)）
