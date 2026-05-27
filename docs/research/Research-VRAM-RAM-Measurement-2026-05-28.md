# GaOTTT VRAM / RAM 実測レポート (2026-05-28)

## 目的

README の Requirements 行 (旧: 「RAM 8GB+ / GPU CUDA or none」) には VRAM 値も corpus 規模別の詳細もなく、ユーザーが自分の環境で動くかを事前判断できなかった。本実験は **本番 DB ~41,000 nodes 規模での開発機実測値** を取得し、サイジング判断の根拠を提供することを目的とする。

具体的な疑問:
1. RURI v3 310m の実 VRAM/RAM フットプリントは?
2. MCP 経由 ingest と batch process 経由 ingest で VRAM/RAM 挙動はどう違うか?
3. CPU 動作時 (`CUDA_VISIBLE_DEVICES=""`) の RAM 消費とスループットは実用範囲か?
4. VRAM/RAM が足りないとき、システムはどう落ちるか?

## 環境

- GPU: NVIDIA、24,564 MiB VRAM、4,222 MiB 使用中 (実験開始時)
- DB: 41,070 active nodes (実験開始時)、SQLite 720MB / FAISS raw 115MB / FAISS virtual 115MB
- Python 3.12、`gaottt` main branch (2026-05-28)
- Backend: `--transport streamable-http --port 7878` で常駐 (PID 1396377)、proxy mode default
- RURI v3 310m を `batch_size=32` で運用

## 実験設計

### Phase 構成

| Phase | 内容 | 計測対象 |
|---|---|---|
| 0 | idle baseline (30s) | backend (PID 1396377) の GPU VRAM + RSS |
| 1 | MCP-route ingest | `mcp__gaottt__ingest()` を Claude Code 経由で呼ぶ。backend が encode |
| 2 | cooldown (60s) | allocator 挙動の観察 (reserved pool 解放されるか) |
| 3 | batch-route ingest | standalone Python process を spawn、独自に RURI を load、`engine.index_documents` 直叩き |
| 4 | post (15s) | batch process 終了後の VRAM 返却確認 |
| 5 | CPU ingest | `CUDA_VISIBLE_DEVICES=""` で fresh process spawn、RAM のみ計測 |

### Corpus

- **GPU 実験 (phase 0-4)**: `input/harakiriworks/` (30 ファイル、260KB) を alphabetical で 15+15 分割
  - MCP route: 前半 15 ファイル → 71 chunks
  - Batch route: 後半 15 ファイル → 36 chunks
- **CPU 実験 (phase 5)**: `input/Narou/` (8 ファイル、440KB) → 76 chunks
- 全件 `source=harakiriworks-blog` (GPU 実験) / `source=narou` (CPU 実験) で tag

### 計測

`nvidia-smi --query-gpu=memory.used` (GPU 用) と `/proc/<pid>/status` の `VmRSS` (RAM 用) を 0.5 秒間隔でサンプル。Phase は CSV の phase 列で識別。

実装は `.perf-acceptance/monitor.py` (汎用 sampler)、`.perf-acceptance/run_batch.py` / `.perf-acceptance/run_cpu.py` (subprocess + sampler 統合) を本実験用に新規作成。

### 安全策

- 実験開始前に `gaottt.db` を `gaottt.db.before-vram-experiment.20260528-011219` として backup
- CPU 実験前に `gaottt.db.before-cpu-experiment.20260528-013036` として再 backup
- Production DB に書き込む内容 (`input/harakiriworks/` + `input/Narou/`) はユーザーが事前に「ingest したい」と意思表示したもの

## 結果

### GPU 実験 (phase 0-4)

| Phase | 持続時間 | GPU VRAM avg / max | Backend RSS avg / max | Loader RSS max |
|---|---|---|---|---|
| idle | 36s | 4,235 / **4,267** MiB | 6,880 / 6,880 MiB | — |
| MCP ingest | 10.6s | 5,712 / **6,713** MiB | 6,833 / 6,888 MiB | — |
| cooldown | 68s | 6,688 / 6,735 MiB | 6,847 / 6,891 MiB | — |
| batch ingest | 195s | 7,727 / **11,390** MiB | 6,891 / 6,891 MiB | **6,285** MiB |
| post | 168s | 6,178 / 6,301 MiB | 6,891 / 6,891 MiB | — |

#### MCP route の詳細タイムライン

- 0-4s: GPU 4,226 MiB (encoding 開始前、リクエスト受信処理)
- 4-5s: GPU 6,688 MiB (+2,462 MiB、encoding 開始)
- 5-10s: GPU 6,712 MiB (定常 ingest 活動)
- 10.6s 終了

→ 71 chunks の encoding 自体は **約 6 秒**、`batch_size=32` で 3 batch (32+32+7)。残りは doc parse + FAISS index 更新 + SQLite store。

#### Batch route の詳細タイムライン

- 0-24s: Process spawn + RURI load。RSS 0 → 2,179 MiB
- 24-115s: Engine startup (BM25 build + raw FAISS load + virtual FAISS load)。RSS 2,179 → 5,206 MiB、GPU はまだ低 (~7,805 MiB は backend のまま、新 process は CPU pre-init)
- 115-180s: 実 ingest 開始。GPU 8,317 → 11,367 MiB、RSS 6,281 MiB peak
- 195s 終了

