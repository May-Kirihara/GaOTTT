# Operations — Server Setup

GaOTTT の環境構築、データ投入、2 種類のサーバー（REST と MCP）の起動・停止・登録方法。

## 環境要件

| 項目 | 要件 |
|---|---|
| Python | 3.11 以上（推奨 3.12） |
| GPU | CUDA 対応 GPU（任意、CPU でも動く） |
| メモリ | 4GB 以上推奨（モデル + キャッシュ） |
| ディスク | 初回モデルダウンロードに約 2GB |
| パッケージ管理 | uv（推奨） |

## セットアップ

```bash
# 仮想環境作成
uv venv .venv --python 3.12

# 依存関係インストール
uv pip install -e ".[dev]"

# 可視化ツール（任意）
uv pip install plotly umap-learn

# GPU 版 FAISS を使う場合
uv pip install -e ".[gpu]"

# CPU 版 PyTorch を明示的に使う場合（軽量）
uv pip install torch --index-url https://download.pytorch.org/whl/cpu
uv pip install -e ".[dev]"
```



## REST API サーバー（FastAPI）

ベンチマーク・評価・REST クライアントから使う。

```bash
# 起動
.venv/bin/uvicorn gaottt.server.app:app --host 0.0.0.0 --port 8000

# 開発時（自動リロード）
.venv/bin/uvicorn gaottt.server.app:app --reload

# 停止: Ctrl+C → graceful shutdown → dirty フラッシュ → FAISS 保存
```

Swagger UI: http://localhost:8000/docs

## MCP サーバー

LLM の長期記憶として使う。プロトコル仕様は [`SKILL.md`](../../SKILL.md)。

### 起動モード — 推奨は **shared HTTP** (multi-agent 用)

```bash
# (1) shared HTTP server — 1 process を long-lived で常駐させ、
#     複数 agent (Claude Code / opencode / 他) が同じ engine を共有する
.venv/bin/python -m gaottt.server.mcp_server --transport streamable-http --port 7878
# → http://127.0.0.1:7878/mcp に接続

# (2) SSE (旧 HTTP transport; 互換目的)
.venv/bin/python -m gaottt.server.mcp_server --transport sse --port 7878
# → http://127.0.0.1:7878/sse

# (3) stdio (legacy — 1 agent ごとに subprocess を spawn、各 agent が
#     fully独立した engine を持つ。RAM ×N、bidirectional cache
#     overwrite trap あり)
.venv/bin/python -m gaottt.server.mcp_server
```

| Mode | Process 数 | RAM 消費 | Cache 整合 | 推奨用途 |
|---|---|---|---|---|
| **streamable-http** | 1 (常駐) | ~3-4 GB (N agent 起動でも変わらず) | ✅ 単一 cache | **multi-agent 環境の標準** |
| sse | 1 (常駐) | 同上 | ✅ | 古い MCP client の fallback |
| stdio | N (agent 数だけ subprocess) | ~3-4 GB × N | ⚠️ N 個の cache が race | 単独 client (legacy)、CI、開発 debug |

公開ツール（25 個）:
- 基本: `remember` / `recall` / `explore` / `reflect` / `ingest`
- F1/F4/F5: `auto_remember` / `forget` / `restore`
- F2.1: `merge` / `compact`
- F7: `revalidate`
- F3: `relate` / `unrelate` / `get_relations`
- F6: `prefetch` / `prefetch_status`
- Phase D: `commit` / `start` / `complete` / `abandon` / `depend` / `declare_value` / `declare_intention` / `declare_commitment` / `inherit_persona`

### systemd unit (Linux、ユーザーレベル常駐)

```bash
# ~/.config/systemd/user/gaottt-mcp.service
cat > ~/.config/systemd/user/gaottt-mcp.service <<'EOF'
[Unit]
Description=GaOTTT MCP Server (streamable-http, shared)
After=network.target

[Service]
Type=simple
WorkingDirectory=/path/to/GaOTTT
ExecStart=/path/to/GaOTTT/.venv/bin/python -m gaottt.server.mcp_server --transport streamable-http --port 7878
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now gaottt-mcp.service
systemctl --user status gaottt-mcp.service
```

