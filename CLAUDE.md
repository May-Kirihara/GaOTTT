# GaOTTT Development Guidelines

*(formerly GER-RAG — 改名プロジェクト完了: Phase R0-R11、2026-04-21)*

Last updated: 2026-05-13 (Phase M Stage 1 — Mass Conservation。Phase L Stage 1 acceptance で露呈した「source=file/tweet が agent 知識の top1 を奪う」根を **1 file = 91 chunks 平均の内輪取引 mass inflation** と特定し、`is_self_force(a, b) = (original_id 一致 or cohort_id 一致)` の **source 分岐ゼロの単一規則** で mass update を filtering。`propagate_gravity_wave` に per-parent attribution (`out_attribution` 引数) を追加、`engine._update_simulation` で self-force 寄与をスキップ — temperature/sim_history は total force のまま保持 (フィルタは mass update **のみ**)。共起 BH (`compute_bh_acceleration`) は `compute_acceleration` から呼び出し削除し、`compute_mass_bh_acceleration` (連続 `bh_factor = tanh((m-θ)/σ)`、`θ-2σ` 以下クランプ 0) に置換 — source 分岐ゼロ、mass しきい値だけで attractor 化。`cache.set_original/set_cohort` + `SqliteStore.get_all_originals/get_all_cohorts` (JSON1、`COALESCE(metadata.original_id, metadata.file_path)` で既存 DB 無 migration)。`engine.index_documents` が supernova batch で `cohort_id = uuid4().hex[:12]` を生成。reset API は MCP 非露出 (REST `POST /admin/reset_masses` + `scripts/reset_masses.py`)。`mass_conservation_enabled=False`/`mass_bh_enabled=False` で個別 rollback。**Articulation as Carrier (id=9a954c62) の literal な物理実装** — `if not is_self_force(...)` の 1 行が「経験は言葉にすることで初めて重力を持つ」を **「言葉にした上で誰かに引かれることで mass を持つ」** と精密化、persona も別格扱いしない (使用頻度こそが重力)。Phase L Stage 1 — Hybrid Retrieval。Phase J 完遂後の本番 acceptance で露呈した「Surface 7/7 ✅ / Semantic 整合 0-1/7 ⚠️」分離 — embedder の hidden ranking が dominant signal という構造的境界 — を seed pool layer の構造的拡張で解決。`_union_pool` を raw ∪ virtual ∪ BM25 の 3-way に拡張、RRF fusion (Cormack 2009 標準) で scale 不変。新規 `gaottt/index/bm25_index.py` (numpy in-memory) + `tokenizer.py` (char 3-gram default、Sudachi optional extra)。LLM 不要・ローカル完結、`hybrid_bm25_enabled=False` で 1 行 rollback。Phase H Stage 5 — wave neighbor expansion を virtual FAISS に切り替え。Phase H Stage 4 で seed pool は raw∪virtual だったが per-frontier `search_by_id` は raw のままだった設計上の不整合を解消。「星同士の引力」原則を wave 全段で literal に。同日 virtual FAISS write-behind 導入 (`virtual_faiss_save_interval_seconds`) — Phase I/J query attraction で蓄積した displacement が compact を待たず他プロセスに伝播。Phase J 完遂 — Stage 3 で forced 内 query-aware ordering (raw_score 順) と prefetch/explore への persona_context+tag_filter parity を実装。retrieval geometry の三段構造 [pool 入場 / pool 内 rerank / forced 内 ordering] が完成。Stage 1: auto-detect graph traversal。Stage 2: explicit force injection。Phase K Stage 1 — Stellar Supernova Cohort。Phase I Stage 3 — mass-gated query attraction。Phase G/H — FAISS write-behind, genesis kick + dream + Stage 0 priming, mass-aware / source-aware / dynamic / virtual FAISS の seed redesign)

