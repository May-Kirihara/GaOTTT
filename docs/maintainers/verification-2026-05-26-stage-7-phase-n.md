# Verification Plan — Stage 7 + Phase N (2026-05-26)

> **読者**: 次に Stage 7.1/7.2 や Phase N β に触る Claude / 保守者、あるいは類似の「機構を本番に rollout する前に independent に検証したい」改修者
> **本セッション**: Lateral Association Stage 7 (anti-hub + dormant percentile) の実装完了 → 本番 opt-in enable → default promotion + Phase N β Stage 1.5 (Mass Evaporation) production enable までを 1 セッション内で完遂。検証は 3-observer pattern で full coverage。

## 1. なぜ verification 計画として残すか

Stage 7 + Phase N の rollout は **3 段階** + **3-observer** で検証した:

- **3 段階の rollout**:
  1. 実装 + 内部 test (PR `9a8e82f`、default OFF/None)
  2. 本番 env opt-in (claude.json + opencode.json に env 追加、code 変更なし)
  3. config default 化 (PR `80214b0`、暫定 default active)
- **3-observer**:
  1. **直読み snapshot** — `SqliteStore` 直接読みで mass / dormant pool / top hubs の literal 数値
  2. **dry-run projection** — `scripts/phase_n_dry_run.py` で「もし今 evaporate を 1 回適用したらどうなるか」の予測
  3. **GLM via secondopinion-MCP** — 独立 process / 独立 LLM context で MCP tool 経由の formatter output として検証 (P7-Z observer effect 回避)

3-observer が同じ literal 数値で **一致** したことで、機構の挙動を「設計通り」と確信できた。本ドキュメントはこの検証パターン自体を future 改修の references として残す。

## 2. Verification 対象

### 2.1 Stage 7.1 — Direct-hit anti-hub (cohort_id OR original_id MMR)

**機構**: `services/memory.py::_apply_cluster_anti_hub` で greedy MMR penalty。cluster_key は `_cluster_key_for(cache)` ヘルパー経由で `cohort_id` OR `original_id` (両方とも Phase M 構造識別子)。

**knob**: `direct_hit_anti_hub_lambda: float` — 当初 default `0.0` (OFF)、2026-05-26 中に `0.4` に暫定 promote。

### 2.2 Stage 7.2 — Dormant distribution-relative cut

**機構**: `services/memory.py::_dormant_surface` で `dormant_mass_threshold` 絶対値の代わりに active corpus mass の P パーセンタイル値を cut として使う。

**knob**: `dormant_mass_percentile: float | None` — 当初 default `None` (legacy absolute)、2026-05-26 中に `10.0` に暫定 promote。

### 2.3 Phase N β Stage 1.5 — Mass Evaporation production enable

**機構**: `services/memory.py::evaporate_mass` (純粋関数) + `engine._update_simulation` の lazy 適用 + `engine.startup` での cold-start sweep。Stage 1 実装は別途 (commit `49af8f7`、2026-05-15)。Stage 1.5 = **本番 enable**。

**knob**: `mass_evaporation_enabled: bool` — default `False`、env で `true` に上げて enable (versioned migration 方式、default は OFF のまま維持)。

## 3. 3-Observer 検証パターン

### Observer A — Direct SqliteStore snapshot (`scripts/diag_*.py` 系)

**目的**: DB レイヤの literal な数値を取る。formatter / engine の中間層を介さない ground truth。

**特性**:
- read-only (`store.initialize()` の idempotent migrations のみ)、本番 DB を安全に snapshot 可能
- engine.startup を経由しないので embedder load (RURI) が不要 = 1 秒以下で完了
- 26k node の corpus で問題なく動作

**本セッションで作った tools**:
- `scripts/diag_dormant.py` — active mass percentile 分布 + 各 threshold での dormant 候補数 + per-source breakdown
- セッション内で書き捨てた `.diag-phase-n-snapshot.py` (top-K hubs の precise mass、削除済)

