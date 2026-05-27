# Phase P — Pressure Terms (Cosmological Λ + Langevin Temperature)

**状態**: ✅ **Stage 1 (Langevin Temperature, P-β) + Stage 2 (Cosmological Λ, P-α) 両方実装完了** (2026-05-27、default OFF)。Stage 1.5 / 2.5 (本番 env opt-in) は Phase N β Stage 1.5 観測後。Phase N の「Plans 化された最初の案が Phase 確定」規約に従い、本ページが Phase P を確定する。

## Stage 2 (Cosmological Λ, P-α) 実装完了サマリ (2026-05-27)

| 項目 | 実装 |
|---|---|
| Config | `cosmological_lambda_enabled: bool = False` / `cosmological_lambda_h: float = 0.001` |
| `compute_acceleration` | 5 番目の項を追加: `a_Λ(i) += +H · (pos_i - pos_j)` を neighbor loop で。既存 4 項目 (gravity / Hooke / mass-BH / query attraction) は完全不変、Λ は純粋に additive |
| 自己力 filter | 共有 — `compute_acceleration` に渡される `neighbors` を生成する呼び出し側 (`propagate_gravity_wave` 等) が適用した filter を Λ もそのまま受け継ぐ (Plan §3.1) |
| テスト | unit 11 (off で zero、literal form、direction、distance-proportional、neighbor sum、H=0 no-op、additivity、scale-linear in H) + integration 4 (smoke off / 拡張観測 / rollback / α と β 共存) |
| 検証 | 全 674 test pass、ruff clean、Stage 1+2 同時 enable で engine.query 正常動作 |

**力学的保証**:
- `cosmological_lambda_enabled=False` で legacy 完全 bit-exact (unit assertion 済)
- `cosmological_lambda_h=0.0` でも no-op (flag on/off 両方で rollback 可能)
- Λ と Langevin は独立に enable/disable できる (Plan §1 「数学的に直交」を unit test で確認)

## Stage 1 (Langevin Temperature, P-β) 実装完了サマリ (2026-05-27)

| 項目 | 実装 |
|---|---|
| Config | `langevin_temperature_enabled: bool = False` / `langevin_temperature_t0: float = 0.001` |
| Acceleration loop | 変更なし (Stage 1 は velocity → position 段のみ触る) |
| Position update | `update_orbital_state` の `new_disp = old_disp + new_vel` の **後**、`clamp_vector` の前に `new_disp += √(2·T₀)·ξ` 加算 |
| RNG | D6 通り: `rng: np.random.Generator | None = None` 引数追加、None なら production unseeded、tests は `np.random.default_rng(seed)` 渡しで reproducible |
| 副次作業 | `compute_virtual_position` も同じ rng-injected pattern に refactor (既存 callers は無変更で動作) |
| テスト | unit 9 (bit-exact legacy / σ scale / determinism / clamp / velocity 不変) + integration 3 (engine path / displacement variance 増加 / T₀=0 rollback) |
| 検証 | 全 659 test pass、ruff clean、既存 logic に regression なし |

**力学的保証**: `langevin_temperature_enabled=False` または `langevin_temperature_t0=0.0` で legacy 完全 bit-exact (unit test で assertion 済)。Stage 1 単独で merge しても本番 default 挙動は完全に変わらない。

> Phase L (hybrid retrieval) — Phase M (mass conservation) — Phase N β (mass evaporation) — **Phase P (pressure terms)** の 4 連は、それぞれ retrieval の異なる層を扱う:
>
> | Phase | 触る層 | 単一規則の方向 |
> |---|---|---|
> | L | seed pool (BM25 union) | 物理外: 別 metric tensor の union |
> | M | mass update (self-force filter) | mass を「増やす」流れの制御 |
> | N β | mass update (evaporation) | mass を「減らす」流れの制御 |
> | **P** | **acceleration / displacement step** | **gravity という単調引力に "圧力" 項を加える** |
>
> P は L/M/N と直交する。L/M/N は mass の流入出を制御するが、P は「mass dominance が retrieval geometry を独占する」現象そのものを geometry 側で押し返す。

## 背景 — gravity は単調引力であり、対抗項なしに collapse する

Phase A 以降の GaOTTT は Newton gravity + Hooke + friction + mass-BH + query attraction の合成で動いている。これらすべての項は **何らかの引力 or 復元力 or 減衰** であって、**離心方向に押す力は構造的に存在しない**:

| 項 | 方向 | 機能 |
|---|---|---|
| Neighbor gravity (1) | 質量へ向かう | 集積 |
| Hooke anchor (2) | original_pos へ戻す | 拘束 |
| Mass-BH (3) | 高 mass へ強く引く | 集積 (高 mass のみ) |
| Query attraction (4) | query へ引く | TTT 勾配 |
| Friction | velocity を減衰 | 散逸 |

集積項が 3 本 + 復元 1 本 + 散逸 1 本。**斥力ゼロ**。

物理的事実として、重力系には負の比熱がある (cluster ↑ → 温度 ↓ → さらに cluster) ので、対抗項なしに gravity 単独で運用すると **necessarily** collapse する。実宇宙が collapse していないのは、宇宙項 (dark energy)、熱的圧力 (CMB)、角運動量 (galactic rotation) という **pressure 項** が組み込まれているから。

### Stage 7 limitation での顕在化

Lateral Association Stage 7.1 (cluster anti-hub) の本番 acceptance で残った問題 ([[stage-7-limitation]]):

> Stage 7.1 anti-hub は cluster 内 dominance を抑えるが、**individual-node high-mass dominance** には効かない。本番で観察された ffe48a30 (mass=1.92), 24a0bf39 (mass=2.09), 28fe1cf6 (mass=1.27), 5bf08058 (mass=2.0), 8e8289dd 系の singleton hub が query 横断で top1 を独占。

これは **「mass だけで query への近接が決まる」** 構造的問題で、ranking layer (Stage 7) の介入では届かない。Phase N β (mass evaporation) は **使われていない hub** には効くが、**使われ続けている singleton hub** (= query 横断で吸引し続けるので touch され続ける) には効かない。

Phase P は **「mass dominance がそもそも geometry に影響しないように pressure を入れる」** ことで、N β と直交的にこの残余を埋める。

## 1. 思想 — gravity に対抗する 2 つの pressure

`a = -∇U + (pressure terms)` の (pressure terms) を 2 系統入れる。両者は数学的に直交 (空間項 vs 時間項) なので衝突せず、両方を default OFF で並列実装する。

### P-α: Cosmological Λ — 長距離斥力 / 空間 pressure

```
a_Λ(i) = +H · Σ_{j ∈ neighbors} (pos_i - pos_j)
```

- 既存の neighbor gravity と **同じ neighbor set** に対して、距離に **比例** する反対方向の項を加える
- 局所 bound (gravity が勝つ密集) は残るが、空間スケールでは push されて cluster 間が膨張する
- 「すべての node が 1 つの supermassive node の周りに集まる」が物理的に禁止される — 宇宙が膨張してるから galaxies が衝突しないのと同じ
- **TTT 対応**: position-space の L2 regularization の符号反転 — distant pair に対する持続的な repulsive weight decay

### P-β: Langevin Temperature — 熱的揺らぎ / 時間 pressure

```
new_disp = old_disp + new_vel · dt + √(2 · T · dt) · ξ,    ξ ~ N(0, I)
```

- Verlet position update に Wiener noise を加える
- 鋭く深い井戸 (= mass=2+ singleton attractor) は確率的に脱出される、広く浅い井戸 (= 健全な diverse cluster) は安定
- **TTT 対応**: Langevin SGD = SGD + thermal kick → posterior sampling。**Bayesian deep learning の正則化機構そのもの**

### ML 文脈での読み替え

ユーザー提示の「learning rate を下げてじっくり学ぶ」は、ML では実際には **3 つの異なる機構** に分解される:

| ML 機構 | 物理対応 | GaOTTT での実現 |
|---|---|---|
| LR ↓ (smaller step) | Verlet の inverse-mass | 既にある (`a = F/m`) |
| Weight decay (L2) | Hooke restoring | 既にある (`orbital_anchor_strength`) |
| **SGLD (noise injection)** | **Langevin thermal pressure** | **P-β で新規** |
| Adam adaptive LR | Eddington luminosity (検討候補だが今回見送り) | 未実装 |
| Margin / repulsion | **Cosmological Λ** | **P-α で新規** |

「lower LR」 は GaOTTT で既に `a = F/m` として実装されているので、今回追加するのはむしろ **その上に乗せる pressure** — つまり SGLD と margin。

## 2. 物理アナロジーの正直な扱い (Phase N の名前 vs 数学 ルール)

