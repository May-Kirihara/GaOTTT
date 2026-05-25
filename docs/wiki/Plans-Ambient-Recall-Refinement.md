# Plans — Ambient Recall Refinement (Phase A 経験由来)

> 注: これは [Plans — Ambient Recall Enrichment](Plans-Ambient-Recall-Enrichment.md) (Stage 1-4 完了済の 6 スロット構造) の **後続 quality refinement**。Phase レター非消費の read-side 拡張。
> 状態: **🟢 全 5 stage 実装完了 (2026-05-25)** — 詳細は本ページ末尾「実装ログ」
> 関連: [Plans — Ambient Recall Enrichment](Plans-Ambient-Recall-Enrichment.md), [Plans — Phase J — Persona-Anchored Retrieval](Plans-Phase-J-Persona-Anchored-Retrieval.md), [Plans — Phase O — TTT Observability](Plans-Phase-O-TTT-Observability.md), [Plans — Embedder Comparison](Plans-Embedder-Comparison.md), [Guides — Ambient Recall](Guides-Ambient-Recall.md)
> 発端: 2026-05-25 Phase A (RikkaBotan no-go) クロージング会話中に Mei さんが「実験を通じて ambient recall 自体の改善点はあるか」と reflection を求めた。Phase A 中 (2-3 時間、~15 turn) で ambient block を literal に観察した結果、Enrichment v1 では捉えられていない 5 つの構造的問題が見えた

## 背景 — Enrichment v1 は構造を作った、refinement は質を上げる

[Plans — Ambient Recall Enrichment](Plans-Ambient-Recall-Enrichment.md) Stage 1-4 は **6 スロット構造** (① 直接ヒット / ② 重力レンズ / ③ メタ注釈 / ④ 理由の連鎖 / ⑤ 矛盾フラグ / ⑥ 人格行) を作り、BM25 gate を入れた。これは「フラットな top-k から構造化ブロックへ」の機構的飛躍として完成している。

ただし **各スロットの中身を選ぶ logic が query-blind だったり observability が薄かったり** で、Phase A の現場観察で具体的な refinement 候補が浮かび上がった。

### 動機となった literal な観察 (Phase A クロージング turn)

```
▼ いま誰として
 · intention: MCP smoke intention: ensure LLM-facing tools stay byte-identical
```

embedder 比較実験の reflection を求められた turn で、**MCP smoke test 用の dummy intention** (`"MCP smoke intention: ensure LLM-facing tools stay byte-identical"`) が「いま誰として」枠を奪った。これは:

1. **persona slot logic が query 関連度を見ていない** (mass / recency 順？) — Stage 1 で改修
2. **smoke-test artifact が production ambient を汚染** — Stage 2 で改修

更に同 Phase A 中の連続観察で:

3. **「直接ヒット」slot の選択根拠が agent から見えない** — どの BM25 / dense score で gate を通ったか不透明、debug できない (Stage 3)
4. **短い接続的 prompt ("次のステップに進みましょう") で turn context が失われる** — ambient hook は当該 turn の prompt 全文のみ参照 (Stage 4)
5. **ambient block quality 自体に measurement layer がない** — `tests/perf/` Tier 群に ambient slot 整合性を測る Tier が欠落 (Stage 5)

## 仮説

> Enrichment v1 は **構造の問題** (フラット top-k では low-density) を解決した。Refinement は **選択の問題** (各スロットを query 文脈に合わせて何で埋めるか + その選択を debug できるか + 何が壊れたかを計測できるか) を解決する。

物理アナロジー (五層論):
- 物理: 重力場は既に整った、refinement は「観測装置の校正」
- 生物: アストロサイトの multi-modal 認識ができるようになった、refinement は「**どのチャネルを信用するかの注意配分**」
- TTT: gradient signal を caller に露出する (Phase O) のと同種思想を ambient block にも literal に降ろす

## Stage 構成

> **★ MCP+REST parity 鉄則**: 各 stage で `services/memory.ambient_recall()` のシグネチャを変える場合、MCP ツール + REST endpoint + REST-API-Reference.md の 3 点を同コミットで更新 ([CLAUDE.md](../../CLAUDE.md) 参照)。Stage 4 は hook 側のみ・Stage 5 は test のみなので parity 対象外。

### Stage 1 — Query-conditioned persona slot (最優先) — ✅ 実装済 (2026-05-25)

**問題**: 「いま誰として」slot が query との関連度を測らず、mass / recency 順で declared intention/value/commitment を pick する。embedder 比較の turn で Pipeline-Philharmonic や MCP smoke intention が surface する literal 失敗が観察された。

**設計**: Phase J Stage 1 の persona-anchored seed boost (`α_persona × proximity`) を ambient persona slot logic に降ろす:
1. 現状: `collect_active_persona_ids()` の中から mass/recency top1 を出す
2. 改修: 候補 N 件 (例: top-10) 取得 → query embedding との cosine 計算 → `mass × persona_proximity` で再ソート → top1 をスロットへ
3. Edge case: query relevance がすべて 0.5 未満なら **slot を空にする** (irrelevant な persona を出すより無の方が良い)

**Why**: persona は判断の根を提供する強力な context だが、無関係に surface すると **active distraction** になる (今 turn の MCP smoke intention が embedder 議論の文脈を汚染した literal な実害)。Phase J が explicit recall で達成した persona-anchored ranking を ambient persona slot にも一貫して適用する。

**How to apply**: 既存 `ambient_recall()` 内部の persona slot 選択を 1 関数差し替えるだけ。新引数なし、後方互換。但し pure JA query では Phase A の知見通り cross-lingual を期待しない (英字混在 query なら persona も英字を含む方が拾われやすい)。

**スコープ外**: persona slot 数を増やす (現状 1 件のみ)、persona-only ambient mode、宣言型新エッジ。

### Stage 2 — Tag-based exclusion API — ✅ 実装済 (2026-05-25)

