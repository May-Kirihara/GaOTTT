# Plans — Hardening — Concurrency & Persistence

> 注: これは physics Phase ではなくクロスカッティングな正確性 hardening。`Phase P/Q/R` は Phase N 落選候補 (N-α/β/γ) の予約レターなので、Phase 名前空間を消費しない独立ドキュメントとして扱う ([Roadmap](Plans-Roadmap.md) 参照)。
> 状態: **Stage 1 + 1.5 + 2 完了 (2026-05-18)** — C1/C3/C4 修正、C2 は調査の結果バグでないと確定 (no-op)、L-flaky 解消、HIGH H1-H8 全 8 件修正。`pytest tests/` **515 passed / 1 skipped**、ruff は documented pre-existing 3 件のみ、REST/MCP smoke 両 green。各修正に teeth-having 回帰テスト (H7 のみ infra のため smoke 検証)。**Stage 3 (MEDIUM M1-M11) / Stage 4 (LOW) は未着手** — 本ドキュメントに catalogue 済、順次対応。
> 関連: [Roadmap](Plans-Roadmap.md), [Architecture — Overview](Architecture-Overview.md), [Architecture — Storage And Schema](Architecture-Storage-And-Schema.md), [Operations — Troubleshooting](Operations-Troubleshooting.md), [Phase O — TTT Observability](Plans-Phase-O-TTT-Observability.md)
> 発端: 2026-05-18 — めいさんの依頼によるリポジトリ網羅コードレビュー。4 領域 (storage/concurrency, server, services+config, core physics) を独立レビューエージェントで深掘り、CRITICAL 所見は実コードで裏取り。テストは 483 passed で緑だが、それは **全テストが単一プロセス・直列実行**だから — 並行性・永続化の正確性バグが構造的に顕在化していない (= 並行回帰テストの不在自体が gap)。

## 背景 — なぜ緑のテストでバグが残るか

GaOTTT の推奨運用は **proxy mode (`--transport proxy`)**: N エージェントの軽量 shim → **単一 HTTP backend (engine 1 プロセス)**。つまり「複数リクエストが単一の可変 engine state を `await` をまたいで共有する」が**常態**。一方:

- `recall`/`query` は read-only ではない — Phase I/J の literal な勾配ステップとして `cache.displacement_cache`/`node_cache` を mutate する
- pytest は単一プロセス・直列。並行 interleave も write-behind とのレースも再現しない
- `tests/perf/` も engine 直叩きの単一フロー

結果、**設計同型 (`retrieval = gradient step`) が並行下で非決定的に崩れる**バグ群が緑のまま潜伏。本 hardening はこれを機構レベルで閉じる ― Phase O が「caller に TTT を可視化」したのに対し、ここでは「並行 caller 下でも TTT が正しく 1 step であること」を保証する補完。

## 所見カタログ

裏取り列: ✅ = レビュー時に実コードで検証済 / ◎ = 独立 2 エージェント一致 / ○ = エージェント trace (未再検証) / ✎ = エージェント誤指摘を訂正。

### 🔴 CRITICAL (Stage 1 — 完了)

裏取り列追記: ✅✅ = 実装後に teeth-check (修正前なら落ちる回帰テスト) で fix の有効性まで検証 / ✗ = 調査の結果バグではないと判明 (誤指摘訂正)。

