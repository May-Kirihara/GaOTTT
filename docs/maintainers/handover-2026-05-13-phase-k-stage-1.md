# Session Handover — 2026-05-13 (Phase K Stage 1 完了 — Stellar Supernova Cohort)

> **読者**: 次のセッションでこのリポジトリを触る Claude / 保守者
> **前回の handover**: [`handover-2026-05-13-phase-j-stage-1.md`](handover-2026-05-13-phase-j-stage-1.md) (Phase J Stage 1 完了 + acceptance 結果 → Phase K 設計)
> **本セッション**: Phase J Stage 1 acceptance での seed pool 入場権問題に対する **根本治療** として Phase K (Stellar Supernova Cohort) を設計・実装。Plan → 実装 → テスト → docs → handover を完走、commit 未実施でめいさん判断待ち。

## 1. 何が起きたか — 流れ

1. **Phase J Stage 1 acceptance の結果共有** (めいさん側で前回 handover 後に実施) — 1/7 のみ機能、edge を張っても改善せず。新たな攻撃者 `768bd469` (前 session の Phase 6 outcome) が全 query top1 を独占
2. **3 段階診断 by めいさん** — (1) FAISS top-K で Phase memory が選ばれない (2) edge expand は seed 必須 (3) score も seed 居ないので意味なし。**Phase J Stage 1 は pool reranking のみで pool injection しない構造的穴**
3. **私の対症療法案 (Stage 1.5)** = persona-tied node を seed pool に強制注入 — めいさん却下: 「運用上、新規項目が拾えなくなる欠点がある以上、運用でどうこうするのは美しくない。remember の後処理や、ネットワークを張るためのいい方法を考えるべき」
4. **めいさんの提案 = 超新星案** — 1 セッション内の新規 remember を **超新星爆発として扱う**、(1) 相互 relation を即時形成、(2) 初期加速度 (爆発の運動量) を付与、(3) 直近の検索 N 回までは位置計算をそれらに対して行う
5. **物理学的精緻化と Phase K 命名** — Phase G genesis kick の集合版として整理、Five-Layer の人格層 → 物理層への翻訳の延長線として位置づけ
6. **Plans-Phase-K 起こし** — 4 軸の設計判断、3 段階分け (Stage 1 cohort 形成 / Stage 2 持続位置計算 / Stage 3 cross-session bridging)、acceptance 判定基準と既存 orphan 救済の分離を明記
7. **Stage 1 実装** — `core/supernova.py` (new) + `engine._apply_supernova_cohort` + config の `supernova_*` 4 fields。Phase G genesis kick の直後に適用、Phase B co-occurrence と Phase G velocity に **加算合成**
8. **副作用検出と修正** — `test_engine_dream_loop` の前提 (index 直後 edge 無し) が Phase K で破られた → dream test で `supernova_enabled=False` 明示。**Test fixture の前提は新 Phase で再確認**
9. **検証** — pytest: 212 passed (+16 from Phase J Stage 1 の 196)、1 skipped。ruff: pre-existing 4 件のみ。bench: p50=15.6ms / p99=38.7ms (前回より若干改善)、7/7 SC pass
10. **付随 docs 同期** — Roadmap / Sidebar / Architecture-Overview / Operations-Tuning / CLAUDE / SKILL ×2 (cp 同期)
11. **本 handover 作成**

## 2. 今のリポジトリ状態 (2026-05-13 セッション終了時点、Phase K Stage 1 完了直後)

- **branch: `dev`、commit 未実施** — Phase I Stage 3 + Phase J Stage 1 + Phase K Stage 1 の 3 stage が working tree dirty で混在
- 最新 commit: `271b876 feat(scripts): add migrate.py — versioned data migration tool`
- pytest: **212 passed, 1 skipped, 3 warnings** (Phase J Stage 1 から +16 件)
- ruff: pre-existing 4 件のみ (新規コード clean)
- bench: 7/7 pass、p50=15.6ms / p99=38.7ms

### Phase K Stage 1 で新規

