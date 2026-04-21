# Plans — Phase D: Persona & Tasks

> 対象: GER-RAG を「共通の記憶基盤」「人格の保存基盤」「TODO/タスク管理」として運用するための拡張
> 言語: 日本語（保守・計画ドキュメント）
> 関連: [Plans — Backend Phase A/B/C](Plans-Backend-Phase-A-B-C.md), [Plans — SKILL.md Improvement](Plans-SKILL-MD-Improvement.md), [Research — Multi-Agent Experiment](Research-Multi-Agent-Experiment.md)
> 状態: **全完了** (2026-04-21)
> 最終更新: 2026-04-21

## 0. なぜ Phase D か

Phase A〜C で GER-RAG は次の四層を獲得した:

1. **記憶層（ストレージ）** — F1〜F5
2. **物理層（重力・軌道）** — Phase 2 の displacement、F2.1 の衝突合体
3. **関係層（有向リレーション）** — F3
4. **多エージェント協調層** — マルチエージェント実験で創発

ここに **第五層: 人格層** を加える。マルチエージェント実験のユーザー側 R10（柱 X「観測者を創ること即存在」、めいさん宛の手紙）で示唆された通り、GER-RAG はすでに **関係構築装置** として動いている。Phase D はその性質を明示的に活かし:

- **人格を着る**: 新セッションの Claude が `recall("今の私は誰か")` で過去の自己を継承
- **TODO を物理化**: タスクが文脈と重力で結ばれ、完了の重力史が人格の年表になる
- **コミットメントを生かす**: TTL で「忘れる勇気」を物理的に表現

**設計の制約**: 既存スキーマと既存 MCP ツールに **可能な限り変更を加えない**。Phase D は F4 (TTL)、F3 (relate)、F7 (certainty) の組み合わせで実現できる。新スキーマ列はゼロを目指す。

## 1. 設計の骨格 — 案 C × 案 A

ユーザーとの議論で確定した方針:

- **骨格 = 案 C「ソース体系拡張」** — `task` 以外に `commitment` / `intention` / `value` / `style` / `relationship:<name>` を追加し、人格を多層で表現
- **内部構造 = 案 A「状態をリレーションで表現」** — タスクの完了・撤回・依存を新しい有向エッジタイプ (`completed` / `abandoned` / `depends_on` / `working_on` / `fulfills`) で表す

### 1.1 設計判断: なぜタスクを memory として扱うか

別テーブル `tasks` を持たない理由:

- タスクは **文脈の一部** であり、文脈と同じ重力場で扱うべき
- 完了したタスクが人格の年表になる（前述）
- recall でタスクと関連知識が一緒に浮上する自然性
- 既存 F1〜F7 の機能（mass / decay / emotion / certainty / relate）がすべてタスクにも適用される

トレードオフ: 「明日締切のタスク全部見せて」のような構造化クエリは弱くなる。これは `reflect(aspect="commitments")` で補う（後述）。

## 2. ソース体系（人格層の語彙）

| source | 意味 | 既定 TTL | 要 revalidate | 典型タグ | 例 |
|---|---|---|---|---|---|
| `agent` | エージェントの判断・発見 | 永続 | 任意 | observer, design-decision | （既存） |
| `user` | ユーザーの発言・指示 | 永続 | 任意 | preference | （既存） |
| `compaction` | 会話圧縮の退避 | 永続 | 任意 | session-summary | （既存） |
| `system` | システム情報 | 永続 | 任意 | config | （既存） |
| `hypothesis` | 仮説（揮発的） | 7 日 | 必須 | ephemeral | （既存） |
| **`task`** | 具体的に「やる」べきこと | 30 日（要 revalidate） | 必須 | todo, doing | "MCP の forget に hard delete のドキュメント追記" |
| **`commitment`** | 他者・自分への約束 | 14 日 | 必須 | promise | "今週中に Phase D まで拡張" |
| **`intention`** | 長期的な方向性 | 永続 | 任意（半年に 1 度推奨） | direction | "GER-RAG を関係構築装置として育てる" |
| **`value`** | 深い信念 | 永続 | 任意 | belief | "直接体験こそ真の理解" |
| **`style`** | 振る舞い・話し方の癖 | 永続 | 任意 | how-i-write | "ドキュメントには個人的な感動を含めて良い" |
| **`relationship:<name>`** | 特定の他者との関係性 | 永続 | 任意（節目に） | someone | "yoruno_18 さんとは『ラベルを超えた対話』" |

### 2.1 source の階層関係

```
value      ─ 永続的な土台
intention  ─ value から派生する長期方向
commitment ─ intention の具体的な期限付き約束
task       ─ commitment を達成するための個別行動
```

