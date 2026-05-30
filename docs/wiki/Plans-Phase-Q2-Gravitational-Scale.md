# Plans — Phase Q2: Gravitational Scale Matching（密度適応の重力 + velocity cooldown）

> **Status (2026-05-31)**: **本番 LIVE。** 段階1-4 完了 + M006 velocity cooldown 適用 + governor 有効化（`feat/phase-q-orbital-mechanics`）。**2026-05-31 に governor を code default ON へ昇格**（段階4 acceptance + 本番 live healthy を承けた owner 判断、規約「新 field は default OFF」からの意図的 promotion。`gravity_neighbor_governor_enabled=False` で bit-exact pre-Q2 legacy に戻せる）。残り = **1-2 週観測 + α チューニング** + PR。[Phase Q](Plans-Phase-Q-Orbital-Mechanics.md) の本番実測（§8 rollout findings）を承けた follow-on。設計は**隔離コピーで measurement-first** に確定し、本番投入は M006 + env opt-in → default ON の順で実施（rollout 手順は [Operations — Migration](Operations-Migration.md) §Phase Q2）。Phase Q が「合わないスケールの項（tick 近傍重力）をとりあえず外す」保守的な床を入れたのに対し、本 plan は **「重力の重みを宇宙のスケールに合わせて項を生かす」** 原理的な天井 — 密度適応の有効重力結合（anchor 基準 governor、§4.1）と、過去に焼き付いた degenerate な velocity 場の一度きり cooldown（A、§5）。ユーザー（めいさん）の診断「重力の重みが宇宙のスケールに合っていないのかな」を literal に実装する Phase。
>
> **★ 段階4 の核心発見（§4.3）**: governor は単一クエリの ranking を変えない（中立）が、**過大な近傍重力に踏み潰されていた query 引力（Phase I Stage 2 の literal な TTT 勾配項）を un-mask する**（drift OFF 0.018 → ON 0.832、top-5 安定）。劣化ではなく**意図された学習機構の回復**。GaOTTT thesis（Gravity as Optimizer, TTT）に literal に噛み合う。

---

## 0. 一行

Phase Q 実測で判明した **「`gravity_G` がこの密な RURI 宇宙に対して ~10⁴ 倍 過大」** を、**密度適応の有効重力結合 `G_eff`** で正し、過去の**飽和 velocity 場**を一度きり cooldown する。狙い: (a) tick でロゼット歳差を**安全に**出す、(b) recall path の velocity **再飽和を止める**、(c) momentum 場の**意味（heavy-ball の EMA 性）を回復**する。

---

## 1. 動機 — Phase Q §8 の実測が突きつけたもの

