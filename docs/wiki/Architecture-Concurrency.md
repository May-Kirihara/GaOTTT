# Architecture — Concurrency

複数のプロセス（複数 MCP サーバー、複数エージェント）が同 DB を共有して並行アクセスする際の安全設計。

## SQLite WAL モード

```python
# gaottt/store/sqlite_store.py
PRAGMA journal_mode = WAL              # 並行 read + 単一 write
PRAGMA synchronous = NORMAL            # 性能とのバランス
PRAGMA busy_timeout = 30000            # ロック中は最大 30 秒待機
PRAGMA wal_autocheckpoint = 2000       # WAL 肥大化抑制
```

- **WAL モード**: 読み込みは複数プロセスから同時に可能、書き込みは 1 プロセスずつ
- **busy_timeout = 30000ms**: 書き込みロック取得失敗時は 30 秒リトライ
- **wal_autocheckpoint = 2000 pages (~8 MB)**: WAL ファイルの肥大化を防ぐ

## マルチプロセスでの動作

| 操作 | 動作 |
|---|---|
| 既存ノードの recall (mass/displacement 蓄積) | DB レベルで共有、cache はプロセス毎に独立 |
| 新規 remember (新ノード追加) | DB に書かれ、書き込みプロセスの FAISS は in-memory 即時反映、disk への永続化は `faiss_save_interval_seconds`（既定 5s）周期。別プロセスは startup 時に load するため、その時点の disk 状態が見える |
| edges/relations | DB に書かれる、別プロセスの cache は次回リロードまで stale |

### FAISS の罠（write-behind 導入で軽減）

各プロセスはそれぞれ FAISS インスタンスを持つ。歴史的に「`shutdown()` まで disk に save しない」設計だったため、shutdown しない長期常駐プロセス（MCP サーバー等）の `remember` は他プロセスから永久に invisible だった。

これは **FAISS write-behind** で解消（2026-05-10 修正）:

```python
# core/engine.py
async def _faiss_save_loop(self) -> None:
    """Background save: flush in-memory FAISS additions to disk every
    faiss_save_interval_seconds. Without this, brand-new `remember`
    lives only in the writing process's RAM until shutdown(),
    making other processes' recall() blind to it."""
```

- 周期は `config.faiss_save_interval_seconds`（既定 5s、`0` で無効化）
- `index_documents` と `_rebuild_faiss_index` で `_faiss_dirty=True` を立てる
- loop は `_faiss_dirty=False`（claim）→ `to_thread(faiss_index.save, path)`（IO はスレッドへ）→ 失敗時のみ `True` に戻す
- `shutdown()` で停止前に最終 save を呼ぶ（残った dirty を flush）
- 残る race: 「save 中の新規 add は次の tick で saved」（実用上影響なし）
- 残る競合: A と B が**同時に save** すると後勝ち → 重要書き込み後は `engine.compact(rebuild_faiss=True)` で再構築可（保険）

### 防御的境界チェック

`faiss_index.search` は `_id_map[idx]` の境界を明示的にチェック:
```python
if idx < 0 or idx >= id_map_len:
    continue  # IndexError ではなく skip
```

`.ids` ファイル破損やインデックスとマップのズレに対する防御。

## アーカイブ後の挙動

`archive`/`forget`/`merge`/`compact` 後は **prefetch cache を invalidate** する:

```python
# core/engine.py
async def archive(self, node_ids: list[str]) -> int:
    ...
    if affected:
        self.prefetch_cache.invalidate()
```

これにより destructive op 後の stale な hit を防ぐ。

## write-behind の安全性

`CacheLayer` は dirty フラグ付きで in-memory に書き込み、5 秒間隔（既定）でバックグラウンドタスクが flush:

```
remember
  ↓
cache.set_node (dirty=True)
  ↓
dirty_nodes に追加
  ↓
5 秒後 (or shutdown 時)
  ↓
flush_to_store(): SqliteStore に書き込み
```

shutdown 時に明示的 `flush_to_store` を呼ぶので、graceful な終了であればロスなし。

`Ctrl+C` 等で強制終了すると、最後の 5 秒分の dirty な変位等が失われる可能性あり（ただしドキュメント本体と embedding は永続化されているので再構築可）。

## 確認・運用

ベンチマーク中に並列実行をシミュレートしたい場合は隔離 DB を使用:

```bash
.venv/bin/bash scripts/run_benchmark_isolated.sh
# → /tmp/gaottt-bench/ で隔離実行、本番 DB は不可触
```

→ [Operations — Isolated Benchmark](Operations-Isolated-Benchmark.md)

## 関連

- [Storage & Schema](Architecture-Storage-And-Schema.md) — テーブル定義
- [Operations — Compact & Backup](Operations-Compact-And-Backup.md) — FAISS rebuild の詳細
- [Operations — Troubleshooting](Operations-Troubleshooting.md) — DB lock 関連
- [Multi-Agent Experiment](Research-Multi-Agent-Experiment.md) — 実運用での発見（busy_timeout 未設定で連続失敗 → 修正の経緯）