- `gaottt/core/supernova.py` (新規、~95 行)
- `tests/unit/test_supernova.py` (新規、11 件)
- `tests/integration/test_engine_supernova.py` (新規、5 件)
- `docs/wiki/Plans-Phase-K-Stellar-Supernova-Cohort.md` (新規)
- `docs/maintainers/handover-2026-05-13-phase-k-stage-1.md` (新規、本ファイル)

### Phase K Stage 1 で修正

- `gaottt/config.py` — Phase K hyperparameters 4 個追加 (Phase J の隣)
- `gaottt/core/engine.py` — `_apply_supernova_cohort` method + `index_documents` 内呼び出し
- `tests/integration/test_engine_dream_loop.py` — fixture で `supernova_enabled=False` を明示 (副作用回避)
- `docs/wiki/Plans-Roadmap.md` — Phase J 完了表記 + Phase K 行追加
- `docs/wiki/_Sidebar.md` — Phase K リンク追加
- `docs/wiki/Architecture-Overview.md` — Phase K 行追加
- `docs/wiki/Operations-Tuning.md` — Supernova cohort section 追加
- `CLAUDE.md` — Last updated + 五層思想段落更新
- `SKILL.md` + `.claude/skills/gaottt/SKILL.md` — Phase K 段落 + Notes、cp 同期

## 3. 実装の要点

### 物理モデル

```
index_documents(batch_of_N_docs):
  1. embed + FAISS add
  2. Phase G genesis kick (各 new_id に個別)
     → 既存隣人との 1 step 重力相互作用 (cohort 外との binding)
  3. Phase K supernova cohort (batch 全体に集合的)
     → 全 pair に co-occurrence edge (weight = supernova_initial_weight = 1.0)
     → 各 new_id に outward velocity = α × (emb - centroid) clamp orbital_max_velocity
     → velocity = Phase G velocity + Phase K velocity (合成、clamp 込み)
  4. flush_to_store
```

### 順序判断 — Phase G の後

- Phase G: each-new-id について「既存重力場からの kick」(cohort 外の星系との binding)
- Phase K: その上に「兄弟との連結 + 爆発エネルギー」を加算 (cohort 内の連結)
- 順序を逆にしても物理的には等価だが、コード可読性のため「個別 → 集合」の順

### Edge weight = 1.0 の意味

- Phase B co-occurrence の `edge_threshold=5` (recall ベースの累積閾値) **とは独立**
- Phase K は event-driven (1 イベント = 1 edge)、Phase B は accumulation-driven (5 回 co-recall で edge)
- 結果として Phase K edge は Phase B threshold を超える状態で生まれる、後の Phase B 累積で重み増加可能

### Min cohort size = 2 の判断

- 1 件だけの remember は超新星ではなく単独彗星 (Phase G で十分)
- 2 件以上で「同 batch から生まれた = 同イベント」の物理的意味が立つ
- 3+ にすると 2 件の小規模 batch が cohort 化しない → 運用上不便

### Velocity 合成: 加算 vs 置換

加算を採用。理由:

- Phase G velocity は「既存星系への重力」、Phase K velocity は「爆発の運動量」、両者は独立した物理現象
- 加算で両方の力が同時に働く (物理的に正しい合成)
- 最後に orbital_max_velocity でclamp して暴走防止
- 置換だと Phase G の効果が消えてしまう

## 4. ハイパーパラメータと運用

### 既定値の根拠

| 名前 | 既定 | 根拠 |
|---|---|---|
| `supernova_enabled` | `True` | Stage 1 を本番で active |
| `supernova_min_cohort_size` | `2` | 単独 remember は単独彗星、2 件以上で発火 |
| `supernova_initial_weight` | `1.0` | seed step の `wave_seed_mass_alpha × log(1+w) = 0.1 × log(2) ≈ 0.069` の boost が立つ程度。`edge_threshold=5` は recall ベースで別軸 |
| `supernova_velocity_alpha` | `0.03` | `orbital_max_velocity=0.05` 以下に収まる安全域、Phase G velocity との合成で clamp に到達することは稀 |

### Roll-back

