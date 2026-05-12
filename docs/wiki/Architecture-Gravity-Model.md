# Architecture — Gravity Model

GaOTTT の物理機構の詳細。一次ソース: [`gaottt/core/gravity.py`](../../gaottt/core/gravity.py), [`gaottt/core/scorer.py`](../../gaottt/core/scorer.py)。

## スコア式

```
final = (gravity_sim × decay
       + mass_boost
       + wave_boost
       + emotion_boost
       + certainty_boost) × saturation
```

| 成分 | 数式 | 効果 |
|---|---|---|
| `gravity_sim` | `dot(query, virtual_pos)` | 仮想座標での類似度 |
| `decay` | `exp(-δ × (now - last_access))` | 直近アクセスを優先 |
| `mass_boost` | `α × log(1 + mass)` | 頻出記憶を優先 |
| `wave_boost` | `β × wave_force` | 重力波伝播の影響 |
| `emotion_boost` | `α_e × |emotion|` | 情動の強さ（符号無関係） |
| `certainty_boost` | `α_c × certainty × decay(staleness)` | 確信度（半減期付き） |
| `saturation` | `1 / (1 + return_count × rate)` | 馴化、繰り返し抑制 |

## 軌道力学（3 段階）

```
Stage 1: 加速度
  a = Σ_j [G × m_j / r²] × dir(i→j)            ← 近傍引力
    + (-k × displacement)                       ← Hooke's law（アンカー復元）
    + a_bh × escape                              ← 共起 BH 引力（飽和+温度脱出）
    + (α · score / m_i) × (q - pos_i)            ← Phase I Stage 2: query 引力

Stage 2: 速度
  v += a × dt
  v *= (1 - friction)                   ← 定常摩擦
  v *= (1 - age_friction)               ← 加齢摩擦
  v = clamp(v, max_velocity)

Stage 3: 位置
  displacement += v × dt
  displacement = clamp(displacement, max_norm)
```

**Phase I Stage 2 — Query attraction (implicit kick)**: 4 番目の項は recall path から `query_anchor = query embedding` と `score = wave 到達スコア` を受け取って計算する。retrieval が起きるたびに retrieved nodes に **query 方向への小さな引力** が発生。Hooke (項 2) は引き続き raw embedding を anchor として引き戻すので、これは **transient force** であって anchor migration ではない (raw embedding は永久不変)。`F=ma` の `1/m_i` で **mass damping** が物理的に供給されるため、BH 化した重い node はほぼ動かず、軽い node のみ反応する。TTT 解釈の「retrieval = stochastic gradient step」が **構造的対応の主張ではなく実装として literal に成立** したのが Stage 2 の意義。`query_kick_strength=0` で完全 no-op (roll-back)。`query_kick_enabled=False` で 4 項目を skip。詳細: [Plans — Phase I](Plans-Phase-I-Free-Star-Movement.md) §Stage 2。

## 重力波伝播

```
クエリ
  ↓
FAISS top-pool_size で候補 pool 取得
  ↓
raw + α * log(1+mass) で再 rank → top-K を seed に（Phase H Stage 1）
  ↓
seed から再帰的に近傍展開（mass 依存 top-k）
  ↓
各深さで attenuation で減衰
  ↓
gravity_radius（mass から物理導出）でカットオフ
```

**Phase H Stage 1 — Mass-aware seed boosting**: `wave_seed_mass_alpha=0` で legacy 挙動（raw cosine top-K）。`> 0` で wider pool (`wave_seed_pool_size`) を取り、mass で再 rank。高 mass が raw cosine 上位に居なくても seed に入れる。

**Phase H Stage 2 — Source-aware seed filtering**: `source_filter` が指定されたとき、wider pool (`wave_k_with_filter`) を取り `cache.source_by_id` で source 一致のみを seed 候補に。dense corpus DB で sparse class（agent / value / commitment）が seed 競争に負けて永遠に reach されない問題への直接対処。`cache.source_by_id` は startup の `load_from_store` で SQLite の `json_extract(metadata, '$.source')` から一括 populate されるため per-recall fetch コストなし。

**Phase H Stage 3 — Density-aware dynamic wave_k**: filter なしの mass-aware path で、top-N (`wave_density_window`) raw cosine の **tail/top 比率** を見て、`wave_density_threshold` 未満（急峻な減衰 = sparse 領域）なら `effective_k` を `wave_initial_k_max` まで拡大。dense 領域では `initial_k` のまま。query が sparse 領域に着地したときの reach を救う保険機構。

