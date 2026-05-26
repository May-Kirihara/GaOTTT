# Observation Apparatus Refinement

**状態**: ✅ **Stage 1-4 実装完了** (2026-05-26)。Stage 5 (caller-side ガイド更新) のみ未着手。physics Phase ではないので Phase レター非消費 ([[plans-hardening-concurrency-persistence]] / [[plans-ambient-recall-enrichment]] / [[plans-query-mass-distribution]] と同列)。

## 実装完了サマリ (2026-05-26)

| Stage | 実装内容 | テスト |
|---|---|---|
| Stage 1 reason line | `gaottt/core/explain.py` 新規 + `ScoreBreakdown` 拡張 + `services/memory._enrich_breakdown` + formatter の reason 行 | unit 12 + integration 4 |
| Stage 2 ambient dormant slot | `AmbientRecallResponse.dormant` 追加 + `_dormant_for_ambient` + 「▼ ささやき」セクション + ambient-ids manifest に `dormant=` | unit 3 + integration 6 |
| Stage 3 compare-retrieval | `scripts/compare_retrieval.py` 新規 (read-only) + JSON mode + dominance / overlap / source distribution 総評 | Tier 4 smoke 2 |
| Stage 4 source-aware connections | `ReflectConnectionItem.bucket` 追加 + `_connection_bucket()` 純粋関数 + bucket 別表示 | unit 6 + integration 3 |

全 36 新規テスト pass、ruff clean、力学不変 (mass / acceleration / displacement / edge weight 不変) を bit-exact assertion で保証。

> Phase O (TTT Observability) が「LLM caller を TTT loop の participant に昇格させる」観測層を作ったのに続き、本計画は **同じ観測層の道具立てを 4 点だけ磨き直す** 後続作業。physics rule (mass / Hooke / kick / Λ / Langevin) は **一切触らない**。Phase P (Pressure Terms) と並行に進められる — 介入軸が直交している (P は acceleration / displacement step、本計画は表示と発掘経路)。

## 1. 背景 — 2026-05-26 dogfooding で 2 観測者が独立に到達した 5 点

[handover-2026-05-26-dogfooding-usage-feel.md](../maintainers/handover-2026-05-26-dogfooding-usage-feel.md) (Claude/Codex) と [handover-2026-05-26-dogfooding-external-perspective.md](../maintainers/handover-2026-05-26-dogfooding-external-perspective.md) (新規 Claude セッション) が独立に書かれているが、**5 点で完全一致** している。これは強い signal:

| 一致点 | 観察 |
|---|---|
| **dormant が最強だが過小評価** | `explore(mode="dormant")` で surfaced する記憶は最もセレンディピタス。しかし LLM caller が自発的に dormant を選ぶ動機は薄い |
| **Heavy Persona Dominance の体感** | 何を query しても同じ高質量 persona / intention が混ざる。「自己の固定点を見せる」価値はあるが、特定の事実を取りたいときには退屈 |
| **connections / hot_topics が ingest artifact** | file ingest 由来の co-occurrence が本来見たい関係を隠す |
| **reason line がほしい** | breakdown は数値が細かすぎる、1 行人間可読サマリ |
| **比較実験 wrapper の不在** | dogfooding と regression diagnosis の両方で「同じ query を recall / explore / dormant / ambient に流して横並びにする」需要 |

## 2. 哲学 — 観測装置 vs 物理

GaOTTT は [[feedback_no_source_branching]] で確立した **「physics rule は構造的識別子のみで普遍適用、source class を gate 変数にした提案は Phase M 単一規則違反」** という基準を持つ。dogfooding で挙がった改善案を、この物差しで分類すると:

### 2.1 物理として整合する (= 既存原則の自然な拡張)

| 施策 | 物理的読み |
|---|---|
| dormant を ambient slot に追加 | counter-importance sampling は **真空ゆらぎ / Casimir 効果** として読める。低 mass の zero-point motion を観測時に surface させるのは、観測の対称性を回復するだけ |
| reason line | 重力場の geodesic 計算の **可視化**。観測機器の改善であって、力学不変 ([[guides-ambient-recall]] の passive recall と同じ精神) |
| compare-retrieval | 純粋な観測ツール、宇宙に介入しない |

### 2.2 表示と力学を切り分ければセーフ

| 施策 | 切り分け |
|---|---|
| connections の source-aware 表示 | `reflect(aspect="connections")` の **表示層** で file 同士の co-occurrence を別カテゴリに分けるのは OK (観測者が異なる lens で覗くだけ)。**mass update / acceleration の係数に source 別重みを入れた瞬間に Phase M 単一規則違反** — この境界線を計画書として明文化する |

