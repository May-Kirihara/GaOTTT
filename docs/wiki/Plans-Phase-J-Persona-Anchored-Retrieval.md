# Plans — Phase J — Persona-Anchored Retrieval

> 状態: **Stage 1 ✅ 完了 (2026-05-13)**, **Stage 2 ✅ 完了 (2026-05-13)**, **Stage 3 ✅ 完了 (2026-05-13) — Phase J 完遂**
> 関連: [Roadmap](Plans-Roadmap.md), [Phase D — Persona & Tasks](Plans-Phase-D-Persona-Tasks.md), [Phase H — Wave Seed Redesign](Plans-Phase-H-Wave-Seed-Redesign.md), [Phase I — Free Star Movement](Plans-Phase-I-Free-Star-Movement.md), [Phase K — Stellar Supernova Cohort](Plans-Phase-K-Stellar-Supernova-Cohort.md)
> 発端: 2026-05-13 セッション中、Phase I Stage 3 本番 acceptance test での回帰観察。Stage 2 は同日の Stage 1 acceptance (0/7) + Phase K acceptance (0/7) で「pool 入場権」が seed boost の事前条件として欠落していたことが判明したことが発端。

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

## Stage 2 — Explicit pool injection (2026-05-13 設計完了 + 実装中)

### 設計動機

Stage 1 acceptance (2026-05-13 本番) で発覚した穴: persona boost は **pool 内 rerank** のみで、FAISS top-K に persona-tied node が入らない query では機能しない。Phase K Stage 1 で「同 batch ノード群に相互 co-occurrence edge」を張る retrospective ritual を実行しても (6216 edge + 112 velocity)、本番 7 query test は **0/7** に悪化 — embedding 距離が dominant、Phase J/K の boost は seed pool に入った候補にしか効かない。

Stage 2 は **LLM が「今の文脈」を明示的に伝えて seed pool に強制注入する** path を提供する。Stage 1 の auto-detect は維持しつつ、新引数で explicit control を加える。「pool injection は美しくない」と思った代わりに、API として正面に位置づけ、LLM の判断による文脈制御として整理する。

### 設計判断 5 軸 (全 recommended で確定)

#### 1. injection の semantic — **additive**

- restrictive (`source_filter` pattern): tag に一致するもの **のみ** 返す → 出力極端に偏る、explore に向かない
- **additive (Stage 2 採用): tag に一致するノードを FAISS top-K に union 注入** → embedding 距離が遠くても確実に届く、かつ semantically relevant な候補も並ぶ
- `source_filter` の restrictive 機構と並立 (両者は独立)

#### 2. tag match — **substring (Phase H Stage 2 source_filter と同様)**

- complete: tag list 要素の完全一致
- prefix: "harakiriworks*"
- **substring (採用): tag list 内のどれかが指定文字列を含めば match** — 柔軟、Phase H Stage 2 と pattern 整合

#### 3. 複数 tag — **OR (どれか 1 つでもマッチで集合化)**

- AND: 全 tag を持つノードのみ — restrictive すぎる
- **OR (採用): 「どれか」が自然 — LLM の意図表現と整合**

#### 4. persona_context と auto-detect — **explicit が auto-detect を上書き**

- 引数省略時: Stage 1 auto-detect (active value/intention/commitment 全部)
- 明示指定時: 指定された id のみ persona として扱う (auto-detect 無効化) — 「この session は intention X だけに focus」と明示できる

#### 5. wave_k_with_filter の扱い — **tag_filter 使用時も同じく pool 拡大**

- tag_filter 使用 → seed pool size を `max(wave_initial_k, wave_k_with_filter)` に拡大
- Phase H Stage 2 `source_filter` と同じ理由 (sparse target が seed に届くため)

### API 仕様

```
recall(
    query: str,
    top_k: int = 5,
    source_filter: list[str] | None = None,        # Phase H Stage 2 (restrictive)
    wave_depth: int | None = None,
    wave_k: int | None = None,
    force_refresh: bool = False,
    persona_context: list[str] | None = None,      # Stage 2 NEW (explicit persona ids)
    tag_filter: list[str] | None = None,           # Stage 2 NEW (additive injection)
) -> list[QueryResultItem]
```

- `persona_context`: intention/commitment/value の id 列。省略時は Stage 1 auto-detect
- `tag_filter`: tag substring 列 (OR match)。マッチするノードを seed pool に additive 注入

### Pattern 例

