# Operations — Resource Requirements

GaOTTT のリソース消費は **embedding model (RURI v3 310m)** が支配的。FAISS / SQLite / BM25 index は DB が数十万ノード規模になるまでは embedding に対して小さい。本ページは **開発機での実測値 (2026-05-28)** + DB スケーリング + OOM 時の挙動をまとめる。

> 実験の詳細レポートは [Research — VRAM/RAM Measurement 2026-05-28](../research/Research-VRAM-RAM-Measurement-2026-05-28.md) 参照。

## GPU / CPU 別の実測 (DB ~41,000 nodes)

| シナリオ | GPU VRAM | システム RAM | スループット | 備考 |
|---|---|---|---|---|
| GPU, recall 中心 (cold start) | ~4.2GB | ~2GB | — | model load 直後・ingest 未実行の最小値 |
| GPU, recall 中心 (warm = ingest 後) | **~6.7GB** | ~6.9GB | — | PyTorch allocator が前回 ingest 分の reserved pool を保持。実質これが定常 idle |
| GPU, MCP 経由 ingest (~100 chunk corpus) | peak ~6.7GB (+2.5GB) | ~6.9GB | **~6 chunk/s** | model は backend 常駐分を再利用 |
| GPU, batch 経由 ingest (新 process, ~100 chunk) | 合算 **~11.4GB** (backend 6.7 + 新 4.7) | 合算 ~13GB (backend 6.9 + 新 6.3) | ~3 chunk/s | 新 process が独自に model load (startup +90 秒で BM25/FAISS 再構築) |
| GPU, 大規模 ingest (数千 chunk 級) | peak ~16GB (推定) | — | — | 小規模測定からの外挿。`batch_size=32` × RURI max_seq=8192 で attention が爆発 |
| CPU, ingest (新 process, ~100 chunk corpus) | — | peak **~9.4GB** | **~0.4 chunk/s** (GPU の 1/15) | engine startup 120 秒、`CUDA_VISIBLE_DEVICES=""` で強制。`batch_size` を 4-8 に絞ると peak 抑えられる可能性 (未測定) |
| CPU, recall 中心 | — | ~5-6GB | — | model load + engine startup 後の安定値、推定 |

### 重要な観察

1. **PyTorch caching allocator は ingest 後に reserved を返さない**: バックエンドの "idle" baseline は ingest 前 4.2GB → ingest 後 6.7GB に +2.5GB 残留。OS 視点では空きでも実質的には握ったまま。**warm idle = 定常 idle** と考えるのが現実的。
2. **Batch route (新 process) の overhead は startup が支配的**: process spawn + RURI load (~24s) + engine startup (BM25 build + FAISS load + virtual FAISS, ~90s) + 実 ingest。Daily 運用で `scripts/load_files.py` を頻繁に回すなら毎回この ~100s を払う。常駐 MCP backend 経由なら ~0 秒。
3. **CPU ingest は実用範囲外**: GPU の 1/15 速度 (0.4 vs 6 chunk/s)。100 chunk で 4 分、1000 chunk で 40 分。recall は CPU でも遅延 1-3 秒程度で実用範囲。

## DB サイズの増え方

`~/.local/share/gaottt/` 配下のファイル:

| ノード数 | SQLite | FAISS (raw + virtual) | 合計目安 |
|---|---|---|---|
| 1,000 | ~20MB | ~6MB | ~25MB |
| 10,000 | ~180MB | ~60MB | ~240MB |
| **~41,000 (開発機の現在値)** | **~720MB** | **~230MB** | **~950MB** |
| 100,000 | ~1.8GB | ~600MB | ~2.4GB |
| 1,000,000 | ~18GB | ~6GB | ~24GB |

(node 1 件 ~= 平均 chunk 1KB-5KB + msgpack metadata + edges + 768 dim × 4 byte × 2 index ≒ 約 23KB/node。文書長に強く依存)

### システム RAM への影響

DB が大きくなると engine startup 時の BM25 build + virtual FAISS load で RAM が逼迫する場合がある。100k node を超える運用では:
- BM25 in-memory index: ~50-200MB
- FAISS index (raw + virtual): 各 dimension × 4 byte × N = 100k で ~600MB、合計 ~1.2GB
- SQLite cache live set (lazy load): ~10-30% of DB size

100k node 規模で常駐 backend に **+2GB 程度** が乗る計算。1M node 規模では **+15GB 以上** を見込む必要あり (FAISS 6GB だけで)。

## VRAM/RAM 不足時の挙動

### CPU fallback は自動化されていない

`gaottt/embedding/ruri.py` の `RuriEmbedder.__init__` は device 指定なしで `SentenceTransformer(...)` を構築する。sentence-transformers は **CUDA が見えれば必ず GPU を掴む** — VRAM 不足でも自動で CPU に逃げる経路はない。

### VRAM 不足時

`torch.cuda.OutOfMemoryError` がそのまま伝播する:

- **モデルロード時に踏む** (起動時): `SentenceTransformer(...)` 構築中に OOM → MCP サーバーが起動しない (proxy mode なら backend が起動失敗、shim だけ立つ)
- **推論時に踏む** (ingest / recall): model は載ったが forward pass で activation 分が overflow → `model.encode(...)` が OOM を raise
  - `recall`: MCP tool がエラー返却、その 1 ターンが失敗
  - `ingest` / `remember`: その batch が死ぬ。再試行しても `batch_size` 不変なので同じく死ぬ
  - dream loop の encode で踏むと background で例外ログが出て quiet node 巡回が停止

### RAM 不足時 (CPU mode)

Linux の OOM killer が process を SIGKILL する可能性あり (swap thrash 後に死ぬパターンも)。GPU の torch OOM のほうがある意味行儀がいい (例外で返ってくる)。

### 強制 CPU フォールバック

```bash
CUDA_VISIBLE_DEVICES="" .venv/bin/python -m gaottt.server.mcp_server
```

または `.env` / systemd unit / claude.json の env に設定。sentence-transformers が GPU を見えなくして CPU 経路に fallback する。

### ingest が VRAM/RAM 不足で落ちる時

`gaottt/config.py` の `batch_size` を 32 → 8 や 4 に下げて再試行。CPU mode では 4-8 が現実的。

```python
# gaottt/config.py
class GaOTTTConfig:
    batch_size: int = 32  # → 8 や 4 に下げる
```

将来的に env var (`GAOTTT_BATCH_SIZE` 等) で動的に絞れる knob を追加する余地あり (現状未整備)。

## 関連ページ

- [Operations — Server Setup](Operations-Server-Setup.md) — 起動モード (proxy/stdio/streamable-http) と RAM/VRAM トレードオフ
- [Operations — Troubleshooting](Operations-Troubleshooting.md) — OOM 以外の起動失敗・recall 失敗パターン
- [Operations — Tuning](Operations-Tuning.md) — ハイパーパラメータ全表 (`batch_size` 含む)
- [Research — VRAM/RAM Measurement 2026-05-28](../research/Research-VRAM-RAM-Measurement-2026-05-28.md) — 本ページの実測根拠
