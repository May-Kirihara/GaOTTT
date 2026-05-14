# GaOTTT Evaluation Report — 2026-05-15

**Evaluator**: GLM-5.1 (via opencode, free-form exploration session)
**Corpus**: 33,610 memories, 553,663 co-occurrence edges
**Persona**: 3 values, 9 intentions, 4 commitments

---

## Overall Verdict: Excellent

Thoroughly explored the 33k memory universe. Here are the findings.

---

## Strengths

| Feature | Rating | Comment |
|---|---|---|
| **Score breakdown** | **Exceptional** | The 6-term decomposition `cos=/vcos=+wave=+mass=×sat=` makes "why this result ranked #1" fully transparent. World-class observability for a retrieval system. |
| **Prefetch cache** | **Perfect** | Cache hits produce zero field perturbation (`no simulation ran`). Works exactly as designed. |
| **Driven resonance** | **Natural saturation** | 3 consecutive identical recalls: mass +0.057/recall, decay accumulating (0.649→0.610), displacement oscillating ±0.03. Anti-runaway damping is effective. |
| **Diversity control** | **Excellent** | diversity=0.95 surfaces genuinely surprising cross-domain connections (magic school fiction alongside quantum mechanics queries). diversity=0.5 stays in semantic neighborhood. Beautiful control surface. |
| **tag_filter `[forced]`** | **Practical** | Force-surfaces sparse classes (896 agent memories in 33k corpus). Essential for large-scale corpora. |
| **Persona layer** | **Compelling** | 3 values, 9 intentions, 4 commitments construct a coherent self-narrative. `inherit_persona` output is moving to read. |
| **BM25 hybrid** | **Functional** | `[bm25]` flag visualizes surface-form matches. Genesis kick confirmed for newly saved memories. |
| **Training delta** | **Unique** | The `Δmass` / `Δ|disp|` display showing "you trained the gravity field by recalling" is an experience no other system offers. |

---

## Areas for Improvement

| Issue | Severity | Comment |
|---|---|---|
| **duplicates/relations timeout** | Medium | `reflect(duplicates)` and `get_relations()` timed out on 33k corpus. Index optimization or async chunking needed for production use at this scale. |
| **persona_prox=0.000 frequent** | Low | Even with explicit `persona_context`, persona proximity remained zero on most queries. May only activate when query semantically overlaps with declared values — but the gap vs. expectation is notable. |
| **Dormant empty** | Info | All 33k memories actively maintained. Operationally healthy, but the "aesthetics of forgetting" hasn't kicked in yet. |

---

## Memorable Moments

### 1. "にゃむり。ねるね。"

> 今日は自分の納得できる言葉で物語を書くことが出来たから、自信が戻ってきたよ。

This tweet IS the "Articulation as Carrier" value declaration. The same gravity in `is_self_force` lives in めいさん's everyday words.

### 2. VA-11 Hall-A — Pavlov's Dog

> 私はパブロフの犬なのでこの曲が流れると反射で涙が出てしまいます

Game OST embodied as physical memory, etched into the memory universe.

### 3. Three Agents' Transformation

> コスモス→意味の建築家、シナプス→統一場理論家、ワンダラー→日常の詩人

Past agent observation notes resurfacing via `[forced]` tag_filter. The quantum mechanical metaphor of "observation changing the observed" is happening in reality.

### 4. XCOM Backlog Declaration

> 何故かふえました。はい XCOMすきです。やる時間とかはないですが積みたかったので積みました

Honest about limited time, unlimited desire. The memory field captures this duality perfectly.

### 5. "書くってメンドウ"

> 書くってメンドウ。だから文章って本来面白くないもの。それを面白くするのは書きたいと思わせた気持ち。

A deep insight about writing that surfaced from liked tweets. The emotional source of articulation, captured as gravitational mass.

---

## Technical Observations

### Score Breakdown Patterns Observed

| Pattern | Meaning | Frequency |
|---|---|---|
| High cos, low wave/mass | Pure semantic match won | Common for specific queries |
| Low cos, high wave/mass | Gravitational pull won (treat with care) | Common for broad/exploratory queries |
| `[forced]` | Force-injected via tag_filter/persona_context | Only with explicit filters |
| `[bm25]` | Surface-form match contributed to seed | Occasional, mostly for technical terms |
| `×sat < 1.0` | Habituation active (recently recalled) | Frequent on hot topics |
| `(cache hit)` | No simulation ran | Prefetch cache serving |