Phase N β で確立した規約: **「名前は homage、数学は問題を解くもの」** ([[plans-phase-n-mass-evaporation]] §2)。Phase P も同じ姿勢で扱う。

| 名称 | 真の物理 | GaOTTT 実装 | 何を借りるか |
|---|---|---|---|
| Λ (cosmological constant) | `T_μν = -Λ/(8πG) · g_μν`、metric tensor の uniform diagonal | embedding space の pairwise repulsion | **distance-proportional repulsion** という挙動だけ |
| Hubble expansion | `dr/dt = H · r` (comoving coordinates) | velocity bias `v_i += dt · H · Σ_j (pos_i - pos_j)` | comoving particle が **distance に比例した相対速度** を持つ literal な式 |
| Langevin equation | `dv = -γv dt + √(2γT) dW` (FDT に従う) | position update に `√(2T·dt) ξ` を直接乗せる | thermal kick の **数学的 form** |
| SGLD (Welling-Teh 2011) | `θ ← θ - η∇L + √(2η) ξ` | 上に同じ | TTT 対応の理論的根拠 |

特に Λ は GR では metric の項であって force ではないが、**embedding 空間は非相対論的な flat space として扱っている** ので、Λ の "膨張効果" を **直接 acceleration 項として書く** ことに矛盾はない。これは Phase I で「query attraction を MSE 勾配と読めば literal な TTT」と書いたのと同じ精神。

## 3. 単一規則 — Pressure Conservation 法則

Phase M (源泉) と Phase N β (汲み上げ停止) に続く **第 3 の単一規則**:

```
∀ pair (i, j) in same wave:
  if not is_self_force(i, j):
    a_Λ(i) += +H · (pos_i - pos_j)    # P-α: distance-proportional repulsion

∀ node n with displacement:
  new_disp(n) += √(2 · T · dt) · ξ_n   # P-β: thermal kick, ξ_n ~ N(0, I) i.i.d.
```

### 3.1 何が単一規則として保証されるか

| 性質 | 帰結 |
|---|---|
| source 分岐ゼロ | agent/file/tweet/persona すべて同じ式 — Phase M/N 系譜と整合 |
| mass しきい値ゼロ | Λ も Langevin も mass を見ない (geometry のみで決まる) — Stage 7 limitation の **mass dominance** を **mass 値そのものに頼らず** 解く |
| self-force 除外 | Λ は `is_self_force_by_id` filter を gravity と共有 — same-cluster (cohort_id/original_id 一致) は repulsion されない (= cluster 内構造は保たれる) |
| Hooke との共存 | Λ は inter-pair 反発、Hooke は原点 (`original_pos`) への引力。Hooke が「原点周りで節度を保つ」、Λ が「他者から距離を保つ」、両者で 2 軸 |
| friction との共存 | Langevin noise は velocity update の **後** に position に乗る。friction で `v` が減衰してもなお `√(2T)` の random walk は維持される (= 完全停止しない) |

### 3.2 Phase M との関係

Phase M `is_self_force_by_id` filter は mass update を filtering する **attribution rule**。Λ も同じ filter を gravity と共有する — つまり「**他者からの引力でのみ mass を持つ** (M)」「**他者との距離で repulsion を受ける** (P-α)」が対称形になる。

Langevin (P-β) は self/other を見ない (個別 node の displacement に独立 noise) ので、Phase M との結合点はない。これは Langevin が **環境からの熱バス** という設定だから — 他者由来ではなく vacuum 由来。

## 4. 実装スコープ (D1-D7、決済)

### D1. Λ の力学形式 ✅ **velocity additive** (acceleration ではなく velocity に直接加算)

```python
# gaottt/core/gravity.py compute_acceleration() 内、neighbor gravity loop と同じ neighbors を使う
for pos_j, mass_j in neighbors:
    # ... gravity 4 項目はそのまま ...

# 5. Cosmological Λ (Phase P-α)
if config.cosmological_lambda_enabled:
    for pos_j, _ in neighbors:
        # is_self_force_by_id filter は neighbor list 生成側 (propagate_gravity_wave)
        # で既に適用済 — neighbors にはここで再 filter 不要
        acc = acc + config.cosmological_lambda_h * (pos_i - pos_j)
```

却下した候補:
- **(a) Hooke と同じ origin-relative 形式 `a_Λ = +H · (pos_i - 0)`**: cosmological constant の真の意味と異なる (全 node が一様に外側へ加速、座標原点に依存する artifact)
- **(b) Newton と同じ 1/r² の repulsive 版**: 近距離 (cluster 内) で発散、Λ の "distance に比例" 性質を壊す

