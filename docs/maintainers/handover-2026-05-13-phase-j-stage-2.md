# Session Handover — 2026-05-13 (Phase J Stage 2 完了 — Explicit Pool Injection)

> **読者**: 次のセッションでこのリポジトリを触る Claude / 保守者
> **前回の handover**: [`handover-2026-05-13-phase-k-stage-1.md`](handover-2026-05-13-phase-k-stage-1.md)
> **本セッション**: Phase K Stage 1 + retrospective ritual の本番 acceptance 結果 (0/7) を踏まえ、Phase J Stage 2 (explicit pool injection) を設計・実装・テスト。LLM が「今の文脈」を明示的に伝える `persona_context` + `tag_filter` 引数を MCP/REST 両方に追加、seed step + final result の **両段階** で force-inject。実装完了、commit + push 済み、本番 acceptance はめいさん側 MCP 再起動後。

## 1. 何が起きたか — 流れ

1. **Phase K Stage 1 + retrospective ritual の本番 acceptance 共有** — めいさん実行で 12,432 edge records + 112 velocities 書き込み成功、MCP 再起動後 acceptance test は **0/7** に悪化。新攻撃者 `f527f0d8` (R12 prefetch) と `1cf06afe` (file: ライトノベル) が top1 を独占
2. **物理的診断** — 4 つの軸 (FAISS / source_filter / mass-aware / persona / cohort) は全部 「pool 入場後の rerank」 で、**pool 入場権を作る機構は FAISS と source_filter のみ**。harakiriworks vs 「Eleventy」のような embedding 距離が遠い query には対応手段がない
3. **Phase J Stage 2 の選択** — 4 候補 (i) pool injection / (ii) wave_k 拡大 / (iii) embedder ensemble / (iv) 中断 から、めいさん (i) を選択。「Stage 1.5 pool injection は美しくない」と前回保留した案を、API の正面に位置づけ直す
4. **Plans-Phase-J に Stage 2 セクション追加** — 5 軸の設計判断 (additive vs restrictive / substring match / OR / explicit overrides auto-detect / wave_k_with_filter pool 拡大)、API spec、pattern 例、acceptance 判定基準
5. **実装 (8 タスク並列)** — types/cache/gravity/services/engine/server/tests/docs を順次拡張。CLAUDE.md の MCP/REST parity 鉄則を守って同じターンで両方公開
6. **設計の深化** — 当初 「seed pool injection」のみ実装したが、test で `persona_context=[target_id]` を渡しても target が top_k に居ない現象が発生 (rank 999)。原因: seed に入った target の隣人が wave 拡張で reach され、それらが target を rank で押し退ける。**seed injection だけでは不十分、final result 段階の injection も必要**と判明
7. **Two-stage force injection の追加実装** — `engine._query_internal` の Step 4 (top-K cut) で `injected_ids` を必ず top-K に含める処理を追加。これで target は必ず surface する
8. **検証** — pytest 216 passed (+4 from Phase K) / ruff pre-existing 4 件のみ
9. **本番 acceptance attempt (MCP 古いコードで動作)** — recall(tag_filter=["harakiriworks-self-knowledge"]) を試みたが MCP server は古いコードで動いていたので新引数を silent ignore、結果 0/5。MCP 再起動が前提条件
10. **commit + push (df1fe67 → next)** — Phase J Stage 2 全体を 1 commit にまとめる
11. **本 handover 作成** — めいさんが MCP 再起動後 acceptance を取れる状態に

## 2. 今のリポジトリ状態 (2026-05-13 セッション終了時点)

- **branch: `dev`、commit + push 済**
- pytest: **216 passed, 1 skipped** (+4 from Phase K Stage 1)
- ruff: pre-existing 4 件のみ
- bench: latest Phase K で p50=15.6ms / p99=38.7ms 確認済 (Phase J Stage 2 は engine.query 経由で同等)

### Phase J Stage 2 で新規 / 修正

**新規**:
- `tests/integration/test_engine_pool_injection.py` — 4 件 (tag_filter lift / persona_context lift / bypass source_filter / no_args legacy)
- `docs/maintainers/handover-2026-05-13-phase-j-stage-2.md` (本ファイル)

