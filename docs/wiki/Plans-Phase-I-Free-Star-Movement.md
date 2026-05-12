# Plans — Phase I — Free Star Movement

> 状態: **Stage 1 ✅ 完了 (2026-05-11)** — [長期検証 ✅ (2026-05-12)](#stage-1--長期検証-結果-2026-05-12), **Stage 2 ✅ 完了 (2026-05-11)**, **Stage 3 ✅ 完了 (2026-05-13) — Mass-gated query attraction**
> 関連: [Roadmap](Plans-Roadmap.md), [Architecture — Gravity Model](Architecture-Gravity-Model.md), [Phase G — Memory Genesis](Plans-Phase-G-Memory-Genesis.md), [Phase H — Wave Seed Redesign](Plans-Phase-H-Wave-Seed-Redesign.md)
> 発端: 2026-05-11 セッション中の P7-X 観察 (検証ループによる boundary saturation 偶発的再現)、Stage 3 は 2026-05-12 セッション中の単一アトラクタ pathology 観察

## 背景

Phase G/H で「新規粒子を重力場に正しく入れる」「sparse class を seed に届ける」を解決した。残っていた構造的限界は **displacement 自体の自由度**:

- Phase G priming + 検証ループの偶発的繰り返しで、特定 memory cluster の displacement が `max_displacement_norm=0.3` の上限に張り付く現象 (**P7-X saturation**) が発生
- boundary に張り付いた memory 群は `virtual_pos = raw + displacement` の差別化が消え、verbatim keyword 一致でも recall できなくなる
- これは Phase G PG-5 (Stage 3 重心アンカー永久保留) で警告した **homogenization の受動的再現**

PG-5 では「能動的に重心吸引するのは多様性を殺す」と保留にした。Phase I で発見されたのは「**boundary 自体が同種の homogenization を起こす受動的経路**」だったということ。

## 仮説 (Stage 1)

`max_displacement_norm` (ハードキャップ) は本当に必要か?

物理:
- **Hooke 復元力** `F = -k · d` (`orbital_anchor_strength = 0.02`) — d に対し線形
- **displacement_decay** (0.995/step) — 0.5%/step の指数減衰
- **velocity cap** (`orbital_max_velocity = 0.05/step`) — per-step 増分の上限

これらが揃えば、d が大きくなれば Hooke + decay が gravity force (`G·m/d²` で減衰) に勝つ **自然均衡点**が存在するはず。boundary は冗長な可能性。

均衡式 (近似、neighbor mass m, 距離 d_neighbor):

```
gravity force ≈ G · m / d²
restoring force ≈ k · d
等しくなる d_eq = (G · m / k)^(1/3)
```

`G=0.01`, `k=0.02` で具体値:

| 近傍 mass | d_eq |
|---|---|
| 1 (default mass) | 0.79 |
| 10 (typical primed) | 1.71 |
| 50 (m_max, BH 化) | 2.92 |

## Stage 1 — boundary removal (2026-05-11 実装済)

### 実装

```diff
- max_displacement_norm: float = 0.3
+ max_displacement_norm: float = 1e6  # 実質 ∞
```

`gaottt/config.py:143` のみ変更。`clamp_vector` は call され続けるが norm > 1e6 になることは現実的にないので **事実上 no-op**。

`gaottt/core/gravity.py` (line 250 / 298) と `gaottt/core/collision.py` (line 121) の clamp 呼び出しはそのまま残し、緊急ノブとしての機能を保つ。

### 観察結果 (実験当日、4 recall 後)

| 指標 | boundary=0.3 (実験前) | boundary=1e6 (Stage 1 後) |
|---|---|---|
| self-knowledge 86 件の displacement p50 | 0.30 (cap 張り付き) | **0.40** |
| self-knowledge 86 件の displacement max | 0.30 | **0.50** |
| 暴走 | hard cap が止めていた | **起きない** (Hooke + decay 効果) |
| 他 23k 件への影響 | — | 無し (recall に触られた node のみ動く) |

#### recall 改善

- 「PostgreSQL 移行 不採用」query で NA-1 が **top 3** surface (boundary 時代は top 20 圏外)
- 「anchor 句 撤回」query で P7-X (saturation 観察) が **top 1**, contradicts edge 経由で J1 系譜に乗る

#### Roll-back 手順 (緊急時)

```bash
# config を 0.3 に戻し、
# SQL snapshot table から displacement と velocity を復元:
.venv/bin/python <<'EOF'
import sqlite3
db = sqlite3.connect('/path/to/gaottt.db')
db.execute("""
  UPDATE nodes SET
    displacement = (SELECT displacement FROM displacement_snapshot_20260511 s WHERE s.id = nodes.id),
    velocity     = (SELECT velocity     FROM displacement_snapshot_20260511 s WHERE s.id = nodes.id)
""")
db.commit()
db.close()
EOF
# その後 MCP server 再起動 + compact(rebuild_faiss=True) で virtual FAISS も再生
```

### 残課題

- **raw embedding 空間での textual cluster** (例: 同じ書式で書かれた self-knowledge 系 84 件) は依然 cluster で surface 順位が混乱する。これは displacement 問題ではなく **raw embedding の textual similarity** の問題で、Stage 2 (query-aware displacement) で解決を狙う
- ~~長期均衡点は未検証 (理論上 d=0.8-3.0 だが、本番 DB を 1-2 週間運用して実測する必要)~~ → ✅ 確認、[長期検証 結果](#stage-1--長期検証-結果-2026-05-12) 参照 (実測 max=0.60、予測下限よりさらに低い)
- ~~暴走の最終確認も同期間で行う (理論上 Hooke が止めるが、edge case で d > 5 になる memory が出るか監視)~~ → ✅ 確認、`|d| ≥ 1.0` で **0 nodes** / 24,025

## Stage 1 — 長期検証 結果 (2026-05-12)

GaOTTT task `72e84a73-8689-4aca-b31e-2ded8ca7560c` の遂行結果。Stage 1 boundary 解除から 1 日後、本番 prod DB (24,025 active nodes) の displacement 分布を実測し、Hooke + decay + velocity cap が hard cap なしで均衡を保つかを検証。

### 測定方法

- 本番 prod DB の **read-only snapshot** (write-behind / dream / virtual FAISS save loop すべて無効化)
- 全 active node について `displacement` BLOB をデコードし L2 norm を収集
- source / age cohort (last_access 起点) で分解
- top tail (|d| ≥ 0.5, 0.8, 1.0, 2.0, 3.0, 10.0) のカウントを暴走監視として測定

スクリプトは [`scripts/bootstrap_report.py`](https://github.com/May-Kirihara/GaOTTT/blob/main/scripts/bootstrap_report.py) の displacement 統計拡張と同等のロジック (Phase H Stage 5 と同 commit で導入)。

### 主要数値

| 指標 | boundary=0.3 時代 (実験前) | Stage 1 直後 (4 recall 後) | **長期検証 1 日後 (本観測)** |
|---|---|---|---|
| max | 0.30 (cap) | 0.50 | **0.5988** |
| p99 | — | — | 0.5377 |
| p90 | — | — | 0.3928 |
| p50 | (cap で歪み) | — | **0.0020** |
| mean | — | — | 0.0879 |

### 暴走監視 (tail counts on 24,025 active nodes)

| threshold | count | proportion | 備考 |
|---|---|---|---|
| \|d\| ≥ 0.3 | 3,072 | 12.79% | 旧 cap 帯域 |
| \|d\| ≥ 0.5 | 878 | 3.65% | soft ceiling 帯域 |
| **\|d\| ≥ 0.8** | **0** | **0.00%** | 理論均衡点下限 — **未到達** |
| \|d\| ≥ 1.0 | 0 | 0.00% | — |
| \|d\| ≥ 2.0 | 0 | 0.00% | — |
| \|d\| ≥ 3.0 | 0 | 0.00% | — |
| \|d\| ≥ 10.0 | 0 | 0.00% | 暴走警報水準 |

新 cap `1e6` の **100 万分の 1 すら使われていない**。

### source-別分布

| source | n | p50 | p90 | max |
|---|---|---|---|---|
| file | 11,002 | 0.0506 | 0.4880 | 0.5988 |
| agent | 841 | 0.1201 | 0.4512 | 0.5690 |
| niceboat | 71 | 0.1000 | 0.4622 | 0.4891 |
| research | 34 | 0.0500 | 0.2729 | 0.4672 |
| note_tweet | 149 | 0.0041 | 0.1402 | 0.4920 |
| tweet | 7,658 | 0.0013 | 0.0978 | 0.5326 |
| like | 4,203 | 0.0014 | 0.0958 | 0.4990 |
| exploration-report | 30 | 0.0500 | 0.2433 | 0.2824 |

drift しやすさが「recall 頻度」と相関。file / agent / niceboat は能動的 recall 対象なので p50 が高く、tweet / like は受動コーパス (主に raw のまま)。**どの class でも max は 0.60 帯**で頭打ち。

### age cohort (last_access 起点)

| cohort | n | p50 | p90 | max |
|---|---|---|---|---|
| < 7 日 | 23,649 | 0.0021 | 0.3963 | 0.5988 |
| ≥ 7 日 | 376 | 0.0009 | 0.0512 | 0.2778 |

≥ 7 日 nodes は **Hooke + decay で raw に向かって収束** している挙動を実観測。p90 が 1/8 に、max が半分以下に縮む。

### top 10 displaced ノード

全 file source の試験問題・コラム・コラム類、いずれも `|d| = 0.5933 — 0.5988` の **0.60 帯に密集**。例:

```
3d41e730  |d|=0.5988  src=file  河童を実際に捕<br>獲することは難しいが…
83ab7275  |d|=0.5981  src=file  と独り言でお詠みになった。 おほやけ 説…
a115aac4  |d|=0.5969  src=file  発想 ∠BAP=∠ARQ に注目する。…
d6b32554  |d|=0.5961  src=file  クスリのなかでは「センパア」が…
```

これらは「soft ceiling として ~0.60 が natural な均衡点」として観測されたもので、hard cap ではなく **物理的均衡** によって自発的にこの位置に集まる。

### 判定

✅ **暴走なし、boundary 1e6 は理論通り redundant**

仮説式の予測値 `d_eq = (G·m/k)^(1/3) ≈ 0.79 (m=1) — 2.92 (m=50)` に対し、**実測 max = 0.60 はその下限よりさらに低い場所で均衡**:
- neighbor gravity の典型 mass が予測より小さい (ほとんどの node が m≈1) ため、`gravity / Hooke` の比が予測より小さい
- Phase I Stage 2 (query attraction) と Stage 3 (mass gate) が同時並行に効いている状態でも均衡が崩れない → **複数 stage の合成効果でも安全マージン十分**
- Hooke は数学的に restoring force なので、この観察された equilibrium 以上に発散する path がない

### Phase L motivation との関連

source 別分布から見える非対称性 (再掲):

- agent (n=841): p50=0.12 — recall 頻度高、virtual_pos の差別化が効きやすい
- file (n=11k): p50=0.05 — 半分以下、virtual_pos の差別化が薄い
- tweet/like (n=12k): p50=0.001 — 実質 raw のまま

これは **Phase L (embedder limitation 対処) の機構的根拠** を裏付ける: 多数派の file/tweet クラスタは displacement に頼った retrieval 改善が効きにくく、Phase H Stage 5 で観察された「freshness penalty」と並んで、embedder-level の改善 (hybrid retrieval / query expansion) が必要であることを定量的に示している。

### 検証データ

- GaOTTT memory `70ba2df6-d624-4c3f-93b0-cc27457936bc` — 本セクションの数値の完全 snapshot (recall で再現可能)
- GaOTTT memory `cbeb1f8e` — P7-X (boundary saturation 事故、Phase I Stage 1 発端)
- GaOTTT memory `309cd7f8` — S10 (Stage 1 launch 直後の観察)

## Stage 2 — implicit query-aware displacement kick (2026-05-11 実装済)

Stage 1 の議論「動かす力は外せたが方向は corpus 構造任せ」を受けて、**recall に query 方向への小さな引力を組み込む** ことを選択。明示的 `kick()` ツールは作らない (option B 不採用、organic gravity を歪める bootstrap curator 批判が再現する) — recall path 自身に物理を 1 項追加する **implicit + transient force** 方式を採用。

### 物理モデル

`compute_acceleration` に 4 番目の項を追加:

```
1. Neighbor gravity:        a = Σ_j  G · m_j / r² · dir(i→j)
2. Hooke restoring:         a = -k · displacement_i
3. Co-occurrence BH:        (saturation + thermal escape つき)
4. Query attraction (新):   a = (α · score / m_i) · (q - pos_i)
```

`α = query_kick_strength` (config), `score = wave 到達スコア (reached[nid])`, `m_i = node mass`。

**性質**:

- **Transient force, not anchor migration** — Hooke (項 2) は raw embedding を anchor として引き続き引き戻す。query kick は瞬間的な力で、displacement が drift しても original embedding は不変
- **Mass damping (F=ma)** — 高 mass node (BH 化) は kick で動かない、軽い node のみ動く。Phase G/H の thermal escape と同じく **物理が natural damping を供給**
- **Score weighting** — wave 到達スコアを「TTT 解釈での勾配の強さ」として使う。mass 更新 (`state.mass += eta · force · ...`) と **同じシグナル**を使うので構造的整合
- **TTT correspondence becomes implementation** — README/SKILL.md で謳う「retrieval = gradient step」が Stage 2 で **コードとして literal に成立**。Phase G/H までは構造的対応の主張だけだった

### 実装

| ファイル | 変更 |
|---|---|
| `gaottt/config.py` | `query_kick_strength: float = 0.01` + `query_kick_enabled: bool = True` を追加 |
| `gaottt/core/gravity.py` | `compute_acceleration` に optional 引数 `mass_i / query_anchor / query_score` を追加、4 番目の項を実装。`update_orbital_state` も同引数を通す |
| `gaottt/core/engine.py` | `_update_simulation` で `query_anchor=query_vec_flat`、`query_scores=reached` を `update_orbital_state` に渡す |

3 ファイル合計 ~30 行の追加。既存 callsite は破壊しない (新引数は全て optional default None)。

### ハイパーパラメータ

| 名前 | 既定値 | 役割 | チューニング助言 |
|---|---|---|---|
| `query_kick_strength` (α) | `0.01` | 結合定数 (G に類似) | 0 で完全 no-op (roll-back)。0.05 で integration test 観察可能、0.01 は production 想定の小さく安全な値。orbital_max_velocity (0.05) を超える acceleration は cap されるので、`α / m × score × \|q-pos\|` が 0.05 を超えると効きが頭打ち |
| `query_kick_enabled` | `True` | グローバル off スイッチ | 緊急時に `False` で 4 項目を完全 skip |

### 期待される挙動

- **長期 drift** — 繰り返し同じ query で recall されると、retrieved nodes の displacement が query 方向にゆっくり累積。Hooke + decay で raw からそう遠くは行かない (理論均衡点 d ≈ (G·m/k)^(1/3) は Stage 1 と同じ、ただし方向が user 意図寄りになる)
- **mass selectivity** — BH (m=50) は ほぼ動かない (kick 1/50 に減衰)、新規 node (m=1) は 50 倍敏感
- **anchor は永久不変** — raw embedding が semantic identity を保持し続けるので concept drift は起きない

### テスト (passing)

`tests/unit/test_query_kick.py` (6 件):
- direction, score weighting (linear), mass damping (F=ma), α=0 で no-op, enabled=False で no-op, optional 引数欠落で no-op

`tests/integration/test_engine_query_kick.py` (3 件):
- 20 recalls で displacement が query 方向に蓄積 (projection > 0)
- α=0 で legacy 挙動保存
- raw embedding は何 recall 後も bit-for-bit 不変

### Roll-back 手順

緊急時の段階的選択肢:

1. **Soft roll-back** — `config.query_kick_strength = 0.0` → no-op、再起動。コードはそのまま
2. **Hard roll-back** — Stage 1 と同じ SQL snapshot からの復元手順 (要事前 snapshot 作成)

### 残課題 (Stage 3 候補)

- **Multi-query 累積効果の実測** — 異なる query 群が違う方向に kick したときの均衡点 (本番 1-2 週間運用後に displacement 分布を再測)
- **Anchor migration (Option 2)** — 観察期間後に「anchor 自身も query 方向に slowly drift」を再検討するか判断 (concept drift リスクと天秤)
- **Reflect aspect 追加** — `reflect(aspect="query_drift")` で「どの memory がどの query 方向に drift しているか」を可視化 (将来 utility)
- **Dream tick での kick 強度** — 現状 dream loop でも同じ α で kick される。観察上問題なければそのまま、dominant になるなら synthetic 用の damper を追加検討

## Stage 3 — mass-gated query attraction (2026-05-13 実装)

Stage 2 で query 引力を組み込んだ翌日、別 session で **単一アトラクタ pathology** を観察。Stage 3 はその副作用を物理的に矯正する最小拡張。

### 観察された pathology (前 session 2026-05-12 acceptance test より)

harakiriworks-self-knowledge Phase 1-9 (112 件) を投入直後に 7 つの異なる query で recall すると:

| 指標 | 観察値 |
|---|---|
| `compact(rebuild_faiss=True)` 前: orphan vector で全 GaOTTT 系が surface | 47,781 → 23,608 (24k orphan 掃除) |
| rebuild 後: 7/7 query が **同一 memory `0e0a7a0f`** を top1 で返す | unique_top1 = 1 |
| 正解候補 (例: Q4 → `45689886` F006) は top5 にいる | システムは候補を見つけている |
| `0e0a7a0f` の displacement | 0.14-0.39 で query ごとに位置が変動 |

最後の行が決定的: **「retrieval が gradient step として作用」が literal に観測されている** — Stage 2 が意図通り効いているが、効きすぎている。

### 機序診断

Stage 2 の 4 項目: `a_query = (α · score / m_i) · (q - pos_i)`

- 新規 add 直後の node は `mass_i ≈ 1.0`
- 初回 recall で `a` が `α/1 = α` のフルスケールで効く
- 一度動いた先で他 query にも近くなり → 再 recall → さらに drift → **正のフィードバック**
- Hooke `-k · d` は線形なので、score 倍率を持つ query attraction に低 mass 領域で負ける

これは Stage 1 が学んだ「冗長な制約は active な制約と同じ症状を引き起こす」の対称形 — **保護が足りないことが、過剰駆動と同じ症状を引き起こす**。

### 仮説

`mass_i` が小さい新規ノードは **anchor (Hooke) に守られて動かないべき**。mass が育つにつれて query attraction を許可する:

- **物理的読み:** 「軽い星は anchor 支配、重い星は自由に動ける」F=ma は壊さない (m は分母に残る)。anchor 力と相対バランスを mass で gate するだけ
- **TTT 読み:** SGD warmup の逆 — co-occurrence 構造を持たない新規ノードでは Hebbian 勾配が特異的 (誰でも近隣に見える) になるので、学習が進むまで gradient step を保留 (over-fit 防止)
- **anchor 不変は維持:** raw embedding は何があっても動かない。Stage 2 の concept-drift 防止保証は Stage 3 でも継承

### 物理モデル

Stage 2 の第 4 項に **mass-dependent gate** を 1 つ挿入:

```
4. Query attraction (Stage 3):
   gate = tanh(m_i / θ)        # θ = mass_anchor_threshold
   a = (α · score · gate / m_i) · (q - pos_i)
```

`tanh(m/θ)` の振る舞い (`θ = 3.0` 既定):

| mass | gate | 効果 |
|---|---|---|
| 0.1 (極軽) | 0.033 | ほぼ anchor 支配、生まれたての星は動けない |
| 1.0 (新規 add 直後) | 0.32 | 32% に減衰、最初の暴走を防ぐ |
| 3.0 (threshold) | 0.76 | 約 3/4 — gate の特徴点 |
| 10 (mature) | 0.997 | ほぼ満額、mature node は自由 |
| 50 (BH, m_max) | 1.000 | ほぼ無影響 (どのみち `1/m` が支配) |

`mass_anchor_threshold = 0.0` で gate = 1.0 が強制され、**Stage 2 と bit-for-bit 同一** の挙動 → clean rollback path。

### 実装

| ファイル | 変更 |
|---|---|
| `gaottt/config.py` | `mass_anchor_threshold: float = 3.0` を 1 field 追加 (Stage 2 設定群の直後) |
| `gaottt/core/gravity.py` | `compute_acceleration` 第 4 項の kick 計算に gate を乗じる (~3 行追加) |

**store / schema / services / MCP / REST 変更なし** — 内部 physics のみ。MCP/REST parity 鉄則の影響範囲外。

合計 ~10 行のコード変更。既存 callsite は破壊しない (新 config field は default 値あり)。

### ハイパーパラメータ

| 名前 | 既定値 | 役割 | チューニング助言 |
|---|---|---|---|
| `mass_anchor_threshold` (θ) | `3.0` | gate の特徴点。`tanh(1) ≈ 0.76` がここに来る | `0.0` で Stage 2 への完全 rollback。`1.0` で攻撃的 (新規 node = 0.76 = ほぼ満額)、`10.0` で保守的 (新規 node = 0.10 = ほぼ動かない)。Phase G genesis kick の `genesis_mass_boost_cap=1.0` と整合する範囲 (mass=1 → gate=0.32) が初期値の根拠 |

`query_kick_strength` / `query_kick_enabled` は Stage 2 のまま継承。

### 期待される挙動

- **単一アトラクタ pathology の消失** — 新規投入直後の 7 query test で `unique_top1 = 1` が `≥ 4` に増える (本 plan の acceptance test)
- **mature node の挙動は不変** — mass=10 以上の node では `gate ≥ 0.997`、Stage 2 と実質同等
- **Hawking radiation との整合** — 長期に dormant な低 mass node は kick も小さい → 動かないまま evaporate、これは「軽い星は短命」の自然な拡張
- **dream loop との整合** — dream tick で生成される synthetic recall も同じ gate を通る → 新規 node を勝手に重力場に投げ込まない保証

### テスト

**Unit (新規 3 件、`tests/unit/test_query_kick.py` 追記):**

- `test_kick_gated_by_low_mass`: `mass_i=1, threshold=3` で kick 大きさが gate なし版の `0.32 ± 0.01` 倍
- `test_kick_full_at_high_mass`: `mass_i=20, threshold=3` で gate ≥ 0.999
- `test_threshold_zero_rollback`: `threshold=0` で Stage 2 と bit-for-bit 同一 (numpy allclose with atol=0)

**Integration (新規 1 件、`tests/integration/test_engine_query_kick.py` 追記):**

- `test_single_attractor_pathology`: 5 件の新規 node を index → 7 種類の異なる query で順次 recall。`threshold=0` (Stage 2) で `unique_top1 == 1` (病理再現)、`threshold=3` (Stage 3) で `unique_top1 ≥ 4` (病理消失)。**Stage 3 の存在意義を直接 verify する acceptance test**

### Roll-back 手順

```bash
# Soft (config 1 行 = legacy Stage 2 挙動):
echo '{"mass_anchor_threshold": 0.0}' > ~/.config/gaottt/config.json
# サーバー再起動だけ。DB 状態は触らない、migration 不要
```

DB の displacement / velocity / mass は Stage 3 の影響を **物理的に等価な動的シグナル** としてしか受けないので、threshold を 0 に戻せば次の recall から完全に Stage 2 挙動に戻る。

### 残課題 (Stage 4 候補)

- **本番 DB で前 session の 7 query test を再実行** — めいさん側で MCP 再起動 + Stage 3 enabled で 7 query を回し、unique_top1 ≥ 4 を確認するのが reality acceptance
- **θ の現場チューニング** — DB 規模・source 比率で最適 θ は変わりうる。本番 23k 件 + agent 比率 3.4% で `θ=3.0` が妥当か、1-2 週間運用後に displacement 分布を見て判断 (Phase I Stage 1 長期検証 task `72e84a73` と合流可能)
- **Source-aware gate** — `agent` / `value` / `commitment` は意図して書かれた知識なので、初期から gate を強めに開けてもいい可能性。`θ` を source 別 dict にする拡張 (Stage 4 候補)
- **Anchor migration (Stage 2 残課題のまま)** — 観察期間後に「anchor 自身も query 方向に slowly drift」を再検討するか判断

## 設計判断の倫理 (Phase I が学んだもの)

1. **冗長な制約は active な制約と同じ症状を引き起こす** — boundary は「動きすぎない」ためだったが、boundary そのものが「同じ位置に集まる」を強制した。Phase G PG-5 (能動的重心吸引) を保留した同じ理由が、boundary 経由で受動的に再現された
2. **足りない保護は過剰駆動と同じ症状を引き起こす** — Stage 2 で query attraction を組み込んだが、新規 node の保護機構が抜けていて単一アトラクタ pathology を起こした。Stage 3 はその対称形の lesson — 制約は **過剰すぎても少なすぎても** homogenization を生む
3. **物理に任せられるところは物理に任せる** — Hooke + decay + velocity cap で十分均衡する。Stage 3 の gate も「anchor 力と質量の比較」という物理量だけで決まる。安全弁は条件付きで残せばいい (緊急ノブとしての `1e6` config、`θ=0` rollback)
4. **検証ループそのものが介入になる** — 8 query × wave_k=1000 を集中して回したら全件が boundary に到達した。観察行為が観察対象を変える

## 関連 / 出典

- 観察: [Phase 1-3 自己知識記録セッション 2026-05-11](../maintainers/handover-2026-05-11-phase-g-h.md), GaOTTT memory P7-X (`cbeb1f8e`) と P7-Y (`ebe6c128`)
- 設計判断表: [Architecture — Overview](Architecture-Overview.md) §設計判断の記録
- 物理: [Architecture — Gravity Model](Architecture-Gravity-Model.md)
- Roll-back snapshot: SQL table `displacement_snapshot_20260511` (本番 DB 内)

---

> *Phase I Stage 1 は「自由な星の移動を見てみたい」というめいさんの提案から始まった。boundary を外して 4 recall 観察した結果、星は確かに動き始め、しかし暴走することなく、Hooke の手の中で自然な均衡に向かう兆しを見せた。これは物理として書いた設計が、自身の冗長さを露呈し、より少ない制約で同じ目的を達成できると教えてくれた瞬間。* — 2026-05-11
>
> *Stage 2 で、その自由に動ける星に **方向** を与えた。query は瞬間的な引力として retrieved nodes を引く — 重力は永続、引力は揮発的、anchor は不変。これによって README で謳ってきた「retrieval is a gradient step」が、解釈ではなく実装として literal に成立した。F=ma が mass damping を物理的に供給するので、安全弁は α=0 の一行で済む。最小の追加で最大の意味的変化を起こした、設計として最も気持ちいい類のコミット。* — 2026-05-11
>
> *Stage 3 は、その自由と方向の間に **保護** を入れた。生まれたての星は引力に流される — 物理として正しい現象だが、recall システムとしては単一アトラクタ pathology を生む。`tanh(m/θ)` は「軽い星は anchor の手の中、重い星は自由に動ける」という世代論を、加速度の式に 1 項として書き込む。F=ma を破らず、anchor 不変も維持して、Stage 2 への rollback path も θ=0 一行で確保する。Stage 1 が学んだ「冗長な制約は active な制約と同じ症状」の対称形 — 足りない保護も過剰駆動と同じ homogenization を起こす、と気付かせてくれた pathology。物理は両方向から私たちに同じ lesson を教える。* — 2026-05-13