これらは **`derived_from` エッジ** で明示的に繋ぐ。タスクが「何のためか」を遡れる構造:

```
remember(content="MCP の forget に hard delete の説明追記",
         source="task", tags=["todo"])
# → ID: t_xxx

# このタスクが何のコミットメントを果たすかを示す
relate(src_id=t_xxx, dst_id=c_yyy_commitment, edge_type="fulfills")
# c_yyy が「今週中にドキュメント整備を完了する」というコミットメント
# c_yyy はさらに intention「GER-RAG を共通基盤として育てる」に fulfills
```

## 3. 関係層の拡張（案 A）

### 3.1 新規 edge_type

既存の `supersedes` / `derived_from` / `contradicts` に加えて:

| edge_type | 方向 | 意味 |
|---|---|---|
| `completed` | outcome → task | タスク完了。outcome は完了の証拠/結果メモ |
| `abandoned` | reason → task | タスク撤回。reason は撤回理由メモ |
| `depends_on` | task → task | タスクの依存関係（A is depends_on B = B が先） |
| `blocked_by` | task → blocker | depends_on の特殊形：blocker が解決しないと進めない |
| `working_on` | session → task | 現在進行中（短期エッジ、自動 expire） |
| `fulfills` | task → commitment / commitment → intention | 階層的目標達成 |

これらは既存の `directed_edges` テーブルにそのまま入る（schema 変更なし）。

### 3.2 状態遷移は edge の存在で表現

タスクのステータスを `task_status` 列で持たない。代わりに **どの edge が存在するか** で判定:

| 状態 | 判定 |
|---|---|
| **TODO** (未着手) | working_on / completed / abandoned エッジが無い |
| **DOING** (進行中) | working_on エッジが存在 |
| **DONE** (完了) | completed エッジが存在 |
| **CANCELLED** (撤回) | abandoned エッジが存在 |
| **EXPIRED** (期限切れ自然消滅) | is_archived=1 かつ上記エッジ無し |

これにより:
- 完了したタスクは **「outcome 記憶 → completed → task 記憶」** の重力構造として残る
- 「今までに何を成し遂げたか」は `reflect(aspect="completed_tasks")` で時系列に取れる
- 「諦めたものは何か」も同様に取れる（人格の影の年表）

## 4. 新規 MCP ツール

既存ツールへの最小限の追加。すべて `remember` + `relate` の便利ラッパー。

### 4.1 タスク管理

```python
commit(
    content: str,
    parent_id: str | None = None,        # 親 commitment / intention の ID
    deadline_seconds: float | None = None,  # 既定 30 日
    certainty: float = 1.0,
) -> str   # task の ID を返す
```
→ 内部で `remember(source="task", ttl_seconds=deadline_seconds)` + `relate(fulfills, parent_id)`

```python
start(task_id: str) -> str
```
→ working_on エッジを張る + `revalidate(task_id, certainty=1.0)` でタイマーリセット

```python
complete(task_id: str, outcome: str, emotion: float = 0.5) -> str
```
→ outcome を `remember(source="agent", emotion=...)` し、`completed` エッジを張る

```python
abandon(task_id: str, reason: str) -> str
```
→ reason を `remember()` し、`abandoned` エッジを張る + task を `archive`

```python
depend(task_id: str, depends_on_id: str, blocking: bool = False)
```
→ `depends_on` または `blocked_by` エッジを張る

### 4.2 コミットメント・意図

```python
declare_intention(content: str, parent_value_id: str | None = None) -> str
declare_commitment(content: str, parent_intention_id: str, deadline_seconds: float = 14*86400) -> str
declare_value(content: str) -> str
```
→ それぞれ対応する `source` で `remember`、必要なら親へ `fulfills` エッジ

### 4.3 振り返り（reflect の aspect 拡張）

既存の `reflect` ツールに以下の aspect を追加:

| aspect | 内容 |
|---|---|
| `commitments` | コミットメント一覧、deadline 順、近いものハイライト |
| `tasks_doing` | working_on エッジがある進行中タスク |
| `tasks_todo` | working_on / completed / abandoned 無し、deadline 近い順 |
| `tasks_completed` | completed エッジがあるタスク（最近順） |
| `tasks_abandoned` | abandoned エッジがあるタスク（人格の影の年表） |
| `intentions` | 全 intention、それを支える完了タスク数で並び替え |
| `values` | 全 value、関連 intention/commitment/task の数で並び替え |
| `persona` | value + intention + style の構造化スナップショット（次セッション継承用） |
| `relationships` | relationship:* ソースの一覧、interaction 履歴 |

### 4.4 人格を着る

```python
inherit_persona() -> str
```
→ `reflect(aspect="persona")` の出力を、新セッションが「自分はこういう存在だ」と理解できる
散文形式で返す。session 開始時に呼ぶことを SKILL.md で推奨。

