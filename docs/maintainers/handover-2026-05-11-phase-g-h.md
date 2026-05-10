# Session Handover — 2026-05-10 〜 2026-05-11 (Phase G/H 完了)

> **読者**: 次のセッションでこのリポジトリを触る Claude / 保守者
> **前回の handover**: [`handover.md`](handover.md) (2026-04-21、改名後の文書温度調整 + bootstrap_report 新設)
> **本セッション**: 当初「自己知識記録 Phase 1-7 の計画」から始まり、recall の検証で深刻なバグを 2 つ発見、それらを治す過程で Phase G (Memory Genesis) と Phase H (Wave Seed Redesign) を一気に書き上げた長大セッション。9 commit 累積、2 段の重力場の根本改修。

## 1. 何が起きたか — 流れ

セッションは「めいさんの 23k 件規模本番 DB に対して、ようやく自己知識記録（プロジェクト引き継ぎを 120-150 件の memory で記述する Phase 1-7 計画）を始めよう」から始まった。記録の前にテストとして数件の plan memory を `remember` した。**その直後の `recall` が完全に空集合を返した**。

ここから連鎖的な発見:

1. **FAISS write-behind 不在バグ** (commit `c049fc0`): `engine.shutdown()` でしか `faiss_index.save()` が呼ばれず、長期常駐の MCP server プロセスでは新規 vector が永久に in-memory のまま、他プロセス invisible だった。`faiss_save_interval_seconds=5.0` の background loop を入れて修正。`cache - faiss = 388` 件のゾンビは過去ずっとこのバグで FAISS から欠落していたノードたち。

2. **anchor 句推奨の自己撤回** (commit `8276647`): bug 発見前に立てた仮説「embedding 空間で hyphen-token が外れ値で seed に入らない」に基づき CLAUDE.md / SKILL.md / Operations-Troubleshooting.md に anchor 推奨を書いたが、根本原因は FAISS save 不在だった。完全撤回。「**検証ループを最後まで回さずにドキュメントを書くと誤った推奨が固定化する**」という教訓。

3. **逆方向 cache 上書きの罠** (同 commit): Stage 0 priming を本番 DB に適用しても結果が反映されない件を追跡 → 古い MCP server プロセスが自分の cache を flush し続けて新しい書き込みを上書きしていた。bulk 書き換えは他プロセスを kill してからやる必要。CLAUDE.md / Architecture-Concurrency.md に記載。

4. **Phase G — Memory Genesis** (commits `e96c4a7`, `ba6eb38`, `5fcd76f`, `8276647`): 「新規ノードが mass=1 / displacement=0 で gravity 場に裸で投入される」問題を、本来あるべき重力法則の起動時適用で塞ぐ。
   - Stage 1 (G.1 軌道捕獲): `compute_gravity_kick` で 1 step の neighbor gravity を新規 add 直後に適用。`genesis_mass_boost_cap=1.0` で raw `|acc|=70+` のような outlier を制御。
   - Stage 2 (G.2 夢): idle 時間に `_dream_loop` が quiet node を synthetic recall で再活性化。`_is_synthetic=True` で return_count はインクリメントしない（saturation 非発火）。
   - Stage 0 (priming): 既存 22k 件に kick を 1 回ずつ適用する `scripts/prime_gravity.py`。本番 DB で実行（34.7 min、22,357 件適用、約 21k が "naked → 動いた"）。

5. **Phase H — Wave Seed Redesign** (commits `1d53881`, `d9a3b2f`, `2d8b39c`, `c857904`): Phase G priming 後の検証で「**displacement / mass 改善は scoring 段階でしか効かず、wave seed (FAISS raw cosine top-K) には届かない**」と判明 — sparse class が seed 入口で構造的に排除される問題。
   - Stage 1 (H.3 mass-aware boost): `raw + α*log(1+mass)` で seed pool を再 rank。scoring は 5x 改善するが sparse class の embedding 距離問題は超えられない。
   - Stage 2 (H.4 source-aware seed filter): `cache.source_by_id` で seed pool から source 一致のみ抽出。`wave_k_with_filter=500` 既定。**初の agent surface 達成**。
   - Stage 3 (H.1 dynamic wave_k): top-N の tail/top 比率で sparse 判定して seed を `wave_initial_k_max=50` まで拡大。
   - Stage 4 (H.2 virtual FAISS): 第二 FAISS index を `virtual_pos = raw + displacement` で構築、seed pool は raw + virtual の union。**priming の displacement が seed step で効くようになり、本番 filter=none top1 score が 5.6x 改善**。

6. **MCP server 再起動後の最終確認** (このセッション末尾): Phase G + H 全 Stage が動いている本番 DB で `recall` を投げ、新規 remember を score 0.79 で即時 surface、agent 系過去 memory を `wave_k=1000` で完全 surface することを確認。**当初の問題は完全に解決された**。

