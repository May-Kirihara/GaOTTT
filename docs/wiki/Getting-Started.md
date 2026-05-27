# Getting Started

GaOTTT をゼロからインストールして、最初の `remember` と `recall` を打つまで、約 5 分。

## 前提

- Python 3.11+（推奨 3.12）
- `uv`（推奨）
- 約 4GB のディスク（ruri-v3-310m モデル ~1.2GB + 余裕）
- CUDA GPU は任意（CPU でも動く）

## 1. インストール

```bash
git clone https://github.com/May-Kirihara/GaOTTT.git
cd GaOTTT
uv venv .venv --python 3.12
uv pip install -e ".[dev]"
```

CPU だけで動かすなら:

```bash
uv pip install torch --index-url https://download.pytorch.org/whl/cpu
uv pip install -e ".[dev]"
```

## 2. データディレクトリの確認

GaOTTT は OS ごとの固定ディレクトリに DB と FAISS index を保存します。どこから起動しても同じデータ:

| OS | データディレクトリ |
|---|---|
| Linux/macOS | `~/.local/share/gaottt/` |
| Windows | `%LOCALAPPDATA%\ger-rag\` |

カスタマイズ:
```bash
export GAOTTT_DATA_DIR=/path/to/data
```

## 3. MCP サーバー起動（Claude Code / Claude Desktop / OpenCode / Codex CLI で使う場合）

`.mcp.json.example` を `.mcp.json` にコピーしてパスを書き換える、または直接起動:

```bash
.venv/bin/python -m gaottt.server.mcp_server
```

Claude Code に登録すると、SKILL.md が自動的にロードされ、`mcp__gaottt__remember` などのツールが使えます。

詳細は [Operations — Server Setup](Operations-Server-Setup.md)。

## 4. 最初の記憶を保存

MCP クライアント（Claude Code 等）から:

```
remember(
  content="今日 GaOTTT のインストールが完了した",
  source="agent",
  tags=["milestone"],
  emotion=0.5,
  certainty=1.0,
)
```

返り値: `Remembered. ID: <uuid>`

## 5. 思い出してみる

```
recall(query="GaOTTT のインストール", top_k=3)
```

返り値に先ほど保存した記憶が、`final_score`・`raw_score`・`source`・`displacement` の値とともに浮上します。

## 6. ファイル一括取り込み（任意）

ノートやドキュメントが既にある場合:

```bash
.venv/bin/python scripts/load_files.py ~/path/to/notes/ --recursive --source notes
```

または MCP 経由で:

```
ingest(path="~/path/to/notes/", pattern="*.md", recursive=true)
```

Claude Code のチャット履歴 (`~/.claude/projects/<proj>/<sessionId>.jsonl`) も取り込めます:

```bash
.venv/bin/python scripts/load_chat.py ~/.claude/projects/<proj>/ -r
```

詳細は [Operations — Ingestion](Operations-Ingestion.md)。

## 7. 状態を眺める

```
reflect(aspect="summary")
```

→ 全メモリ数、active ノード数、共起エッジ数、ソース内訳

```
reflect(aspect="hot_topics", limit=10)
```

→ 質量が大きい記憶（よく recall されるもの）

## 8. 受動的記憶注入を有効にする（任意）

エージェントが明示的に `recall` しなくても、プロンプトを毎ターン自動検索して関連記憶を文脈に注入できます（[Ambient Recall](Guides-Ambient-Recall.md)）。フックを 1 つ登録するだけ — read-only な passive recall なので重力場を乱さず、関連性の低いプロンプトには何も注入しません。

**Claude Code** — `~/.claude/settings.json`（無ければ新規作成、`/Path/to/GaOTTT` は実際の GaOTTT clone path に置き換え）:

```json
{ "hooks": { "UserPromptSubmit": [ { "hooks": [ {
  "type": "command",
  "command": "\"/Path/to/GaOTTT/.venv/bin/python\" \"/Path/to/GaOTTT/scripts/hooks/ambient_recall.py\""
} ] } ] } }
```

> `$CLAUDE_PROJECT_DIR` は使わない — 現在の project の dir に展開されるので別レポで Claude Code を起動すると hook script が見つからない。詳細: [Operations — Server Setup §Hook の登録](Operations-Server-Setup.md#hook-の登録-ambient_recall--save_candidates)

**opencode** — プラグインをプラグインディレクトリにコピー（起動時に自動ロード）+ **必ず** `GAOTTT_REPO` を export:

```bash
mkdir -p ~/.config/opencode/plugin
cp scripts/hooks/opencode-ambient-recall.ts ~/.config/opencode/plugin/gaottt-ambient-recall.ts
echo 'export GAOTTT_REPO=/Path/to/GaOTTT' >> ~/.bashrc   # 必須、自分の clone path
source ~/.bashrc
```

⚠️ `GAOTTT_REPO` を設定しないと plugin が wrong path で Python interpreter を探して silent fail する（error 出ず、ただ block が injection されない）。詳細・relevance gate・観察者効果は [Guides — Ambient Recall](Guides-Ambient-Recall.md)。

## 次に進む

- **長期記憶として育てる** → [Guides — Use as Memory](Guides-Use-As-Memory.md)
- **タスク管理に使う** → [Guides — Use as Task Manager](Guides-Use-As-Task-Manager.md)
- **人格保存基盤として** → [Guides — Use as Persona Base](Guides-Use-As-Persona-Base.md)
- **記憶を自動で効かせる（フック）** → [Guides — Ambient Recall](Guides-Ambient-Recall.md)
- **使えるツール一覧** → [MCP Tool Index](MCP-Reference-Index.md)

## 詰まったら

→ [Operations — Troubleshooting](Operations-Troubleshooting.md)