**使用例**:
```bash
# Stage 7.2 percentile 候補の確定
.venv/bin/python scripts/diag_dormant.py --data-dir /home/misaki_maihara/.local/share/gaottt
# → "abs 2.0 で 0 candidates / age=30d 厳しすぎ" を可視化
.venv/bin/python scripts/diag_dormant.py --data-dir /home/misaki_maihara/.local/share/gaottt --age-days 7
# → "p10 で 23 candidates" を観測 → percentile=10 を default に
```

### Observer B — Dry-run projection (`scripts/phase_n_dry_run.py`)

**目的**: 「もしこの操作を今適用したらどうなるか」を **本番 DB を read-only で開いて in-memory で simulate**。`evaporate_mass` を全 active node に対し 1 回適用、before/after の mass 分布 + drain 量 + top loser を md + json で出力。

**特性**:
- 本番 DB を mutate しない (`load_states_and_sources` のみ、cache の write-behind は起動しない)
- 異なる preset (`default / conservative / aggressive / heavy-hub-bias / slow-idle-bias`) を `--sweep` で一括比較
- markdown + JSON 両方出力、後で diff 可能

**本セッションでの run**:
```bash
.venv/bin/python scripts/phase_n_dry_run.py --label "stage15-readiness-2026-05-26"
# → .phase-n-dry-run/stage15-readiness-2026-05-26.md
# Total drain projected: 123.8 (0.27%)、top-1 (f557e7af) 33.99 → 33.25 (-0.74)
```

### Observer C — GLM via secondopinion-MCP (independent observer)

**目的**: P7-Z 原則 (「観察行為が観察対象を変える」) を機構として閉じる。Claude (= 自分) で観察すると recall が field を train してしまうので、**独立 process / 独立 LLM / 独立 context** で観察。CLAUDE.md §「本番 acceptance test の workflow」の gold standard。

**特性**:
- `mcp__secondopinion__delegate_task(provider="glm", task=...)` で opencode 経由 GLM-5.1 を起動
- Claude Code 側の MCP tool result 上限 (~100KB) を超えないよう「substring 検出のみ報告、生出力貼らない」を prompt に明示
- 多段 test を 1 turn で完走させる (token 効率)
- 終了後 `mcp__secondopinion__end_session(session_id=...)` で resource 即解放

**本セッションでの run**:
- Stage 7 acceptance (mass_weight=0.3 + Stage 7.1/7.2 env enabled): 3/4 PASS + 1 PARTIAL (ambient persona rotation は caller の `recently_surfaced` 渡しが前提という発見)
- Phase N β Stage 1.5 acceptance (上記 + mass_evaporation_enabled=true): 4/4 PASS、加えて「Phase N の evaporation は 1 回 sweep で終わらず recall/reflect ごとに漸進的に効き続ける」という設計通りの追加挙動を GLM が独立検出

**Prompt 設計の原則** (CLAUDE.md より):
1. 期待される操作 (具体的な MCP tool 呼び出し: ツール名 + args)
2. 観察項目 (substring 検出、top1/top5/metadata 等の何を見るか)
3. 期待される正解 (LLM 判断のための参考)
4. 報告フォーマット (200-400 字 / test、表 + 集計)
5. **「生出力貼らない、substring 検出のみ報告」を明示**

## 4. Verification の literal な数値 (本セッション全段)

### 4.1 Stage 7.1 anti-hub

**内部 test corpus (12 docs、4 cohorts、`tests/perf/test_tier3_cluster_monoculture.py`)**:

| | baseline (λ=0) | λ=0.4 |
|---|---|---|
| avg_unique_cohorts (ambient direct top-5) | 2.67 | **4.00** |
| avg_max_dominance | 2.33 | **2.00** |
| target_hit_rate | 3/3 | 3/3 (維持) |
| `original_id`-only path (book chunks in direct) | 5/5 (想定) | **2/5** |