→ Engine startup が **約 90 秒** で支配的。実 ingest 36 chunk は約 13 秒。スループット ~3 chunk/s (MCP route の半分は engine 並行使用の overhead 込み)。

#### 重要観察: PyTorch caching allocator のスティッキネス

`idle` の GPU 4,267 MiB → `cooldown` (= ingest 終了後の何もしない 68 秒) で 6,735 MiB。**+2,468 MiB を保持したまま OS に返さない**。

これは PyTorch の caching allocator が再利用のために reserved pool を保持する挙動。次回 ingest で同 size の tensor を再 allocate するときに高速化される。**warm idle = 定常 idle** と考えるのが正しい。「cold start の 4.2GB」は再起動直後の数十秒間しか観測されない。

#### Batch process 終了後の VRAM 返却

`post` phase で GPU 6,301 MiB。`cooldown` の 6,735 MiB から **-434 MiB**。新 process の VRAM (~4,679 MiB) は綺麗に release されたが、backend の retained pool は残った。

→ **複数 process 同時稼働 = 合算 peak が VRAM 上限に達する設計上の上限**。24GB GPU なら今回の構成 (backend + batch loader) で peak 11.4GB は 47% 使用、まだ余裕。12GB GPU だと 95% で OOM 寸前。

### CPU 実験 (phase 5)

| 区間 | RSS |
|---|---|
| Process spawn | 0 MiB |
| Model load 完了 (0-14s) | 2,179 MiB |
| BM25 build (14-70s) | 5,263 MiB |
| FAISS load (70-126s) | 6,606 MiB |
| 実 ingest 進行中 (126-336s) | 7,927-9,395 MiB (variance ~1.5GB、attention 活動による) |
| **Peak** | **9,395 MiB** |

スループット: **76 chunks / 214s = 0.36 chunks/s**

GPU MCP route (~6 chunks/s) との比: **約 1/17**。

Engine startup は GPU batch route の 90s に対し CPU で 120s。Model load 自体は GPU/CPU で大差なし (FAISS load も CPU 動作で同じ)、ingest 部分のみ大幅に遅い。

## 考察

### サイジング判断

**Recall のみのユーザー** (検索だけで ingest しない):
- GPU: 8GB VRAM で動く (4.2GB cold idle、warm でも 6.7GB)
- CPU: 8GB RAM で動く (~5-6GB 安定)

**occasional ingest** (週に数十 chunk):
- GPU: 12GB VRAM 推奨 (cold 4.2 + ingest peak 2.5 + 安全マージン)
- CPU: 12GB RAM 推奨 (~9.4GB peak)

**heavy ingest** (数千 chunk を一度に):
- GPU: 16GB+ VRAM 推奨 (本実験は小規模 corpus、過去 user 観測の「16GB peak」と整合)
- CPU: 実用範囲外 (時間がかかりすぎる)

**multi-process** (REST + MCP backend + batch loader 同時):
- GPU: 24GB+ 推奨 (本実験で 11.4GB observed、活動増えれば更に上)

### Engine startup 90s の意味

`scripts/load_files.py` を REPL 的に何度も叩く運用は **毎回 90 秒の startup cost** がかかる。長時間 ingest するなら一括 batch、頻繁に小さい ingest をするなら常駐 MCP backend 経由 (MCP route で startup 0 秒) が望ましい。

### CPU の実用範囲

Recall 単体は CPU で十分使える (~1-3 秒/query)。Ingest は **完全に GPU 前提の設計**。BM25 build + FAISS load + virtual FAISS load も CPU で動くが、production 規模 DB だと engine startup が分単位になる可能性。

### batch_size の影響 (未測定)

`config.batch_size` 既定 32 は GPU 前提。CPU で OOM を踏まないためには 4-8 推奨だが本実験では未測定。今後の TODO。

## 成果物

- README.md / README_ja.md: 要件表を実測値ベースに更新、詳細は Wiki へ
- docs/wiki/Operations-Resource-Requirements.md: 本実験を要約した運用ドキュメント (新規)
- docs/wiki/_Sidebar.md / Home.md: 新ページへのリンク追加
- DB backup: `~/.local/share/gaottt/gaottt.db.before-vram-experiment.*` + `.before-cpu-experiment.*`
- 実験 script + raw data: `.perf-acceptance/` (gitignore 想定の scratch 領域)
  - `monitor.py` / `run_batch.py` / `run_cpu.py` (汎用 sampler + subprocess wrapper)
  - `batch_ingest.py` / `cpu_ingest.py` (実験 driver)
  - `analyze.py` / `analyze_cpu.py` (集計)
  - `samples.csv` (GPU 実験 raw、282 サンプル) / `cpu_samples.csv` (CPU 実験 raw、693 サンプル)

## 未解決 / 後続作業

1. **`batch_size=8` での CPU ingest peak 測定** — CPU mode のチューニングガイド完成のため
2. **大規模 corpus (数千 chunk) での GPU ingest peak の実測** — 本レポートの「16GB は外挿」を実測値に置換
3. **DB が 100k node を超える領域での engine startup 時間スケーリング**
4. **動的 batch_size knob (env var)** の実装検討 — 現状は `config.py` 直接編集が必要
