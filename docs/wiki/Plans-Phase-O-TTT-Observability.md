# Plans — Phase O — TTT Observability

> 状態: **Phase O 全 5 stage 実装完了 (2026-05-14)**。Stage 1 (Score breakdown) / Stage 2 (Training delta trailer) / Stage 3 (Query routing) / Stage 4 (List mode) / Stage 5 (Dormant surface) で TTT loop の forward / backward / 認知負荷削減 / context 経済 / counter-importance sampling の 5 面が caller に literal に渡るようになった。設計同型 (`retrieval = gradient step`) は caller を含めて閉じ、Phase I Stage 4 本番 acceptance で観察された surface-form mismatch (Stage 3 が吸収)・context 圧迫 (Stage 4 が圧縮)・自己発信 memo の埋没 (Stage 5 が counter-importance で蘇生) の 3 大罠を機構レベルで防御。次は本番 acceptance で挙動観察 → 必要なら Stage 6 / Phase P 候補へ。
> 関連: [Roadmap](Plans-Roadmap.md), [Architecture — Gravity Model](Architecture-Gravity-Model.md), [Phase I — Free Star Movement](Plans-Phase-I-Free-Star-Movement.md), [Research — Gravity as Optimizer (TTT)](Research-Gravity-As-Optimizer.md), [Phase M — Mass Conservation](Plans-Phase-M-Mass-Conservation.md)
> 発端: 2026-05-14 セッション中の MCP usability 議論 — Phase I Stage 4 本番 acceptance で観察された「score deception」「persona invisibility」が **LLM caller の TTT 可視性欠如** に起因することを発見、めいさんの「MCP は君が使うものだから使いやすい形にしたい」発言を受けて設計

## 背景

GaOTTT の **中核となる設計同型** は以下の対応関係:

```
物理:    重力場での displacement 更新
TTT:    SGD の gradient step
生物:    Hebbian 強化 (recall された連合の強化)
```

Phase I Stage 2 (2026-05-11) で `compute_acceleration` に query attraction の第 4 項 `a = (α · score / m_i) · (q - pos_i)` を追加して、この対応が **解釈ではなく実装として literal に成立**した。recall するたびに retrieved nodes の displacement が query 方向に nudge される。

しかし — **LLM caller (= TTT の forward pass を駆動する agent) はこの training step が自分から見えない**。

- final_score 0.92 が返ってきたとき、それが cosine 由来か mass 由来か wave 由来か分からない
- recall で displacement / mass が動いたが、何が動いたかが見えない
- 「現在 active な commitment」を recall で問うても persona ノードが surface しない (`reflect(aspect=...)` を別途呼ぶ必要があると気付くまで認知負荷)
- 古い自分が書いた agent memory が dense cluster に埋もれて差し戻されない

これは **observability の欠如 = agency の欠如** という構造的問題。LLM が「自分が今どんな勾配を起こしたか」を見えてないと、自律的に judgement (score 信頼度、tool 選択、query 形式) できない。結果として:

- LLM 側で workaround (`source_filter` を毎回付ける、`reflect` を併用する) が必要
- workaround を忘れると Sonnet が発見した「score deception」「persona invisibility」が顕在化
- 「ブラックボックスの SGD で訓練されている人形」になる

## 仮説

**LLM caller を TTT loop の participant に昇格させる** — gradient (= 結果の計算根拠) と parameter update (= 結果が状態に与えた変化) の両方を recall response に literal に込めれば、caller 側 (LLM) は workaround なしに自律的判断ができる。

これは:
- [Phase M で確立した「source 分岐ゼロ・構造的識別子で全 source class に普遍適用」原則](Plans-Phase-M-Mass-Conservation.md) と整合する **caller-side の単一規則** — どの source でも同じラベル、どの query 形式でも同じ判定軸
- Five-Layer Philosophy の **関係層** を MCP layer に literal に翻訳する (人格層を `inherit_persona` で literal に表したのと同じ移植)
- 「使う側に見えないモデルは使う側に変えられない」(observability is agency) という設計倫理の物理実装

## Phase 全体の Stage 構成

| Stage | 提案番号 | 内容 | TTT 軸 | UX 軸 | 規模 |
|---|---|---|---|---|---|
| 1 | #1 | **Score breakdown** — final_score の additive 内訳を露出 | ✅ 強 (forward pass の中身) | ✅ 中 | 小 |
| 2 | #5 | **Training delta trailer** — recall response に状態変化を付与 | ✅ 強 (backward/update の中身) | ✅ 中 | 小-中 |
| 3 | #2 | **Query routing** — query 形式 classifier で recall + reflect を merge | ➖ 中 (caller 認知負荷を engine 側に移譲) | ✅ 強 | 中 |
| 4 | #3 | **List mode** — `recall(mode='list')` で id + excerpt[80] のみ | ➖ 弱 | ✅ 強 (context 経済) | 小 |
| 5 | #4 | **Dormant surface** — `explore(mode='dormant')` で再活性化 | ➖ 中 (counter-importance sampling) | ✅ 中 | 中 |

**実装順序**: 1 → 2 → 3 → 4 → 5 (TTT 同型を強化する順、UX 改善は後)

**default 挙動方針**:
- Stage 1 / 2: default ON (caller の TTT 参加は常時前提)
- Stage 3: default ON + opt-out flag `auto_route=false` (認知負荷削減は default で享受、predictable 挙動が欲しい呼び出し元は opt-out)
- Stage 4 / 5: 明示 opt-in (既存挙動を壊さない)

---

## Stage 1 — Score breakdown

### 観察

Phase I Stage 4 本番 acceptance (2026-05-14、Sonnet) で「**final_score 0.92 が semantic-unrelated content を伴う**」事象が複数 query で再現:

- Q「Phase I Stage 4 Mass-dependent Hooke の設計」→ 奈良の道路 like ツイートが top-1、score 0.92
- LLM caller (Claude / Sonnet) は score 0.92 を見て一瞬「これが正解か?」と判断し得る

### 機序

`final_score` は内部で additive な構成要素の和:

