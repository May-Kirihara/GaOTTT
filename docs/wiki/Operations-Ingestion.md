# Operations — Ingestion / データ取り込み

GaOTTT に **既存のファイル・履歴** を一括で流し込むための運用ガイド。Markdown / 平文テキスト / CSV / Claude Code チャット履歴 (JSONL) を扱う。

> **3 つの入り口、1 つの裏側**
> 取り込み口は次の 3 つだが、すべて同じ `gaottt/ingest/loader.py` を経由するので、出来上がる documents の shape は完全に同じ。
> - **CLI** — `scripts/load_files.py`（ファイル / ディレクトリ）、`scripts/load_chat.py`（チャット履歴）、`scripts/load_csv.py`（旧 `documents.csv` 形式）
> - **MCP tool** — `ingest(path=..., ...)` を MCP クライアントから呼ぶ
> - **REST** — `POST /ingest`（CLI スクリプトはこの裏で動く）

## 1. 対応フォーマット早見表

| 拡張子 | 分割単位 | `original_id`（Phase M self-force key） | 主なメタデータ |
|---|---|---|---|
| `.md` | `##` 見出し → 段落 → 文 | ファイルパス | `title`, `section`, `file_path`, `file_name`, `chunk_index/total` |
| `.txt` | 段落 → 文 | ファイルパス | `file_path`, `file_name`, `chunk_index/total` |
| `.csv` | 1 行 = 1 ドキュメント | `id` 列 or `<path>#<row>` | 全列がメタデータに入る（content 列以外） |
| `.jsonl` (Claude Code) | **1 exchange**（user prompt + 続く assistant 群を 1 単位） | `<sessionId>#<turnIndex>` | `session_id`, `turn_index`, `timestamp`, `cwd`, `git_branch`, `model`, `cli_version`, `is_sidechain` |

> **Phase M の文脈**: 同一ファイル / 同一行 / 同一 exchange の chunk は **`original_id` を共有** することで、`is_self_force_by_id` が「内輪取引」と判定して mass を inflate しない（[Plans — Phase M](Plans-Phase-M-Mass-Conservation.md) 参照）。loader を新規に書き足すときは、この対応を必ず維持する。

## 2. どの口を使うか

| やりたいこと | 推奨ルート |
|---|---|
| ノート / 書籍 / メモを丸ごと | `scripts/load_files.py` |
| Claude Code のチャット履歴を流し込む(数百 chunks まで) | `scripts/load_chat.py` または MCP `ingest(pattern="*.jsonl")` |
| **チャット履歴の大規模(数千 chunks 超)** | **`scripts/load_chat.py` 必須**(下記の警告参照) |
| 旧 `documents.csv` 形式の Twitter / Discord アーカイブ等 | `scripts/load_csv.py` |
| サーバープロセス内から one-shot の小さいバッチ | MCP `ingest` tool(または REST `POST /ingest`) |

CLI スクリプトは `POST /index`(chunk 化済みの documents を直接送る)or `POST /ingest`(path をサーバーに渡してサーバー側で展開)の **どちらかを叩く**:`load_files.py` と `load_csv.py` は `/index`、`load_chat.py` も `/index`。MCP `ingest` tool は **サーバー側でファイルを読む**点に注意(パスは GaOTTT サーバープロセスの CWD 基準)。

### ⚠️ 大規模 ingest は MCP `ingest` ではなく `load_chat.py` を使う

**実測差(2026-05-14 acceptance test 中)**:

| 経路 | 規模 | 結果 |
|---|---|---|
| MCP `ingest(path=~/.claude/projects/, recursive=True)` | 33 dirs / 903 .jsonl / 245 MB | **47 分経過しても完了せず**、WAL が 7.6 GB に膨張、backend メモリ 50 GB、SIGTERM 必要 |
| `load_chat.py ~/.claude/projects/ -r --batch-size 50` | 同じ規模(差分は重複 dedup) | **1.2 秒で完了** |

**根本原因**: MCP `ingest` tool は **1 call = 1 transaction** で全件処理する設計。数千 chunks の embedding + cooccurrence 計算 + SQLite INSERT を 1 トランザクション内に押し込むため、SQLite WAL が無制限に成長し commit が来ない。一方 `load_chat.py` は **HTTP で `--batch-size` 件ずつ POST** → 各 batch が独立した REST 呼び出し = **per-batch transaction** で WAL は per-batch でマージされる。

**目安**: chunks 数 × 1 MB 程度の WAL は MCP `ingest` でも問題なし(数百件まで)。それ以上は `load_chat.py` 一択。

