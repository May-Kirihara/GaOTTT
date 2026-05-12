# Plans — Phase G: Memory Genesis (重力誕生 / 軌道捕獲 + 夢)

> **Status**: 計画中（2026-05-10 ドラフト、未実装）
> **Depends on**: FAISS write-behind 修正完了（2026-05-10 commit、同日 fix）
> **Author**: 2026-05-10 session — めいさん + Claude
> **関連**: [Plans — Roadmap](Plans-Roadmap.md), [Architecture — Gravity Model](Architecture-Gravity-Model.md), [Reflections — Five-Layer Philosophy](Reflections-Five-Layer-Philosophy.md)

---

## 動機 — なぜ Phase G が必要か

GaOTTT は使い込むほど memory 同士が co-recall で結びつき、co-occurrence エッジが張られ、mass が蓄積し、displacement で意味的に近いノードが gravity 井戸を共有するように **organic に育つ**。これがこのプロジェクトの中核体験である。

しかし、**新規 `remember` 直後のノードは「裸」の状態**で gravity 場に置かれる:

| 量 | 新規ノードの初期値 | 既存高 mass ノード（例） |
|---|---|---|
| `mass` | 1.0 | 5.0 – 20.0 |
| `displacement` | `0` ベクトル | L2 ノルム ~ 0.3（飽和）|
| `velocity` | `0` ベクトル | ~ 0.05（軌道速度）|
| `temperature` | 0.0 | 0–35 |
| co-occurrence エッジ数 | 0 | 5–20 |
| `last_access` | indexed_at | 様々 |

その結果、自然文クエリでの `recall` で、新規ノードは **embedding 距離が近いのに重力補正後の score band で押し負ける**。本来重力場の中の粒子は引力を受けて軌道を持つはずなのに、現状の実装では**重力法則が新規粒子に対して起動していない**。

これは 2026-05-10 セッションの recall 検証で実証された（[Operations — Troubleshooting](Operations-Troubleshooting.md) の関連項を参照）。FAISS write-behind 修正で「永続化されない」問題は解消したが、「永続化されたが見つけられない」問題は別物として残っている。

Phase G は **新規 memory にも重力法則を最初から適用する** Phase。

---

## 三層語彙 — Phase G を物理 / TTT / 生物で読む

| 層 | 案 G.1（軌道捕獲） | 案 G.2（夢） |
|---|---|---|
| **物理** | hyperbolic encounter / Hill sphere 捕獲。新粒子が高 mass 体の重力場を通過する瞬間に kick を受け、初期軌道を獲得 | tidal interaction による段階的軌道捕獲。N 回の flyby でエネルギー散逸 → 束縛軌道へ |
| **TTT 機構** | 初期 gradient injection。Hebbian "fire together" の 1 step を index 時に強制実行し、representation を周囲の geometry に整列 | 自己教師あり pre-training。新パラメータが「自身を query にして」neighbor から signal を受け取る |
| **生物** | 新生ニューロンが既存回路に挿入される際の synaptic priming（dentate gyrus の neurogenesis） | 海馬 → 大脳皮質の memory replay。睡眠中に新規 memory が再活性化され、既存 cortex 表現と統合される（hippocampal replay / cortical consolidation） |

両者は排他ではなく**段階の違い**。G.1 は瞬間の重力 kick、G.2 は時間軸での緩やかな統合。組み合わせると「新規粒子は誕生の瞬間に軌道を得て、夢の中で深く沈み込む」。

---

## 設計

### G.1 — 軌道捕獲（Initial Gravitational Kick）

新規 `index_documents` の末尾で、各新規ノードに対して **1 step の物理シミュレーションを既存粒子と同じ方式で走らせる**。新しい計算機構を導入するのではなく、既に動いている `update_orbital_state` / 重力波伝播の **1 イテレーションを新規ノードに対しても適用するだけ**。

