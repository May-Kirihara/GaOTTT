# Session Handover — 2026-05-13 (Phase J Stage 1 完了 — Persona-Anchored Retrieval)

> **読者**: 次のセッションでこのリポジトリを触る Claude / 保守者
> **前回の handover**: [`handover-2026-05-13-phase-i-stage-3.md`](handover-2026-05-13-phase-i-stage-3.md) (Phase I Stage 3 完了 + acceptance 結果 → Phase J 設計)
> **本セッション**: Phase J Stage 1 (Persona-Anchored Seed Boost) を最小実装で完了。Plans → 設計 → 実装 → テスト → docs → handover を 1 セッションで完走、commit 未実施でめいさん acceptance 待ち。

## 1. 何が起きたか — 流れ

1. **前回からの継続** — Phase I Stage 3 acceptance test がめいさん側で実行され、Stage 3 が想定外に効かないことが判明 (前 handover §「acceptance 結果」参照)。Stage 3 は新規ノードの「単一アトラクタ pathology」を防ぐが、本番で起きていたのは「dense mature agent cluster (前 session で記録した自己知識) vs sparse new agent cluster (今 session の harakiriworks 記録)」の押し退け
2. **Phase J 設計合意** — 4 判断 (Plan 配置 / 入口 / proximity / 介入点) すべて recommended で確定。B (新 Phase J) + c (Both explicit/implicit) + i (Graph traversal) + α (Seed step)
3. **Plans-Phase-J-Persona-Anchored-Retrieval.md 起こし** — 設計判断 / 段階分け / Stage 1 範囲 / hyperparameters / テスト戦略 / acceptance 判定基準 / rollback / 倫理条項 を網羅 (前 handover §「Phase J 設計開始」)
4. **Roadmap + Sidebar + Stage 3 handover 更新** — Phase J を Phase I の隣に追加、Stage 3 handover に acceptance 結果と Phase J への遷移を追記
5. **実装フェーズ突入** — 「実装をおねがいします」で本 handover の作業に入る
6. **Cache/Store の edge API 調査** — `cache.get_neighbors` は co-occurrence のみ。directed edges は `store.get_directed_edges()` で取れるが async、`propagate_gravity_wave` は sync なので毎 recall に呼べない。**Phase H Stage 2 の `source_by_id` と同じ pattern** で CacheLayer に乗せる方針確定
7. **config + cache + persona_gravity 実装** — `mass_anchor_threshold` の隣に `persona_boost_*` 5 field、CacheLayer に `directed_out`/`directed_in` dict + load/sync method、新 `core/persona_gravity.py` (collect_active_persona_ids + compute_persona_proximities)
8. **gravity.py 統合** — `propagate_gravity_wave` に `persona_proximities` 引数、`_seed_boost` helper で 3 つの seed path (source_filter / mass-aware / legacy) を統一、各 path で mass + persona を加算
9. **engine.query 統合** — recall ごとに `collect_active_persona_ids` + `compute_persona_proximities` を呼んで proximities を計算、`propagate_gravity_wave` に渡す
10. **engine.relate / unrelate 同期** — `store.upsert_directed_edge` の直後に `cache.set_directed_edge` を呼んで in-memory を最新化。`unrelate` も同様
11. **テスト追加** — unit 13 件 (collect: 3 / proximity: 10) + integration 3 件 (boost lifts linked memo / disabled legacy / relate-unrelate cache sync)
12. **検証** — pytest: 196 passed (+16 from Phase I Stage 3 の 180)、1 skipped。ruff: pre-existing 4 件のみ。bench: p50=16.1ms / p99=37.0ms (Stage 3 から劣化なし)、7/7 SC pass
13. **付随 docs 同期** — Architecture-Overview / Operations-Tuning / CLAUDE / SKILL ×2 (cp で同期)
14. **本 handover 作成**

## 2. 今のリポジトリ状態 (2026-05-13 セッション終了時点、Phase J Stage 1 完了直後)

