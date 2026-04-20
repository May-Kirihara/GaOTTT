# GER-RAG 本体改修計画

> 対象: `ger_rag/` 配下のコア・ストア・グラフ・サーバー実装
> 言語: 日本語（保守・計画ドキュメント）
> 関連: `docs/skill-md-improvement-plan.md`（SKILL.md 側の改良計画）
> 最終更新: 2026-04-21

## 0. なぜ本体改修が必要か

`docs/skill-md-improvement-plan.md` で計画している運用パターンのうち、いくつかは **SKILL.md（プロトコル文書）だけでは実現できない**。
これらは `ger_rag/` 本体に新しい API・スキーマ・スコアリング次元を追加する必要がある。

本ドキュメントは、SKILL.md 改良と並走する **本体側の作業計画** をまとめる。

## 1. 現状アーキテクチャの確認

調査結果（2026-04-21 時点）:

| レイヤ | ファイル | 主な責務 |
|---|---|---|
| MCP サーバー | `ger_rag/server/mcp_server.py` | remember / recall / explore / reflect / ingest を公開 |
| コア | `ger_rag/core/scorer.py`, `engine.py`, `types.py` | 重力スコアリング・状態遷移 |
| ストア | `ger_rag/store/sqlite_store.py` | documents / nodes / edges の永続化 |
| グラフ | `ger_rag/graph/cooccurrence.py` | 共起エッジ（無向・時間衰減） |

### 現状スキーマ（SQLite）

```sql
documents(id, content, content_hash, metadata)
nodes(id, mass, temperature, last_access, sim_history,
      displacement, velocity, return_count)
edges(src, dst, weight, last_update)
```

### 現状スコア式（`core/scorer.py`）

```
final = (gravity_sim * decay + mass_boost + wave_boost) * saturation
```

## 2. 機能ギャップ一覧

SKILL.md 改良計画で求める機能と現状の実装ギャップ:

| # | 機能 | 現状 | 必要な作業 |
|---|------|------|-----------|
| F1 | `auto_remember` | ❌ 無し | 新規 MCP ツール追加 |
| F2 | 類似記憶の統合提案 | ❌ 無し（重複は SHA-256 完全一致のみ） | recall/reflect に類似クラスタ抽出 |
| F3 | 記憶間の有向リレーション（`supersedes` 等） | ⚠️ 共起エッジは無向のみ | `EdgeType` enum 追加 + スキーマ拡張 |
| F4 | TTL 付き短期記憶（`source="hypothesis"`） | ❌ 無し | nodes に `expires_at` 追加 + 掃除ジョブ |
| F5 | 削除/アーカイブ API（forget） | ❌ 無し（reset のみ） | `forget` / `archive` MCP ツール追加 |
| F6 | バックグラウンド prefetch | ❌ 無し | 軽量 prefetch API + サーバー側ジョブ |
| F7 | エモーショナル重み付け | ⚠️ 重力次元のみ | scorer に新次元追加 |

## 3. 設計方針（横断的）

### 3.1 後方互換性

- 既存の `remember/recall/explore/reflect/ingest` のシグネチャは**変更しない**（オプショナル引数の追加のみ）
- スキーマ追加列は `DEFAULT` を設定し、既存 DB ファイルが読めることを担保
- 既存テストはすべてグリーンを維持

### 3.2 段階的ロールアウト

各機能は独立フィーチャーフラグ（`config.json`）で個別に有効化できるようにする:

```json
{
  "features": {
    "auto_remember": false,
    "similarity_clustering": false,
    "directed_edges": false,
    "ephemeral_memory": false,
    "forget_api": false,
    "background_prefetch": false,
    "emotional_weight": false
  }
}
```

### 3.3 テスト戦略

- 各機能ごとに `tests/test_<feature>.py` を新設
- スキーマ移行は `tests/test_migration.py` で旧 DB → 新 DB の互換性を検証
- ベンチマーク（nDCG/レイテンシ）は機能追加前後で **退行ゼロ** を必達

