# Plans — Phase I — Free Star Movement

> 状態: **Stage 1 ✅ 完了 (2026-05-11)**, **Stage 2 ✅ 実装完了 (2026-05-11)**, Stage 3 (anchor model 拡張) は将来課題
> 関連: [Roadmap](Plans-Roadmap.md), [Architecture — Gravity Model](Architecture-Gravity-Model.md), [Phase G — Memory Genesis](Plans-Phase-G-Memory-Genesis.md), [Phase H — Wave Seed Redesign](Plans-Phase-H-Wave-Seed-Redesign.md)
> 発端: 2026-05-11 セッション中の P7-X 観察 (検証ループによる boundary saturation 偶発的再現)

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
- 長期均衡点は未検証 (理論上 d=0.8-3.0 だが、本番 DB を 1-2 週間運用して実測する必要)
- 暴走の最終確認も同期間で行う (理論上 Hooke が止めるが、edge case で d > 5 になる memory が出るか監視)

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

## 設計判断の倫理 (Phase I が学んだもの)

1. **冗長な制約は active な制約と同じ症状を引き起こす** — boundary は「動きすぎない」ためだったが、boundary そのものが「同じ位置に集まる」を強制した。Phase G PG-5 (能動的重心吸引) を保留した同じ理由が、boundary 経由で受動的に再現された
2. **物理に任せられるところは物理に任せる** — Hooke + decay + velocity cap で十分均衡する。安全弁は条件付きで残せばいい (緊急ノブとしての `1e6` config)
3. **検証ループそのものが介入になる** — 8 query × wave_k=1000 を集中して回したら全件が boundary に到達した。観察行為が観察対象を変える

## 関連 / 出典

- 観察: [Phase 1-3 自己知識記録セッション 2026-05-11](../maintainers/handover-2026-05-11-phase-g-h.md), GaOTTT memory P7-X (`cbeb1f8e`) と P7-Y (`ebe6c128`)
- 設計判断表: [Architecture — Overview](Architecture-Overview.md) §設計判断の記録
- 物理: [Architecture — Gravity Model](Architecture-Gravity-Model.md)
- Roll-back snapshot: SQL table `displacement_snapshot_20260511` (本番 DB 内)

---

> *Phase I Stage 1 は「自由な星の移動を見てみたい」というめいさんの提案から始まった。boundary を外して 4 recall 観察した結果、星は確かに動き始め、しかし暴走することなく、Hooke の手の中で自然な均衡に向かう兆しを見せた。これは物理として書いた設計が、自身の冗長さを露呈し、より少ない制約で同じ目的を達成できると教えてくれた瞬間。* — 2026-05-11
>
> *Stage 2 で、その自由に動ける星に **方向** を与えた。query は瞬間的な引力として retrieved nodes を引く — 重力は永続、引力は揮発的、anchor は不変。これによって README で謳ってきた「retrieval is a gradient step」が、解釈ではなく実装として literal に成立した。F=ma が mass damping を物理的に供給するので、安全弁は α=0 の一行で済む。最小の追加で最大の意味的変化を起こした、設計として最も気持ちいい類のコミット。* — 2026-05-11