- **branch: `dev`、commit 未実施**
- 最新 commit: `271b876 feat(scripts): add migrate.py — versioned data migration tool` (Phase I Stage 3 含む全変更が working tree dirty)
- pytest: **196 passed, 1 skipped, 3 warnings**
- ruff: pre-existing 4 件のみ (新規コード clean)
- bench: 7/7 pass、p50=16.1ms / p99=37.0ms

### 変更ファイル

**Phase J Stage 1 で新規:**
- `gaottt/core/persona_gravity.py` (新規) — `collect_active_persona_ids` + `compute_persona_proximities`
- `tests/unit/test_persona_gravity.py` (新規) — 13 件
- `tests/integration/test_engine_persona_anchored.py` (新規) — 3 件
- `docs/wiki/Plans-Phase-J-Persona-Anchored-Retrieval.md` (新規)
- `docs/maintainers/handover-2026-05-13-phase-j-stage-1.md` (新規、本ファイル)

**Phase J Stage 1 で修正:**
- `gaottt/config.py` — Phase J hyperparameters 5 個追加
- `gaottt/core/gravity.py` — `_seed_boost` helper + `propagate_gravity_wave` の `persona_proximities` 引数 + 3 seed path 統一
- `gaottt/core/engine.py` — import + `query` で proximities 計算 + `relate`/`unrelate` で cache 同期
- `gaottt/store/cache.py` — `directed_out`/`directed_in` + set/remove method + `load_from_store` で全 directed edges load + `evict_node` で sync prune
- `docs/wiki/Architecture-Overview.md` — 設計判断表に Phase J 行
- `docs/wiki/Operations-Tuning.md` — `persona_boost_*` セクション追加
- `docs/wiki/Plans-Roadmap.md` — Phase J 行追加
- `docs/wiki/_Sidebar.md` — Phase J リンク追加
- `CLAUDE.md` — Last updated + 五層思想段落更新
- `SKILL.md` + `.claude/skills/gaottt/SKILL.md` (cp 同期)

**Phase I Stage 3 から残置 (前 session の変更):**
- `gaottt/core/gravity.py` の `compute_acceleration` (Stage 3 gate)
- `tests/unit/test_query_kick.py` (Stage 3 追加 3 件)
- `tests/integration/test_engine_query_kick.py` (Stage 3 追加 1 件)
- `docs/wiki/Plans-Phase-I-Free-Star-Movement.md` (Stage 3 セクション)
- `docs/maintainers/handover-2026-05-13-phase-i-stage-3.md` (acceptance 結果追記済)
- `docs/maintainers/handover-2026-05-12-self-knowledge-completion.md` (前々 session)

## 3. 実装の要点

### 設計の核

Phase D の persona ノード (value/intention/commitment) からの **graph 距離** を proximity に変換し、recall の **seed step** で boost する:

```
proximity(node) = persona_hop_decay ** min_hop_distance(node, declared_persona_set)
                  0 if beyond persona_max_hop

boosted_seed_score = raw_cosine
                   + wave_seed_mass_alpha × log(1 + mass)        # Phase H Stage 1
                   + persona_boost_alpha × proximity              # Phase J Stage 1
```

これは Phase H Stage 1 (mass-aware) と直交する加算項として実装され、両方独立 on/off できる。

### Active persona の auto-detect (Stage 1)

`cache.source_by_id` をスキャンして source が `{"value", "intention", "commitment"}` のものを集める:

- Cache は archived ノードを load しないので、archived persona は自動除外
- Stage 1 は **TTL 検証なし** (cache 信頼)。Stage 2 で commitment の `last_access` ベース TTL を加える
- `persona_boost_enabled=False` で空 set を返す → 全 path skip

### Graph traversal の方向

Multi-source BFS、persona set 全員 hop=0 で開始、`cache.directed_out` と `cache.directed_in` の **両方向** を辿る:

- Phase D の `fulfills` は **task → parent intention** の有向 edge — persona 側から見ると incoming
- `derived_from` は **extension → seed** — persona 側から見ると incoming
- `completed` は **outcome → task** — persona 側から見ると incoming (2 hop で task 経由)
- 両方向辿るので edge 方向を Stage 1 で判別する必要なし。`supersedes` / `contradicts` も拾うが Stage 1 は許容

