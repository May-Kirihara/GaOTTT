# Operations — Troubleshooting

既知の問題と対処。

## クエリスコアが初回だけ極端に低い

正常動作。初回クエリ時、`last_access` がインデックス時刻のため `decay = exp(-δ × 経過時間)` が非常に小さくなる。2 回目以降は decay ≈ 1.0。

## 別プロセスから新規 `remember` が見えない（FAISS stale）

**症状**: 別プロセスの MCP サーバー / opencode エージェント等で `remember` した直後、自プロセスの `recall` でその memory が一切 surface しない。`reflect(aspect="summary")` の `Total memories` は増えていることがある（SQLite は WAL で共有されるが FAISS index はプロセス毎独立）。

**原因（歴史的バグ、2026-05-10 修正済み）**: かつて `engine.shutdown()` でしか FAISS が disk に save されなかった。MCP サーバー等の長期常駐プロセスは shutdown しないため、新規 vector が永久に in-memory のまま、他プロセスからは invisible だった。

**修正**: `faiss_save_interval_seconds`（既定 5s）周期の write-behind loop を導入（[Architecture — Concurrency](Architecture-Concurrency.md) 参照）。

**それでも見えない場合の対処**:
- 自プロセスを再起動（startup() で disk から最新 FAISS を load）
- 修正前の DB で長期間積もった「FAISS に無く SQLite/cache にのみ存在する」ノードがある場合、`engine.compact(rebuild_faiss=True)` で全 active から再構築すれば解消（diagnostics: `len(faiss._id_map - cache.node_cache.keys())` と逆向きを比較）
- `faiss_save_interval_seconds=0` に設定してしまっていないか確認（disable 設定）

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

## `tag_filter` / `persona_context` で注入した node が recall 結果に出ない

**症状**: `recall(query, tag_filter=["foo"])` を呼んだのに、タグ "foo" を持つ node が結果に表示されない。`reflect` で確認すると node 自体は存在する。

**原因（2026-05-12 修正済み）**: Phase J Stage 2 の `injected_ids` が seed pool の `initial_k` 上限（既定 ~3 程度）を超えると、溢れた node が wave propagation の `reached` dict に入らず、Step 3 の `original_emb = faiss_index.get_vectors(reached_ids)` で `None` になり results から除外されていた。FAISS にベクトルが存在していても surface しないという非直感的な挙動。

**修正内容** (`gaottt/core/gravity.py`): wave 終了後に `injected_ids` の欠落 node を `reached[nid] = 1.0`（direct seed と同等の force）で強制追加するパスを追加。これにより injected node 数が `initial_k` を超えても全件が scoring に参加する。

**修正前の回避策**（旧バージョン対応時）:
- `top_k` を小さくして `injected_ids` が `initial_k` を超えないようにする
- 注入対象を 1 件に絞って `persona_context=[specific_id]` を使う

## FAISS と SQLite のカウントが合わない

**症状**: `recall` で存在するはずの node が surface しない、または `compact(rebuild_faiss=True)` を実行しても FAISS count が SQLite count より少ないまま。

**診断**: `scripts/verify_faiss_recovery.py` を実行:
```bash
.venv/bin/python scripts/verify_faiss_recovery.py [node_id_prefix ...]
```
`Gap > 0` ならば SQLite にはあるが FAISS にない node が存在する。特定 ID を引数に渡すと IN FAISS / MISSING を確認できる。

**原因 A — write-behind フラッシュ前のプロセス終了**: MCP サーバーが `faiss_save_interval_seconds`（既定 5s）周期のフラッシュ前に異常終了した場合、その session の `remember` が SQLite には保存されているが FAISS disk には反映されない。次回起動時に FAISS を disk から load するため欠落が続く。

**原因 B — `_rebuild_faiss_index` の旧バグ（2026-05-12 修正済み）**: `compact(rebuild_faiss=True)` が FAISS に既存のベクトルのみ再構築し、SQLite/cache にあるが FAISS に載っていない node を再埋め込みしなかった。

**修正内容** (`gaottt/core/engine.py`): `_rebuild_faiss_index` が `vecs = faiss_index.get_vectors(active_ids)` で返らなかった `missing_ids` を `store.get_document()` で content 取得 → `embedder.encode_documents()` で再埋め込み → FAISS 追加するパスを追加。これにより `compact(rebuild_faiss=True)` が SQLite 全 active node を確実に FAISS に収録する。

**対処手順**:
1. `scripts/verify_faiss_recovery.py` でギャップを確認
2. MCP サーバーを再起動（修正済みコードを読み込む）
3. `compact(rebuild_faiss=True)` を実行
4. 再度 `verify_faiss_recovery.py` で `Gap: 0` を確認