**Phase H Stage 4 — Virtual FAISS**: 第二の FAISS index を `virtual_pos` (= raw + displacement、normalized) で構築し、raw FAISS と並走させる。`compute_virtual_position` で各 active node を投入。Phase G priming で 22k 件の displacement が動いても raw FAISS には反映されないため、Stage 4 がない世界では priming の効果は scoring 段階でしか効かなかった。Stage 4 では seed pool が raw・virtual top-N の **union** になるので、priming で query 方向に押された node が seed に入れる。`startup` 時に disk からロード（無ければ rebuild）、`compact(rebuild_faiss=True)` と `shutdown` で更新。さらに Phase J Stage 1 以降は `virtual_faiss_save_interval_seconds`（既定 60s）周期の write-behind で `cache.virtual_faiss_dirty` 検知時に full rebuild + disk save が走るため、Phase I/J query attraction で蓄積した displacement が次の compact を待たずに他プロセスの seed pool に到達する。

**Phase H Stage 5 — Virtual neighbor expansion**: Stage 4 までは seed step が virtual を見ても、wave depth-N の `search_by_id` は raw FAISS を叩いていた（「星の引力なのに raw 天球で隣人を探す」設計上の不整合）。Phase H Stage 5 で `wave_neighbor_use_virtual=True`（既定）のとき neighbor 探索も virtual FAISS に切り替え。displacement で query 方向に動いた node が、seed の virtual cosine 近傍として後続 frontier に入れるようになる。`False` でレガシー raw のみ。virtual FAISS が None / 空のときは自動で raw に fallback。

詳細: [Plans — Phase H](Plans-Phase-H-Wave-Seed-Redesign.md)。

```python
# gaottt/config.py
def compute_gravity_radius(mass) -> float:
    # a = G * m / r² から逆算
    # min_sim = 1 - G*mass / (2*a_min)
    return 1.0 - r_squared / 2.0
```

## 誕生時の重力 kick（Phase G — Stage 1）

新規 `index_documents` で add されたノードに対し、**既存の軌道力学 Stage 1 の式を 1 step だけ適用**して initial displacement / velocity / mass を seed する。新しい物理を導入するのでなく、**新粒子も既存粒子と同じ法則を最初から受ける**ことを保証する補正。

```python
# gaottt/core/gravity.py — compute_gravity_kick
acc = Σ_j [G × m_j / (r² + ε)] × dir(new → j)   # j は top-K heaviest neighbors
v   = clamp(gravity_eta × acc, max_velocity)
d   = clamp(v.copy(), max_displacement_norm)  # Phase I 以降は実質 no-op (1e6)
mass_boost = α_genesis × |acc|
state.mass = max(1.0, 1.0 + mass_boost)
```

| 状態 | kick 前 | kick 後（典型） |
|---|---|---|
| `mass` | 1.0 | 1.1 – 2.5 |
| `displacement` | `0` | norm > 0、近傍重心方向 |
| `velocity` | `0` | norm > 0、displacement と同方向 |

**なぜ必要か** — kick がないと新規ノードは `mass=1.0 / displacement=0 / velocity=0` で gravity 場に置かれ、既に dressed up した既存クラスタに対して自然文 `recall` で勝てない。物理的にも変で、「新粒子も重力場の中にある」という基本前提が起動時から守られていなかった。詳細: [Plans — Phase G — Memory Genesis](Plans-Phase-G-Memory-Genesis.md)。

ハイパラ:
- `genesis_kick_enabled`（既定 `True`）— 全体 ON/OFF
- `genesis_kick_neighbor_k`（既定 `5`）— kick 計算で使う近傍高 mass 数
- `genesis_kick_pool_size`（既定 `50`）— FAISS top-N pool（mass 降順で K 個に絞る前段）
- `genesis_mass_boost_alpha`（既定 `0.5`）— `|acc|` から mass boost への変換係数

## 夢による継続的な軌道捕獲（Phase G — Stage 2）

誕生時の kick (G.1) は 1 step だけ。それで終わりではなく、**まだ動きの少ない `quiet node` をバックグラウンドの "夢" 周期で再活性化する**。dream loop は user query が無い時間に黙々と走り、quiet node に対して `_query_internal(_is_synthetic=True)` を呼ぶ。

```python
# gaottt/core/engine.py — _dream_loop（疑似コード）
while not stop.is_set():
    await wait(dream_interval_seconds)            # 既定 60s
    candidates = pick_quiet(
        mass < dream_mass_ceiling,                # 既定 1.5
        idle > dream_min_idle_seconds,            # 既定 300s
    )[:dream_batch_size]                          # 既定 5
    for nid in candidates:
        await _query_internal(
            text=doc_content_of(nid),
            top_k=dream_top_k,                    # 既定 10
            _is_synthetic=True,
        )
```