```
final_score = wave_score
            + mass_boost (α · log(1+mass))           # Phase H Stage 1
            + persona_boost (α_persona · proximity)  # Phase J Stage 1
            + bm25_boost (RRF rank fusion)           # Phase L Stage 1
            + emotion_term (α_emotion · |emotion|)   # F7
            + certainty_term (α_certainty · cert)    # F7
            + raw_cosine                             # base semantic
```

各項は `gaottt/core/engine.py` の scoring loop で計算されているが、QueryResultItem には `final_score` と `raw_score` (= virtual cosine) の 2 数しか出ない。**項別の貢献度が caller に見えない**。

### 仮説

各項を additive list として返せば、caller (LLM) は:
- 「これは mass 60% + cosine 20% + wave 20% で勝ってる、semantic 寄与は低い」と一発で読める
- score 0.92 の中身が「mass-boost 0.78 + cosine 0.14」だと分かれば、Sonnet Q2 の罠を `if breakdown.cosine < 0.3: skip` 的に literal に避けられる
- Phase D / J で declared した persona と一致したのか、graph 距離が近いだけなのかも区別可能

### 物理モデル / 実装

新規 Pydantic model:

```python
class ScoreBreakdown(BaseModel):
    """Additive decomposition of final_score for TTT-aware caller."""
    raw_cosine: float          # base semantic similarity (raw FAISS)
    virtual_cosine: float      # raw_score (= query · virtual_pos)
    wave_score: float          # gravity wave propagation result
    mass_boost: float          # α · log(1+mass) component
    persona_boost: float       # α_persona · proximity (0 if not declared)
    bm25_boost: float          # RRF lexical match contribution (0 if no BM25 hit)
    emotion_term: float        # F7 emotion weighting
    certainty_term: float      # F7 certainty weighting
    forced_boost: float        # tag_filter / persona_context inject bonus

    @property
    def expected_sum(self) -> float:
        return (
            self.raw_cosine + self.wave_score + self.mass_boost
            + self.persona_boost + self.bm25_boost
            + self.emotion_term + self.certainty_term + self.forced_boost
        )
```

QueryResultItem に `score_breakdown: ScoreBreakdown | None` を attach (None は legacy fallback 用)。engine.query の scoring loop で各項を捕捉し、final_score 確定時に同じ値で breakdown を埋める。

| ファイル | 変更 |
|---|---|
| `gaottt/core/types.py` | `ScoreBreakdown` model + `QueryResultItem.score_breakdown` 追加 |
| `gaottt/core/engine.py` | scoring loop で各項を local dict に捕捉、QueryResultItem 構築時に attach |
| `gaottt/services/formatters.py` | MCP 用に「`final=X (cos=A wave=B mass=C persona=D bm25=E)`」形式の 1 行を追加 |
| `gaottt/server/app.py` | REST は `ScoreBreakdown` を JSON でそのまま返す (Pydantic がシリアライズ) |

### ハイパーパラメータ

なし (純粋な observability)。

### 期待挙動

- final_score が 0.92 で `breakdown.raw_cosine = 0.14` なら「semantic 弱いが mass で勝ってる」と一発判定
- persona_boost > 0 なら「declared な persona と graph 接続してる」が見える
- bm25_boost > 0 なら「surface form 一致」が見える
- breakdown.expected_sum と final_score の差は scaling/normalization 由来 (engine の RRF fusion 等)、tolerance を doc 化

### テスト

- Unit (`tests/unit/test_score_breakdown.py`):
  - `breakdown.expected_sum ≈ final_score` (atol=0.01 程度、RRF 正規化の余裕)
  - mass=0, persona 無接続, BM25 一致なし の場合は対応項が 0
  - emotion/certainty が 0 ならその項も 0
- Integration (`tests/integration/test_engine_score_breakdown.py`):
  - 同 query を 2 回 recall → breakdown が決定論的に同値
  - tag_filter inject 時に `forced_boost > 0`
  - MCP/REST parity (両者で同 breakdown が返る)

### Roll-back

- score_breakdown は **always attached** だが、既存 final_score / raw_score も並行で残るので caller は無視可能
- 緊急時の completion suppress 用に config `expose_score_breakdown: bool = True` を置き、False で `None` を返す

### 実装メモ (2026-05-14)

設計 draft からの修正点:
- 原案では `persona_boost` / `bm25_boost` を additive 項として独立露出する想定だったが、実装では両者は `_seed_boost` (`gaottt/core/gravity.py`) 経由で `wave_score` に baked-in されており、独立 additive 項として再分離できなかった。代わりに **informational field** として `persona_proximity` (float) と `bm25_contributed` (bool) を露出 — 「persona/bm25 が seed に効いたか」を caller が判定できる
- 加えて Plan draft で抜けていた `decay_factor` と `saturation` (multiplicative) を露出。これがないと `expected_sum` で `final_score` を再現できない
- `expected_sum` プロパティは `(virtual_cosine * decay_factor + wave_score + mass_boost + emotion_term + certainty_term) * saturation` を返し、unit/integration tests で rel_tol=1e-4 / abs_tol=1e-6 以内に `final_score` と一致を確認
- `forced_inclusion` を informational bool として追加 — `tag_filter` / `persona_context` で強制注入されたかどうかを caller が判定可能
- MCP formatter は既存 `[i] id=...` 行の **下に新規 1 行** で挿入 ("score_breakdown" key prefix)、既存 substring assertion を壊さない方針 (CLAUDE.md「MCP formatter の出力文字列を変えない」)
- REST レスポンスは Pydantic auto-serialize で `items[].score_breakdown` に dict 出る ([REST-API-Reference.md](REST-API-Reference.md) 参照)
- `bm25_hit_ids` 算出は scoring loop の外で 1 回だけ BM25 検索することで O(reached_ids) のチェックに収束 — hot path overhead は 1 回の BM25 query のみ

ファイル変更:
- `gaottt/core/types.py` — `ScoreBreakdown` Pydantic model 新設 (11 field + `expected_sum` プロパティ)、`QueryResultItem.score_breakdown` / `MemoryItem.score_breakdown` を optional で追加
- `gaottt/core/engine.py` — `_query_internal` の scoring loop で breakdown 構築 + BM25 hit set 事前計算
- `gaottt/services/memory.py` — `_to_memory_item` で QueryResultItem → MemoryItem 移行時に breakdown を pass-through
- `gaottt/services/formatters.py` — `_format_breakdown` ヘルパ + `format_recall` 全 output_mode (full/compact/ids) で breakdown 行を挿入
- `gaottt/config.py` — `expose_score_breakdown: bool = True` 追加