## 4. 機能別実装計画

### F1. `auto_remember` ツール

**目的**: LLM が「何を保存すべきか」の判断負荷を軽減する。
会話末尾でテキストブロックを渡すと、保存候補を抽出して提示する（保存自体は LLM の確認後）。

**API 案**:
```python
auto_remember(
    transcript: str,         # 会話の直近セグメント
    max_candidates: int = 5,
    include_reasons: bool = True,
) -> list[Candidate]
```

**実装スケッチ**:
- `ger_rag/core/extractor.py` を新設
- 候補抽出は当面ヒューリスティック（固有名詞・数値・「決定/結論/エラー」キーワード周辺）
- 将来的に小型 LLM 呼び出しに差し替え可能なインターフェイスにする

**スキーマ変更**: なし
**所要**: 中（2〜3日）

---

### F2. 類似記憶の統合提案

**目的**: 完全一致 SHA-256 では拾えない「ほぼ同じ記憶」を検出し、ユーザーに統合を促す。

**API 案**:
```python
recall(query=..., suggest_clusters=True)
# → results[].cluster_id を返す

reflect(aspect="duplicates", threshold=0.9)
# → 高類似ペア一覧
```

**実装スケッチ**:
- `ger_rag/core/clustering.py` を新設
- 既存 embedding を使い、cosine 類似度 ≥ threshold をクラスタ化（単純な union-find）
- 統合 API（`merge(ids=[...], keep=...)`）も同時に追加

**スキーマ変更**: documents に `merged_into TEXT NULL` を追加
**所要**: 中（3〜4日）


IDEA：重力式RAGなので、十分に座標が近づいたら衝突して質量が増える形で実装すると面白そう　確認不要、物理ロジックのみで実装

---

### F3. 記憶間の有向リレーション（`supersedes` 等）

**目的**: 「過去の自分との対話モード」で、撤回された判断と新判断を構造化して繋ぐ。

**スキーマ変更**:
```sql
edges(
    src TEXT,
    dst TEXT,
    edge_type TEXT NOT NULL DEFAULT 'cooccurrence',  -- ★追加
    weight REAL,
    last_update REAL,
    metadata JSON                                     -- ★追加
)
```

**`EdgeType` enum**:
- `cooccurrence` — 既存（無向、共起）
- `supersedes` — 有向、撤回・上書き（新→旧）
- `derived_from` — 有向、派生・展開
- `contradicts` — 有向、矛盾検出時

**API 案**:
```python
relate(src_id: str, dst_id: str, edge_type: str, metadata: dict | None = None)
recall(query=..., follow_edges=["supersedes"])  # フォロー対象を指定
```

**所要**: 大（4〜5日）— 既存 cooccurrence ロジックとの共存設計が必要

---

### F4. TTL 付き短期記憶（`source="hypothesis"`）

**目的**: Thinking ログから救った仮説を、永続記憶を汚さずに保持する。

**スキーマ変更**:
```sql
nodes(
    ...,
    expires_at REAL NULL,  -- ★追加（NULL なら永続）
    is_archived INTEGER DEFAULT 0  -- ★追加（F5 と兼用）
)
```

**動作**:
- `source="hypothesis"` で remember すると `expires_at = now + default_ttl`（デフォルト 7 日）
- バックグラウンド掃除ジョブが期限切れを `is_archived=1` にする（即削除はしない）
- recall は `is_archived=0` のみを対象とする

**API 案**:
```python
remember(content=..., source="hypothesis", ttl_seconds=86400 * 30)
# ttl_seconds 指定で延命可能
```

**所要**: 中（2〜3日）

---

### F5. 削除/アーカイブ API（forget）

**目的**: dormant 記憶の剪定をユーザー対話で行う。

**API 案**:
```python
forget(node_ids: list[str], hard: bool = False)
# hard=False → is_archived=1（復元可能）
# hard=True  → 物理削除
```

**実装スケッチ**:
- F4 で追加する `is_archived` 列を共用
- recall/reflect は archived を除外（オプションで含める引数も追加）
- 物理削除は documents/nodes/edges を CASCADE で消す

