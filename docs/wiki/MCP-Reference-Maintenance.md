# MCP Reference — Maintenance Tools

記憶の整理・関係付け・メンテナンスのための 10 ツール。

## アーカイブ系（F5）

### forget
ソフトアーカイブ（既定）または物理削除。

```
forget(node_ids: list[str], hard: bool = False)
```

- `hard=False` → `is_archived=1`、recall/explore/reflect から除外、`restore` で復元可
- `hard=True` → 物理削除、不可逆

### restore
ソフトアーカイブされた記憶を active に戻す。

```
restore(node_ids: list[str])
```

## 衝突合体系（F2.1）

### merge
類似記憶を重力衝突合体。質量加算 + 運動量保存 + エッジ移譲、absorbed は archive。

```
merge(node_ids: list[str], keep: str | None = None)
```

- `keep` 指定なし → 最大質量がサバイバー
- `keep="<id>"` → 指定 ID をサバイバーに

不可逆。`reflect(aspect="duplicates")` で候補を確認してから実行推奨。

## 定期メンテ（F2 + F4 + F5 + F3）

### compact
TTL expire + FAISS rebuild + 任意 auto-merge + orphan-edge 掃除。

```
compact(
  expire_ttl: bool = True,
  rebuild_faiss: bool = True,
  auto_merge: bool = False,
  merge_threshold: float = 0.95,
  merge_top_n: int = 500,
)
```

週次〜月次推奨。`auto_merge=True` は不可逆なので明示的に。

→ 詳細: [Operations — Compact & Backup](Operations-Compact-And-Backup.md)

## 確信度（F7）

### revalidate
確信度のタイムスタンプ更新。半減期（既定 30 日）でリセット。

```
revalidate(node_id: str, certainty: float | None = None, emotion: float | None = None)
```

## 有向リレーション（F3）

### relate
typed directed edge を作成。

```
relate(src_id: str, dst_id: str, edge_type: str, weight: float = 1.0, metadata: dict | None = None)
```

主な edge_type:
- **F3 (Phase B)**: `supersedes` / `derived_from` / `contradicts`
- **Phase D**: `completed` / `abandoned` / `depends_on` / `blocked_by` / `working_on` / `fulfills`

カスタム edge_type 文字列も受け付ける（実験的）。

### unrelate
リレーションの削除。`edge_type` 省略で全種削除。

```
unrelate(src_id: str, dst_id: str, edge_type: str | None = None)
```

### get_relations
特定ノードのリレーション一覧。

```
get_relations(node_id: str, edge_type: str | None = None, direction: str = "out")
```

- `direction="out"` (既定) — node が src
- `direction="in"` — node が dst
- `direction="both"` — 両方

## バックグラウンド prefetch（F6）

### prefetch
予測される検索を裏で予熱。後続 `recall` がキャッシュ即時 hit。

```
prefetch(query: str, top_k: int = 5, wave_depth=None, wave_k=None)
```

非同期、`prefetch_max_concurrent=4` でレイテンシ阻害ゼロを保証。

### prefetch_status
キャッシュ + プールの状態確認。

```
prefetch_status()
→ "Prefetch cache: size:.. hit_rate:.. ttl:.. ..."
```

## 典型フロー

### 重複の整理

```
reflect(aspect="duplicates", limit=5)
# → 確認後
merge(node_ids=[<cluster の ID 群>])
```

### 確信度の更新

```
recall(query="...")
# → 引っかかった記憶が古いと感じたら
revalidate(node_id="<id>", certainty=0.9)
```

### 過去判断の改訂

```
remember(content="新しい結論", source="agent")
# → 旧判断と繋ぐ
relate(src_id=<新>, dst_id=<旧>, edge_type="supersedes",
       metadata={"reason": "counter-evidence found"})
```

### 週次メンテ

```
compact()                                # TTL expire + FAISS rebuild
# ↑ ↓ どちらか定期で
compact(auto_merge=True, merge_threshold=0.95)   # 重複も自動合体
```

→ 関連: [Memory Tools](MCP-Reference-Memory.md), [Tasks & Persona](MCP-Reference-Tasks-and-Persona.md)