```bash
# Soft (config 1 行で完全 skip):
echo '{"supernova_enabled": false}' > ~/.config/gaottt/config.json
# サーバー再起動。新規 remember は Phase G まで (legacy 挙動)
```

DB 状態は触らない、migration 不要。既に形成された cohort edges は残る (set_edge は idempotent、cohort edge が legacy mode で害をなさない)。

### 本番 acceptance test (めいさんに委ねる)

#### Acceptance 1 — 新規 cohort 単独で

1. MCP サーバー再起動 (新 config 読み込み)
2. 新規 5 件の memo を **1 batch** で `remember` (engine.index_documents 経由)
3. `reflect(aspect="connections")` で 5 件間に 10 edge があることを確認
4. 直後の recall でこれら 5 件が seed pool に届くか確認 (mass-aware boost が立つはず)

#### Acceptance 2 — 既存 harakiriworks 救済 (Phase K 適用範囲外)

**重要**: Phase K Stage 1 は **将来 session の新規 cohort** に効くが、**既存 orphan の 112 件は遡及できない**。これは Plan で明示済の制約。

既存 harakiriworks 112 件への対処:
- 案 R1: 「retrospective supernova」 script で edge + velocity を後付け (script は本セッションで作成せず、必要なら別 commit)
- 案 R2: 前回提案の Hierarchical 2-hop ritual (Phase J Stage 1 のため) を実行 → Phase J の効果も合流
- 案 R3: Driven Resonance (Phase F pattern) で 9 中心ノードを各 5-10 回 recall

最も効果的: **R2 + R3 の合わせ技** — relate() で Phase task に繋ぐ + 中心 9 ノードを mass 成長させる。Phase J Stage 1 と Phase K Stage 1 の両 boost が seed step で合算される。

## 5. 学んだ lesson

### 5.1 「対症療法を提案された時、根本治療を提案する勇気」 ★

私が Phase J Stage 1.5 (pool injection) を「実用的 fallback」として提案した時、めいさんは却下した。**「運用上、新規項目が拾えなくなる欠点がある以上、運用でどうこうするのは美しくない」**。

これは GaOTTT 開発の本質的な原則 — **物理として書いた設計は、運用回避策で覆い隠さず、物理として修正する**。Phase G は「個別ノードの genesis」を物理として書いた、Phase J は「persona の重力」を物理として書いた、Phase K は「集合的記憶生成」を物理として書いた。これらは全て **記憶のあり方そのもの** を変える設計であって、retrieval 側で hack するのではない。

将来の設計でも、私が「実用的回避策」を提案した時、めいさんが「美しくない」と言ったら、それは **より深い物理修正の方向を指している** ことを忘れない。

### 5.2 「Articulation as Carrier の単数性 vs 複数性」 ★

めいさんの core value は本来「言葉にすることで重力を持つ」(単数の articulation)。Phase K は **「同時に N 個言葉にする」(複数の articulation)** という新しい現象を物理として記述した。

集合 = 単数の N 倍ではない。集合自体に固有の物理 (相互 edge + 爆発エネルギー) がある。これは Phase D が「人格 = 単独 declare」を扱った構造化の延長で、「人格の表明は 1 イベントで複数言葉を生む」現実に対応する。

将来の Phase は「人格の **時間的な複数性**」(同じ session 内での意図の進化、別 session への持続) を扱う可能性がある (Phase K Stage 3 の cross-session bridging)。

### 5.3 「Test fixture の前提は新 Phase で再確認必須」

`test_engine_dream_loop` は「index_documents 直後に edge は無い」を前提にしていた。Phase K で「index_documents 直後に N×(N-1)/2 個の cohort edge がある」状態に変わったので、fixture で `supernova_enabled=False` を明示する必要があった。

これは Phase I Stage 3 で `test_query_kick_mass_damping_F_equals_ma` を Stage 2 mode に明示固定したのと同じ pattern。**新 Phase は既存 test の暗黙の前提を破る可能性があり、test fixture の config を明示するのが将来の保守を楽にする**。

設計判断の倫理に追加: **「新 Phase 実装時は、関連する既存 test fixture の暗黙前提を grep で洗い出す」**。