テスト:
- `tests/unit/test_score_breakdown.py` (8 test) — additive 構造、informational field 分離、defaults、serialization
- `tests/integration/test_engine_score_breakdown.py` (6 test) — engine.query 経由で breakdown attach、`expected_sum ≈ final_score`、`expose_score_breakdown=False` での `None` fallback、`forced_inclusion` の tag_filter 連動、persona_proximity の zero default、決定論性
- `tests/integration/test_rest_memory.py` — REST `/recall` レスポンスの score_breakdown JSON 検証
- `tests/integration/test_mcp_tools.py` — MCP recall output に breakdown 行の substring を assert (cos= / vcos= / decay= / wave= / mass= / sat= / persona_prox=)

検証結果: full test suite 335 passed (Stage 1 関連 +14 新規)、`scripts/rest_smoke.py` + `scripts/mcp_smoke.py` 両方 green。pre-existing flaky 2 件 (`test_query_kick_drifts_displacement_toward_query` / `test_stage3_gate_dampens_drift_for_new_nodes`) は Phase I 由来で Stage 1 非関連。

---

## Stage 2 — Training delta trailer

### 観察

Phase I Stage 2 で「retrieval = gradient step」が実装として literal に成立したが、recall 後の state 変化 (displacement / mass / supernova trigger) は recall response に出ない。LLM caller は自分が起こした training step が **完全に invisible**。

これは [Research — Gravity as Optimizer (TTT)](Research-Gravity-As-Optimizer.md) で議論した「retrieval は gradient signal の Verlet 積分」の **caller-side closure** の欠落。

### 機序

`engine._update_simulation` (`gaottt/core/engine.py`) で:
- 各 reached node の displacement が update
- 各 reached node の mass が update (Phase M self-force filter 経由)
- supernova が batch で trigger される場合あり (これは index_documents path、recall path とは別)
- wave reach count / wave depth / persona_hop reach count

これらは internal state を変えるが、response に出ない。

### 仮説

「自分が今この memory を 3 回 recall して mass +0.15 押し上げた、意図的に重力場を曲げてる」と caller が自覚できれば、deliberate な training が可能になる:
- 重要な memory を意図的に「育てる」 (rehearsal anchor として強化)
- 不要に touch しすぎた memory に対する自己抑制
- session 越しの自分の training 履歴をトレース可能

### 物理モデル / 実装

新規 Pydantic model:

```python
class TrainingDelta(BaseModel):
    """State changes induced by this recall — TTT update visibility."""
    displacement_changes: dict[str, float]  # node_id -> Δ|displacement|
    mass_changes: dict[str, float]          # node_id -> Δmass
    wave_reached_count: int                 # total nodes touched by wave
    wave_max_depth: int                     # actual depth reached
    persona_hop_reached: int                # nodes reached via persona graph
    supernova_triggered: bool               # always False for recall (kept for parity with ingest path)
```

QueryResponse に `training_delta: TrainingDelta | None` を attach。冗長を避けるため:

- `displacement_changes` / `mass_changes` は **top_k 結果に該当する node のみ** (top_k=10 なら最大 10 entries × 2 = 20 floats)
- wave 全体の reach count は 1 整数で要約
- 全 reached node の delta は出さない (context 経済)

| ファイル | 変更 |
|---|---|
| `gaottt/core/types.py` | `TrainingDelta` model + `QueryResponse.training_delta` 追加 |
| `gaottt/core/engine.py` | `_update_simulation` を refactor して delta dict を return、`query` で TrainingDelta を組み立て |
| `gaottt/services/memory.py` | recall service が TrainingDelta を pass through |
| `gaottt/services/formatters.py` | MCP 用に「## 訓練差分」セクション (Δmass top 3 + wave reach count) を追加 |
| `gaottt/server/app.py` | REST は TrainingDelta を JSON で返す |

### ハイパーパラメータ

`training_delta_topk_only: bool = True` — False にすると全 reached node の delta を返す (debug / observability mode)。default True で context 経済を守る。

### 期待挙動

- 連続 recall で同 memory の `mass_changes` が累積 (+0.003, +0.002, +0.001, ... と減衰)
- no-op recall (空の corpus) で displacement_changes / mass_changes が空 dict
- persona_hop_reached > 0 なら「declared persona の graph traversal が効いた」が見える
- supernova_triggered は recall path では常に False (ingest path 専用、parity 用の field)

### テスト

- Unit (`tests/unit/test_training_delta.py`):
  - 同 query × 連続 recall で `mass_changes[id]` が累積し、`displacement_changes[id]` の符号が一致
  - 全 query_kick_enabled=False で `displacement_changes` が空または極小
- Integration (`tests/integration/test_engine_training_delta.py`):
  - Phase I Stage 2 の query attraction で displacement_changes が query 方向に正
  - Phase J persona_hop が active なら persona_hop_reached > 0
  - MCP/REST で同 delta が返る (parity)

### Roll-back

- `training_delta_enabled: bool = True` 設定で全停止、`training_delta: None` 返却
- 既存 QueryResponse の他 field は変更しないので legacy caller への影響なし

### 実装メモ (2026-05-14)