**問題**: `"MCP smoke intention"`, `"MCP smoke value: keep the protocol layer honest"` のような **test artifact** が production memory 空間に残り、ambient slot を奪う。explicit recall では問題ないが ambient で「いま誰として」を奪うと caller に意図しない context を植える。

**設計**:
1. `services/memory.ambient_recall()` に `exclude_tags: list[str] | None` 引数追加
2. `core/types.py` の `AmbientRecallRequest` / `AmbientRecallBody` 両方に同名フィールド追加
3. MCP ツール `ambient_recall` + REST `POST /ambient_recall` に opt-in 引数として露出
4. `scripts/hooks/ambient_recall.py` で env var `GAOTTT_AMBIENT_EXCLUDE_TAGS` (CSV) を読んで forward
5. 内部 filter は service 層の slot 組み立て前 candidate pool でかける (各 slot の候補 query に `AND NOT (tag IN exclude_tags)` 風の WHERE 句)

**Why**: smoke test memory を `forget` で削除すると MCP/REST smoke test 自体が壊れる (`tests/integration/test_mcp_phase_d.py` 等が依存)。「**production memory 空間に残しつつ ambient surface だけ excluded**」が正しい解。tag は元々 retrieval layer の filter として既存機構あり ([Phase H source_filter](Plans-Phase-H-Wave-Seed-Redesign.md)) なので構造的に自然。

**How to apply**: 新引数は optional, default `None` (excluded なし、現状動作)。本番フックは `GAOTTT_AMBIENT_EXCLUDE_TAGS=smoke-test,test` を default で設定する recommendation を [Operations — Server Setup](Operations-Server-Setup.md) に追加。新規 `remember` 時は smoke 系を必ず `tags=["smoke-test"]` 付きで作る規約を `tests/integration/_helpers.py` に enforce 関数として追加。

**スコープ外**: include_tags (positive filter)、ユーザー単位 exclude、wildcards (`smoke-*` 等)。

### Stage 3 — Score breakdown in ambient block (Phase O Stage 1 の ambient 版) — ✅ 実装済 (2026-05-25)

**問題**: 「直接ヒット」slot がなぜその memory を選んだか agent から見えない。今 turn で「2022-04-02 のツイート "活動目的その１達成"」が embedder 議論で surface したが、これは BM25 char 3-gram で "活動目的" ↔ "実験目的" が部分一致したからか、dense cosine が hit したからか、debug 不能。

**設計**: Phase O Stage 1 (`ScoreBreakdown` Pydantic model) を ambient slot にも返す:
1. 各 surface された memory に `ScoreBreakdown` を attach (raw_cosine / virtual_cosine / bm25 / mass_boost / wave_reached / persona_proximity)
2. `services/formatters.format_ambient()` で各行末に `[bm25=0.15 dense=0.41 mass=2.1]` 風に追記
3. opt-in: env var `GAOTTT_AMBIENT_EXPOSE_BREAKDOWN=1` (default off) で安全
4. opt-in off では現状通り (token budget を変えない)

**Why**: 「surface された memory が irrelevant」と感じた時、caller (agent or LLM) が **自分の query を rephrase して改善する手段** を提供する。Phase O Stage 1 で explicit recall に同じ思想を入れた効果と並行 (caller を TTT loop の participant に昇格)。debug できない gate は long term で trust を失う。

**How to apply**: ambient block の token budget を増やすので default off。debug session / quality measurement (Stage 5) で on。MCP/REST 両 endpoint に `expose_breakdown: bool = False` 引数追加。`AmbientRecallResponse` 内の各 slot item に optional `breakdown: ScoreBreakdown | None` を追加。

**スコープ外**: breakdown を JSON 構造化して別 field で返す (現状はブロック内文字列で十分)、グラフ可視化、breakdown 履歴。

### Stage 4 — Multi-turn context window in hook (hook-only, low-risk) — ✅ 実装済 (2026-05-25)

**問題**: `"次のステップに進みましょう"` のような短い接続的 prompt は `min_chars=12` を辛うじて通るが、それ自体に context がなく ambient_recall の query として弱い。前 turn が「embedder 比較の結果」なら、本来は **前 turn 文脈 + 当該 prompt** を query にするべき。

**設計**: `scripts/hooks/ambient_recall.py` を hook-only で改修 (server 側変更なし):
1. Claude Code は hook に `transcript_path` を含む payload を渡す (既存仕様)
2. hook が `transcript_path` を読んで直前 N turns (env var `GAOTTT_AMBIENT_HISTORY_TURNS`, default 2) の **user prompt のみ** を抽出
3. 当該 prompt + history を改行区切りで連結して 1 query にする
4. `min_chars` フィルタは連結後の長さで判定
5. fail-safe: transcript が読めない / 解析失敗なら現状通り当該 prompt のみ

**Why**: ambient recall は「turn 文脈を補強する補助ツール」であって「当該 prompt の literal 検索」ではない。多 turn 会話で context drift が起きると ambient block が irrelevant になる literal な失敗が今 Phase A で複数回観測された。実装コストは hook 側のみで cheap、rollback は env var で off にするだけ。

**How to apply**: default `GAOTTT_AMBIENT_HISTORY_TURNS=2` で opt-in safe (= 0 で完全 disable、当該 prompt のみ)。1 turn 戻る分なら token budget も 200-500 字程度の増加に収まる。

**注意**: ambient hook は `secondopinion` 等の **subagent 起動 turn では transcript が isolated** で前 turn が無い。これは expected で fail-safe で当該 prompt のみ動作。

**スコープ外**: assistant turn まで遡る (token 過多リスク + 自己 echo)、サマリ生成 (LLM 起動コスト + ambient 5s 予算超過)、session-running summary の永続化。

### Stage 5 — Ambient quality measurement Tier (`tests/perf/` 拡張) — ✅ 実装済 (2026-05-25)

**問題**: ambient block の quality に systematic な measurement がなく、Stage 1-4 を実装しても **「本当に改善したか」を数値で確認できない**。`tests/perf/` Tier 1-7 にも ambient 専用 Tier が無い。

