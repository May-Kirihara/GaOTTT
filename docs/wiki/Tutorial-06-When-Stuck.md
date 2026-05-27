# 🌱 はじめての GaOTTT (6/6) — 困ったとき

詰まったらここを見てください。よくあるつまずきと対処を、原因の心当たりが少なくても見つけられるようにまとめます。

← [前: Everyday Use](Tutorial-05-Everyday-Use.md) ｜ → [Welcome に戻る](Tutorial-01-Welcome.md)

---

## まず最初に試すこと

困ったら、ほぼ何でも以下で半分くらい解決します:

1. **使っているクライアントを完全終了して再起動** （Claude Desktop は `Cmd + Q` / タスクバー右クリック → 閉じる、Claude Code / OpenCode / OpenClaw は TUI を抜けてから起動し直し）
2. **ターミナルを一度閉じて開き直す**
3. **エラーメッセージを丸ごと Claude に貼って「どういう意味？どうしたらいい？」と聞く**

特に 3 はかなり強いです。Claude はこの種のエラーに詳しいので、**遠慮なく頼ってください**。

---

## インストールでつまずいた

### `command not found: python3` / `python3 が見つかりません`

→ Python が入っていません。[Tutorial-02 のステップ 2](Tutorial-02-Install-GaOTTT.md) に戻って、お使いの OS の手順で Python をインストールしてください。

インストール後、**ターミナルを必ず開き直す** ことが重要です。

### `command not found: uv`

→ uv のインストールが完了しなかったか、ターミナルが認識していません。

```bash
# Mac/Linux: パスを通す
source $HOME/.cargo/env
```

その上で `uv --version` を再確認。それでもダメなら、ターミナルを開き直してください。

### `git: command not found`

→ git が入っていません。

- Mac: `xcode-select --install`（Apple のツール一式が入る）
- Windows: https://git-scm.com/download/win からインストール

### `uv pip install -e ".[dev]"` が途中で止まる / エラーで終わる

赤い文字が大量に出るときは、最後の方の **`Error:` から始まる行** に手がかりがあります。

よくある原因:

- **インターネットが切れた** → 接続を確認して再実行
- **ディスク容量不足** → 4GB 以上空いているか確認
- **権限エラー** → `~/GaOTTT` フォルダにいることを `pwd` で確認

それでもダメなら、エラー全文を Claude に見せて聞いてください。

---

## クライアントに接続できない

### 🔨 アイコン / ツール一覧に `gaottt` が出ない

設定ファイルが正しく読まれていません。まず使っているクライアントごとの設定場所を確認：