**所要**: 小（1〜2日）

---

### F6. バックグラウンド prefetch

**目的**: アストロサイト的役割の本丸。ユーザー発言ごとに裏で recall を走らせ、関連記憶を「発火準備」させておく。

**API 案**:
```python
prefetch(query: str, top_k: int = 20) -> PrefetchHandle
# 非同期で recall を走らせ、結果はキャッシュに保持
# 後続 recall(query=...) がキャッシュヒットすれば高速

prefetch_status() -> dict  # キャッシュ状態の確認
```

**実装スケッチ**:
- `ger_rag/server/prefetch.py` を新設
- LRU キャッシュ + 非同期タスクプール
- MCP サーバーが `asyncio.create_task` でバックグラウンド実行
- キャッシュキーは query embedding の量子化値

**注意**: GER-RAG はレイテンシ重視のため、prefetch がメインスレッドを阻害しない設計を厳守。
**所要**: 大（5〜6日）— 並行性とリソース管理が肝

---

### F7. エモーショナル重み付け

**目的**: 「悔しかった失敗」「スッキリした成功」など、情動的な重みを recall に反映する。

**スキーマ変更**:
```sql
nodes(
    ...,
    emotion_weight REAL DEFAULT 0.0,    -- ★追加（-1.0 〜 +1.0）
    certainty REAL DEFAULT 1.0,         -- ★追加（確信度 0.0 〜 1.0）
    last_verified_at REAL NULL          -- ★追加（再確認のタイムスタンプ）
)
```

**スコア式拡張**（`core/scorer.py`）:
```
final = (gravity_sim * decay
         + mass_boost
         + wave_boost
         + emotion_boost
         + certainty_decay) * saturation

emotion_boost   = emotion_weight_alpha * abs(emotion_weight)
certainty_decay = certainty_alpha * certainty * exp(-staleness)
```

**API 案**:
```python
remember(content=..., emotion=0.7, certainty=0.9)
revalidate(node_id: str, certainty: float)  # 再確認したとき
```

**所要**: 中（3〜4日）— ベンチマークでの効果検証が必要

## 5. 実装ロードマップ（推奨順）

### Phase A: 基盤整備（依存先・小〜中）

1. **F5 forget API**（小） — 単独で価値があり、F4 と列を共有するので先に基盤を作る
2. **F4 TTL 付き短期記憶**（中） — F5 のスキーマ追加と同時に
3. **F1 auto_remember**（中） — スキーマに依存せず単独で進められる

### Phase B: 関係性とスコアリング（中〜大）

4. **F2 類似記憶の統合提案**（中）
5. **F7 エモーショナル重み付け**（中） — scorer 改修、ベンチマーク必須
6. **F3 有向リレーション**（大） — 既存 cooccurrence との共存設計

### Phase C: アストロサイト本丸（大）

7. **F6 バックグラウンド prefetch**（大） — 全機能が揃った状態で導入

各 Phase 完了時に `docs/skill-md-improvement-plan.md` の対応パターンを正式版に差し替える。

## 6. リスクと留意点

- **レイテンシ退行**: GER-RAG の核は「100K 文書で 20ms」。各機能追加でベンチマーク必達
- **スキーマ移行**: SQLite なので `ALTER TABLE ADD COLUMN` で段階追加可能だが、テストで旧 DB → 新 DB の互換を検証
- **MCP プロトコル互換性**: 既存ツールのシグネチャ変更は禁止。新引数はすべてオプショナル
- **重複機能**: `forget` と `archive` の境界、`hypothesis` と通常記憶の境界が曖昧化しないよう、ドキュメントとテストで明確化

## 7. 関連ドキュメント

- SKILL.md 改良計画: `docs/skill-md-improvement-plan.md`
- アーキテクチャ全体像: `docs/architecture.md`
- 運用ガイド: `docs/operations.md`
- 引き継ぎメモ: `docs/handover.md`