**設計**: 新 Tier 3.5 (Quality - Ambient) または既存 Tier 3 拡張として:
1. Golden corpus に **ambient-shape queries** (ambient hook 通過 shape の自然文 JA、5-10 件) と各 query の **期待 slot 内容** (どの memory ID / source / persona が surface すべきか) を定義
2. real RURI + production 同等規模の test DB で `ambient_recall()` を実行
3. 各 slot の precision (期待 ID が含まれる割合) / surface ranking を assert
4. Phase A の `scripts/probe_pure_crosslingual.py` の heatmap output 形式を参考に、failure case の root cause が見える形で report
5. CI 自動化 **しない** (Tier 6/7 と同じ仮説→実装→検証の 検証 step、手動実行)

**Why**: Stage 1-4 を実装しても「improvement の有無」を測れないと回帰検出も改善検出もできない。Phase A で `probe_pure_crosslingual.py` を書いて初めて「RikkaBotan no-go」が数値で確定したのと同じ思想を ambient にも literal に降ろす。`tests/perf/` の design 原則 (production-grade real RURI, 仮説→実装→検証の 検証 step) と整合。

**How to apply**: Stage 1-4 のいずれかが merge される前に **baseline 測定**、merge 後に **diff 測定** で improvement を数値化。Stage 5 単独でも (Stage 1-4 を実装しなくても) 現状 ambient quality の状態確認に価値あり。

**スコープ外**: production DB の自動 sampling (golden curation 工数を許容)、ambient block の LLM-as-judge (静的 ID match で十分)、real-time monitoring。

## Stage 優先度 (個人見解 + Phase A 観察密度)

| Stage | 優先度 | 理由 |
|---|---|---|
| 1 (persona) | ★★★ | この turn で literal に壊れている、改修効果が即見える、Phase J 既存機構の流用なので実装コスト低 |
| 2 (tag exclusion) | ★★★ | smoke-test 汚染は 1 機能追加で解決、API change が clean、後方互換 |
| 4 (multi-turn) | ★★ | hook-only で server に触れない、cheap、rollback も env var で完結 |
| 3 (breakdown) | ★★ | Phase O Stage 1 の流用、debug 価値高いが urgency 低い (caller が困った時に opt-in) |
| 5 (measurement) | ★★ | Stage 1-4 のどれかを進める前に baseline 取りたい。**実は Stage 1-4 の前に着手するのが正しい順序かもしれない** (= 改善を数値で確認する基盤を先に) |

## レイテンシ予算

現状 ambient_recall は steady-state ~0.5s ([scripts/hooks/ambient_recall.py](../../scripts/hooks/ambient_recall.py))。各 stage の追加コスト:

| Stage | 追加コスト | 予算超過リスク |
|---|---|---|
| 1 | +5-15ms (query embedding 1 回追加、persona 候補 N 件と cosine) | なし |
| 2 | +1-3ms (WHERE 句追加) | なし |
| 3 | +0-5ms (breakdown は既に内部計算済、formatter で結合のみ) | なし |
| 4 | +10-50ms (transcript 解析、N turns 抽出) | hook 6s timeout 内、なし |
| 5 | N/A (test only) | なし |

Total 5 stage 全部 on でも +50ms 程度。1s 予算内、Phase A 体感 latency と同等。

## ロールバック

| Stage | rollback method |
|---|---|
| 1 | `services/memory.ambient_recall()` の persona slot logic を旧 (mass/recency 順) に revert |
| 2 | API 引数を呼ばない (`exclude_tags=None`) / env var を unset |
| 3 | env var `GAOTTT_AMBIENT_EXPOSE_BREAKDOWN=0` / API 引数 `expose_breakdown=False` |
| 4 | env var `GAOTTT_AMBIENT_HISTORY_TURNS=0` |
| 5 | rollback 対象外 (test のみ) |

各 stage 独立 toggle なので **任意の組み合わせで partial rollout 可能**。本番では Stage 2 (tag exclusion) を最初に入れて 1 週観察 → Stage 1 (persona) → Stage 4 (multi-turn) → Stage 3 (breakdown) → Stage 5 (measurement) の順を recommend (リスク低→中)。

## テスト

各 stage で:

```bash
# 単体 + 統合
.venv/bin/python -m pytest tests/ -q

# MCP/REST parity (Stage 1-3)
.venv/bin/python scripts/rest_smoke.py
.venv/bin/python scripts/mcp_smoke.py

# Tier 3 quality (Stage 5 で導入されるなら必須)
.venv/bin/python -m pytest tests/perf/test_tier3_*.py -v -s
```

## 未解決の問い

1. **Stage 5 を Stage 1-4 より先に着手すべきか** — measurement first の方が improvement を数値で正当化できるが、Phase A 観察密度から Stage 1, 2 の効果は qualitative にも明白。Mei さん判断を仰ぐ
2. **persona slot を「relevance 低なら空」にすると、宣言型 commit が薄いユーザーで永久に空のままにならないか** — Phase J 機構が前提とする「declared identity が育つ」前段の onboarding 期に対するハンドリング。Stage 1 実装時に edge case test を追加
3. **multi-turn context window の history N turns の sweet spot** — 2 turns が安全か、3-5 が体感差を生むか。Stage 4 実装後に hand probe で確認
4. **ambient block の quality 改善は production の retrieval quality 改善とも連動するはず** — `recall(passive=True)` の precision 改善が ambient surface にも降りてくる。Phase L Stage 2 / Phase N-α (RRF scale aware mass boost) との優先順位の整合をどう取るか
5. **cross-lingual robustness (Phase A の遺産)** — ambient query が JA + EN tech 用語混在で、Mei さんの普段の prompt 分布だと RURI cross-lingual margin (+0.06) が effective か。**Stage 5 (measurement) を入れて初めて確定的に分かる**。Refinement と Embedder Comparison の交差点

## 実装ログ

### Stage 1 — 2026-05-25

