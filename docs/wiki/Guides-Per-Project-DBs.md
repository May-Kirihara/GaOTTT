# Guide — Per-Project DBs (知識ドメインを分ける)

「**プロジェクト A の memo / persona と、プロジェクト B の memo / persona を別物として保持したい**」ときの設定方法。

GaOTTT は env var 1 本で完全に独立した DB を作れるが、**default の proxy mode は port 7878 の backend を共有する**ので、env var だけ分けても初回 spawn 時の env が勝ってしまう。回避策まで含めて整理する。

## 何が「独立」になるか

`data_dir` を切り替えると、以下のファイル一式がプロジェクトごとに独立する ([Architecture — Storage & Schema](Architecture-Storage-And-Schema.md) 参照):

| ファイル | 内容 |
|---|---|
| `gaottt.db` | SQLite (memo / edges / tasks / persona declarations 全て) |
| `gaottt.faiss` | raw FAISS (原始 embedding) |
| `gaottt.virtual.faiss` | virtual FAISS (raw + displacement) |
| `cache/` | write-behind 一時領域 |

→ 一切のクロスコンタミなし。プロジェクト B の `recall` がプロジェクト A の memo を返すことはない。

## 切り替えメカニズム (優先度順)

`gaottt/config.py:_default_data_dir` の解決順:

| 優先度 | 手段 | 用途 |
|---|---|---|
| 1 | `GAOTTT_DATA_DIR=/path` env var | プロジェクト単位 (`.envrc` / direnv で自動切替) |
| 2 | `GAOTTT_CONFIG=/path/to/config.json` env var | ハイパラも併せて分けたい場合 |
| 3 | `~/.config/gaottt/config.json` の `"data_dir"` フィールド | グローバル既定を変えたい場合 |
| 4 | (default) `~/.local/share/gaottt/` | 何も指定しない場合 |

切替先ディレクトリが空でも、初回 startup で必要なファイルは全部 auto-create される。**手動で `gaottt.db` を作る必要はない**。

## proxy mode の落とし穴 (default 構成)

`--transport proxy` (default) の topology を思い出す ([Operations — Server Setup](Operations-Server-Setup.md) 「Cold-war dead-man-switch」):

```
agent A (env: GAOTTT_DATA_DIR=/path/A) ─┐
                                        ├→ stdio shim ─→ 127.0.0.1:7878 backend
agent B (env: GAOTTT_DATA_DIR=/path/B) ─┘                      ↑
                                                  最初に spawn した shim の env を継承
```

`gaottt/server/mcp_proxy.py:_spawn_backend_detached` は `subprocess.Popen(cmd)` に `env=` を渡していないので、**backend は最初に spawn を仕掛けた shim の env を引き継いで起動する**。port 7878 の backend が既に走っている限り、2 つめ以降の shim はそれに attach するだけ — env var の値はチェックされない。

つまり default のままだと:

| シナリオ | 結果 |
|---|---|
| A を先に立ち上げ → B を後で立ち上げ | A も B も `/path/A` を見る (B の env は無視) |
| A を kill → B を立ち上げ → A を立ち上げ直し | A も B も `/path/B` を見る |
| 同時起動 (race) | spawn を制した方の env が勝つ |

**症状**: B のプロジェクトで `recall` したのに A の memo が返ってくる、`remember` した内容が A の DB に紛れ込む、等。

## 解法 1 — port を分けて backend を分離 (推奨)

各プロジェクトに専用 port を割り当てれば、それぞれ独立した backend process が走り、env もちゃんと分離される:

`project_A/.mcp.json`:
```json
{
  "mcpServers": {
    "gaottt": {
      "command": "/path/to/GaOTTT/.venv/bin/python",
      "args": ["-m", "gaottt.server.mcp_server", "--port", "7878"],
      "cwd": "/path/to/GaOTTT",
      "env": { "GAOTTT_DATA_DIR": "/path/A" }
    }
  }
}
```

`project_B/.mcp.json`:
```json
{
  "mcpServers": {
    "gaottt": {
      "command": "/path/to/GaOTTT/.venv/bin/python",
      "args": ["-m", "gaottt.server.mcp_server", "--port", "7879"],
      "cwd": "/path/to/GaOTTT",
      "env": { "GAOTTT_DATA_DIR": "/path/B" }
    }
  }
}
```

`port` (proxy の `--port`) は **backend の listening port** でもある。port が違えば backend process も別、env も別、DB も別。

確認:
```bash
ps -ef | grep "gaottt.server.mcp_server.*streamable-http" | grep -v grep
# project A 起動中なら 7878 listening の backend、B も起動中なら 7879 も追加で listening
lsof -i :7878 -i :7879
```

**RAM コスト**: backend 1 つにつき ~3-4 GB (RURI モデル分が dominate)。N project 並行で走らせるなら N × 3-4 GB 必要。

## 解法 2 — stdio mode に落とす (省 RAM、毎回 cold start)

`--transport stdio` なら shim も backend も無く、agent 内に engine をフルロードする legacy 動作になる。agent ごとに env がそのまま効く:

```json
{
  "mcpServers": {
    "gaottt": {
      "command": "/path/to/GaOTTT/.venv/bin/python",
      "args": ["-m", "gaottt.server.mcp_server", "--transport", "stdio"],
      "cwd": "/path/to/GaOTTT",
      "env": { "GAOTTT_DATA_DIR": "/path/A" }
    }
  }
}
```

- ✅ env が確実に効く
- ✅ port 衝突無し
- ❌ agent 起動ごとに RURI ロード (~30s)
- ❌ N agent 並行で N × 3-4 GB

debug / 単独 client / 「項目数が小さくて RURI load が許容できる」場合に有効。

## direnv で `.envrc` 連携 (実用パターン)

direnv を使うと `cd` するだけで env が自動切替される。各プロジェクトリポジトリのルートに:

```bash
# project_A/.envrc
export GAOTTT_DATA_DIR="$HOME/.local/share/gaottt-projects/project_A"
```

```bash
# project_B/.envrc
export GAOTTT_DATA_DIR="$HOME/.local/share/gaottt-projects/project_B"
```

`direnv allow` を各リポジトリで 1 回叩けば、以降は `cd project_A/` で env がロードされ、その shell で起動した agent (Claude Code 等) は **そのプロジェクトの DB を見る** 状態になる。

`.mcp.json` 側で env を hardcode せず direnv に任せるパターン:

```json
{
  "mcpServers": {
    "gaottt": {
      "command": "/path/to/GaOTTT/.venv/bin/python",
      "args": ["-m", "gaottt.server.mcp_server", "--port", "7878"],
      "cwd": "/path/to/GaOTTT"
    }
  }
}
```

注意: それでも **proxy mode の落とし穴** は残る (上の解法 1 と組み合わせて port も分ける必要あり)。direnv だけで env を分けても、初回 spawn を制した方の env で backend が立ち上がってしまう。

## backend を確実に切り替えたいとき

「proxy mode のままで、今走っている backend を別 data_dir で立て直したい」場合:

```bash
# 1. 走っている backend を全部止める
pkill -f "gaottt.server.mcp_server.*streamable-http"

# 2. cache が flush されるのを 5-10 秒待つ (gracefulshutdown)

# 3. 切り替えたい env で agent を再起動
GAOTTT_DATA_DIR=/path/B claude
```

これは ad-hoc な手段なので、恒常的に project を切り替えるなら **解法 1 (port 分離)** が素直。

## ベスト・プラクティス

### `data_dir` をどこに置くか

```
~/.local/share/gaottt/                          # default の personal global DB
~/.local/share/gaottt-projects/work-A/          # 仕事プロジェクト A
~/.local/share/gaottt-projects/work-B/          # 仕事プロジェクト B
~/.local/share/gaottt-projects/research/        # 研究用知識ドメイン
```

`gaottt-projects/` 配下に統一しておくと、`du -sh ~/.local/share/gaottt-projects/*` で各プロジェクトの DB サイズが一目で見える + バックアップ対象が一箇所にまとまる。

### Port 割り当て

| プロジェクト | port | 用途 |
|---|---|---|
| (default global) | 7878 | personal な全ドメイン共有 DB |
| work-A | 7879 | クライアント A 関連 |
| work-B | 7880 | クライアント B 関連 |
| research | 7881 | 学術調査ドメイン |

`7878` は mnemonic で NSNS なので、+1 ずつ振っていくのが分かりやすい (`/etc/services` と被らない range)。

### バックアップ

各 `data_dir/` を独立して tar すれば良い。ドメイン分離してあると「研究 DB はバックアップ頻度低め、仕事 DB は毎日」のような差別化も自然にできる ([Operations — Compact & Backup](Operations-Compact-And-Backup.md))。

### 一切混ぜたくない場合の確認

```bash
# 起動中の backend がどの data_dir を見ているか
ls -la /proc/$(pgrep -f "mcp_server.*streamable-http")/cwd  # cwd
cat /proc/$(pgrep -f "mcp_server.*streamable-http")/environ | tr '\0' '\n' | grep GAOTTT
```

`GAOTTT_DATA_DIR` の export 値と、実際に backend が見ている env が一致していることを必ず確認する。proxy mode の trap で食い違っていたら、上の「backend を確実に切り替えたいとき」の手順で直す。

## 関連

- [Operations — Server Setup](Operations-Server-Setup.md) — proxy mode の topology と起動オプション
- [Guides — Multi-Agent](Guides-Multi-Agent.md) — 逆方向の use case (同一 DB を複数 agent で共有)
- [Architecture — Storage & Schema](Architecture-Storage-And-Schema.md) — どのファイルが `data_dir/` 配下に作られるか
- [Operations — Compact & Backup](Operations-Compact-And-Backup.md) — バックアップ手順
- [Operations — Troubleshooting](Operations-Troubleshooting.md) — 「`recall` の結果が変」「env を変えたのに反映されない」等の症状診断
