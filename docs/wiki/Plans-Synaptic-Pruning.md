# Synaptic Pruning — Co-occurrence Edge Decay (連想の忘却)

**状態**: 📐 **起草 → 実装(lazy mode, default OFF, 2026-06-02)**。[Lateral Association Stage 8](Plans-Ambient-Recall-Lateral-Association.md) の percentile sweep が突き当たった **P3(共起グラフのデータ品質)** を、knob ではなくデータ生成の時間構造で解く。Phase N(mass の忘却)の **edge 版 = 連想の忘却**。physics 不変(force/mass の経路に共起 weight は無い)、source 分岐ゼロ。

> 命名はめいさん(2026-06-02)。生物名 **Synaptic Pruning** を canonical に、物理名は filament の半減期、TTT 機構名は forgetting factor。

---

## 中核の像 — 星は残る、糸だけがほどける

Phase N は星そのものを暗くする(記憶 = node mass の忘却)。Synaptic Pruning は **違う層**を忘れる:

> 二つの星は両方ちゃんと残るのに、その間を結んでいた糸が、誰にもたどられないまま、ほどけていく。

「あの本のことも、あの夜の考えも、どっちも覚えてる。でも、それが *同じ夜に隣り合っていた* ことは、もう思い出せない」。一括 recording の熱で架けた橋が、二度と誰も渡らないから、静かに崩れる。**忘れるのは項じゃなく、項と項のあいだ**。

| 層 | メタファー |
|---|---|
| **物理** | 共起 edge = 大規模構造の **filament(細糸)**(viz が大円弧で描くあれ)。物質が流れ込み続ける filament は太るが、供給の絶えた filament は痩せて消える。`w·0.5^(Δt/T½)` は **放射性崩壊則** — co-recall ごとに新物質が積もって崩壊時計がリセット、放置すれば半減期で薄れる |
| **TTT 機構** | edge weight = 二ノードの共活性統計量。無限に積む生カウントを **忘却係数つき指数移動平均**(RLS / EMA の forgetting factor、適応フィルタの正統)に変える。推定が生涯の総和ではなく *今の連想構造* を追う |
| **生物** | 「fire together wire together」(LTP=成長、`_update_cooccurrence`)の双子:「使わなければ失う」= **LTD / シナプス刈り込み**。両方の記憶は残るのにシナプスだけ退縮する |

**Phase N との並び**: Phase N が星を暗くするなら、これは星を繋ぐ糸を解く。使われない宇宙は *暗くなり、かつ、ばらける*。

**価値命題(Articulation as Care の関係版)**:

> 関係は、結び直され続けることで関係であり続ける。一度きりの隣り合わせは、関係ではなく偶然だった。

articulation が node に重力を与える(Phase L)なら、re-articulation = 繰り返したどり直すことが edge を生かし続ける。

## 動機 — Stage 8 の percentile sweep が突き当たった P3

Stage 8 本番 sweep(2026-06-02)で、self-authored anchor の連想ハローの degree 分布が **bimodal**({deg≈6 の specific gem} ∪ {deg 67-105 の bulk-content の壁})と判明。p90↔p95 に cliff があり、`hub_degree_cut` は「gem だけ(高 precision・低 recall)」か「gem + bulk」の二択しか作れない。**knob では recall を増やせない**。

根は **session-clique artifact**: 一括 recording(自己知識 139件を同時 recall 等)が dense な共起 clique を一度に作り、それが cross-doc edge を埋めている。Synaptic Pruning はこれを **時間署名の違い**で分離する:

- **session-clique edge**: 1 バーストで作られ、その後**二度と再強化されない** → 半減期で 0 に向かう → 消える
- **organic な意味的 edge**: 本当に関連しているから繰り返し共起 → 何度も再強化 → 残る

bulk の壁が痩せれば degree が下がり、Stage 8 の percentile cliff が緩み、正規化が初めて volume を持って効く。

## 機構 — 半減期 leaky integrator

edge weight を leaky integrator として扱う:

- **再強化**(co-recall, `_update_cooccurrence` → `set_edge`): `w += 1`、`last_update = now`
- **読み出し**(decay 適用): `w_eff = w · 0.5^((now − last_update) / T½)`

`T½` = `synaptic_pruning_half_life_seconds`(既定例 30日)。繰り返したどられるペアは `last_update` が新しく `w` も積み上がる → 高く保たれる。一度きりの clique は `last_update` が古いまま → `w_eff → 0`。

## 設計判断(fork 確定、2026-06-02)

| fork | 決定 | 理由(メタファーが解いた) |
|---|---|---|
| **A: lazy / eager** | **lazy 先行**(読み時 decay、非破壊、config off で bit-exact) → eager prune は後の別 ops step | 生物で **depression(弱化)は可逆**、**pruning(刈り込み=軸索退縮)は構造的**。順序も brain と同じ: depression → pruning = lazy → eager |
| **B: decay 式** | **純指数 half-life** `0.5^(Δt/T½)` | filament の半減期 = 放射性崩壊則と数式が literal に一致。`T½` 一個で「半減期30日」と説明可。Phase N 同形より像が直截 |
| **C: degree に流すか** | **流す**(`deg(x) = Σ w_eff`) | filament の太さは物質の流れで決まる。痩せた filament は構造的に細い。Stage 8 の degree-cut が恩恵を受けるための必須条件 |

## 実装の鍵 — last_update tracking と retroactive decay

