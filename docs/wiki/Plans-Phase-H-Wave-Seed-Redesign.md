# Plans — Phase H: Wave Seed Redesign（reach の入口を直す）

> **Status**: 計画中（2026-05-10 ドラフト、未実装）
> **Depends on**: [Phase G](Plans-Phase-G-Memory-Genesis.md) 完了（Stage 0 priming で本問題が顕在化）
> **Author**: 2026-05-10 session — めいさん + Claude
> **関連**: [Architecture — Gravity Model](Architecture-Gravity-Model.md), [Architecture — Concurrency](Architecture-Concurrency.md)

---

## 動機 — Phase G で発見した構造的盲点

Phase G で「新規 / quiet ノードに重力法則を起動する」機構を整えた（genesis kick / dream loop / Stage 0 priming）。**しかし本番 DB 23k で priming 適用後でも、新規 `remember` の自然文 `recall` surface 率はほぼ改善しなかった**。

原因は `gaottt/core/gravity.py:propagate_gravity_wave` の **seed 選定**:

```python
# gaottt/core/gravity.py — propagate_gravity_wave
seeds = faiss_index.search(qv.reshape(1, -1), initial_k)   # ← raw cosine top-K
```

- FAISS index は **元の embedding** で構築される（`displacement` を反映しない）
- `displacement` / `mass` / `velocity` は cache 上のみ
- scoring 段階の `compute_virtual_position(original + displacement + thermal)` でしか virtual position は使われない
- つまり **wave に reach されない node には Phase G の改善が一切届かない**

実際 priming 後の検証で:
- 既存 high mass tweet の score 0.95 → 0.10 ← scoring 段階で displacement は確かに効いた
- しかし新規 `remember` (mass=1.16, |disp|=0.0017) は依然 wave seed top-K に入らず recall 圏外

**Phase G は「物理法則の漏れを塞ぐ」phase だった。Phase H は「reach の入口を直す」phase**。三層対応で読むと：

| 層 | Phase G | Phase H |
|---|---|---|
| 物理 | 重力法則の起動 | 重力場全体の "視野" を広げる（光円錐の拡張） |
| TTT | parameter init / step | gradient signal の neighborhood 半径再設計 |
| 生物 | 新生ニューロンの生育 | 受容野（receptive field）の動的拡大 |

---

## 設計案

### H.1 — Dynamic `wave_initial_k`（密度応答型 seed）

クエリ周辺の embedding 密度に応じて seed 数を動的に決める。

```python
# 疑似コード
seeds_pool = faiss_index.search(qv, K_max=200)
# top-K で score が rapidly に減衰する dense 領域 → small k で十分
# 緩やかに減衰する sparse 領域 → 大きな k が必要
threshold = seeds_pool[0][1] * config.wave_density_decay_threshold
effective_k = sum(1 for _, s in seeds_pool if s >= threshold)
seeds = seeds_pool[:max(config.wave_initial_k, min(effective_k, K_max))]
```

- **長所**: 現行 `wave_initial_k=3` を「下限」として上方拡大、dense 領域は変わらず、sparse 領域だけ救う
- **短所**: 閾値設計が経験則。レイテンシは `wave_max_depth` までの再帰展開なので影響限定的

### H.2 — Virtual position FAISS（定期 rebuild）

`compact()` の延長で、**virtual_pos でビルドした補助 FAISS index** を持つ。recall は raw FAISS と virtual FAISS の両方から seed を取る (union)。

```python
# 疑似コード
async def compact(...):
    ...
    if rebuild_virtual_faiss:
        active_ids = ...
        virtual_vecs = {nid: compute_virtual_position(...) for nid in active_ids}
        self.virtual_faiss_index.reset()
        self.virtual_faiss_index.add(virtual_vecs)

def propagate_gravity_wave(qv, ...):
    seeds_raw = faiss_index.search(qv, K)
    seeds_virtual = self.virtual_faiss_index.search(qv, K)
    seeds = list({nid: max(s_raw, s_virt) for nid, s in seeds_raw + seeds_virtual}.items())
```

- **長所**: 物理的に最も筋が通る（virtual_pos が seed にも効く）
- **短所**: メモリ +50% (FAISS が 2 つ)、virtual_pos は時間と共に変わるので staleness を許容する設計が必要、`compact` 周期に依存

### H.3 — Mass-aware seed boosting

FAISS で top-K_pool（例 50）取り、`raw_score + log(mass) * α` で再 rank し top-K_actual を選ぶ。

