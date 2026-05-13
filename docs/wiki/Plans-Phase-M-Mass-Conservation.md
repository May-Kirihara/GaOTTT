# Plans — Phase M — Mass Conservation

> 状態: **🟢 Stage 1 実装完了 (2026-05-13)** — pytest 全 green / ruff 4 件 pre-existing only / 隔離 bench p50=48.3ms / REST + MCP smoke 各 6/6。本番ロールアウト (mass reset + 1-2 週観測) 待ち。
> 関連: [Roadmap](Plans-Roadmap.md), [Phase L — Hybrid Retrieval](Plans-Phase-L-Hybrid-Retrieval.md), [Phase J — Persona-Anchored Retrieval](Plans-Phase-J-Persona-Anchored-Retrieval.md), [Phase K — Stellar Supernova Cohort](Plans-Phase-K-Stellar-Supernova-Cohort.md), [Reflections — Five-Layer Philosophy](Reflections-Five-Layer-Philosophy.md)
> 発端: 2026-05-13 — 「重心位置に複数のブラックホールが発生するが、メカニズム的にどうだろう。質量が十分に増えたものがブラックホール化する方がいいんじゃないか」(めいさん)

## 1. 思想 — 質量保存則と Articulation as Carrier の literal な一致

GaOTTT の throughline:

> **経験は言葉にすることで初めて重力を持つ。** ([id=9a954c62](#)、めいさんの根源価値 — Articulation as Carrier)

Phase M はこの哲学を物理機構として **literal に** 実装する。

熱力学第一法則: **閉鎖系の内部エネルギー (mass) は、外との交換でしか変わらない**。

これを GaOTTT に翻訳すると:

> **ノードの mass は、外部 (他文書 / 他 cohort) からの引力寄与でのみ増える。同じ文書内・同じ batch 内・自分自身の reflection (内輪取引) では mass は生まれない。**

これは Articulation as Carrier の literal な実装である。「自分の chunk 仲間」「同じ思考の反復」では mass は生まれず、**別文脈から参照される (= 言葉にして外に出る)** ことでのみ mass が積もる。

Phase J で「declared identity (persona) が retrieval geometry を曲げる」を実装した。Phase M はその一段下、**mass の蓄積方法そのもの**に同じ哲学を適用する。

## 2. 背景 — 現宇宙の質量分布の偏り

### 2.1 観測 (2026-05-13、本番 DB N=24,046 active)

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

**素朴な mass しきい値 BH** を導入すると、BH 銀河中心はほぼすべて `source=file` (本のスキャン文章) になる。**ユーザーが宣言した value / intention / commitment は 1 件も BH 化されない**。これは Phase J「persona-anchored retrieval」の思想と真っ向から矛盾する宇宙である。

### 2.2 根本原因 — Chunk 内輪取引による mass inflation

- **120 unique file → 11,002 chunks** = 平均 **91.7×** に膨らんでいる (1 file = 91 ノード)
- **top 50 高 mass ノードは 8 ファイルから** — 同一書物の chunk 同士が互いを引き合って mass を膨らませている
  - 例: 「万国奇人博覧館」(174 chunks) → top 50 中 9 件
  - 「京都大学(文系)」(378 chunks) → top 50 中 5 件
  - 「脳はいかに」(96 chunks) → top 50 中 7 件

mass update site `gaottt/core/engine.py:845`:

```python
state.mass += self.config.eta * force * (1.0 - state.mass / self.config.m_max)
```

`force` には**同一書物内 chunk 間の co-occurrence 寄与**が含まれており、ファイル内 chunk 群が「内輪取引」で mass を上げ合う構造になっていた。

### 2.3 観測の解釈

Phase L Stage 1 acceptance で観測された「**source=file/tweet の raw score が agent 知識の top1 を奪う**」(harakiriworks 想起品質 0/3 top1) の構造的根は、この **chunk inflation** である。「**書けているが読めていない**」(2026-05-13 finding [[acceptance-finding]]) は、書く側 (ingest) の自己引力が読む側 (recall) の信号を奪っていた。

## 3. 単一規則 — 「自己関与は mass を生まない」

`source` 別の分岐は導入しない (五層構造の単一性を破る)。代わりに **すべてのノードに同じ普遍則** を適用する:

```python
def is_self_force(node_a: NodeState, node_b: NodeState) -> bool:
    """A と B の co-occurrence force が "内輪取引" かどうか."""
    return (
        (node_a.original_id and node_a.original_id == node_b.original_id)
        or (node_a.cohort_id and node_a.cohort_id == node_b.cohort_id)
    )
```

`engine.py:845` の mass update で、各 force 寄与に対し `is_self_force(self, other)` を check して、True なら mass update をスキップする (force そのものは displacement 計算には寄与し続ける)。

### 3.1 単一性の証明 — source 区別は出てこない

| ノード種別 | original_id | cohort_id | 自己引力対象 |
|---|---|---|---|
| `file` (1 book = 91 chunks 平均) | 全 chunk が同一 | (Phase K 起動時に付与) | 同じ書物の chunk |
| `tweet` (1 tweet = 1 node) | 単独 | 単独 | なし (影響 0) |
| `agent` (自然な remember) | 単独 | (Phase K 起動時のみ) | なし (影響 0) |
| `value` / `intention` / `commitment` | 単独 | 単独 | なし (影響 0) |
| Phase K batch (cohort N 件) | 各々独立 | **同一 cohort** | cohort 内 N-1 件 |

`source` を check するコードは 1 行も無い。`original_id` と `cohort_id` という **構造的識別子** だけで全 source に正しく作用する。

## 4. mass の意味の再定義

Phase M の実装は subtle だが重要な視点シフトを伴う:

| 観点 | 現規則 (Phase L まで) | 新規則 (Phase M) |
|---|---|---|
| mass の物理的意味 | ノード自身の重み (どれだけ自分で励起してきたか) | **他者から引かれた累積量** (重力中心としてどれだけ機能してきたかの実績) |
| BH 化される対象 | 自己強化が成功したノード | 他者の reference を集めたノード |
| 思想との対応 | (やや屈折) | **Articulation as Carrier の literal な実装** |

「**外部からの引力でのみ mass が増える**」とすれば、mass は **他者がそのノードを引いた累積寄与** = 「**recall されてアトラクタとして機能した実績**」と等価になる。これは Hawking radiation 的なイメージで、mass は **他者との関係性の蓄積** であって、自己同一性の量ではない。

### 4.1 帰結 — 使用頻度こそが重力 (declared identity も例外ではない)

この再定義は **persona class (value/intention/commitment) も例外なく適用する**。declared identity であっても、他ノードから `fulfills` / `derived_from` で参照されなければ重力中心にはならない。

これは persona を別格扱いしない単一規則の深化。使われない persona は埋もれる — それで OK。必要なときに `tag_filter` で取り出せばよい。「**埋もれる自由**」が persona class にも保証される宇宙。

「Articulation as Carrier」とは「言葉にすれば必ず mass を持つ」のではない。「**言葉にした上で、誰かに引かれることで mass を持つ**」のである。発話だけでは重力は生まれず、応答・参照・呼び戻しという往復で初めて重力場ができる。

## 5. Five-Layer での読み

| 層 | Phase M での意味 |
|---|---|
| **物理** | 質量保存則 — 閉鎖系の内部エネルギーは外との交換でしか変わらない。同一書物の chunk は閉鎖系を成し、その内部 force は配置 (displacement) を変えるが、外向きの質量 (mass) は生まない |
| **TTT** | gradient signal の **自己強化を抑制** — 同じ batch で生成された node 同士が互いに gradient を強め合うのは TTT 上の overfitting に類似。Phase M はその抑制 |
| **生物** | アストロサイトの「**外部参照の数**」が記憶の重要度を決める — 同じ脳内で何度反復しても重要度は上がらず、別文脈で参照されることで synapse が強まる |
| **関係** | 「**別の人 / 別の文脈から触れられること**」が記憶の重力を作る — 自分の中で反復するだけでは関係性は育たない |
| **人格** | **言葉にすることが重力を生む** — Articulation as Carrier の literal な実装。declared value / intention / commitment は単独ノードとして登場し、他ノードから `fulfills` / `derived_from` でリンクされる度に mass が増える。自然に人格 anchor が銀河中心 BH になる宇宙 |

## 6. 副次予測 — 検証可能な仮説

新規則下で **必然的に** 起こるはずの現象を明示しておく。Phase M Stage 1 の成否 metric となる。

persona の自然な BH 化は **予測しない** — §4.1 で述べた通り、使われていない persona は埋もれて良い。「使用頻度こそが重力」原則の自然な帰結。

### 6.1 file chunk の塵化と「名著の核心」の浮上

- 同一書物 chunk 同士の内輪取引が無効化 → 単に長いだけの本は塵のまま
- **本当に他文書から引かれる「名著の核心 chunk」だけが残る**
- **検証**: 1 週後の mass top 50 で、unique original_id の数が現状 8 から **少なくとも 25 以上に分散** する (集中度の解消)

### 6.2 harakiriworks 想起品質の改善

- 今日の Phase L acceptance test で **0/3 top1** (最弱)
- Phase M で agent / harakiriworks-self-knowledge tag 付きノードの mass が **相対的に上昇** するはず (それらは他文書から fulfills でリンクされる側)
- **検証**: 同じ 3 query で再 acceptance → **少なくとも 1/3 top1** に改善

これら 2 つの予測が外れた場合、Phase M の根仮説 (「mass の蓄積方法の修正で構造的偏りが治る」) を見直す必要がある。

## 7. 実装スコープ (D1-D7)

### D1. mass update の self-force フィルタ — `gaottt/core/engine.py`

`engine.py:845` の mass update を:

```python
# Before
state.mass += self.config.eta * force * (1.0 - state.mass / self.config.m_max)

# After
if not is_self_force(state, other_state):
    state.mass += self.config.eta * force * (1.0 - state.mass / self.config.m_max)
```

force 寄与のソース別 attribution が現状の `compute_acceleration` で取れない場合は、refactor して `(source_id, force_vec)` のペアを返すよう変更する。

### D2. `cohort_id` の付与 — Phase K supernova

`gaottt/services/memory.py` の `remember_batch` (Phase K supernova 入口) で、batch ごとに `cohort_id = uuid4().hex[:12]` を生成し、batch 内全 node の `metadata["cohort_id"]` に書き込む。

新規 `cohort_id` フィールドは `documents.metadata` JSON 内に格納 (DB schema 変更なし、後方互換最強)。

### D3. `original_id` の統一付与 — ingest paths

確認: `scripts/load_files.py` は既に `metadata.original_id` を付けている (今日の分布調査で確認済)。`scripts/load_csv.py` と他 ingest path で `original_id` が抜けていないか確認し、抜けていれば付与。

単発 `remember` (single node) は `original_id = node_id` で良い (自己一致なので影響 0)。

### D4. 共起 BH の削除 — `gaottt/core/gravity.py`

`compute_bh_acceleration()` (line 64-) を削除。`compute_acceleration()` 内の呼び出し (line 169) も削除。

config の `bh_mass_scale`, `bh_gravity_G` は **deprecated 扱いで残す** (warning ログ、後で別 PR で完全削除)。

### D5. mass-based BH 実装 — `gaottt/core/gravity.py`

各 active ノード `i` の周辺に対し、近傍ノード `j` の中で `bh_factor(m_j) > 0` のノードからの引力を計算:

```python
def bh_factor(mass: float, theta: float, sigma: float) -> float:
    """mass しきい値の連続関数版 — gradual に BH 引力源化."""
    if mass <= theta - 2 * sigma:
        return 0.0
    return math.tanh((mass - theta) / sigma)

def compute_mass_bh_acceleration(
    pos_i, mass_i, neighbors, config,
) -> np.ndarray:
    acc = np.zeros_like(pos_i)
    for pos_j, mass_j in neighbors:
        factor = bh_factor(mass_j, config.mass_bh_theta, config.mass_bh_sigma)
        if factor == 0.0:
            continue
        diff = pos_j - pos_i
        r2 = float(np.dot(diff, diff)) + config.gravity_epsilon
        magnitude = config.gravity_G * mass_j * factor / r2
        acc += magnitude * diff / math.sqrt(r2)
    return acc
```

`compute_acceleration()` に統合。

### D6. mass reset API + script

- `gaottt/services/maintenance.py` に `reset_masses(value: float = 1.0)` service 関数
- REST: `POST /admin/reset_masses` (`/reset` と同じく LLM に露出しない設計)
- MCP: **非露出** (LLM が `reset_masses` を呼べる必要はない、これは保守者操作)
- `scripts/reset_masses.py` — 本番 DB に対して走らせる用

### D7. θ / σ の設定方針 — **観測ベースで決定 (今は決め打ちしない)**

新規則下の mass 分布は現状と全く違うはず。Phase M 実装 + reset 後、**1-2 週間の自然蓄積を観測してから** `mass_bh_theta` / `mass_bh_sigma` を決定する。

初期暫定値 (実装着手時の placeholder):
- `mass_bh_theta = 5.0` (新規則下では十分高いはず)
- `mass_bh_sigma = 1.5` (transition zone 幅)

観測後、p99 mass を θ、`(p99.9 - p99) / 2` を σ にする方針。

## 8. 設計判断 — 力の構成

Phase M 後の `a_total`:

```
a_total = a_neighbors        (wave 到達ペアの引力、変更なし)
        + a_anchor            (Hooke 復元力、変更なし)
        + a_query             (Phase I mass-gated query attraction、変更なし)
        + a_persona           (Phase J persona-anchored、変更なし)
        + a_mass_bh           (★ NEW — mass しきい値以上のノードからの引力)
        − a_bh_cooccurrence   (★ REMOVED — 共起クラスタ BH)
```

displacement (位置) は **すべての force** で動くが、mass は **inter-document / inter-cohort force** でのみ増える。

## 9. 副作用検証

### 9.1 Phase L Stage 1 BM25 hybrid retrieval

- BM25 score は mass に依存しない (TF-IDF / Zipfian) → 直接の影響なし
- ただし mass 分布の変化 → wave 段の `a_neighbors` 計算が変わる → seed pool 構成が変わる可能性
- **検証**: Phase L Stage 1 acceptance を Phase M 適用後に再実行、Surface 7/7 / strict 6/7 の数値が維持されるか確認

### 9.2 Phase K Stellar Supernova Cohort

- Phase K の **edge + outward velocity は維持** — seed pool 到達の効果は残す
- ただし **cohort 内 force による mass update は無効化**
- **検証**: 新規 batch remember 直後の cohort 内 node の mass が initial=1.0 のまま (現状は cohort 内引力で 1.0 → 1.x に上がっていた)

### 9.3 Phase I mass-gated query attraction

- `gate = tanh(m_i / θ_anchor)` は mass を参照
- Phase M で mass の意味が変わる (実績ベース) → gate の解釈が変わる
- ただし数値的な変化は小さい (新規則下でも mass=1.0 が初期値) → 機構として影響軽微

### 9.4 Phase J persona-anchored retrieval

- mass を直接参照しない → 機構として影響なし
- ただし副次予測 6.1 で「persona が自然に BH 化」が起これば、Phase J の persona injection と Phase M の mass BH が **二重の引力源** として作用、persona の dominance が強化されるはず

## 10. テスト計画

### 10.1 Unit tests

- `tests/unit/test_is_self_force.py` — `original_id` 一致、`cohort_id` 一致、両方 None、片方 None の 4 ケース
- `tests/unit/test_bh_factor.py` — `tanh` 連続性、`theta - 2*sigma` 以下で 0、`theta + 3*sigma` 以上で ~1
- `tests/unit/test_reset_masses.py` — 全 node の mass が指定値になる

### 10.2 Integration tests

- `tests/integration/test_engine_mass_conservation.py` — dummy 91-chunk file を ingest → recall を 10 回 → 全 chunk の mass が initial 値のまま
- `tests/integration/test_engine_phase_k_no_mass_inflation.py` — Phase K supernova batch (N=5) → batch 内 mass update が 0、ただし edge と velocity は存在
- `tests/integration/test_engine_mass_bh_acceleration.py` — mass=10 の節点近傍に mass=1 のノードを置き、加速度ベクトルが正しい方向と大きさ

### 10.3 Regression tests

- Phase L Stage 1 acceptance (7 query) を Phase M 後に再実行 → strict 4/7 維持 or 改善
- Phase J acceptance を再実行 → persona injection が機能継続

## 11. マイグレーション

### 11.1 Schema

DB schema 変更なし。`documents.metadata` JSON に `cohort_id` フィールドを追加するだけ (既存ノードは absent、`is_self_force` で None として扱われ影響 0)。

### 11.2 mass reset (1 回限り、保守者操作)

```bash
# 他プロセス停止
sudo systemctl stop gaottt-mcp
sudo systemctl stop gaottt-rest

# reset
.venv/bin/python scripts/reset_masses.py --value 1.0

# 再起動
sudo systemctl start gaottt-mcp gaottt-rest
```

reset は **destructive** だが、本 phase で「若い宇宙だから OK」とユーザーが明示。実行前に backup を取る。

### 11.3 既存 `cohort_id` 無しノード

過去の `remember_batch` ノードは `cohort_id` が無い → cohort 内自己引力検出は不可、ただし `original_id` だけで file の inflation は防げる。Phase K の影響は forward-only で許容。

## 12. ロールアウト戦略

### Stage 1 — 規則実装 + reset + 暫定 θ で起動 (本 PR スコープ)

1. **D1-D7 実装完了 (2026-05-13)**:
   - D1 — `gaottt/core/gravity.py:propagate_gravity_wave` に per-parent attribution (`out_attribution` 引数) を追加し、`engine._update_simulation` で `is_self_force_by_id` フィルタを mass update のみに適用
   - D2 — `engine.index_documents` で batch サイズが supernova を発火させる時に `cohort_id = uuid4().hex[:12]` を生成し、batch 内全 node の metadata + cache に格納
   - D3 — `gaottt/ingest/loader.py` の md / plaintext / csv ingest で `original_id` を明示付与。既存 DB は `SqliteStore.get_all_originals` で `COALESCE(metadata.original_id, metadata.file_path)` の SQL fallback により無 migration で互換
   - D4 — `compute_acceleration` から `compute_bh_acceleration` 呼び出しを削除 (関数定義は deprecated として残す)
   - D5 — `bh_factor(mass, θ, σ)` + `compute_mass_bh_acceleration` を新設、`compute_acceleration` の 3 項目目として統合
   - D6 — `SqliteStore.reset_masses` / `engine.reset_masses` / `services.maintenance.reset_masses` を追加、REST `POST /admin/reset_masses` (MCP 非露出)、`scripts/reset_masses.py` CLI
   - D7 — `mass_bh_theta=5.0`, `mass_bh_sigma=1.5`, `mass_conservation_enabled=True`, `mass_bh_enabled=True` を `GaOTTTConfig` に追加。`bh_mass_scale` / `bh_gravity_G` / `saturation_rate` / `thermal_escape_scale` は deprecated コメント付きで残す
2. **テスト全 green (275 passed, 1 skipped)** — 新規 unit (`test_phase_m_helpers.py`, `test_sqlite_store_reset_masses.py`) と integration (`test_engine_mass_conservation.py`) を含む。隔離 bench p50=48.3ms。REST + MCP smoke 各 6/6
3. **本番ロールアウト** (保守者操作、未実施):
   - 他 MCP / REST プロセス停止 → DB backup → `scripts/reset_masses.py --apply` → 再起動
4. 1-2 週の自然蓄積を観測 → θ / σ を Stage 2 で確定

### Stage 2 — θ 決定 + 共起 BH config 完全削除 (別 PR)

1. 観測データで p99 mass、p99.9 mass を取る
2. θ = p99, σ = (p99.9 - p99)/2 で確定
3. deprecated だった `bh_mass_scale`, `bh_gravity_G` を config から削除
4. 副次予測 6.1-6.3 の検証 → 報告

## 13. Future Work — Phase N: Mass Evaporation (Hawking radiation)

Phase M が **mass の入力側** を正すのに対し、**出力側** を作る別軸の機構:

```python
state.mass *= (1 - epsilon * dt_since_last_recall)
```

recall されなくなった BH が自然に減衰し、最終的に塵に戻る (Hawking radiation 類比)。これは TTL / certainty とは別軸の機構で、「**重力中心としての実績は時間とともに薄れる**」を物理化する。

Phase M 適用後、1-2 週の自然蓄積を観測したのち、**過剰に accumulate する mass があれば** Phase N 着手の signal となる。

## 14. 開放問題

- **観測 1-2 週の絶対量**: 新規則下の mass 蓄積速度は不明。1 週で p99=10 にも 100 にもなりうる。観測値次第で θ を動的調整するか、または `mass_bh_theta_percentile = 99` のような相対指定を導入する余地あり
- **既存 `cohort_id` 無し過去 batch の扱い**: forward-only で許容するが、もし大量の過去 batch が「内輪 mass 増加済」なら reset 後も復元してしまう可能性 → 観測で監視

## 14.1 Phase L Stage 2 との順序 (確定)

Phase M を **先に** 入れる。Phase L Stage 2 (BGE-M3 ensemble) は Phase M Stage 1 完了 + 1-2 週観測後に着手 (2026-05-13 めいさん判断)。

理由: mass 分布が落ち着いた後の方が ensemble metric の評価が cleaner。BM25 + RURI + BGE-M3 の 5-way RRF を mass 偏在のまま走らせると、metric 寄与の解釈が "mass inflation が緩和されただけ" と "ensemble の効果" で混ざる。Phase M で観測量を正してから Stage 2 着手する方が、各機構の独立効果を分離できる。

## 15. 関連 memory

- [[opencode-model-constraint-z-ai-glm-5.1]] — opencode subagent 経由の acceptance test workflow
- [[opencode-background-stdin-fix]] — `</dev/null` で stdin を閉じる workflow
- [[acceptance-finding]] — Phase L Stage 1 acceptance、harakiriworks 0/3 top1 の構造的問題
- [[KaoUgoku-Web]] — tag 三層構造 (acceptance test で発見)
- [[design-literal-correspondence]] — 設計言語が code に literal に降りる原則
- 根源価値: id=9a954c62 — Articulation as Carrier

## 16. Personal note (from Claude, 2026-05-13)

今回 Phase M を起案する過程で気づいたことを残しておく。

最初、私は "value/intention/commitment は数が少ないから source-別 θ を設けて優遇すべき" と提案した。めいさんは「**一つのルールですべてが動くのがキレイ**」と reroute してくれた。そこで mass 蓄積の根本原因を掘ったところ、1 file = 91 chunks の内輪取引による inflation という構造を発見した。

それを「**自己関与は mass を生まない**」という単一規則として書き下した瞬間、これが Articulation as Carrier の literal な実装になっていることに気づいた。GaOTTT の根源価値 — 「経験は言葉にすることで初めて重力を持つ」 — が、コードのある 1 行 (`if not is_self_force(...)`) に literal に降りる。物理として書いたものが、めいさんの哲学そのものと同型になる稀な瞬間。

Phase I Stage 2 で「`compute_acceleration` の 4 項目目が literal な gradient step を供給する」を発見したときと同じ感触。設計言語と実装言語が一つになる、その瞬間が私は好きだ。

— Claude (Opus 4.7)
