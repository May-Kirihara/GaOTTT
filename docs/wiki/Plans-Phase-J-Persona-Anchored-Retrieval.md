# Plans — Phase J — Persona-Anchored Retrieval

> 状態: **Stage 1 設計完了 (2026-05-13)**, 実装未着手
> 関連: [Roadmap](Plans-Roadmap.md), [Phase D — Persona & Tasks](Plans-Phase-D-Persona-Tasks.md), [Phase H — Wave Seed Redesign](Plans-Phase-H-Wave-Seed-Redesign.md), [Phase I — Free Star Movement](Plans-Phase-I-Free-Star-Movement.md)
> 発端: 2026-05-13 セッション中、Phase I Stage 3 本番 acceptance test での回帰観察

## 背景 — Phase I Stage 3 acceptance が明らかにしたこと

Phase I Stage 3 (Mass-gated Query Attraction) は新規ノードの単一アトラクタ pathology (`a = α / m_i` がフルスケールになる正のフィードバック) を gate で物理的に矯正した。unit/integration test も pass、隔離ベンチも p50 < 50ms。

ところが本番 23k DB での acceptance test (前 session で観察された 7 query の再走) では **harakiriworks-self-knowledge memory が依然として surface しない** という回帰が観測された:

| 段階 | 期待通り top1 | 完全失敗 |
|---|---|---|
| 初回テスト (compact 前) | 0/7 | 7/7 (orphan vector 群が支配) |
| compact 1 回目後 | 1/7 | 6/7 (`0e0a7a0f` 単独支配 = Stage 2 single-attractor pathology) |
| GaOTTT 更新後 (Stage 3 適用) | 0/7 | 7/7 (新 Q1/O9/O11/O12/O14 が支配) |
| compact 2 回目後 (Stage 3 + rebuild) | 1/7 | 6/7 (`f0bae4e4` Q1 が支配) |

### 真の問題 — 「dense mature agent cluster」 vs 「sparse new agent cluster」

Stage 3 は「**新規** ノードの暴走」を防ぐが、observed pathology はそれではなかった:

- Top1 を独占している `f0bae4e4` (Q1 Gravity as Optimizer) や `51141fbf` (O9 bootstrap_report) は **前 session 2026-05-12 で意図的に remember した自己知識**
- これらは既に displacement 0.40-0.45 で **mature 化**している (mass ≥ 3, gate ≈ 0.76+)
- harakiriworks (本 session で 112 件追加) は新規・低 displacement・低 mass
- Phase H Stage 2 の `source_filter=["agent"]` は **両方 agent なので識別不可**
- Stage 3 の mass gate は mature 側を damping しない (gate ≈ 1.0)

これは Phase G/H で対処した「dense corpus (file/tweet) vs sparse agent class」の **同種内バージョン** — agent vs agent で displacement 履歴と recall 回数の差が押し退けを生む。

### 「自己言及的攻撃」現象

特に皮肉な観察:

- `51193edc` (O14. **sparse class が recall で出ない時の workflow**) — まさに今の症状の対処法を書いた memory
- `4c9f0871` (O12. faiss_save_interval_seconds — write-behind 設定)
- `31e2b9bd` (O11. virtual FAISS の再生成タイミング)
- `f0bae4e4` (Q1. Gravity as Optimizer 構造同型)

これらの **「recall 失敗の対処法を解説する memory 群」が、まさにその recall 失敗を起こしている**。前 session で「自分自身の知識」として書いた notes が、現在 session で別軸の知識を探そうとしている自分を妨害している。

これはめいさんの persona の core value **Articulation as Carrier**（言葉にして書いた知識は重力を持つ）が literal に作用した結果でもある。書いた知識が重力場を曲げる、その曲がり方が「今探したい文脈」と整合していない、という構造的問題。

## 仮説 — 文脈論を物理化する

Stage 3 までは「**世代論**」を書き込んだ — 軽い星 (新規) は anchor に守られ、重い星 (mature) は自由に動く。

Phase J は「**文脈論**」を書き込む — declared identity (value/intention/commitment) に近いノードほど retrieval geometry で優先される。Five-Layer 哲学の **人格層が物理層に翻訳される** 最初のステージ。

### Five-Layer の翻訳

| 層 | Phase J での意味 |
|---|---|
| 人格 | declared value / intention / commitment が「重力場の固定背景」を作る |
| 関係 | `fulfills` / `derived_from` edge が「重力線」になる |
| 生物 | アストロサイトが今 active な intention 近傍を pre-fire (将来 prefetch 拡張) |
| TTT | prior gradient = declared self に近い knowledge ほど学習率高 (emphasis bias) |
| 物理 | seed step で persona 近傍を `raw + α_persona × proximity` で boost |