### Cache に directed_edges を乗せた背景

`propagate_gravity_wave` は **sync 関数**。SqliteStore は **async**。 sync 内で async を await できないので、毎 recall に DB hit するなら traversal を engine.query (async) 側で完了させる必要があった。

選択肢の比較:
- **A: cache に load (採用)** — Phase H Stage 2 で `source_by_id` を同じ pattern で乗せた前例あり。startup 1 度の load + relate/unrelate で同期、recall 時は memory のみ。
- B: engine.query で BFS、proximities dict を作って propagate_gravity_wave に渡す — recall 1 回で `persona × hop_branching ^ max_hop` 個の async query が走る (現実的に 100+ ms latency)
- C: lazy load — 初回 recall 時に全 directed load。最初の 1 query が遅い

A が一番自然。directed_edges は本番 23k DB でも数百レベルなのでメモリ消費も無視できる。

### 実装の最小性 (CLAUDE.md の実装フロー 1 ステップ)

CLAUDE.md の MCP/REST parity 鉄則の対象外:
- Stage 1 は recall API 変更なし (auto-detect のみ)
- store/schema 変更なし
- services 変更なし
- types.py 変更なし (`Request`/`Body` 変わらず)
- MCP/REST tools 変わらず

Stage 2 で `persona_context: list[str] | None` 引数を recall に追加するときに MCP/REST 両方を同一 commit で更新する (parity 鉄則)。

## 4. ハイパーパラメータと運用

### 既定値の根拠

| 名前 | 既定 | 根拠 |
|---|---|---|
| `persona_boost_enabled` | `True` | Stage 1 を本番で active にする |
| `persona_boost_alpha` (α) | `0.5` | `wave_seed_mass_alpha=0.1` の 5×。「context が mass より優先」の prior。本番で persona-tied node が seed に入らなければ `1.0` まで上げる |
| `persona_max_hop` | `2` | Phase D の典型チェーン (intention → task → outcome) を拾える深さ。3 以上で間接的混入リスク |
| `persona_hop_decay` | `0.5` | 1 hop 0.5、2 hop 0.25。`0.7` なら 2 hop でも 0.49 で強い、`0.3` なら 2 hop で 0.09 で急減衰 |
| `persona_active_ttl_seconds` | `14 日` | commitment TTL と同期。Stage 1 では未使用、Stage 2 で利用 |

### Roll-back

```bash
# Soft (config 1 行で完全 skip):
echo '{"persona_boost_enabled": false}' > ~/.config/gaottt/config.json
# サーバー再起動だけ
```

DB 状態は触らない、migration 不要。

### 本番 DB での acceptance test (めいさんに委ねる)

前 session の 7 query (harakiriworks-self-knowledge Phase 1-9 系) を再走。

**判定基準** (Plans-Phase-J §「Stage 1 実装範囲 § Acceptance」より):

| 指標 | Phase J Stage 1 前 (現状) | Phase J Stage 1 後 (期待) |
|---|---|---|
| harakiriworks intention `eb31f843` に紐付くノードが top1 | 1/7 | ≥ 4/7 |
| unique top1 ID 数 | 2 (Stage 3 acceptance) | ≥ 4 |

**注意点**:
- 本番 acceptance を取る前に、harakiriworks の 112 件のうち何件が `fulfills` / `derived_from` で intention `eb31f843` に繋がっているか確認。もし edge が張られていなければ、Phase J Stage 1 は **何も boost できない** (graph 距離 ∞)。
- `eb31f843` の incoming edge を `get_relations(node_id="eb31f843", direction="in")` で確認、必要なら `relate(harakiriworks_node, "eb31f843", "derived_from")` を一括で張る ritual が前提条件になる可能性
- これは設計判断の倫理 #4「acceptance を Plans 内に明記」が示した「test green ≠ acceptance」教訓の continuation

## 5. 学んだ lesson (Phase J Stage 1 で見えたもの)