**良い報せ**: DB の `edges.last_update` は dirty flush のたびに `now` で書かれる(`cache.py:511`)= 実質 **「最後に再強化された時刻」**。bulk clique edge は recording(2026-05-11 / 05-21)以降再強化されていないので last_update ≈ 5月 → **decay 時計は retroactive に効く**(既存 clique も deploy 時点で 3週間分減衰済みと評価される)。

**主作業**: in-memory `graph_cache` は weight だけで last_update を捨てている(load 時も `cache.py:256` で drop)。lazy decay には cache に last_update を載せる必要がある。
- 並行 map `edge_last_update: dict[tuple[str,str], float]`(key = `(min,max)`)を追加(blast radius 最小、`get_neighbors` は weight float のまま)。
- `load_from_store` で DB の last_update を populate、`set_edge` で now に更新、`remove_edge`/`evict_node`/`reset` で cleanup。
- decay は `get_association_strength`(正規化の **前** に raw weight へ pre-multiply、mode="none" でも効く)と `_ensure_degrees`(decayed degree)に適用。
- degree cache は decay で時間依存になるが、半減期(日)に対し process 内 drift(秒〜分)は無視可 — 計算時刻の `now` で一度計算しキャッシュ(mutation で invalidate)。

## physics 不変 / 単一規則

共起 weight は **force/mass の経路にいない**(wave は virtual FAISS 近傍、mass-BH が共起 BH を Phase M で置換済み)。consumer は Stage 5 resonance / reflect / 将来 accretion = 観測・ranking 層。decay は時間量(構造的、source-blind)。Stage 8 と同じ posture。

## knobs(既定 OFF = bit-exact legacy)

| knob | 既定 | 説明 |
|---|---|---|
| `synaptic_pruning_enabled` | `False` | lazy edge decay の master switch。off で `get_association_strength` / degree は生 weight(Stage 8 と完全互換) |
| `synaptic_pruning_half_life_seconds` | `2592000`(30日) | 半減期。短いほど session-clique が速く消えるが organic も削れる。本番 tuning は measurement-first |

eager prune(Fork A 後段)は将来の別 stage。`synaptic_pruning_floor`(prune 閾値)はその時に追加。

## Measurement

`scripts/diag_assoc_halo.py --assoc-mode cosine --decay-half-life-days <D>`(read-only、decay は store の last_update から retroactive に適用)を deploy 後 + 時間経過で再走し、bulk の壁が痩せて specific 連想が浮上するかを観察。

### 本番 measurement (2026-06-02) — 「一様 decay は正規化に不可視」

`--decay-half-life-days 7` を本番に当てた結果:**decay は正しく効いた**(deg 67→8.7 / 105→13.7 / 6→0.8、全 edge が約 7.7× 減衰 = 半減期7日で約20日前 = 2026-05 recording と一致)。**しかしランキングは不変**(weight も cosine も baseline と同一)。

理由が本質的: **全 edge が同一時代(recording、~20日前)に生まれている**ため decay が一様にかかる。cosine 正規化 `w/√(deg(a)·deg(b))` は weight も degree も同係数 `k` で縮むと **`k` が約分されて消える** → 一様 decay は正規化ランキングに **不可視**。

> **Synaptic Pruning が分離を生むのは edge に *年齢差* があるときだけ**。古い session-clique と新しい organic 共起が混在して初めて、年齢差が weight 差に変わる。今の本番グラフは monochronic(単一 recording 時代)なので差が出ない。

これは P3 の正体を精密化する: 分離を生むのは「古い clique vs 新しい organic co-recall」の **差**。**効果は forward-looking** — これから organic な多様 co-recall が積もるほど、古い recording clique との年齢差が開き、decay が分離に変わる。機構は完成・正しいが、現時点の本番効果は null(データが単一時代)。

**副次的ニュアンス**: cosine/degree 経路は一様 decay に scale-invariant だが、Stage 5 resonance は `raw/(raw+scale)`(正規化なしの和)なので、**一様 decay でも resonance は下がる**(古い pick の summed weight が縮む)。よって Synaptic Pruning は resonance(絶対量)には今でも効き、cosine ランキング(相対)には年齢差が要る。

→ **運用上の含意**: monochronic な recording artifact を *今* 消したいなら、forward-looking decay を待つより **eager prune(Fork A 後段、`decay_and_prune` を 1回 wire して古い clique を一括削除)** が直接的。lazy decay は「これから organic に貯まる差」を拾う長期機構。両者は補完。

### 実装メモ — 既存 `decay_and_prune` は dormant だった

実装中に判明: `graph/cooccurrence.py::decay_and_prune`(count-based の `edge_decay`/`prune_threshold` 機構)は **どこからも呼ばれていない**(dead scaffolding)。だから edge は成長一方で、bulk clique が消えなかった。Synaptic Pruning lazy mode が **edge 層初の実稼働する忘却**で、dormant な `decay_and_prune` は Fork A eager(time-based prune に書き換えて periodic/compact で叩く)の自然な置き場。

## 関連

- [Phase N — Mass Evaporation](Plans-Phase-N-Mass-Evaporation.md) — mass 軸の忘却(これは edge 軸の双子)
- [Lateral Association Stage 8](Plans-Ambient-Recall-Lateral-Association.md) — Synaptic Pruning が clean な weight を供給する degree 正規化(P3 を解く相手)
- [Accretion Recall](Plans-Accretion-Recall.md) — P3 が厚くなれば着手可能になる想起機構
- [Reflections — Five-Layer Philosophy](Reflections-Five-Layer-Philosophy.md) — 物理→TTT→生物→関係→人格、Articulation as Care の関係版