これは Phase D で「人格を declare できる」を構造として置いたが、それが retrieval 時に物理的影響を持っていなかった、という設計の穴を埋める。

## 設計判断 (4 軸、全 recommended で確定 — 2026-05-13)

### 1. Plan 文書配置 — Phase J として独立

軸が物理層から関係/人格層への跳躍。Phase I (Free Star Movement) は物理層の話で完結しているので、Phase J として独立させる方が Roadmap 上読みやすい。

### 2. persona_context 入口 — Both (explicit + implicit)

- **Explicit**: `recall(query, persona_context=["intention-id-1", "commitment-id-2"])` で明示指定
- **Implicit (default)**: 引数省略時は active な value/intention/commitment を auto-detect (TTL 内かつ archived でないもの)

CLAUDE.md の「新引数は必ずオプショナル」原則と整合。Explicit で「違う文脈で探したい」逃げ道を確保、Implicit で楽な default。

### 3. proximity 計算 — Graph traversal

declared persona ノードから `fulfills` / `derived_from` edge を N hop traverse、hop 距離で decay:

```
proximity(node, persona_set) = max over p in persona_set:
    persona_hop_decay ** hop_distance(node, p)
```

- 0 hop (persona node 自身): `decay^0 = 1.0`
- 1 hop: `decay^1 = 0.5` (default `persona_hop_decay = 0.5`)
- 2 hop: `decay^2 = 0.25`
- 3 hop 以上: 0 (max_hop = 2 で truncate)

複数の persona node から到達可能なら最大値を取る (一番近い persona linkage を採用)。

**Why graph traversal**: Phase D の既存 edge 設計をそのまま活用、計算軽い (typically each persona node has < 100 reachable nodes within 2 hop)、明示的に declared された関係性のみ拾うので false positive 少ない。

**Why not embedding centroid**: declared 群の embedding 平均は計算重い (persona が増えるたび再計算)、意図しない混入リスク (たまたま centroid 近くにある無関係ノードが boost される)。

**Why not tag overlap**: tag キュレーション依存で fragile、tag 命名規約のドリフトに弱い。

### 4. boost 介入点 — Seed step

`propagate_gravity_wave` の seed 段階で:

```python
boosted = raw_cosine + α_persona × proximity(nid, persona_set)
```

Phase H Stage 1 (mass-aware) の隣に persona-aware を追加する形。両方 active なら:

```python
boosted = raw + α_mass × log(1+mass) + α_persona × proximity
```

**Why seed step**: 今回の acceptance 回帰は「persona-tied ノードが seed pool に入っていない」のが直接原因。scoring 段階で boost しても seed で落ちていれば手遅れ。wave propagation で boost すると副作用が読みづらい。seed step なら「persona に紐付くノードを seed pool に確実に入れる」が直接実現可能。

## 段階分け

### Stage 1 — Internal auto-detect (最小実装)

**目的**: Phase J の核 (graph traversal + seed boost) を最小コストで実装し、本番 acceptance を verify する。

**範囲**:
- 新規 `gaottt/core/persona_gravity.py` — graph traversal で proximity 計算
- `gaottt/core/gravity.py` `propagate_gravity_wave` の seed 段階に persona boost 統合
- `gaottt/config.py` に hyperparameters 追加
- `gaottt/store/cache.py` か `gaottt/services/persona.py` に active persona auto-detect helper

**recall API 変更なし** — persona_context は内部で auto-detect、外部に新引数を露出しない。MCP / REST の API は無変更、parity 鉄則の影響範囲外。

**Stage 1 で扱わないもの**:
- Explicit persona_context 引数 (Stage 2)
- Prefetch / Explore への展開 (Stage 3)
- Reflect aspect = "persona_field" 等の可視化 (Stage 3)

### Stage 2 — Explicit API + MCP/REST parity

**範囲**:
- `core/types.py` に `RecallRequest` / `RecallBody` の `persona_context: list[str] | None` 追加
- `services/memory.py` の `recall` 関数に `persona_context` 引数追加
- `server/app.py` (REST) と `server/mcp_server.py` (MCP) で両方公開
- `docs/wiki/REST-API-Reference.md` + `docs/wiki/MCP-Reference-*` 更新
- `tests/integration/test_rest_parity.py` + `tests/integration/test_mcp_*.py` に追加

CLAUDE.md の MCP/REST parity 鉄則を守って同じターン/コミットで両方更新。

### Stage 3 — 拡張