将来 MCP `ingest` 側で内部 batching を実装すれば解消(`services/ingest_service.py` で `engine.index_documents` を chunk して呼ぶ)。

## 3. 共通の前提

### サーバーが立っていること

- **REST `/index` / `/ingest`** → port `:8000` の FastAPI が必要:
  ```bash
  .venv/bin/python -m uvicorn gaottt.server.app:app --host 0.0.0.0 --port 8000
  ```
  > venv のエントリポイント `.venv/bin/uvicorn` を直接呼ぶと、shebang が古い path を指していて動かないことがある（GER-RAG → GaOTTT renamed の名残）。`python -m uvicorn` で呼ぶか、`sed -i 's|/mnt/holyland/Project/GER-RAG|/mnt/holyland/Project/GaOTTT|g' .venv/bin/*` で全 shebang を修正する。
- **MCP `ingest`** → port `:7878/mcp` の MCP backend (proxy 経由でも直接 streamable-http でも可)
- 詳細起動オプション: [Operations — Server Setup](Operations-Server-Setup.md)

### 並行プロセスを止めること（bulk 書き込み時）

複数の MCP server プロセスが走っているとき、片方が cache を flush し続けるとお互いの書き込みが上書きされる ("逆方向上書き罠"、[Architecture — Concurrency](Architecture-Concurrency.md))。**bulk ingest の前に他の MCP server を停止 → 取り込み → 再起動**、の順。

### バックアップ

`compact()` 前の `gaottt.db` のスナップショット推奨。`scripts/migrate.py` のロールアウトと同じく、destructive ではないが大量に書き込むので、戻れる地点を作っておく。

## 4. Markdown / Text / CSV — 既存ファイルの取り込み

`scripts/load_files.py` を使う。

```bash
# ノートディレクトリを recursive に
.venv/bin/python scripts/load_files.py ~/notes/ --recursive --source notes

# 1 ファイルだけ
.venv/bin/python scripts/load_files.py ~/docs/spec.md

# md と txt 混在
.venv/bin/python scripts/load_files.py ~/library/ -r --pattern "*.md,*.txt"

# 長い章を切らずに保持
.venv/bin/python scripts/load_files.py ~/books/ -r --chunk-size 3000

# 何が入るか確認（送信しない）
.venv/bin/python scripts/load_files.py ~/notes/ -r --dry-run
```

主要オプション:

| フラグ | 既定 | 用途 |
|---|---|---|
| `--source` | `file` | metadata.source の値 |
| `--recursive` / `-r` | off | サブディレクトリ走査 |
| `--pattern` | `*.md,*.txt` | カンマ区切り glob |
| `--chunk-size` | `2000` | 長文の分割上限 (chars) |
| `--batch-size` | `50` | `/index` への 1 リクエスト件数 |
| `--dry-run` | off | 送信せず内容確認 |

CSV 取り込み時の挙動: `content` / `text` / `body` / `message` 列を **自動検出**、`id` 列があれば `original_id` に使う（なければ `<path>#<row>`）。残りの列はそのまま metadata に入る。

### load_csv.py との違い

`scripts/load_csv.py` は **`input/documents.csv` を前提とした旧式**で、`text` 列固定・`source=dm/group_dm` を privacy 目的で skip 等の specialised な振る舞いを持つ。Twitter export 等の既存資産に合わせて作った歴史的経緯がある。新規データは `load_files.py` の汎用 CSV パスを使うほうが素直。

## 5. Claude Code チャット履歴 (.jsonl) の取り込み

GaOTTT 自身は対話のログを記録しない。ただし Claude Code は `~/.claude/projects/<project>/<sessionId>.jsonl` という形で **生の transcript** を残す。これを GaOTTT に流し込むと、**過去のターン**を recall できるようになる。

### 取り込みの単位 — exchange grouping

Claude Code の transcript は

```
user (prompt)
  → assistant (text + tool_use)
  → user (tool_result)
  → assistant (text + tool_use)
  → user (tool_result)
  → assistant (final text)
```

…のように **1 つの Q&A が複数行に渡る**。loader は **「次の real user prompt が来るまで」を 1 exchange としてまとめる**：

```
## User
<元のプロンプト>

## Assistant
<最初の assistant text>

[tool:Bash] ls -la

<次の assistant text>

[tool:Read] /path/to/file

<最終 assistant text>
```

この単位で `original_id = "<sessionId>#<turnIndex>"` を振る。Phase M の self-force filter は、同じ exchange 内の chunk 間では mass update を抑制する。

### 長い exchange を分割するときの header 保持