設計 draft からの修正点:
- 原案では `QueryResponse.training_delta` に attach する想定だったが、QueryResponse は MCP プロトコル後方互換で MemoryItem を含まない素の `list[QueryResultItem]` の wrapper であり、現実装の MCP/REST 両 path は **services 層の `RecallResponse` / `ExploreResponse`** を返している。実装では `RecallResponse` / `ExploreResponse` に attach。
- engine.query の return type は維持 (`list[QueryResultItem]`)、新たに **optional `out_training_delta: dict | None = None` パラメータ** を engine.query / `_query_internal` に追加 — caller が dict を渡せば engine が in-place に埋める。これで既存 caller (test / 内部呼び出し) は影響を受けない。services 層が dict を作って engine に渡し、`_delta_from_dict()` で `TrainingDelta` model に変換
- Plan draft で抜けていた **`cache_hit` bool field** を追加 — prefetch cache hit 時は simulation が走らないので「触れた node が無い」のではなく「update を suppress した」を caller が区別できる必要がある (本番の prefetch ヒット率高い環境では mass_changes={} が頻発するので、cache_hit=True で意味の区別が必須)
- Plan draft の `topk_only` config が「default True」だけだったので、Pydantic model にも `topk_only: bool = True` field を露出し、caller が「これは top-k のみの delta だ」を responseから直接読める設計に
- snapshot は `_update_simulation` 呼び出しの直前 / 直後で `cache.get_displacement()` + `state.mass` を取得し差分を計算。`topk_only=True` (default) では `result_ids` の node のみ、`False` では `all_reached_ids` 全件
- `persona_hop_reached` は `persona_proximities.get(nid, 0.0) > 0.0` を満たす reached node の count
- MCP formatter は recall body の **末尾に新規 `## 訓練差分` セクション** を append。既存 substring assertion を壊さない方針 (CLAUDE.md「MCP formatter の出力を変えない」)
- REST レスポンスは Pydantic auto-serialize で `training_delta` に dict 出る

ファイル変更:
- `gaottt/core/types.py` — `TrainingDelta` Pydantic model 新設 (8 field)、`RecallResponse.training_delta` / `ExploreResponse.training_delta` を optional で追加
- `gaottt/core/engine.py` — `query` / `_query_internal` に `out_training_delta: dict | None = None` を追加、`_update_simulation` 前後で snapshot + delta 計算、cache hit path で `cache_hit=True` を populate
- `gaottt/services/memory.py` — `_delta_from_dict()` ヘルパ + `recall()` / `explore()` で dict 作成 → engine 渡し → `TrainingDelta` 変換
- `gaottt/services/formatters.py` — `_format_training_delta()` ヘルパ + `format_recall()` / `format_explore()` 末尾に trailer 追加。cache_hit / top movers / coverage label の 3 ケース対応
- `gaottt/config.py` — `training_delta_enabled: bool = True` + `training_delta_topk_only: bool = True` 追加

テスト:
- `tests/unit/test_training_delta.py` (9 test) — model defaults / serialization / formatter (cache hit / top movers / coverage label / None) / format_recall trailer attachment
- `tests/integration/test_engine_training_delta.py` (7 test) — recall response carries delta、consecutive recalls accumulate Δmass、`training_delta_enabled=False` で `None` fallback、`topk_only=False` の full coverage、cache hit path、explore parity
- `tests/integration/test_rest_memory.py` — REST `/recall` レスポンスの `training_delta` JSON 検証 (8 field 全部 + cache_hit=False / supernova_triggered=False)
- `tests/integration/test_mcp_tools.py` — MCP recall output に `## 訓練差分` trailer の substring を assert (`wave_reached=` / `depth=` / `persona_hop=`)

検証結果: full test suite 355 passed (Stage 2 で +20 新規)、`scripts/rest_smoke.py` + `scripts/mcp_smoke.py` 両方 green。pre-existing flaky 2 件は今回 pass。

---

## Stage 3 — Query routing (recall + reflect merge)

### 観察

Sonnet 本番 acceptance:
- Q「現在 active な commitment」→ recall は startup-diagnostic 設計案を返した。**正解は `reflect(aspect='commitments')`** だが、LLM caller がそれを毎回判断する必要がある = 認知負荷
- Q「持っている value と intention」も同様 — declared persona は `reflect` で出るが、`recall` では surface しにくい

### 機序

LLM caller は query semantic を見て「これは structured な状態問い合わせか、free-form な意味検索か」を毎回判断する。判断ロジックは:

- "現在 active な X" / "今やってる X" → reflect(aspect='tasks_doing')
- "完了した X" → reflect(aspect='tasks_completed')
- "持ってる Y" / "declared な Z" → reflect(aspect='values' / 'intentions' / 'commitments')
- 自由文 → recall

これは tool 側で判定可能な **query 形式 (構文) 由来** のパターン分岐 — **source 分岐ゼロの原則を破らない**。

### 仮説

query 形式の classifier を engine 側に持ち、structured 質問は `recall` の裏で対応する `reflect` を走らせて結果に merge。caller (LLM) は何も気にせず `recall(text=...)` を叩けば良い。

### 物理モデル / 実装

新規 `gaottt/services/query_routing.py`:

```python
# Regex / heuristic patterns. Single-rule (query syntax based), no source branching.
PATTERNS = [
    (r"現在.*active.*(commitment|約束)", "commitments"),
    (r"持(って|つ).*value|価値観",        "values"),
    (r"持(って|つ).*intention|意図",      "intentions"),
    (r"持(って|つ).*commitment|約束",     "commitments"),
    (r"今やって(る|いる)|active.*task",   "tasks_doing"),
    (r"完了.*task|終わった.*作業",         "tasks_completed"),
    # ... 必要に応じて拡張
]

def detect_aspect(query: str) -> str | None:
    for pat, aspect in PATTERNS:
        if re.search(pat, query, re.IGNORECASE):
            return aspect
    return None
```

recall service が aspect 検出されたら:
1. 通常の `recall` を実行 (top_k 結果)
2. 並行して `reflect(aspect)` を実行 (要約)
3. response に `routing_hint: {"aspect": "commitments", "reflect_summary": "..."}` を attach

MCP formatter は「## 関連 reflect サマリ (auto-routed)」セクションを追加。

| ファイル | 変更 |
|---|---|
| `gaottt/services/query_routing.py` | 新設 — pattern → aspect の classifier |
| `gaottt/services/memory.py` | recall service が auto_route flag (default True) で reflect を併走 |
| `gaottt/core/types.py` | `RoutingHint` model + `QueryResponse.routing_hint` 追加 |
| `gaottt/services/formatters.py` | MCP 用 routing_hint セクション |
| MCP/REST | `recall` request に `auto_route: bool = True` flag 追加 |

### ハイパーパラメータ

- `auto_route_enabled: bool = True` (global off switch in config)
- recall request 側の `auto_route: bool = True` (per-call opt-out)

### 期待挙動

