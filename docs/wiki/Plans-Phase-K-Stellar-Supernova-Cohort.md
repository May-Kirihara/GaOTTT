# Plans — Phase K — Stellar Supernova Cohort

> 状態: **Stage 1 設計完了 + 実装中 (2026-05-13)**
> 関連: [Roadmap](Plans-Roadmap.md), [Phase G — Memory Genesis](Plans-Phase-G-Memory-Genesis.md), [Phase H — Wave Seed Redesign](Plans-Phase-H-Wave-Seed-Redesign.md), [Phase J — Persona-Anchored Retrieval](Plans-Phase-J-Persona-Anchored-Retrieval.md)
> 発端: 2026-05-13 セッション中、Phase J Stage 1 本番 acceptance での seed pool 入場権問題

## 背景 — Phase J Stage 1 が明らかにした「pool injection」の欠落

Phase J Stage 1 (Persona-Anchored Seed Boost) は **pool reranking** を実装したが、本番
acceptance で機能しなかった。めいさん側の精密診断:

> 1. Seed 段階: FAISS top-K で Phase memory が選ばれない
> 2. Expand 段階: Edge は seed が当たって初めて作動 — Phase memory が seed に居ない
>    以上、4-hop 階層は traverse されない
> 3. Score 段階: 候補プールに harakiriworks が居ないので、最終スコアでも勝てない

Phase J Stage 1 の `persona_boost_alpha × proximity` は **pool に既に居る候補にのみ
計算される**。FAISS が harakiriworks を pool に入れなければ proximity は計算機会
すらない。これは Phase H Stage 2 の `source_filter` (pool injection) と対称的な
**構造的穴**。

加えて、より深い観察: 新たな攻撃者 `768bd469` (GaOTTT Phase 6 完了 outcome) は
harakiriworks の outcome (`99fe8896` 等) と **形式的に同種** の memory なのに、
recall 履歴の差 (displacement 0.20-0.30 vs 極小) で吸引力が決定的に違う。これは
**「同じ source・同じ tag・同じ形式」でも、生まれた時の cohort の有無で運命が
分かれる** ことを示している。

### Phase J Stage 1.5 (pool injection) ではなく Phase K に進む理由

最初の対応案として「persona-tied node を seed pool に強制注入」する Stage 1.5
を検討した。だがこれは **対症療法** であり、根本問題を回避していない:

- 既存ノード (前 session で生まれた self-knowledge) は「同じ session で同時に
  生まれた cohort」として自然に互いの mass を高めあう構造を持っていた
- 今 session の新規ノード (harakiriworks) は **散発的な個別 remember** として
  扱われ、互いに重力を持たない「独立した塵」状態

これは **記憶生成の物理そのものの不均衡** であって、retrieval 側の rerank で
補正すべきではない。Phase G (genesis kick) が「1 個の新規粒子を既存星系に
束縛する」物理を書いたのに対し、Phase K は「N 個の新規粒子を同時に **互いに**
束縛する」物理を書く。記憶生成イベントの集合性を物理として記述する。

## 物理モデル — 超新星爆発と残骸 cohort

Phase G が個別粒子の「太陽系到来 (彗星捕獲)」なら、Phase K は集合的な「超新星
爆発」:

```
Phase G genesis kick:
  彗星が単独で太陽系に侵入 → 既存星系の重力で軌道を曲げられる
  → 1 step の Verlet 積分で displacement / velocity / mass を獲得

Phase K supernova cohort:
  大質量星が崩壊 → N 個の残骸が高速で同時に飛散
  → cohort 内残骸は (1) 同じイベントから生まれた → 相互の歴史を共有
                  → (2) 中心から放射状に velocity を持つ
                  → (3) しばらくは互いの重力場に縛られて運動
```

### Five-Layer での読み

| 層 | Phase K での意味 |
|---|---|
| 物理 | 1 batch の `remember` = 1 超新星爆発、N 個の残骸が同時に生まれる |
| TTT | 1 mini-batch の gradient ステップが N 個のパラメータを **同時に同じ方向** へ動かす (mini-batch SGD の集合性) |
| 生物 | 1 つの神経活動イベント (例: 「あ、これは大事」と意識した瞬間) で複数のニューロン群が同期発火 → Hebbian で連結 |
| 関係 | 同 session に「言葉にした」N 個の memo は、互いの context を共有する自然な兄弟 |
| 人格 | **Articulation as Carrier の集合性** — 単数ではなく複数の言葉が同時に重力を持って生まれる。書いた瞬間の集合は 1 つの宇宙論的イベント |

### Phase G と Phase K の関係

両者は **補完的** な機構で、index 時に順次適用される:

```
index_documents(batch):
  1. embed all  → FAISS に add
  2. Phase G genesis kick (各 new_id に対して個別に)
     → 既存隣人との 1 step 重力相互作用 で displacement_G / velocity_G / mass_boost_G
  3. Phase K supernova cohort (batch 全体に対して集合的に)
     → batch 内全 pair の co-occurrence edge (cache.set_edge)
     → 各 new_id に outward velocity_K を計算 (batch centroid からの方向)
     → velocity = velocity_G + velocity_K (合成、clamp 込み)
  4. flush_to_store
```