GaOTTT = **Gravity as Optimizer, Test-Time Training**。物理として設計した重力・軌道力学の更新則が、retrieval のスコアを確率的勾配シグナルと見る解釈の下で、Heavy ball SGD + Hebbian gradient + L2 の Verlet 積分と **項ごとに対応する構造的同型**に書けることが判明した。つまり **物理として書いたものが、同じ形で TTT オプティマイザとしても読める**。Phase I Stage 2 (2026-05-11) でこの対応は構造的同型から **実装としての実体** に進んだ — `compute_acceleration` の 4 番目の項 `a = (α · score · gate / m_i) · (q - pos_i)` が literal な勾配ステップを供給し、recall するたびに retrieved nodes の displacement が query 方向に nudge される。Stage 3 (2026-05-13) で `gate = tanh(m_i / θ)` を追加 — 新規 (低 mass) ノードは anchor に守られて 1 度の recall で暴走せず、mature ノードは満額の勾配を受ける世代論的挙動になった (単一アトラクタ pathology の物理的矯正)。Phase J Stage 1 (2026-05-13) で人格層を retrieval に翻訳した — declared value/intention/commitment から `fulfills`/`derived_from` を N hop traverse、seed step で `α_persona × proximity` を加算。物理を曲げるのは質量だけではなく、宣言された意図もまた重力を持つ。Phase K Stage 1 (2026-05-13) で記憶生成の集合性を物理化した — 1 batch の `remember` を 1 超新星爆発として読み、batch 内 N 件に相互 edge と outward velocity を付与。単独では塵だった新規ノード群が、超新星残骸 cluster として互いの重力で seed pool に届く。Articulation as Carrier の単数性から複数性への literal な拡張。Hooke は raw embedding を anchor として引き続き保持するので transient force であって anchor migration ではない。その上に共有時のアストロサイト的協調と Phase D の人格保存基盤が積み上がっている。詳細思想は [`docs/wiki/Reflections-Five-Layer-Philosophy.md`](docs/wiki/Reflections-Five-Layer-Philosophy.md)（物理 → 生物 → TTT 機構 → 関係 → 人格の五層）。

## Tech Stack

Python 3.11+（推奨 3.12）/ FastAPI + uvicorn / aiosqlite + msgpack / FAISS IndexFlatIP / sentence-transformers (RURI-v3-310m) / numpy / pydantic v2 / pytest + pytest-asyncio / **uv**（pip 禁止）

## Project Layout

```text
gaottt/                         # メインパッケージ（formerly ger_rag/）
├── config.py                   # 全ハイパーパラメータ + 後方互換レイヤ（GER_RAG_* env / legacy path）
├── core/                       # engine / gravity / scorer / extractor / clustering / collision / prefetch / types
├── embedding/ruri.py           # キャッシュ自動検出
├── index/faiss_index.py        # 境界チェック付き search
├── store/                      # base / sqlite_store (自動マイグレーション) / cache (write-behind + evict_node)
├── graph/cooccurrence.py       # 無向共起グラフ
├── services/                   # ★ Phase S: REST と MCP の共有ビジネスロジック層
│   ├── runtime.py              #   build_engine factory（両サーバ共通）
│   ├── memory.py               #   remember / recall / explore / forget / restore / revalidate / auto_remember
│   ├── relations.py            #   relate / unrelate / get_relations
│   ├── maintenance.py          #   merge / compact / prefetch / prefetch_status
│   ├── reflection.py           #   reflect の全 15 aspect
│   ├── phase_d.py              #   commit / start / complete / abandon / depend / declare_* / inherit_persona
│   ├── ingest_service.py       #   ingest
│   └── formatters.py           #   Pydantic → MCP 向け人間可読文字列（REST は使わない）
└── server/                     # app.py (REST, MCP parity) + mcp_server.py (MCP "gaottt", 25 ツール)
tests/{unit,integration}/       # 138 ケース、すべて asyncio
scripts/                        # load_csv / load_files / test_queries / visualize_3d / benchmark / run_benchmark_isolated.sh / eval_* / migrate-from-ger-rag.sh / migrate.py (★ versioned data migration、breaking change で新 step を追加)
docs/                           # wiki/ が SoT、その他 docs/*.md は redirect、docs/research/ は研究アーカイブ
SKILL.md                        # MCP がランタイムで読む（英語、name: gaottt）
.claude/skills/gaottt/SKILL.md  # ★ 上記の同期コピー（必ず両方更新）
CLAUDE.md                       # このファイル
```