### 5.1 「sync 関数の中で async を呼びたければ、必要な状態を cache に乗せる」

`propagate_gravity_wave` が sync である制約から、Phase J Stage 1 は **CacheLayer の拡張** が必要不可欠だった。これは Phase H Stage 2 で `source_by_id` を乗せた経緯と同じ pattern。設計の制約が implementation pattern を決める典型例。

**将来 Stage への含意**: もし sync 関数で何かの DB データを参照したい場合、まず CacheLayer に乗せる検討。逆に「cache に乗せると重い」場合は engine.query (async) 側で事前計算して dict で渡す方針 (Phase J でも `persona_proximities` は engine 側で計算)。

### 5.2 「persona_gravity の auto-detect は cache 信頼で十分」

Stage 1 設計時に「TTL 切れの commitment を除外すべきか」を検討したが、**cache 自体が archived ノードを load しない設計** なので、cache.source_by_id にいるなら active と扱える。Stage 1 では TTL 検証を省略。

これは「**信頼できる layer の上に信頼を積む**」原則。cache が archived フィルタを行うなら、上層 (persona_gravity) は cache を信頼するだけで OK。重複検証はコードを膨らませる。

Stage 2 で commitment の `last_access` ベース TTL を導入するときも、まず cache が `last_access > now - 14 days` でフィルタする方が clean。

### 5.3 「Stage 1 と Stage 2 を分離した設計の重み」

Phase J を 3 stage に分けた (Stage 1 内部のみ / Stage 2 API 拡張 / Stage 3 prefetch/explore 拡張)。最初の Stage を **API 変更なし** にしたことで:

- MCP/REST parity 鉄則の対象外 → 実装範囲が core/store のみに閉じる
- 本番 acceptance を「内部挙動の改善」だけで取れる → API 拡張のコストなしに値を verify できる
- Stage 2 を後で別 commit で追加できる → 段階的 release

これは「最初の Stage で **API 表面 = 0 変更** を目指す」原則。Stage 3 でも同じ pattern (mass_anchor_threshold は内部 hyperparameter、API 変更なし)。

### 5.4 「Five-Layer 翻訳は本物だった」

CLAUDE.md と Reflections-Five-Layer-Philosophy.md で「物理 → TTT → 生物 → 関係 → 人格」と書いてきた五層の翻訳が、Phase J Stage 1 で **コードの実体** になった。

Phase D で「人格を declare できる」を構造として置いた (relations table + value/intention/commitment source)。Phase J Stage 1 はその構造を **retrieval geometry に literal に翻訳** している。`fulfills`/`derived_from`/`completed` edge は単なる注釈ではなく、recall 時の重力場の geodesic として作用する。

これは設計初期に書いた reflections が、abstract な比喩ではなく **operational な仕様** だったことの証明。CLAUDE.md の語彙に書いた「人格層 → 関係層 → 物理層」が実装上の階層に対応している。

## 6. 残る open tasks

### Phase I 系 (Stage 1 acceptance test 等、変わらず)

| id | 内容 | deadline |
|---|---|---|
| `72e84a73` | Phase I Stage 1 長期検証 (1-2 週間運用後の displacement 分布測定) | 2026-06-01 |
| `d668ba35` | wave_k_with_filter=500 → 1000 引き上げ判断 | 2026-06-10 |
| `94fd3f23` | bootstrap_report.py の virtual FAISS 対応 | 2026-06-10 |
| `7bfff23d` | dream loop 効果の定量化ベンチ整備 | 2026-06-10 |
| `804bc91f` | virtual FAISS の write-behind 検討 | 2026-06-10 |

### Phase J 系 (新規、Stage 2/3 候補)

Plans-Phase-J §「段階分け」に記述。task 化は本番 acceptance 後:

1. **Stage 2: Explicit `persona_context` 引数**
   - recall に optional list[str] 引数を追加
   - MCP + REST parity で同一 commit 公開
   - `services/memory.py recall` 関数の追加引数
   - types.py の Request/Body 拡張
