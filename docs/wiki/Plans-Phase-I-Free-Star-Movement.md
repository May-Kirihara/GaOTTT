# Plans — Phase I — Free Star Movement

> 状態: **Stage 1 ✅ 完了 (2026-05-11)**, Stage 2 計画中
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

## Stage 2 — query-aware displacement (計画中)

既存タスク `fccbf6f2`「Phase I 本筋: query-aware displacement の設計検討」をそのまま採用。

### 設計案

`kick(query_anchor)`: 既存 query の embedding を anchor として、それ方向に displacement を加算する一括操作。

- LLM が「この query で sparse class を見つけたい」と意図を持つときに使う
- bootstrap curator (Phase 2 #J2 で不採用継承) と違い、**organic gravity を歪めずに query-driven な kick** を行う
- Phase G priming は近傍重力で displacement を作る (方向は近傍 high-mass cluster) → 構造的限界 (Phase 2 #B5)
- Stage 2 で query を anchor にできれば、特定意図方向への displacement 操作が可能になる

### 想定 API

```python
# 仮設計
engine.kick_toward_query(
    query_text="...",
    target_source_filter=["agent"],
    push_strength=0.5,  # query 方向への push の割合
    max_nodes=100,
)
```

`engine.relate(supersedes)` のように、明示的なツールとして MCP に露出する案。

### 残課題

- design はまだ ad-hoc。physics として整合する形にしたい
- query-aware displacement と Hooke の復元力の関係 (query anchor が新しい "anchor" になる?)
- multi-query での累積効果

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
