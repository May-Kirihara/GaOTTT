# Guide — Cosmic 3D Visualization

GaOTTT の記憶宇宙を、**恒星と銀河のように** Plotly で可視化するツール。

## 起動

サーバー停止後に実行（DB と FAISS ファイルを直接読む）:

```bash
# 仮想座標ビュー（重力変位後、sphere + 測地線 default）
.venv/bin/python scripts/visualize_3d.py --sample 3000 --open

# 原始座標 vs 仮想座標の並列比較
.venv/bin/python scripts/visualize_3d.py --compare --sample 3000 --open

# UMAP（局所構造保存、遅め）
.venv/bin/python scripts/visualize_3d.py --method umap --sample 3000 --open

# 軽量モード — sphere 内で chord 描画（~2x 小さい HTML）
.venv/bin/python scripts/visualize_3d.py --sample 5000 --straight-lines --open

# 完全な legacy 表示（無拘束 3D + chord）
.venv/bin/python scripts/visualize_3d.py --sample 3000 --flat --open

# 全件 (注: curves default は ~200MB クラスになる、--sample 推奨)
.venv/bin/python scripts/visualize_3d.py --compare --straight-lines --open
```

## Geometry — sphere-wrap がデフォルト

埋め込み空間は単位超球面 S^767 で、RURI v3 が unit-norm vector を吐き、Phase M/J の物理はその球面上で動作する。Default の viz はその幾何を literal に再現する:

| Layer | 既定 (sphere mode) | `--flat` |
|---|---|---|
| 座標 | PCA/UMAP の 3D 出力を **L2-normalize して半径 1 に貼る** (`sphere_wrap`) | 投影直後の無拘束 3D 雲 |
| 背景 | 薄い lat/lon wireframe (8 parallels × 12 meridians) | なし |
| Filament (共起 edge) | 大円弧 (slerp、各 10 点) | 球内部を貫通する弦 |
| Velocity 矢印 | 接空間 projection → 大円で `\|v_t\|` rad 歩く tangent geodesic (各 8 点) | `p → p+v` の直線 |
| Mass-BH ring | XY/XZ 平面の円 (sphere に対しては斜め通過) | 同 |

`--straight-lines` は sphere モードを保ったまま filament/velocity だけ chord に戻す中間 mode。File size と initial load 速度を取りたい時用 (~2 倍速)。`--flat` は完全な legacy で sphere + wireframe + curves 全部 off。

## File size の目安 (sphere mode + curves)

| `--sample` | curves (既定) | `--straight-lines` | `--flat` |
|---|---|---|---|
| 1,000 | ~20 MB | ~10 MB | ~10 MB |
| 5,000 | ~100 MB | ~50 MB | ~50 MB |
| 24,000 全件 | ~480 MB ⚠️ | ~230 MB | ~230 MB |

Curve mode は filament あたり 10 倍の点数を持つので 2-2.5x のオーバーヘッド。本番 24k 件は curves で開くと初回ロードが遅いので、観賞用は `--sample 5000` か `--straight-lines` を推奨。

## 視覚エンコーディング

| 視覚要素 | 動的状態 | 恒星アナロジー |
|---|---|---|
| サイズ | Mass | 赤色巨星 vs 矮星 |
| 色温度 | Temperature | M赤 → K橙 → G黄 → F白 → A/B青白 |
| 明るさ | Decay × Mass | 最近アクセス + 高質量が最も明るい |
| シアン矢印 | 速度ベクトル | 次のステップでの移動方向 |
| 金色リング | 重力半径 | mass 由来の重力圏 |
| 紫◆ | Mass-BH (mass > θ-2σ) | 質量しきい値超えの吸引天体 (Phase M Stage 1) — `bh_factor(m, θ, σ) = tanh((m-θ)/σ)` で連続的に強度上昇。Phase M 直後の clean DB では mass ≤ 2.0 で count=0 になり次第に発生する |
| フィラメント | 共起エッジ | 宇宙の大規模構造 (sphere mode では大円弧で球面に貼り付く) |

## 恒星分類の例

- **赤色巨星** (高 mass + 低 temperature) — 安定して頻繁に検索されるドキュメント
- **青色超巨星** (高 mass + 高 temperature) — 多様な文脈で活発に検索される不安定な恒星
- **赤色矮星** (低 mass + 低 temperature) — まだあまり検索されていない記憶
- **ダスト** (未検索) — 背景にぼんやり

## 動的変化を見る手順

1. サーバー起動
2. データ投入（`load_csv.py` 等）
3. クエリ実行（`test_queries.py --mode stress --rounds 10`）
4. サーバー停止
5. `visualize_3d.py --compare` で Before/After を比較
6. サーバー再起動 → 追加クエリ → 停止 → 再可視化 → 星の移動・色変化を観察

## ヒント

- 24,000 ノード全件はブラウザが重い場合がある。`--sample 3000` で間引く
- `--method pca`（既定）は速い、`--method umap` は遅いが局所構造を保存
- ホバーで質量・温度・スペクトル型・変位量が表示される

→ 関連: [Architecture — Gravity Model](Architecture-Gravity-Model.md) — 何が可視化されているか