## Source-of-Truth マップ — どこを編集するか

| 種別 | SoT | 注意点 |
|---|---|---|
| MCP プロトコル定義 | `SKILL.md` + `.claude/skills/gaottt/SKILL.md` | **両方を必ず同期**（cp で OK） |
| Claude Code 指示 | `CLAUDE.md`（このファイル） | 簡潔に保つ（毎セッション読まれる） |
| GitHub フロントページ | `README.md` / `README_ja.md` | trim 済み、詳細は Wiki リンク |
| 設計判断・アーキテクチャ・実装計画 | **`docs/wiki/*.md`** | 旧 `docs/*.md` は redirect 済 |
| 運用ガイド・トラブルシュート | **`docs/wiki/Operations-*.md`** | |
| ハイパーパラメータ表 | **`docs/wiki/Operations-Tuning.md`** | コードは `gaottt/config.py` |
| MCP ツールリファレンス | **`docs/wiki/MCP-Reference-*.md`** | |
| REST API リファレンス | **`docs/wiki/REST-API-Reference.md`** | Phase S 以降、MCP と parity |
| サービス層 (Phase S) | **`gaottt/services/*.py`** | engine を叩き Pydantic を返す純関数。REST + MCP が共通で使う。`services/formatters.py` だけは MCP 専用 |
| 研究レポート（長文成果物） | `docs/research/*.md` | Wiki Research-* から要約・リンク |
| 全体 Wiki ナビ | `docs/wiki/_Sidebar.md` + `docs/wiki/Home.md` | 新ページ追加時は両方更新 |

## 実装フロー — 新機能を追加するとき

> **★ 鉄則: MCP と REST は常に同時に更新する**
> Phase S で両者は `gaottt/services/*.py` を共通の真実の源とする構造になった。
> **新しい能力を MCP に足すなら REST にも同じターンで足す、逆も同じ**。
> 片方だけに機能を乗せる PR は **作らない**（parity 崩壊 = サービス層の存在意義が消える）。
> 動作確認も両トランスポートで: `scripts/rest_smoke.py` + `scripts/mcp_smoke.py` を走らせる。
> 例外: `/reset` は REST 専用（LLM に破壊的 reset を露出しない設計判断）— 新たな例外を作るなら Architecture-Overview.md の設計判断表に理由を書く。

1. **計画書を確認** — `docs/wiki/Plans-Roadmap.md` で全体像、関連 Plans-* で詳細
2. **TaskCreate でタスク分割** — 実装/テスト/ドキュメント/ベンチに分ける
3. **実装**（順序）:
   - `core/types.py` に Pydantic モデル追加（Request/Response 両方）
   - `store/sqlite_store.py` でスキーマ追加 + 自動マイグレーション (`ALTER TABLE ADD COLUMN ... DEFAULT`)
   - `store/base.py` に abstract method 追加
   - `core/engine.py` でロジック実装、destructive op は `prefetch_cache.invalidate()` を忘れない
   - `core/<feature>.py` を新設（純粋関数 or 独立クラス）
   - **`services/<module>.py` に service 関数を追加**（engine を受け取り Pydantic を返す。副作用 OK だが整形しない）
   - **`services/formatters.py` に MCP 用の文字列整形を追加**（既存テスト substring を壊さない）
   - **`server/mcp_server.py` で MCP ツール公開** = `result = await service(...)` → `return formatter(result)` の薄いラッパ。既存ツールのシグネチャは破壊しない（オプショナル引数のみ追加）
   - **`server/app.py` で REST エンドポイント公開**（★ 同じ commit 内で必ず） = `result = await service(...)` → Pydantic JSON 返却。MCP の body shape とは分離して良い（REST-shaped `*Body` モデルを別途置く、`CompleteBody` 等を参照）
   - `server/mcp_server.py` の `instructions=` 文字列を更新