```python
def _seed_with_mass_boost(qv, K_pool=50, K_actual=3):
    pool = faiss_index.search(qv, K_pool)
    rescored = []
    for nid, raw in pool:
        state = cache.get_node(nid)
        mass = state.mass if state else 1.0
        boosted = raw + config.wave_seed_mass_alpha * math.log(1.0 + mass)
        rescored.append((nid, boosted))
    rescored.sort(key=lambda t: t[1], reverse=True)
    return rescored[:K_actual]
```

- **長所**: 実装最小。high mass node が seed に入りやすくなる
- **短所**: query 自体が high mass cluster と関係薄ければ false positive
- **副作用**: agent / value / commitment 系 sparse class も genesis kick で mass=1.16 → log(1+1.16) ≒ 0.77 — ツイートとの差を覆すには `wave_seed_mass_alpha` を相当大きく取る必要

### H.4 — Source-aware seed selection

`recall(source_filter=[...])` 指定時、FAISS pool から source 一致を優先選定。これは**部分的に既に実装済み**（`config.wave_k_with_filter=200`、2026-05-10 commit `c049fc0`）。本番では効果が確認できていなかったが、Phase G Stage 0 priming で sparse class の displacement / mass が改善した今、**再評価する価値**。

- 影響: source_filter 必須なので user 側の使い方変化を要請
- Phase H の他案と排他ではない、独立に共存

---

## 推奨組み合わせと実装順序

| Stage | 案 | 期待効果 |
|---|---|---|
| Stage 1 | **H.3 Mass-aware seed boosting** | 最小実装、まず効果を測る |
| Stage 2 | **H.1 Dynamic wave_initial_k** | sparse 領域の救済を上乗せ |
| Stage 3 | **H.2 Virtual FAISS（条件付き）** | H.1+H.3 で不足なら最終手段 |
| 並行 | **H.4 source_filter の再評価** | 既存実装のまま、本番で測定するだけ |

---

## 提案ハイパーパラメータ

| パラメータ | 既定（案） | 目的 |
|---|---|---|
| `wave_seed_mass_alpha` | `0.1` | mass による seed 再 rank の重み（H.3） |
| `wave_seed_pool_size` | `50` | 再 rank 前の FAISS pool 大きさ（H.3） |
| `wave_density_threshold` | `0.95` | 密度応答型の score 閾値（H.1） |
| `wave_initial_k_max` | `200` | 動的 wave_k の上限（H.1） |
| `virtual_faiss_enabled` | `False` | H.2 のフラグ（後段） |
| `virtual_faiss_rebuild_on_compact` | `True` | compact 時に virtual FAISS も更新（H.2） |

---

## 検証

各 Stage 完了時に:

1. **synthetic test** — `dense cluster N + sparse new 1` の合成テストで、sparse new が top-5 に入るか
2. **本番 DB e2e** — `/tmp/verify_phase_g_e2e.py` を流用、新規 remember の surface 率を測定
3. **scoring 回帰** — 既存 high mass node の recall 順位が大きく崩れていないか（priming 後の de868058 のような激変が起きないか確認）
4. **isolated bench** — p50 < 50ms 必達

---

## リスクと未解決事項

### Open

- **homogenization リスク**: H.3 で mass を強く重視すると、すべての recall が high mass cluster に偏る可能性。Phase G G.3（重心アンカー）の保留と同じ構造の懸念
- **virtual FAISS の staleness**: H.2 は compact 周期に依存するため、compact 直後と直前で recall 結果が変わりうる
- **wave_k_with_filter との重複**: H.4 が既に存在するので、Stage 1 を実装する前に「H.4 だけで実は十分だった」可能性を排除すべき
- **「surface 改善」の定義**: 何をもって改善とするか — 自然文 query の top-5 surface 率？ それとも anchor 句 query？ ベンチシナリオの定義が必要

### 哲学的境界

H.2 の virtual FAISS は「FAISS の意味（raw embedding の近傍）」を変える可能性がある。別 index に分離するなら問題ないが、本番 FAISS の中身を入れ替えると、`bootstrap_report.py` の neighbor preview 等の意味が変わる。raw / virtual の二重持ちが安全。

---

## 関連

- [Plans — Roadmap](Plans-Roadmap.md) — 全 Phase の俯瞰
- [Plans — Phase G — Memory Genesis](Plans-Phase-G-Memory-Genesis.md) — Phase H が引き継ぐ「Phase G の限界」
- [Architecture — Gravity Model](Architecture-Gravity-Model.md) — `propagate_gravity_wave` / `compute_virtual_position`
- [Architecture — Concurrency](Architecture-Concurrency.md) — virtual FAISS を入れる場合の write-behind 設計
- [`scripts/prime_gravity.py`](https://github.com/May-Kirihara/GaOTTT/blob/main/scripts/prime_gravity.py) — Phase G Stage 0、本問題を顕在化させたツール