2. **Stage 3: Prefetch / Explore 拡張 + Reflect aspect "persona_field"**
   - prefetch も persona-anchored
   - explore は default で persona off (cross-domain serendipity 目的)
   - 可視化 reflect aspect
3. **Source-aware gate (Phase I の Stage 4 候補から移植)**
   - persona 関係ない agent vs file の不均衡を別軸で扱う

## 7. 次セッションでやるとよいこと (優先度順)

### 7.1 本番 DB で Phase J Stage 1 の acceptance test (最優先)

#### 前提条件 — 2026-05-13 セッション内確認結果

harakiriworks 112 件は **完全 orphan** (どの directed edge にも繋がっていない)。
existing 構造は以下:

```
9f99be21 (intention "harakiriworks 重力場")
   ↑ fulfills (1 edge)
eb31f843 (commitment "Phase 1-9, 21日 deadline")
   ↑ fulfills (9 edges) — Phase task のみ
697fdaab (Phase 1 task) ← completed ← 99fe8896 (outcome)
138953c0 (Phase 2 task) ← completed ← 0bae6230 (outcome)
7aad286a (Phase 3 task) ← completed ← 9462ed1c (outcome)
166fc419 (Phase 4 task) ← completed ← a62c575f (outcome)
187785a3 (Phase 5 task) ← completed ← 44d7582c (outcome)
eb201f7a (Phase 6 task) ← completed ← 9d9e0650 (outcome)
862fc296 (Phase 7 task) ← completed ← 533c29ab (outcome)
613e669a (Phase 8 task) ← completed ← fa9c94f1 (outcome)
db089956 (Phase 9 task) ← completed ← 90e41660 (outcome)
(112 個別 phase memory) ← ORPHAN
```

Phase J Stage 1 の persona traversal は `commit eb31f843` から 2 hop で:
- commitment → fulfills (incoming) → Phase task (1 hop)
- Phase task → derived_from (incoming) → memory (2 hop)

の経路を期待する。**現状はこの 2 hop 目が無い**。

#### Hierarchical 2-hop ritual (方法 A 採用、2026-05-13 めいさん選択)

各 memory → derived_from → 該当 Phase task の **112 本** の relate。Phase task の
ID は上記既存構造から:

| Phase | Task ID | 期待 derived_from 本数 |
|---|---|---|
| Phase 1 (哲学・トーン) | `697fdaab` | ~10 |
| Phase 2 (Critical Gotchas) | `138953c0` | ~34 |
| Phase 3 (系譜・採用/不採用) | `7aad286a` | ~39 |
| Phase 4 (ファイル責務) | `166fc419` | ~18 |
| Phase 5 (運用ノウハウ) | `187785a3` | ~16 |
| Phase 6 (研究系成果) | `eb201f7a` | ~12 |
| Phase 7 (失敗の物語) | `862fc296` | ~10 |
| Phase 8 (handover) | `613e669a` | ~1 |
| Phase 9 (将来研究方向) | `db089956` | ~1 |

(件数は前 session handover-2026-05-12 §3 を参照。手元 DB で `reflect(aspect="hot_topics", limit=200)` + tag フィルタで確認可能。)

#### Ritual 実行方法 (3 つの案、めいさん選択)

**案 A1: MCP セッションで手動 relate** — 透明、cache 同期も自動
```python
# 各 phase の memory id を recall で集めて relate を呼ぶ
ids_phase_1 = recall(query="harakiriworks-self-knowledge phase-1", top_k=20, wave_k=1000)
for memo_id in ids_phase_1:
    relate(src_id=memo_id, dst_id="697fdaab", edge_type="derived_from")
# Phase 2-9 も同様、112 件分
```

**案 A2: 専用 script** — 一発で済む、ただし MCP server kill が前提
```bash
# scripts/ritual_harakiriworks_edges.py を書いて実行
# (Phase J Stage 1 commit には含まない、別 commit/manual で対応)
python scripts/ritual_harakiriworks_edges.py --dry-run
python scripts/ritual_harakiriworks_edges.py --apply
# その後 MCP server 再起動 (cache reload で新 edges 反映)
```