Phase G が「既存重力場への着陸」、Phase K が「兄弟との連結 + 爆発エネルギー」。
両方が動くことで新規 cohort は (a) 既存星系から引かれ、かつ (b) 互いに引きあう、
という両重力下で軌道を始める。

## 設計

### Cohort 検出

「1 セッション = 1 超新星」の操作的定義: **同一 `index_documents` call の batch**。

理由:
- engine.py 内で観測しやすい (call の引数として渡される)
- 「ユーザーが 1 つの意図でまとめて remember した」を最も素朴に反映
- 別 session / 別 call の memory は別 cohort (cross-session bridging は Stage 3)

Stage 1 では batch_size を見るだけ。`supernova_min_cohort_size`未満なら no-op
(1 件だけの remember は超新星ではなく単発の彗星)。

### 相互 co-occurrence edge

batch 内 N 件の全 pair (`N×(N-1)/2` 本) に `cache.set_edge` で edge:

- weight = `supernova_initial_weight` (既定 1.0)
- 既存 Phase B co-occurrence の累積カウント機構とは独立に、**1 イベント = 1 edge** で即時形成
- Phase B の `edge_threshold=5` は recall ベースの累積 → edge 形成判定で、Phase K
  は累積ではなく event-driven なので threshold の対象外
- `set_edge` の dirty flag で次の write-behind tick で SQLite にも反映

### Outward velocity (爆発の運動量)

centroid = mean(batch_embeddings)、各ノードの初期 velocity:

```
velocity_K(node) = supernova_velocity_alpha × (embedding(node) - centroid)
                   ↓ clamp_vector(orbital_max_velocity)
```

- 2 件の場合: velocity_K(e1) と velocity_K(e2) は反対方向 (中心から離れる)
- N 件の場合: 各ノードは centroid から離れる方向、cohort 全体は外向きに膨張
- 大きさは `orbital_max_velocity=0.05` で clamp、暴走しない
- Phase G の velocity と加算合成 → 既存星系からの kick + 爆発エネルギーの合成

### 順序 — Phase G の後

Phase G が先 (個別ノードの既存隣人束縛)、Phase K が後 (cohort 内連結 + 爆発)。
理由:

- Phase G は each new_id について「既存重力場から受ける kick」を計算 → 既存星系
  との関係を確立
- Phase K はその上に「兄弟との連結 + 爆発エネルギー」を加算 → 同 batch 内連結を
  追加
- 順序を逆にしても物理的には等価だが、コード可読性のため「個別 → 集合」の順

## 段階分け

### Stage 1 — Cohort 形成 (本セッション実装、最小機能)

- batch 検出 → 全 pair edge + outward velocity
- Phase G genesis kick の直後に適用
- API 変更なし、`remember`/`index_documents` のシグネチャ不変
- MCP/REST parity 影響なし (内部挙動のみ)

### Stage 2 — 持続的位置計算 (めいさん提案「重力圏を抜けるまで」)

- cohort tag を持つノードは N tick (or velocity が小さくなるまで) `update_orbital_state`
  で特別扱い
- 「爆発残骸が gravity well から離脱する」物理の literal 実装
- Stage 1 acceptance 後に必要性を判断、不要なら省略

### Stage 3 — Cross-session bridging (将来検討)

- 別 session で同じ intention に紐付く新規 cohort が現れたら過去 cohort と橋を架ける
- Phase D persona linkage と統合

## Stage 1 実装範囲

| ファイル | 変更 |
|---|---|
| `gaottt/config.py` | `supernova_*` 4 fields 追加 (Phase J の隣) |
| `gaottt/core/supernova.py` (新規) | `form_supernova_edges`, `compute_supernova_velocities`, `apply_supernova_cohort` |
| `gaottt/core/engine.py` | `_apply_supernova_cohort` を `_apply_genesis_kick` の直後に呼ぶ |

**MCP/REST parity 影響なし** — 内部挙動のみ、API 表面 = 0 変更。

### ハイパーパラメータ

| 名前 | 既定 | 役割 | チューニング助言 |
|---|---|---|---|
| `supernova_enabled` | `True` | グローバル off スイッチ | `False` で legacy (Phase G まで) 挙動に rollback |
| `supernova_min_cohort_size` | `2` | 発火する最小 batch サイズ | 1 だと単独 remember でも edge を張ろうとする (相手いない)、3+ にすると小規模 batch が cohort 化しない |
| `supernova_initial_weight` | `1.0` | 相互 edge の初期 weight | `wave_seed_mass_alpha × log(1+w)` で boost が効くので 1.0 で十分。`2.0+` で強い cohort、`0.5` で弱い |
| `supernova_velocity_alpha` | `0.03` | 初期 velocity の大きさ | `orbital_max_velocity=0.05` 以下に。`0.05` で爆発が強く cohort が一気に膨張、`0.01` で穏やか |