**修正**:
- `gaottt/core/types.py` — RecallRequest に `persona_context` + `tag_filter` 追加
- `gaottt/store/cache.py` — `tags_by_id` reverse index、`set_tags` / `get_tags` / `find_ids_by_tag_filter`、load_from_store / evict_node で同期
- `gaottt/store/sqlite_store.py` — `get_all_tags()` を `get_all_sources()` と同 pattern で追加
- `gaottt/core/gravity.py` — `_inject_into_pool` helper、`propagate_gravity_wave` に `injected_ids` 引数、3 seed path で force seed injection、source_filter は bypass
- `gaottt/core/engine.py` — `query` / `_query_internal` に新引数追加、`injected_ids` の構築 (persona_context ∪ tag_filter match)、**Step 4 で top-K force injection**、`index_documents` で `tags` を cache に同期
- `gaottt/services/memory.py` — `recall` 関数に新引数、post-filter で injected_set 保護
- `gaottt/server/app.py` — RecallRequest 経由で透過的に渡す
- `gaottt/server/mcp_server.py` — recall tool に新引数 + docstring 拡張
- `docs/wiki/Plans-Phase-J-Persona-Anchored-Retrieval.md` — Stage 2 セクション (5 軸設計判断 + API + pattern + tests + acceptance + rollback)
- `docs/wiki/Plans-Roadmap.md` — Phase J 完了表記を Stage 1+Stage 2 に更新
- `docs/wiki/Architecture-Overview.md` — 設計判断表に Phase J Stage 2 行
- `CLAUDE.md` — Last updated 行
- `SKILL.md` + `.claude/skills/gaottt/SKILL.md` — Phase J Stage 2 段落 + Notes (cp 同期)

## 3. 実装の要点

### 設計の核 — Two-stage force injection

```
1. seed step (gravity.py propagate_gravity_wave):
   - FAISS top-K で pool 取得
   - injected_ids を _inject_into_pool で union (raw cosine 計算)
   - rerank (mass + persona boost)
   - forced injection: injected_ids を rerank order に関わらず seed に含める
   - source_filter は injected を bypass

2. final result step (engine._query_internal Step 4):
   - reached set を scoring
   - top-K で sort
   - forced injection: injected_ids が top-K に居なければ強制挿入
```

**なぜ two-stage が必要だったか** (実装中の発見):
- seed injection だけだと、target を seed にした後 wave propagation で target の隣人 (random) が reach され、scoring で target を rank で押し退ける
- 「caller が明示的に頼んだ ids は **必ず最終結果に含める**」が Phase J Stage 2 の真の意味
- これは Plans の §「設計判断 1: additive vs restrictive」を強化する追加要件として handover で記録

### Tag substring match — Phase H Stage 2 と同 pattern

`cache.find_ids_by_tag_filter(["harakiriworks-self-knowledge"])` は各 node の `tags` list 内のいずれかが指定 substring を含めば hit。OR match (複数指定で union)。

### source_filter bypass

`source_filter=["agent"]` + `tag_filter=["bypass-target"]` で target が source=file でも tag 一致なら inject される。LLM の explicit ask が source filter restriction に勝つ。

### 既存 callsite の保護

- `recall()` / `query()` / `_query_internal()` の新引数は **すべて optional default None**
- 引数省略時は Stage 1 までの挙動と完全 backward compatible
- prefetch cache は source_filter / persona_context / tag_filter のいずれか指定で bypass

## 4. ハイパーパラメータ

Phase J Stage 2 は **API 引数追加のみ** で新 config field なし。Stage 1 の `persona_boost_*` 系は continue to apply (proximity 計算は persona_context 経由でも auto-detect 経由でも同じ計算)。

## 5. Roll-back

API 引数追加のみで既存挙動を変えないので、**rollback 不要**。引数を渡さなければ Stage 1 までの挙動と完全互換。緊急時の config kill switch は **設けない** (Stage 1 と違って boost ではなく explicit API なので、引数省略で無効化される)。