本番 41K 隔離コピーの実測（[Phase Q §8](Plans-Phase-Q-Orbital-Mechanics.md#8-rollout-findings-2026-05-30-本番隔離コピー実測)）:

- **net 近傍重力 p50≈10 / max≈640 vs anchor 復元力 ~0.005** → 約 **10³ 倍**。20% 摂動に乗せるには `G_eff ≈ 7×10⁻⁷` = 現 `G=0.01` の **~10⁴ 分の 1**。
- **coherence ≈ 0.3–0.7**（RURI の狭 cosine 帯で近傍重力の方向が揃う、ランダムなら 1/√N≈0.08）→ **net ∝ N**（近傍数に線形）。
- **velocity 場が飽和**（median `|v|=0.05`=clamp、98.8% lively）= recall path の過大 G が、recall のたびに reach ノードの速度を clamp へ押し上げた **degenerate な副産物**（momentum の EMA 性が clamp で破壊された）。

→ Phase Q が入れた保守 fix（tick 近傍重力 OFF = 純 self-anchor）は**床**。本 plan はその上に「**スケールを合わせて近傍重力を本物の摂動として生かす**」=ロゼットの正体、を据える。

---

## 2. 哲学的核心 — なぜ定数 G が誤りなのか

- 現実の Newton's G は定数でも発散しない。理由は**現実空間が疎かつ等方**（質量は希薄に散り、近傍方向はバラバラで打ち消し合う）。
- GaOTTT の「空間」は 768 次元単位超球面に RURI が全部を**狭い cone**に詰め込む = **密・異方（実効低次元）**。ここに「現実宇宙向けの定数 G」を置いたのがミスマッチの根。coherent sum がキャンセルせず積み上がる。
- **「重力の重みを宇宙のスケールに合わせる」= 平均場極限の `1/N` 結合 / anchor 基準の密度適応**。Kuramoto・Vlasov の `1/N` 結合（系を大きくしても 1 体あたりの力を有限に保つ）の literal な構造的対応。三層語彙: 物理（平均場重力）↔ TTT 機構（勾配ステップの密度正規化）↔ 生物（シナプス密度に応じた可塑性スケーリング）。
- **source 分岐ゼロを維持**（密度・幾何・構造的識別子のみで、source class を gate にしない）→ [No source branching] 原則と整合。**anchor migration ゼロも不変**（密度適応は force *scale* だけを触り、公転中心は自分の anchor のまま）。

---

## 3. 影響範囲 — `gravity_G` は何に効くか（だから measurement-first）

`gravity_G` は局所ではない。以下すべてに効くので、変更は retrieval と mass 進化の両方に波及する:

| 経路 | 関数 | 効果 |
|---|---|---|
| recall wave 近傍重力 | `update_orbital_state` / `propagate_gravity_wave` | displacement → virtual_score（ranking） |
| mass 進化 | wave force の per-parent attribution | mass の増減（[Phase M](Plans-Phase-M-Mass-Conservation.md)） |
| genesis kick | `compute_gravity_kick` | 新規ノードの初期 displacement/velocity |
| supernova | `compute_supernova_velocities` | cohort の outward velocity |
| mass-BH | `compute_mass_bh_acceleration`（G-scaled） | 重い attractor の引力 |
| Phase Q tick | `engine._orbital_tick` | 連続公転 |

→ **段階4 の retrieval before/after が go/no-go の肝**。

---

## 4. 設計（pass-5 実測で確定）

### 4.0 pass-5 実測結果（2026-05-30、fresh 隔離コピー、gravity_G=0.01、β=1.0、anchor 力 p50=0.0036）

| scheme | N/k | net_p50 | coherence | ratio_p50 | **ratio_p90** | G_eff@20% |
|---|---|---|---|---|---|---|
| mutual | 32 | 1.23 | 0.81 | 537 | 29,504 | 3.7e-6 |
| mutual | 128 | 7.0 | ~1.0 | 3,648 | 165,986 | 5.5e-7 |
| mutual | 199 | 13.5 | ~1.0※ | 6,926 | 313,628 | 2.9e-7 |
| knn | 50 | 4.2 | 0.73 | 4,607 | 62,028 | 4.3e-7 |
| knn | 200 | 13.3 | 0.75 | 16,950 | 283,895 | 1.2e-7 |

（※coherence>1 は summag が mass-BH を除いた計測アーティファクト。実 coherence は ≤1 だが「ほぼ完全に揃う」は不変。random なら 0.088）

実測で確定した事実:
- **coherence ≈ 0.75–1.0**（random 0.088 の 8–12 倍）= 近傍重力ベクトルがほぼ完全に同方向に揃って加算（打ち消しゼロ）。めいさんの「重力の重みが宇宙スケールに合っていない」を裏付け。
- **net ∝ N**（線形）→ 平均場 1/N が構造的に正しい正規化。
- **過大スケール ~10⁴–10⁵×**（G_eff@20% p50 ≈ 5e-7 = 現 0.01 の 2 万分の 1）。
- **重い裾: ratio p90 ≈ 10⁵** → **単一の小さい大域定数 G では全ノードを飼い慣らせない**（密領域ノードは G を下げても支配的）。→ **per-node 密度適応が必須**。
- **knn（plan §3.3）は逃げ道にならない**（coher 0.73–0.75、ratio はむしろ同等以上）→ 問題は近傍集合でなく**スケール**。

### 4.1 確定設計 — anchor 基準の neighbor-gravity governor（per-node、密度適応）

近傍重力（attractive: 近傍 gravity + mass-BH）を **per-node で anchor の一定割合に cap** する:

```
acc_neigh = Σ_j neighbour_gravity_j + mass_bh_j          # term1 + term3（attractive）
ref_i = α · k_eff(m_i) · max(|d_i|, d_floor)             # anchor 力スケール（α≈0.2, d_floor≈0.1）
g_i   = min(1.0, ref_i / (|acc_neigh| + ε))              # 1 で頭打ち（増幅しない）
acc_neigh ← g_i · acc_neigh                              # 向きは保持、magnitude だけ cap
```

- **per-node 密度適応**: 密領域（`|acc_neigh|` 大）ほど `g_i` 小 → 重い裾 p90 も飼い慣らす。疎領域（`|acc_neigh| < ref`）は `g_i=1` で無変更 → 摂動が消えない（評価軸②）。
- **`d_floor`** で `d=0`（anchor 上で静止）の退化（ref→0 で近傍重力が完全抑制され動けない）を回避。`d_floor` は平衡スケール ~0.1。
- **anchor / query (Phase I) / Λ (Phase P) は cap しない** — governor は coherent 暴走する attractive 近傍重力（term1+3）だけを抑える。Λ は別系の斥力 pressure。
- **source 分岐ゼロ**（密度・幾何・mass のみ）、向き保持（direction は不変）。
- **大域定数 (c) は却下**（重い裾）、**平均場 1/N (a)** は net∝N より構造的に正しいが per-node 裾適応では governor が上。governor は実質「per-node の anchor 基準オートゲイン」。

### 4.2 適用範囲

- **`compute_acceleration`（recall wave + tick 共通経路）に governor を入れる** = recall path も含む (ii)。これで velocity 再飽和も根絶（recall 時の近傍重力が cap される）。
- genesis kick (`compute_gravity_kick`) / supernova は別関数（compute_acceleration を通らない）。同じ governor を後段で適用するかは段階4 の後に判断（初期 seed は再飽和の主因ではない）。
- **default ON**（2026-05-31 昇格、Phase Q2 rollout 完了後）。`gravity_neighbor_governor_enabled=False` で bit-exact pre-Q2 legacy に戻せる。

### 4.2 適用範囲

- governor は `compute_acceleration`（recall wave + tick 共通経路）に入る = recall path 含む (ii)。
- genesis / supernova は別関数。段階4 後に判断。
- default ON（2026-05-31 昇格）。`gravity_neighbor_governor_enabled=False` で bit-exact legacy。

### 4.3 段階4 実測 — governor は **query 引力（TTT 勾配）を un-mask する**（2026-05-30、fresh 隔離コピー）

`engine.query` の flow: **ranking は mutation 前**に確定し（score → sort）、governed force を通る `_update_simulation` は**その後**（`if not passive`）。よって:

- **ranking 中立を実証**: recall #1 の top-5 は **5 クエリ全て off/on 完全一致** → governor 有効化は**既存検索結果を即座に変えない**。effect は displacement の evolution のみ。
- **evolution（q0 を 15× active hammer）**: OFF は total `|Δdisp|`=0.018 / max 0.009、ON は **0.832（~45倍）/ max 0.286**。両方とも q0 top-5 安定。
- **逆説の正体**: 予想は「governor=近傍重力 cap → drift 減」だったが**逆に増えた**。理由 = mutation 加速度 = 近傍重力(t1) + anchor(t2) + **query 引力(t4)** + Λ。OFF では過大な t1(~10) が支配し velocity を近傍方向に飽和、**query 引力 t4 を掻き消す**。ON では t1 を anchor の ~20% に cap → **t4 が effective になりノードがクエリ方向へドリフト**（anchor とのバランスで有界、top-5 安定）。
- **GaOTTT thesis と literal に噛み合う**: 「`compute_acceleration` の 4 番目の項が literal な query 勾配ステップ (Phase I Stage 2)」— その **TTT 勾配が過大スケールの近傍重力に踏み潰されていた**。governor はそれを救出する（velocity 飽和も同根）。**劣化ではなく意図された学習機構の回復**。
- **go/no-go = GO（観測ステージへ）**。ただし **no-op ではない**: governor は query 引力の effective 学習率を実質変える。「ドリフト増が relevance を改善するか/しすぎないか」は単一クエリでは判定不能 → **1–2 週の本番観測 + α チューニング**。`α` が query 引力の effective 学習率を決める。anchor + `max_displacement_norm` で有界。

---

## 5. velocity cooldown migration（過去の degenerate 場の掃除）

G を rescale しても**焼き付いた飽和 velocity は変わらない**。かつ cap=256 のもとで一様飽和場は**自然 drain しない**（数週〜）ので、能動的 migration が**前提**。

- **A: `velocity=NULL`（向き捨て、displacement 保持）** ← **pass-6 で確定**。displacement は学習（query 引力の積分）なので残す。velocity は場の導関数で再生成可能。
- ~~B': 向き保持・magnitude 縮小~~ → **不要**（pass-6 で却下）。
- **pass-6 実測（2026-05-30）**: 248/250 が velocity 保持、`|v| p50=p90=0.05`（完全飽和）。`|cos(v, 現在の近傍重力)| p50=0.869 / mean=0.804`、`|cos(v, displacement)| p50=0.807`（baseline 0.036）。→ **velocity の向きは "現在の重力の影" であって独立情報ではない**。重力は保持する位置＋質量から即再生成可能なので、**A でゼロにしても失うものはない**（次に dynamics 参加時に rescale 後の正しい重力が同じ向きを再生成）。
- 実装済み（commit）: `scripts/migrate.py` wizard の **M006「phase-q2-velocity-cooldown」**（M005 は phase-m-warm-displacement で使用済み）。critical=True で `[y/N]` + backup + ledger、idempotent。engine `reset_velocities()`（velocity-only、displacement 保持。既存 `reset_orbital_state` は両方消すので別物）+ `SqliteStore.reset_velocities()`（`UPDATE nodes SET velocity = NULL`）。velocity は ranking/virtual-FAISS に効かないので prefetch invalidate も virtual-FAISS dirty も**しない**。**実行は rollout 時のみ**: backend 停止 → migrate → 再起動（write-behind 逆上書き罠 [Backend kill on code deploy]）。needs_apply は `|v|>0.5·clamp` のノード比が >50% で発火（飽和検出）。
- **持続性**: (ii) で recall G を下げれば**再飽和しない＝一度きり**。tick だけ直すと recall が再飽和させるので**定期再 cool** が要る（(ii) を選ぶ最大の実利）。

---

## 6. measurement 計画（すべて隔離コピー、本番無傷）

| pass | 内容 | 決めること |
|---|---|---|
| **pass-5** ✅完了 | `G_eff` スケールマッピング（mutual/knn × N、coherence、anchor 基準 `G_eff`） | → §4.0: coherence ~0.8-1.0、net∝N、~10⁴-10⁵×、重い裾 p90~10⁵ → **per-node anchor 基準 governor 確定**（§4.1） |
| **pass-6** ✅完了 | velocity 向き情報（`cos(v_dir, a_grav_dir)` / `cos(v_dir, d_dir)`、baseline `1/√768≈0.036`） | → §5: cos(v, 重力)=0.87 → **A（ゼロ）確定**、向きは再生成可能 |
| **段階4** ✅完了 | governor off/on で recall evolution（同一 fresh copy、neutrality + 15× hammer drift） | → §4.3: **ranking 中立実証**（recall#1 top-5 完全一致）、**governor は query 引力 TTT 勾配を un-mask**（drift OFF 0.018 → ON 0.832、top-5 安定）。**go（観測ステージへ）**、α で TTT 学習率調整 |
| **段階4b** | mass 進化への影響（mass update が G 依存） | BH 化・mass 分布の退行有無 |

仮説: 過大 G が velocity を飽和させ momentum を殺していたので、適正化で retrieval の動的シグナルが**復活 or 中立**。要・実測。

---

## 7. rollout 順序（実測 go 後）

```
DB backup
→ 本番 backend 停止（write-behind 罠）
→ config 適用（density-aware G + orbital bundle）+ M005 velocity cooldown
→ backend 再起動（reset 済み velocity を reload）
→ env opt-in
→ 1–2 週観測（Tier4 + diag_recall で displacement 分布・retrieval 品質）
```

---

## 8. リスク / 留意

- **(ii) は retrieval を触る最大リスク** — G を下げて ranking が劣化したら no-go か係数再調整。段階4 が gate。
- **write-behind 逆上書き罠** — 停止 → 書き込み → 再起動 の順序厳守。
- **mass-BH も G-scaled** — BH 化挙動が変わる（[Phase M](Plans-Phase-M-Mass-Conservation.md) との相互作用を観測）。
- **疎領域での重力消失** — 大域定数 (c) の罠。密度適応 (a)/(b) で回避。
- **anchor migration ゼロは不変** — 密度適応は force scale のみ、公転中心は自分の anchor。
- **保守 fix は床として残す** — density-aware G が no-go でも、Phase Q の純 self-anchor tick は安全に有効化できる。

---

## 9. 関連

- [Phase Q — Orbital Mechanics](Plans-Phase-Q-Orbital-Mechanics.md)（親 — §8 rollout findings が本 plan の出発点）
- [Phase I — Free Star Movement](Plans-Phase-I-Free-Star-Movement.md)（`max_displacement_norm=1e6` の出自）
- [Phase M — Mass Conservation](Plans-Phase-M-Mass-Conservation.md)（migration wizard / mass-BH / source 分岐ゼロ）
- [Phase P — Pressure Terms](Plans-Phase-P-Pressure-Terms.md)（Λ も結合定数を持つ対抗項）
- [Operations — Tuning](Operations-Tuning.md) / [Operations — Performance Testing](Operations-Performance-Testing.md)
- [Plans — Roadmap](Plans-Roadmap.md)
