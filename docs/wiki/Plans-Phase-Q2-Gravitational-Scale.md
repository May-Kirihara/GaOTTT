# Plans — Phase Q2: Gravitational Scale Matching（密度適応の重力 + velocity cooldown）

> **Status (2026-05-30)**: **起草**。[Phase Q](Plans-Phase-Q-Orbital-Mechanics.md) の本番実測（§8 rollout findings）を承けた follow-on。すべて**隔離コピーで measurement-first**、本番未投入。Phase Q が「合わないスケールの項（tick 近傍重力）をとりあえず外す」保守的な床を入れたのに対し、本 plan は **「重力の重みを宇宙のスケールに合わせて項を生かす」** 原理的な天井 — 密度適応の有効重力結合と、過去に焼き付いた degenerate な velocity 場の一度きり cooldown。ユーザー（めいさん）の診断「重力の重みが宇宙のスケールに合っていないのかな」を literal に実装する Phase。

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

## 4. 設計候補（pass-5 が係数を確定）

### 4.1 密度適応 `G_eff`

- **(a) 平均場 1/N**: `a_neighbor = (G₀ / N_reached) · Σ_j …`。reach 数（or lively set サイズ）で割り、`net ∝ N` を相殺。pass-5 で `net∝N` が確認できれば構造的に正しい。
- **(b) anchor 基準オートゲイン** ←本命候補: `G_eff = α · ⟨anchor⟩ / ⟨net @ unit G⟩`（α≈0.2）。「近傍重力を常に anchor の一定割合に保つ」ので**密度に自動追従**（密でも疎でも摂動として振る舞う）。1/N × anchor 基準定数、と等価。
- **(c) 粗い大域定数** `G≈1e-6`: 最も単純。だが疎領域／小コーパスで重力が消える。fallback のみ。

評価軸: ① `net/anchor` を ~0.1–0.3 に乗せる ② 疎領域でも摂動が消えない ③ source 非依存 ④ 計算コスト中立。

### 4.2 適用範囲

- **tick だけ**（保守、再飽和は定期 cool で対処）/ **recall path 含む全 gravity**（本命 = (ii)、再飽和を根絶）。
- tick と recall で**別係数**も可（tick は弱め、recall はさらに弱め等）。pass-5 + 段階4 で決定。

---

## 5. velocity cooldown migration（過去の degenerate 場の掃除）

G を rescale しても**焼き付いた飽和 velocity は変わらない**。かつ cap=256 のもとで一様飽和場は**自然 drain しない**（数週〜）ので、能動的 migration が**前提**。

- **A: `velocity=NULL`（向き捨て、displacement 保持）** ← lean。displacement は学習（query 引力の積分）なので残す。velocity は場の導関数で再生成可能。
- **B': 向き保持・magnitude 縮小**（単位化して小さい固定長）。velocity の向きが意味ある独立情報を持つ場合のみ。
- **A vs B' は pass-6 で決定**（velocity 向きが現在の近傍重力方向の影に過ぎない＝再生成可能なら A、軌跡 momentum として独立なら B'）。
- 実装: `scripts/migrate.py` wizard の **M005「phase-q-velocity-cooldown」**。**backend 停止 → reset → 再起動**（write-behind 逆上書き罠 [Backend kill on code deploy]）。backup + `[y/N]` + ledger、idempotent。engine に velocity-only `reset_velocities()` を新設（既存 `reset_orbital_state` は displacement も消すので別物）。
- **持続性**: (ii) で recall G を下げれば**再飽和しない＝一度きり**。tick だけ直すと recall が再飽和させるので**定期再 cool** が要る（(ii) を選ぶ最大の実利）。

---

## 6. measurement 計画（すべて隔離コピー、本番無傷）

| pass | 内容 | 決めること |
|---|---|---|
| **pass-5** | `G_eff` スケールマッピング（mutual/knn × N、coherence、anchor 基準 `G_eff`） | density-aware G の方式と係数（4.1） |
| **pass-6** | velocity 向き情報（`cos(v_dir, a_grav_dir)` / `cos(v_dir, d_dir)`、baseline `1/√768≈0.036`） | A vs B'（§5） |
| **段階4** | density-aware G で **retrieval before/after** — `scripts/diag_recall.py` snapshot/diff（同一クエリ集合の top-K 変化）+ Tier3 quality + Tier7 golden | **(ii) の go/no-go** |
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