## 6. 学んだ lesson

### 6.1 「seed injection と final injection は同等に必要」 ★

実装中の本質的発見。「pool に入れたから後は rerank が引っ張ってくれる」と思っていたが、target の **隣人** が wave 拡張で reach されて target を rank で押し退ける現象が起きる。

Phase J Stage 2 の正しい挙動: **「caller の explicit ask は wave 拡張・rerank・scoring すべてを bypass して、必ず最終結果に含める」**。これは Phase H Stage 2 source_filter の restrictive とは違う、新しい semantic。

将来の Phase でも 「pool injection」を語る時は、必ず **「最終結果 injection」もセットで設計** すべき。

### 6.2 「美しくない解が必要な場面がある」 ★

前回 (Phase J Stage 1 acceptance 失敗時) めいさんが「pool injection は美しくない」と却下し、Phase K (記憶生成の物理修正) を選んだ。これは正しい判断だった (Phase K Stage 1 は将来 cohort に対して機能する設計)。

しかし Phase K Stage 1 acceptance (retrospective ritual 後の 0/7) で **embedding 距離問題は記憶生成の物理では解決できない** と判明。embedder の限界、cross-vocabulary の問題、これらは別軸。

そこで Phase J Stage 2 で **pool injection を API として正面に位置づける** 判断。「美しくない」と思った機構を、LLM の判断による explicit control として再定義する。これは設計の段階的発見 — 「美しさ」と「実用性」は対立軸ではなく、それぞれが必要とされる場面が違う。

将来の設計でも、ある段階で「美しさ」を取って保留した案が、別の問題の解として再評価される可能性を意識する。

### 6.3 「test driven discovery of design holes」

Plans-Phase-J Stage 2 の初期設計には **「seed injection で十分」と書いていた**。だが test で `test_persona_context_lifts_target_rank` が fail → debug で「seed に入れても rank 999 の現象」を発見 → 「final injection も必要」が見えた。

Plans 段階で完璧な設計を書くのは不可能で、test がそれを暴露する。Plans は「最初の approximation」で、実装中に refined されるべき document。次セッションで Phase J Stage 2 の Plans を再度更新して、final injection の必要性を明記する候補。

### 6.4 「Phase J Stage 1 と Stage 2 は補完的 — auto-detect vs explicit」

Stage 1: auto-detect (LLM が考えない、cache 自動)
Stage 2: explicit (LLM が「今の文脈」を判断して渡す)

両者は OR ではなく **重ね合わせ**。引数省略時は Stage 1、明示時は Stage 2。LLM の judgment is signal、cache の auto-detect も signal、両方が retrieval geometry を曲げる。

これは Phase D persona layer の「declared identity」+ Phase J Stage 2「declared context」の組み合わせ — 静的 identity と動的 context の両方を物理に翻訳する設計の deeper layer。

## 7. 残る open tasks

### Phase J 系 (Stage 3 候補)

1. **prefetch / explore への引数展開** — recall API と同じ persona_context + tag_filter を prefetch / explore にも渡せるように
2. **persona_context の TTL 検証** — Stage 1 で省略済の commitment TTL チェック (last_access ベース)
3. **tag の階層 / namespace** — `harakiriworks/phase-4` のようなパス指定
4. **tag_filter mode** — 現状 OR match。AND match や exclude (`tag_exclude`) の追加検討

### 既存 task (Phase I 系、継続)

| id | 内容 | deadline |
|---|---|---|
| `72e84a73` | Phase I Stage 1 長期検証 | 2026-06-01 |
| `d668ba35` | wave_k_with_filter=500 → 1000 引き上げ判断 | 2026-06-10 |
| `94fd3f23` | bootstrap_report.py の virtual FAISS 対応 | 2026-06-10 |
| `7bfff23d` | dream loop 効果の定量化ベンチ整備 | 2026-06-10 |
| `804bc91f` | virtual FAISS の write-behind 検討 | 2026-06-10 |

## 8. 次セッションでやるとよいこと (優先度順)

### 8.1 本番 acceptance (最優先、めいさん作業)