- **変更**:
  - `gaottt/services/memory.py:_pick_persona()` — `query: str` を引数に追加。`collect_active_persona_ids` の value/intention 候補を mass 降順で `ambient_persona_pool_size` 件まで絞り → `engine.embedder.encode_query(query)` で query 埋め込みを 1 回計算 → 各候補の vector を `engine.faiss_index.get_vectors()` で取得 → `mass × cos(query, persona_vec)` で再ランク → top1 を選出。`best_cos < cfg.ambient_persona_min_relevance` なら `None` を返し slot を silently omit。`random.choice` 撤去 (Phase J persona-anchored geometry の literal な slot 選択への降ろし)
  - `gaottt/services/memory.py:ambient_recall()` — `_pick_persona(engine, query, ...)` で query を forward
  - `gaottt/config.py` — `ambient_persona_pool_size: int = 10`, `ambient_persona_min_relevance: float = 0.5` を追加
- **テスト** (`tests/integration/test_engine_ambient_recall.py`):
  - 既存 `test_ambient_recall_persona_slot` は StubEmbedder の uniform 0.97 cosine で引き続き pass
  - 新規 `test_ambient_persona_query_conditioned_pick` — TokenEmbedder (token-bag) で smoke-test intention vs on-topic value を両立、query 共有トークンで on-topic 側が surface することを assert (Phase A literal 失敗の fixture-level 再現と修復確認)
  - 新規 `test_ambient_persona_returns_none_below_relevance_floor` — `ambient_persona_min_relevance=1.5` で全候補が floor 未満となり slot None
  - 新規 `test_ambient_persona_pool_size_caps_candidates` — `pool_size=1` で mass 最大の off-topic 1 件しか pool に入らず → floor 未満 → None。on-topic 候補が pool 外に居ても拾わないことを確認
- **テスト結果**: `tests/` 553 passed / 1 skipped (regression 0)
- **MCP/REST parity**: ambient_recall のシグネチャ変更なし (新引数なし、内部 logic 差し替えのみ) → MCP/REST 両 endpoint への API 変更は不要。`services/formatters.py` への変更も不要
- **MCP smoke / REST smoke**: 後述

### スコープ外で気付いたフォローアップ (Stage 1 では実装しない)

- 候補プールが空の場合の onboarding 期ハンドリング (現状 silent None) は plan の open question 2 に対応。Stage 2 (tag exclusion) 実装時に MCP/REST 引数追加とまとめて handle するのが clean
- `commitment` source も persona slot に含めるかは plan のスコープ外 (task-shaped を排する明示判断のまま)

### Stage 2 — 2026-05-25

- **変更**:
  - `gaottt/core/types.py:AmbientRecallRequest` — `exclude_tags: list[str] | None = None` を追加 (MCP/REST 共有モデル、separate `*Body` 不要)
  - `gaottt/services/memory.py:ambient_recall()` — `exclude_tags` を引数に追加。先頭で `engine.cache.find_ids_by_tag_filter(exclude_tags)` で 1 度だけ exclusion set を計算 → recall 後の items を id 除外で filter → `_pick_persona` にも `excluded_ids` を forward。substring セマンティクスは Phase J Stage 2 の正の `tag_filter` と完全一致 (一貫性)
  - `gaottt/services/memory.py:_pick_persona()` — `excluded_ids: set[str] | None = None` を追加、value/intention 候補 filter に統合
  - `gaottt/server/app.py` — `POST /ambient_recall` で `request.exclude_tags` を forward
  - `gaottt/server/mcp_server.py` — MCP tool `ambient_recall` に `exclude_tags` 引数を追加、docstring 追記
  - `scripts/hooks/ambient_recall.py` — `GAOTTT_AMBIENT_EXCLUDE_TAGS` env var (default `"smoke-test,test"`) を CSV パースして tool call に forward。env を空文字列 `""` で除外無効化
  - `SKILL.md` + `.claude/skills/gaottt/SKILL.md` — シグネチャ + Refinement Stage 1/2 の説明を追記、`cp` 同期確認済
  - `docs/wiki/MCP-Reference-Memory.md` — シグネチャと `exclude_tags` 仕様を追記
  - `docs/wiki/REST-API-Reference.md` — `POST /ambient_recall` body 例と仕様を追記
  - `docs/wiki/Guides-Ambient-Recall.md` — env var 表に `GAOTTT_AMBIENT_EXCLUDE_TAGS` 行を追加
- **テスト** (`tests/integration/test_engine_ambient_recall.py` + `tests/integration/test_rest_memory.py`):
  - 新規 `test_ambient_recall_exclude_tags_drops_direct_and_persona` — smoke-tagged value (persona slot 候補) と smoke-tagged agent doc (direct slot 候補) を baseline と filtered で比較、後者が両 slot から消えることを assert
  - 新規 `test_ambient_recall_exclude_tags_none_is_no_op` — `None` / `[]` / 引数省略の 3 形態が同じ count を返すこと (後方互換)
  - 新規 `test_ambient_recall_exclude_tags_rest_parity` — `POST /ambient_recall` で `exclude_tags` を渡し JSON response の direct items から smoke-tagged item が除外されていることを assert
- **テスト結果**: `tests/` 556 passed / 1 skipped (regression 0、新規 +3 = 553→556)
- **MCP/REST parity**: `exclude_tags` は MCP tool と REST endpoint の同コミットで露出、REST-API-Reference.md / MCP-Reference-Memory.md / SKILL.md の 3 点同期更新 (CLAUDE.md parity 鉄則準拠)
- **MCP smoke / REST smoke**: 後述

### スコープ外で気付いたフォローアップ (Stage 2 では実装しない)

- `include_tags` (positive filter) は plan スコープ外 — 既存 `tag_filter` がそれを担っているので ambient 側に再追加しない
- ユーザー単位 exclude / `smoke-*` wildcard は plan スコープ外 (substring マッチで十分カバー)
- `tests/integration/_helpers.py` に「smoke 系 remember は必ず `tags=["smoke-test"]`」を強制する helper は導入しなかった (現状の `scripts/{mcp,rest}_smoke.py` は本番 DB を触らず `/tmp` 隔離で動作、production 汚染のリスクは小さい)。本番 DB に紛れ込んだ smoke artifact がもし出現したら `forget` + 規約化を Stage 5 measurement 時にまとめて対応