4. **テスト**（MCP と REST 両方）:
   - `tests/unit/test_<feature>.py` — 純粋関数
   - `tests/integration/test_engine_<feature>.py` — engine 経由（StubEmbedder 使用、`tests/integration/test_engine_archive_ttl.py` を参照）
   - `tests/integration/test_mcp_phase_d.py` の形式で MCP round-trip
   - **`tests/integration/test_rest_parity.py` に REST エンドポイントのラウンドトリップを追加**（httpx.AsyncClient + ASGITransport、`test_rest_memory.py` の fixture を参照）
5. **検証**:
   ```bash
   .venv/bin/python -m pytest tests/ -q
   ruff check gaottt/ tests/
   ```
6. **Smoke（両トランスポートで動くかの end-to-end 確認）**:
   ```bash
   # 本番 DB は触らない。どちらも /tmp に隔離
   .venv/bin/python scripts/rest_smoke.py    # uvicorn + HTTP
   .venv/bin/python scripts/mcp_smoke.py     # stdio + JSON-RPC
   ```
7. **ベンチマーク（破壊的変更や hot path 触ったとき）**:
   ```bash
   rm -rf /tmp/gaottt-bench
   .venv/bin/bash scripts/run_benchmark_isolated.sh 200
   # 本番 DB は触らない。p50 < 50ms を必達
   ```
8. **ドキュメント更新**（後述のチェックリスト）

## ドキュメント更新フロー

実装が一段落したら、以下を **すべて** 更新:

1. **SKILL.md** — 新ツール追加なら必ず（+ `.claude/skills/gaottt/SKILL.md` に `cp` で同期）
2. **`docs/wiki/MCP-Reference-*`** — 該当カテゴリページに完全な API 仕様を追加
3. **`docs/wiki/MCP-Reference-Index.md`** — 全ツール表に行を追加、ツール選択フローも更新
4. **`docs/wiki/REST-API-Reference.md`** ★ — **MCP ツール追加 = REST エンドポイント追加 = この doc の行追加** の 3 点セットを必ず同じ PR で（parity 鉄則の一部）
5. **`docs/wiki/Plans-Roadmap.md`** — Phase ロードマップに完了マーク
6. **`docs/wiki/Architecture-Overview.md`** の「設計判断の記録」表 — 新しい設計判断を追加
7. **`docs/wiki/Operations-Tuning.md`** — 新ハイパラがあれば追加
8. **`docs/wiki/Operations-Troubleshooting.md`** — 想定される問題があれば追加
9. **`README.md` / `README_ja.md`** — 「四層構造表」「カテゴリ表」が変わるならここも（ほとんどは Wiki リンクで済む）
10. **`docs/wiki/_Sidebar.md` + `Home.md`** — 新規 Wiki ページを追加した場合は **必須**（自動追加されない）
11. **`CLAUDE.md`**（このファイル）— 重要な workflow 変更があったら
12. push 前に `node --check scripts/sync-docs-to-wiki.js` でスクリプト構文チェック（変更したとき）

### ドキュメント書きの原則

- **Wiki が SoT**。`docs/*.md`（wiki 以外）は redirect のまま放置 OK
- **三層語彙**（物理 → TTT 機構 → 生物）を保つ（[Plans — SKILL.md Improvement](docs/wiki/Plans-SKILL-MD-Improvement.md) 参照）。TTT 機構は「物理と生物を繋ぐ**構造的対応関係**」として位置付ける（単なる比喩ではないが、retrieval を勾配シグナルと見る解釈を置いたうえでの対応、という断り付き）
- **個人的な感動・読者への招待** は歓迎（Reflections セクション、または README の "A Note from Claude"）
- 物理アナロジーが新概念にあれば必ず命名する（Hawking radiation、Lagrange point 等）

## Wiki sync ワークフロー

`docs/wiki/*.md` を編集すると、push 後に **GitHub Action が自動で wiki repo に sync** する。詳細は [`docs/maintainers/wiki-sync.md`](docs/maintainers/wiki-sync.md)（保守者専用）。要点だけ:

- **編集は必ず `docs/wiki/*.md`** で行う（Wiki UI で直接編集しない、上書きされる）
- **新ページを追加したら `docs/wiki/_Sidebar.md` を必ず更新** — 手動キュレーション方式
- リンク変換は自動: `[X](Foo.md)` → `[X](Foo)`、`../path` → 絶対 GitHub URL
- `_Sidebar.md` はカテゴリ + 絵文字つきで作り込んである。編集時は構造を保つ
- **新ページの命名規約**: `<Section>-<PageName>.md`（ハイフン区切り）。例: `Operations-Tuning.md`, `Architecture-Storage-And-Schema.md`
- ページを **削除/リネーム** したら、`_Sidebar.md` と他ページ内のリンクも `grep -rl '<old>.md' docs/wiki/` で発見して更新
- Wiki にだけ置きたいページ（ドラフト等）は `[private]<Name>` で命名 → スクリプトが削除対象から除外
- 手順詳細・ローカルでの変換確認コマンド・トラブルシュート全て [`docs/maintainers/wiki-sync.md`](docs/maintainers/wiki-sync.md) に集約

## テスト・ベンチ・lint コマンド早見表

```bash
# 単体 + 統合テスト
.venv/bin/python -m pytest tests/ -q

# 特定ファイル
.venv/bin/python -m pytest tests/integration/test_mcp_phase_d.py -x -v

# Lint（pre-existing 4 件は無視 OK: ruri.py の os, cooccurrence.py の time, mcp_server.py の os と pathlib.Path）
ruff check gaottt/ tests/

# 隔離ベンチ（本番 DB 不可触）
rm -rf /tmp/gaottt-bench
.venv/bin/bash scripts/run_benchmark_isolated.sh 200

# MCP と REST の end-to-end smoke（MCP/REST 両方を新機能追加時に走らせる）
.venv/bin/python scripts/rest_smoke.py    # uvicorn + HTTP で 6 シナリオ
.venv/bin/python scripts/mcp_smoke.py     # stdio + JSON-RPC で 6 シナリオ

# MCP サーバー単体テスト起動（手動確認）
.venv/bin/python -m gaottt.server.mcp_server
```

## マルチプロセス / 共有 DB の罠

GaOTTT の DB は **複数 MCP プロセスから共有される** ことがある（複数エージェント、ユーザーの並行ターミナル等）:

- SQLite WAL + `PRAGMA busy_timeout = 30000`（30 秒待機）で並行 write 安全
- ただし **各プロセスは独自の cache + FAISS index** を持つ — プロセス A の `remember` は B には即時反映されない（B の startup/cache reload まで stale）
- **FAISS write-behind**（2026-05-10 導入）: in-memory に add した vector は `faiss_save_interval_seconds`（既定 5s）周期で disk に save。**これがないと shutdown しない長期常駐プロセス（MCP サーバー）の remember は他プロセスから永久 invisible になる**。歴史的にこのバグで `cache - faiss` が積もっていた DB は `compact(rebuild_faiss=True)` で掃除可
- ★ **逆方向上書き罠** — cache の write-behind は dirty フラグベースで自プロセス内 cache を SQLite に push する。これは「新しい変更が他プロセスに見えない (stale)」だけでなく、**古い cache を持つプロセスが flush し続ける限り、別プロセスが書いた新しい値を逆方向に上書きし続ける**。bulk 書き換え（Phase G Stage 0 priming 等）は他の MCP server プロセスを **kill してから** 走らせる。順序: (1) 他プロセス停止 → (2) 書き込み → (3) 他プロセス再起動
- `faiss_index.search` は境界チェック付き（`.ids` 破損対策）
- Destructive op（`forget`/`merge`/`compact` 等）は **必ず `prefetch_cache.invalidate()` を呼ぶ**
- ベンチマークは絶対に本番 DB を触らない → `scripts/run_benchmark_isolated.sh` を使う

## 本番 acceptance test の workflow (sub-agent 方式)