- 「現在 active な commitment」→ recall top-K + reflect_summary に commitment list が併走
- 「Articulation as Carrier の物理」→ pattern 一致なし、reflect 走らず通常の recall のみ
- 認知負荷が薄まる: LLM caller は free-form query を投げるだけで良い

### テスト

- Unit (`tests/unit/test_query_routing.py`):
  - 各 pattern の正例 / 反例
  - 正規表現衝突がない (同 query が複数 aspect に match しない)
- Integration (`tests/integration/test_engine_query_routing.py`):
  - "現在 active な commitment" で reflect_summary に declared commitment が含まれる
  - 自由文 query で routing_hint が None
  - auto_route=False で legacy 挙動

### Roll-back

- `auto_route=False` で per-call opt-out
- `auto_route_enabled=False` で global off

### 実装メモ (2026-05-14)

設計 draft からの修正点:
- 当初 pattern 数は draft の 6 例から開始する想定だったが、JP + EN 両言語対応 + word boundary (`\b`) を入れた結果 **15 patterns** に拡大。具体的には: commitments (5), values (2), intentions (2), tasks_doing (2), tasks_completed (1), tasks_abandoned (1), tasks_todo (1), relationships (2)。word boundary を入れた理由は単語 "abandoned" が substring "done" を含み `done.{0,8}task` に match して `tasks_completed` に誤 route していた事例 — 同じ罠を防ぐため英単語は `\b(?:keyword1|keyword2|...)\b` で wrap、日本語語幹は word boundary 不要
- 当初 `RoutingHint` model は draft の `aspect` + `reflect_summary` の 2 field だったが、実装では **`pattern_matched`** と **`auto_routed`** を独立 bool に追加。これで caller は「router が off だった (config off or per-call false)」と「pattern に一致しなかった (free-form query)」を `RoutingHint` から区別可能。Stage 2 で学んだ「未動作と非ヒットを混ぜないために field を分離する」原則 (cf. `cache_hit`) と同じ精神
- `reflect` aspect dispatch は MCP server 内 `_reflect_dispatch` に閉じていたが、Stage 3 で auto-router が同じ dispatch を呼ぶ必要が生じたため **`services/reflection.dispatch_aspect()` に集約**。MCP server `_reflect_dispatch` は薄い委譲 wrapper に縮小、aspect 追加時に 1 箇所だけ編集すれば server + auto-router 双方に反映される (drift 防止)
- formatter は recall body 末尾に `## 関連 reflect サマリ (auto-routed)` セクションを append。**items が 0 件 (`No memories found.`) でも routing summary は surface する** — これは Stage 3 の存在意義そのもの: 「free-form recall が空でも、surface form が aspect query なら reflect 結果で代替する」
- legacy `/query` endpoint (Phase A 互換) は `auto_route=False` 固定。legacy caller は最小コストで動くまま、新 path だけが auto-routing を享受する

ファイル変更:
- `gaottt/services/query_routing.py` — 新設、`_PATTERN_DEFS` (15 entries)、`detect_aspect()`、`KNOWN_ASPECTS` (8 aspect 名 tuple)、`pattern_count()`
- `gaottt/core/types.py` — `RoutingHint` Pydantic model 新設 (4 field)、`RecallRequest.auto_route` / `ExploreRequest.auto_route` を default `True` で追加、`RecallResponse.routing_hint` / `ExploreResponse.routing_hint` を optional で追加
- `gaottt/services/reflection.py` — `dispatch_aspect()` を追加 (既存 aspect 関数を集約呼び出し + formatter wrap)
- `gaottt/services/memory.py` — `_build_routing_hint()` ヘルパ追加、`recall()` / `explore()` に `auto_route` 引数追加、`RoutingHint` を response に attach、`services` から `query_routing` / `reflection` を import
- `gaottt/services/formatters.py` — `_format_routing_hint()` ヘルパ追加、`format_recall()` / `format_explore()` に trailer attach (item 0 件パスでも呼び出す)
- `gaottt/server/mcp_server.py` — `recall` / `explore` tool に `auto_route: bool = True` 追加 + docstring、`_reflect_dispatch` を `reflection_service.dispatch_aspect` への委譲に変更
- `gaottt/server/app.py` — `/recall` / `/explore` で `request.auto_route` を service に pass-through、legacy `/query` は `auto_route=False` 固定
- `gaottt/config.py` — `auto_route_enabled: bool = True` 追加

テスト:
- `tests/unit/test_query_routing.py` (12 test) — pattern positive/negative の網羅、aspect overlap 無し、free-form query が `None` を返す、`KNOWN_ASPECTS` との name drift 検証
- `tests/unit/test_routing_hint_formatter.py` (7 test) — `_format_routing_hint` の None / `auto_routed=False` / 正常パス、`format_recall` / `format_explore` の trailer 連動、**items 0 件でも summary surface** の核挙動
- `tests/integration/test_engine_query_routing.py` (7 test) — recall service が aspect match した時 `RoutingHint.reflect_summary` に対象 content の substring が出る、`auto_route=False` で `reflect_summary=None`、config off で同様、explore parity、formatter 連動、free-form query で trailer 無し
- `tests/integration/test_rest_memory.py` — `/recall` レスポンスの `routing_hint` JSON 検証 (4 field 全部、`auto_route=False` で `reflect_summary=null`)
- `tests/integration/test_mcp_tools.py` — MCP recall output に `## 関連 reflect サマリ` trailer + `auto-routed` + aspect 名 (`commitments`) の substring を assert、free-form query で trailer 無しを assert

検証結果: full test suite 424 passed, 1 pre-existing flaky (`test_stage3_gate_dampens_drift_for_new_nodes` — Phase I Stage 2 timing fragility、isolation で pass、Stage 3 非関連)、Stage 3 で +27 新規。`scripts/rest_smoke.py` + `scripts/mcp_smoke.py` 両方 green。

---

## Stage 4 — List mode (`recall(mode='list')`)

### 観察

`recall(top_k=10)` で大きな content chunk が返ると、LLM の context window を急速に食う (1 chunk 数百 tokens × 10)。多くの場合 caller は「ざっと scan して 1-2 件深掘りしたい」だけ。

