# GER-RAG

**Gravity-Based Event-Driven RAG** - 動的スコアリングによる自己組織化検索システム

## 概要

GER-RAGは、知識ノードが質量（mass）・温度（temperature）・時間減衰（decay）といった動的メタデータを持ち、検索のたびにスコアリングが変化するRAGシステムである。

- **頻繁に検索される知識**は質量が増加し、優先的に返される
- **長期間アクセスされない知識**は時間減衰により影響力が低下する
- **一緒に検索される知識**は共起グラフでつながり、互いにブーストし合う
- **embedding空間は不変**のまま、動的挙動をスコアリング層で実現する

## クイックスタート

### セットアップ

```bash
# 仮想環境作成・依存関係インストール
uv venv .venv --python 3.12
uv pip install -e ".[dev]"

# 可視化ツール（任意）
uv pip install plotly umap-learn
```

### サーバー起動

```bash
.venv/bin/uvicorn ger_rag.server.app:app --host 0.0.0.0 --port 8000
```

初回起動時にRURI-v3モデルがダウンロードされる。2回目以降はローカルキャッシュから即座にロード。

### ドキュメント登録

```bash
# API経由
curl -X POST http://localhost:8000/index \
  -H "Content-Type: application/json" \
  -d '{
    "documents": [
      {"content": "Pythonは汎用プログラミング言語です。"},
      {"content": "機械学習はAIの一分野です。"}
    ]
  }'

# CSVからの一括投入（チャンク分割・重複スキップ付き）
.venv/bin/python scripts/load_csv.py                # 全件投入
.venv/bin/python scripts/load_csv.py --limit 100    # テスト用
```

### 検索

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"text": "プログラミングについて", "top_k": 5}'
```

### テストクエリ

```bash
# 基本テスト（5クエリ）
.venv/bin/python scripts/test_queries.py --mode basic

# 多様なクエリ（37トピック）
.venv/bin/python scripts/test_queries.py --mode full --rounds 3

# ストレステスト（mass/temperature/共起グラフを高速蓄積）
.venv/bin/python scripts/test_queries.py --mode stress --rounds 10
```

### 3D可視化

サーバー停止後に実行。クエリを重ねるほどノードの見た目が変化する。

```bash
# PCA（高速）
.venv/bin/python scripts/visualize_3d.py --open

# UMAP（局所構造をよく保存）
.venv/bin/python scripts/visualize_3d.py --method umap --open

# サンプリング（大規模データ向け）
.venv/bin/python scripts/visualize_3d.py --sample 3000 --open
```

| 表現 | 動的状態 |
|------|---------|
| ノードサイズ | Mass（検索されるほど大きい） |
| 透明度 | Decay（長期未アクセスで薄い） |
| オレンジ色寄り | Temperature（文脈変動が大きい） |
| 色分け | Source（青=tweet, 赤=like, 緑=note_tweet） |
| 線 | 共起エッジ |

## API

| メソッド | パス | 説明 |
|---------|------|------|
| POST | /index | ドキュメント登録（SHA-256重複自動スキップ） |
| POST | /query | 動的スコアリング検索 |
| GET | /node/{id} | ノード状態確認 |
| GET | /graph | 共起グラフ確認 |
| POST | /reset | 動的状態リセット |

Swagger UI: http://localhost:8000/docs

## スコアリング

```
final_score = raw_score * decay + mass_boost + temp_noise + graph_boost
```

| 要素 | 数式 | 効果 |
|------|------|------|
| raw_score | cosine_similarity(query, doc) | 意味的類似度 |
| decay | exp(-δ * (now - last_access)) | 最近アクセスされたものを優先 |
| mass_boost | α * log(1 + mass) | 頻出ドキュメントを優先 |
| temp_noise | Normal(0, temperature) | 不確実な知識の探索 |
| graph_boost | ρ * Σ(w_ij * sim(q, x_j)) | 共起関連ドキュメントのブースト |

## 技術スタック

| コンポーネント | 技術 |
|-------------|------|
| Embedding | [RURI-v3-310m](https://huggingface.co/cl-nagoya/ruri-v3-310m) (768次元, 日本語特化) |
| ベクトル検索 | FAISS IndexFlatIP |
| ストレージ | SQLite (WAL) + インメモリキャッシュ |
| API | FastAPI |
| 可視化 | Plotly + PCA/UMAP |
| パッケージ管理 | uv |

## ドキュメント

### 保守・運用

- [アーキテクチャ概要](docs/architecture.md) - システム構成、データフロー、モジュール構成、キャッシュ戦略
- [APIリファレンス](docs/api-reference.md) - 全エンドポイントの詳細仕様
- [運用・保守ガイド](docs/operations.md) - セットアップ、テスト、可視化、チューニング、トラブルシューティング
- [引継書](docs/handover.md) - 設計判断、コードの読み方、スクリプト詳細、将来の拡張ロードマップ

### 評価・研究

- [Phase 2 評価レポート](docs/research/evaluation-report.md) - Static RAG比較、セッション適応性、ベンチマーク結果、改善提言

### 設計ドキュメント

- [機能仕様](specs/001-ger-rag-core/spec.md) - ユーザーストーリー、機能要件、成功基準
- [実装計画](specs/001-ger-rag-core/plan.md) - 技術選定、プロジェクト構成
- [技術調査](specs/001-ger-rag-core/research.md) - RURI-v3, FAISS, SQLite WAL等の調査結果
- [データモデル](specs/001-ger-rag-core/data-model.md) - エンティティ定義、ハイパーパラメータ一覧
- [APIコントラクト](specs/001-ger-rag-core/contracts/api.md) - API設計仕様
- [設計原案](plan.md) - GER-RAGの着想・数理的背景

## ライセンス

Private