**本番 acceptance (GLM 経由)**:
- 米国会社四季報 (638-chunk 本) クエリ → top-5 で book chunks **1/5** (anti-hub なしなら 5/5 になる case)
- 異種抽象クエリ (Phase L hybrid retrieval BM25 等) → top-5 で agent singleton 連発 **残存** (= 想定通り、Phase N 領域)

### 4.2 Stage 7.2 dormant percentile

**`scripts/diag_dormant.py` による本番分布診断 (26,446 active)**:

| age threshold | source filter pass | abs 2.0 | p10 (1.098) | p20 (1.142) | p30 (1.171) | p50 (1.246) |
|---|---|---|---|---|---|---|
| 30 days | **0** | 0 | 0 | 0 | 0 | 0 |
| 7 days | 77 | 75 (flood) | **23** ✅ | 42 | 49 | 58 |
| 0 days | 1,314 | 1,178 (89.6%) | 26 | 72 | 109 | 269 |

→ `percentile=10` + `age=7d` で 23 candidates が sweet spot。

**本番 acceptance (GLM 経由)**:
- `explore(mode='dormant', top_k=25)` → **25/25 surfaced** (LMS knowledge / observer 発見 / completed task / 過去 reflection)

### 4.3 Phase N β Stage 1.5

**dry-run projection vs literal production**:

| 指標 | Before | After (literal) | Delta | Dry-run 予測 | 一致 |
|---|---|---|---|---|---|
| Total mass | 45,151.16 | 45,027.24 | **-123.92** | -123.8 | **99.9%** |
| Dormant pool (mass≤2.0) | 23,904 | 23,910 | **+6** | +6 | **exact** |
| rank 1 (f557e7af, 刑法175条 chunk) | 33.9946 | 33.2534 | **-0.7412** | -0.741 | **exact** |
| rank 2 (6418b5f7, agent) | 32.2750 | 32.2750 | **0** | 不変 | **exact** |
| sweep affected | — | 22,749 / 26,446 (86%) | — | — | — |

**継続観察 (GLM acceptance 経由)**:
- Phase N の evaporation は **1 回 sweep で終わりではなく、recall / reflect 呼び出しごとに漸進的に効き続ける** (DB 直読み 33.25 → GLM reflect 経由 32.52 で更に -0.73 drained。lazy evaluation が機能している証拠)

## 5. 過程で発見した architectural 制約 — anti-hub vs prefetch cache

### 症状

Stage 7.1 anti-hub の初版実装は `services/memory.recall` で `engine.query` の `top_k` を `top_k * 3` に広げて MMR の pool を確保していた。Default 0.4 promote 後、以下のテストが fail:

- `test_prefetch_then_recall_emits_cache_hit_phrase`
- `test_cache_hit_zero_perturbation`
- `test_training_delta_topk_only_limits_coverage`
- `test_prefetch_then_recall_hits_cache`
- ... 計 4 件

### 原因

`prefetch_cache` の key が `(query, top_k)` を含むため、anti-hub on 時の `engine_top_k = top_k * 3` が cache key を変えて **常時 cache miss** になっていた。

### 修正

`services/memory.recall` の expansion を撤回。anti-hub は `engine.query` が返した top_K 内の reorder のみ (= raw recall path では効果が薄い)。一方 `ambient_recall` は内部 pool が `max(direct_k * 5, 10)` = 25 件あるので MMR が full に機能する。

**実際の rollout 後の効果**:
- `ambient_recall` (Claude Code 毎ターン injection): full anti-hub 効果、user-visible value 維持 ✅
- raw `recall` (caller が直接叩く): engine 返却内の reorder のみ、cluster 完全独占ケースには無効

### Lesson