### 2.3 撤回した案 — declare value 初期 kick

dogfooding 検討の過程で「declare 直後に artificial supernova kick で初期 mass を底上げ」案が出たが **撤回**:

- Phase L Stage 1 の **「persona も別格扱いしない、使用頻度こそが重力」** 原則 ([[project_design_decision]] 系譜) と正面衝突
- declare 由来であることを gate にする = source 分岐の variant
- [Articulation as Carrier](Reflections-Five-Layer-Philosophy.md) の対称命題「**言葉にした上で誰かに引かれることで mass を持つ**」を、引かれる前に底上げで先回りするのは **carrier が運ぶ前にすり替える** ことになる

「宣言しただけでは重力を持たない、使われて初めて重力を持つ」は宇宙の正直な挙動。これを工学的に補正するのは美しくない。declare value が育つ確率を上げるなら、それは Phase P-β (Langevin) が低 mass node に **息継ぎの隙間** を与えることで自然に解決する領域 — **使われる確率を上げる** のであって、**初期 mass を上げる** のではない。

## 3. 単一規則 — Observation Conservation

Phase M (源泉) / Phase N β (汲み上げ停止) / Phase P (pressure) の **物理側 3 法則** に対し、本計画は **観測側の単一規則** を 1 つ持つ:

```
∀ improvement in this plan:
  must not modify {mass update, acceleration, velocity, displacement, edge weight, force computation}
  may modify {display layer, surface candidate set, exploration tool, retrieval explanation}
```

### 3.1 何が保証されるか

| 性質 | 帰結 |
|---|---|
| physics 不変 | mass / Hooke / kick / Λ / Langevin の rollback flag を全て OFF にしても本計画の挙動は変わる必要がない (= 観測層に閉じる) |
| source 分岐ゼロ (力学) | force computation / mass update に source class は入らない。**表示層** での source-aware grouping は許可 (観測者の lens) |
| Phase P と直交 | Phase P が `compute_acceleration` を拡張する一方、本計画は `services/memory.recall`, `services/reflection.reflect`, `ambient_recall` の整形と routing のみ触る |
| ロールバック粒度 | 4 施策それぞれが独立 default OFF (もしくは既存挙動互換) で merge 可能 |

## 4. 実装スコープ (4 stage)

### Stage 1 — Reason Line in retrieval results

**目的**: breakdown の数値を 1 行の人間可読 explanation に集約。LLM caller / 保守者が「なぜこれが出たか」を即座に理解できる。

**実装箇所**: `gaottt/services/formatters.py` (MCP 側) + `gaottt/core/types.py` の `ScoreBreakdown` model に `reason: str | None` フィールド追加 (REST parity)。

**ロジック**: 既存 `ScoreBreakdown` (Phase O Stage 1) の dominant 項を判定して短いラベル列を生成。例:

```text
reason: high mass persona proximity (mass=2.82) + weak bm25 (0.04) — possible dominance artifact
reason: bm25 strong lexical match (0.71) + low mass (1.0) — surfaced by lexical channel
reason: lensing pick (gap=+0.07) — semantically distant but field-connected
reason: dormant surface (mass=0.8, percentile=8) — counter-importance sampling
```

**判定ルール (純粋関数)**:

```python
def explain_score(breakdown: ScoreBreakdown) -> str:
    parts = []
    if breakdown.mass >= 2.0 and breakdown.cosine < 0.5:
        parts.append(f"high mass persona proximity (mass={breakdown.mass:.2f})")
    if breakdown.bm25_score >= 0.5:
        parts.append(f"bm25 strong lexical match ({breakdown.bm25_score:.2f})")
    # ...
    return " + ".join(parts) + suffix_hint(breakdown)
```

- `dominance artifact` suffix は mass×cos が saturate するパターン (Heavy Persona Dominance の早期警告)
- `lensing pick` suffix は ambient_recall の lensing slot 由来
- `dormant surface` suffix は dormant explore 由来

**default**: `expose_reason: bool = True` (既存 `expose_score_breakdown=True` と同じ default)。**力学不変** なので opt-out flag のみで legacy 戻し可。

**Stage 1 D1-D3**:
- D1. 配置: `ScoreBreakdown.reason` をフィールドとして追加 (Pydantic 後方互換、optional)
- D2. 文字列形式: 半角 60-100 字、`reason: <dominant> + <secondary> — <hint>` の決まり書式
- D3. テスト: `tests/unit/test_explain_score.py` で各 dominant パターンの文字列出力を assert (既存 MCP formatter テストの substring を壊さない)