| ID | 箇所 | 内容 | 裏取り | 状態 |
|---|---|---|---|---|
| **C1** | `store/sqlite_store.py:282-298` | `save_node_states` の `INSERT OR REPLACE` (= DELETE+INSERT) が列リスト外の `displacement`/`velocity` を NULL 化。`dirty_nodes` のみ dirty なノード (recall タッチ/revalidate/emotion) は flush で変位が消え再書込されない → 再起動/`load_from_store` で Phase I/J/K の蓄積変位 (中核機構) が silent 消失。deploy 毎 backend kill 運用なので日常的に重力場が削られる。 | ✅✅ | **修正済** column-preserving upsert + 回帰 2 件 |
| **C2** | `core/engine.py:_query_internal`/`_update_simulation` | レビューエージェント (server-H3 + core-C1 が一致) は「query パスに lock ゼロ → 並行 recall の read-modify-write が交錯し勾配ステップ drop/二重」と主張。**実機検証で誤りと判明**: recall の mutation phase (`_update_simulation` + `_update_cooccurrence` はどちらも sync `def`・`await` ゼロ) は asyncio 協調スケジューラ下で**アトミック**、しかも `_update_simulation` は各 `state` を `cache.get_node` で都度フレッシュに読み直す。よって並行 recall でも勾配ステップは drop/二重しない。lock を入れて回帰テストを書いたが、lock 有/無で結果が完全一致 (= 守るべきものが無い) ことを teeth-check で確認 → lock もテストも revert。`config.gamma` 系の真の並行バグは C3 が捕捉済。エージェント 2 体の収束は「もっともらしいが誤った同一メンタルモデル」であり検証ではなかった、という教訓。 | ✗ | **no-op 確定** (コード変更なし) |
| **C3** | `services/memory.py:317-333` | `explore()` が共有 `config.gamma` を `await` またいで monkey-patch。`engine.config` はプロセス単一、`engine.query` の await 中に並行 recall の同期物理 (`_update_simulation` の temperature step) が汚染 gamma を読む。並行 explore 同士は `finally` が汚染値を「復元」し gamma 永続ドリフト。**これが本クラスタ唯一の実在する並行 corruption** (実コード裏取り)。 | ✅✅ | **修正済** per-call `gamma_override` + 回帰 1 件 |
| **C4** | `core/engine.py:reset()` | `engine.reset()` だけ `prefetch_cache.invalidate()` を呼ばない (他 destructive op は全て呼ぶ)。reset 後 `prefetch_ttl_seconds` (既定 90s) 間、消去前のランク済み結果が返り続ける。CLAUDE.md 鉄則違反。 | ✅✅ | **修正済** invalidate + `virtual_faiss_dirty` + 回帰 1 件 |

### 🟠 HIGH (Stage 2 — 完了 2026-05-18)

全 8 件修正 + teeth-having 回帰 (H7 を除き unit/integration、H7 は infra のため smoke 検証)。`pytest tests/` 515 passed / 1 skipped、ruff は documented pre-existing 3 件のみ、REST/MCP smoke 両 green。

| ID | 箇所 | 内容 | 状態 |
|---|---|---|---|
| H1 | `engine._rebuild_faiss_index` / `_rebuild_virtual_faiss_index` | `reset()`→`add()` 間の `ntotal==0` 窓で並行 recall が空 seed = 劣化結果。**C2 が no-op 確定したので lock 案は破棄**、代わりに **fresh `FaissIndex` をローカル構築 → `self.faiss_index` を単一代入で atomic swap** (GIL 下で torn read 皆無、in-flight search は旧 index を完走)。※「`_id_map` 二重化で恒久破壊」はエージェント誤指摘 (`reset()` は `_id_map=[]` する)。 | **修正済** atomic swap + 回帰 1 件 (`is not old` で teeth) |
| H2 | `store/sqlite_store.save_node_states` + `cache.set_node` + `NodeState` | last-write-wins ガード皆無 → 「逆方向上書き罠」未対策。`NodeState.rev` (cache.set_node で単調 +1、永続+reload) + 条件付き upsert `WHERE excluded.rev >= nodes.rev`。stale flush は no-op 行になり `total_changes` 差分で WARNING ログ (検出可能 skip)。 | **修正済** rev guard + 回帰 4 件 |
| H3 | `index/faiss_index.save` + `diagnostics/startup._cleanup_tmp_residuals` | 共有 FAISS dir の `*.tmp` 無条件 unlink が他プロセスの in-flight save を破壊。`f"{path}.{getpid()}.tmp"` pid スコープ命名 + cleanup は「死 pid orphan」「>600s の legacy unscoped」のみ削除、live pid / recent は skip。 | **修正済** pid 命名 + 回帰 4 件 (live-writer skip で teeth) |
| H4 | `index/faiss_index.load` | index 本体と `.ids` の 2 段 `os.replace` 非アトミック → 不一致時に `search` が silent 誤マップ/切り詰め。`load()` で `len(_id_map)==ntotal` 不一致なら `reset()` して startup rebuild に委譲。 | **修正済** load assert + 回帰 3 件 |
| H5 | `config.from_config_file` | per-field env override 不在。ユーザー判断で **実装** を選択 → `GAOTTT_<FIELD>` 読取 (env > json > default)、scalar のみ、bool は `bool("false")==True` トラップ回避、型不正は WARNING で無視、legacy `GER_RAG_<FIELD>` 受理。`Operations-Tuning.md` に優先順位節追記。 | **修正済** env 層 + 回帰 13 件 |
| H6 | `core/prefetch.PrefetchCache` + `engine.query`/`prefetch` | cache key が `(text,k)` のみで `wave_depth`/`wave_k` 無視 → 浅い prefetch が深い recall を汚染。key を `(text,k,wave_depth,wave_k)` に拡張 (一致時のみ hit、prefetch の有用性保持)。 | **修正済** key 拡張 + 回帰 2 件 |
| H7 | `server/mcp_server._install_idle_watcher` | 非推奨 `get_event_loop()`、task handle 破棄、`last_activity` 入口のみ更新で長い ingest/compact 中 SIGTERM しうる。`asyncio.create_task` + handle 保持、**in-flight カウンタ gate** (実行中リクエストありなら shutdown 延期)、request 退出時も `last_activity` 更新。closure `state` 共有のため二重 spawn は元々ガード済。 | **修正済** (信号+sleep の決定論 unit test は brittle = 既出 flaky アンチパターンなので回避、MCP smoke + 35 mcp test で検証) |
| H8 | `engine.index_documents` original_id fallback | `file_path` 衝突 (`README.md` 等) で無関係ノードを全 cross-pair self 扱い → mass 誤抑制。fallback は **絶対パスのみ** grouping、相対/basename は `doc_id` に (false grouping=corruption より missed grouping=軽微、安全方向)。loader は `original_id` 明示なので通常 ingest 不変。 | **修正済** abs-path gate + 回帰 3 件 |

