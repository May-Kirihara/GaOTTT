# Operations — Migration

`scripts/migrate.py` は GaOTTT を旧バージョン (主に main) から最新 dev に上げる時に走らせる **データ migration ツール**。重力物理の breaking change を跨いで安全にアップグレードするための one-time な処理 (Phase G の Stage 0 priming など) を、versioned + idempotent な step として順次適用する。

## いつ使うか

- GaOTTT を `git pull` で更新した後、**MCP server を再起動する前** に一度走らせる
- 新規 install では原則不要 (走らせても "no migrations to apply" で終わる)
- 各 release で `docs/wiki/Operations-Migration.md` の表に新 step が増える可能性がある

## 走らせ方

```bash
# 0. (推奨) 既存 MCP server を停止
pkill -f gaottt.server.mcp_server
ps -ef | grep gaottt   # 停止確認

# 1. dry-run で何が起きるか確認
.venv/bin/python scripts/migrate.py

# 2. (推奨) backup 付きで apply
.venv/bin/python scripts/migrate.py --apply --backup

# 3. MCP server を再起動 (新物理が live になる)
# (各環境のやり方で再起動)

# 4. 任意: smoke で動作確認
.venv/bin/python scripts/mcp_smoke.py
```

## CLI

| flag | 動作 |
|---|---|
| (引数なし) | dry-run、適用予定の plan を表示するだけ |
| `--list` | 既知 migration を全部 list (APPLIED/PENDING/SKIP) して終了 |
| `--apply` | 実際に migration を実行する |
| `--apply --step M001` | 特定の version だけ実行 |
| `--apply --backup` | apply 前に `data_dir` 全体を `data_dir.backup-<timestamp>/` に複製 |
| `--apply --force` | live MCP プロセス検出を無視 (推奨せず) |

dry-run は **読み取り専用** で、MCP プロセス検出も飛ばす。実 mutation は `--apply` 時のみ。

## 安全装置

`migrate.py` は以下の rail を持つ:

1. **Dry-run by default** — `--apply` がないと何も書かない
2. **MCP プロセス検出 (apply 時のみ)** — `pgrep -f gaottt.server.mcp_server` で live process があれば refuse。理由は cache 逆方向上書き罠 ([Architecture — Concurrency](Architecture-Concurrency.md))。古い cache を持つプロセスが write-behind tick で migrate.py の書き込みを **上書きし返す** ため、必ず止めてから走らせる
3. **Backup** — `--backup` で data_dir 全体を timestamp 付きでコピー。production では強く推奨
4. **Idempotency** — 各 migration は `needs_apply` (state からの検出) + `_migrations` 台帳 (DB 内テーブル) の **両方** で重複を防ぐ。台帳が消えても `needs_apply` が「もう不要」と判断する強い detector を持つ設計
5. **Verify** — 各 step は適用後に `verify()` を走らせ、期待状態になっているか確認。verify 失敗時は台帳に記録 **しない** (再 apply の余地を残す)

## 適用台帳 (`_migrations` テーブル)

`gaottt.db` 内の SQLite テーブル:

```sql
CREATE TABLE _migrations (
    version    TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    applied_at REAL NOT NULL,
    notes      TEXT
)
```

存在しなければ初回起動時に自動作成。手動で行を消すと「もう一度 apply できる」状態に戻るが、`needs_apply` の detector が「不要」と判断すれば結局 skip される (二段防御)。

## 既知 migration (バージョン履歴)

| version | name | 何をするか | 必要な前提条件 |
|---|---|---|---|
| **M001** | phase-g-priming | 全 active node に `compute_gravity_kick` を 1 step 適用し、Phase G 以前に index された doc に initial displacement / velocity / mass を与える | `mass=1.0 / displacement=0 / velocity=0` の node が active node の 50% 以上ある場合に PENDING 判定。既存 displacement は **加算** されるので recall history は保存される |

## 新しい migration を追加する手順 (開発者向け)

各 release で物理 breaking change を導入した時:

1. **検出ロジック** — DB state から「この migration が必要か」を判定する純粋な関数を書く (`async def _mXXX_needs_apply(engine, config) -> tuple[bool, str]`)。state-driven にすることで `_migrations` 台帳が消えても正しく動く
2. **適用ロジック** — `async def _mXXX_apply(engine, config) -> str` で実際の処理。Pydantic Response も print も自由、戻り値は台帳に記録される notes 文字列
3. **検証ロジック** — `async def _mXXX_verify(engine, config) -> tuple[bool, str]` で期待 state を確認
4. **登録** — `scripts/migrate.py` の `MIGRATIONS` リストに `Migration(...)` を順序通りに append
5. **ドキュメント** — このページの「既知 migration」表に行を追加

`scripts/migrate.py` 自体のテストは現時点では tests/ に統合せず、手動 smoke ([`scripts/migrate.py` docstring 参照](../../scripts/migrate.py)) のみ。将来 migration が増えてきたら `tests/integration/test_migrate.py` を作る方針。

## トラブルシュート

### `ERROR: detected gaottt.server.mcp_server processes`

`pkill -f gaottt.server.mcp_server` で停止してから再実行。**`--force` で押し通すと cache 上書きで migration が無に帰す可能性がある**。

### `ERROR: no GaOTTT database at ...`

`config.db_path` の DB が存在しない。fresh install なら MCP server を一度起動して `remember()` を呼べば自動で作られる。GER-RAG 系譜なら `scripts/migrate-from-ger-rag.sh` を先に。

### migration が verify failed で台帳に記録されない

`needs_apply` は引き続き True を返すので、原因を調べて修正後に再 apply できる。`scripts/bootstrap_report.py` で DB の現状を確認するのが第一歩。

### 「適用済みだったはずなのに再度 PENDING と出る」

`_migrations` テーブルが消えている可能性 — `compact(rebuild_faiss=True)` などで誤って削除した? `migrate.py --list` の出力と `sqlite3 gaottt.db "SELECT * FROM _migrations"` を比較。台帳が消えても `needs_apply` が「もう不要」と判断すれば二度目の apply は state を変えない (idempotency)。

## 関連

- [Architecture — Concurrency](Architecture-Concurrency.md) — bidirectional cache overwrite の罠
- [Operations — Compact & Backup](Operations-Compact-And-Backup.md) — 定期 maintenance
- [Operations — Server Setup](Operations-Server-Setup.md) — MCP server 起動・停止
- [Plans — Phase G — Memory Genesis](Plans-Phase-G-Memory-Genesis.md) — M001 が解決する問題の元設計
- [Plans — Phase I — Free Star Movement](Plans-Phase-I-Free-Star-Movement.md) — Phase I 系の物理変更
- [`scripts/prime_gravity.py`](https://github.com/May-Kirihara/GaOTTT/blob/main/scripts/prime_gravity.py) — M001 と同等処理の specialist 版 (advanced user 向け CLI、より細かい引数あり)
