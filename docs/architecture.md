# アーキテクチャ概要

## システム構成

GER-RAGは**固定embedding空間 + 動的スコアリング層**による検索システムである。embeddingモデルの意味的保証を壊さず、クエリ履歴に基づいて検索結果を動的に変化させる。

```
クエリ入力
  │
  ▼
[RURI-v3 Embedding] ──→ クエリベクトル (768次元, L2正規化済)
  │                      ※キャッシュ済みならローカルから即座にロード
  ▼
[FAISS IndexFlatIP] ──→ Top-K候補 (コサイン類似度)
  │
  ▼
[動的スコアリング層]
  ├─ mass_boost   = α * log(1 + mass)
  ├─ decay        = exp(-δ * (now - last_access))
  ├─ temp_noise   = Normal(0, temperature)
  └─ graph_boost  = ρ * Σ(w_ij * sim(q, x_j))
  │
  ▼
final_score = raw_score * decay + mass_boost + temp_noise + graph_boost
  │ (負スコアは除外)
  ▼
[状態更新] ──→ mass増加, temperature再計算, 共起グラフ更新
  │
  ▼
[Write-behind] ──→ 非同期でSQLiteにフラッシュ
```

## モジュール構成

```
ger_rag/
├── config.py               # GERConfig: 全ハイパーパラメータ
├── core/
│   ├── engine.py           # GEREngine: 全操作の統合レイヤー
│   ├── scorer.py           # スコアリング関数群 (純粋関数)
│   └── types.py            # Pydanticモデル (リクエスト/レスポンス/内部型)
├── embedding/
│   └── ruri.py             # RuriEmbedder: RURI-v3ラッパー (ローカルキャッシュ自動検出)
├── index/
│   └── faiss_index.py      # FaissIndex: FAISS IndexFlatIPラッパー
├── store/
│   ├── base.py             # StoreBase: 抽象ストアインターフェース
│   ├── sqlite_store.py     # SqliteStore: SQLite WAL実装 (content_hashによる重複チェック)
│   └── cache.py            # CacheLayer: インメモリキャッシュ + write-behind
├── graph/
│   └── cooccurrence.py     # CooccurrenceGraph: 共起グラフ管理
└── server/
    └── app.py              # FastAPIアプリ + lifespan管理
```

## データフロー

### インデックス時

1. `POST /index` でドキュメント受信
2. content SHA-256ハッシュで重複チェック（重複はembedding生成前にスキップ）
3. RURI-v3で embedding生成 (「検索文書: 」プレフィックス付き)
4. L2正規化後、FAISSインデックスに追加
5. NodeState初期化 (mass=1.0, temperature=0.0)
6. SQLiteにドキュメント + 状態を永続化

### クエリ時

1. `POST /query` でクエリ受信
2. RURI-v3でクエリembedding生成 (「検索クエリ: 」プレフィックス付き)
3. FAISS検索でTop-K候補取得
4. 各候補に動的スコアリング適用
5. 負スコアを除外、final_scoreでソート
6. **レスポンス返却後**に状態更新 (mass, temperature, 共起グラフ)
7. ダーティ状態はwrite-behindタスクで非同期にSQLiteへフラッシュ

## ストレージ戦略

```
起動時:   SQLite → インメモリキャッシュにロード + FAISSインデックスロード
稼働時:   キャッシュから読み取り → 変更はdirtyセットに記録
定期的:   write-behindタスクがdirty状態をバッチでSQLiteにフラッシュ (5秒間隔)
停止時:   write-behind停止 → 全dirty状態フラッシュ → FAISSインデックス保存 → 接続クローズ
異常終了: フラッシュされていないdirty状態は消失 (ドキュメント・embeddingは保全)
```

### SQLiteスキーマ

`documents`テーブルには`content_hash`カラム（SHA-256）とUNIQUEインデックスがあり、同一contentの重複登録をDB層でも防止する。

## 並行性モデル

- **シングルインスタンス**前提
- ノード状態更新は**last-write-wins**（ロックなし）
- SQLite WALモードで読み書き並行可能
- write-behindは単一asyncioタスクで実行

## Embeddingモデルのキャッシュ

`RuriEmbedder`は起動時にHuggingFaceキャッシュ（`~/.cache/huggingface/`）を検査し、モデルがキャッシュ済みであれば`local_files_only=True`でロードする。これによりオフライン環境でも動作し、起動時のHuggingFace APIへのHTTPリクエストが抑制される。

## 3D可視化

`scripts/visualize_3d.py`はFAISSインデックスからembeddingを直接読み取り、PCAまたはUMAPで3次元に次元削減し、動的状態をインタラクティブなPlotly HTMLとして出力する。

- ノードサイズ: mass（質量）
- 透明度: decay（時間減衰）
- 色: source別（tweet/like/note_tweet）+ temperature（高温でオレンジ寄り）
- エッジ: 共起グラフの接続
