# 引継書

## プロジェクト概要

**GER-RAG** (Gravity-Based Event-Driven RAG) は、知識ノードが動的メタデータ（質量・温度・時間減衰）を持ち、検索のたびにスコアリングが変化する検索システムである。

従来のRAG（静的ベクトル検索）やGraphRAG（LLMによる明示的グラフ構築）と異なり、**embedding空間は固定のまま**、クエリ履歴から**自己組織的に知識構造が形成**される。

## 現在の状態 (Phase 1 完了)

### 実装済み機能

| 機能 | エンドポイント | 状態 |
|------|-------------|------|
| ドキュメント登録 | POST /index | 完了 (SHA-256重複チェック付き) |
| 動的スコアリング検索 | POST /query | 完了 |
| ノード状態確認 | GET /node/{id} | 完了 |
| 共起グラフ確認 | GET /graph | 完了 |
| 状態リセット | POST /reset | 完了 |

### 追加ツール

| ツール | スクリプト | 説明 |
|--------|----------|------|
| CSV投入 | scripts/load_csv.py | DM除外、長文チャンク分割、重複スキップ |
| テストクエリ | scripts/test_queries.py | basic/full/stress 3モード、37+トピック |
| 3D可視化 | scripts/visualize_3d.py | PCA/UMAP次元削減、Plotlyインタラクティブ |

### 技術スタック

| コンポーネント | 選定技術 | 選定理由 |
|-------------|---------|---------|
| Embedding | RURI-v3-310m (768次元) | 日本語特化、8192トークン対応 |
| ベクトル検索 | FAISS IndexFlatIP | 100K件で~1ms、exact search |
| ストレージ | SQLite WAL + aiosqlite | 非同期、軽量、単一インスタンス向き |
| キャッシュ | インメモリdict + write-behind | ~0.01ms読み取り |
| API | FastAPI + uvicorn | 非同期、自動ドキュメント生成 |
| シリアライゼーション | msgpack (sim_history) | コンパクト、高速 |
| 可視化 | Plotly + PCA/UMAP | インタラクティブ3D、ブラウザベース |
| パッケージ管理 | uv | 高速、Python環境構築 |

### 設計判断の記録

これらの判断は `specs/001-ger-rag-core/` 以下に詳細が残っている。

| 判断事項 | 決定内容 | 経緯 |
|---------|---------|------|
| 並行性 | Last-write-wins（ロックなし） | シングルインスタンス前提、レイテンシ優先 |
| ドキュメントID | システムUUID自動生成 | ユーザー指定不可、API簡素化 |
| 認証 | なし (Phase 1) | 開発・検証フェーズ |
| 異常終了時 | dirty状態消失を許容 | 動的状態は自然再構築可能 |
| 負スコア | 結果から除外 | temperature noiseによる無関係結果の排除 |
| 重複チェック | content SHA-256ハッシュ | embedding生成前にスキップ、計算資源節約 |
| モデルキャッシュ | ローカルキャッシュ自動検出 | 2回目以降のHuggingFace API通信を完全抑制 |

## コードの読み方

### エントリポイント

1. **サーバー起動**: `ger_rag/server/app.py` の `lifespan()` → 全コンポーネント初期化
2. **クエリ処理**: `app.py` の `query_documents()` → `engine.query()` → `scorer.*` + `cooccurrence.*`
3. **状態更新**: `engine._update_state_after_query()` → `cache.set_node()` → write-behind
4. **重複チェック**: `engine.index_documents()` → `store.find_existing_hashes()` → embedding生成前にスキップ

### 主要クラスの役割

| クラス | ファイル | 責務 |
|-------|---------|------|
| GEREngine | core/engine.py | 全操作のオーケストレーション（重複チェック含む） |
| RuriEmbedder | embedding/ruri.py | テキスト→ベクトル変換（ローカルキャッシュ自動検出） |
| FaissIndex | index/faiss_index.py | ベクトル近傍探索 |
| CacheLayer | store/cache.py | インメモリ状態管理 + write-behind |
| SqliteStore | store/sqlite_store.py | 永続化（content_hashによる重複防止含む） |
| CooccurrenceGraph | graph/cooccurrence.py | 共起エッジの形成・減衰・剪定 |

### scorer.py は純粋関数

`core/scorer.py` の4関数は副作用なしの純粋関数。ユニットテストが最も書きやすい部分。