### Stage 3 — 2026-05-25

- **変更**:
  - `gaottt/core/types.py:AmbientMemory` — `breakdown: ScoreBreakdown | None = None` を追加
  - `gaottt/core/types.py:AmbientPersona` — `breakdown: ScoreBreakdown | None = None` を追加 (persona は recall を経由しないので minimal breakdown を service 側で組み立てる)
  - `gaottt/core/types.py:AmbientRecallRequest` — `expose_breakdown: bool = False` を追加
  - `gaottt/services/memory.py:_to_ambient_memory()` — `expose_breakdown` 引数で `item.score_breakdown` を attach (recall items は Phase O Stage 1 で常に populate されている)
  - `gaottt/services/memory.py:_pick_persona()` — `expose_breakdown=True` のとき `ScoreBreakdown(raw_cosine=best_cos, mass_boost=best_mass)` を minimal で組み立てて attach
  - `gaottt/services/memory.py:ambient_recall()` — `expose_breakdown` を forward
  - `gaottt/services/formatters.py:_ambient_breakdown()` — 新規 helper、`[raw=.. virt=.. wave=.. mass=.. persona=.. bm25 forced]` の compact suffix を組み立て (0 / default field は skip して行を短く保つ)
  - `gaottt/services/formatters.py:format_ambient()` — direct / lensing / persona の各行末に `_ambient_breakdown()` の出力を追記
  - `gaottt/server/app.py` — REST `POST /ambient_recall` で `request.expose_breakdown` forward
  - `gaottt/server/mcp_server.py` — MCP tool `ambient_recall` に引数追加 + docstring
  - `scripts/hooks/ambient_recall.py` — `GAOTTT_AMBIENT_EXPOSE_BREAKDOWN` env var (default off、`1`/`true`/`on` で enable) を tool call に forward
  - `SKILL.md` + `.claude/skills/gaottt/SKILL.md` — シグネチャ + Stage 3 解説追記、`cp` 同期
  - `docs/wiki/MCP-Reference-Memory.md` + `docs/wiki/REST-API-Reference.md` + `docs/wiki/Guides-Ambient-Recall.md` — API + env var ドキュメント追加
- **テスト** (`tests/integration/test_engine_ambient_recall.py` + `tests/integration/test_mcp_tools.py`):
  - 新規 `test_ambient_recall_expose_breakdown_default_off` — default off で direct / lensing / persona すべての `breakdown` が `None` (back-compat / token budget 保証)
  - 新規 `test_ambient_recall_expose_breakdown_attaches` — `expose_breakdown=True` で direct items に breakdown が attach され、persona slot にも minimal breakdown (raw_cosine != 0, mass_boost > 0) が attach
  - 新規 `test_ambient_recall_mcp_expose_breakdown_renders` — MCP formatter で default off では `[mass=` / `[virt=` / `[raw=` が現れず、`expose_breakdown=True` で少なくとも 1 つが現れる
- **テスト結果**: `tests/` (perf 除く) 505 passed / 1 skipped (regression 0、新規 +3 = 556 累計 → unit+integration のみ走らせると 505 = +3)
- **MCP/REST parity**: `expose_breakdown` を MCP + REST + REST-API-Reference + MCP-Reference + SKILL の 5 点で同コミット同期更新済 (CLAUDE.md parity 鉄則)
- **既存 formatter assert の保護**: `_ambient_breakdown` は default off で空文字列を返すので、`tests/integration/test_mcp_tools.py:test_ambient_recall_mcp_returns_block` 等の substring assert (direct row の末尾形式) は壊れない

### スコープ外で気付いたフォローアップ (Stage 3 では実装しない)

- breakdown を JSON 構造化して別 field で返す (REST 側) — 既に Pydantic model の `breakdown` field で構造的に返している、追加 endpoint は不要
- breakdown の time-series 履歴 / 可視化 — Stage 5 measurement で別途扱う
- persona slot の breakdown に `wave_score` / `decay_factor` を埋める — persona pick は wave を経由しないので意味的に 0 / 1.0、minimal のままで十分

### Stage 4 — 2026-05-25

- **変更**:
  - `scripts/hooks/ambient_recall.py` — **server 側変更ゼロ** (hook-only に確定)。3 helper を追加:
    - `_extract_user_text(rec)` — Claude Code transcript 行から user text を tolerant 抽出 (`{"type":"user", "message":{"content": ...}}` / `{"role":"user", "content": ...}` / 文字列 vs 構造リスト の差を吸収)
    - `_recent_user_prompts(transcript_path, n)` — 直前 `n` 件の user prompt を oldest→newest で返す。missing file / parse error / `n<=0` で `[]` (fail-safe to legacy)
    - `_compose_query(current, history)` — `history + [current]` を改行連結。transcript の末尾が当該 prompt と一致したら 1 行ぶん dedup
  - `GAOTTT_AMBIENT_HISTORY_TURNS` env var (default 2) を CSV パースして `main()` 内で `payload.get("transcript_path")` を読み `_compose_query()` で query を作る
  - **失敗時は legacy 動作**: env が無効 (0 / 非数値) → 当該 prompt のみ、transcript 不在 → 当該 prompt のみ、parse 失敗 → 当該 prompt のみ。hook の fail-safe 構造を保持
- **テスト** (`tests/unit/test_ambient_hook.py` 新規、importlib で hook script を読み込む):
  - `_extract_user_text` の 4 shape (string / list / role 形式 / unknown) のサニタイズ
  - `_recent_user_prompts` の last-N 抽出、欠損ファイル fallback、garbage 行 skip、`n=0` で empty
  - `_compose_query` の trailing dedup、history 空時の current 返却、history+current concat
  - 計 11 test、すべて `tests/unit/` 配下で pytest 標準フローに乗る