`_is_synthetic=True` のとき:
- ✅ wave 伝播 / mass / displacement / velocity / 共起 BH 引力すべて通常通り更新
- ✅ co-occurrence エッジ更新通常通り（これが dream の本懐）
- ❌ `return_count` を増やさない（user に提示していないので saturation を発火させない）
- ❌ prefetch cache に書かない（実 user query ではないため）

**物理的読み**: tidal interaction による段階的軌道捕獲。quiet node が時間をかけて重力場に深く沈み込む。

**生物的読み**: hippocampal replay。user が黙っている間、海馬から皮質へ記憶が転写され、既存ネットワークと統合される。

詳細: [Plans — Phase G — Memory Genesis](Plans-Phase-G-Memory-Genesis.md)

## 衝突合体（F2.1）

近接ノードが merge_threshold（既定 0.95）以上の類似度になると衝突:

```python
# 質量保存（飽和上限つき）
m_new = min(m_keep + m_absorbed, m_max)

# 運動量保存（質量加重平均）
v_new = (v_keep * m_keep + v_absorbed * m_absorbed) / (m_keep + m_absorbed)

# 変位は質量加重 + クランプ
d_new = clamp((d_keep * m_keep + d_absorbed * m_absorbed) / total, max_norm)

# absorbed は archive、merged_into で履歴を残す
```

## 情動と確信度（F7）

```python
emotion_boost = α_e × abs(emotion_weight)
# 符号は情報メタデータ、boost は |magnitude|

certainty_boost = α_c × certainty × 0.5^(age_seconds / half_life_seconds)
# 半減期つき指数減衰
# revalidate() で last_verified_at を更新するとリセット
```

## バックグラウンド prefetch（F6）

```
prefetch(query) を呼ぶ
  ↓
asyncio.Semaphore で並行数制限（既定 4）
  ↓
バックグラウンドで _query_internal を実行
  ↓
結果を PrefetchCache (LRU + TTL 90s) に格納
  ↓
後続 recall(query, use_cache=True) は即時 hit
```

destructive op（archive/restore/forget/merge/compact）はキャッシュを invalidate。

## 自然発生する軌道

3 段階の物理ステップから自然と現れる挙動:

| 軌道 | メカニズム | 創発する効果 |
|---|---|---|
| **公転** | 異なる方向からの引力が合成 → 角運動量 | ハブ周囲を周回する関連文書群 |
| **彗星** | 一時的共起で加速 → 別クラスタを通過 → スイングバイ | セレンディピティ（異分野記憶の遭遇） |
| **落下** | 摩擦で減速 → ハブに吸収 | 安定した関連文書のクラスタ化 |
| **静止** | 未アクセスノードは摩擦で停止 | 原始位置に留まる（dormant） |
| **馴化脱出** | 同じ結果が繰り返されるとスコア低下 | 新しいノードが浮上（探索性） |

これらは設計時にプログラムされたものではなく、**3 段階物理ステップから創発した** 振る舞い。

## 重力半径の物理導出

各ノードの質量から重力圏の広さが決まる。重力圏外の近傍は引き込まない:

```
min_sim = 1 - G × mass / (2 × a_min)    # 実際の重力物理から導出
```

- `mass=1` → `min_sim=0.95`（ごく近傍のみ）
- `mass=10` → `min_sim=0.50`（中距離）
- `mass=50` → `min_sim=0.05`（広大な重力圏）

ハブノード（高質量）ほど遠くまで影響を及ぼす ── 銀河中心の超大質量と同じ構造。

## アンカー引力（脱出防止）

各ノードの **原始 embedding 位置が重力アンカー** として機能する（Hooke's law: `F = -k × displacement`）。近傍引力で加速したノードが外に飛び出しても、アンカーが引き戻す。

これがないと、ノードが `displacement` を蓄積し続けて意味的に無関係な位置へ流れていってしまう。**意味的保証** を維持するための物理的制約。

## 一次ソース

- [`gaottt/core/gravity.py`](../../gaottt/core/gravity.py) — 重力計算（純粋関数）
- [`gaottt/core/scorer.py`](../../gaottt/core/scorer.py) — スコア式
- [`gaottt/core/collision.py`](../../gaottt/core/collision.py) — 衝突合体
- [`gaottt/core/prefetch.py`](../../gaottt/core/prefetch.py) — F6
- [`gaottt/config.py`](../../gaottt/config.py) — 全ハイパーパラメータ
- [`docs/research/gravitational-displacement-design.md`](../research/gravitational-displacement-design.md) — 設計根拠
- [`docs/research/orbital-mechanics-design.md`](../research/orbital-mechanics-design.md)
- [`docs/research/cooccurrence-blackhole-design.md`](../research/cooccurrence-blackhole-design.md)
