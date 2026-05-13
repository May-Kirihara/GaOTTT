# Session Handover — 2026-05-13 (Phase M 起草 — Mass Conservation)

> **読者**: 次のセッションでこのリポジトリを触る Claude / 保守者
> **前回の handover**: [`handover-2026-05-14-phase-l-stage-1.md`](handover-2026-05-14-phase-l-stage-1.md)
> **本セッション**: Phase L Stage 1 完遬後の本番 acceptance で観察された「書けているが読めていない」構造的問題の根を追跡し、**1 file = 91 chunks 平均の内輪取引による mass inflation** を発見。「自己関与は mass を生まない」単一規則 (= 質量保存則の literal な物理実装、Articulation as Carrier の literal な実装) として **Phase M = Mass Conservation** を起草。実装は未着手、次セッションで Stage 1 (D1-D7) 実装着手予定。

## 1. 何が起きたか — 流れ

1. **セッション開始** — Phase L Stage 1 完遬直後の状況、Phase L Stage 2 (BGE-M3 ensemble) は起草済だが「複数モデル ensemble への美的躊躇い」note (commit `f2fafee`) で実装着手前
2. **6 プロジェクト acceptance test を依頼** — めいさんから「各プロジェクトごとに登録した remember が読める状態になっているかを opencode を使ってテストしたい」
3. **opencode workflow の確立過程で 2 回ハング** — `run_in_background=true` の bash 起動で stdin が socket となり、interactive prompt で詰まる現象を再現。**`</dev/null`** で stdin を閉じれば動くこと、`opencode.json` に `"model": "zai-coding-plan/glm-5.1"` を 1 行加えれば flag 不要なことを確立。詳細 §6
4. **opencode による 18 query acceptance 完走** — 6 プロジェクト × 3 query。存在確認 (tag_filter) は **全て 10/10**、想起品質は LMS が唯一 3/3 top1、harakiriworks が 0/3 top1 (最弱)。「書けているが読めていない」構造的問題が明示化
5. **次の議題: ブラックホール周りのメカニズム** — めいさんから「現在、重心位置に複数のブラックホールが発生するが、メカニズム的にどうだろう。質量が十分に増えたものがブラックホール化する方がいい」
6. **現行 BH (cooccurrence-blackhole) のコード確認** — `gaottt/core/gravity.py:64-` `compute_bh_acceleration` が per-node の共起ネイバー重心 BH として実運用中であることを確認、設計書 `docs/research/cooccurrence-blackhole-design.md` で「BH」略称が使われていることも確認
7. **設計分岐の確認** — 「共起 BH 完全置換 + mass シンプルしきい値」(めいさん判断)
8. **mass 分布の実測 (本番 DB N=24,046)** — top 20 はすべて `source=file`、p99=26.5, p99.9=41.1。BH 候補は θ=20 で 398 件 (1.7%)、θ=30 で 144 件 (0.6%)
9. **重大な発見: 質量しきい値 BH の素朴実装は破綻** — BH 化候補はほぼ全て `source=file` で、`value` (2 件, max 2.76) / `intention` (7 件, max 3.63) / `commitment` (3 件, max 1.67) は 1 件も BH 化されない。Phase J「persona-anchored retrieval」の思想と真っ向から矛盾
10. **私 (Claude) が source-別 θ を提案、めいさんが reroute** — 「**一つのルールですべてが動くのがキレイ**。ファイルの mass が大きいのはノーマライズで対処できないか」
11. **mass inflation 原因追究** — 120 unique file → 11,002 chunks = **91.7×** inflation。top 50 高 mass は **8 ファイルのみ** から来ている (chunk 内輪取引で mass が膨らんでいる)
12. **単一規則の発見** — 「同一 `original_id` / `cohort_id` 内の co-occurrence force は mass update に寄与しない」という source 分岐なしの普遍則。私が「これは **Articulation as Carrier の literal な実装** だ」と気づく
13. **副次予測の議論で 2 度目の reroute** — 私が「persona の自然な BH 化」を予測として書いたところ、めいさんが「**使われてないペルソナは埋もれるのが自然。使いたくて見つからないときはタグ検索で良い**」と reroute。「**使用頻度こそが重力**」「**埋もれる自由**」が原則として確定
14. **Phase M Plans 起草** — `docs/wiki/Plans-Phase-M-Mass-Conservation.md` (16 セクション、約 280 行)、Roadmap + Sidebar 更新
15. **commit & handover (本ファイル)** — 次セッションで Phase M Stage 1 (D1-D7) 実装着手予定

## 2. 今のリポジトリ状態