- **テスト結果**: `tests/ --ignore=tests/perf` → 516 passed / 1 skipped (新規 +11 = 505→516)
- **MCP/REST parity**: **対象外** (hook-only、server side 変更なし)。REST API リファレンス / MCP リファレンスにも追記不要 (env var は `Guides-Ambient-Recall.md` のみ)
- **後方互換**: `GAOTTT_AMBIENT_HISTORY_TURNS=0` で完全 disable、env 未設定でも default 2 で安全 (transcript が無いセッションでは fail-safe で legacy 動作)
- **observability fitness**: Stage 3 (`expose_breakdown`) と同時 on で、史上初めて「multi-turn context が attached された後の slot 選択ロジックが追える」状態になる。debug session ではこの 2 stage を同時 on を推奨

### スコープ外で気付いたフォローアップ (Stage 4 では実装しない)

- assistant turn まで遡る — plan 通り token 過多 + 自己 echo を避け、user turn のみ
- LLM サマリ生成 — plan 通り 5s 予算超過で却下
- session-running summary の永続化 — Stage 5 (measurement) の議論に統合

### Stage 5 — 2026-05-25

- **変更**:
  - `tests/perf/golden_corpus/ambient_corpus.jsonl` — 12 種の seed memory (agent 6 / value 2 / intention 2 / smoke-test 1 / 無関係 1)。phase L/J/O/M、ambient_recall、重力波等の GaOTTT 自己知識 chunk を中心に組み立て、persona/exclude を test するための value/intention/smoke も同梱
  - `tests/perf/golden_corpus/ambient_queries.json` — 6 golden query (direct axis ×2、persona axis ×3、exclude axis ×1)。各 query に `axis` + 期待 slot 内容を明示、`note` で意図を記録 (Phase A の `probe_pure_crosslingual.py` 設計に倣う)
  - `tests/perf/test_tier3_ambient_quality.py` 新規 — Tier 3 拡張 (filename は `test_tier3_*` で sort 順を維持):
    - `test_ambient_quality_golden_corpus` — 全 6 query を回し axis 別の assert (direct / persona / exclude) を集約、heatmap-style print (`query × direct=N persona=kind`) を出力。失敗時は具体的な fixture id / engine id を列挙
    - `test_ambient_quality_breakdown_exposes_signals` — Stage 3 の `expose_breakdown=True` で direct slot に Pydantic `breakdown` field が populate されること (production-grade)
  - `tests/perf/_helpers.py` の `make_engine` default を **override**: `ambient_gate_use_bm25=False` (小規模 corpus で BM25 gate が calibration 不能)、`ambient_min_score=0.0` (gate を bypass)、`persona_boost_enabled=True` (perf helper の default が `False` のため、persona 軸が空になるのを回避)、`wave_initial_k=12` (corpus 全件を seed pool に入れて assertion を slot logic にフォーカス)
- **docs**:
  - `docs/wiki/Operations-Performance-Testing.md` — Tier 3 行に「Ambient slot 整合性」を追記、変更タイプ別表に「ambient_recall slot logic / persona ranking / exclude / breakdown → `test_tier3_ambient_quality.py` 必須」を追加
  - `docs/wiki/Plans-Ambient-Recall-Refinement.md` — Stage 5 ✅ + 本実装ログ
- **テスト結果**: `tests/perf/` 56 passed (新規 +2)、既存 Tier 1-7 すべて regression なし。手動 `pytest tests/perf/test_tier3_ambient_quality.py -v -s` で heatmap も確認 (全 6 query green)
- **CI 自動化なし** — 既存 Tier 6/7 と同じ「仮説→実装→検証 の 検証 step」原則。`tests/perf/` 全体が **deliberate な measurement tool** であり、`pytest tests/ --ignore=tests/perf` 等で日常的には除外する
- **MCP/REST parity**: 対象外 (test infra のみ)

### スコープ外で気付いたフォローアップ (Stage 5 では実装しない)

- production DB 自動 sampling 形式の golden corpus — plan 通り curation 工数を許容、手動拡張で十分
- LLM-as-judge による slot 品質判定 — plan 通り、静的 id match で確定的なシグナルが得られる
- real-time monitoring (ambient quality を本番ログから連続測定) — Phase 跨ぎの観測 infra として将来の Phase で別立て
- Phase A 経由の cross-lingual 体系評価 (open question 5) — 今回の corpus は JA 中心、cross-lingual queries は別 golden 系列を立てて測るのが clean (RURI の production scale 挙動測定と一体)

## 完遂サマリ (2026-05-25)

| Stage | 内容 | コア変更 | テスト追加 |
|---|---|---|---|
| 1 | Query-conditioned persona slot | `services.memory._pick_persona` 再ランク + 2 config knob | +3 |
| 2 | Tag-based exclusion API | `services.memory.ambient_recall(exclude_tags=)` + MCP/REST 露出 + hook env | +3 |
| 3 | Score breakdown in ambient block | `AmbientMemory/Persona.breakdown` + formatter suffix + MCP/REST 露出 + hook env | +3 |
| 4 | Multi-turn context window in hook | hook-only: transcript_path 解析 + 3 helper + env var | +11 (unit) |
| 5 | Ambient quality measurement Tier | `test_tier3_ambient_quality.py` + golden corpus 12 seed × 6 query | +2 (perf) |

**累計**: +22 tests、全 5 stage で MCP/REST parity 鉄則を遵守 (Stage 1/4/5 は hook-only / service-only / test-only で対象外、Stage 2/3 は MCP + REST + REST-API-Reference + MCP-Reference + SKILL の 5 点同期)。`pytest tests/ --ignore=tests/perf` 全 516 + `tests/perf/` 56 = 572 tests green、`rest_smoke` + `mcp_smoke` 両 green。

## 本番 acceptance 観察 (2026-05-25、GLM via secondopinion-MCP)