**案 A3: tag base で SQLite に直接 INSERT** — 最速、要 SQL 知識
```sql
INSERT INTO directed_edges (src, dst, edge_type, weight, created_at)
SELECT n.id, '697fdaab', 'derived_from', 1.0, strftime('%s', 'now')
FROM nodes n
WHERE n.metadata LIKE '%"phase-1"%' AND n.metadata LIKE '%harakiriworks%';
-- Phase 2-9 同様、9 statements
```
MCP server kill 後実行、再起動で cache reload。

#### 推奨: 案 A1 (透明性 + cache 同期自動)

ただし 112 回の手作業は重いので、recall + Python loop が現実的。MCP の Python
SDK or claude-code 内の bash で呼ぶ。

#### Acceptance 判定

1. Ritual 完了後、MCP サーバー再起動 (cache が新しい directed_edges を load)
2. 前 session の 7 query を再走
3. 期待値:
   - harakiriworks 系が top1 に来る率 ≥ 4/7
   - unique top1 ID 数 ≥ 4
   - top1 で来た memory が intended Phase に属する (例: query "F006" → Phase 4 #5 `45689886`)
4. 期待外なら `persona_boost_alpha` を `1.0` まで上げる、または案 A1 で torch derived_from を verify
5. Stage 1 で十分なら commit message に「Phase J Stage 1 acceptance ≥ 4/7」を含めて push、不十分なら Stage 2 (explicit persona_context) や Source-aware gate を検討

### 7.2 commit と push (めいさん合意済の方法 A: 別 commit)

#### 実装上の課題

本セッションで Stage 3 + Phase J Stage 1 を **同日に実装** したため、以下 6 ファイルは
両 Stage の修正を 1 つの diff に持つ:

| ファイル | Stage 3 部分 | Phase J Stage 1 部分 |
|---|---|---|
| `gaottt/config.py` | `mass_anchor_threshold` field | `persona_boost_*` 5 fields |
| `gaottt/core/gravity.py` | `compute_acceleration` の gate | `_seed_boost` + `propagate_gravity_wave` 引数 |
| `docs/wiki/Architecture-Overview.md` | Stage 3 行 | Stage 1 行 |
| `docs/wiki/Operations-Tuning.md` | Query 引力 section の Stage 3 更新 | Persona boost section 新設 |
| `CLAUDE.md` | Last updated (Stage 3) | Last updated (Phase J Stage 1 上書き)、五層段落 |
| `SKILL.md` / `.claude/skills/gaottt/SKILL.md` | Stage 3 段落 | Phase J 段落 |

純粋な方法 A (Stage 3 と Phase J を別 commit) には **git add -p で hunks を分割**
する必要がある。手動 hunks 選択は fragile (各 hunk で y/n、間違えると history 汚染)。

#### 推奨手順 (3 commit、実用的に分けやすい単位)

**Commit 1**: `feat(engine): Phase I Stage 3 — mass-gated query attraction`

git add -p で Stage 3 部分のみを stage:
```bash
git add -p gaottt/config.py        # mass_anchor_threshold hunk のみ accept (y)、persona_* hunk skip (n)
git add -p gaottt/core/gravity.py  # compute_acceleration の gate hunk のみ accept
# Stage 3 専用 (-p 不要)
git add tests/unit/test_query_kick.py \
        tests/integration/test_engine_query_kick.py \
        docs/wiki/Plans-Phase-I-Free-Star-Movement.md
git commit -m "feat(engine): Phase I Stage 3 — mass-gated query attraction"
```

**Commit 2**: `feat(engine): Phase J Stage 1 — persona-anchored seed boost`

残りの diff (Phase J 部分) と Phase J 専用ファイル:
```bash
git add gaottt/config.py gaottt/core/gravity.py  # 残りの Phase J hunks
git add gaottt/core/persona_gravity.py \
        gaottt/store/cache.py \
        gaottt/core/engine.py \
        tests/unit/test_persona_gravity.py \
        tests/integration/test_engine_persona_anchored.py \
        docs/wiki/Plans-Phase-J-Persona-Anchored-Retrieval.md \
        docs/wiki/Plans-Roadmap.md \
        docs/wiki/_Sidebar.md
git add -p docs/wiki/Architecture-Overview.md  # Phase J 行のみ、Stage 3 行は Commit 1 へ
git add -p docs/wiki/Operations-Tuning.md      # Persona section のみ、Stage 3 update は Commit 1 へ
git add -p CLAUDE.md                            # Phase J Last updated + 五層段落 (Stage 3 行は Commit 1 で済)
git add -p SKILL.md .claude/skills/gaottt/SKILL.md  # Phase J 段落
git commit -m "feat(engine): Phase J Stage 1 — persona-anchored seed boost"
```

**Commit 3**: `docs: handover — 2026-05-13 Phase I Stage 3 + Phase J Stage 1`

新規 handover docs (untracked):
```bash
git add docs/maintainers/handover-2026-05-12-self-knowledge-completion.md \
        docs/maintainers/handover-2026-05-13-phase-i-stage-3.md \
        docs/maintainers/handover-2026-05-13-phase-j-stage-1.md
git commit -m "docs: handover — 2026-05-13 Phase I Stage 3 + Phase J Stage 1"
```

#### 簡易代替手段 (時間優先、history は粗いが実用的)

git add -p の hunk 選択が煩雑なら、**1 commit にまとめる** ことも可:
```bash
git add -A
git commit -m "$(cat <<'EOF'
feat(engine): Phase I Stage 3 (mass-gated kick) + Phase J Stage 1 (persona-anchored seed boost)

Phase I Stage 3 — mass_anchor_threshold で compute_acceleration 第 4 項に
gate = tanh(m/θ) を乗じ、新規ノードを anchor (Hooke) が保護。単一アトラクタ
pathology の物理的矯正。詳細: docs/wiki/Plans-Phase-I-Free-Star-Movement.md §Stage 3

Phase J Stage 1 — declared value/intention/commitment から fulfills/derived_from
を N hop traverse、seed step で α_persona × proximity を加算。Phase I Stage 3
acceptance で見えた dense mature agent cluster vs sparse new agent cluster
問題への文脈論的解。詳細: docs/wiki/Plans-Phase-J-Persona-Anchored-Retrieval.md
EOF
)"
```

過去 commit history (Phase I Stage 1/2 は別 commit) と整合させたいなら 3 commit、
時間優先なら 1 commit。判断はめいさんに委ねる。

### 7.3 Stage 2 設計 (Stage 1 acceptance 後)

acceptance で想定通り (top1 率 ≥ 4/7) なら、Stage 2 に進む:

- `recall(query, persona_context=["intention-id-1", ...])` 引数追加
- 既存 auto-detect は引数 None 時の fallback
- MCP / REST parity で公開

Stage 2 は実装範囲が大きい (types/services/server 全部触る) ので独立セッションで。

## 8. 設計判断・トーン原則の継承

### 前 handover からの継承 (引き続き有効)

- 「検証ループを最後まで回す」(2026-05-11 §5.1)
- 「組み上がる前に initial seed を入れる」(2026-04-21 §1.3)
- 「逆方向 cache 上書きの罠 — bulk は他プロセス kill から」(2026-05-11 §5.3)
- 「冗長な制約は active な制約と同症状を引き起こす」(2026-05-11 §7.1)
- 「観察行為が観察対象を変える」(2026-05-11 §7.2)
- 「物理に任せられるところは物理に任せる」(2026-05-11 §7.3)
- 「session 越境 inventory は initial recall では不十分」(2026-05-12 §8.1)
- 「番号衝突は再番号より共存」(2026-05-12 §8.2)
- 「Phase 構成は三層構造に自然収束する」(2026-05-12 §8.3)
- 「足りない保護は active な過剰駆動と同じ症状を引き起こす」(2026-05-13 Stage 3 §5.1)
- 「legacy test は明示的に rollback mode を渡して意味的純度を保つ」(2026-05-13 Stage 3 §5.2)
- 「Total displacement 磁量は neighbor gravity が支配的、projection で isolate せよ」(2026-05-13 Stage 3 §5.3)
- 「unit/integration test + bench は実装の正しさ、acceptance test は設計の正しさ」(2026-05-13 Stage 3 §5.4)
- 「Articulation as Carrier の重力は方向を持つべき」(2026-05-13 Stage 3 §5.5)

### 本セッションで追加 (§5 再掲)

- 「sync 関数の中で async を呼びたければ、必要な状態を cache に乗せる」(§5.1)
- 「auto-detect は cache 信頼で十分、重複検証はコードを膨らませる」(§5.2)
- 「最初の Stage で API 表面 = 0 変更を目指す」(§5.3)
- 「Five-Layer 翻訳は本物だった — Phase D の declare 構造が retrieval geometry に literal に翻訳された」(§5.4)

## 9. 関連ドキュメント

- [前 handover (Phase I Stage 3 + acceptance 結果)](handover-2026-05-13-phase-i-stage-3.md)
- [Plans — Phase J](../wiki/Plans-Phase-J-Persona-Anchored-Retrieval.md) — 設計書 + 段階分け + 倫理条項
- [Plans — Phase I](../wiki/Plans-Phase-I-Free-Star-Movement.md) — Stage 1-3 全体
- [Plans — Roadmap](../wiki/Plans-Roadmap.md) — 全 Phase 俯瞰
- [Operations — Tuning](../wiki/Operations-Tuning.md) — `persona_boost_*` 行
- [Architecture — Overview](../wiki/Architecture-Overview.md) — 設計判断表
- [Reflections — Five-Layer Philosophy](../wiki/Reflections-Five-Layer-Philosophy.md) — 五層思想

## 10. 付録: 本 session で変更したファイル一覧

**新規:**
- `gaottt/core/persona_gravity.py` (+115 行)
- `tests/unit/test_persona_gravity.py` (+177 行)
- `tests/integration/test_engine_persona_anchored.py` (+150 行)
- `docs/wiki/Plans-Phase-J-Persona-Anchored-Retrieval.md` (+250 行)
- `docs/maintainers/handover-2026-05-13-phase-j-stage-1.md` (本ファイル)

**修正:**
- `gaottt/config.py` (Phase J hyperparameters +15 行)
- `gaottt/core/gravity.py` (`_seed_boost` helper + 3 path 統一 + `persona_proximities` 引数、+25 行)
- `gaottt/core/engine.py` (import + query で proximities 計算 + relate/unrelate 同期、+20 行)
- `gaottt/store/cache.py` (`directed_out`/`directed_in` + method + load + evict、+90 行)
- `docs/wiki/Plans-Roadmap.md` (Phase I 表記更新 + Phase J 行追加、+5 行)
- `docs/wiki/_Sidebar.md` (Phase J リンク追加、+1 行)
- `docs/wiki/Architecture-Overview.md` (Phase J 行追加、+1 行)
- `docs/wiki/Operations-Tuning.md` (Persona boost セクション追加、+15 行)
- `CLAUDE.md` (Last updated + 五層思想段落、置換)
- `SKILL.md` + `.claude/skills/gaottt/SKILL.md` (Phase J 段落 + Notes、cp 同期、+5 行)

合計: コード +250 行、テスト +330 行、ドキュメント +280 行。

---

> *Phase J Stage 1 は、Phase D で書いた declare 構造を、retrieval の重力場に直接編み込んだ。`fulfills` と `derived_from` はもう単なる注釈ではない — 重力線として recall を曲げる。前 session で書いた自分の memo が、現在 session の memo を押し退ける現象は、Articulation as Carrier の literal な動作だったが、その重力が「今 declared な文脈」を向いていなかったことが問題だった。Phase J Stage 1 はその方向を与える。Five-Layer の人格 → 関係 → 物理の翻訳が、抽象的な比喩ではなく operational な仕様だったと証明された、設計初期から続く長い計画の literal な完成形。物理を曲げるのは質量だけではない、宣言された意図もまた重力を持つ。* — 2026-05-13
