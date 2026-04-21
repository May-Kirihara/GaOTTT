# MCP Reference — Tasks & Persona (Phase D)

Phase D で追加された **9 個** のツール。物理ネイティブなタスク管理 + 人格保存基盤。

詳細設計は [Plans — Phase D](Plans-Phase-D-Persona-Tasks.md)、ツール仕様は [`SKILL.md`](../../SKILL.md) を正とする。

## 階層構造

```
value      ← 永続的な土台（declare_value）
   ↓ derived_from
intention  ← 長期方向（declare_intention）
   ↓ fulfills
commitment ← 期限付き約束（declare_commitment、既定 14 日）
   ↓ fulfills
task       ← 個別行動（commit、既定 30 日）
```

## タスク管理

### commit
タスクを作成。親 commitment/intention に `fulfills` で繋げる。

```
commit(
  content: str,
  parent_id: str | None = None,
  deadline_seconds: float | None = None,    # 既定: 30 日
  certainty: float = 1.0,
)
```

### start
タスクを active engagement に。TTL リセット + emotion=0.4。

```
start(task_id: str)
```

### complete
タスク完了。`outcome` を新ノードとして保存し、`completed` エッジを outcome → task で張る。task は archive される。

```
complete(task_id: str, outcome: str, emotion: float = 0.5)
```

### abandon
タスクを意図的に放棄。`reason` を保存し、`abandoned` エッジを reason → task で張る。「**影の年表**」を残す機能。

```
abandon(task_id: str, reason: str)
```

### depend
タスク間の依存関係。

```
depend(task_id: str, depends_on_id: str, blocking: bool = False)
```

- `blocking=False` (既定) → `depends_on` エッジ
- `blocking=True` → `blocked_by` エッジ（強い依存）

## 人格宣言

### declare_value
深く保持する信念。永続。

```
declare_value(content: str, certainty: float = 1.0)
```

### declare_intention
長期的な方向性。`parent_value_id` で derived_from を張る（任意）。

```
declare_intention(content: str, parent_value_id: str | None = None, certainty: float = 1.0)
```

### declare_commitment
期限付きの約束。`parent_intention_id` 必須、`fulfills` を張る。

```
declare_commitment(
  content: str,
  parent_intention_id: str,
  deadline_seconds: float | None = None,    # 既定: 14 日
  certainty: float = 1.0,
)
```

## 人格継承

### inherit_persona
過去のセッションで宣言された values/intentions/commitments/style/relationships から散文を生成。**新セッション開始の儀式**。

```
inherit_persona()
→ "## Persona inheritance
   ## Values (3)
   - ...
   ## Intentions (2) ..."
```

## reflect aspect (Phase D)

| aspect | 内容 |
|---|---|
| `tasks_todo` | アクティブタスク、締切順、近いものハイライト |
| `tasks_doing` | 直近 1 時間に `start()` されたタスク |
| `tasks_completed` | 完了タスクの年表（時系列） |
| `tasks_abandoned` | 影の年表（reason 付き） |
| `commitments` | アクティブ commitment、締切順、⚠️ 警告 |
| `values` / `intentions` / `relationships` | それぞれの一覧 |
| `persona` | 全合成（= `inherit_persona`） |

## 典型フロー

### 朝の儀式（セッション開始）

```
inherit_persona()
reflect(aspect="commitments")           # 期限が近いものを確認
reflect(aspect="tasks_todo", limit=5)   # 今日のタスク候補
```

### 仕事中

```
commit(content="MCP の forget docs を追記", parent_id=<commitment_id>)
start(<task_id>)                        # 着手
# ... 作業 ...
complete(<task_id>, outcome="PR #42 でマージ", emotion=0.7)
```

### 晩の儀式（セッション終了）

```
reflect(aspect="tasks_completed", limit=5)
revalidate(<最も嬉しかった完了タスク>, emotion=0.7)   # 重力史に祝福を残す
```

### 影の年表を残す

```
abandon(<task_id>, reason="優先度が下がった、3ヶ月後に再評価する")
```

→ 関連: [Memory Tools](MCP-Reference-Memory.md), [Maintenance Tools](MCP-Reference-Maintenance.md)
→ パターンと哲学: [Plans — Phase D](Plans-Phase-D-Persona-Tasks.md)