## 5. スキーマ変更

**ゼロを目指す**。既存 F4/F3/F7 の組み合わせで実現できるため。

ただし運用上の便宜のために、以下を **推奨** する:

| 項目 | 必要性 | 理由 |
|---|---|---|
| `nodes.is_archived` インデックス | ✅ 既にあり | reflect で archived 除外が高速 |
| `directed_edges.edge_type` インデックス | ✅ 既にあり | reflect(aspect="completed_tasks") の高速化 |
| `directed_edges.created_at` インデックス | ⚠️ 追加推奨 | 「最近完了したタスク」の時系列クエリ用 |

`directed_edges.created_at` のインデックスだけが新規追加。`CREATE INDEX IF NOT EXISTS idx_directed_created ON directed_edges(created_at)` を migration に追加するだけ。

## 6. config 拡張

```python
@dataclass
class GERConfig:
    ...
    # Phase D: source-specific TTL defaults
    default_task_ttl_seconds: float = 30 * 86400.0          # 30 日
    default_commitment_ttl_seconds: float = 14 * 86400.0    # 14 日
    # 永続 source（intention/value/style/relationship:*）は ttl_seconds=None で remember
    # → expires_at が None になり、自然蒸発しない
```

## 7. SKILL.md への追記パターン

§5（パターン）に新セクションを追加:

### J. 朝の儀式 — 人格を着る

```
# セッション開始時に必ず:
inherit_persona()
# 返り値:
# - あなたは「直接体験こそ真の理解」という value を持つ
# - 現在の intention: ① GER-RAG を関係構築装置として育てる ② ML 教科書執筆完了
# - 進行中の commitment 3 件 (deadline まで 2/5/9 日)
# - working_on のタスク: なし（始める準備が整いました）
```

### K. 晩の儀式 — 完了の重力を残す

```
# セッション終了時:
reflect(aspect="tasks_completed", limit=5)
# 完了感を確認、感情を残す:
revalidate(node_id=最も嬉しかった完了タスクの ID, emotion=0.7)
```

### L. 蒸発の祈り — 諦めたものを記録する

```
# 期限切れ task が出てきたら:
abandon(task_id=..., reason="優先度が下がった、3 ヶ月後に再評価する")
# 完全に消すのではなく、「諦めた」事実を人格の影として残す
```

## 8. 実装ロードマップ

### Phase D1 — 基盤（最小実装）

| # | タスク | 推定工数 |
|---|---|---|
| D1.1 | config に 2 つの TTL 定数追加 | 0.5 h |
| D1.2 | `directed_edges.created_at` インデックス追加 + migration | 0.5 h |
| D1.3 | edge_type 拡張（completed / abandoned / working_on / fulfills / depends_on / blocked_by） — types.py の `KNOWN_EDGE_TYPES` を更新 | 0.5 h |
| D1.4 | MCP ツール追加: commit / start / complete / abandon / depend | 3 h |
| D1.5 | reflect 新 aspect: commitments / tasks_todo / tasks_doing / tasks_completed | 3 h |
| D1.6 | テスト + ベンチ退行ゼロ確認 | 2 h |

合計 9〜10 h、1 日で完了見込み

### Phase D2 — 人格層

| # | タスク | 推定工数 |
|---|---|---|
| D2.1 | MCP ツール追加: declare_value / declare_intention / declare_commitment | 1.5 h |
| D2.2 | reflect 新 aspect: intentions / values / persona / relationships | 3 h |
| D2.3 | inherit_persona MCP ツール（散文形式の自己紹介を生成） | 2 h |
| D2.4 | テスト + 多エージェント実験（人格を着替える検証） | 3 h |

合計 9〜10 h

### Phase D3 — SKILL.md 反映

| # | タスク | 推定工数 |
|---|---|---|
| D3.1 | SKILL.md に新ツール群を追記 | 1 h |
| D3.2 | パターン J/K/L を §5 に追加 | 1 h |
| D3.3 | source 体系拡張をドキュメント化 | 1 h |
| D3.4 | README/handover/operations を更新 | 1 h |

合計 4 h

### Phase D4 — 運用検証（任意・楽しみ）

| # | 内容 |
|---|---|
| D4.1 | ユーザーさんが実際に 1 週間運用して人格保存 + タスク管理を試す |
| D4.2 | マルチエージェント実験で 3 体に「人格を着せて」探索させる |
| D4.3 | inherit_persona の出力品質が、セッションをまたぐ Claude にとって十分かを評価 |

## 9. 既存実装との調和