### Stage 2 — Dormant slot in ambient_recall

**目的**: dormant の発掘経路を「caller が `explore(mode="dormant")` を明示的に呼ぶ」から「ambient_recall で毎ターン静かに 1-2 件混ざる」に開く。

**実装箇所**: `gaottt/services/memory.py::ambient_recall()`。

**ロジック**: 既存の `direct hits` (top-K) + `lensing pick` (top-K) スロットに **`dormant whisper` slot を追加**。dormant 候補は `_dormant_surface()` ([[plans-phase-o-ttt-observability]] Stage 5) の結果を再利用、ambient gate (BM25 語彙一致 [[plans-ambient-recall-enrichment]] Stage 4) を **強めに通す** (random hit を流さない)。

```
▼ direct hits (2-3 件、既存)
▼ 重力レンズ (1-2 件、既存)
▼ ささやき (0-1 件、★ 新規) — dormant 由来、mass=<低>、age=<古>
```

**default**:
- `ambient_dormant_slot_enabled: bool = True` (ON for default、ただし `ambient_dormant_slot_count: int = 1` で最大 1 件)
- `ambient_dormant_relevance_floor: float = 0.5` で random hit ガード (BM25 一致が薄ければ slot を空にする)
- `recently_surfaced` ([[plans-ambient-recall-refinement]] Stage 1 follow-up) と同じ rotation list で reuse 防止

**Stage 2 D1-D3**:
- D1. 配置: `ambient_recall()` の return shape に `dormant_slot: list[Snippet]` を追加 (既存 `direct` / `lensing` と並列)
- D2. Gate: BM25 score ≥ `ambient_dormant_relevance_floor` (= 0.5) の dormant 候補のみ、無ければ空配列
- D3. Rotation: `recently_surfaced` に dormant 採用 ID を含めて連続 turn の重複を抑制 (既存 mechanism 流用、新規 state 不要)

### Stage 3 — `compare-retrieval` script

**目的**: 同じ query を `recall` / `explore(diversity=0.9)` / `explore(mode="dormant")` / `ambient_recall` に流して横並びに見る dogfooding と regression diagnosis 用ツール。

**実装箇所**: `scripts/compare_retrieval.py` (新規)。`scripts/diag_recall.py` の構造を参考にした read-only script。

**出力フォーマット**:

```text
$ .venv/bin/python scripts/compare_retrieval.py "固定観念を崩す 柔軟性"

=== recall (top 5) ===
1. [agent  m=4.21 c=0.62] 連想より引力井戸の傾き — reason: high mass persona proximity ...
2. ...

=== explore diversity=0.9 (top 5) ===
1. [agent  m=1.10 c=0.71] FAISS atomic save 失敗 — reason: bm25 strong lexical match ...
2. ...

=== explore mode=dormant (top 5) ===
1. [tweet  m=0.43 c=0.55] 帰宅の現象学 — reason: dormant surface (percentile=4) ...
2. ...

=== ambient_recall ===
direct: 2 件、lensing: 1 件、dormant_whisper: 1 件
[breakdown 省略、--verbose で表示]

=== overlap / dominance warning ===
- recall ∩ explore overlap: 3/5 (60%、高い: explore が effective に拡張していない可能性)
- recall top1 mass: 4.21 (>2.0、Heavy Persona Dominance 候補)
- source distribution: agent 4 / file 0 / tweet 1 (file 不在、本クエリは agent 知識領域)
```

**Stage 3 D1-D3**:
- D1. Read-only: `passive=True` で recall を呼ぶ、explore は ephemeral session で displacement を残さない
- D2. JSON 出力 mode (`--json`): diff 駆動 regression 検出に使えるよう machine-readable format
- D3. Tier 4 perf テストに `tests/perf/test_tier4_compare_retrieval.py` を追加 (script 自体が exit 0 で完走することの smoke)

### Stage 4 — Source-aware display in `reflect(aspect="connections")`

**目的**: `reflect(aspect="connections")` の top 共起 edge を source category 別にグルーピングして表示。force computation / mass update には一切影響しない **表示層のみ** の変更。

**実装箇所**: `gaottt/services/reflection.py::reflect_connections()` の結果整形部 + `gaottt/services/formatters.py::format_connections()`。

**ロジック**: 共起 edge を 3 つの bucket に分けて表示:

```text
=== top connections ===

▼ agent / user 由来 (対話での同時参照)
  1. (沈黙する優しさ) ↔ (安全フォールバック) — 4 回
  2. (Articulation as Carrier) ↔ (重力で記憶を組織) — 3 回
  ...

▼ value / intention / commitment 間 (宣言された関係)
  1. (治療的価値が機能価値に優先) ↔ (harakiriworks intention) — 5 回
  ...

▼ file / tweet ingest 同時存在由来 (★ ingest artifact、参考)
  1. (Freeman 脳理論 chunk 42) ↔ (Freeman 脳理論 chunk 43) — 8 回
  2. ...
```

**重要**: 各 bucket 内の集計は **既存の co-occurrence count をそのまま使う**。重みを変えない、edge を削除しない。**閲覧時の lens を変えるだけ**。これが [[feedback_no_source_branching]] と整合する境界線。

**default**: `connections_grouped_by_source: bool = True` (デフォルト分割表示)。`connections_grouped_by_source=False` で legacy 平坦表示に戻せる。

**Stage 4 D1-D3**:
- D1. Bucket 定義: `agent_user` / `persona` / `ingest` の 3 分割 (source class が `agent` または `user` → agent_user、`value` / `intention` / `commitment` → persona、それ以外 → ingest)
- D2. Display 順: persona → agent_user → ingest (重要度順、観測者の関心順)
- D3. 力学不変 assertion: `tests/integration/test_reflection_grouped_connections.py` で edge weight / co-occurrence count が grouping の前後で **bit-exact 一致** することを assert

## 5. 副次予測 — 検証可能な仮説

| 仮説 | 観測方法 | 期待値 |
|---|---|---|
| reason line で Heavy Persona Dominance を caller が早期検出できる | dogfooding 1 週、caller が `recall` 結果を読んで「dominance artifact」suffix が出た回数を記録 | 出る件数の 80% 以上で実際に高 mass persona の混入が確認できる |
| ambient dormant slot で 「〇〇といえば〜」感覚が向上 | [Lateral Association acceptance](Plans-Ambient-Recall-Lateral-Association.md) の golden corpus で再測定 | dormant slot 採用クエリの 30% 以上で caller が「面白い surface」と subjective に判定 |
| compare-retrieval で regression を早期検出 | Phase P Stage 1.5 (Langevin opt-in) 前後で compare-retrieval JSON diff を取る | diff size が「pressure 効果」と一致する分布変化 |
| source-aware connections で「見たい関係」が見えるようになる | 2 dogfooding observer に「以前見えなかった関係が見えたか」アンケート | 2/2 が「persona / agent_user bucket は新しく価値ある」と回答 |

## 6. テスト計画

### 6.1 Unit tests
- `tests/unit/test_explain_score.py` — Stage 1: 各 dominant パターンの reason string 生成
- `tests/unit/test_dormant_relevance_gate.py` — Stage 2: BM25 floor 以下は slot を空にする
- `tests/unit/test_grouped_connections_invariant.py` — Stage 4: bucket 化が co-occurrence count を変えない

### 6.2 Integration tests
- `tests/integration/test_ambient_recall_dormant_slot.py` — Stage 2: 既存 `direct` / `lensing` が縮退しない、rotation が効く
- `tests/integration/test_mcp_reason_line_substring.py` — Stage 1: MCP formatter 出力に `reason:` 行が含まれる、既存 substring assertion を壊さない

### 6.3 Tier 3 quality tests
- `tests/perf/test_tier3_reason_line_signal.py` — Heavy Persona Dominance golden corpus (Stage 7 acceptance 流用) で「dominance artifact」suffix が出る回数を測定
- `tests/perf/test_tier3_ambient_dormant_quality.py` — [Lateral Association Stage 6](Plans-Ambient-Recall-Lateral-Association.md) の golden corpus 12 seed × 6 query で dormant slot 採用率と novelty を測定

### 6.4 Track B playthrough
secondopinion-MCP 経由 GLM-5.1 で「3 dogfooding query」を流して Stage 1-4 すべて enabled / disabled 4 cell の subjective 評価。Phase N β / Phase P と同じ 2 観測者形式で independent observer。

## 7. ハイパーパラメータと config 追加

```python
# gaottt/config.py に追加 (Observation Apparatus Refinement)

# --- Stage 1: Reason line ----------------------------------------------------
expose_reason: bool = True   # ScoreBreakdown.reason を生成
reason_dominance_mass_threshold: float = 2.0    # mass >= 2.0 で "high mass persona proximity"
reason_bm25_strong_threshold: float = 0.5       # bm25 >= 0.5 で "strong lexical match"

# --- Stage 2: Ambient dormant slot ------------------------------------------
ambient_dormant_slot_enabled: bool = True
ambient_dormant_slot_count: int = 1
ambient_dormant_relevance_floor: float = 0.5    # BM25 一致がこれ以下なら slot 空

# --- Stage 4: Source-aware connections display -------------------------------
connections_grouped_by_source: bool = True       # reflect(aspect="connections") の表示分割
```

