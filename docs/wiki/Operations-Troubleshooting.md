# Operations — Troubleshooting

既知の問題と対処。

## クエリスコアが初回だけ極端に低い

正常動作。初回クエリ時、`last_access` がインデックス時刻のため `decay = exp(-δ × 経過時間)` が非常に小さくなる。2 回目以降は decay ≈ 1.0。

## メモリ使用量が大きい

- embedding モデル: ~1.5GB（GPU VRAM）
- FAISS インデックス: 768次元 × 4byte × ドキュメント数（100K 件で ~300MB）
- ノードキャッシュ: ドキュメント数に比例

## SQLite ロックエラー (`database is locked`)

複数 MCP サーバー（複数エージェント並行運用）で発生する。`PRAGMA busy_timeout = 30000` を設定済（最大 30 秒待機）が、それでも頻発するなら:

- write 頻度が高い → `flush_interval_seconds` を伸ばす
- ロック待ちが長い → MCP サーバープロセスを必要数だけに減らす

→ 詳細: [Architecture — Concurrency](Architecture-Concurrency.md)

## `recall` で `list index out of range`

`faiss_index._id_map` と FAISS の `ntotal` がズレた場合に発生していた問題。修正済（境界チェック追加）。

復元方法: `engine.compact(rebuild_faiss=True)` で FAISS を active ノードから再構築。

## archived ノードが大量に溜まった

`forget(hard=False)` の蓄積、または TTL hypothesis の自動 expire が積み重なると、FAISS に「使われないベクトル」が残り続ける。

**対処**: `compact(rebuild_faiss=True)` を週次〜月次で実行。

## 重力衝突合体 (merge) が暴走する

`compact(auto_merge=True, merge_threshold=...)` の閾値が低すぎると、似て非なる記憶を融合してしまう。

**対処**:
- `merge_threshold` を 0.95 以上に保つ
- `auto_merge` は default OFF。明示的に有効化したときのみ動く
- 心配な場合は手動で `reflect(aspect="duplicates")` → 中身を確認 → `merge(node_ids=[...])`

## 確信度が古いまま下がっていく（F7）

`certainty_half_life_seconds`（既定 30 日）を超えると certainty boost が指数減衰。`revalidate(node_id)` を呼ぶと last_verified_at が更新され、boost が回復。

## prefetch のヒット率が低い（F6）

`prefetch_status` で `hit_rate` が低い場合:
- クエリ文字列が完全一致しない → LLM 側で「prefetch と recall に渡す query を完全一致させる」プロトコル徹底
- TTL が短すぎる → `prefetch_ttl_seconds` を伸ばす
- destructive op が頻繁 → 設計上 invalidate される。頻発するなら戦略再考

## タスクが知らないうちに消える（Phase D）

`source="task"` は既定 30 日、`source="commitment"` は既定 14 日で auto-expire。

**対処**:
- `revalidate(node_id)` で意識的にコミットメントを生かし続ける
- `reflect(aspect="commitments")` を週次儀式に
- TTL を伸ばす（`config.py` の `default_*_ttl_seconds`）

## inherit_persona の出力が薄い

新セッションで `inherit_persona()` を呼んだのに「No values declared」しか返ってこない場合:
- value/intention/commitment を実際に declare していない
- agent ソースの記憶が混ざっている → `inherit_persona` は明示的に source 指定が必要
- 数が多すぎて切り詰められている → `reflect(aspect="values", limit=20)` で全件確認可能

## 異常終了後の起動

フラッシュされていない dirty 状態は消失するが、ドキュメントと embedding は保全される。動的状態（mass, temperature）はクエリを繰り返すことで自然に再構築される。

→ 関連: [Architecture — Concurrency](Architecture-Concurrency.md), [Compact & Backup](Operations-Compact-And-Backup.md)