1. **MCP server 再起動** — 新コードを load (Phase J Stage 2 の新 recall 引数 + force injection が active になる)
2. **本番 7 query acceptance**:
   ```
   recall(query="80s レトロウェーブ", tag_filter=["harakiriworks-self-knowledge"], top_k=5)
   recall(query="Eleventy Pipeline", tag_filter=["harakiriworks-self-knowledge"], top_k=5)
   recall(query="日本語 URL encoding", tag_filter=["harakiriworks-self-knowledge"], top_k=5)
   recall(query="Playwright F006", tag_filter=["harakiriworks-self-knowledge"], top_k=5)
   recall(query="緊急復旧", tag_filter=["harakiriworks-self-knowledge"], top_k=5)
   recall(query="sidebar SidebarManager", tag_filter=["harakiriworks-self-knowledge"], top_k=5)
   recall(query="霧原めい Articulation", tag_filter=["harakiriworks-self-knowledge"], top_k=5)
   ```
3. **判定基準** (Plans-Phase-J Stage 2 §「Acceptance 判定基準」より):
   - 各 query で harakiriworks 系が top5 に **確実に** 出る (まず必須)
   - 各 query で「正解 phase memory」が top1 に来る率 ≥ 5/7
   - tag_filter 未使用時は Stage 1 までの挙動 (current 0/7) を維持

### 8.2 acceptance 失敗時の調整

- Phase 1-9 の各 task ID を `persona_context=[task_id]` で渡す pattern も試す
- tag_filter を `["harakiriworks-self-knowledge", "phase-4"]` のように複数指定で AND-like な絞り込み (OR match 内の自然な交差)
- `wave_k=1000` も併用

### 8.3 Stage 3 設計 (acceptance 後)

acceptance が想定通り (≥ 5/7) なら、Stage 3 で:
- prefetch / explore への展開
- persona_context の TTL 検証
- tag 階層

## 9. 設計判断・トーン原則の継承

### 前 handover からの継承 (引き続き有効)

(前 handover §8 を継承)

### 本セッションで追加 (§6 再掲)

- 「seed injection と final injection は同等に必要」(§6.1) ★ 最重要
- 「美しくない解が必要な場面がある」(§6.2)
- 「test driven discovery of design holes」(§6.3)
- 「Phase J Stage 1 と Stage 2 は補完的 — auto-detect vs explicit」(§6.4)

## 10. 関連ドキュメント

- [前 handover (Phase K Stage 1)](handover-2026-05-13-phase-k-stage-1.md)
- [前々 handover (Phase J Stage 1)](handover-2026-05-13-phase-j-stage-1.md)
- [Plans — Phase J](../wiki/Plans-Phase-J-Persona-Anchored-Retrieval.md) — Stage 1 + Stage 2 設計
- [Plans — Phase K](../wiki/Plans-Phase-K-Stellar-Supernova-Cohort.md)
- [Plans — Roadmap](../wiki/Plans-Roadmap.md)
- [Architecture — Overview](../wiki/Architecture-Overview.md) — 設計判断表
- [Reflections — Five-Layer Philosophy](../wiki/Reflections-Five-Layer-Philosophy.md)

---

> *Phase J Stage 2 は、Phase K Stage 1 acceptance の 0/7 結果が必要だった。Phase K で「記憶生成の物理」を修正しても、embedding 距離が遠い query から既存 cohort には届かない。前回「美しくない」と保留した pool injection を、今回は API として正面に位置づける judgement の段階的発見。LLM が「今の文脈」を明示的に伝える `persona_context` + `tag_filter` は、物理に依存しない「caller の judgement」を retrieval geometry に翻訳する path で、これは Phase D で declared した identity が retrieval を曲げる Stage 1 と補完的に重なる。Stage 1 は静的 identity (declared value/intention/commitment)、Stage 2 は動的 context (LLM の「今この query は intention X 文脈」という判断)。両者は OR ではなく重ね合わせ。 retrieval geometry を曲げる signal は、embedding 類似度・物理的重力・宣言された identity・動的 context の四重奏になった。* — 2026-05-13