### 🟡 MEDIUM (Stage 3)

**第一弾 (M3 + M4 + M6) 完了 (2026-05-27)** — storage / physics の低リスク safety fix を 1 PR にまとめた。pytest 全 667 pass (Hardening teeth で +8) + ruff clean。M3/M4/M6 各々に teeth-having 回帰テスト (`tests/integration/test_hardening_stage_3_batch_1.py`)。

| ID | 箇所 | 内容 | 状態 |
|---|---|---|---|
| M1 | `sqlite_store.py:136/320/510 等` | `IN (?,?,...)` が SQLite 999 変数上限を無視 → corpus-scale ingest/forget で `OperationalError`、dedup 失敗時は重複書込。`_in_chunks(ids, fn, 900)` で全 call site。 | 第二弾予定 |
| M2 | `memory.py:264-277`, `reflection.py:55-94` | reflect/dormant/summary が 24k ノードで `await store.get_document` を逐次 N 回、event loop ブロック。バッチ `get_documents`/`count_by_source` + `asyncio.sleep(0)` interleave。 | 第三弾予定 |
| **M3** | `sqlite_store.py:reset_dynamic_state` / `hard_delete_nodes` | 多文 destructive op が明示 transaction 外 → 途中例外で部分適用 + 未 rollback。`try: ... await commit() except: await rollback() raise` で囲んだ (aiosqlite の暗黙 transaction を尊重、明示 `BEGIN` 不要)。 | **✅ 完了** |
| **M4** | `sqlite_store.py:save_displacements` / `save_velocities` | dtype 無検査 → float64 で無言ゴミ化 (`load_displacements` が `dtype=np.float32` で frombuffer するので 2× 幅シフト)。`np.ascontiguousarray(disp, dtype=np.float32)` で書き込み前に float32 強制 + 連続化。 | **✅ 完了** |
| M5 | `bm25_index.py:89-209` | tombstone 無限増加、`search` が毎クエリ active postings 再構築 → uptime で p50/p95 劣化。removed 比率 20% で自動 rebuild。 | 第二弾予定 |
| **M6** | `gravity.py:update_velocity` | friction 係数が負/>1 を取りうる (`orbital_friction>1` で `v *= (1-friction) < 0` → 毎ステップ反転 runaway oscillator、negative で amplification)。runtime で `max(0.0, min(1.0, 1.0-friction))` clamp + `config.__post_init__` で `[0,1]` 範囲を WARNING 検出。constant + age-based 両 friction に適用。 | **✅ 完了** |
| M7 | `app.py:287-301` | `/admin/*` が無認証 — REST 到達者が単発 POST で全 mass 不可逆破壊。共有 secret or localhost unix socket。最低限 Architecture 設計判断表に「network 隔離前提・`--host 0.0.0.0` 禁止」明記。 |
| M8 | `memory.py:207-233` | `recall(source_filter=...)` が `top_k*10` 後段フィルタのみで sparse class 空返し。`source_filter` 時 `wave_k` を `wave_k_with_filter` 既定化。 |
| M9 | `cache.py:345-353` | `flush_to_store` の `await` 中に `set_node` → 直後 `.clear()` でその更新が durable から消失。ids ローカル捕捉後 clear、await 中 dirty 分を再追加。 |
| M10 | `engine.py:419-424` | cohort が post-dedup `len(ids)`、dup で閾値割れすると cohort/velocity 無付与で警告なし。スタンプを supernova 適用ガードと一致 + log。 |
| M11 | `maintenance.py:35-56` | `compact` 部分失敗が不可視、`CompactResponse` all-or-nothing。`faiss_rebuilt`/`error` フィールド (optional, DEFAULT安全)。 |