```python
# gaottt/core/engine.py（疑似コード、最終形は要調整）
async def index_documents(self, documents):
    ...
    self.faiss_index.add(vectors, ids)
    self._faiss_dirty = True

    if self.config.genesis_kick_enabled:
        for new_id, new_vec in zip(ids, vectors):
            # Step 1: 近傍 K の高 mass ノードを集める
            neighbors = self._top_k_heavy_neighbors(
                new_vec, k=self.config.genesis_kick_neighbor_k,
            )
            if not neighbors:
                continue

            # Step 2: 重力 kick = Σ G * m_j * (r_j - r_i) / |r_j - r_i|^3
            # これは update_orbital_state 内の force 計算と同じ式
            kick_force = compute_gravity_force(new_vec, neighbors, self.config)

            # Step 3: 初期 displacement / velocity / mass を kick から導出
            # gravity_eta は既存ハイパラを流用
            initial_displacement = self.config.gravity_eta * kick_force
            initial_velocity = initial_displacement.copy()  # ~ Δr/Δt with Δt=1
            mass_boost = self.config.genesis_mass_boost_alpha * \
                np.linalg.norm(kick_force)

            self.cache.set_displacement(new_id, initial_displacement)
            self.cache.set_velocity(new_id, initial_velocity)
            state = self.cache.get_node(new_id)
            state.mass = 1.0 + mass_boost  # typically 1.5–2.5
            self.cache.set_node(state, dirty=True)
```

**なぜ既存の gravity_force 計算を流用するか** — 物理として整合し、新規コードを最小化し、ハイパラチューニングが既存と連動する。新規粒子も既存粒子も**同じ法則**に従う、というのが Phase G の核心。

**Open**: kick 計算で「既存ノードへの反作用」を実装するか。物理的には momentum 保存で BH 側も微小に momentum を失うべきだが、`m_max=50 vs 新粒子 m=1` なら影響微小。実装簡略化の観点で**反作用なし**で開始、後段で観測して判断。

### G.2 — 夢（Dream Consolidation）

`engine.startup()` でバックグラウンド `_dream_loop` を起動。一定周期で **「最近 add されたが mass=1 付近で動きの少ないノード」を選び、そのノード自身を query にした synthetic recall を走らせる**。これは既存の `_query_internal` をそのまま呼ぶだけ。simulation step がそこで起きるので mass / displacement / co-occurrence が自然に build up する。

```python
# gaottt/core/engine.py（疑似コード）
async def _dream_loop(self):
    """Hippocampal-replay analog. Recently-added quiet nodes are revisited
    on a slow cadence, building gravitational binding without user query."""
    while not self._dream_stop.is_set():
        try:
            await asyncio.wait_for(
                self._dream_stop.wait(),
                timeout=self.config.dream_interval_seconds,
            )
            break
        except asyncio.TimeoutError:
            pass

        candidates = self._pick_dream_candidates(
            limit=self.config.dream_batch_size,
        )
        for nid in candidates:
            doc = await self.store.get_document(nid)
            if not doc:
                continue
            # synthetic = True: simulation を走らせるが return_count は増やさない
            await self._query_internal(
                text=doc["content"],
                top_k=self.config.dream_top_k,
                wave_depth=None, wave_k=None,
                _is_synthetic=True,
            )

def _pick_dream_candidates(self, limit: int) -> list[str]:
    """mass≈1 で last_access が古い、archived でない node から limit 件。"""
    now = time.time()
    quiet = [
        s for s in self.cache.get_all_nodes()
        if not s.is_archived
        and s.mass < self.config.dream_mass_ceiling   # e.g. 1.5
        and (now - s.last_access) > self.config.dream_min_idle_seconds
    ]
    quiet.sort(key=lambda s: s.last_access)  # 古いものから
    return [s.id for s in quiet[:limit]]
```

**`_is_synthetic` フラグ** — 既存 `_query_internal` に optional 引数を追加し、`True` のとき:
- `state.return_count` の更新をスキップ（user に提示されていないので saturation を発火させない）
- prefetch cache に書かない

**夢の物理的意味** — 「重力場の中で時間が経過した」という更新を、user query のない idle 時間中に少量ずつ進める。粒子が休眠していても重力法則が止まる訳ではない、というモデル。tidal capture の段階的シミュレーション。

### G.3 — 重心アンカー（候補保留）

「銀河系全体の中心 BH 重力で新粒子を引き寄せる」案。実装は最小（重心計算 + 1 行）だが、**homogenization リスク**が大きい。重心は意味の塊なので、そこに新粒子を引き寄せると全 memory が「平均」に収束し、ネットワークが死ぬ。