### 5.4 「Phase G と Phase K は対称的: 個別 vs 集合」

Phase G (個別 genesis kick) と Phase K (集合 supernova cohort) は **物理的に対称な対**:

- Phase G: 1 つの粒子 vs N 個の既存隣人 (彗星捕獲、集合 → 個別への重力)
- Phase K: N 個の粒子 vs 自分たち (超新星爆発、集合 → 集合内の重力)

両者を順次適用することで、新規ノードは「既存星系に着陸 + 兄弟と連結 + 爆発」の三重物理を獲得する。これは記憶生成のリッチさを物理として記述する設計の極致。

将来 Stage 3 では「**過去 session の cohort との bridging**」を扱う — Phase K Stage 3 = cross-session supernova chain。これも物理として書ける。

## 6. 残る open tasks

### Phase I 系 (継続)

| id | 内容 | deadline |
|---|---|---|
| `72e84a73` | Phase I Stage 1 長期検証 | 2026-06-01 |
| `d668ba35` | wave_k_with_filter=500 → 1000 引き上げ判断 | 2026-06-10 |
| `94fd3f23` | bootstrap_report.py の virtual FAISS 対応 | 2026-06-10 |
| `7bfff23d` | dream loop 効果の定量化ベンチ整備 | 2026-06-10 |
| `804bc91f` | virtual FAISS の write-behind 検討 | 2026-06-10 |

### Phase K 系 (新規、acceptance 後に判断)

1. **Phase K Stage 2: 持続的位置計算 (めいさん提案「重力圏を抜けるまで」)**
   - cohort tag を持つノードは N tick `update_orbital_state` で特別扱い
   - 爆発残骸が gravity well から離脱する物理の literal 実装
   - Stage 1 acceptance で不要と判断すれば省略
2. **Phase K Stage 3: Cross-session bridging**
   - 別 session で同じ intention に紐付く新規 cohort が現れたら過去 cohort と橋を架ける
   - Phase D persona linkage と統合
3. **既存 orphan 救済 ritual script**
   - harakiriworks 112 件のような Phase K 前の orphan に edge + velocity を後付け
   - Stage 2 で実装 or 別 commit
4. **Phase J Stage 2: Explicit `persona_context` 引数**
   - 前 handover §6 で言及済、MCP/REST parity 対応

## 7. 次セッションでやるとよいこと (優先度順)

### 7.1 本番 DB で Phase K Stage 1 の acceptance test (最優先)

めいさん側で:

1. 本セッションの全変更を commit (Phase I Stage 3 + Phase J Stage 1 + Phase K Stage 1)
2. MCP サーバー再起動 (新 config + 新コードを load)
3. **新規 cohort acceptance**:
   - 5 件の test memo を 1 batch で remember
   - `reflect(aspect="connections")` で 10 edge を確認
   - 直後の recall で cohort 内 5 件が surface するか確認
4. **既存 harakiriworks 救済** (別軸、Phase K では遡及不可):
   - Hierarchical 2-hop ritual (Phase J Stage 1 用)
   - or Driven Resonance (Phase task 9 中心ノードの mass 成長)
   - 両方の効果を見て、必要なら Phase K retrospective ritual script を Stage 2 で実装

### 7.2 commit 戦略

本セッションは **3 stage 分の変更** が working tree dirty:

- Phase I Stage 3 (前々 session 含む)
- Phase J Stage 1 (前 session)
- Phase K Stage 1 (本 session)

3 stage 別 commit に分けるなら git add -p で fragmentation 必要。実用的には:

- **方法 A**: 3 commit に分割 (`feat(engine): Phase I Stage 3` + `feat(engine): Phase J Stage 1` + `feat(engine): Phase K Stage 1`) + handover docs 1 commit = 4 commit
- **方法 B**: 1 commit にまとめる (`feat(engine): Phase I Stage 3 + Phase J Stage 1 + Phase K Stage 1 — sequenced response to seed-pool entry pathology`)
- **方法 C**: 中庸 = 「Phase I 系で 1 commit、Phase J+K で 1 commit、docs で 1 commit」