### embedding/ruri.py のキャッシュ検出

`_is_model_cached()` が `huggingface_hub.scan_cache_dir()` でローカルキャッシュの有無を確認し、キャッシュ済みなら `local_files_only=True` で `SentenceTransformer` をロードする。これによりオフライン環境でも動作し、起動が高速化される。

## スクリプト詳細

### scripts/load_csv.py

- `input/documents.csv` を読み込み、`POST /index` に分割投入
- DM/group_DMはプライバシー保護のため自動除外
- 長文（2000文字超）は `---` セパレータまたは段落区切りで自動チャンク分割
- 結果: 9,060行 → 約12,010チャンク

### scripts/test_queries.py

- **basic**: 5クエリ（動作確認）
- **full**: 37クエリ（Tech, Culture, Food, Life, Society, Humor + 異トピック重複5件で共起エッジ促進）
- **stress**: 82クエリ/ラウンド（37多様 + AI/映画/食べ物の集中バーストで特定クラスタのmassを急速蓄積）

### scripts/visualize_3d.py

- FAISSインデックスから直接embeddingベクトルを読み取り
- PCA or UMAPで3Dに次元削減
- SQLiteからノード状態を取得し、mass→サイズ、decay→透明度、temperature→色で表現
- Plotly HTMLとして出力、ブラウザでインタラクティブ操作

## 将来の拡張 (Phase 2-3 ロードマップ)

### Phase 2: 評価・チューニング

- ベンチマーク（検索精度、レイテンシ、セッション適応性）
- ハイパーパラメータ感度分析
- 静的RAGとの比較実験
- 3D可視化を使ったクラスタ構造の定性分析

### Phase 3: 本番強化

- **PostgreSQL移行**: `store/base.py` の抽象インターフェースに対してPostgres実装を追加。SqliteStoreと差し替え可能。
- **MCP Server統合**: `/query` をMCPツールとして公開
- **マルチユーザー状態分離**: NodeState, CacheLayerにユーザーIDディメンション追加
- **認証**: FastAPIミドルウェアでAPIキー or OAuth2
- **IndexIVFFlat移行**: 100K件超でFAISSインデックスをIVFに切り替え（要トレーニングステップ）

### 拡張時の注意点

- `store/base.py` のStoreBaseインターフェースを崩さない（DB差し替えの可搬性を維持）
- embeddingのL2正規化は必須（FAISSのInner Product = cosine similarity の前提）
- RURI-v3のプレフィックス（「検索クエリ: 」「検索文書: 」）は省略不可
- `documents`テーブルの`content_hash`カラム + UNIQUEインデックスは重複防止の要

## ファイル構成

```
GER-RAG/
├── ger_rag/                  # メインパッケージ
│   ├── config.py             # ハイパーパラメータ (★チューニング対象)
│   ├── core/                 # コアロジック
│   │   ├── engine.py         # 統合エンジン (重複チェック含む)
│   │   ├── scorer.py         # スコアリング純粋関数
│   │   └── types.py          # Pydanticモデル
│   ├── embedding/            # Embeddingモデル (キャッシュ自動検出)
│   ├── index/                # ベクトルインデックス
│   ├── store/                # 永続化レイヤー (content_hash重複防止)
│   ├── graph/                # 共起グラフ
│   └── server/               # FastAPI
├── scripts/                  # ユーティリティ
│   ├── load_csv.py           # CSV投入（チャンク分割、DM除外、重複スキップ）
│   ├── test_queries.py       # テストクエリ（basic/full/stress 3モード）
│   └── visualize_3d.py       # 3D可視化（PCA/UMAP、Plotly HTML出力）
├── input/                    # 入力データ
│   └── documents.csv         # テストCSV (9,060行 → 約12,010チャンク)
├── specs/                    # 設計ドキュメント (speckit)
│   └── 001-ger-rag-core/     # 仕様・計画・タスク
├── docs/                     # 保守ドキュメント
├── pyproject.toml            # プロジェクト定義
└── .gitignore
```

## 連絡事項

- 設計経緯の詳細: `specs/001-ger-rag-core/` 以下の spec.md, plan.md, research.md を参照
- スコアリング数式の根拠: `plan.md` のSection 6 (Retrieval Flow) を参照
- ハイパーパラメータの推奨範囲: `plan.md` のSection 11 を参照