cosmology の Hubble flow `dr/dt = H · r` は実物理では velocity-level だが、GaOTTT は dt=1 の Verlet なので velocity-update と acceleration-update は数式上区別不要。`compute_acceleration` 内に追加する方が既存 4 項目との対称性が良い。

### D2. Langevin noise の場所 ✅ **position update step** (velocity ではなく displacement に直接加算)

```python
# gaottt/core/gravity.py update_orbital_state() 内、new_disp = old_disp + new_vel の後
if config.langevin_temperature_enabled and config.langevin_temperature_t0 > 0.0:
    sigma = math.sqrt(2.0 * config.langevin_temperature_t0)  # dt=1 absorbed
    noise = np.random.randn(*new_disp.shape).astype(np.float32) * sigma
    new_disp = new_disp + noise
new_disp = clamp_vector(new_disp, config.max_displacement_norm)
```

却下した候補:
- **(a) velocity に乗せる (true Langevin)**: `v += √(2γT) ξ` は friction `γ` と FDT で結ばれるべきだが、GaOTTT の friction は age-dependent (`orbital_friction_age_factor`) で γ ≠ const、FDT が成立しない。position-level に乗せれば friction の構造に縛られない
- **(c) compute_acceleration に乗せる**: acceleration は他項目との結合が強く (mass / score / gate 等)、noise が他項に影響する。position に乗せれば「最後に random walk が 1 step 加算される」だけで blast radius 最小

position 加算は SGLD (Welling-Teh 2011) の `θ ← θ - η∇L + √(2η) ξ` と同型 — TTT 対応として最も clean。

### D3. 既存 `state.temperature` との関係 ✅ **別チャネル、追加実装ゼロで共存**

| 項目 | 既存 `state.temperature` | 新規 Langevin temperature |
|---|---|---|
| 計算 | `gamma * var(recent activations)` — 動的、per-node | constant global knob `langevin_temperature_t0` |
| 適用箇所 | `compute_virtual_position()` — read time | `update_orbital_state()` — write time |
| 物理対応 | 観測ノイズ / measurement disturbance | dynamics ノイズ / Brownian kick |

別概念なので衝突せず、両方が無効化されていれば動作は legacy 等価。将来的に統一する余地はあるが Phase P scope 外。

### D4. Λ の wave scope ✅ **既存 wave neighbors と同一 (= seed pool ∪ wave-expanded)**

Λ は `compute_acceleration()` の `neighbors` 引数を gravity と共有する。これは `propagate_gravity_wave()` で構築される wave-reached set。

**理由**:
1. 全 node 対 全 node の O(N²) Λ は 24K nodes で intractable (576M pair / step)
2. cosmology でも Hubble flow は "観測可能宇宙" の範囲 — 全宇宙ではなく causally connected region
3. wave neighbors はちょうど "今この query で gravity を感じている set" なので、対応する Λ の「観測可能宇宙」として自然
4. is_self_force_by_id filter が wave 生成側で既に適用済

Stage 1 で wave scope 限定で十分。将来 (Stage 3+) で「query-independent な global Λ」を別 cron で適用する余地は残す (Phase N β の eager cron と同じ pattern)。

### D5. ハイパーパラメータ初期値

| param | 暫定値 | 根拠 | 確定方法 |
|---|---|---|---|
| `cosmological_lambda_enabled` | `False` | default OFF (Phase L Stage 1 / Phase N Stage 1 と同 pattern) | Stage 1.5 で env opt-in |
| `cosmological_lambda_h` | `0.001` | gravity_G=0.01 の 1/10。「弱い斥力で長期に効く」スケール感。`a_Λ ~ H · |Δ| ~ 0.001 · 0.5 ~ 5e-4` for displacement 0.5、これは gravity acc ~5e-3 の 10% | dry-run + 本番 opt-in で 1-2 桁単位調整 |
| `langevin_temperature_enabled` | `False` | default OFF | Stage 1.5 で env opt-in |
| `langevin_temperature_t0` | `0.001` | `σ = √(2T) ~ 0.045` → 1 step あたり L2 ~0.045 の random walk、Hooke 平衡 `(G·m/k)^(1/3) ~ 0.8` の 5% | dry-run + 本番 opt-in |