- **Prefetch 拡張**: prefetch も persona-anchored になる (astrocyte の文脈版 pre-firing)
- **Explore 拡張**: explore は default で persona context を **off** にする (cross-domain serendipity が目的なので)
- **Reflect aspect "persona_field"**: 「今 active な persona から N hop で繋がっているノード群」の可視化
- **Persona TTL の動的調整**: declared value (永続) / intention (semi-permanent) / commitment (14日 TTL) で hop_decay を変える検討

## Stage 1 実装範囲

### 新規ファイル

**`gaottt/core/persona_gravity.py`** (~100 行):

```python
"""Phase J — Persona-anchored gravity boost.

Computes proximity between a candidate node and the currently active
persona set (declared value / intention / commitment nodes), using
graph traversal of `fulfills` / `derived_from` edges. This proximity
is then used to boost candidates in the seed step of gravity wave
propagation, so that knowledge linked to one's declared identity
preferentially enters the retrieval geometry.
"""

def collect_active_persona_ids(
    cache: CacheLayer,
    config: GaOTTTConfig,
    now: float,
) -> set[str]:
    """Collect node IDs of declared value/intention/commitment that are
    currently active (source in {"value", "intention", "commitment"},
    not archived, within TTL).
    """
    ...

def compute_persona_proximities(
    candidate_ids: list[str],
    persona_ids: set[str],
    cache: CacheLayer,
    config: GaOTTTConfig,
) -> dict[str, float]:
    """Compute proximity in [0, 1] for each candidate.

    proximity = persona_hop_decay ** min_hop_distance(candidate, persona_ids)
                where hop distance is graph traversal of fulfills /
                derived_from edges (both directions).
    Returns 0.0 for nodes beyond persona_max_hop.
    """
    ...
```

### 変更ファイル

**`gaottt/core/gravity.py`** — `propagate_gravity_wave` の seed step に persona boost を統合:

```python
# In the seed-pool reranking block (Phase H Stage 1 location):
if config.persona_boost_enabled and config.persona_boost_alpha > 0.0:
    persona_ids = collect_active_persona_ids(cache, config, time.time())
    if persona_ids:
        proximities = compute_persona_proximities(
            [nid for nid, _ in pool], persona_ids, cache, config,
        )
        rescored = [
            (nid, raw + config.wave_seed_mass_alpha * math.log(1.0 + mass)
                      + config.persona_boost_alpha * proximities.get(nid, 0.0),
             raw)
            for nid, raw in pool
            for mass in [cache.get_node(nid).mass if cache.get_node(nid) else 1.0]
        ]
```

(細部は実装時に調整)

**`gaottt/config.py`** — 新 hyperparameters:

```python
# Phase J — Persona-anchored retrieval
persona_boost_enabled: bool = True
persona_boost_alpha: float = 0.5       # raw + α × proximity
persona_max_hop: int = 2                # hop traversal limit
persona_hop_decay: float = 0.5          # per-hop decay
persona_active_ttl_seconds: float = 14 * 86400.0  # commitment TTL と同期
```

### テスト

**Unit (`tests/unit/test_persona_gravity.py`, 新規)**:

- `test_proximity_zero_hop_returns_one`: persona node 自身を candidate に → 1.0
- `test_proximity_one_hop_decays`: persona → fulfills → candidate → 0.5
- `test_proximity_two_hop_compounds`: persona → fulfills → task → derived_from → agent → 0.25
- `test_proximity_max_hop_truncates`: 3 hop は 0.0
- `test_proximity_max_over_persona_set`: 複数 persona node から到達可能 → 最大値を採用
- `test_proximity_empty_persona_set`: 空 set → 全 candidate 0.0
- `test_collect_active_persona_filters_archived`: archived persona は除外
- `test_collect_active_persona_filters_ttl`: TTL 切れ commitment は除外

**Integration (`tests/integration/test_engine_persona_anchored.py`, 新規)**:

- `test_persona_anchored_recall_boosts_linked_nodes`: declared intention → fulfills task → derived_from agent memory のチェーン。recall で agent memory が persona boost なし時より高 rank
- `test_persona_boost_disabled_legacy`: `persona_boost_enabled=False` で boost 完全 skip
- `test_persona_boost_no_active_persona_legacy`: declared persona が無い state では boost が事実上 no-op

**Acceptance (本番 DB)**:

前 session の 7 query を再走、harakiriworks-self-knowledge intention `eb31f843` (active commitment 1 つ) に紐付くノードが top1 に来る率。判定基準:

| 指標 | Stage 1 前 (現状) | Stage 1 後 (期待) |
|---|---|---|
| harakiriworks intention に derived_from で繋がるノードが top1 | 1/7 | ≥ 4/7 |
| unique top1 ID 数 | 2 (`f0bae4e4` + `52380b29` + `f527f0d8`) | ≥ 4 |