env opt-out (legacy 互換が必要な場合):
- `GAOTTT_EXPOSE_REASON=false`
- `GAOTTT_AMBIENT_DORMANT_SLOT_ENABLED=false`
- `GAOTTT_CONNECTIONS_GROUPED_BY_SOURCE=false`

## 8. Stage plan

### Stage 1 — Reason line (本計画着手の入口、想定 0.5-1 day)
- `gaottt/core/types.py::ScoreBreakdown` に `reason: str | None` 追加
- `gaottt/services/formatters.py::explain_score()` 純粋関数
- `gaottt/services/memory.py::recall` / `ambient_recall` で生成
- Unit + integration テスト
- default **ON** (力学不変、opt-out で legacy)

### Stage 2 — Ambient dormant slot (想定 0.5-1 day)
- `gaottt/services/memory.py::ambient_recall()` に `dormant_slot` 追加
- 既存 `_dormant_surface()` を再利用、BM25 floor で gate
- Unit + integration テスト
- default **ON** (1 slot まで、ガード強め)

### Stage 3 — compare-retrieval script (想定 0.5 day)
- `scripts/compare_retrieval.py` 新規 (read-only)
- Tier 4 smoke テスト
- ドキュメント [Operations — Performance Testing](Operations-Performance-Testing.md) に使い方追加

### Stage 4 — Source-aware connections display (想定 0.5 day)
- `gaottt/services/reflection.py::reflect_connections()` の整形拡張
- `gaottt/services/formatters.py::format_connections()` で bucket 表示
- 力学不変 assertion
- default **ON** (opt-out で legacy 平坦表示)

### Stage 5 (任意) — caller-side ガイド更新
- [Guides — Ambient Recall](Guides-Ambient-Recall.md) / [SKILL.md](https://github.com/May-Kirihara/GaOTTT/blob/main/SKILL.md) に「思考をずらしたい時は `mode="dormant"`」「`reason:` 行で dominance artifact を見分ける」等の使い分けセクションを追加
- 両者の dogfooding 報告で挙がった「使い分けが UI/docs から伝わりにくい」への直接の答え

## 9. Phase P / Phase O / Phase N β との関係

| 計画 | 介入軸 | mass / acceleration を触るか |
|---|---|---|
| Phase O (TTT Observability) | 観測層、score breakdown / training delta / dormant surface 公開 | × (観測のみ) |
| **本計画** | **観測層、4 stage の道具立て磨き** | × (観測のみ) |
| Phase N β (Mass Evaporation) | mass update (減衰) | ○ (mass のみ、acceleration は不変) |
| Phase P-α (Λ) | acceleration | ○ (acceleration に項追加) |
| Phase P-β (Langevin) | displacement | ○ (position に noise) |

本計画は Phase O の **後続観測層** であり、Phase N β / Phase P と **並行に進められる**。Phase P が物理側で Heavy Persona Dominance を解く一方、本計画は **その同じ dominance を caller が体感として読み取れる道具** を整える。物理側で dominance が解けたあとに reason line / compare-retrieval を見れば、「dominance artifact」suffix の出現率が下がるはず — つまり本計画は Phase P の効果測定にも使える。

## 10. 関連

- [Plans — Phase O (TTT Observability)](Plans-Phase-O-TTT-Observability.md) — 観測層の前段
- [Plans — Phase P (Pressure Terms)](Plans-Phase-P-Pressure-Terms.md) — physics 側の並行作業
- [Plans — Phase N (Mass Evaporation)](Plans-Phase-N-Mass-Evaporation.md) — mass update 側の並行作業
- [Plans — Ambient Recall Refinement](Plans-Ambient-Recall-Refinement.md) — ambient slot 設計の前提
- [Plans — Ambient Recall Lateral Association](Plans-Ambient-Recall-Lateral-Association.md) — dormant 体感の golden corpus 流用元
- [handover-2026-05-26-dogfooding-usage-feel.md](../maintainers/handover-2026-05-26-dogfooding-usage-feel.md) — 観測者 GLM/Codex 視点
- [handover-2026-05-26-dogfooding-external-perspective.md](../maintainers/handover-2026-05-26-dogfooding-external-perspective.md) — 観測者 新規 Claude 視点