**「機構を default 化する前に、その機構が依存する pool 拡張が cache invariants と衝突しないか確認する」**。今回は default OFF → opt-in env → default 0.4 の 3 段階 rollout のうち、**default 0.4 promote 段で初めて regression が表面化**した。理由は OFF 時は expansion code path が走らないため。

**回避策**: 機構を実装する段階で、cache hit テスト (prefetch + recall round-trip) を意図的に走らせて invariants を検証する。Stage 7.1 初版 PR の test 範囲には「anti-hub on + cache hit」が含まれていなかった。

## 6. Default promote の 3 段階 rollout discipline

Stage 7.1 / 7.2 で意図的に踏んだ 3 段階:

```
段階 1: 実装 + 内部 test、default OFF
   - PR ``9a8e82f`` (feat lateral-association Stage 7)
   - knob 値: ``direct_hit_anti_hub_lambda=0.0``, ``dormant_mass_percentile=None``
   - 内部 test では explicit に λ=0.4 / percentile=20 を set して acceptance 確認

段階 2: 本番 env opt-in (code 変更なし)
   - claude.json + opencode.json に env 追加 (めいさん側で ``claude mcp add --env=...``)
   - production backend を kill → respawn で env inherit
   - 本番 acceptance (直読み snapshot + GLM independent)

段階 3: config default に promote
   - PR ``80214b0`` (feat stage-7 promote anti-hub λ=0.4 + dormant percentile=10 to defaults)
   - knob 値: ``direct_hit_anti_hub_lambda=0.4``, ``dormant_mass_percentile=10.0``
   - **段階 3 で初めて anti-hub vs cache の architectural 制約が表面化**
   - 修正 → 新 default で再 acceptance
```

Phase N β Stage 1.5 はこの 3 段階のうち **段階 2 のみ**:
- Stage 1 実装 (`49af8f7`、2026-05-15) では default OFF を維持
- Stage 1.5 enable は **env 経由のみ** (`mass_evaporation_enabled=true`)
- default 化は **しない** — Plans-Phase-N §8 の "Stage 1.5 は本番に enable する PR を別途切る" 方針通り、慎重 rollout

なぜ Phase N は段階 3 をスキップするか:
- evaporation は **irreversible** (mass drain は復元しない、Plans §9)
- 新規 deployment が暗黙に evaporation 有効化されると不要な mass drain が発生する
- 本番運用判断が必要な knob は default OFF で env explicit の方が安全

Stage 7 は逆に:
- anti-hub / percentile cut は **重力場を mutate しない** (ranking 変更 + filter 変更のみ)
- 新規 deployment でも安全に動く
- default 化することで「Stage 7 を意識しなくても恩恵を受ける」状態が作れる

## 7. 関連 commits + artifacts