```python
# 「文脈付き recall」 — 今 declared な intention を意識的に retrieve
recall(query="Eleventy Pipeline",
       tag_filter=["harakiriworks-self-knowledge"])
# → harakiriworks 内の Phase 4 R1 (.eleventy.js 責務) が top に届く

# 「クロス文脈 recall」 — 別 intention に紐付くノードを意図的に持ち込む
recall(query="重力場の設計判断",
       tag_filter=["niceboat", "gaottt-self-knowledge"])
# → 両 corpus から material を引き出す

# 「明示 persona」 — auto-detect でなく特定の intention に絞る
recall(query="今日のテスト戦略",
       persona_context=["eb31f843-..."])  # harakiriworks commitment id
# → harakiriworks intention 配下の知識のみが persona graph として作用
```

### 実装範囲

| ファイル | 変更 |
|---|---|
| `gaottt/core/types.py` | RecallRequest (MCP) + RecallBody (REST) に `persona_context` + `tag_filter` を optional 追加 |
| `gaottt/store/cache.py` | `tag_to_ids: dict[str, set[str]]` reverse index を追加 (Phase H Stage 2 `source_by_id` と同 pattern)。`load_from_store` で documents.metadata から抽出、`index_documents` で同期、`evict_node` で clean up |
| `gaottt/core/gravity.py` | `propagate_gravity_wave` に `persona_context_ids` + `tag_filter_ids` 引数追加、seed step で additive injection (FAISS top-K + injection の union) |
| `gaottt/core/engine.py` | `query` に `persona_context` + `tag_filter` 引数追加、`propagate_gravity_wave` に渡す。auto-detect path は省略時のみ走る |
| `gaottt/services/memory.py` | `recall` 関数に新引数追加、engine.query に渡す |
| `gaottt/server/app.py` | RecallBody に新 field、endpoint で受け取り services.recall に渡す |
| `gaottt/server/mcp_server.py` | recall tool の引数に追加、`instructions` 文字列も更新 |
| `tests/integration/test_rest_parity.py` | tag_filter / persona_context の REST roundtrip |
| `tests/integration/test_mcp_*.py` | MCP 経由の挙動 |
| `tests/unit/test_persona_gravity.py` | additive injection の unit test |

**MCP/REST parity 鉄則対応**: 同じターン/コミットで両方公開。docs (`MCP-Reference-*` + `REST-API-Reference.md`) も同時更新。

### テスト戦略

**Unit**:
- `test_tag_filter_injection_unions_with_topk`: tag_filter で得た id が FAISS top-K に加わる
- `test_tag_filter_substring_or_match`: substring OR semantic
- `test_persona_context_overrides_autodetect`: 明示指定で auto-detect が無効化

**Integration**:
- `test_recall_tag_filter_surfaces_orphan_via_engine`: engine.query 経由で embedding 距離が遠い orphan ノードが tag_filter で surface する
- `test_recall_legacy_when_no_args`: 引数省略時は Stage 1 / source_filter なしの挙動と完全互換

**REST parity**:
- POST /recall に tag_filter / persona_context を含めた roundtrip 確認、MCP の formatter 出力と同じ id 順を expect

### Acceptance 判定基準 (本番 23k DB)

1. MCP `recall(query="Eleventy Pipeline", tag_filter=["harakiriworks-self-knowledge"])` で harakiriworks 系が top5 に **確実に** 出る (FAISS embedding 距離関係なく)
2. 7 query で tag_filter=["harakiriworks-self-knowledge"] 使用 → 正解 phase memory が top1 に来る率 ≥ 5/7
3. tag_filter 未使用時は Stage 1 までの挙動 (current 0/7) を維持 — backward compatibility

### Roll-back

Stage 2 は **API 引数追加のみ** で既存挙動を変えない。引数省略時は完全 Stage 1 互換。緊急時は LLM 側で tag_filter / persona_context を渡さなければ rollback 不要。

config レベルでの kill switch (`persona_explicit_enabled`) は **設けない** — Stage 1 と違って boost ではなく API field なので、引数を渡さなければ無効化される。

### Stage 2 で扱わないもの (Stage 3 候補)

- prefetch / explore への引数展開
- persona_context の TTL 検証 (active commitment の last_access ベース)
- tag の階層 / namespace (e.g., `harakiriworks/phase-4`)
- search-friendly filter (`tag_exclude`, `tag_filter_mode="and"`)

## Stage 3 — forced 内 query-aware ordering + prefetch/explore parity (2026-05-13 完遂)

### 設計動機

Stage 2 acceptance (2026-05-13 本番、7 query) で観察:
- ✅ **「各 query で harakiriworks 系が top5 に確実に出る」7/7 達成** (force injection が機能)
- ⚠️ **「正解 phase memory が top1 に来る率 ≥ 5/7」未達 (実測 1-2/7)**