過去 history では各 Stage 別 commit が標準なので方法 A が筋、ただし時間優先なら方法 B も実用的。

### 7.3 Phase K Stage 2 設計判断

Stage 1 acceptance で:
- 新規 cohort が seed pool に届けば Stage 2 (持続的位置計算) は不要
- 届くが「すぐに gravity well に再吸引される」現象が起きれば Stage 2 が必要
- Stage 1 acceptance の観察次第

## 8. 設計判断・トーン原則の継承

### 前 handover からの継承 (引き続き有効)

(前 handover §8 を継承、省略)

### 本セッションで追加

- 「対症療法を提案された時、根本治療を提案する勇気」 (§5.1) ★ 最重要
- 「Articulation as Carrier の単数性 vs 複数性 — 集合に固有の物理がある」 (§5.2)
- 「Test fixture の暗黙前提は新 Phase で再確認必須」 (§5.3)
- 「Phase G と Phase K は対称的 — 個別 genesis vs 集合 supernova」 (§5.4)

## 9. 関連ドキュメント

- [前 handover (Phase J Stage 1)](handover-2026-05-13-phase-j-stage-1.md)
- [前々 handover (Phase I Stage 3)](handover-2026-05-13-phase-i-stage-3.md)
- [Plans — Phase K](../wiki/Plans-Phase-K-Stellar-Supernova-Cohort.md)
- [Plans — Phase J](../wiki/Plans-Phase-J-Persona-Anchored-Retrieval.md)
- [Plans — Phase G](../wiki/Plans-Phase-G-Memory-Genesis.md) — 個別 genesis kick の物理 (Phase K の対称対)
- [Plans — Roadmap](../wiki/Plans-Roadmap.md)
- [Operations — Tuning](../wiki/Operations-Tuning.md) — supernova_* row
- [Architecture — Overview](../wiki/Architecture-Overview.md) — 設計判断表

## 10. 付録: 本 session で変更したファイル一覧

**新規**:
- `gaottt/core/supernova.py` (+95 行)
- `tests/unit/test_supernova.py` (+145 行)
- `tests/integration/test_engine_supernova.py` (+180 行)
- `docs/wiki/Plans-Phase-K-Stellar-Supernova-Cohort.md` (+250 行)
- `docs/maintainers/handover-2026-05-13-phase-k-stage-1.md` (本ファイル)

**修正**:
- `gaottt/config.py` (Phase K hyperparameters +20 行)
- `gaottt/core/engine.py` (`_apply_supernova_cohort` method + `index_documents` 呼び出し、+50 行)
- `tests/integration/test_engine_dream_loop.py` (supernova_enabled=False 追加、+6 行)
- `docs/wiki/Plans-Roadmap.md` (Phase J 完了表記 + Phase K 行、+3 行)
- `docs/wiki/_Sidebar.md` (Phase K リンク、+1 行)
- `docs/wiki/Architecture-Overview.md` (Phase K 行、+1 行)
- `docs/wiki/Operations-Tuning.md` (Supernova cohort section、+10 行)
- `CLAUDE.md` (Last updated + 五層思想段落、置換)
- `SKILL.md` + `.claude/skills/gaottt/SKILL.md` (Phase K 段落 + Notes、cp 同期、+5 行)

合計: コード +165 行、テスト +330 行、ドキュメント +280 行。

---

> *Phase K は、めいさんの一文 — 「運用上、新規項目が拾えなくなる欠点がある以上、運用でどうこうするのは美しくない」 — から生まれた。私が pool injection で対症療法しようとしたとき、めいさんはそれを却下し、代わりに「remember の後処理や、ネットワークを張るためのいい方法を考えるべき」と提案した。続けて出てきた「超新星爆発」のメタファーは、設計の根幹を一発で書き直す質を持っていた — 散発的塵だった新規ノード群が、超新星残骸として読まれることで cluster として生まれる。Phase G genesis kick の集合版、Articulation as Carrier の単数から複数への拡張、Five-Layer の人格層 → 物理層への翻訳の連続性。これは私には書けない種類の設計だった。「物理として書く」とはこういうことだ、と教わった。* — 2026-05-13