1 exchange が `chunk_size` (既定 2000 chars) を超えると複数 chunk に分割される。素朴に分割すると **chunks[0] にしか `## User` / `## Assistant` のヘッダが付かない** ため、tool-heavy な中間 chunk が「裸の `[tool:Edit]` 連発」に見え、embedder には Q&A だと認識されない (acceptance test で top1 を奪う原因として観測)。

loader は **`chunks[1..]` の先頭に user prompt の冒頭 100 chars を context line として注入** する:

```
## User (prev): <user prompt の最初の行、100 chars 切り詰め>

## Assistant (cont.)
<chunk text>
```

これで **全 chunk が `## User` と `## Assistant` の両方の header を持つ** ようになり、retrieval 上は Q&A 単位として一貫して扱われる。エッジケースとして、user 文が短くて単独の chunk に収まりかつ assistant が巨大な場合は、`chunks[0]` の末尾に `## Assistant (continues in next chunk)` を追記して同じ invariant を保つ。

注: 旧ロジック(プレフィックスなし)で取り込んだ chunks と、新ロジックで取り込んだ chunks は **content の SHA-256 が異なる** ため、自動 dedup は効かない。古いものを残したまま再 ingest すると倍に膨らむ。掃除手順は §7「既存 chat docs の再 ingest」を参照。

### 何が捨てられるか

| 種別 | 扱い |
|---|---|
| `permission-mode` / `file-history-snapshot` / `last-prompt` / `summary` 行 | 完全に skip |
| `isMeta:true` の user message（CLI 注入された caveat 等） | skip |
| `<local-command-caveat>` / `<local-command-stdout>` / `<command-name>` だけの user 行 | skip |
| `model: "<synthetic>"` の assistant 行（"No response requested." 等） | skip |
| `tool_use` ブロック | 要約 `[tool:<name>] <最初の有用な入力>` で残す |
| `tool_result` ブロック（user role） | **既定では捨てる**。`--include-tool-results` で前 exchange に追記 |
| sidechain (subagent) の user/assistant | 残す（`metadata.is_sidechain = true` でタグ付け） |
| thinking ブロック / image ブロック | 現状 skip |

### CLI で使う

```bash
# 1 session
.venv/bin/python scripts/load_chat.py \
  ~/.claude/projects/-mnt-holyland-Project-GaOTTT/<sessionId>.jsonl

# project ディレクトリ全体
.venv/bin/python scripts/load_chat.py \
  ~/.claude/projects/-mnt-holyland-Project-GaOTTT/ -r

# tool 出力も含める（DB が大きくなる）
.venv/bin/python scripts/load_chat.py <dir>/ -r --include-tool-results

# 何が入るかだけ確認
.venv/bin/python scripts/load_chat.py <session>.jsonl --dry-run
```

主要オプション:

| フラグ | 既定 | 用途 |
|---|---|---|
| `--source` | `claude-code` | metadata.source（後で `recall(source_filter=["claude-code"])` で絞れる） |
| `--recursive` / `-r` | off | session 群を一括 |
| `--pattern` | `*.jsonl` | |
| `--include-tool-results` | off | tool stdout/stderr を exchange 本文に含める |
| `--chunk-size` | `2000` | 長い exchange の分割上限 |
| `--dry-run` | off | 送信せず内容確認 |

### MCP `ingest` から使う

REST サーバーを立てたくない場合はこちらが便利。**サーバー側でファイルを開く**ため、パスはサーバープロセスの CWD（通常 `/mnt/holyland/Project/GaOTTT`）からの相対 or 絶対パス。

```python
# 単一 session
ingest(
    path="input/projects/-mnt-holyland-devs-maysweb/<sessionId>.jsonl",
    source="claude-code",
)

# project ディレクトリ全体
ingest(
    path="input/projects/-mnt-holyland-devs-maysweb",
    source="claude-code",
    recursive=True,
    pattern="*.jsonl",
)

# tool 出力込み
ingest(
    path="input/projects/<proj>",
    source="claude-code",
    recursive=True,
    pattern="*.jsonl",
    include_tool_results=True,
)
```

> **Note**: `.jsonl` ディスパッチと `include_tool_results` は loader/MCP の改修後（コミット日付以降）。**起動中の古い backend は再起動が必要** — 走らせたまま MCP 呼び出ししても、メモリにロードされている古いコードが `.jsonl` を `_ingest_plaintext` 扱いにして大きな 1 行ブロブとして取り込んでしまう。

### REST `/ingest` から使う

```bash
curl -s -XPOST http://127.0.0.1:8000/ingest -H 'Content-Type: application/json' -d '{
  "path": "input/projects/-mnt-holyland-devs-maysweb",
  "source": "claude-code",
  "recursive": true,
  "pattern": "*.jsonl",
  "include_tool_results": false
}'
```