機序: forced 内 5 件は engine.py Step 4 で `final_score` 順 (= raw + mass + wave + emotion + certainty)。当日繰り返し触った memory が mass + displacement の累積で勝つ → 「タグ一致」+「触りやすさ」が top に来る、「query との semantic 距離」は弱い signal だった。

この結果から retrieval geometry の **三段構造** が分離されて見えた:

| 段 | 役割 | 対応 Phase |
|---|---|---|
| 1. pool 入場 | embedding 距離 / 強制注入 | Phase J Stage 2 |
| 2. pool 内 rerank | mass / persona / cohort で重み付け | Phase H Stage 1 + Phase J Stage 1 + Phase K |
| 3. **forced 内 ordering** | **強制注入された候補同士の順位** | **Phase J Stage 3 (本 stage)** |

### 設計判断 2 軸

#### 1. forced 内 sort key — **raw_score (query semantic) を優先**

- (a) **raw_score 単独**: forced 内では純粋に query semantic で sort、tag 一致 + query 距離が直観的
- (b) final_score 単独 (Stage 2 現状): query と無関係な要素 (mass/wave/emotion/certainty) が dominant、acceptance 失敗
- (c) 重み付き: `β × raw + (1-β) × final` — 調整必要

**(a) raw_score 単独を採用**: 「caller が明示したタグ集合の中で、query に意味的に最も近いもの」が top1。シンプル、debug 容易、acceptance 改善が期待できる。final_score 順位は forced **外** には引き続き適用 (forced 既に注入されているので mass boost は無関係)。

#### 2. prefetch / explore に persona_context + tag_filter — **追加 (MCP/REST parity 鉄則)**

- prefetch: Stage 2 で recall に追加した引数を prefetch にも追加、これで「文脈を予測した pre-fire」が可能
- explore: 同じく追加、ただし default 挙動は cross-domain serendipity なので persona_context auto-detect は **off**
- types.py の PrefetchRequest / ExploreRequest を拡張、services + engine + server (両方) で公開

これは Phase J Stage 2 で recall に追加した引数の自然な拡張。CLAUDE.md MCP/REST parity 鉄則の対応。

### 実装範囲

| ファイル | 変更 |
|---|---|
| `gaottt/core/engine.py` | Step 4 の forced sort を `raw_score` 順に変更 + prefetch_query / explore に引数追加 |
| `gaottt/core/types.py` | PrefetchRequest + ExploreRequest に `persona_context` / `tag_filter` 追加 |
| `gaottt/services/memory.py` | services.prefetch + services.explore に引数を伝搬 |
| `gaottt/server/app.py` | /prefetch + /explore endpoint で受け取り |
| `gaottt/server/mcp_server.py` | prefetch + explore tool に引数追加 + docstring 更新 |
| `tests/integration/test_engine_pool_injection.py` | forced 内 ordering が raw_score 順、prefetch / explore parity |

API 表面の拡張のみで、Stage 1 / Stage 2 の core 機能には影響なし。Stage 2 acceptance が満たした「top5 surface」は維持しつつ、forced 内の top1 を query-aware にする。

### ハイパーパラメータ

Stage 3 は **新 config field なし** — API field のみの追加と内部 sort key の変更。

### Acceptance 判定基準

本番 23k DB で:
1. `recall(query, tag_filter=["harakiriworks-self-knowledge"])` で top5 が harakiriworks 系 (Stage 2 達成済を維持) ✅
2. **top1 が「query の semantic に最も近い harakiriworks memory」** に変わる
3. `prefetch(query, tag_filter=[...])` で recall と同じ結果が cache に乗る (parity)
4. 7 query の acceptance で top1 が「期待される正解 phase memory」に来る率 ≥ 5/7

### Roll-back

Stage 3 は **挙動変更が forced 内 sort key のみ** で、新 config field なし。緊急時の rollback は **コード変更を revert** する必要 (config kill switch なし)。ただし backward-compat は維持: Stage 1/2 の API は変わらず、prefetch/explore は新引数を省略時 Stage 0 挙動。

## Phase J 完遂宣言

Stage 1 (auto-detect graph traversal boost) + Stage 2 (explicit force injection) + Stage 3 (forced 内 query-aware ordering + prefetch/explore parity) で、**Phase J = Persona-Anchored Retrieval の core machinery は完成**。

残る候補 (将来の Phase J Stage 4+ or Phase L):
- persona_context の TTL 検証 (commitment last_access ベース)
- tag の階層 / namespace (e.g., `harakiriworks/phase-4`)
- tag_filter mode (AND, exclude)
- Reflect aspect "persona_field" 可視化

これらは Phase J の核 (人格層を retrieval geometry に翻訳) ではなく、運用面の細部。Phase J 完遂後の追加機能として独立に判断可能。

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