**Commits (PR #21、dev → main)**:
- `ec1fb01` docs(client-setup): OpenAI Codex CLI への MCP 登録方法 (Stage 7 と独立、PR bundle に含む)
- `9a8e82f` feat(lateral-association): Stage 7 — direct-hit anti-hub + dormant percentile cut (Stage 7.1/7.2 実装 + 内部 test、default OFF/None)
- `4c3057e` docs: Lateral Association Stage 7 を CLAUDE.md + Architecture-Overview に反映
- `80214b0` feat(stage-7): promote anti-hub λ=0.4 + dormant percentile=10 to defaults

**Plans (本セッションで触れた docs)**:
- [Plans — Ambient Recall Lateral Association](../wiki/Plans-Ambient-Recall-Lateral-Association.md) — Stage 7 セクション
- [Plans — Phase N β Mass Evaporation](../wiki/Plans-Phase-N-Mass-Evaporation.md) — Stage 1.5 readiness verdict (2026-05-15 GLM dry-run evaluation)
- [Operations — Tuning](../wiki/Operations-Tuning.md) — 新 knob 行
- [Architecture — Overview](../wiki/Architecture-Overview.md) — 設計判断表に Stage 7 行

**User memory (Claude Code auto-memory)**:
- `project_lateral_association_observation.md` — Stage 7 dogfooding 観察期
- `project_phase_n_stage_1_5_enabled.md` — Phase N enable milestone

**gaottt memory (本セッションで保存した key memos)**:
- `eb6da352` STAGE-7-DESIGN — cluster_key 拡張判断
- `0fca0dd6` STAGE-7-LIMITATION — Stage 7.1 scope と Phase N 領域の切り分け
- `116df61f` STAGE-7-LEARNING — dogfooding-as-design-test 方法論
- `614e38aa` STAGE-7-DORMANT-AGE — 30 日 threshold は active user に厳しすぎ
- `966fae69` STAGE-7-VALIDATION — 本番 acceptance 完成値
- `620ab370` PHASE-N-STAGE-1.5-ENABLE — 2026-05-26 production enable
- `1fe532ce` ARTICULATION-AS-CARRIER-SYMMETRY — Phase M + N β 対称完成

## 8. 次の verification 時に参考にすべきもの

future 改修者 (Claude も含む) が「本番に rollout する前に 3-observer で検証したい」と思った時:

1. **Observer A 用に diag script を 1 つ書く** — read-only、本番 DB を安全に snapshot する形で。`scripts/diag_dormant.py` を雛型に。
2. **Observer B 用に dry-run projection を考える** — 変更が DB を mutate する系なら、適用前の予測 markdown を出すツール。`scripts/phase_n_dry_run.py` を雛型に。
3. **Observer C 用に secondopinion-MCP prompt を書く** — 「生出力貼るな、substring 検出のみ」を明示。本セッションの prompt は (Stage 7 + Phase N) を 4-5 test ずつ 1 ターンで完走させる形式。
4. **3 観測の literal 一致を確認** — 直読みと dry-run と GLM が同じ数値を見たら設計通り、ズレたら原因を追う。
5. **default promote する前に cache invariants を確認** — anti-hub の architectural 制約は段階 3 で初めて表面化した。`tests/perf/test_tier1_phase_o_trailers.py` の cache-hit phrase / `test_engine_training_delta.py` の topk_only / `test_engine_explore_dormant.py` の absolute-threshold pinning を意図的に試して、新 default 下でも壊れないか先回りで確認する。

---

## Appendix — 本セッションで使った env knob 一覧

production backend (claude.json + opencode.json で永続化済み):

```bash
GAOTTT_AMBIENT_PERSONA_MASS_WEIGHT=0.3       # Refinement follow-up (b)
GAOTTT_DIRECT_HIT_ANTI_HUB_LAMBDA=0.4        # Stage 7.1 (default に promote 済)
GAOTTT_DORMANT_MASS_PERCENTILE=10            # Stage 7.2 (default に promote 済)
GAOTTT_DORMANT_AGE_THRESHOLD_SECONDS=604800  # active user 用 7d (default は 30d のまま)
GAOTTT_MASS_EVAPORATION_ENABLED=true         # Phase N β Stage 1.5 (default は OFF のまま、env で opt-in)
```

config default に上がったもの (PR `80214b0`):
- `direct_hit_anti_hub_lambda: 0.0 → 0.4`
- `dormant_mass_percentile: None → 10.0`

env でしか有効化されていないもの (default は保守的):
- `mass_evaporation_enabled: False` のまま (irreversible 操作なので default OFF を維持)
- `dormant_age_threshold_seconds: 30 days` のまま (新規 deployment への影響を考慮)
- `ambient_persona_mass_weight: 1.0` のまま (Refinement follow-up は別途観察) — ※追記 (2026-07-02): 当時は 1.0 のままだったが、後に 0.3 へ default 昇格、`ambient_persona_min_relevance` も 0.5→0.65 へ昇格 (harakiriworks dominance 対策、Plans-Ambient-Recall-Refinement.md 「Follow-up (b) follow-through」節・ToDo 6-7 参照)