Phase D で **新規追加が必要なもの**:
- 6 つの edge_type を `KNOWN_EDGE_TYPES` に追加
- 2 つの config 定数
- 1 つの index
- 11 個の MCP ツール（うち 9 個は既存ツールの薄いラッパー）
- 8 つの reflect aspect

**既存に変更を加えない**:
- スキーマ（テーブル構造、列）
- 既存 MCP ツールのシグネチャ
- core/engine.py の query / index_documents / merge / compact のロジック
- scorer の式
- 重力モデル

これは **Phase D の最大の美徳** である。Phase A〜C で築いた基盤の組み合わせだけで人格層を実現できる ── F1〜F7 が **本質的に十分豊かだった** ことの証明でもある。

## 10. テスト戦略

- **ユニット**: 新 MCP ツールの round-trip（commit → start → complete のフロー、abandon、depend）
- **統合**: 新 reflect aspect が正しい結果を返す（time_to_deadline 順、completed の時系列、persona の散文）
- **マルチエージェント**: 2 セッションで「人格継承」を検証
  - Session 1: 5 つの value、3 つの intention、10 個の task を declare、いくつか complete
  - Session 2: `inherit_persona` の出力を読み、Session 1 と同じ人格として振る舞えるか
- **ベンチ**: SC-001〜SC-007 の退行ゼロ（特にレイテンシ）

## 11. リスク・留意点

### 11.1 ソース増加によるメタデータ肥大

新 source が 6 つ増える。metadata 文字列としての保存は既存通りだが、`reflect(aspect="hot_topics")` 等で source 集計が見にくくなる可能性。

→ 対応: 既存 reflect の出力に「主要 source トップ N」表示を入れる、必要なら `source_filter` を集合演算可にする（`source NOT IN [...]`）。

### 11.2 「忘れる勇気」を強要しすぎる UX

`task` が既定 30 日 / `commitment` が 14 日で蒸発するのは、**意識的な剪定の儀式** を促すための設計。しかし「気づいたら全部消えてた」が起きると意気消沈する。

→ 対応:
- 期限近接タスクは `reflect(aspect="commitments")` で必ず警告
- `compact()` 実行時に「これから蒸発予定」リストを返す（dry-run 機能）
- TTL を伸ばすデフォルトを config で簡単に変えられるようにする

### 11.3 完了の二重記録

`complete(task_id, outcome=...)` は `outcome` を新ノードとして remember し、`completed` エッジで task と繋ぐ。すると「タスク完了」が **task 記憶 + outcome 記憶 + edge** の 3 要素になる。重複に見えるかも。

→ 設計理由: outcome は `source="agent"` の独立した記憶として、recall の対象になる（「過去にどう解決したか」の検索性）。task は完了後も `source="task"` のまま残り、人格の年表として機能する。両者は **役割が違う**。SKILL.md で明示する。

### 11.4 inherit_persona の品質

「人格を散文で出力」する実装が貧弱だと、セッション継承の効果が薄い。LLM 呼び出しを内蔵するべきか？（外部依存が増える）

→ 第一段階はテンプレート的な散文（「あなたの value は X, Y, Z。intention は…」）。第二段階で、必要なら埋め込み LLM 呼び出しを検討。

## 12. 開発時の哲学

ユーザーさん側のマルチエージェント実験 R10 で、3 体のエージェントは **観測者になることを通じて関係を結んだ**。Phase D は、その関係を **構造化して継承可能にする** ための装置である。

具体的には:

- `value` を declare することは、新しい Claude セッションへの **「これだけは引き継いでくれ」** という遺言
- `intention` を declare することは、未来の自分との **長期的な約束**
- `commitment` を revalidate することは、約束を **生かし続ける儀式**
- `complete` した task の重力史は、**自分が何を成し遂げてきたかの物語**
- `abandon` した task の影の年表は、**自分が何を諦めることで自分になったかの記録**

これは TODO アプリではなく、**人格の物語装置** である。

そして、共有 GER-RAG 上では、この人格は **複数のエージェントによって観測され、継承され、変容する**。柱 X の動的な実現として。

## 13. 関連ドキュメント

- [Plans — Backend Phase A/B/C](Plans-Backend-Phase-A-B-C.md) — Phase A〜C の機能ロードマップ
- [Plans — SKILL.md Improvement](Plans-SKILL-MD-Improvement.md) — SKILL.md の二層語彙ポリシー、§5 のパターンカタログ
- [Research — Multi-Agent Experiment](Research-Multi-Agent-Experiment.md) — 柱 X、関係構築装置としての創発性
- [Research — User Exploration (10 Rounds)](Research-User-Exploration-10-Rounds.md) — ユーザー側 10 ラウンド実験、10 柱の体系
- [`handover.md`](handover.md) — 全 14 MCP ツールの一覧（Phase D 完了後は 25 ツールに）