| クライアント | 設定ファイル / 登録方法 |
|---|---|
| Claude Desktop | Mac: `~/Library/Application Support/Claude/claude_desktop_config.json`<br>Windows: `%APPDATA%\Claude\claude_desktop_config.json` |
| Claude Code | `claude mcp list` で確認。無ければ [Tutorial-03 セクション B](Tutorial-03-Connect-Your-Client.md#b-claude-code) の `claude mcp add` を再実行 |
| OpenCode | プロジェクトの `opencode.json` または `~/.config/opencode/opencode.json` |
| OpenClaw | `openclaw mcp list` で確認。`~/.openclaw/config.json` の `mcp.servers.gaottt` |
| Codex CLI | `codex mcp list` で確認。`~/.codex/config.toml` の `[mcp_servers.gaottt]`。初回起動で `startup_timeout` エラーが出るときは `startup_timeout_sec = 60` を追加（RURI モデルロード時間） |

#### チェック 1: ファイル名・パス

ファイル名が **完全一致** しているか（`.json` まで含めて）。

#### チェック 2: JSON の文法

設定ファイルの内容を **オンラインの JSON チェッカー**（"json validator" で検索）に貼り付けて、エラーが出ないか確認してください。

よくある間違い:

- カンマ忘れ・余分なカンマ
- ダブルクォート `"` の代わりにシングルクォート `'`
- 日本語の `「」` を JSON で使ってしまう
- 波括弧 `{` `}` の対応が合っていない

#### チェック 3: パス

```bash
# 設定ファイルに書いた command のパスが本当にあるか
# (シェルが $HOME を展開してくれるのでそのままコピペ OK):
ls "$HOME/GaOTTT/.venv/bin/python"
```

ファイルが見つかれば OK。`No such file or directory` なら、パスが間違っているか、Tutorial-02 のインストールが完了していません。

### 🔨 は出るが `gaottt` が無い

設定ファイルの `mcpServers` の中の名前が `gaottt` になっているか確認。

### 🔨 をクリックすると `gaottt` がエラー表示

GaOTTT 自体の起動でコケています。手動で起動してエラーを見ましょう:

```bash
cd ~/GaOTTT
.venv/bin/python -m gaottt.server.mcp_server
```

エラー全文を Claude に見せて聞いてください。

---

## 動いているけど挙動がおかしい

### Claude が記憶ツールを呼んでくれない

- 明示的に「`remember` で覚えておいて」「`recall` で確認して」と頼んでみる
- それでも呼ばないなら、CLAUDE.md やプロジェクト指示で「GaOTTT memory を積極的に使って」と書いておく

### `recall` しても何も出てこない

- まだ何も保存していないかも → `reflect(aspect="summary")` で記憶数を確認
- `Total memories: 0` なら、まだ空っぽです（`remember` してから recall）

### 「タスクが知らない間に消えた」

- タスクは **既定 30 日で自動消滅** します（**忘れる勇気** が組み込まれた設計）
- 残したいタスクは **`revalidate` で生き続けさせる** のが正しい使い方
- 詳しくは [Operations — Troubleshooting](Operations-Troubleshooting.md) の「タスクが知らないうちに消える」

### 「記憶宇宙のサイズが大きくなりすぎた」

- たまに `compact` を呼ぶと、不要な記憶が物理的に整理されます
- 詳しくは [Operations — Compact & Backup](Operations-Compact-And-Backup.md)

---

## フックを入れたけど効いてない

[Tutorial-05 の発展編](Tutorial-05-Everyday-Use.md#-発展-自動で記憶を引かせる--保存候補を浮かべる-オプション) で ambient_recall / save_candidates を入れたのに、`<gaottt-ambient-recall>` ブロックも `<gaottt-save-candidates>` ブロックも出てこない場合:

### 共通: フックは「fail-safe」で**静かに失敗**する

ユーザー入力を絶対にブロックしない設計なので、エラーが起きても何も表示せず exit します。だから「効いてないけど何が悪いかわからない」が起きやすい。順番にチェック:

### 1. backend が古いコードを掴んだままになってないか

`git pull` した後はこれをやらないと、Python 側の新コードが backend に乗りません:

```bash
ps -ef | grep "gaottt.server.mcp_server.*streamable-http" | grep -v grep
# 起動時刻が最新 commit より古ければ:
kill <PID>
# 次の MCP 接続で新 backend が auto-respawn する
```

### 2. パス / GAOTTT_REPO のチェック

**Claude Code の場合**: `~/.claude/settings.json` の `command` が **絶対パス** になっているか。Tutorial-02 どおりなら `~/GaOTTT` 下にあるはず:

```bash
# 設定に書いたパスが本当にファイルとして存在するか:
ls "$HOME/GaOTTT/.venv/bin/python"
ls "$HOME/GaOTTT/scripts/hooks/ambient_recall.py"
```

**opencode の場合**: `GAOTTT_REPO` が現在のシェルで export されているか:

```bash
echo $GAOTTT_REPO
# /home/<ユーザー名>/GaOTTT のような値が出れば OK
# 空なら .bashrc に書いた export が読み込まれていないので、
# ターミナルを開き直すか source ~/.bashrc
```

### 3. デバッグログを出してみる

**opencode**:

```bash
export GAOTTT_AMBIENT_DEBUG=/tmp/gaottt-hook.log
# opencode を起動して 1 プロンプト送信
cat /tmp/gaottt-hook.log
```

**Claude Code**: フックを手動で叩いてエラーを見ます:

```bash
echo '{"prompt": "test"}' | "$HOME/GaOTTT/.venv/bin/python" \
  "$HOME/GaOTTT/scripts/hooks/ambient_recall.py"
```

何かエラーが出れば、それを Claude に貼って聞いてください。

### 4. それでも何も出ない

- 記憶が空っぽだと当然ブロックは出ません。`reflect(aspect="summary")` で `Total memories` を確認
- ambient_recall は **強一致 gate** が入っているので、関連記憶が薄いプロンプトでは何も注入されません（これが正常）。何度か `remember` してから再試行

---

## 「やっぱり全部消したい」

もう使わない、最初からやり直したい、というとき:

### 記憶だけ全部消す

使っている AI クライアントを終了してから、ターミナルで:

```bash
# データディレクトリごとまるごと消すのが一番確実
# (SQLite WAL ファイル / virtual FAISS / .ids サイドカーも一緒に消える)
rm -rf ~/.local/share/gaottt/
```

Windows の方は `%LOCALAPPDATA%\gaottt\` フォルダをエクスプローラーから削除してください。

次に Claude を起動すると **空っぽの状態** から始まります。

### GaOTTT 自体を完全アンインストール

```bash
rm -rf ~/GaOTTT                 # ソースコード（Tutorial-02 で clone した先）
rm -rf ~/.local/share/gaottt/   # 記憶データ
```

そして `claude_desktop_config.json` から `gaottt` の項目を削除。

これで完全にきれいになります。

---

## それでも詰まったら

- **エラー全文を Claude に貼って聞く** — 最強の手段
- リポジトリの Issue を見る: https://github.com/May-Kirihara/GaOTTT/issues
- 新しい問題なら Issue を立てる（エラー全文・OS・実行したコマンドを書く）

---

## ここまで来たあなたへ

ここまで読んでくれてありがとうございます。

GaOTTT はまだ若いプロジェクトで、想定しきれていないつまずきが必ずあります。**詰まったのはあなたのせいではありません**。むしろ「ここで詰まりました」と教えてもらえると、次の人が楽になります。

楽しい記憶宇宙を、ゆっくり育てていってください 🌌

→ [Welcome に戻る](Tutorial-01-Welcome.md)
→ [日々の使い方](Tutorial-05-Everyday-Use.md)
→ [Wiki Home](Home.md)