これらは **Phase M Stage 2 / Phase N β Stage 1.5 と同様、観測で決める**。Stage 1 で literal な実装を入れた上で 1-2 週観測 → Stage 2 で本決め。

### D6. Determinism — Langevin の seed 管理 ✅ **caller-provided seed for tests, default unseeded**

```python
# gaottt/core/gravity.py
def update_orbital_state(..., rng: np.random.Generator | None = None):
    if rng is None:
        rng = np.random.default_rng()  # production: unseeded
    # ...
    noise = rng.standard_normal(new_disp.shape).astype(np.float32) * sigma
```

- production: unseeded → 真の stochasticity
- tests: `rng = np.random.default_rng(42)` を fixture から渡して reproducible
- 既存 `compute_virtual_position` の `np.random.randn` (line 87) も同様に rng-injected に refactor (Phase P-β 副次作業)

### D7. 観測ハンドル ✅ **`scripts/diag_pressure.py` 実装完了 (2026-05-27)**

Phase N β の `scripts/diag_dormant.py` / `phase_n_dry_run.py` と同じ位置付け:

- `diag_pressure.py snapshot`: 本番 DB を read-only で開き (write-behind loop 全 disable)、Λ と Langevin の 1-step 効果を dry-run projection
- 出力 (text mode):
  - 全体: active nodes / embedding dim / H / T₀ / σ=√(2·T₀) / Langevin expected per-step ||noise||=σ·√dim
  - Top-K mass hubs (default K=20): mass / |d| / source / neighbor count / ||a_Λ|| / a_Λ/m / content preview
  - Λ accel 統計: min / p50 / p90 / p95 / p99 / max / mean over hubs
  - Headlines: largest Λ accel hub、median ||a_Λ|| vs Langevin step norm の比 (どちらが dominant か)
- `--json` mode: machine-readable で diff 駆動・secondopinion-MCP Observer C 入力に
- `--out FILE`: stdout でなくファイルに書き出し
- `--lambda-h` / `--langevin-t0` で config default を override して試算可能
- **safety contract**: SQLite + FAISS とも read-only。`faiss_save_interval=999s` / `flush_interval=999s` / `virtual_faiss_save_interval=999s` で write-behind loop 全 disable、`genesis_kick` / `dream` も off
- Tier 4 smoke: 3 test (`tests/perf/test_tier4_diag_pressure.py`) — JSON 出力 / text mode headline / `--out` file 書き出し

## 5. 副次予測 — 検証可能な仮説

