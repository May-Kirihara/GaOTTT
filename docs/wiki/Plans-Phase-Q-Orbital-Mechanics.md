# Plans — Phase Q: Orbital Mechanics (Rosette Orbits Around Own Anchor)

> **Status (2026-05-30)**: **Stage 1–4c 完了・push 済み（ブランチ `feat/phase-q-orbital-mechanics`、HEAD `c3265ab`、全 default OFF）**。残るは本番 rollout（運用）と real-RURI Tier4 perf のみ。Phase I で「星が動く」を、Phase P で「重力に対抗する圧力」を入れた上に、**ノードが自分の anchor を中心に閉軌道（楕円/ロゼット）を描く**保存系レジームを足す。狙いは "宇宙の再現度" — 緩和（relax）して平衡に落ちるだけの場を、**公転し・歳差し・やがて熱力学的に井戸へ螺旋落下する**力学系に拡張する。**anchor migration はゼロ**（自分のホームを回る、他者の衛星にはしない）。引き継ぎ: [handover-2026-05-30](../maintainers/handover-2026-05-30-phase-q-orbital-mechanics.md)。
>
> | Stage | commit | 内容 |
> |---|---|---|
> | 計画 | `dac2686` | 本計画書 |
> | 1 | `ebade88` | 接線速度 seeding (`_perpendicular_unit` + `compute_gravity_kick`/supernova) + velocity-Verlet (`update_orbital_state`) + config `orbital_tangential_alpha`/`orbital_integrator`。unit 9 |
> | 2 | `8aa4150` | `engine._orbital_tick()` を dream loop に（lively set だけ recall なしで積分、age friction を tick で抑制） + config `orbital_tick_enabled`/`orbital_lively_v_min`/`orbital_tick_max_nodes`。integration 4 |
> | 3 | `65c8a1d` | orbit-regime 安定性 unit 2（displacement clamp backstop + energy 散逸） |
> | 4a | `7b50169` | config 安全ガード（`__post_init__`: orbit mode + 大 max_displacement_norm 警告） |
> | 4b | `9a386ce` | docs — Operations-Tuning「公転・閉軌道」節 + Architecture-Overview 設計判断表 |
> | 4c | `28c1414` / `c3265ab` | viz `--orbital-trails`（`orbital_ellipse` + `compute_orbital_trails`）+ Guides-Visualization 節 |
>
> **★ Stage 3 の発見（[§4 Stage 3](#stage-3--stability-test-の再定義) 参照）**: orbit mode では displacement が runaway しうる。純粋な自 anchor 公転（近傍弱）は energy だけで bound されるが、**強い近傍重力の 1/r² 近接特異点は velocity clamp では止まらない正味の外向きドリフトを生む（500 step で |d|≈26）**。→ orbit regime の runaway backstop は **`max_displacement_norm` clamp そのもの**。Phase I が `max_displacement_norm=1e6`（実質∞）にしたのは relax regime 限定の判断で、orbit mode では**有限値（例 2.0）の設定が必須**。`__post_init__` に `orbital_tick_enabled` + 大 `max_displacement_norm` の警告ガードを追加済み。
>
> **残り（運用）**: friction 0.005 / β=1.0 bundle の本番 measurement-first tuning + env opt-in rollout（DB backup + 他プロセス停止、1–2 週観測）、real-RURI Tier 4 perf 版、PR 作成。core / 安全ガード / docs / viz は完了。

---

## 0. このフェーズの哲学的核心 — Hooke アンカーが「太陽」になる

Phase I は「重力でスコアを変える」を「重力で星の位置を変える」にした。Phase Q はその位置変化を **緩和（relaxation）から公転（orbit）へ**変える。

鍵は **Bertrand の定理**：全ての束縛軌道が閉軌道になる中心力は宇宙に 2 つしかない — `F ∝ -1/r²`（Kepler）と `F ∝ -r`（等方調和振動子）。

GaOTTT の anchor 復元力 `acc -= k·d`（`gravity.py:compute_acceleration` 第 2 項）は、ノード自身の原点 `x₀` に向かう `F = -k·d` = **後者そのもの**。つまり **Hooke アンカーは既に閉軌道を生む中心力**であり、軌道化に足りないのは新しい力ではなく **接線速度（角運動量）だけ**。

これが哲学的に literal に閉じる：

- **公転の中心 = 自分の articulated self（原点 `x₀`）**。displacement の基準点を他者へ移さない → **anchor migration ゼロ**。
- 近傍重力は楕円を**歳差**させる摂動 → ロゼット軌道。「自分の出自に縛られたまま、近傍重力で歳差する」が調和振動子の摂動論として literal に成立。
- 「言葉にした自分の周りを回る」= **Articulation as Carrier (id=9a954c62) の力学版**。`is_self_force` の単数性（Phase M）が「誰に引かれて mass を持つか」を決めたのと対称に、軌道は「自分の出自の周りをどう回るか」を決める。

> Hooke を捨てて軌道を出すのではない。**Hooke こそが軌道を作っていた** — 接線速度を与えていなかっただけ。

衛星化（他星を公転）・彗星のスイングバイ脱出は **公転中心 = 他者 = anchor migration** を要求し、これは [Phase M](Plans-Phase-M-Mass-Conservation.md) の単一規則と value=「設計言語と実装の literal 対応」が引いた線を越える。**Phase Q はその線の内側に厳密に留まる。**

---

## 1. レジームの対比 — なぜ既存設定では軌道にならない

公転が要求する 3 要素を、現状の実装は一つずつ意図的に潰している：

| 軌道に必要 | 現状 | 場所 |
|---|---|---|
| エネルギーが（ほぼ）保存 | constant friction 0.05/step で散逸 | `gravity.py:update_velocity` |
| 角運動量（接線速度） | 種速度は全て**動径方向**（genesis kick / supernova outward） | `gravity.py:compute_gravity_kick` |
| 公転中心 = anchor を回る | ✅ 既に anchor は自分の `x₀`（Bertrand 調和） | `gravity.py:compute_acceleration` 第 2 項 |

→ 3 要素目は既にある。**足りないのは「接線速度の seeding」と「摩擦を下げて保存系に寄せる」の 2 つだけ**。あとは "宇宙の再現度" のための fidelity（symplectic 積分・連続時計・質量依存周期）。

---

## 2. 設計判断（確定済み）

ユーザーとの設計対話（2026-05-30）で以下を確定：

### 2.1 時計 = 連続（dream tick 積分） ✅

軌道は recall イベント時だけでなく、**dream loop の tick ごとに自走**する（宇宙が自分の時計で動く）。

- recall 駆動だと滅多に呼ばれないノードが軌道の途中で凍る → "宇宙の再現" に反する。
- **計算量の保証**: 連続積分は「生きてる集合 `M`（`|v| > v_min`）だけ step」する。`M` が 41K 全部に膨れると O(N²) で破綻するが、**§2.2 のわずかな摩擦が `M` を自己制限する**（kick されたノードは ~100 分で `v_min` を割って `M` から脱落）。→ **#2 の摩擦選択が #1 連続の安全弁そのもの**。同じ 1 事実の 2 つの顔。
- 実コスト試算（M ~ 数百〜2000、41K×310 flat IP）: `search_by_id` top-k=10 を M 回 ≈ 0.6s、Verlet で 2× ≈ 1.2s/tick、30s 周期で duty ~4%。idle 時 M≈0 でほぼ無料。

### 2.2 摩擦 = わずかに残す ✅

`orbital_friction: 0.05 → 0.005`（tick は **constant friction のみ**）。e-folding ~200 tick ≈ 100 分 → 数十周回ってからゆっくり井戸へ螺旋落下。「**全ての軌道はいずれ井戸に落ちる**」熱力学的終末を literal に持たせる。

### 2.3 質量依存の公転周期 = β 有効化 ✅

`mass_anchor_extra_strength: 0.0 → ~1.0`（θ=`mass_anchor_threshold`=3.0 据置）。`k_eff(m) = k·(1 + β(1 - tanh(m/θ)))`：

| mass | k_eff (β=1) | ω=√k_eff | 周期 2π/ω |
|---|---|---|---|
| 1（新規・軽） | 0.034 | 0.18 | ~35 |
| 10（重・確立） | ~0.020 | 0.14 | ~44 |

- **方向**: 重い星ほど緩い anchor・長周期・広い軌道 = 「確立した記憶ほど出自から自由に広く周回、新しい記憶は source にきつく束縛」= [Phase I Stage 4](Plans-Phase-I-Free-Star-Movement.md) の新規ノード保護意図と一致。
- **Kepler 第 3 法則ではない**（あちらは中心質量で周期が決まる）。こちらは「周回する star 自身の質量が自分のバネ定数を決める」調和振動子。「質量が軌道に刻まれる」が別法則。spread を派手にするなら β を上げる。

---

## 3. 物理仕様

### 3.1 接線速度の seeding（角運動量注入）

`compute_gravity_kick`（genesis）と supernova の種速度に、動径 `d` に直交する成分を足す：

```
t = normalize(g - (g·d̂)·d̂)            # 近傍重力 g の、動径 d に直交する成分
v_tangential = orbital_tangential_alpha · |v_radial| · t
v_seed = v_radial + v_tangential
```

- 場の非対称性（g の接線成分）が接線キックを生む、という literal な読み。
- `|v_t| = √k·|d|` で円、ズレで楕円。`orbital_tangential_alpha` が eccentricity の knob。`=0` で legacy（純動径 = 直線振動）。
- **退化 `g ∥ d` のフォールバックは決定論的基底**（`np.random` は使わない — tests/perf golden corpus の再現性、value=「test fixture に乱数を使わない」と整合）。

### 3.2 velocity-Verlet（symplectic 積分）

現状の `v+=a; x+=v`（semi-implicit Euler）は既に symplectic で発散はしないが、dt=1 で O(ω·dt) の**人工歳差**が乗る。velocity-Verlet 化で O(dt²)・時間反転対称にし、**数値由来の偽歳差を消して物理的な歳差（近傍摂動由来）だけ残す**：

```
x_{n+1} = x_n + v_n·dt + ½·a_n·dt²
a_{n+1} = a(x_{n+1})
v_{n+1} = v_n + ½(a_n + a_{n+1})·dt
```

- 力計算 2 回/step（2× コスト）。最大 ω~0.25、dt=1 で `ω·dt << 2` → 安定、sub-step 不要。
- `relax` mode は legacy の semi-implicit Euler のまま（`orbital_integrator` で切替）。

### 3.3 連続軌道積分 tick（`_orbital_tick`）

dream loop に**軽量な軌道積分 pass を新設**（既存 synthetic recall とは別物）：

1. 生きてる集合 `M = {nid : |v| > orbital_lively_v_min}` を cache から取る。
2. 各 nid で `neighbor_index.search_by_id(top-k)` → 近傍取得。
3. anchor(β) + 近傍重力 + Λ（Phase P）の力で velocity-Verlet を 1 step。
4. **constant friction のみ**適用（age friction は recall path に残す — §4 注意）。
5. displacement/velocity を cache に書く（virtual FAISS write-behind 経由で他プロセスへ伝播）。
6. **mass / temperature / last_access / co-occurrence / 結果返却は一切触らない。**

→ recall = エネルギー注入、tick = 自由軌道の積分、と役割が綺麗に分離する。

### 3.4 source 分岐ゼロの担保

接線 seeding も tick 積分も **node の幾何位置と構造的識別子だけ**に依存し、source / class を見ない。[Phase M](Plans-Phase-M-Mass-Conservation.md) 単一規則・観測/物理境界（force computation への source-blind な項追加 = 許容側）を維持。

---

## 4. 実装計画（build order）

> 鉄則: 本番 DB を触らない。検証は tmp DB（real RURI or 合成）。MCP/REST parity は内部 dynamics のため対象外（新 tool/endpoint なし）。

### Stage 1 — 楕円 proof（tmp DB、recall 駆動でまず物理確認）

- `gravity.py`: §3.1 接線 seeding + §3.2 velocity-Verlet（`orbital_mode="orbit"` 時）
- `config.py`: §5 の knob 追加（全て default OFF / legacy 値）
- β 有効化を orbit bundle 内に閉じる
- **検証**: `scripts/visualize_3d.py` / `scripts/diag_recall.py` で「井戸への直線振動」が「閉じた楕円」になるのを目視。これで物理を確定。

### Stage 2 — 連続 tick

- `core/engine.py`: `_orbital_tick` を dream loop に追加（§3.3）。recall path（`_update_simulation`）との役割分離。
- バースト時の `M` 上限 `orbital_tick_max_nodes`（超過は高速度順処理 + **log、silent cap 禁止**）
- **検証**: 40K 合成ノードで `M` が bound する事 + duty cycle を tmp で実測（§2.1 の前提検証）。

### Stage 3 — stability test の再定義

- `tests/perf/test_tier4_*.py`: 「displacement 単調有界（緩和）」を **energy + 角運動量保存 bound** に言い直す：`E = ½|v|² + ½k|d|²`、`L = d×v` が friction≥0 で単調減少 → `|d|` は turning point で抑えられる、を assert。

### Stage 4 — config / rollback / docs

- `orbital_mode="relax"` に戻す or `orbital_tangential_alpha=0` で legacy 完全復帰（bit-exact）。
- docs: この Plans / [Operations — Tuning](Operations-Tuning.md)（新 knob）/ [Architecture — Overview](Architecture-Overview.md) 設計判断表 / [Roadmap](Plans-Roadmap.md) / `_Sidebar.md`。

---

## 5. config（orbital bundle、全て default は legacy）

```python
orbital_mode: str = "relax"               # "orbit" で軌道レジーム
orbital_tangential_alpha: float = 0.0     # 接線速度の大きさ（eccentricity）。0=legacy
orbital_integrator: str = "euler"         # "verlet" で symplectic
orbital_friction: float = 0.05            # orbit 時は 0.005 推奨（tick は constant のみ）
orbital_max_velocity: float = 0.05        # orbit 時は ↑（近点速度クリップ回避）
mass_anchor_extra_strength: float = 0.0   # β、質量→周期。orbit bundle で 1.0
orbital_tick_enabled: bool = False        # dream loop の連続積分 pass
orbital_tick_dt: float = 1.0              # ω·dt<<2 で安定
orbital_lively_v_min: float = ...         # M の足切り（cold cosmos 除外）
orbital_tick_max_nodes: int = ...         # バースト時上限、超過は log
```

---

## 6. 留意点

- **β は orbit mode と無関係に `compute_acceleration` 全体に効く** — `relax` 現行 production の平衡 `d_eq=(G·m/k_eff)^⅓` も全ノード動く。β は **orbit bundle 内で有効化**するか、本番では measurement-first で別ロールアウト。
- **age friction を tick から外す** — `last_access` 起点の age friction を毎 tick 適用すると、最近 recall されてない軌道中ノードを激しく damp して楕円が数 tick で死ぬ。tick は constant friction のみ。age friction は recall path（recall 軸の冷却）に残す。
- **Phase P と合成** — Langevin (P-β) は軌道に Brownian キック = 軌道拡散（恒星エンカウンターの熱化）、Λ (P-α) は遠距離斥力で「束縛 vs 脱出」境界。3 つ揃うと "重力 + 膨張 + 熱" の小宇宙。Phase Q は P の上に積む。
- **デフォルト OFF** — 既存力学を変えない。opt-in で tmp 検証してから本番投入。
- **接線 α が強すぎると**離心率が暴れて clamp に当たる、**摩擦が弱すぎると** `M` が bound せず連続 tick のコストが膨らむ。弱く始める。

---

## 7. 関連

- [Phase I — Free Star Movement](Plans-Phase-I-Free-Star-Movement.md)（軌道力学の出自）
- [Phase P — Pressure Terms (Λ + Langevin)](Plans-Phase-P-Pressure-Terms.md)（合成相手）
- [Phase M — Mass Conservation](Plans-Phase-M-Mass-Conservation.md)（anchor migration 禁止の単一規則）
- [Phase K — Stellar Supernova Cohort](Plans-Phase-K-Stellar-Supernova-Cohort.md)（種速度の出元）
- [Reflections — Five-Layer Philosophy](Reflections-Five-Layer-Philosophy.md)
- [Plans — Roadmap](Plans-Roadmap.md)
- [Operations — Performance Testing](Operations-Performance-Testing.md)