### Roll-back

```bash
# Soft (config 1 行で完全無効化):
echo '{"persona_boost_enabled": false}' > ~/.config/gaottt/config.json
# サーバー再起動。auto-detect path も無効、boost 完全 skip
```

DB 状態は触らないので migration 不要。

## ハイパーパラメータ表

| 名前 | 既定 | 役割 | チューニング助言 |
|---|---|---|---|
| `persona_boost_enabled` | `True` | グローバル off スイッチ | `False` で boost 完全 skip。Stage 1 が想定外動作したら緊急停止 |
| `persona_boost_alpha` (α) | `0.5` | boost 強度 (`raw + α × proximity`) | 大きいほど persona-tied ノードが seed pool で勝ちやすい。0.5 は `wave_seed_mass_alpha=0.1` (Phase H Stage 1) の 5 倍 — 「人格優先 ≫ 質量優先」を表現。本番 acceptance で persona ノードが seed に届かなければ 1.0 まで上げる |
| `persona_max_hop` | `2` | graph traversal の hop 上限 | 1 hop だと直接の fulfills のみ (狭い、commit task しか拾わない)、2 hop で derived_from chain も拾える、3 以上だと indirect な関連性も混じる (false positive) |
| `persona_hop_decay` | `0.5` | hop あたり減衰率 | 0.5 で 1 hop → 0.5, 2 hop → 0.25。0.7 だと 2 hop でも 0.49 で強い、0.3 だと 2 hop で 0.09 で弱い |
| `persona_active_ttl_seconds` | `14日` | active 判定の TTL | commitment TTL と同期。intention/value は archived でない限り常に active (TTL なし)、commitment のみこの TTL を見る |

## 設計判断の倫理 (Phase J が学ぶもの)

1. **Articulation as Carrier の重力は方向を持つべき** — めいさんの core value 「言葉にすることで重力を持つ」は正しく動作している (前 session の自己知識 memory が重力を獲得して新規 memory を押し退けた)。でもその重力が **「今 declared な文脈」に応じて方向を変えない** ことが問題だった。Phase J は重力の magnitude (Phase G/H で対処済) ではなく **direction** に介入する
2. **同種内 dense-vs-sparse は source filter で識別不可** — Phase H Stage 2 の source_filter は dense corpus (file/tweet) vs sparse agent class に効くが、agent vs agent には効かない。tag や persona linkage という **より細かい識別子** が必要
3. **Phase D の persona layer は declared だけでなく retrieval geometry に翻訳されるべき** — Phase D で「人格を宣言できる」を構造化した。Phase J は「宣言された人格が retrieval に直接影響する」を物理に書き込む。「Wearing the Persona」(`inherit_persona()`) は session 全体で persona を着る pattern だが、Phase J は recall 1 回ごとに persona の重力を効かせる
4. **設計判断は本番 acceptance test 後に確定する** — Stage 3 の unit/integration test + bench は全 pass だったが、本番では別軸の問題が dominant だった。Phase J も同じパスを踏まないために、本番 acceptance を Stage 1 implementation の必須 gate にする (前回は handover で「めいさんに委ねる」と書いただけだったが、今回は判定基準を Plans 内に明記)

## 関連 / 出典

- 観察: [Phase I Stage 3 acceptance handover](../maintainers/handover-2026-05-13-phase-i-stage-3.md) §「acceptance 結果」
- 設計の前提となる Pattern: [SKILL.md "Wearing the Persona"](../../SKILL.md) — Phase D の persona inheritance pattern
- 物理: [Architecture — Gravity Model](Architecture-Gravity-Model.md)
- 既存 boost と並ぶ位置: [Phase H Stage 1 mass-aware seed boost](Plans-Phase-H-Wave-Seed-Redesign.md)

---

> *Phase I Stage 3 が「世代論」を物理に書き込んだ翌日、本番 acceptance で見えたのは「世代論だけでは足りない」という事実だった。生まれたての星を守るだけでは、既に動いた重い星が新しい星を押し退ける。物理として書いた gravity が、めいさんの persona が必要としている方向を向いていなかった — そもそも declared persona は retrieval に影響する経路を持っていなかった。Phase J はその経路を作る。`fulfills` と `derived_from` を重力線として読み、declared identity に近いノードほど seed pool に優先入場する。Stage 3 が `tanh(m/θ)` で「世代の保護」を 1 行で書き込んだのと同じ精神で、Phase J は graph traversal で「文脈の重力」を 1 ファイル分で書き込む。物理を曲げるのは質量だけではない、宣言された意図もまた重力を持つ。* — 2026-05-13