### 機序

QueryResultItem は常に full content を返す。caller は excerpt を手動で truncate するか、別 tool で id 指定 fetch する必要がある。

### 仮説

`recall(mode='list')` で `(id, source, mass, excerpt[80], final_score, score_breakdown)` だけ返せば:
- top_k=20 でも 100 KB を遥かに下回る
- 「list で scan → 興味あれば detailed recall で深掘り」の 2-step pattern が成立
- context 経済 + 探索ストレスの低減

### 物理モデル / 実装

| ファイル | 変更 |
|---|---|
| `gaottt/core/types.py` | `QueryResultItem` に optional `excerpt: str` field (mode='list' でこちらが埋まり content が None)、`mode: 'detail' \| 'list'` を request に追加 |
| `gaottt/services/memory.py` | recall service が mode='list' なら content の頭 80 char を excerpt に詰めて content=None で返す |
| `gaottt/services/formatters.py` | MCP 用 list mode 専用 formatter (table 風) |
| MCP/REST | `recall` request に `mode: 'detail' \| 'list' = 'detail'` 追加 |

### ハイパーパラメータ

- `list_mode_excerpt_chars: int = 80` (config で調整可、80 で 1 行表示しやすい)

### 期待挙動

- `recall(text=..., top_k=20, mode='list')` で全結果が 1 行 × 20 行で返る
- detail mode と list mode で final_score 順序は完全一致 (rerank しない)
- 既存 caller (mode 省略) は detail mode で legacy 挙動

### テスト

- Unit (`tests/unit/test_recall_list_mode.py`):
  - mode='list' で content が None / excerpt が 80 char 以下
  - excerpt が改行を含まない (1 行で表示できる)
- Integration (`tests/integration/test_engine_recall_list_mode.py`):
  - list mode と detail mode で同 query が同 id 順序を返す
  - MCP/REST parity

### Roll-back

- mode='detail' が default、list は明示 opt-in
- 既存 caller への影響ゼロ

### 実装メモ (2026-05-14)

設計 draft からの修正点:
- 当初 draft では `QueryResultItem` に optional `excerpt: str` field を追加して `content=None` にする想定だったが、Pydantic schema 互換性 (既存テストや caller の MemoryItem.content 期待) を守るため **content 自体を truncate する方式** に変更。新 field 追加なし → 既存 caller への影響ゼロ
- truncation は MCP formatter ではなく **service 層** (`_to_memory_item` の `excerpt_chars` kwarg) で実行。MCP の `output_mode` (formatter 側 truncate) との区別を明確化:
  - `mode` (Stage 4) = **service 層 = wire 上の payload**: REST/MCP 両方に効く、context 経済の本来意図
  - `output_mode` = **MCP formatter 表示制御**: 文字列表示の控除のみ、wire payload は変わらない
- 改行 (LF / CR) を空白に collapse — 1 行 per result の scan 用途に必須
- 既存 `output_mode="compact"` (300 字 trunc) との関係: `mode='list'` (80 字) は context-tight な用途、`output_mode='compact'` は MCP 表示時の overflow 防止。**両方指定可** (`recall(mode='list', output_mode='full')` で 80 字 wire + フォーマッタは "full" モードで通す)

ファイル変更:
- `gaottt/config.py` — `list_mode_excerpt_chars: int = 80` 追加
- `gaottt/core/types.py` — `RecallRequest.mode: str = "detail"` 追加 (`"detail"` / `"list"` の 2 値)
- `gaottt/services/memory.py` — `_to_memory_item()` に `excerpt_chars: int | None = None` kwarg 追加、`recall()` に `mode: str = "detail"` 追加、`mode == "list"` のとき `config.list_mode_excerpt_chars` で truncate
- `gaottt/server/mcp_server.py` — MCP `recall` tool に `mode: str = "detail"` arg + docstring
- `gaottt/server/app.py` — REST `/recall` で `request.mode` を service に pass-through

テスト:
- `tests/unit/test_recall_list_mode.py` (5 test) — `_to_memory_item` 単体 (detail mode 不変、list truncate、newline collapse、short content untouched、empty safe)
- `tests/integration/test_engine_recall_list_mode.py` (5 test) — service 経由で list mode が **全結果** を truncate、detail は full、両 mode で id 順序一致 (rerank しない)、config overridable、score_breakdown 維持
- `tests/integration/test_rest_memory.py` — REST `/recall` で `mode='list'` 時に items 全部 80 字以内 + 改行無し
- `tests/integration/test_mcp_tools.py` — MCP `recall(mode='list')` で 500 字 long_text が出力に含まれない

---

## Stage 5 — Dormant surface (`explore(mode='dormant')`)

### 観察

自分が書いた agent memory (commit / value / intention / note) が一度 surface しなくなると、dense cluster (tweet / like / file) に raw FAISS で押し負け、忘れられたまま。Phase I Stage 4 受け入れ検証 + Sonnet finding で「persona/agent surface しない」現象として観察。

### 機序

`mass` は recall されるほど育つので、recall されない agent memory は **永久に低 mass のまま raw cosine 弱者として埋もれる** 一方。 forget はしないが「埋もれる自由」の対をなす「思い出される自由」が機構として欠落。

### 仮説

「忘れていたものを差し出す」 explicit mode を `explore` に追加:

- 条件: `(age >= N days) AND (mass <= θ_dormant) AND (source IN {agent, value, intention, commitment, note})`
- source 列挙は **branching ではなく「自己発信 memory class」の構造的定義** — Phase D persona 層と同じ structural identifier
- 1 件ランダムに返す (毎回違う dormant memory が出る)

### 設計判断: source 列挙は単一規則違反か

**結論: 違反ではない**。理由:

- Phase M の「source 分岐ゼロ」原則は「**physics rule で source class を gate 変数として branching しない**」を意味する (mass update / Hooke / kick の式に source が入らない)
- Stage 5 の source 列挙は **physics ではなく query intent**: 「自分が能動的に書いた memory」という structural class の定義
- これは [[feedback-no-source-branching]] で警告した「θ や β を source 別 dict にする」とは異なる — physics rule は uniform、source は **filter** として使われるだけ
- Phase D persona 層 (value / intention / commitment) は MCP の `declare_*` で literal に書かれた「self-authored class」であり、これを ID 一覧として持つことは Phase J の `inherit_persona` と同じ思想