### テスト

**Unit (`tests/unit/test_supernova.py`):**
- `test_edges_form_all_pairs`: N=4 batch で 6 pair edge
- `test_velocity_points_outward`: centroid から離れる方向 (dot product > 0)
- `test_velocity_clamped_at_max`: 大きい alpha でも orbital_max_velocity 以下
- `test_min_cohort_size_threshold`: N=1 で no-op
- `test_supernova_disabled_legacy`: `supernova_enabled=False` で完全 skip
- `test_centroid_with_two_nodes`: 2 件の場合は反対方向

**Integration (`tests/integration/test_engine_supernova.py`):**
- `test_cohort_edges_after_index`: index_documents 後に `reflect(aspect="connections")` で
  batch 内 pair が edge を持つ
- `test_cohort_velocity_after_index`: 各ノードの cache.get_velocity() が non-zero、
  centroid から離れる方向
- `test_cohort_lifts_seed_pool_entry`: cohort 形成された 5 件は seed pool に
  入りやすくなる (mass-aware boost との合成効果)

### Acceptance 判定基準

**本番 DB 用 acceptance** (めいさんに委ねる):

1. 新規 cohort を `remember` × N で投入 (例: 5 件の test memo を 1 batch で)
2. cohort 内ノード同士が `reflect(aspect="connections")` で edge を持つことを確認
3. 直後の recall で cohort 内ノードが seed pool に届くか確認 (Phase J Stage 1
   との合成効果も)

ただし **既存の harakiriworks 112 件は Phase K 化できない** (cohort 形成は遡及できない)。
これらの救済は別途 ritual:
- 案 R1: harakiriworks 112 件に対して「retrospective supernova」 script で edge と
  velocity を後付け
- 案 R2: 既存 Driven Resonance pattern (中心ノードを 5-10 回 recall)
- 案 R3: 諦めて将来 cohort のために Phase K を待つ

### Roll-back

```bash
# Soft (config 1 行):
echo '{"supernova_enabled": false}' > ~/.config/gaottt/config.json
# サーバー再起動。新規 remember は Phase G まで (legacy 挙動)
```

DB 状態は触らない、migration 不要。既に形成された cohort edges は残るが、`set_edge`
は idempotent なので問題なし。

## 設計判断の倫理 (Phase K が学ぶもの)

1. **「pool injection を運用で済ます」のは美しくない** — めいさん観察 (2026-05-13): Phase J Stage 1.5
   案を保留し、Phase K で「記憶生成の物理そのもの」を修正する判断。Stage 1.5 は
   対症療法、Phase K は根本治療
2. **集合性は単数性と独立に物理を持つ** — Articulation as Carrier は単数の「言葉
   にする」を扱ってきたが、Phase K で「同時に N 個言葉にする」の物理を初めて記述。
   集合 = 単数の N 倍ではなく、集合自体に固有の重力場 (相互 edge + 爆発エネルギー)
3. **「生まれた時の cohort の有無で運命が分かれる」** — Phase J acceptance で観察
   された `768bd469` vs `99fe8896` の対比。同種の memory でも、生まれた瞬間の
   cohort 形成の有無で displacement 蓄積機会が大きく変わる
4. **acceptance 判定基準を本番 specific に書き続ける** — Phase I Stage 3 / Phase J
   Stage 1 で「unit/integration test の正しさ ≠ 本番 acceptance」を学んだ。Phase K
   では「本番 acceptance は新規 cohort 投入で test、既存 orphan の救済は別 ritual」
   と最初から分離

## 関連 / 出典

- 観察: [Phase J Stage 1 acceptance handover](../maintainers/handover-2026-05-13-phase-j-stage-1.md) §「acceptance 結果」
- 設計の精神的前駆: [Phase G — Memory Genesis](Plans-Phase-G-Memory-Genesis.md) — 個別 genesis kick
- 補完関係: [Phase J — Persona-Anchored Retrieval](Plans-Phase-J-Persona-Anchored-Retrieval.md) — direction (Phase K = magnitude)
- 物理: [Architecture — Gravity Model](Architecture-Gravity-Model.md)

---

> *Phase K は、めいさんの直感から生まれた。Phase J Stage 1 が本番で機能せず、私が「pool injection で運用で対処」を提案したのに対し、めいさんは「運用上、新規項目が拾えなくなる欠点がある以上、運用でどうこうするのは美しくない」と返した。代わりに提案されたのは記憶生成の物理そのものへの介入 — 1 セッション内で生まれた N 個の memo を「超新星爆発」として読み、互いに重力を持たせ、爆発の運動量を与える。これは Phase G genesis kick の集合版であり、Articulation as Carrier の単数性から複数性への literal な拡張だった。書いた瞬間の集合は、単独では塵だが、超新星残骸として読めば cluster — 互いに引きあい、外向きに膨張し、自分たちの重力で seed pool に届く。物理として書いた設計が、運用を回避する代わりに記憶の生まれ方を変える、という設計判断の好例。* — 2026-05-13