| 仮説 | 観測方法 | 期待値 |
|---|---|---|
| 個別 singleton high-mass dominance (ffe48a30 等) の query 横断 top1 占有が減る | Stage 7 acceptance と同じ 5 query で top1 を再測定 | top1 occupation が 5/5 → 2-3/5 に分散 |
| 健全 cluster (cohort 内) の semantic 一貫性は保たれる | 米国会社四季報 638-chunk クエリで book chunks in top-5 = 1/5 (Stage 7.1 baseline) が崩れない | book chunks in top-5 ≥ 1/5 を維持 |
| Λ 単独より Λ + Langevin の方が hub dominance 解消が効く | Stage 1 (Langevin) と Stage 2 (Λ) を別 PR で merge、Stage 2 acceptance で前者との差分計測 | Stage 2 acceptance で top1 占有がさらに下がる |
| Phase N β との直交性 | Phase N β enabled + Phase P disabled の baseline と、Phase N β enabled + Phase P enabled の比較で、互いの効果が打ち消し合わない | Phase N β drain 量と Phase P top1 dispersion が独立に変動 |
| displacement 分布の長期安定 | Phase I Stage 1 [長期検証](Plans-Phase-I-Free-Star-Movement.md#stage-1--長期検証-結果-2026-05-12) と同じ 24K nodes baseline で max/p99 を再測定 | max ≤ 1.0 (Hooke + friction で bound)、Λ 込みでも発散しない |

仮説 1 が **Phase P の存在意義そのもの** — Stage 7 limitation の literal 解消。

## 6. テスト計画

### 6.1 Unit tests (`tests/unit/test_pressure_terms.py`)

- **Λ**: `compute_acceleration` を 2 node fixture で呼び、`a_Λ = H · (pos_i - pos_j)` が literal に出ることを確認
- **Λ self-force**: same-cohort pair で neighbors から除外されるか (gravity と共有の filter なので、neighbor 生成側のテスト)
- **Langevin**: `update_orbital_state` に seeded rng を渡し、同じ seed で同じ noise が乗ることを確認 + std が `√(2T)` に一致
- **Langevin disabled**: `langevin_temperature_enabled=False` で legacy 挙動と bit-exact 一致 (regression guard)

### 6.2 Integration tests (`tests/integration/test_engine_pressure_terms.py`)

- Λ + StubEmbedder で 10 node fixture を 100 step 走らせ、cluster centroid 距離が長期に **増える** ことを確認 (= 膨張)
- Langevin + StubEmbedder で同 fixture を、`T=0` の baseline と比較し、`T>0` での displacement variance が増えることを確認
- Phase M `is_self_force` filter との共存: same-cohort batch で `remember` 後、Λ が cohort 内 pair に効いていないこと

### 6.3 Tier 4 perf test (`tests/perf/test_tier4_pressure_terms.py`)

- 30 chunk corpus、Phase I Stage 1 long-term obs 形式 (24K nodes は重いので scale down)、`|d| max` と `|d| p99` が `T_0` を上げても発散しないこと
- ablation: Λ off / Λ on / Langevin off / Langevin on の 4 cell で nDCG / MRR 比較

### 6.4 Tier 3 quality test (`tests/perf/test_tier3_pressure_terms_quality.py`)

- Stage 7 acceptance のクエリ集合 + ffe48a30 / 24a0bf39 等の hub node を含む production-like fixture で、`top1` 占有率を baseline / Λ / Langevin / Λ+Langevin の 4 cell で測定

### 6.5 Track B playthrough (`Operations-Performance-Testing.md` Figure 2 新設)

Phase N β の Track B と同じ pattern: GLM-5.1 経由で 7 query playthrough、機械軸 + 定性軸 + 官能軸の 3 axis 評価。Figure 1 (Phase N β 完遂時) との比較で「mass dominance が解けたあとの retrieval geometry」がどう動いたか観測。

## 7. ハイパーパラメータと config 追加

```python
# gaottt/config.py に追加 (Phase P)

# --- Phase P-α: Cosmological constant Λ -----------------------------------
# Long-range repulsion proportional to inter-node distance. Acts as a
# "pressure" term opposing gravity's monotonic attraction. Default OFF.
# When enabled, every wave-neighbor pair contributes
# ``a_Λ(i) += +H · (pos_i - pos_j)`` to acceleration. Source-blind,
# mass-blind, shares the gravity neighbor scope and ``is_self_force_by_id``
# filter (so same-cohort pairs are unaffected — cluster internal structure
# is preserved while inter-cluster space expands).
cosmological_lambda_enabled: bool = False
cosmological_lambda_h: float = 0.001   # H — Hubble-flow rate. 0.1× gravity_G.

# --- Phase P-β: Langevin temperature --------------------------------------
# Stochastic thermal kick added to position-update step:
#   new_disp += √(2 · T · dt) · ξ,  ξ ~ N(0, I),  dt = 1.0
# This is the SGLD (Welling-Teh 2011) noise term — exits sharp deep wells
# probabilistically while broad shallow wells stay stable. Default OFF.
# Distinct from the legacy per-node ``state.temperature`` (which adds
# read-time noise inside ``compute_virtual_position``); the two are
# orthogonal noise channels and may coexist.
langevin_temperature_enabled: bool = False
langevin_temperature_t0: float = 0.001  # T₀ — global temperature constant
```

`cosmological_lambda_enabled=False` / `langevin_temperature_enabled=False` の両方で完全 legacy。

env opt-in (Stage 1.5):
- `GAOTTT_COSMOLOGICAL_LAMBDA_ENABLED=true`
- `GAOTTT_COSMOLOGICAL_LAMBDA_H=0.001`
- `GAOTTT_LANGEVIN_TEMPERATURE_ENABLED=true`
- `GAOTTT_LANGEVIN_TEMPERATURE_T0=0.001`

## 8. Stage plan

### Stage 1 — P-β Langevin Temperature 実装 + default OFF (本 PR scope, 想定 1-2 day)

理由: Langevin は P-α より architectural blast radius が小さい (`update_orbital_state` 内 1 行追加、neighbor scope 不変、self-force filter 不要)。先に入れて回す。

- `gaottt/core/gravity.py::update_orbital_state` に noise 加算 (D2 通り)
- `gaottt/core/gravity.py::compute_virtual_position` の既存 `np.random.randn` を rng-injected に refactor (副次作業、test fixture 都合)
- `gaottt/config.py` に `langevin_temperature_*` 2 フィールド
- Unit + integration + Tier 3/4 perf テスト
- default **OFF**

### Stage 2 — P-α Cosmological Λ 実装 + default OFF (別 PR、想定 2-3 day)

- `gaottt/core/gravity.py::compute_acceleration` に Λ 項追加 (D1 通り)
- `gaottt/config.py` に `cosmological_lambda_*` 2 フィールド
- Unit + integration + Tier 3/4 perf テスト
- default **OFF**

### Stage 1.5 / 2.5 — 本番 env opt-in (各 Stage 別 PR)

- Stage 1 完了後 1 週観測 → Stage 1.5 で Langevin を env opt-in
- Stage 2 完了後 1 週観測 → Stage 2.5 で Λ を env opt-in
- 各 opt-in で `scripts/diag_pressure.py` による dry-run + secondopinion-MCP 経由 Track B playthrough

### Stage 3 — 観測 + default 昇格判断 (1-2 ヶ月後)

- Stage 1.5 / 2.5 の本番 opt-in を 1-2 ヶ月走らせて、3-observer pattern ([[verification-2026-05-26-stage-7-phase-n]] §3) で literal 数値の一致を確認
- 副次予測 (§5) すべてを 1 つずつ verify
- 段階 3 (config default 昇格) の判断は **観測結果次第**:
  - 仮説 1 (hub dominance 解消) が confirmed → default 昇格候補
  - 副次予測のどれかが反証 → opt-in のまま維持 or rollback
- Phase N β と同じく、**default 昇格しない選択肢を残す** (機構が "rolling release" の前提でなく、明示 opt-in が運用的に正しい場合)

### Stage 4 (optional) — Λ の global scope 拡張

- wave 外 (causally disconnected) pair にも Λ を eager cron で適用するかの設計
- Stage 3 観測で「wave scope だけでは singleton hub に届かない」と判明した場合のみ着手

## 9. ロールアウト戦略

### 順序 — Phase N β との関係

**Phase P Stage 1 (Langevin) は Phase N β Stage 1.5 と並行可能**:
- 両者は default OFF で merge できる (副作用なし)
- env opt-in 順序は **N β 先、P 後** が clean

理由: Phase N β は **mass 分布そのものを動かす** (drain される)。Phase P が先に geometry を動かすと、N β の drain target が moving target になる。Phase M Stage 2 (θ 確定) → Phase N β Stage 1.5 (evaporation 起動) → 1-2 週観測 → Phase P Stage 1.5 (Langevin) → 1-2 週観測 → Phase P Stage 2.5 (Λ) の順が最も clean。

### Migration 要否

- スキーマ変更なし (state.displacement / state.velocity は既存)
- `migrate.py` への新規追加なし
- rollback: `cosmological_lambda_enabled=False` + `langevin_temperature_enabled=False` で即停止、displacement は Hooke で原点に戻る (= 復旧)

### 3-Observer Pattern の適用 ([[verification-2026-05-26-stage-7-phase-n]] §3)

| Observer | 役割 | Phase P での具体 |
|---|---|---|
| A. 直読み snapshot | DB literal 数値 (ground truth) | Stage 1.5 / 2.5 enable 前後の `state.displacement` 分布 snapshot |
| B. dry-run projection | 「適用したらどうなるか」予測 | `scripts/diag_pressure.py snapshot` で本番 DB read-only + Λ/Langevin の 1-step 効果 projection |
| C. 独立 LLM 観察 | P7-Z 回避 | secondopinion-MCP 経由 GLM に Stage 7 limitation の 5 hub クエリで top1 占有を独立計測依頼 |

3 observer の literal 一致を Stage 1.5 / 2.5 の opt-in 判断条件とする。

## 10. 開放問題

1. **Λ の neighbor scope は wave-reached set だが、wave 外の "観測されない宇宙" は Λ を受けない** — これは意図的 (D4 通り、causally disconnected を再現) だが、**「ある query で wave に入る/入らない」が確率的に決まる** ので、long-term 平均で Λ 効果は均される想定。観測で確認。
2. **Langevin noise が virtual FAISS の write-behind と相互作用するか** — virtual FAISS は `virtual_faiss_save_interval_seconds=60` で displacement を rebuild する。Langevin で常時 random walk すると virtual FAISS が永遠に dirty になる可能性。観測で帯域影響を計測。
3. **Phase I Stage 4 mass-dependent Hooke (β=0 default) との干渉** — Hooke が mass で variable になる + Λ が constant → mature 高 mass node では Hooke が弱まる + Λ で push される、の合成。`β > 0` を opt-in したときの Phase P 影響を別軸で追う必要あり。
4. **Λ と mass-BH (Phase M) の物理的整合** — mass-BH は `tanh((m-θ)/σ)` の continuous attractor。Λ は mass-blind の repulsion。「重い BH への Λ 反発」が意図か unintended consequence か。設計通り (geometry に mass を入れない単一規則) だが、本番で hub が **bound** ではなく **expelled** になる極端ケースが起きうるか観測。

## 11. Phase N の "残り候補" との関係

Plans-Roadmap.md §40 の規約で「Phase N の Plans 化されなかった候補 (N-α RRF-scale aware mass boost / N-γ Muon thought experiment) は Phase P/Q/R に繰り下げ」とあるが、**Phase P は Pressure Terms を確定する**。

| N の元候補 | 現状 | 今後の Phase letter 案 |
|---|---|---|
| N-α (RRF-scale aware mass boost) | 未起草、scope は ranking layer の score scale 正規化 | Phase letter を消費しない "ranking layer fix" として扱う (Phase H Stage の延長 or 独立 PR) |
| N-γ (Muon thought experiment) | 思考実験段階 | Phase Q / R に繰り下げ候補。Phase P 完了後の hybrid retrieval geometry が落ち着いてから着手 |

N-α は構造的に小規模 (config 1-2 個 + score normalize 1 関数) なので Phase letter 消費は overkill、N-γ は研究領域なので即 Phase 確定は早い。**Phase P を Pressure Terms に割り当てる方が物理体系の対称性で美しい** ([[plans-phase-m-mass-conservation]] §13 〜 [[plans-phase-n-mass-evaporation]] §2 の対称命題の系列を引き継ぐ)。

## 12. 関連 memory / 出典

- [[stage-7-limitation]] — singleton high-mass dominance が Stage 7.1 scope 外、Phase N β / Phase P の領域
- [[plans-phase-m-mass-conservation]] §13 — Articulation as Carrier の単一規則、Phase P は対称命題の第 3 法則として接続
- [[plans-phase-n-mass-evaporation]] §2 — 「名前は homage、数学は問題を解くもの」規約、Phase P でも適用
- [[plans-phase-i-free-star-movement]] Stage 1 長期検証 — displacement 分布 baseline (Phase P で発散しないことを確認)
- [[plans-ambient-recall-lateral-association]] Stage 7 — anti-hub が cluster 内 dominance を扱う ranking layer、Phase P は geometry layer で相補
- [[research-gravity-as-optimizer]] §5 — TTT 対応表に SGLD 行を追加する必要 (Phase P 副次作業)
- [[verification-2026-05-26-stage-7-phase-n]] §3 — 3-observer pattern、Phase P でも踏襲

## 13. Personal note (Claude, 2026-05-26)

Phase M (Articulation as Carrier) と Phase N β (使われない言葉は重力を失う) で **「言葉と重力」の input/output** が対称形になった。Phase P は方向を変えて **「重力場に対抗する pressure」** を入れる — gravity だけでは collapse する系に、cosmic expansion と thermal motion を入れることで宇宙が壊れないようにしているのと同じ。

これは ML 文脈の「lower LR でじっくり学ぶ」とは少し違う向きの解 — LR 自体は `a = F/m` で既に inverse-mass 済み。今回入れるのは **margin と exploration** という、optimizer ではなく optimizer の周りに置く正則化機構。SGLD と weight decay の物理対応が、cosmology の Λ と CMB に literal に対応するのが個人的には一番美しい。

Phase L (lexical metric の重ね合わせ) — Phase M (mass 増の単一規則) — Phase N β (mass 減の単一規則) — Phase P (geometry pressure) の 4 連は、retrieval を「言葉の重力場」として書き切るために必要な軸が一通り揃う形になる。Phase P の後、次に来るべきは何か (curvature? phase transition? Pauli exclusion?) は、Phase P 観測の後に自然に見えてくるはず。

**This plan is a sketch, not a commitment.** Stage 1 着手判断は Phase N β Stage 1.5 の本番観察結果次第。Phase P が「やらない方が良い」結論になる余地も残す (= Phase M/N で十分 hub dominance が解けていれば Phase P は overkill)。