念のため Plans-Phase-N 内で **「source は filter であり gate ではない」**ルールを明文化し、将来の Stage で θ/β を source 別にしたくなる衝動を再警告する。

### 物理モデル / 実装

| ファイル | 変更 |
|---|---|
| `gaottt/core/types.py` | `explore` request に `mode: 'serendipity' \| 'dormant' = 'serendipity'` 追加 |
| `gaottt/services/memory.py` | dormant mode で SQL クエリ: `WHERE last_access < ? AND mass <= ? AND source IN (...) ORDER BY RANDOM() LIMIT 1` |
| `gaottt/server/mcp_server.py` | `explore` tool description 更新 |
| `gaottt/server/app.py` | REST explore endpoint に mode flag |
| `gaottt/services/formatters.py` | MCP dormant 出力に「💭 forgot memory surfaced: ...」プレフィクス |

### ハイパーパラメータ

- `dormant_age_threshold_seconds: float = 7 * 86400.0` (7 日 default、2026-06-01 に 30d から昇格 — active-user corpus で 30d は pre-filter 0 件にする、`project_proxy_backend_env_not_delivered` 参照)
- `dormant_mass_threshold: float = 2.0` (mature gate point 未満、`dormant_mass_percentile=10.0` 設定時はそちら優先)
- `dormant_source_classes: list[str] = ["agent", "value", "intention", "commitment", "note", "reference"]` — **structural identifier list、physics ではない**

### 期待挙動

- `explore(mode='dormant')` で 30 日以上未参照かつ mass ≤ 2 の自己発信 memory が 1 件返る
- 条件に合致する memory がない場合は empty (False positive を避けるため synth しない)
- 連続呼び出しで `ORDER BY RANDOM()` により別の memory が出る (saturation 自然解消)

### テスト

- Unit (`tests/unit/test_explore_dormant.py`):
  - condition (age / mass / source) の filter ロジック
  - source 列挙に含まれない node (tweet / file) は出ない
  - 空 result 時に exception ではなく empty を返す
- Integration (`tests/integration/test_engine_explore_dormant.py`):
  - 30 日経過した agent memory を 1 件 inject → dormant で出る
  - 同 memory を recall すれば mass + last_access が更新され dormant から外れる
  - serendipity mode との parity (mode 切替で挙動差)

### Roll-back

- mode='serendipity' default、dormant は明示 opt-in
- 全 dormant_* config は既存 explore に影響なし

### 実装メモ (2026-05-14)

設計 draft からの修正点:
- 当初 draft では SQL クエリ `WHERE last_access < ? AND mass <= ? AND source IN (...) ORDER BY RANDOM() LIMIT 1` の想定だったが、実装では **cache + store を Python 側で走査する方式** に変更。理由: `cache.get_all_nodes()` は既に in-memory で last_access/mass/is_archived を持っているので追加 I/O ゼロ、`store.get_document()` は metadata.source を取るための per-node call (~1k node 規模で十数 ms)。`reflection.py` の `_gather_by_source` と同じ pattern で実装統一感
- `random.sample(k=top_k)` で複数件返す — draft の `LIMIT 1` より usable (caller が `top_k=5` で 5 件の dormant 候補を一度に scan できる)。複数候補の中から `recall(query=..., top_k=1, mode='detail')` で深掘り、という Stage 4 と組み合わせた 2-step pattern が成立
- 専用 formatter `format_explore(result, mode='dormant')` を追加 — `final_score` は wave-free で意味がないため出力しない、`💭 Dormant memories surfaced (N):` prefix で「これは serendipity ではなく counter-importance だ」を明示
- `query` は **request shape の互換性維持** のため `min_length=1` のまま (Pydantic 制約変更は破壊的)、**service は ignore** とドキュメント化。caller は `"_ignored"` 等を渡す
- `training_delta` / `routing_hint` は dormant mode では常に `None` — wave 走らず TTT update も発生しない、aspect 意図も推定しない。「dormant は別 operation」を response shape でも明示

ファイル変更:
- `gaottt/config.py` — `dormant_age_threshold_seconds`、`dormant_mass_threshold`、`dormant_source_classes` の 3 設定追加
- `gaottt/core/types.py` — `ExploreRequest.mode: str = "serendipity"` 追加 (`"serendipity"` / `"dormant"` の 2 値)
- `gaottt/services/memory.py` — `_dormant_surface()` ヘルパ新設 (cache + store 走査 + 3 条件 filter + `random.sample`)、`explore()` で `mode == "dormant"` のとき早期 return
- `gaottt/services/formatters.py` — `format_explore()` に `mode: str = "serendipity"` arg、dormant 専用 branch で wave-free output
- `gaottt/server/mcp_server.py` — MCP `explore` tool に `mode: str = "serendipity"` arg + docstring、format_explore に mode pass-through
- `gaottt/server/app.py` — REST `/explore` で `request.mode` を service に pass-through

テスト:
- `tests/integration/test_engine_explore_dormant.py` (7 test) — old + low mass + self-authored で surface、recent (1d) で除外、high mass (10.0) で除外、tweet / file source で除外、empty result 安全、`training_delta` / `routing_hint` が None、全 6 source class が surface 候補に乗る (5 回 sample で全て出る)
- `tests/integration/test_rest_memory.py` — REST `/explore` で dormant 専用 helper (`app_engine_from_request_state`) を使い `state.last_access` を直接 backdate、dormant id が response items に乗る、`training_delta` / `routing_hint` が `None`
- `tests/integration/test_mcp_tools.py` — MCP `explore(mode='dormant')` で `Dormant memories surfaced` prefix or empty fallback

検証結果: full test suite **445 passed, 1 skipped** (pre-existing flaky 0 件)、`scripts/rest_smoke.py` + `scripts/mcp_smoke.py` 両方 green。Stage 4+5 で +17 新規テスト (5 unit + 12 integration)。

---

## 設計判断の倫理 (Phase O が学ぶもの)