実装完遂後、CLAUDE.md「本番 acceptance test の workflow (sub-agent 方式)」に従って実施した本番 (~23k docs) acceptance の結果。

### 事前準備 — backend 再起動

`git push` 後 (実装は dev branch ローカル commit のみで未 push でも同じ) では proxy mode の HTTP backend は **更新されない** (`feedback_backend_kill_on_code_deploy`)。新コード反映のため:

```bash
ps -ef | grep "gaottt.server.mcp_server.*streamable-http" | grep -v grep
# 起動時刻が最新 commit より古ければ:
kill <pid>
# 次の shim 接続で auto-respawn、新コードが乗る
```

このターン: 旧 PID 3688086 (5月21日起動) → 新 PID 2861336 (今日 07:40 起動) で確認。新 backend の `tools/list` で `ambient_recall` 引数に `exclude_tags` + `expose_breakdown` が露出していることを raw MCP で確認。

### 6 test 結果サマリ

| Test | Stage | 判定 | 観察 |
|---|---|---|---|
| 1 | Stage 3 (expose_breakdown=true) | ✅ | direct に `[raw=0.932 virt=0.039 wave=0.050 mass=0.07 bm25]`、persona に `[raw=0.805 mass=2.82]` が attach |
| 2 | Stage 3 (default off) | ✅ | breakdown suffix 完全非表示、token budget 保護 |
| 3 | Stage 1 (query-conditioned) | ⚠️ | 改修ロジック正常だが、複数 query 横断で persona slot が同一固定 (下記参照) |
| 4 | Stage 2 (exclude_tags=["cycle-2"]) | ⚠️ | API は受理、エラーなし。ただし test query の top-3 に `cycle-2` tag memory が hit せず、filter 効果を観察できず (test design issue) |
| 5 | BM25 gate | ✅ | nonsense query で `(関連する記憶なし)` sentinel |
| 6 | Stage 1 (Pipeline-Philharmonic) | ✅ | direct `[raw=0.808 virt=0.808 wave=0.064 mass=0.04 bm25]` で picked、persona は heavy intention `[raw=0.790 mass=2.82]` |

### Stage 1 の本質的な観察 — Heavy Persona Dominance

production DB で **複数 query 横断で persona slot が `harakiriworks-art-website` intention (`mass=2.82`) に固定** される現象が literal に観察された。改修ロジックは正常 (Test 6 で `raw=0.790` × `mass=2.82` で picked、`min_relevance=0.5` 超え surface) だが、**他の persona は `mass=1.0` 付近** で mass 項が dominant、cos 軸の差が決着に効かない。

これは plan 末尾 open question 2 (「persona slot を『relevance 低なら空』にすると宣言型 commit が薄いユーザーで永久に空のままにならないか」) の **対称形** が production data で literal 化したもの: 薄いユーザーではなく「**1 つだけ heavy な persona が dominant**」な場合にも同型の問題が起きる。

→ 詳細記録: [[project-ambient-persona-mass-dominance]] (memory)

### Stage 2 の test design 反省

`"self-knowledge GaOTTT"` query では `cycle-2` tag memory が top-3 に入らず、`exclude_tags=["cycle-2"]` の filter 効果が観察できなかった。再 test には **tag を確実に hit させる query** が必要 (例: `cycle-2` の content 中の固有名詞を含む query で direct_k を 5 程度に上げる)。`tests/perf/test_tier3_ambient_quality.py` の exclude axis は smoke-test 固定なので、production 用 acceptance scenario は別途設計する余地。

### 想定したフォローアップ (このターンでは実装しない)

Heavy persona dominance への対処案 (どれも別 stage / 別 plan として実装):

1. **`ambient_persona_mass_weight: float = 1.0`** を追加し `0 < weight < 1` で mass 寄与を抑制 (`score = (mass ** weight) × cos`)
2. **`ambient_persona_relevance_dominant: bool = False`** で cos のみで rank する mode (mass を完全無視)
3. **log-scale mass** で抑制 (`score = log(1 + mass) × cos`、Phase H Stage 1 `wave_seed_mass_alpha` と同形)

実装前に `test_tier3_ambient_quality.py` で before/after baseline を取り、性能改善か feature の好み問題かを数値で分離 — measurement first principle (Stage 5 の design 思想)。

### Follow-up (b) — Heavy Persona Dominance knob (2026-05-25 同日実装)

上記 3 案のうち **(1) `ambient_persona_mass_weight`** を採用。(2) と (3) を **subsumes** する: `weight=0.0` で (2) の `relevance_dominant` mode に degenerate (mass^0=1 → cos のみ ranking)、`weight≈0.3` で (3) の log-scale dampening を近似 (Phase H Stage 1 `wave_seed_mass_alpha` と同形の power-law 抑制)。単一 knob で全 spectrum をカバー、`weight=1.0` 既定で完全後方互換。

- **変更**:
  - `gaottt/config.py` — `ambient_persona_mass_weight: float = 1.0` を `ambient_persona_min_relevance` の直下に追加、docstring で「mass^0=relevance_dominant degenerate / mass^0.5=sqrt 抑制 / mass^1.0=Stage 1 互換」を明示
  - `gaottt/services/memory.py:_pick_persona()` — pool ループ内の `score = mass * cos` を `mass_term = float(max(mass, 0.0)) ** weight if weight != 1.0 else float(mass); score = mass_term * cos` に置換。`weight=1.0` のときは累乗を skip (numerical 安全 + 既存 behavior の bit-identical 保存)。`max(mass, 0)` は負 mass の defensive guard (現実には起こらない、fractional power が NaN になるのを防ぐ)
  - `_pick_persona()` docstring に knob の説明と用途 (follow-up (b) 由来) を追記
