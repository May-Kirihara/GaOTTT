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

### 起動モード — default は **proxy** (auto-spawn + relay)

```bash
# (1) proxy (DEFAULT) — agent ごとに subprocess を spawn するが、
#     その subprocess は軽量 stdio shim で、初回起動時に detached な
#     HTTP backend を spawn し、以降は relay として動作する。N agents
#     all share 1 backend、agent 終了で shim も死ぬが backend は idle
#     timeout (default 5 分) まで生存して再利用される
.venv/bin/python -m gaottt.server.mcp_server
# → stdio を喋りつつ 127.0.0.1:7878 の HTTP backend を内部利用

# (2) streamable-http — HTTP backend を直接起動する。systemd 等で
#     明示常駐させたい場合用
.venv/bin/python -m gaottt.server.mcp_server --transport streamable-http --port 7878
# → http://127.0.0.1:7878/mcp に接続

# (3) SSE (旧 HTTP transport; 互換目的)
.venv/bin/python -m gaottt.server.mcp_server --transport sse --port 7878
# → http://127.0.0.1:7878/sse

# (4) stdio (legacy — agent 内に engine をフル ロード、shim 経由しない)
.venv/bin/python -m gaottt.server.mcp_server --transport stdio
```

| Mode | Per-agent Process | Backend Process | RAM 消費 | 推奨用途 |
|---|---|---|---|---|
| **proxy** (default) | 軽量 shim (~50 MB) | 1 (auto-spawn, idle で self-shutdown) | ~3-4 GB (合計、N agents で増えない) | **personal multi-agent 環境の標準** — `.mcp.json` 変更不要 |
| streamable-http | (なし) | 1 (常駐、systemd 等で管理) | ~3-4 GB | systemd / 24/7 backend を明示管理したい場合 |
| sse | 同上 | 同上 | 同上 | 古い MCP client の fallback |
| stdio | フル engine (~3-4 GB) | (なし) | ~3-4 GB × N | 単独 client、CI、開発 debug |

### Cold-war dead-man-switch (proxy + backend)

```
agent (Claude Code / opencode / ...)
  ↓ stdio
gaottt mcp proxy (shim)  ← 軽量、agent ごとに 1 つ
  ↓ HTTP (streamable-http MCP)
gaottt http backend  ← 1 process、全 shim で共有
  │
  ├─ idle watchdog (--idle-timeout 300 default)
  │   └─ 最後の MCP request から 300 秒経つと cache flush + self-shutdown
  │
  └─ shim 側からの ping (--ping-interval 60 default)
      └─ agent が idle でも 60 秒ごとに backend.last_activity を更新
```

冷戦の核発射シーケンスと同型: 各 silo (shim) が周期的に key を回し続ける限り operator (backend) は活動継続、全 silo が key を回さなくなったら一定時間後に stand down。

| パラメータ | default | 意味 |
|---|---|---|
| `--idle-timeout` (backend) | 300 sec | 無音許容時間。経過後に backend が自分から終了。`0` で無効化 (永久生存) |
| `--ping-interval` (proxy) | 60 sec | 各 shim が backend に打つ heartbeat 周期 (default では idle-timeout の 1/5) |

### Ping は agent の操作とは独立した background task

ここが mental model として重要な点: **shim 内の `_ping_loop` は `asyncio.create_task` で起動した独立 task** で、stdio relay と並列に実行され、agent が `recall` 等を投げているかどうかとは無関係に `--ping-interval` 秒ごとに backend へ ping を飛ばし続ける。つまり「**Agent が idle = backend が死ぬ**」ではなく「**全 agent process が close した = backend が死ぬ**」が正しい判定:

| 状態 | shim の ping | backend `last_activity` | backend |
|---|---|---|---|
| Agent 起動中、recall 全くしない | 60 秒ごとに飛ぶ | 60 秒ごと更新 | **生存** |
| Agent 起動中、頻繁に recall | recall + ping 両方 | 連続更新 | 生存 |
| Agent **idle で 5 分放置** | 飛び続ける | 更新され続ける | **生存** (idle ≠ death) |
| Agent close (Claude Code 終了) | shim 死 → ping 停止 | 最後の ping から計時 | 5 分後 SIGTERM |
| Agent 複数、1 つだけ close | 残り agent の shim が ping 継続 | 連続更新 | 生存 |
| 全 agent close | 全 ping 停止 | 5 分後 timeout | SIGTERM |

つまり「Claude Code を開いている間は何時間でも backend は生存」「全 agent を完全に閉じてから 5 分」が backend の lifecycle。

### Restart cost と memory cost の trade-off