### 🟢 LOW / NIT (Stage 4 — 機会対応)

`faiss_index.save` の fsync 不足 / `get_vectors` 全行列コピー (`reconstruct` 化) / 移行列の `DEFAULT` 欠落 + 移行台帳テーブル不在 / BM25 breakdown 例外無言握り潰し / MCP `relate` ValueError 内部リーク / `shutdown()` cancel 後未 await / `working_on` edge デッド定義 / `dormant` 同名別定義 (reflect vs explore) / proxy 二重 spawn・spawn log fd リーク / `RecallRequest.mode` 無検証 str。

**L-flaky (Stage 1 で発見、回帰網の信頼性に直結)**: `tests/integration/test_engine_query_kick.py` の `StubEmbedder` が `np.random.default_rng(abs(hash(text)))` を使用 → builtin `hash` は `PYTHONHASHSEED` で per-process salt されるため埋め込み幾何が run 毎に変わり、`test_query_kick_drifts_...` / `test_stage3_gate_dampens_...` が run-to-run で flap (pre-change baseline でも 5 run 中 3 fail を確認、本 hardening の変更とは無関係)。CLAUDE.md「よくある罠: ランダム埋め込み fixture は flaky」の現存違反。修正案: `hashlib.sha256(text.encode()).intdigest()` 等の安定ハッシュで seed、または `test_engine_archive_ttl.py:StubEmbedder` のトークンベース決定論埋め込みに統一。**緑のテストにバグが潜む** を主題とする本ドキュメントにとって、flaky テストは「赤が信用されない」逆向きの同じ病。**修正済 (Stage 1.5, 2026-05-18)**: `_embed` を `int.from_bytes(hashlib.sha256(text).digest()[:8])` 安定 seed + 共有 base 方向 + 小摂動 (相互 cosine ~0.97 で wave 連結を保証、テストの物理的意図を保持) に。PYTHONHASHSEED 0/1/42 で決定論的に 6 passed。`test_engine_concurrent.py` の StubEmbedder も同 anti-pattern を伝播しないよう安定 seed 化。

## 修正方針 (Stage 1 — CRITICAL)

### C1 — column-preserving upsert
`INSERT OR REPLACE` を `INSERT INTO nodes (...) VALUES (...) ON CONFLICT(id) DO UPDATE SET <14列のみ>` に変更 (SQLite ≥3.24 upsert)。未指定の `displacement`/`velocity` は ON CONFLICT 経路では UPDATE されず保持、新規 INSERT 経路では元々 NULL で正しい。回帰テスト: displacement set → 別理由 (mass) で dirty 化のみ → flush → `load_displacements` で生存 assert。

### C2 — 調査の結果 no-op (コード変更なし)
当初 `self._sim_lock = asyncio.Lock()` を入れ `_query_internal` を wrapper 化したが、**teeth-check で「守るべきものが無い」と判明し全 revert**。論拠:

1. recall の mutation phase = Step 5 (return_count) + `_update_simulation` + `_update_cooccurrence`。`_update_simulation` も `_update_cooccurrence` も sync `def` で本体に `await` ゼロ (mutation 区間に唯一あった `await self.store.get_node_states` は scoring loop 側 = read phase。`get_node_state` の await は別メソッドで recall 経路外)。
2. asyncio 協調スケジューラは `await` でしかコルーチンを切り替えない → `await` の無い同期ブロックは**実行完了までアトミック**。`_update_simulation` は各 `state` を `cache.get_node` で都度フレッシュに読み直し `+=` して `set_node` する。よって並行 recall B の mutation phase は A の mutation phase に完全に先行 or 後続するだけで、interleave しない = 勾配ステップは drop も二重もしない。
3. 検証: `if True:` で lock を一時無効化し並行 recall ×12 vs 直列 ×12 の総 mass 増分を比較 → **完全一致**。lock 有/無で差が出ない = 回帰テストに歯が無い = 守るべき不変条件が存在しない。
4. lock を残すと「N agents → engine 1 プロセス」推奨構成で全 recall の `await store.get_document` ごとの DB I/O まで直列化する実 latency regression を、asyncio が既に防いでいる corruption の対価に払うことになる → 純負。

エージェント 2 体 (server-H3 + core-C1) が同一の lost-update メンタルモデルに収束したが、それは「もっともらしいが mutation phase の同期性を見落とした」誤り。**並行性で実在するのは C3 のみ** (`config.gamma` は service 層で set → engine 層 await 中に別 recall の同期物理が読む、という mutation と await が別関数にまたがる真のレース)。教訓: 複数エージェントの収束 ≠ 検証。reviewer claim は実行モデルまで降りて再現させる。

### C3 — gamma_override パラメータ化
`engine.query(..., gamma_override: float | None = None)` → `_query_internal` → 物理計算で `config.gamma` の代わりに `gamma_override if gamma_override is not None else config.gamma` を使用 (`wave_depth`/`wave_k` と同じ thread パターン)。`services/memory.explore` の monkey-patch 削除、`gamma_override=config.gamma*(1+diversity*20)` を渡す。MCP/REST の `explore` シグネチャは不変 (内部引数のみ追加、parity 影響なし)。回帰テスト: 並行 explore+recall で `config.gamma` が不変。

### C4 — reset invalidate
`engine.reset()` 末尾 (`store.reset_dynamic_state()` 後) に `self.prefetch_cache.invalidate()` + 兄弟 reset と整合のため `self.cache.virtual_faiss_dirty = True`。回帰テスト: prefetch → reset → 同一クエリ recall が新 state を返す (cache hit しない)。

> **parity**: C1〜C4 は MCP tool / REST endpoint を**追加しない** (internal な engine/store/services 修正のみ) ため Phase S の 3 点セット鉄則は非該当。ただし実装フロー通り両 smoke (`rest_smoke.py`/`mcp_smoke.py`) + `pytest tests/` + 該当 perf tier を実行する。

## Stage 構成

| Stage | 対象 | 規模 | 状態 |
|---|---|---|---|
| 1 | C1 / C3 / C4 修正 + C2 調査 | 小 (localized) | **完了 (2026-05-18)** — 487 passed, ruff clean, REST/MCP smoke green |
| 1.5 | L-flaky (回帰網の信頼性) | 小 | **完了 (2026-05-18)** — `StubEmbedder` を安定 sha256 seed + 共有 base 幾何に。PYTHONHASHSEED 0/1/42 で決定論 6 passed |
| 2 | HIGH H1-H8 | 中 | **完了 (2026-05-18)** — 全 8 件修正、515 passed / 1 skipped、ruff pre-existing 3 のみ、REST/MCP smoke green |
| 3 | MEDIUM M1-M11 | 中 | 未着手 |
| 4 | LOW/NIT | 小 (機会対応) | 未着手 |

横断: **並行回帰テスト基盤** (`tests/integration/test_engine_concurrent.py`) を Stage 1 で新設 (C3/C4 の teeth-having 回帰 + C2 が defect でない旨を docstring に記録)。以降の Stage が回帰チェックに使う。テストが緑でバグが残った根本原因 (並行 path 未カバー) を機構で閉じる。C1 回帰は `tests/unit/test_sqlite_store_displacement_preserve.py`。

## 関連

- [Architecture — Overview](Architecture-Overview.md) — 設計判断の記録表に simulation lock 判断を追記
- [Operations — Troubleshooting](Operations-Troubleshooting.md) — 並行下の症状エントリ追加
- [Phase M — Mass Conservation](Plans-Phase-M-Mass-Conservation.md) — C1 が守る蓄積変位の出自