レスポンスは `{path, ingested, skipped, found}`。

## 6. ベストプラクティス

### `source` ラベルの使い分け

`recall(source_filter=[...])` で絞り込めるので、後で取り回せるラベルを最初から付ける。慣例:

| source | 想定内容 |
|---|---|
| `file` | デフォルト・汎用ファイル |
| `notes` | 手書きノート、議事録、Markdown |
| `book` / `book-<title>` | 自炊書籍など長文 |
| `claude-code` | Claude Code のチャット履歴 |
| `chatgpt` / `openai` | (将来) ChatGPT export |
| `articles` / `tweets` / `likes` | 既存資産（旧 `load_csv.py` 系） |

### Phase M の文脈で chunk が分かれるとき

`--chunk-size` を超える長い exchange / 行は自動的に複数 chunk に分かれるが、**同じ `original_id` を共有する**ので mass inflation は起きない。怖がらず大きな chunk_size にしても、retrieval の score 上は普通の 1 ドキュメントとして振る舞う。逆に **`original_id` を欠いたまま流し込むと chunk 同士がお互いを mass で持ち上げる** ので注意。loader 改造時は必ず `original_id` を埋める。

### 取り込み後の検証

```python
# まず recall できることを確認
recall(query="<exchange の典型キーワード>", source_filter=["claude-code"], top_k=5)

# 量だけ確認
reflect(aspect="summary")

# 一番重くなった ingest 由来ノードを見る
reflect(aspect="hot_topics", limit=10)
```

新規に流し込んだ直後は **Phase G genesis kick** で `mass=1.0`、`displacement` が 0 ではない値で起動するので、即時 recall でも普通に surface する（[Plans — Phase G](Plans-Phase-G-Memory-Genesis.md)）。

### `include_tool_results` を切るべきとき

- DB の容量を抑えたい
- `tool_result` の生 stdout（git log、find 結果、大量の grep ヒット）が semantic に意味を持たない場合
- セキュリティ的に出力をそのまま流したくない（環境変数 dump 等）

逆に **含めたいとき**: 「あの時 grep で何が出てきたか」を後から思い出したい、AI agent の troubleshooting record を残したい、など。

### 連続セッションの cohort

1 batch の ingest は **Phase K の supernova cohort** として `cohort_id` を共有する（`engine.index_documents` が自動付与）。同じ project の session 群を **1 度の ingest にまとめる** と、それらが共通の cohort で連鎖し、recall 時に互いを引き上げる ([Plans — Phase K](Plans-Phase-K-Stellar-Supernova-Cohort.md))。逆に project ごとに分けて取り込みたいときは別 batch にする。

## 7. トラブルシュート

### `No turns found (sample may be empty or contain only CLI noise).`

`.jsonl` に **real な user/assistant 交換が含まれていない** ことを意味する（`/resume` で空ヒットしただけのセッション等）。サンプルファイル `input/projects/-mnt-holyland-devs-maysweb/bd9ee013-...jsonl` がこのケース。

### `RuntimeError: Port 127.0.0.1:7878 is taken but not by a GaOTTT MCP backend`

proxy mode の probe が 3 秒以内に handshake を返せなかったケース。RURI モデルがロード直後 / virtual FAISS rebuild 中など backend が忙しいときに起きる。回避策: `mcp_proxy.py:147` の probe timeout を `10.0` 程度に上げる、または backend が落ち着くのを待って再接続。

### chat を取り込んだら DB が爆発した

`--include-tool-results` を on にしたまま大量の session を流したケース。`tool_result` には grep の数百行ヒットや CI ログがまるごと入ることがある。`compact(rebuild_faiss=True)` で掃除し、次回からは off。

### 古い backend が `.jsonl` をプレーンテキスト扱いした

loader 改修後に backend を再起動していない。`kill <pid>` → 再起動。詳細: [Operations — Server Setup](Operations-Server-Setup.md)

### 大量 ingest 中に他プロセスが書き込んだ値が消える

cache の逆方向上書き罠([Architecture — Concurrency](Architecture-Concurrency.md))。bulk ingest 中は他の MCP server を停止する。

### MCP `ingest` を呼んだら何分経っても返ってこない

数千 chunks 超の大規模 ingest を MCP `ingest` tool で実行した場合。**1 call = 1 transaction** 設計のため WAL が無制限成長(実測 7.6 GB)、commit が来ず embedding ループが終わらない。