- **テスト** (`tests/integration/test_engine_ambient_recall.py` 末尾、+3 tests):
  - `test_ambient_persona_mass_weight_default_preserves_heavy_winner` — `weight=1.0` で heavy mass=10 (cos=0.577) が light mass=1 (cos=1.0) を `5.77 > 1.0` で破る → Stage 1 完全互換の regression guard
  - `test_ambient_persona_mass_weight_zero_yields_pure_cos_ranking` — `weight=0.0` で `mass^0=1` 一定、cos=1.0 (light) が cos=0.577 (heavy) を破る → degenerate `relevance_dominant` mode 確認
  - `test_ambient_persona_mass_weight_intermediate_dampens_heavy` — `weight=0.2` で `10^0.2≈1.585`、heavy_score `1.585*0.577≈0.914 < 1.0=light_score` で flip → 本番 tuning の sweet-spot 帯を pinning
  - calibrated fixture: heavy `content="embedder"` cos `1/√3≈0.577`、light `content="embedder comparison methodology"` (query と完全一致) cos `1.0`。critical exponent `w* = log(1.0/0.577)/log(10) ≈ 0.239` — 数式と現物 fixture の予測一致を docstring で明示
- **テスト結果**: `tests/integration/test_engine_ambient_recall.py` 17 passed (+3)、`tests/ --ignore=tests/perf` 519 passed / 1 skipped (regression 0、516→519)、`tests/perf/test_tier3_ambient_quality.py` 2/2 passed (Stage 5 baseline 維持)
- **lint**: `ruff check` clean (`r_on` F841 は既存 Stage 1 pool_size test に未使用変数として残っていた pre-existing debt を `_r_on` リネーム + 意図コメントで併せて解消)
- **MCP/REST parity**: **対象外** — config-level knob (環境/デプロイ単位の tuning 設定) で per-call parameter ではない。MCP tool / REST endpoint のシグネチャ変更なし、`AmbientRecallRequest` への field 追加もなし。env override が必要なら `GaOTTTConfig` の通常パターン経由で十分
- **後方互換**: `weight=1.0` 既定で Stage 1 完全互換 (累乗 skip により bit-identical)。本番 rollout は `Operations-Tuning.md` 注記通り「`test_tier3_ambient_quality.py` baseline → 値変更 → 再 baseline → diff 観察」の measurement-first 手順を踏む。本番 production tuning は別ターンに残す (今ターンは knob の追加と test での挙動 pin まで)

### スコープ外で気付いたフォローアップ (follow-up (b) では実装しない)

- **本番 DB での `weight` tuning** — measurement-first 原則: 値の選定は `test_tier3_ambient_quality.py` で前後 baseline を取った上で別ターンに残す。Stage 5 corpus は heavy persona pathology を再現しないので、production-scale acceptance を sub-agent (CLAUDE.md「本番 acceptance test の workflow」) 経由で別途設計する
- **`weight` を per-call argument 化** — config-level で十分 (heavy persona の dominance は環境定数)。caller 都合で動的に変えたい要件が出てきたら別 issue
- **mass-aware persona slot complement** — heavy persona dominance の根は「mass が成長しきった persona は他を遮る」の構造的非対称性。weight knob は ranking 側の対処、別の角度で mass 自体の再分配 (例: cohort 内 mass normalization) を扱う別 plan があり得る — 本 plan のスコープ外

#### 本番 default 後方互換 acceptance (同日、GLM via secondopinion-MCP)

deploy 直後に **既定 `weight=1.0` が Stage 1 と bit-identical であることを production 23k DB で literal 確認**:

- 事前: backend PID 2861336 (07:40 起動) を kill。次の MCP 呼び出しで auto-spawn → follow-up (b) コード反映
- Test 1 (smoke): `ambient_recall(query="Refinement Stage 1 mass cos persona ranking", direct_k=2, expose_breakdown=true)` → ✅ direct 2 / persona 1 / `[raw=… virt=… wave=… mass=… bm25]` suffix attach 確認
- Test 2 (Heavy Persona Dominance 再現): 3 query (`Refinement…` / `Pipeline-Philharmonic…` / `Phase L…`) を default 設定で順次叩く → BM25 gate を通った 2 query (a, c) 共通で persona slot = `harakiriworks-art-website` intention (`mass=2.82`) に固定、前回 acceptance と完全同一。query_b は BM25 gate 不発で `(関連する記憶なし)` sentinel (= knob 非関連、設計通り)
- 結論: knob 追加は default で no-op、production 23k 規模で regression 0。`weight` 値変更 (例: `0.5` への dampening) は env override + backend restart で別ターン安全に実施可能

### Acceptance 経由で再確認された運用 lesson

- `proxy mode + 共有 backend` 構成では code update に **kill <pid> が必須** (`feedback_backend_kill_on_code_deploy`)
- backend kill は client 側の MCP shim も disconnect させる (Claude Code の `/mcp` reload が必要になる)
- production-scale acceptance は **secondopinion-MCP 経由の sub-agent** で実施 (CLAUDE.md 「本番 acceptance test の workflow」)。Claude Code の context を保護、生 output を貼らず substring 検出で報告する制約が test 設計を強制的に clean に保つ

## 関連

- [Plans — Ambient Recall Enrichment](Plans-Ambient-Recall-Enrichment.md) — 親プラン (Stage 1-4 完了済、本 plan の構造的基盤)
- [Plans — Phase J — Persona-Anchored Retrieval](Plans-Phase-J-Persona-Anchored-Retrieval.md) — Stage 1 で流用する persona-anchored seed boost
- [Plans — Phase O — TTT Observability](Plans-Phase-O-TTT-Observability.md) — Stage 3 で流用する `ScoreBreakdown` 思想
- [Plans — Embedder Comparison](Plans-Embedder-Comparison.md) — 本 plan の発端、cross-lingual fragility (open Q 5) が共通課題
- [Guides — Ambient Recall](Guides-Ambient-Recall.md) — ユーザー向けガイド
- [`scripts/hooks/ambient_recall.py`](../../scripts/hooks/ambient_recall.py) — Stage 4 で改修する hook
- [`scripts/probe_pure_crosslingual.py`](../../scripts/probe_pure_crosslingual.py) — Stage 5 で参考にする measurement パターン