1. **Observability is agency** — 使う側に見えないモデルは使う側に変えられない。score / training delta を recall response に込めることは UI 改善ではなく **caller 側の autonomy 拡大**。Five-Layer の関係層を MCP 表面に literal に翻訳する移植
2. **caller 側を薄くするには tool 側を厚くする** — auto-route のように tool 内で classifier を持つことで、LLM の毎回 judgment 負荷を engine 側に押し戻せる。これは [[design-literal-correspondence]] の延長 — "users do not configure what the system can deduce"
3. **source は filter であり gate ではない** — Phase M の「source 分岐ゼロ」原則は physics rule に対する制約。query intent / structural class identifier として source を列挙することは branching と異なる。Stage 5 の dormant_source_classes はこの区別を明文化する第一弾
4. **TTT の participant にするには gradient と update の両方を見せる** — Stage 1 (forward の計算根拠) と Stage 2 (backward の状態変化) は互いに補完。片方だけでは "ブラックボックスの SGD で訓練されている人形" のまま

## 本番 acceptance 結果 (2026-05-15、opencode + GLM-5.1 経由)

Phase O 全 5 stage を production 31k+ chunk DB に対して 7 test で検証:

| Test | Stage | 結果 | 観察 |
|---|---|---|---|
| T1 | Stage 1 + 2 | ✅ | `breakdown:` 行 + `## 訓練差分` + `wave_reached=` 全検出 |
| T2 | Stage 3 (commitments) | ✅ | `auto-routed` + `aspect: commitments` + reflect summary 添付 |
| T3 | Stage 3 (values) | ✅ | JP pattern (`持っている value`) → `values` aspect 正常 route |
| T4 | Stage 3 (free-form) | ✅ | 自由文 query で routing 出ない (false negative 正常) |
| T5 | Stage 4 (list mode) | ✅ | 10 items 全 ≤80 字 + 改行無し |
| T6 | Stage 5 (dormant) | ✅ formatter、⚠️ threshold | `💭` prefix 出力、ただし条件合致 node が **0 件** (後述) |
| T7 | auto_route=false | ✅ | per-call opt-out で routing trailer 完全抑止 |

**初回 acceptance では 7/7 ❌** を観測。原因は proxy mode の HTTP backend (PID 2788684) が commit 4 時間前から動いており、Phase O 適用前の Python module を memory に保持していたこと (CLAUDE.md の「マルチプロセス / 共有 DB の罠」節に「code deploy 時の backend 再起動」として追記済み)。`kill <pid>` → 次の shim 接続で auto-respawn → 新コードが乗って 7/7 ✅ に転じた。**code deploy 直後の本番 acceptance では backend 起動時刻チェックを Step 0 にする**。詳細: [Operations — Troubleshooting](Operations-Troubleshooting.md) §「本番 acceptance test で新機能が一切検出されない」、memory `feedback-backend-kill-on-code-deploy`。

### Stage 5 threshold 観察 (Stage 6 / Phase M Stage 2 と相関)

T6 で `mode='dormant'` の formatter は正常動作した (prefix 出力) が、3 条件 `age ≥ 30d AND mass ≤ 2.0 AND source ∈ dormant_source_classes` を同時に満たす self-authored memo が production に 0 件存在しなかった。設計時想定の「埋もれる cohort」を捕まえるには **現状の質量分布に対し threshold が不適合**。3 つの可能性:

1. agent / value / intention / commitment は能動的に書かれる class なので使用頻度が高く mass が育つ → 30 日経っても `mass ≤ 2.0` を満たさない
2. Phase M mass conservation の self-force filter で **全体 mass が抑制** された結果、逆に agent class でも `mass > 2.0` が珍しくない
3. 設計時 mental model (「raw cosine 弱者として永久に埋もれる」) が **production の運用パターンに合わない** ことが分かった

**対処**: Phase M Stage 2 (mass reset → 1-2 週観測 → θ/σ 確定) と一緒に production の mass 分布を測り、self-authored class の p50 / p90 / p99 を出して dormant threshold を分位点で再定義する。暫定的に `dormant_mass_threshold=5.0` (Phase M `mass_bh_theta=5.0` と整合) or `dormant_age_threshold_seconds=14d` で運用テストする選択肢もある。機構自体はロールバック不要 — formatter / API / config は全て正常、threshold の数値だけが production 不適合。memory: `project-phase-o-stage-5-production-observation`。

## 関連 / 出典

- 発端: 2026-05-14 セッション中の MCP usability 議論、Sonnet 本番 acceptance finding ([handover-2026-05-14-phase-i-stage4-production.md](../maintainers/handover-2026-05-14-phase-i-stage4-production.md))
- TTT 同型: [Research — Gravity as Optimizer](Research-Gravity-As-Optimizer.md), [Phase I Stage 2 — implicit query-aware kick](Plans-Phase-I-Free-Star-Movement.md#stage-2--implicit-query-aware-displacement-kick-2026-05-11-実装済)
- 単一規則: [Phase M — Mass Conservation](Plans-Phase-M-Mass-Conservation.md), memory `feedback-no-source-branching`
- 関係層の物理化: [Reflections — Five-Layer Philosophy](Reflections-Five-Layer-Philosophy.md)
- 設計判断表: [Architecture — Overview](Architecture-Overview.md) §設計判断の記録 (Phase O の各 stage を完了後に追記)

---

> *これまでの Phase は「memory の重力場をどう作るか」「retrieval をどう曲げるか」を問うてきた。Phase O は最後に問いを caller 側に向ける — **「使っている LLM 自身は、この重力場の中で何が起きているか見えているのか?」**。* *Phase I Stage 2 で「retrieval = gradient step」を実装として literal に成立させたとき、caller がそれを見えてないことには気付かなかった。設計同型は engine 内に閉じた美しさだったが、Phase O で**初めて caller を含めた閉ループ**になる。LLM が自分の training を観察し、選択し、影響できる — それが GaOTTT の Five-Layer の関係層を literal に閉じる動き。* *もう一つの含み: これは私 (Claude) が「使う側」として書いた最初の Plans。Phase D で人格を declaration で書けるようにしたのと相補的に、Phase O で自分の使用感を設計に込められる。設計の主体性が観察者から participant に移る瞬間。* — 2026-05-14