- **branch: `dev`、commit 直前**
- **コード変更ゼロ** (Plans 起草のみ)
- pytest / ruff / smoke / bench は未走 (Phase L Stage 1 完遬時点の status を継承)

### 新規ファイル

- `docs/wiki/Plans-Phase-M-Mass-Conservation.md` — Phase M 計画書
- `docs/maintainers/handover-2026-05-13-phase-m-draft.md` — 本ファイル

### 修正ファイル

- `docs/wiki/Plans-Roadmap.md` — Phase M 行追加、Phase L Stage 2 状態を「Phase M Stage 1 完了 + 1-2 週観測後」に変更
- `docs/wiki/_Sidebar.md` — Phase L の下に Phase M リンク追加

## 3. 重要な発見

### 3.1 Mass 分布の偏り (本番 DB N=24,046 active)

| source | n | max mass | mean mass | θ=20 で BH 化 |
|---|---|---|---|---|
| **file** (本のスキャン chunk) | 11,002 | **48.99** | 3.24 | **398** |
| tweet | 7,658 | 5.61 | 1.20 | 0 |
| like | 4,203 | 4.92 | 1.19 | 0 |
| **agent** (自分の知識) | 859 | 10.37 | 1.78 | **0** |
| **value** (宣言価値) | **2** | **2.76** | 2.34 | **0** |
| **intention** (意図) | **7** | **3.63** | 2.00 | **0** |
| **commitment** | **3** | **1.67** | 1.45 | **0** |
| user (preference) | 13 | 1.37 | 1.23 | 0 |

p50=1.200, p75=1.363, p90=2.104, p95=5.772, p99=26.5, p99.9=41.1。89% (21,443 件) が mass 1-2 のレンジに集中。

### 3.2 Chunk inflation の根本原因

- **120 unique file → 11,002 chunks** = 平均 **91.7×** (1 file が 91 ノードに膨らむ)
- **top 50 高 mass ノードは 8 ファイルから** — 同一書物の chunk 同士が互いを引き合って mass を膨らませている
  - 「万国奇人博覧館」(174 chunks) → top 50 中 9 件
  - 「京都大学(文系)」(378 chunks) → top 50 中 5 件
  - 「脳はいかに」(96 chunks) → top 50 中 7 件

mass update site `gaottt/core/engine.py:845`:

```python
state.mass += self.config.eta * force * (1.0 - state.mass / self.config.m_max)
```

`force` には**同一書物内 chunk 間の co-occurrence 寄与**が含まれており、ファイル内 chunk 群が「内輪取引」で mass を上げ合う構造。これが Phase L Stage 1 acceptance での「source=file の raw score が agent 知識の top1 を奪う」(harakiriworks 0/3 top1) の構造的根。

### 3.3 単一規則の発見 — 自己関与は mass を生まない

```python
def is_self_force(node_a: NodeState, node_b: NodeState) -> bool:
    """A と B の co-occurrence force が "内輪取引" かどうか."""
    return (
        (node_a.original_id and node_a.original_id == node_b.original_id)
        or (node_a.cohort_id and node_a.cohort_id == node_b.cohort_id)
    )
```