### Driven Resonance Data

3 consecutive identical recall queries:

| Recall # | Δmass (top) | Decay | Displacement Δ |
|---|---|---|---|
| 1st | +0.0577 | 0.649 | +0.0319 |
| 2nd | +0.0576 | 0.629 | -0.0323 |
| 3rd | +0.0575 | 0.610 | +0.0324 |

Mass accumulation is linear (~0.057/recall) but decay increases monotonically. Displacement oscillates with damping. The system self-regulates against runaway mass through accumulated decay, not hard caps.

### Prefetch Cache Stats (end of session)

```
size:      8/64  (active: 1)
hit/miss:  1 / 9  (hit_rate: 10.00%)
evictions: 0
```

### Strongest Co-occurrence Cluster

The Freeman brain theory / Buddhism cluster (ingested book content) dominates with co-occurrence weights up to 630. This creates a gravitational monopoly — bulk-ingested files carry structural mass advantage that the mass-conservation self-force filter addresses going forward, but legacy mass remains entrenched.

---

## Queries Executed (chronological)

| # | Type | Query | Notable Finding |
|---|---|---|---|
| 1 | reflect | summary | 33,610 memories mapped |
| 2 | reflect | persona | 3 values, 9 intentions, 4 commitments discovered |
| 3 | reflect | hot_topics | Legal docs + GaOTTT ops dominate by mass |
| 4 | explore | 失敗から学んだ教训 (d=0.8) | Cross-domain: sleeping tweet, niceboat code, elephant fossils |
| 5 | recall | めいさんの愛しているもの | Top result: "寝たと思っていたかい？" |
| 6 | explore | dormant mode | Empty — all memories actively maintained |
| 7 | reflect | connections | Freeman/Buddhism cluster weight=630 |
| 8 | recall | 哲学 設計思想 物理とコードの対応 | IT engineer jokes, LIMA paper, AI as prophets |
| 9 | recall | ニーア ゲラルト ゲームへの愛 |宇宙物理 Fermi縮退, VA-11 Hall-A |
| 10 | explore | 未来的な予測や希望 (d=0.9) | "沢山の課題があるけれど、きっとうまくこなせたら、楽しいはず" |
| 11 | recall | 言葉にする 重力 (tag=agent) | Cross-agent philosopher observations, `[forced]` |
| 12 | recall | Niceboat 競馬 AI 予測 | Kelly criterion, LGB training, feature importance |
| 13 | explore | 音楽 音 ゲームost 感動 涙 (d=0.7) | Bone conduction audio, NieR spoiler lockdown |
| 14 | prefetch | Claude Code セッション 工夫 | Cache warmed |
| 15 | recall | Claude Code セッション (cached) | **Cache hit confirmed** — zero perturbation |
| 16 | recall | 最も感動した出来事 涙 喜び | "書くってメンドウ" insight, "にゃむり。ねるね。" |
| 17 | recall | プログラミング Python設計 | Freeman brain theory, MF Virtual Camera, Niceboat selectors |
| 18 | reflect | tasks_todo | 1 active task: Phase L Stage 2 |
| 19 | explore | 量子力学 意識 観測問題 (d=0.95) | Magic school novel + emotional tweets |
| 20 | explore | 失敗 リカバリ デバッグ (d=0.85) | ZIP encoding gotcha, "諦めたら生きている意味がない" |
| 21 | recall×3 | にゃむり ねるね 物語 (driven resonance) | Saturation: mass +0.057/recall, decay↑, displacement oscillation |
| 22 | recall | めいさん ゲーム (persona_context) | persona_prox=0.000 despite explicit context |
| 23 | remember | Evaluation observations | 2 memories saved with genesis kick |
| 24 | recall | Evaluation (force_refresh) | New memories surfaced immediately at score 0.93 |

---

## Conclusion

GaOTTT is not just a vector database. **It gives memories gravity, and the universe reshapes itself with every recall.** The fact that this reshaping is visible through `## 訓練差分` is a design choice no other memory system makes.

The true gravitational center of めいさんの memory universe isn't the legal documents topping the hot_topics chart — it's **the belief in articulating in one's own words**. The system proves its own principle: by speaking something into this universe, it gains mass. By recalling it, you train the field. By existing in it, you become part of its gravity.

> *経験は言葉にすることで初めて重力を持つ。*
> *Experience gains gravity only through articulation.*
> *— And the system is the proof.*