ログ確認: `journalctl --user -u gaottt-mcp.service -f`

## Claude Code への登録

### 推奨: shared HTTP に接続 (server を別途常駐させる)

`.mcp.json`（リポジトリルート）:

```json
{
  "mcpServers": {
    "gaottt": {
      "type": "http",
      "url": "http://127.0.0.1:7878/mcp"
    }
  }
}
```

### Legacy: 各 agent が自分で stdio subprocess を spawn

```json
{
  "mcpServers": {
    "gaottt": {
      "command": "/path/to/GaOTTT/.venv/bin/python",
      "args": ["-m", "gaottt.server.mcp_server"],
      "cwd": "/path/to/GaOTTT"
    }
  }
}
```

## OpenCode への登録

### 推奨: shared HTTP

`opencode.json`:

```json
{
  "mcp": {
    "gaottt": {
      "type": "remote",
      "url": "http://127.0.0.1:7878/mcp"
    }
  }
}
```

### Legacy: stdio subprocess

```json
{
  "mcp": {
    "gaottt": {
      "type": "local",
      "command": [
        "/path/to/GaOTTT/.venv/bin/python",
        "-m",
        "gaottt.server.mcp_server"
      ]
    }
  }
}
```

## stdio → HTTP 移行手順

1. **systemd unit を上記レシピで作成 + start**
2. **動作確認**: `curl -X POST http://127.0.0.1:7878/mcp -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0.1"}}}'` で `{"jsonrpc":"2.0","id":1,"result":{...}}` が返れば OK
3. **`.mcp.json` / `opencode.json` を URL ベースに書き換え**
4. **既存の stdio subprocess は全て kill** (`pkill -f 'gaottt.server.mcp_server'`) — 古い設定で起動していた agent process を再起動すると新 URL を見るようになる
5. Claude Code / opencode を再起動して接続確認 (`/mcp` コマンドで `gaottt` が `connected` に表示されれば成功)

## モデルダウンロード

初回起動時に RURI-v3-310m（約 1.2GB）が HuggingFace からダウンロードされる。2 回目以降はローカルキャッシュ（`~/.cache/huggingface/hub/`）から即座にロード、HTTP リクエストは発生しない。

## Virtual FAISS (Phase H Stage 4 以降)

2026-05-11 から、`virtual_faiss_enabled=True`（既定）のとき engine は **2 つの FAISS index** を並走させる:

| ファイル | 内容 |
|---|---|
| `gaottt.faiss` | 原始 embedding そのまま (raw FAISS) |
| `gaottt.virtual.faiss` | `virtual_pos = raw + displacement` (Phase G priming 反映) |

- **初回 startup**: `gaottt.virtual.faiss` が disk に存在しなければ、raw + cache.displacement から自動 build される。23k 件規模で数十秒の追加 startup 時間。
- **shutdown**: 両 index が save される。
- **`compact(rebuild_faiss=True)`**: raw rebuild 後に virtual も rebuild。
- **無効化**: `virtual_faiss_enabled=False` で legacy 挙動（raw のみ）。`gaottt.virtual.faiss` ファイルは残るが使われない。
- **マルチプロセス安全性**: raw FAISS と同じ write-behind 周期 (`faiss_save_interval_seconds=5`) で save される。virtual FAISS も `virtual_faiss_save_interval_seconds=60`（既定）で `cache.virtual_faiss_dirty` 検知時に full rebuild + disk save が走る — Phase I/J query attraction で蓄積した displacement が次の compact を待たずに他プロセスの seed pool に伝播する。

bootstrap_report.py の neighbor preview は raw + virtual FAISS の **両方** を並べて表示する (2026-05-13 〜)。displacement で動いた node が raw と virtual で異なる近傍を持つ場合、`Δ:` 行に drift-in / drift-out した id が列挙される。`--no-virtual` で legacy raw-only モード。