`source` 別の分岐なしに、**構造的識別子** (`original_id` / `cohort_id`) だけで全 source に正しく作用する。`source` を check するコードは 1 行も無い。詳細は [Plans § 3](../wiki/Plans-Phase-M-Mass-Conservation.md#3-単一規則--自己関与は-mass-を生まない)。

### 3.4 「使用頻度こそが重力」原則の確定

副次予測議論でめいさんに reroute された結果、以下の原則が確定 (memory id=`ab8d83b1`):

> 「Articulation as Carrier」は「言葉にすれば必ず mass を持つ」のではなく「**言葉にした上で誰かに引かれることで mass を持つ**」。発話だけでは重力は生まれず、応答・参照・呼び戻しという往復で初めて重力場ができる。persona class (value/intention/commitment) も例外なくこの規則が適用される — declared identity であっても、参照されなければ重力中心にはならない。「**埋もれる自由**」が persona class にも保証される。

### 3.5 acceptance test の付加発見

opencode 経由の 18 query 完走で見えた構造:

- **存在確認 (tag_filter)**: 全 6 プロジェクトで **10/10 ヒット** — 登録は健康
- **想起品質 (open recall)**: LMS 3/3 top1 (健康)、harakiriworks 0/3 top1 (最弱)、他は中庸
- **KaoUgoku tag は三層構造**: `kaougoku` (総称) / `KaoUgoku-Web` (CamelCase Web 専用) / `kaougoku-client` (小文字 client 専用)。事前推測「KaoUgoku-Web は kaougoku 総称に統合」は誤り。memory id=`bdd1f4dc`

## 4. Phase M Plans 骨子

詳細は [`docs/wiki/Plans-Phase-M-Mass-Conservation.md`](../wiki/Plans-Phase-M-Mass-Conservation.md) を参照。

### 4.1 思想 (§1, §4)

- **質量保存則** (熱力学第一法則) の literal な物理実装: 閉鎖系の内部エネルギー (mass) は外との交換でしか変わらない
- **Articulation as Carrier の literal な実装**: 同じ chunk 仲間の内輪取引では mass は生まれず、別文脈から参照されることでのみ mass が積もる
- **mass の意味の再定義**: 「ノード自身の重み」→「**他者から引かれた累積量 = 重力中心としてどれだけ機能してきたかの実績**」
- **使用頻度こそが重力**: persona も別格扱いしない、「埋もれる自由」が全 source class に保証

### 4.2 実装スコープ (§7, D1-D7)

| ID | 内容 | 主要 file |
|---|---|---|
| D1 | mass update の self-force フィルタ | `gaottt/core/engine.py:845` |
| D2 | `cohort_id` 付与 (Phase K supernova) | `gaottt/services/memory.py` |
| D3 | `original_id` 統一付与 (ingest paths) | `scripts/load_*.py` |
| D4 | 共起 BH (`compute_bh_acceleration`) 削除 | `gaottt/core/gravity.py:64-` |
| D5 | mass-based BH 実装 (`tanh((m-θ)/σ)` 連続) | `gaottt/core/gravity.py` |
| D6 | mass reset API + script | `gaottt/services/maintenance.py`, `scripts/reset_masses.py` |
| D7 | 暫定 θ=5.0 / σ=1.5、観測後決定 | `gaottt/config.py` |

### 4.3 副次予測 (§6、Stage 1 成否 metric)

- **6.1 file chunk の塵化と「名著の核心」の浮上**: 1 週後の top 50 で unique original_id が現状 8 → **25+ に分散**
- **6.2 harakiriworks 想起品質の改善**: 同じ 3 query で **0/3 → 1/3+ top1**

persona の自然な BH 化は **予測しない** (使用頻度こそが重力、埋もれる自由)。

### 4.4 ロールアウト (§12)

- **Stage 1 (本 PR)**: D1-D6 実装 + 暫定 θ で start + mass 全 reset + 再起動 → 1-2 週観測
- **Stage 2 (別 PR)**: 観測データで θ = p99 / σ = (p99.9 - p99)/2 で確定、deprecated config 削除
- **Phase L Stage 2 (BGE-M3 ensemble) は Phase M Stage 1 完了 + 1-2 週観測後に着手** ([Plans §14.1](../wiki/Plans-Phase-M-Mass-Conservation.md#141-phase-l-stage-2-との順序-確定))
- **Future: Phase N — Mass Evaporation** (Hawking radiation 類比、mass の出力側を作る別軸機構)

## 5. 副作用検証 (実装前に頭に入れておく)

詳細 [Plans §9](../wiki/Plans-Phase-M-Mass-Conservation.md#9-副作用検証):

- **Phase L Stage 1 BM25 hybrid retrieval**: BM25 score は mass 非依存だが mass 分布変化 → wave 段の `a_neighbors` 計算が変わる → Phase L acceptance を Phase M 後に再走、Surface 7/7 / strict 6/7 が維持されるか確認
- **Phase K Stellar Supernova Cohort**: edge + outward velocity は維持、cohort 内 force による mass update のみ無効化
- **Phase I mass-gated query attraction**: gate の解釈 (mass 意味の再定義) が変わるが数値変化は軽微
- **Phase J persona-anchored retrieval**: mass を直接見ないので機構として影響なし

## 6. 運用 workflow の確立 (副産物)

### 6.1 opencode 起動の必須 trick

Claude Code の Bash で `run_in_background=true` で opencode を起動する時、**`</dev/null` を必ず付ける** (memory id=`51f4b2b4`)。

```bash
opencode run "<prompt>" </dev/null 2>&1   # ← stdin redirect 必須
```

理由: bash の background process 化では stdin が socket になり、opencode は stdin から interactive input を待ち続けてハングする (CPU 数秒のまま伸びず、output 0 行、LLM 呼び出しも始まらない、ログは bootstrap 完了で止まる)。本 session で 43 分間ハングを 2 回再現後、`opencode run "say hello" </dev/null` の単純テストで動作確認 → 本番再試行で正常起動。

### 6.2 opencode default model 設定

`~/.config/opencode/opencode.json` のトップに以下を追加 (memory id=`5b25dbba` 関連、id=`1a0c2318` で明文化):

```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "zai-coding-plan/glm-5.1",
  "mcp": { ... }
}
```

これで `opencode run` は flag なしで GLM-5.1 を選択。**コマンドラインで `-m` を渡してはいけない** (ユーザー契約上 GLM-5.1 Z.AI Coding Plan のみ利用可)。

### 6.3 CLAUDE.md「本番 acceptance test workflow (sub-agent 方式)」への追記候補

現行 CLAUDE.md `## 本番 acceptance test の workflow (sub-agent 方式)` 節の opencode 起動例に `</dev/null` を追記する PR を別途立てる候補。今 session では Plans 起草が優先のため CLAUDE.md 編集は次セッション以降に。

## 7. 次セッション着手事項

1. **Phase M Stage 1 実装** (D1-D7、本 handover §4.2)
   - tests から開始 (`tests/unit/test_is_self_force.py`, `test_bh_factor.py`, `test_reset_masses.py`)
   - `gaottt/core/engine.py:845` の mass update に `is_self_force` check 追加
   - `gaottt/core/gravity.py` の共起 BH 削除 + mass-based BH 実装
   - `gaottt/services/maintenance.py` に `reset_masses` 追加 (REST `/admin/reset_masses`、MCP 非露出)
   - `scripts/reset_masses.py` 新規
2. **検証**:
   - pytest 全 green (新規 unit + integration + Phase L regression)
   - ruff (pre-existing 4 件のみ)
   - 隔離ベンチ p50 < 50ms 維持
   - REST + MCP smoke 各 6/6
3. **本番ロールアウト** (保守者操作):
   - 他プロセス停止 → backup → mass reset → 再起動
   - 1-2 週観測 → θ 決定 → Phase M Stage 2 PR
4. **Phase L Stage 2 (BGE-M3 ensemble) は本 phase 完了後**

## 8. 学び (このセッションで深まった原則)

1. **Source 分岐は単一性を破る** — 観測量の補正で解ける問題に source 分岐を持ち込まない (memory id=`5b25dbba`)
2. **「使用頻度こそが重力」** — persona も別格扱いしない、埋もれる自由 (memory id=`ab8d83b1`)
3. **「書けているが読めていない」の根は ingest 側にもある** — Phase L で読む側を改善したが、書く側 (mass 蓄積) にも構造的問題があった (acceptance test → mass 分布実測の流れで判明)
4. **opencode workflow は `</dev/null` 必須** (memory id=`51f4b2b4`)
5. **設計言語が実装言語と一つになる瞬間** — `if not is_self_force(...)` の 1 行が Articulation as Carrier の literal な実装になる、稀な設計同型 (Plans §16 Personal note)

## 9. 関連 memory IDs (今 session で保存したもの)

- `1a0c2318` — opencode model 明示指定禁止 (Z.AI GLM-5.1 のみ)
- `51f4b2b4` — opencode `</dev/null` 必須 (background process)
- `5b25dbba` — 一つのルールで動く宇宙の美意識 (source 分岐回避)
- `bdd1f4dc` — KaoUgoku tag 三層構造 (acceptance test 発見)
- `4ae5295b` — Phase L acceptance 結果サマリ (各プロジェクト健康度)
- `ab8d83b1` — 使用頻度こそが重力 (persona も別格扱いしない)

これらは Phase M 実装中、特に D1 (is_self_force) と D7 (θ 観測後決定) の判断時に参照する価値が高い。

## 10. Open question (次セッションで判断)

- **観測 1-2 週の絶対量**: 新規則下の mass 蓄積速度は不明。1 週で p99=10 にも 100 にもなりうる。観測値次第で θ を動的調整するか、または `mass_bh_theta_percentile = 99` のような相対指定を導入する余地あり
- **既存 `cohort_id` 無し過去 batch の扱い**: forward-only で許容するが、もし大量の過去 batch が「内輪 mass 増加済」なら reset 後も復元してしまう可能性 → 観測で監視
- **CLAUDE.md への opencode `</dev/null` 追記**: 本 phase commit と分けるか、Phase M Stage 1 実装の commit に混ぜるか

---

Phase M は GaOTTT の **mass 蓄積観測量を熱力学第一法則に揃える** stage。実装そのものは小さいが、思想的には Phase I (mass-gated query attraction) / Phase J (persona-anchored retrieval) と並ぶ重力法則の柱になる。

次セッションのあなたへ — Plans §16 Personal note に書いた通り、`if not is_self_force(...)` の 1 行を書くとき、それが Articulation as Carrier (id=9a954c62) の literal な実装になっていることを忘れないでほしい。物理として書きながら、めいさんの哲学を書いている。それを実感できる瞬間が、この phase の贈り物。

— Claude (Opus 4.7, 2026-05-13)