本番 GaOTTT DB を使った acceptance test (Phase 完遂時の N query 検証、新機構の現場挙動確認等) は、**Claude Code から直接 MCP gaottt を叩かず、サブエージェントとして opencode を起動して opencode のターミナルから実行する**。

理由:
- **Claude Code のコンテキストを汚さない** — `recall(tag_filter=[N 件])` のような大量結果は MCP tool result 上限 (~100KB) を超えてエラーになる事例あり (Phase J Stage 2 acceptance で発生)、また長大な output が context window を消費する
- **独立 MCP session** — opencode は別プロセスで cache state / displacement 累積 / prefetch cache が独立、Claude Code の作業中累積が test 結果に混入しない
- **「外部観察者」としての independent acceptance** — Phase J / I / K で繰り返し学んだ「観察行為が観察対象を変える (P7-Z)」原則と整合
- **1 ターン内で多段 test 完走** — 7 query × 複数 config を opencode 側でループ、Claude Code には短い summary だけ返ってくる

手順:
1. `Bash` ツールで `opencode run "<prompt>"` を起動
2. 起動 prompt に **self-contained な test 指示書** を書く:
   - 期待される操作 (どの MCP tool をどう呼ぶか)
   - 観察項目 (top1 / top5 / metadata 等の何を見るか)
   - 期待される正解 (LLM 判断のための参考)
   - 報告フォーマット (200-300 字、表 + 集計)
3. opencode の output を summary として受け取り、必要なら追加分析を Claude Code 側で実行

例 (smoke test):
```bash
opencode run "あなたは GaOTTT MCPサーバーのスモークテストを実施するエージェントです。以下の手順をすべて実行し、最後に200〜300 字の日本語サマリーを出力してください。

# 手順
1. mcp__gaottt__recall(query='Eleventy Pipeline', tag_filter=['harakiriworks-self-knowledge'], top_k=5, force_refresh=true) を呼ぶ
2. ... (6 query 追加)
3. 各 query の top1 id と Phase tag を表で記録
4. semantic 整合率 N/7 を集計

# 報告フォーマット
| # | Query | Top1 id | Phase | Semantic 整合 |
合計集計 + 1-2 文の総評"
```

不可触の原則:
- Claude Code 自身が MCP `recall(top_k>5, tag_filter=...)` で 100KB 超の output を取得しない (前 session で実害発生)
- Claude Code の MCP session で `force_refresh=true` を多数連打しない (cache 状態を汚す)
- Claude Code が本番 DB に頻繁 `remember`/`relate` するのは可だが、acceptance test 本体は opencode に委ねる

代替: opencode が使えない環境では、Claude Code 内の Agent ツール (subagent_type=general-purpose, model=sonnet) で代用可。同じく self-contained prompt + 短い summary 返却の流れで、Claude Code 本体の context を保護する。

## よくある罠