→ **Phase G では不採用。** G.1 + G.2 の効果次第で将来再検討。

---

## 哲学的整合性 — bootstrap curator (不採用) との区別

[handover.md §1.3](https://github.com/May-Kirihara/GaOTTT/blob/main/docs/maintainers/handover.md) で **「LLM curator で初期サマリ橋を生成」案は不採用**となった（"organic gravity が自発的に build up する感触を奪う" — 「言われると自分で組み上がっていくほうが面白い」というめいさんの判断）。

Phase G はこの判断と矛盾しない:

|  | bootstrap curator（不採用） | Phase G — 軌道捕獲 / 夢（採用候補） |
|---|---|---|
| 性質 | LLM が外から橋を架ける | 既存物理法則を新粒子にも適用するだけ |
| 内容 | semantic な意味解釈を 1 段階含む | 機械的・自動的、意味解釈しない |
| organic か | No（人工的） | Yes（自然法則） |
| 既存設計との関係 | 別経路の追加 | shipped 設計の盲点を埋める |

curator は「橋を別に作る」、Phase G は「重力という既存の働きが新粒子を見落としていた漏れを塞ぐ」。**Phase G の機構は本来 Phase 1 の重力モデル設計時にあるべきだった**機構と読める。FAISS write-behind 修正と同じく shipped 設計の盲点を埋める性質。

---

## 実装ロードマップ

### Stage 1 — G.1 のみ実装

| ステップ | 内容 |
|---|---|
| 1 | `gaottt/core/gravity.py` に `compute_gravity_kick(new_vec, neighbors, config)` を追加。既存の force 計算式を流用。 |
| 2 | `gaottt/core/engine.py` の `index_documents` 末尾で kick を 1 step 適用（`config.genesis_kick_enabled` でガード） |
| 3 | `gaottt/config.py` に `genesis_kick_enabled: bool = True`, `genesis_kick_neighbor_k: int = 5`, `genesis_mass_boost_alpha: float = 0.5` を追加 |
| 4 | `tests/integration/test_engine_genesis_kick.py` 新規。StubEmbedder で 「dense cluster 50 件 + sparse new 1 件」を ingest → 自然文 recall で sparse new が top-K に出現することを assert |
| 5 | 隔離 bench で p50 を確認（kick は index_documents の hot path に乗る、+5–10ms 想定） |
| 6 | 本番 DB で（read-only シミュ環境で）kick あり / なしの recall 比較 |
| 7 | docs 更新（Architecture-Gravity-Model.md, Operations-Tuning.md） |

**判定基準**: 「dense cluster + sparse new の合成テストで、sparse new が top-5 に入る」+「p50 < 50ms 必達」。

### Stage 2 — G.2 を被せる

| ステップ | 内容 |
|---|---|
| 1 | `_query_internal` に `_is_synthetic: bool = False` を追加。`True` のとき return_count 更新と prefetch cache 書き込みをスキップ |
| 2 | `engine.py` に `_dream_loop`, `_pick_dream_candidates`, `_dream_task`, `_dream_stop` を追加 |
| 3 | `startup()` で task 起動（`config.dream_enabled` でガード）、`shutdown()` で停止 |
| 4 | `gaottt/config.py` に `dream_enabled: bool = True`, `dream_interval_seconds: float = 60.0`, `dream_batch_size: int = 5`, `dream_mass_ceiling: float = 1.5`, `dream_min_idle_seconds: float = 300`, `dream_top_k: int = 10` |
| 5 | `tests/integration/test_engine_dream_loop.py` 新規。短い `dream_interval_seconds`（例 0.1s）で startup → quiet node の mass / co-occurrence が時間とともに増えることを assert |
| 6 | 本番 DB で 1 日後の statistics を測定（dream で持ち上げられた節の mass 分布） |
| 7 | docs 更新（Architecture-Concurrency.md にも dream loop の存在を記載） |

**判定基準**: 「synthetic recall で組み上がる co-occurrence エッジが long-tail 救済に寄与する」+「CPU 占有率が許容範囲」。

### Stage 3（Open）— G.3 評価

G.1 + G.2 で十分なら G.3 は永久不採用。不足なら**最小強度の重心 pull** を additive で追加し、homogenization 兆候（recall 多様性の低下、duplicates 急増）をモニタ。

### Stage 0 — Primordial gravity activation（post-hoc、2026-05-10 実装）

**動機**: Stage 1 は新規 `remember` のみに kick を適用するため、Stage 1 デプロイ前に index されていた既存ノード（`mass=1.0`, `displacement=0`, `velocity=0` の "naked" 状態）には何の効果も及ばない。本番 DB では `Active(mass>1) = 1114 / 23368` ≒ **5%** しか動いておらず、残り 95% は重力法則を一度も体験していない。Stage 0 は「**全 active node に対して kick を 1 回だけ適用**」する後付けの一発操作。

**実装**: [`scripts/prime_gravity.py`](https://github.com/May-Kirihara/GaOTTT/blob/main/scripts/prime_gravity.py)
- 既存ノードは `compute_gravity_kick` の戻り値を **加算**（既存 displacement + Δd）— 過去軌道を保持
- `mass = max(現在, 1.0 + m_boost)` で既に重い node を守る
- `genesis_mass_boost_cap` で 1 step の mass 増加を上限制（観測 raw boost max 71 → cap 1.0）

**安全要件**: [Architecture — Concurrency](Architecture-Concurrency.md)「逆方向上書きの罠」参照。実行前に他の MCP server プロセスを `kill` して flush ループを止め、`data_dir` をバックアップ。実行順は (1) 他プロセス停止 → (2) priming → (3) 他プロセス再起動。

**結果（本番 DB 23,372 nodes、2026-05-10）**:

| 量 | 値 |
|---|---|
| processed / kicked | 23,014 |
| pre-existing mass > 1 | 2,460（守られた、加算で重畳） |
| pre-existing displacement > 0 | 2,357 |
| FAISS にない skip 件数 | 358（write-behind 修正前のゾンビ） |
| elapsed | 2,083s ≒ 34.7 min（11 nodes/s） |
| mass boost | median 0.11 / mean 0.13 / max **1.00** (cap) |
| `|disp|` after | median 0.0012 / mean 0.0077 / max 0.30 |

**観察された限界**: priming 後の `recall` で、新規 `remember` の surface 率は**改善せず**。同時に既存高 mass node の score は大きく再分布（例: あるツイートの top1 score が 0.95 → 0.10）— これは scoring 段階で displacement が確かに効いている証拠。が、wave **seed 段階** は `faiss_index.search` の raw cosine top-K で固定されているため、displacement / mass 改善は seed 経由でしか scoring に到達できない sparse class（agent / value / commitment 等）の救済には届かない。

→ この発見は Phase G の前提を超える構造的問題。後続: [Phase H — Wave Seed Redesign](Plans-Phase-H-Wave-Seed-Redesign.md)。

---

## 提案ハイパーパラメータ

すべて [`gaottt/config.py`](https://github.com/May-Kirihara/GaOTTT/blob/main/gaottt/config.py) に追加。デフォルトは保守的。

| パラメータ | 既定 | 影響 |
|---|---|---|
| `genesis_kick_enabled` | `True` | G.1 の有効化 |
| `genesis_kick_neighbor_k` | `5` | kick 計算で参照する近傍高 mass の数 |
| `genesis_kick_pool_size` | `50` | FAISS top-N pool（mass 降順で K に絞る前段） |
| `genesis_mass_boost_alpha` | `0.5` | kick 強度に応じた mass 初期 boost のスケール |
| `genesis_mass_boost_cap` | `1.0` | 1 step あたりの mass boost 上限（dense cluster 中心の outlier を抑える） |
| `dream_enabled` | `True` | G.2 の有効化 |
| `dream_interval_seconds` | `60.0` | 夢ループの周期。短いほど消費 CPU↑ |
| `dream_batch_size` | `5` | 1 周期で再活性化する quiet node の最大数 |
| `dream_mass_ceiling` | `1.5` | この mass 未満を quiet とみなす閾値 |
| `dream_min_idle_seconds` | `300` | 最終アクセスからこれ以上経った node のみ対象 |
| `dream_top_k` | `10` | synthetic recall の top_k |

チューニングシナリオ（提案）:
- 「新規 memory が surface しすぎる」→ `genesis_mass_boost_alpha` ↓ / `genesis_kick_neighbor_k` ↓
- 「夢が遅い」→ `dream_interval_seconds` ↓ / `dream_batch_size` ↑
- 「夢が CPU を食う」→ `dream_interval_seconds` ↑ / `dream_batch_size` ↓

---

## リスクと未解決事項

### Measured（測定済み、2026-05-10）

| 観点 | 値 |
|---|---|
| 単体テスト | pytest 155/155 PASS（genesis_kick 4 + dream_loop 3 + faiss_write_behind 2 を含む） |
| isolated bench | p50 = 14.9ms（< 50ms 必達余裕、kick / dream の overhead は計測レベル外） |
| smoke | mcp_smoke.py / rest_smoke.py 両方 全 green |
| Stage 0 priming（本番 DB） | 23,014 件適用、34.7 min、cap で max boost 1.0 |
| 既存ノード保護 | mass > 1 の 2,460 件は max() で守られた、displacement > 0 の 2,357 件は加算で重畳 |

### Claimed（実装後に主張する効果）
- 新規 `remember` 直後の自然文 `recall` で、対象 memory が top-5 に surface する率が ~0% → 80%+ に向上
- 23k 件規模 corpus-heavy DB でも、agent / value / commitment 系 sparse class が sparse 性ゆえに見失われることがなくなる
- "Use → grow" の体感が直後から立ち上がる（現在は時間と co-recall の蓄積後にのみ感じられる）

### Open（未解決 / 観測課題）
- ★ **新規 doc / sparse class の surface 改善は Phase G では届かない（2026-05-10 確認）** — wave seed が `faiss_index.search` の raw cosine top-K で固定されており、`displacement` / `mass` の改善は scoring 段階でしか効かない。reach されない node には何の効果もない。後続: [Phase H — Wave Seed Redesign](Plans-Phase-H-Wave-Seed-Redesign.md)
- **kick 強度の校正** — `genesis_mass_boost_alpha=0.5` + `genesis_mass_boost_cap=1.0` は仮置き。priming で観察された「scoring 再分布」と「surface 不変」のバランスが望ましい挙動かは本格運用後に評価
- **Stage 1 vs Stage 1+2 の効果分離** — G.1 だけで十分か、G.2 が本当に追加価値を出すかを切り分け測定したい（Phase H 完了後にやる方が筋）
- **Dream loop の優先順位** — `_pick_dream_candidates` は mass + idle 時間で並べるが、もっと洗練された heuristic（「重要そうなのに見落とされている」評価）に進化させる余地
- **マルチプロセス整合性** — 複数 MCP プロセスが同時に dream loop を回したらどうなるか（重複的な synthetic recall で mass 加算が狂わないか）。priming で発見した [逆方向上書きの罠](Architecture-Concurrency.md) も含めて整理
- **`bootstrap_report.py` との関係** — bootstrap_report は read-only な観察ツール、Phase G は write-side。両者のメッセージが整合するよう、bootstrap_report の出力に「genesis kick で持ち上げられた最近の node」を表示するセクションを追加すると親切
- **ベンチ拡張** — `scripts/benchmark.py` に「新規 add → 即時 recall surface 率」シナリオを追加し、Phase G + H の効果を定量化

---

## 関連

- [Plans — Roadmap](Plans-Roadmap.md) — 全 Phase の俯瞰
- [Plans — Backend Phase A/B/C](Plans-Backend-Phase-A-B-C.md) — 重力モデル本体（G.1 が借りる force 計算の出処）
- [Architecture — Gravity Model](Architecture-Gravity-Model.md) — 既存の displacement / velocity / Hookean restoring の数式
- [Architecture — Concurrency](Architecture-Concurrency.md) — FAISS write-behind と並ぶ background loop（dream はその次の loop になる）
- [Reflections — Five-Layer Philosophy](Reflections-Five-Layer-Philosophy.md) — 物理 → TTT → 生物 → 関係 → 人格の五層
- [Operations — Troubleshooting](Operations-Troubleshooting.md) — 本 Phase のきっかけとなった「別プロセスから新規 remember が見えない」項
- [`docs/maintainers/handover.md`](https://github.com/May-Kirihara/GaOTTT/blob/main/docs/maintainers/handover.md) §1.3 — bootstrap curator 不採用の判断（Phase G の哲学的境界条件）
