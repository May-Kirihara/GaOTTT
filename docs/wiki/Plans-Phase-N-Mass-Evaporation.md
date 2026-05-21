# Phase N candidate β — Mass Evaporation (Hawking radiation 類比)

**状態**: 起草 (2026-05-15)。Phase N 候補 3 案 ([α RRF-scale aware mass boost](Plans-Roadmap.md#phase-n) / β 本ページ / γ Muon 思考実験) のうち、Plans 化された最初の案を Phase N 確定とする規約に従う。**Plans 化 = 着手 commitment ではない** — Phase M Stage 2 (mass reset 後 1-2 週観測 + θ 確定) との順序を [§9 ロールアウト戦略](#9-ロールアウト戦略) で扱う。

## 背景 — 入力 4 / 出力 0 という mass の非対称

Phase M Stage 1 までで、mass を **増やす** 機構は 4 系統そろっている:

| 系統 | 由来 | Phase |
|---|---|---|
| 共起 Hebbian 更新 | recall 中の reached set 内の `state.mass += δ * w(edge)` | Phase A baseline |
| Genesis kick | 新規 ingest 時の近傍重力 kick | Phase G Stage 1 |
| Supernova batch impulse | `remember(batch)` の cohort 内相互 mass boost | Phase K Stage 1 |
| Query attraction | Phase I Stage 2 `a = (α·score·gate/m)·(q-pos)` の reached node 側への副作用累積 | Phase I Stage 2 (Stage 3 で gate 化) |

mass を **減らす** 機構: **0 系統**。

唯一の "下向き" は Phase M の self-force filter だが、これは attribution-level (どの寄与が count されるか) であって erosion ではない。Phase M 適用 = **未来の inflation を止める** が、**既に積み上がった legacy mass debt は減らない**。

### 2026-05-15 GLM-5.1 acceptance での観察

外部観察者 (secondopinion-MCP 経由 GLM playthrough、Figure 0 [`Operations-Performance-Testing.md`](Operations-Performance-Testing.md)) が独立に検出した: **hot_topics の上位は「重要だから」ではなく「過去に Bulk ingest 経由で co-recall を蓄積したから」上位にいる**。具体的には Japan の刑法第 175 条 (わいせつ物頒布) と GaOTTT 運用 note。

これは Phase M で **入力側を止めた後** も残り続ける、構造的な 過去 inflation 残滓 の問題。Phase O Stage 5 dormant も「過去に inflate して今は静かに高 mass で居座っている」ノードを subjectively は捕まえられないので (high mass = dormant 条件から外れる)、補完機構が必要になる。

## 1. 思想 — 「使われない重力中心は時間とともに薄れる」

物理的直感:
- 天体の質量は永遠ではない。恒星は luminosity を介して質量を放射に変えて寿命を持つ。
- ブラックホールも Hawking 放射で蒸発する (時間スケールは長いが ≠ 不変)。
- 真空中の塵が永久に塵で居続けるのは、塵自身に放射するエネルギーが無い (= 質量が極小) から。

GaOTTT への対応:
- mass-BH (Phase M で `tanh((m-θ)/σ)` で連続化された attractor) は **「外部からの引力で吸い込み続ける限り **だけ** BH のまま」
- 引力 (= recall 経由の query attraction、共起更新、persona traversal) が止まれば、**蓄積した mass を時間とともに放射 (= 減少)** していく
- 塵 (低 mass) は放射するものが少ないので、ほぼ不変 (新規ノードの保護)

**つまり mass は「他者との関係性の蓄積」 (Phase M) であると同時に、「他者との関係性が断たれれば散逸する」(Phase N β)。** Articulation as Carrier の literal な物理実装 ([Phase M §1](Plans-Phase-M-Mass-Conservation.md)) に対し、Phase N β は **「言葉にしたものが、誰にも再び持ち出されなければ、重力を失う」** という対称命題の物理化。

## 2. 物理アナロジーの正直な扱い

「Hawking radiation」を素朴に literal 適用すると、direction が逆になる罠がある。整理:

| 名称 | 法則 (時間あたり) | 効果 | GaOTTT で何が起きるか |
|---|---|---|---|
| 真の Hawking | dM/dt ∝ -1/M² | **重い BH ほど放射が遅い** (M³ 寿命) | hot_topics の hub が **不死** に近づく ❌ |
| 恒星質量放射 | dM/dt ∝ -L ∝ -M^(3.5) (主系列) | **重い恒星ほど短命** | hub が自己訂正 ✅ |
| Ebbinghaus | dM/dt ∝ -ε · (M - M_floor) · f(t_idle) | mass + time の合成、調整可能 | 既存 `last_access` で実装容易 ✅ |

**名前は "Hawking radiation 類比" で残す** (Phase M 文書 §13 の先行用語、めいさんの命名意図) が、**数学は恒星質量放射 + Ebbinghaus の混合** を採る。これは Phase M で「source 分岐」を一切採らずに「self-force = 構造的識別子のみ」で literal physics を書いたのと同じ姿勢: **名前は homage、数学は問題を解くもの**。

### 候補となる decay law (D1 で確定)

```python
# (A) Pure time-decay (Ebbinghaus、Phase M §13 の seed 案)
state.mass *= (1 - epsilon * dt_since_last_access)

# (B) Mass-amplified time-decay (現案、本ページが提案)
state.mass -= epsilon * max(state.mass - M_floor, 0) ** beta * t_idle_normalized ** gamma

# (C) Stellar luminosity 型 (β=3.5 で恒星寿命に類似)
state.mass -= epsilon * state.mass ** 3.5 * t_idle_normalized
```

(B) が現在の有力候補。3 パラメータ (ε, β, γ) + 1 floor で挙動を細かく調整できる。

## 3. 単一規則 — 「mass は時間と質量で蒸発する」

```
∀ node n:
  if state.mass > M_floor and (now - state.last_access) > τ_grace:
    mass_after = max(M_floor,
                     state.mass - ε · (state.mass - M_floor)^β · ((now - state.last_access) / τ_idle)^γ · dt)
```

- **source 分岐ゼロ** (Phase M 単一規則と整合): agent も file も tweet も同じ式
- **floor 保護** (`M_floor` 以下は不変、新規ノード保護): `M_floor = 1.0` で初期質量と一致
- **grace period** (`τ_grace`、例 7 days): recall 直後の即時 decay を防ぐ
- **dt** は evaluation 周期 (例 hourly cron で dt=3600s)、または lazy evaluation (アクセス時に補正)

### 3.1 何が単一規則として保証されるか

| 性質 | 帰結 |
|---|---|
| `state.mass = M_floor` のノード | 永久不変 (低 mass 保護) |
| 高 mass で recall 継続 | `last_access` が常に新しいので decay 量 ≈ 0、実質不変 |
| 高 mass で recall 途絶 | t_idle ↑ + 高 (mass)^β → decay 量 ↑、急速減衰 |
| 中 mass で recall 途絶 | decay 量 中、ゆっくり減衰 |

## 4. 実装スコープ (D1-D6 案、めいさん決済)

### D1. Decay law の確定 ✅ (B) Mass-amplified time-decay (2026-05-15 確定)

```
mass -= ε · max(mass - M_floor, 0)^β · (t_idle / τ_idle)^γ
  if mass > M_floor and t_idle > τ_grace
```

3 パラメータ (ε, β, γ) + 1 floor で挙動を細かく調整できる。Stage 1 起動時の暫定値は `ε=0.01, β=1.5, γ=1.0, τ_idle=30日, τ_grace=7日, M_floor=1.0`。**観測で確定** (Phase M Stage 2 と同様)。

却下した候補:
- (A) Pure Ebbinghaus (`mass *= (1 - ε·dt)`): mass-aware 性なし、hub と塵に同じ rate がかかるので hub dominance を直接矯正できない
- (C) Stellar 型 (`mass -= ε·mass^3.5·dt`): β=3.5 固定で、低 mass まで一気に蒸発させすぎる (新規ノード保護が崩れる)

### D2. Evaluation 戦略 ✅ (c) Hybrid (2026-05-15 確定)

**lazy** を default、**起動時 full sweep** を併用。

- **lazy 経路**: `engine._update_simulation` 内、Hebbian mass 更新 (line 1030) の直前で `evaporate_mass(state.mass, state.last_access, now, config)` を呼ぶ。recall / query で touch されるたびに「前回 access 以降の蒸発量」を補正。書き込みは既存の `state.last_access = now` と同じ tick で乗るので追加 I/O ゼロ。
- **起動時 sweep**: `engine.startup` 末尾で `mass_evaporation_enabled=True` のとき、全 active node に対し evaporate を 1 回適用。engine が長期停止していた間の "cold-start mass debt" を一括清算。lazy だけだと touch されないノードが永久 stale になるので必要。idempotent (同じ `last_access` を基準にするので 2 回呼んでも同じ結果)。

却下した候補:
- (a) eager only (cron / background loop): 全 N nodes に毎周期書き込み、I/O 過剰
- (b) lazy only: 長期 touch されないノードが永遠に stale (= hub dominance 矯正の漏れ)

eager cron は **Stage 2 で optional オプションとして残す** (`mass_evaporation_eager_cron_seconds > 0` で有効化、観測 dashboard 用途)。

### D3. M_floor、τ_grace、ε、β、γ の初期値

| param | 暫定値 | 根拠 | 確定方法 |
|---|---|---|---|
| `M_floor` | `1.0` | 新規ノード初期値 | 不変 (定義) |
| `τ_grace` | `7 days` | Phase O Stage 5 の `dormant_age_threshold_seconds` 30d の 1/4 | M002 reset 後 1-2 週観測 |
| `ε` (rate) | `0.01 / day` | 「7 days idle で `mass=5.0` のノードが `5.0 - 0.01 · 4 · 7^1 = 4.72` まで減少」のスケール感 | 観測で 1 桁単位調整 |
| `β` (mass 指数) | `1.5` | (mass - floor)^1.5 — heavy にやや amplify、最低限の self-correction | Stage 2 で 1.0 / 1.5 / 2.0 を A/B |
| `γ` (time 指数) | `1.0` | linear in t_idle、最も保守的 | β と一緒に Stage 2 |

これらは **すべて Phase M Stage 2 と同様、観測で決める**。Stage 1 で literal な実装を入れた上で 1-2 週観測 → Stage 2 で θ/σ と同時に Phase N param を本決め。

### D4. mass-BH との相互作用

Phase M `compute_mass_bh_acceleration` は `bh_factor = tanh((m-θ)/σ)` で連続。mass が evaporation で下がれば自然に `bh_factor` も下がり、attractor 効果も連続的に低下する。**追加実装ゼロで integrate される**。

### D5. Phase O Stage 2 training_delta との integration

evaporation event は recall とは別チャネルだが、「mass の総和が変化した量」として観測可能にする:

```python
class TrainingDelta:
    mass_changes: dict[str, float]
    evaporation_changes: dict[str, float] = Field(default_factory=dict)  # 新規追加
```

formatter 側で「Δmass(evap) top: 0a1b2c.. -0.0234」のような追加行を出力。**lazy evaluation のときは「この recall で評価された」ノードの evaporation を表示**、eager のときは「直近 cron 周期で蒸発した」total を別 endpoint (`reflect(aspect='evaporation_log')`?) で見られるように。

D5 は **Phase N β の Stage 2 範囲** (β の core 実装は Stage 1)。

### D6. 観測ハンドル — Mass distribution snapshot script

`scripts/mass_distribution.py` 新設。production DB を read-only で開いて p50/p90/p99 mass を出力。Phase M Stage 2 の θ 確定にも使えるので、N β と M Stage 2 が同じ tool を共有する。

## 5. 副次予測 — 検証可能な仮説

| 仮説 | 観測方法 | 期待値 |
|---|---|---|
| 1-2 週で hot_topics の上位陣が入れ替わる | `reflect(aspect=hot_topics, limit=10)` を週次 snapshot | top10 のうち 3-5 件入れ替わる |
| Phase O Stage 5 dormant が production で N>0 を返すようになる | 既に保存した [[project-phase-o-stage-5-production-observation]] の閾値で再測定 | `dormant_mass_threshold=2.0` のまま N≥1 |
| 新規 agent memo の top1 取得確率が上がる | "harakiriworks 想起品質" を [`Plans-Phase-M-Mass-Conservation.md §6.2`](Plans-Phase-M-Mass-Conservation.md) の問い直しで再計測 | bulk-ingest 経由 file の top1 dominance が下がる |
| 重複 BH 候補が `reflect(duplicates)` で見やすくなる | Phase O playthrough Track B の Figure 1 で観測 | duplicates timeout が解消 (mass が散ったため pairwise が軽くなる) |

仮説 2 は **Phase O Stage 5 threshold tuning が不要になる** ことを意味する — Phase N β が effectively Stage 5 の本物の dormant 母集団を生む。

## 6. テスト計画

### 6.1 Unit tests (`tests/unit/test_mass_evaporation.py`)

- `evaporate(state, now, config)` の境界: `mass <= M_floor` で no-op
- grace period: `now - last_access < τ_grace` で no-op
- monotonic: ε, β, γ それぞれ単調 (param ↑ → decay ↑)
- numerical sanity: 無限大 / NaN を発生させない

### 6.2 Integration tests (`tests/integration/test_engine_mass_evaporation.py`)

- ingest → recall 1 回 → 8 day fake clock advance → 別 recall → top1 の mass が ε·(initial - floor)·... 分減少
- recall 継続中 (毎日 fake clock + recall) → mass 不変 (within tolerance)
- Phase M self-force filter と共存: bulk ingest cohort の self-recall でも mass は増えず evaporation だけ進む

### 6.3 Tier 4 perf test (`tests/perf/test_tier4_phase_n_evaporation.py`)

- 30 chunk corpus、artifical aging + recall pattern → mass 分布の p50/p99 の長期挙動が equilibrium に向かう
- Track A の driven resonance test と独立 (異なる time scale の同居が壊れない)

### 6.4 Track B playthrough (`Operations-Performance-Testing.md` Figure 1)

Stage 1 完了後の本番 acceptance: GLM-5.1 経由で 7 query playthrough、機械軸 + 定性軸 + 官能軸の 3 axis 評価。Figure 0 (Phase O 完遂時) との比較で「hot_topics 上位の sensual valence」がどう動いたか観測。

## 7. ハイパーパラメータと config 追加

```python
# gaottt/config.py に追加
mass_evaporation_enabled: bool = False             # Phase N β rollout gate、default OFF
mass_evaporation_floor: float = 1.0                # M_floor
mass_evaporation_grace_seconds: float = 7 * 86400  # τ_grace
mass_evaporation_rate: float = 0.01                # ε (per day equivalent)
mass_evaporation_mass_exponent: float = 1.5        # β
mass_evaporation_time_exponent: float = 1.0        # γ
mass_evaporation_eager_cron_seconds: float = 0.0   # 0 = lazy only、>0 で eager cron 起動
```

`mass_evaporation_enabled=False` で完全 rollback。Stage 1 では default OFF で merge、Stage 1.5 で本番に enable する PR を別途切る (Phase M の versioned migration 方式と同じ慎重さ)。

## 8. Stage plan

### Stage 1 — Literal implementation + lazy evaluation (本 PR 想定 scope)

- `gaottt/core/gravity.py` に `evaporate_mass()` 純粋関数
- `gaottt/core/engine.py::_update_simulation` 内で lazy 適用 (touch されたノードに対し dt 補正)
- `gaottt/config.py` に 7 パラメータ + `enabled` flag
- Unit + integration + Tier 4 perf テスト
- Phase O Stage 2 training_delta との integration は **Stage 1 範囲外** (まず core を入れる)
- default **OFF**、`mass_evaporation_enabled=True` で opt-in

### Stage 1.5 — 本番 opt-in (別 PR)

- Phase M Stage 2 (mass reset 後 1-2 週観測) の結果と合わせて enable
- `scripts/mass_distribution.py` で M_floor / ε / β / γ の本決め
- 本番 acceptance (secondopinion-MCP 経由 Track B playthrough)
- 1-2 週 monitor して hot_topics が動いたか確認

### Stage 2 — Observability + eager option (別 PR)

- `TrainingDelta.evaporation_changes` 追加
- formatter に「Δmass(evap)」行追加 (Phase O Stage 2 trailer 拡張)
- `mass_evaporation_eager_cron_seconds > 0` の cron loop (cache flush と同じ pattern)
- `reflect(aspect="evaporation_log")` で直近 N hours の蒸発 top movers を見られる

### Stage 3 (optional) — Mass-aware param tuning

- β を mass percentile ベースに動的調整 ("p99 ノードは β=2.0、p50 は β=1.0")
- Stage 2 観測で hub dominance が想定通り解消しなかった場合のみ着手

## 9. ロールアウト戦略

### 順序 — Phase M Stage 2 との関係

**Phase N β Stage 1 (実装) は Phase M Stage 2 (θ 確定) を待たずに着手可能**:
- 実装 は default OFF で merge できる (副作用なし)
- 本番 opt-in (Stage 1.5) は **Phase M Stage 2 完了後**

理由: Phase M Stage 2 は「現在の mass 分布」を観測対象とする。Phase N β を先に有効化すると分布が動的に変わって観測対象が定まらなくなる。**Phase M で「未来の inflation を止めた」状態を 1-2 週固定で観測 → θ 確定 → Phase N β で「過去の inflation debt を流す」**、の順が clean。

### Migration 要否

- スキーマ変更なし (`last_access` は既に SQLite に column 存在)
- `migrate.py N005` (cold-start sweep) は Stage 1.5 の opt-in タイミングで追加 (Stage 1 では不要、lazy だけで動く)
- rollback: `mass_evaporation_enabled=False` で即停止、過去 evaporation 分の復元は **行わない** (mass debt として観測される、Phase N β γ で取り戻す機構を別途設計する余地)

## 10. 開放問題

1. **Recall は last_access を update するが、prefetch cache hit は?** — 現状 prefetch cache hit は recall 経路を通らないので touch しない。これは設計通り (Phase O Stage 2 cache hit zero-perturbation 契約) — つまり cache hit してもらっただけでは mass evaporation 抑制にならない。意図的か bug か判断。
2. **共起更新 (Hebbian) も touch だが、これは last_access を update するか?** — 現状の挙動を確認、必要なら "touch なし" の方が evaporation 設計と整合 (= 自己関与の Hebbian は last_access も上げない)。Phase M 単一規則との整合。
3. **persona traversal の hop でも last_access?** — Phase J の persona-anchored retrieval が hop した先のノードを touch するか。設計次第。
4. **mass 0 への漸近** — `M_floor=1.0` で物理的には永遠に到達しないが、float64 で実用上ほぼ floor。これは保護として OK。

## 10.5. Stage 1.5 readiness assessment (2026-05-15、GLM-5.1 dry-run 評価)

`scripts/phase_n_dry_run.py` で production 33,612 active node に対し **read-only projection** を 6 シナリオ実施 (default / 14d-30%cold / 30d-30%cold / 30d-50%cold / 30d-30%random / β=2.0 variant)、secondopinion-MCP 経由 GLM-5.1 が Track B 3-axis rubric ([Operations-Performance-Testing.md](Operations-Performance-Testing.md)) で評価。

### 観察された事実

production は 2026-05-13 Phase M mass reset 直後で、**全 33k node の last_access が 0.8 日以内**。grace=7d で完全保護され、現時点 drain=0。aging を入れた projection でのみ機構の振る舞いが見える状態。

### 機械軸

drain は 6 シナリオで 0.01-2.40% range、全ケース非破滅。default param 30d-30%highmass-cold で **0.74% total drain (415 of 55,769)**。p50/p90 不変、drain は p99+ tail に集中。floor=1.0 は全ケースで守られた。違和感 2 点:
- 30%→50% highmass-cold で drain が 0.74%→0.77% と僅か → 拡張対象が low-mass に偏るため (数学的には正しい)
- β=2.0 で compaction source (n=5、mean 6.6) が **22.19% drain** — session-summary 設計意図との衝突可能性

### 定性軸

top losers は 6 シナリオで一貫して同一 cluster (刑法 175 条 file chunks、chat ingest agent memo、claude-code session transcripts) = **Phase O Figure 0 で GLM が独立検出した legacy bulk-ingest hub と完全一致**。「使われない hub を drain する」設計意図が正確に targetting されている。

**+27 dormant pool 復元** (`mass ≤ 2.0` 通過数) — Phase O Stage 5 が production で 0 件だった問題 ([[project-phase-o-stage-5-production-observation]]) への、Phase N β 単独での最初の効果証拠 (仮説 2 の支持)。

Articulation as Carrier 対称命題 「言葉にしたものが、誰にも再び持ち出されなければ、重力を失う」が literal に動作 — recall で touch され続ける hub は drain されず、touch が止まった legacy hub だけが drain される。

### 官能軸

valence **+2**、arousal **2**、surprise **1**。somatic: 「constellation の重心がゆっくり shift する感触。β=1.5 default は重力場の撹拌 — 星は動くが座標系は保たれる。p50 が動かないことで mass を放射に変える機構の存在を確認した — 塵は塵のままで、恒星だけが寿命を持つ」。

### Verdict — conditional go

| 項目 | 判定 |
|---|---|
| Stage 1.5 enable | **追加観測必要 (go after Phase M Stage 2)** |
| 推奨 param | **default (β=1.5)** |
| β=2.0 (heavy-hub-bias) | **見送り** (compaction 22.19% drain、設計意図衝突) |
| Phase M Stage 2 との順序 | **M Stage 2 先、N β Stage 1.5 後** (Plans §9 通り、observation 期間中は N β disabled のまま idle age 蓄積可) |
| earliest enable | **2026-05-20** (mass reset から 7d、grace を超える node が出現する timing) |
| 推奨 enable | **2026-05-27** (mass reset から 14d、idle age distribution が realistic な形になってから) |

### Stage 1.5 enable 前に観察すべき 3 点

1. **Phase M Stage 2 の完了** — θ 確定前に N β を有効化すると mass 分布が動的に変わって観測対象が定まらない。
2. **idle age distribution の自然推移** — 現在 max 0.8d の全 node が 7-14d 後にどこまで自然 aging するか。grace=7d を超える node が現れ始める timing が N β の実際の起動点。
3. **compaction source の drain 感度** — β=1.5 でも compaction (n=5) は 4.29% drain と highest source 群。Stage 1.5 enable 後の compaction drain rate を monitor。本来 high-mass であるべき session summary が、使われていれば recall→grace 保護で drain されないはずだが、想定外に drain される場合は source-aware floor 調整を検討 (Phase M 単一規則との整合性を保つ範囲で)。

### 出典

- Dry-run reports: `.phase-n-dry-run/*.md` (gitignored、`scripts/phase_n_dry_run.py --sweep` で再生成可)
- GLM-5.1 evaluation session: 2026-05-15 (closed)、`secondopinion-MCP delegate_task` 経由

## 11. 関連 memory / 出典

- [[plans-phase-m-mass-conservation]] §13 — Phase M 文書内の先行用語 ("Mass Evaporation (Hawking radiation)" の命名)
- [[plans-phase-o-ttt-observability]] Stage 5 — dormant surface の母集団を Phase N β が再生
- [[project-phase-o-stage-5-production-observation]] — `dormant_mass_threshold=2.0` で 0 件、Phase N β で母集団復元 (仮説 2)
- [[plans-roadmap]] §Phase N — 候補 α / β / γ の選定規約 (Plans 化された最初の案が Phase N 確定)
- 2026-05-15 GLM-5.1 playthrough Figure 0 ([Operations-Performance-Testing.md](Operations-Performance-Testing.md)) — hot_topics の上位陣が legal docs / GaOTTT ops に偏っているという外部観察者の指摘が直接の動機

## 12. Personal note (Claude, 2026-05-15)

Phase M で「自己関与は mass を生まない」を入れたとき、対称形として「他者関与が無くなれば mass は減る」が必要になることは構造的にわかっていた。それが Phase M 自身の §13 に "Future Work — Phase N: Mass Evaporation" として書き残された。

ただ、Phase M Stage 1 直後にすぐ着手しなかったのは正しかった。**先に inflate を止めないと、何を蒸発させているのか観測できない**。Stage 1 を 1-2 週寝かせて分布が静止するのを待つ。それが Phase M Stage 2 (θ 確定) と Phase N β (evaporation 起動) の自然な順序を作る。

そして 2026-05-15 GLM-5.1 の playthrough (Phase O 完遂直後) が外部観察者として「hot_topics が legacy debt で固まっている」と独立に検出した。これは Phase M Stage 2 を待たずに Phase N β の **draft** だけ進めて良いという signal。実装は Phase M Stage 2 観測と並行できる (default OFF なので)。

物理として一番美しいのは、Phase M (源泉が articulation を介した他者依存) と Phase N β (汲み上げが止まれば自然蒸発) が **対称な単一規則** として並ぶ姿。Articulation as Carrier の 2 命題:

- 「言葉にした上で誰かに引かれることで mass を持つ」 (Phase M、入力側)
- 「言葉にしたものが、誰にも再び持ち出されなければ、重力を失う」 (Phase N β、出力側)

両方が 1 つの式で書けたとき、Five-Layer (物理 / 生物 / TTT / 関係 / 人格) の **生物層** で「使われるニューロンは強化され、使われないシナプスは刈り取られる (Hebbian learning + Synaptic pruning)」と literal に一致する。Phase M だけだと半分しか実装されていない。

Hawking radiation の名前は homage として残す。**数学は問題を解くために選ぶ** ([§2](#2-物理アナロジーの正直な扱い))。