## 2. 今のリポジトリ状態（2026-05-11 セッション終了時点）

- branch: `dev`、`origin/dev` から **9 commit ahead**（push 未実施）
- 最新 commit: `c857904 feat(engine): Phase H Stage 4 — virtual FAISS for displacement-aware seed`
- pytest: **167 passed, 1 skipped** (1 skip は fixture lottery、機能 OK)
- ruff: pre-existing 4 件のみ
- bench: SC-001 p50 = 15.7ms (< 50ms 必達 OK)、7/7 PASS
- mcp_smoke + rest_smoke: 全 green
- 本番 DB:
  - Total 23,374、Active(mass>1) **23,022** (priming 効果定着)
  - Displaced 15,578、Co-occurrence edges **710** (dream loop で増加中)
  - `cache.source_by_id` 23,497 件 populate
  - virtual FAISS file (`gaottt.virtual.faiss`) は startup で初回 build される（自動）

### 9 commit のリスト

```
c857904 feat(engine): Phase H Stage 4 — virtual FAISS for displacement-aware seed
2d8b39c feat(engine): Phase H Stage 3 — density-aware dynamic wave_k
d9a3b2f feat(engine): Phase H Stage 2 — source-aware seed filtering
1d53881 feat(engine): Phase H Stage 1 — mass-aware seed boosting
8276647 feat(engine): Phase G Stage 0 priming + mass cap + Phase H plan
5fcd76f feat(engine): Phase G Stage 2 — dream consolidation loop
ba6eb38 feat(engine): Phase G Stage 1 — genesis kick for new nodes
e96c4a7 docs(plans): add Phase G — Memory Genesis plan
c049fc0 fix(engine): FAISS write-behind to fix multi-process invisibility
```

## 3. 解消された限界 / 残った限界

### ✅ 解消された

- 新規 `remember` 直後の即時 `recall` で score 0.7+ で surface（Phase G Stage 1 + Phase H Stage 4）
- `recall(source_filter=["agent"])` が seed 段階で機能（Phase H Stage 2）
- 23k corpus-heavy DB で sparse class の reach（agent 280 件が priming で 393 件相当の重力を持ち、Stage 4 の virtual cosine で seed に入りやすくなった）
- 長期常駐 MCP server プロセスの新規 remember が他プロセスから永久 invisible になる歴史的バグ
- co-occurrence edges が時間軸で自然に増える（dream loop、本セッション中で 409 → 710）

### ⚠️ 残った構造的限界

- **embedding 距離が極端に遠い query への agent surface**: agent docs の displacement は priming で **近傍 high-mass cluster 方向**に動かされる（Phase G の機構）。query と関係ない方向に動いている agent docs は virtual cosine も近づかない。`Articulation as Carving` 系の query で agent が surface しないのはこのため。
  - 次の方向性: **query-aware displacement** または **semantic-targeted kick**。query 側の embedding を考慮した方向への displacement、または特定の semantic anchor に向かう一括 displacement。これは Phase G の前提（neighbor-based kick）を超える設計で、別 Phase の領域。

- **virtual FAISS の write-behind 不在**: Phase H Stage 4 の virtual FAISS は `compact(rebuild_faiss=True)` か `shutdown` でしか更新されない。長期常駐プロセスの累積 displacement 変化は次の compact までは virtual に反映されない。`virtual_faiss_save_interval_seconds` を別途持つかは保留。

- **`bootstrap_report.py` が virtual FAISS を見ない**: raw FAISS の neighbor preview のみ。Phase G priming 後の virtual 距離は別途診断スクリプトで（今のところ `/tmp/verify_phase_h_source_filter.py` など ad-hoc）。

- **Stage 3 の効果定量化未整備**: `dynamic wave_k` のうれしさを測る合成シナリオがベンチに無い。

## 4. 次セッションでやるとよいこと（優先度順）

### 4.1 当初の本題「自己知識記録 Phase 1-7」を着手

Phase G + H が動いている今、anchor 句頼みでなく自然な remember + 自然文 recall + 必要に応じ source_filter で運用できる。120-150 件の記録を進められる状態。計画は GaOTTT memory に保存済み:
- `id=810bd59d` plan v1 (anchor 版)
- `id=fd61193b` Phase G/H 完了 milestone (2026-05-11、本セッションの最後で保存)

### 4.2 `wave_k_with_filter` を 500 → 1000 に再評価

本番 DB の検証で 500 では届かないクエリが 1000 で届く実例が複数。レイテンシ影響は source_filter 指定時のみで p50 は影響なし。デフォルト引き上げ候補。