| パターン | Backend 再起動頻度 | 常時 RAM コスト |
|---|---|---|
| `--idle-timeout 300` (default) | 全 agent close → 5 分後に終了。次回起動で proxy が ~30s で respawn | Agent open 時のみ ~3-4 GB |
| `--idle-timeout 0` | **永久生存**、明示 kill するまで動き続ける | 常時 ~3-4 GB |
| systemd 常駐 | 同上 (systemd が auto-restart 管理) | 常時 ~3-4 GB |

「日に数回 Claude Code を完全終了する派」は default のままが省 RAM、「Claude Code 終了でも backend は残しときたい派」は `--idle-timeout 0` を `.mcp.json` の args に追加:

```json
{
  "mcpServers": {
    "gaottt": {
      "command": "/path/to/GaOTTT/.venv/bin/python",
      "args": ["-m", "gaottt.server.mcp_server", "--idle-timeout", "0"],
      "cwd": "/path/to/GaOTTT"
    }
  }
}
```

(shim 側には `--idle-timeout 0` は無関係だが、spawn する backend にそのまま forward されるので結果として backend が永久生存になる。)

公開ツール（25 個）:
- 基本: `remember` / `recall` / `explore` / `reflect` / `ingest`
- F1/F4/F5: `auto_remember` / `forget` / `restore`
- F2.1: `merge` / `compact`
- F7: `revalidate`
- F3: `relate` / `unrelate` / `get_relations`
- F6: `prefetch` / `prefetch_status`
- Phase D: `commit` / `start` / `complete` / `abandon` / `depend` / `declare_value` / `declare_intention` / `declare_commitment` / `inherit_persona`

## Claude Code への登録

**推奨**: proxy mode を使うので `.mcp.json` の設定は単純な stdio subprocess を残せる (default が proxy になったので config は変えなくて良い)。

`.mcp.json`（リポジトリルート）:

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

これだけで:
- Claude Code 起動時 → shim subprocess spawn (軽量、~1s)
- shim が backend の有無を check → 居なければ detached spawn して engine load (~30s) を待つ
- 以降 stdio↔HTTP relay
- Claude Code 終了 → shim 死、backend は idle 5 分後に self-shutdown (Claude Code がすぐ再起動するなら backend は再利用される)

### 旧 stdio mode (full engine in subprocess)

意図的に proxy を bypass したい場合 (debug / CI):

```json
{
  "mcpServers": {
    "gaottt": {
      "command": "/path/to/GaOTTT/.venv/bin/python",
      "args": ["-m", "gaottt.server.mcp_server", "--transport", "stdio"],
      "cwd": "/path/to/GaOTTT"
    }
  }
}
```

### 明示的 HTTP backend (systemd) 経由

systemd で常駐 backend を管理する場合:

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

## OpenCode への登録

**推奨**: proxy mode 経由 (上の Claude Code と同様、config 変更不要)

`opencode.json`:

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

### 明示的 HTTP backend 経由

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

## 旧 stdio multi-process setup からの移行手順

これまで複数 agent が個別に full engine を spawn していた環境からの切り替え:

1. **既存の stdio MCP server を全部 kill**: `pkill -f 'gaottt.server.mcp_server'`
2. **`.mcp.json` / `opencode.json` は変更不要** — proxy mode が default なので既存の `command` based config がそのまま動く
3. **agent (Claude Code / opencode) を再起動** — 起動時に proxy が backend を spawn する (~30s)
4. **動作確認**:
   - `lsof -i :7878` で backend が listening していること
   - `ps aux | grep mcp_server` で `--transport streamable-http` が 1 process だけあること
   - Claude Code の `/mcp` で `gaottt` が `connected`

## systemd で backend を明示常駐させたい場合

proxy mode の auto-spawn を使わず、backend を OS service として管理:

```bash
# ~/.config/systemd/user/gaottt-mcp.service
cat > ~/.config/systemd/user/gaottt-mcp.service <<'EOF'
[Unit]
Description=GaOTTT MCP Server (streamable-http, shared)
After=network.target

[Service]
Type=simple
WorkingDirectory=/path/to/GaOTTT
ExecStart=/path/to/GaOTTT/.venv/bin/python -m gaottt.server.mcp_server --transport streamable-http --port 7878 --idle-timeout 0
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now gaottt-mcp.service
systemctl --user status gaottt-mcp.service
```

`--idle-timeout 0` で idle 終了を無効化 (systemd 管理下では意味がない)。ログ確認: `journalctl --user -u gaottt-mcp.service -f`。

この場合は agent config を `type: http` + URL に書き換える (上の「明示的 HTTP backend」セクション)。

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