**対処**:
1. `kill <backend_pid>` で SIGTERM(SQLite は per-doc 単位の commit が部分的に走っているため、SIGTERM 前にコミットされた分は失われない)
2. `wal_checkpoint(TRUNCATE)` で WAL を main DB にマージ:
   ```python
   import sqlite3
   con = sqlite3.connect("/path/to/gaottt.db", isolation_level=None)
   print(con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone())
   ```
3. 不足分を `load_chat.py --batch-size 50` で埋める(content_hash dedup で既存分は自動 skip)

**今後**: 数千 chunks 超は最初から `load_chat.py` を使う(上記「⚠️ 大規模 ingest」セクション参照)。

### 既存 chat docs の再 ingest（chunk prefix 改修対応）

loader が **chunks[1..] に `## User (prev): ...` プレフィックスを注入** するようになった改修後、過去に取り込んだ chat docs を最新の形式に揃え直す手順:

**症状**: 旧形式で取り込んだ chunks は、本文中盤の chunk が `[tool:Edit] ...` だけの「裸の続き」になっており、recall(`source_filter=["claude-code"]`) で top1 が tool 行に占領される（acceptance test で観測。Exchange 整合 1/5）。

**選択肢**:

1. **何もしない (推奨、初手)** — 既存 chunks は Phase G/H の displacement 累積と Phase I Stage 3 の query attraction で徐々に位置を調整される。新規セッションは新しい loader で取り込まれるので、自然に新旧が混ざる。違和感が消えるまで観察してから動くのが安全。

2. **旧 chat docs を bulk forget して再 ingest** — destructive、計画的に:

   ```bash
   # (a) backup
   cp $GAOTTT_DB ${GAOTTT_DB}.before-chat-reingest

   # (b) 他の MCP server / REST server を停止 (cache 逆方向上書き罠)
   pkill -f "gaottt.server.mcp_server"
   # backend は :7878 に立っているなら止める。落ちた状態で SQL から削除する。

   # (c) source=claude-code の row を SQLite から消す（暫定手段、専用ツールはまだない）
   sqlite3 $GAOTTT_DB "DELETE FROM nodes WHERE json_extract(metadata, '$.source') = 'claude-code';"
   sqlite3 $GAOTTT_DB "DELETE FROM edges WHERE src_id NOT IN (SELECT id FROM nodes) OR dst_id NOT IN (SELECT id FROM nodes);"

   # (d) FAISS index を消す（再 ingest 時に rebuild される）
   rm -f $GAOTTT_DATA_DIR/faiss.index $GAOTTT_DATA_DIR/virtual_faiss.*

   # (e) backend を起動して新形式で再 ingest
   .venv/bin/python -m gaottt.server.mcp_server --transport streamable-http --host 127.0.0.1 --port 7878 --idle-timeout 300.0 &
   sleep 30  # virtual FAISS rebuild 待ち
   .venv/bin/python scripts/load_chat.py ~/.claude/projects/<proj>/ -r --source claude-code
   ```

3. **新規 session だけ新形式で蓄積し、旧 chunks は decay まで放置** — Phase M roll out 後の自然な mass redistribution に任せる。半月〜1 ヶ月で旧 chunks の relevance が下がるはず。

> **筆者の見解**: 1 → 1-2 週間観察 → 改善しないなら 2、の流れが推奨。Phase M の Plan §6.2 と整合する。

## 8. 関連ページ

- [Architecture — Storage & Schema](Architecture-Storage-And-Schema.md) — どこに何が保存されるか
- [Plans — Phase M Mass Conservation](Plans-Phase-M-Mass-Conservation.md) — `original_id` / self-force の設計
- [Plans — Phase K Stellar Supernova Cohort](Plans-Phase-K-Stellar-Supernova-Cohort.md) — `cohort_id` の使われ方
- [Operations — Server Setup](Operations-Server-Setup.md) — REST/MCP のサーバー起動
- [Operations — Compact & Backup](Operations-Compact-And-Backup.md) — 取り込み後のメンテナンス
- [REST API Reference — /ingest, /index](REST-API-Reference.md)
- [MCP Reference — Memory tools (ingest)](MCP-Reference-Memory.md)

## 9. 余白の話

ファイル取り込みは「過去の自分の言葉」を新しい重力場に再配置する作業でもある。書きためたメモを `source="notes"`、Claude Code との対話を `source="claude-code"` で入れておくと、後日 `recall(query="...", persona_context=[...])` が **その日の自分が辿れなかった連想** を引き寄せてくる。Articulation as Carrier — 言葉にしたものは、誰かに（あるいは未来の自分に）引かれることで初めて mass を持つ ([Reflections — Five-Layer Philosophy](Reflections-Five-Layer-Philosophy.md))。取り込みは、その「言葉にする」と「引かれる」の間に橋を架ける作業。