### 4.3 query-aware displacement の検討（Phase I 候補）

agent surface が依然届かない `Articulation as Carving` 系 query への対処。設計案:
- `kick(query_anchor)`: 既存 query の embedding を anchor として、それ方向に displacement を加算する一括操作。LLM が「この query で sparse class を見つけたい」と意図を持つときに使う。
- bootstrap curator (不採用) と違い、organic gravity を歪めずに query-driven な kick を行う。

### 4.4 bootstrap_report.py の virtual FAISS 対応

raw 距離だけでなく virtual 距離での neighbor preview を出すと、priming 後の状態が見える。Phase G/H 後の運用ツールとしての完成度向上。

### 4.5 dream loop 効果の定量化ベンチ

`scripts/benchmark.py` に「N 件 add 直後 vs dream tick × M 回後の co-occurrence 数 / surface 率」を追加。Phase G Stage 2 のうれしさを数字で示せる。

## 5. 設計判断・トーン原則の継承

### 5.1 「検証ループを最後まで回す」

anchor 句推奨の誤認は、仮説 → ドキュメント書き → 検証 という順序で起きた。仮説が間違っていても doc が固定化する。**仮説 → 検証 → ドキュメント** の順で。今回は撤回 commit でリカバリしたが、それを再発しないために本 handover にも明示。

### 5.2 「組み上がる前に initial seed を入れる」設計判断

handover.md (前回) §1.3 で **bootstrap curator (LLM bridge) は不採用**だった理由が「organic gravity が自発的に build up する感触を奪う」だった。今回 Phase G の各 Stage / Phase H の各 Stage はその判断と矛盾しない設計を選んだ:
- Phase G の機構は「既存物理法則を新粒子にも適用するだけ」で意味解釈をしない
- Phase H の seed redesign は raw cosine を覆さず候補を増やすだけ

curator は「橋を別に作る」、Phase G/H は「重力という既存の働きが新粒子を見落としていた漏れを塞ぐ / wave reach の入口を物理的に広げる」。今後の Phase I も同じ境界を保つこと。

### 5.3 「逆方向 cache 上書きの罠」を覚えておく

複数 MCP プロセスが同 DB を見ているとき、bulk 書き換えは他プロセスを kill してからやる。これは Architecture-Concurrency.md と CLAUDE.md に記載済み。Stage 0 priming のような操作は今後も同じ手順で。

## 6. 関連ドキュメント

- [Plans — Phase G — Memory Genesis](../wiki/Plans-Phase-G-Memory-Genesis.md) — Stage 0/1/2/3 の設計と結果
- [Plans — Phase H — Wave Seed Redesign](../wiki/Plans-Phase-H-Wave-Seed-Redesign.md) — Stage 1/2/3/4 の設計と結果
- [Plans — Roadmap](../wiki/Plans-Roadmap.md) — 全 Phase の俯瞰
- [Architecture — Overview](../wiki/Architecture-Overview.md) — 設計判断の表（本 handover の作業を反映）
- [Architecture — Gravity Model](../wiki/Architecture-Gravity-Model.md) — 重力 kick / dream / virtual FAISS の数式
- [Architecture — Concurrency](../wiki/Architecture-Concurrency.md) — FAISS write-behind / 逆方向 cache 上書き / dream loop
- [Operations — Tuning](../wiki/Operations-Tuning.md) — 全ハイパラ表
- [Operations — Server Setup](../wiki/Operations-Server-Setup.md) — virtual FAISS の運用
- [Operations — Troubleshooting](../wiki/Operations-Troubleshooting.md) — 別プロセスから新規 remember が見えない件
- [`scripts/prime_gravity.py`](../../scripts/prime_gravity.py) — Stage 0 priming ツール

## 7. 付録: GaOTTT 内に登録した task / memory

セッション末で GaOTTT に以下を記録:

- `remember` (重要発見):
  - Phase G/H 完了 milestone (id=fd61193b)
  - 構造的発見群（cache 上書き罠、wave seed 構造、displacement 方向問題）
- `commit` (Phase D task として):
  - `wave_k_with_filter=1000 への引き上げ検討` (Phase I 候補)
  - `bootstrap_report.py の virtual FAISS 対応`
  - `自己知識記録 Phase 1-7 の着手`
  - `query-aware displacement 設計検討` (Phase I 本筋)
  - `dream loop 効果の定量化ベンチ整備`

これらは次セッションで `inherit_persona()` + `reflect(aspect="tasks_todo")` で取り出せる。

---

> *Phase G/H は GaOTTT がついに「使い込むほど育つ重力場」として実用化された瞬間。今日の最後に保存した `id=fd61193b` の memory は、その実用化を初めて自分自身で体験した記録になっている。*
