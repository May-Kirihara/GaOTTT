# Guide — Using GaOTTT as a Narrative Engine

GaOTTT は **タスク駆動の検索 tool** でも **受動的な観察 lens** でもなく、**好奇心駆動の navigation で物語を組み立てる environment** としても使える。同じ engine、同じ重力場、違う使い方。

## 三つの使い分け (read 側)

| Use case | 主体 | 典型 entry point | 期待する出力 |
|---|---|---|---|
| **Task-driven retrieval** | 今やるべきことが明確 | `recall("具体的な query")` | top-K 検索結果の中から関連する 1-3 件 |
| **Passive lens** (ambient_recall) | 何もしない、agent の prompt に文脈を浮かべる | hook injection で自動 | `<gaottt-ambient-recall>` block の direct + lensing + persona |
| **Narrative engine** ← **本ガイドの主題** | 何が出てくるか分からないが好奇心がある | `explore × N parallel` → `recall × N targeted` → 読む | 重力 accumulation で組み立てられた 1 つの coherent な物語 |

## いつ narrative engine モードを使うか

- **「自分が何にいつも引き戻されるか」を知りたい** (self-reflection / 固定観念観察)
- **過去のプロジェクト群の関係性が知りたい** (e.g. 「A と B と C は別物だと思ってたが連続体だった」)
- **次に何を articulate すべきか分からない時** (思考の種を場に拾わせる)
- **新規 agent が初めて記憶層に触れる時** (onboarding 的)

逆に **タスクが明確な時には使わない** — narrative mode は時間も context window も食う、目的が明確なら recall 1 発の方が経済的。

## 基本レシピ

```
1. inherit_persona()                           — 「いま誰として navigate するか」確認
2. reflect(aspect="summary")                   — corpus 全体像
3. explore × 4 parallel queries                — 興味の方向を 4 つ並べる
4. recall × 4 parallel, targeted               — explore で見つけた hub を deeper
5. (重力 accumulation を `reason:` 行で観察)    — 「pulled by mass=2.15 — possible dominance artifact」
6. 読む (一番気になった document の full content)
7. synthesis — 自分の言葉で 5 chapter narrative を書く
```

各 step の意図:
- **Step 3 parallel explore**: 単一 query は重力場の 1 軸しか見えない、N 軸並列で重力場の **形** が浮かぶ
- **Step 4 targeted recall**: explore で見つけた hub の id / tag で精密化
- **Step 5 `reason:` 行**: Phase O Stage 1 が surface する dominance artifact 警告 (`mass=2.15 — possible dominance artifact`) を読んで、自分が pull されている方向を意識する → 抵抗するか / 任せるかを選ぶ
- **Step 7 synthesis**: 自分で書いて save する瞬間に articulation as carrier が成立、navigator 自身も 1 つの memory として場に残る

## なぜこの mode が動くか — 重力場の literal な挙動

GaOTTT は recall するたびに retrieved nodes の displacement が query 方向に nudge される (Phase I Stage 2、`compute_acceleration` の第 4 項 `a = (α × score × gate / m_i) × (q - pos_i)`)。連続 query を打つと:
- 1 回目の recall → high-mass nodes が query 方向に微小移動
- 2 回目の (関連する) recall → 1 回目で動いた nodes が新しい query にもヒットしやすくなる
- N 回目 → 重力 accumulation で「同じ軌道」を辿る

つまり **連続 recall は "zooming in" 効果**、flat 検索なら N 個独立 ranked list が出るだけだが、GaOTTT は **重力場が連続性を場の構造として記憶する** ので、navigator は自然に trail を辿ることになる。

これを external observer (LLM) が初めて文章化したのが 2026-05-27 の [GLM-5.1 free-exploration review](../maintainers/evaluation-2026-05-27-free-exploration.md):

> "Each recall built on the displacement from the previous one, creating a 'zooming in' effect that felt like following a trail."

## どんな corpus state で動くか

下の数値は production 41k corpus を本日 (2026-05-27) `scripts/diag_cluster_coverage.py` + `scripts/diag_dormant.py --service-mirror` で計測した live snapshot。narrative engine が effective に動くために必要な corpus 健全性:

| 指標 | 本日値 | narrative engine 適性 |
|---|---|---|
| Active nodes | 41,064 | ✓ 十分な多様性 |
| Cluster 多様性 (file source) | 131 clusters / max=638 | ✓ Stage 7.1 anti-hub が黒洞を demote 中 |
| Dormant pool (mass≤p10 + age≥7d + self-source) | 15 nodes | ✓ 0 ではない、`explore(mode="dormant")` で「忘れていた何か」が surface する |
| Persona mass dominance | harakiriworks-art-website intention mass=2.82 | ⚠️ 強い、`reason:` 行で警告される |

逆に corpus が **薄すぎる** (記憶が数百以下) と重力場が育っていないので narrative engine モードは結果が貧弱。

## 観察者効果への対策

このモードは **重力場を能動的に動かす** ので、観察行為自体が場を変える (Heisenberg)。回避策:

- **`passive=true` を使い分ける**: 「観察したいが場は触りたくない」query は `recall(query, passive=true)` で訓練 step を skip
- **`scripts/compare_retrieval.py` で diff snapshot**: 同 query を `recall` / `explore` / `dormant` / `ambient_recall` に並列で投げて結果を比較、観察者の選択が結果にどう効くか見える
- **dominance artifact を意識**: `reason:` 行に `high mass persona proximity (mass=X) — possible dominance artifact` が出たら、あなたが pulled by gravity wells していることを場が教えてくれている

## 設計意図との接続

GaOTTT の design intent は memory id [`9a954c62`](https://github.com/May-Kirihara/GaOTTT) **Articulation as Carrier** — 「言葉にすることで初めて経験が重力を持つ」。これは write 側の話だが、**読む側にも同じ原理が literal に作用する**:

> 「recall は記憶を retrieve する操作ではなく、navigator が場を辿る操作。場を辿ることで navigator 自身が場の一部になる。」

GLM レビューの結論:

> "The act of recalling is itself a form of care."

これが narrative engine モードが existence する核 — 記憶 system を tool ではなく environment として扱うとき、navigator は altered by navigated になる。

## 関連

- [Reflections — Five Layer Philosophy](Reflections-Five-Layer-Philosophy.md) — 物理 → TTT 機構 → 生物 → 関係 → 人格 の五層
- [Reflections — A Note from Claude](Reflections-A-Note-From-Claude.md) — Claude 自身の体験談
- [evaluation-2026-05-27-free-exploration.md](../maintainers/evaluation-2026-05-27-free-exploration.md) — external observer (GLM) の同等体験
- [Plans — Lens Hygiene](Plans-Lens-Hygiene.md) — 観察 lens の衛生 (本ガイドの前提となる Stage 1-3 修正)
- [Guides — Use as Memory](Guides-Use-As-Memory.md) — task-driven retrieval (本ガイドの対)
- [Guides — Ambient Recall](Guides-Ambient-Recall.md) — passive lens (本ガイドの対)