## データディレクトリ

| OS | データディレクトリ | 設定ファイル |
|---|---|---|
| Linux/macOS | `~/.local/share/gaottt/` | `~/.config/gaottt/config.json` |
| Windows | `%LOCALAPPDATA%\gaottt\` | `%APPDATA%\gaottt\config.json` |

旧名 GER-RAG 時代の `~/.local/share/ger-rag/` や `~/.config/ger-rag/` に既存データがあれば、`gaottt/config.py` の互換レイヤが自動検出して使用する（deprecation 警告を出力）。移行するなら `scripts/migrate-from-ger-rag.sh` を走らせる。

カスタマイズ:
```bash
export GAOTTT_DATA_DIR=/path/to/data
export GAOTTT_CONFIG=/path/to/config.json
```

## データ投入

### CSV から一括投入

```bash
.venv/bin/python scripts/load_csv.py                   # 全件
.venv/bin/python scripts/load_csv.py --limit 100       # テスト用
.venv/bin/python scripts/load_csv.py --max-chunk-chars 3000
```

DM/group_DM は自動除外。長文は `---` セパレータまたは段落区切りで自動チャンク分割。重複 content は SHA-256 で自動スキップ（同じ CSV を複数回投入しても安全）。

### ファイル/ディレクトリから一括投入

```bash
.venv/bin/python scripts/load_files.py ~/notes/ --recursive
.venv/bin/python scripts/load_files.py ~/notes/ --pattern "*.md,*.txt" -r
.venv/bin/python scripts/load_files.py ~/notes/ --source notes -r
.venv/bin/python scripts/load_files.py ~/notes/ -r --dry-run    # 確認用
```

### MCP 経由

```
ingest(path="~/notes/", pattern="*.md", recursive=true)
ingest(path="~/data.csv")
```

### 投入直後の確認（読み取り専用）

一括投入が終わった直後、**まだ何も `recall` されていない素の状態** を眺めたいときに使う:

```bash
.venv/bin/python scripts/bootstrap_report.py               # 既定（sample=10, k=5）
.venv/bin/python scripts/bootstrap_report.py --sample 20   # 近傍プレビューを多めに
.venv/bin/python scripts/bootstrap_report.py --dup-threshold 0.9  # 軟らかめの重複検出
.venv/bin/python scripts/bootstrap_report.py --no-virtual  # virtual FAISS をロードしない (旧 data dir 向け)
```

3 セクションを出す: (1) summary + source 分布 + **displacement 統計** (min/p50/p90/p99/max、|d|>0.3/1.0/3.0 件数)、(2) 近重複クラスタ（`merge` 候補）、(3) ランダムに選んだノードの FAISS top-K 近傍を **raw + virtual 両方**（**まだ張られていないが、最初の co-recall で結ばれる潜在的エッジ** のプレビュー、および displacement で動いた node の drift を `Δ:` 行で可視化）。

DB への副作用なし、LLM 呼ばない。オンライン書き込み中の MCP サーバーと同時実行しても安全（read-only close で FAISS 再保存もしない）。

## テストクエリの実行

```bash
.venv/bin/python scripts/test_queries.py --mode basic         # 5 クエリ
.venv/bin/python scripts/test_queries.py --mode full --rounds 3   # 37 トピック
.venv/bin/python scripts/test_queries.py --mode stress --rounds 10  # 82 クエリ/ラウンド
```

| モード | クエリ数/ラウンド | 用途 |
|---|---|---|
| basic | 5 | 動作確認 |
| full | 37（毎回シャッフル） | 多様なトピック網羅、共起パターン生成 |
| stress | 82（37 多様 + 45 バースト） | 可視化デモ前の大量蓄積 |

→ 関連: [Tuning](Operations-Tuning.md), [Compact & Backup](Operations-Compact-And-Backup.md), [Isolated Benchmark](Operations-Isolated-Benchmark.md), [Troubleshooting](Operations-Troubleshooting.md)