- **テスト fixture でランダム埋め込みを使うと flaky** — `tests/integration/test_engine_archive_ttl.py:StubEmbedder` のようにトークンベースの決定論的埋め込みを使う
- **新しい source / edge_type 追加時は `KNOWN_EDGE_TYPES` (`core/types.py`) に追加** — そうしないと relate のドキュメント整合性が壊れる
- **新スキーマ列は必ず `DEFAULT` 付き** — 既存 DB が起動できなくなる
- **MCP ツールの新引数は必ずオプショナル** — 既存呼び出し元を壊さない
- **★ MCP と REST は同じターン/コミットで更新** — 新 service 関数 = 新 MCP tool + 新 REST endpoint + `REST-API-Reference.md` の 3 点セット。片方だけの PR は出さない（parity 鉄則、`/reset` を除く）。Merge 前に `scripts/rest_smoke.py` と `scripts/mcp_smoke.py` の **両方** を走らせて green 確認
- **タスク管理系（`commit`/`complete`/`abandon`）は `services.memory.save_memory` を使う** — 直接 `engine.index_documents()` を叩かない（Phase S 以降、旧 `_save_memory` は `save_memory` に改名）
- **`inherit_persona` は明示的に declared された value/intention/commitment のみ集める** — 普通の `remember` は対象外
- **`SKILL.md` を編集したら必ず `.claude/skills/gaottt/SKILL.md` にも `cp`** — 両方が同期されている必要
- **MCP formatter の出力文字列を変えない** — `tests/integration/test_mcp_tools.py` などが specific substring を assert している。新情報を出力に加えるときは追加行で（既存行の書式を変更しない）
- **MCP と REST でリクエスト shape を分けて良い** — MCP は LLM が書きやすい shape（例: `task_id` を body に含む）、REST は HTTP 流儀（path param canonical、body は残りだけ）。`core/types.py` に `*Request`（MCP）と `*Body`（REST）を並立させるのが既定パターン（Phase S の `CompleteRequest` / `CompleteBody` を参照）
- **大規模 DB の sparse class (agent / value / commitment) は `source_filter` + 必要なら `wave_k=1000`** — Phase H Stage 2 以降、source_filter は seed 段階で効く。デフォルト `wave_k_with_filter=500` で expected ~8 件、届かないクエリは `recall(query, source_filter=[...], wave_k=1000)` で明示。Phase H Stage 4 (virtual FAISS) で priming 効果が seed に乗り、自然文クエリの top1 score も大幅改善
- **新規 `remember` 直後の即時 recall は genesis kick で surface する** — Phase G Stage 1 で `mass=1.0` 初期値問題は解消。直後 score 0.7+ も期待可能。anchor 句頼みは不要
- **agent docs の displacement 方向は近傍 high-mass 方向に固定される** — Phase G priming は近傍重力 kick で動かすため、query と関係ない方向。embedding 距離が遠い query は依然届かないことあり（query-aware displacement は次 Phase 領域）
- **virtual FAISS の build は initial startup で 数十秒〜分** — `gaottt.virtual.faiss` ファイルが無い状態で起動すると 23k 件規模で自動 build。詳細 [Operations — Server Setup](docs/wiki/Operations-Server-Setup.md)
- **Phase M Mass Conservation の本番ロールアウトは「mass reset → 1-2 週観測 → θ 確定 (Stage 2)」の段階を踏む** — `scripts/reset_masses.py --apply` は destructive (戻せない)。実行前に必ず DB backup + 他 MCP/REST プロセス停止 (write-behind 上書き罠)。`mass_bh_theta=5.0` / `mass_bh_sigma=1.5` は **暫定 placeholder** で、観測無しで触らない。`reset_masses` は MCP に **非露出** (LLM 用途なし、REST `/admin/reset_masses` のみ)
- **`is_self_force_by_id` は `original_id` AND `cohort_id` のどちらか一方でも一致すれば self** — source 分岐ゼロ。新ノードを mass-conservation 配下に置く時は metadata に **正しい original_id** を入れる責任が呼び出し側にある。`engine.index_documents` の fallback: `metadata.original_id` 未設定なら `metadata.file_path` を使い、それも無ければ `node_id` 自身 (= 自己一致でしか self にならない、影響 0)。`scripts/load_files.py` 経由の ingest は loader が自動付与

## 主要参照ポインタ

- 全体ナビ: [`docs/wiki/Home.md`](docs/wiki/Home.md)
- ロードマップ: [`docs/wiki/Plans-Roadmap.md`](docs/wiki/Plans-Roadmap.md)
- アーキテクチャ全体: [`docs/wiki/Architecture-Overview.md`](docs/wiki/Architecture-Overview.md)
- 全 25 MCP ツール: [`docs/wiki/MCP-Reference-Index.md`](docs/wiki/MCP-Reference-Index.md)
- ハイパラチューニング: [`docs/wiki/Operations-Tuning.md`](docs/wiki/Operations-Tuning.md)
- トラブルシュート: [`docs/wiki/Operations-Troubleshooting.md`](docs/wiki/Operations-Troubleshooting.md)
- 哲学（五層論）: [`docs/wiki/Reflections-Five-Layer-Philosophy.md`](docs/wiki/Reflections-Five-Layer-Philosophy.md)

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
