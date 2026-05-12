# Session Handover — 2026-05-13 (Phase J Stage 3 完了 — Phase J 完遂)

> **読者**: 次のセッションでこのリポジトリを触る Claude / 保守者
> **前回の handover**: [`handover-2026-05-13-phase-j-stage-2.md`](handover-2026-05-13-phase-j-stage-2.md)
> **本セッション**: Stage 2 本番 acceptance で見えた「top5 surface ✅ / top1 正解率 ⚠️」問題を Stage 3 で解決。forced 内 ordering を `raw_score` 順に変更、prefetch/explore にも persona_context+tag_filter を展開。Phase J 完遂宣言。

## 1. 何が起きたか — 流れ

1. **Stage 2 本番 acceptance 結果共有** (めいさん MCP 再起動 → 7 query 走らせ):
   - ✅ 7/7 で harakiriworks 系が top5 に surface (force injection 完璧)
   - ⚠️ 1-2/7 のみ「正解 phase memory が top1」
2. **機序診断** — forced 内 top-K cut は `final_score` 順、final_score は mass/wave/emotion/certainty 累積を強く反映 → 当日繰り返し触った memory (`6b7db3bb` F005 / `62f69bfc` eleventy.js.backup) が forced 内でも top1 を独占
3. **三段構造の発見** — retrieval geometry が独立した 3 段で動いていることが見えた:
   - 段 1: pool 入場 (FAISS / 強制注入) — Phase J Stage 2 で完成
   - 段 2: pool 内 rerank (mass / persona / cohort) — Phase H/J Stage 1/K
   - 段 3: forced 内 ordering — 未調整、Stage 3 で完成
4. **設計** — Stage 3 = (a) forced 内 sort key を `raw_score` に変更 + (b) prefetch/explore parity
5. **実装** — engine.py / types.py / services / server / tests を順次拡張、Plans-Phase-J に Stage 3 セクション追加
6. **検証** — pytest 219 passed (+3 from Stage 2) / ruff pre-existing 4 件のみ
7. **Phase J 完遂宣言** — 三段構造が完成、Plans-Phase-J §「Phase J 完遂宣言」を追加
8. **handover 作成** (本ファイル)

## 2. 今のリポジトリ状態

- **branch: `dev`、commit + push 直前** (commit + push は task #48 でこれから実施)
- pytest: **219 passed, 1 skipped** (+3 from Phase J Stage 2)
- ruff: pre-existing 4 件のみ
- bench: 同等 (Stage 3 は sort key 変更 + 引数追加のみ、latency 影響なし)

### Phase J Stage 3 で新規 / 修正

**新規**:
- `docs/maintainers/handover-2026-05-13-phase-j-stage-3.md` (本ファイル)

**修正**:
- `gaottt/core/engine.py` — Step 4 で forced sort を `raw_score` 順に + prefetch メソッドに persona_context / tag_filter
- `gaottt/core/types.py` — PrefetchRequest + ExploreRequest に persona_context + tag_filter
- `gaottt/services/memory.py` — explore に新引数を伝搬
- `gaottt/services/maintenance.py` — prefetch に新引数を伝搬
- `gaottt/server/app.py` — /prefetch + /explore endpoint で新引数を受け取り
- `gaottt/server/mcp_server.py` — prefetch + explore tool に新引数 + docstring 拡張
- `tests/integration/test_engine_pool_injection.py` — Stage 3 用 test 3 件追加 (forced ordering / explore parity / prefetch parity)
- `docs/wiki/Plans-Phase-J-Persona-Anchored-Retrieval.md` — Stage 3 セクション + Phase J 完遂宣言
- `docs/wiki/Plans-Roadmap.md` — Phase J 完遂表記
- `docs/wiki/Architecture-Overview.md` — 設計判断表に Stage 3 行
- `CLAUDE.md` — Last updated 行
- `SKILL.md` + `.claude/skills/gaottt/SKILL.md` — Phase J Stage 3 段落 + Notes (cp 同期)

## 3. 実装の核

### Step 4 の sort key 変更 (engine.py)

```python
# Stage 2 まで:
results.sort(key=lambda r: r.final_score, reverse=True)
if injected_ids:
    forced = [r for r in results if r.id in injected_ids]
    others = [r for r in results if r.id not in injected_ids]
    if len(forced) >= k:
        results = forced[:k]
    else:
        results = forced + others[: k - len(forced)]

# Stage 3:
if injected_ids:
    forced = [r for r in results if r.id in injected_ids]
    others = [r for r in results if r.id not in injected_ids]
    forced.sort(key=lambda r: r.raw_score, reverse=True)    # ← 変更点
    others.sort(key=lambda r: r.final_score, reverse=True)
    if len(forced) >= k:
        results = forced[:k]
    else:
        results = forced + others[: k - len(forced)]
else:
    results.sort(key=lambda r: r.final_score, reverse=True)
    results = results[:k]
```

非 forced は引き続き `final_score` 順 (mass / wave 累積を尊重)。forced 内は `raw_score` 順 (query semantic を尊重)。両者は混在せず独立 stage で評価。

### prefetch/explore parity

types.py の PrefetchRequest / ExploreRequest に `persona_context` / `tag_filter` を追加、services / engine / server を recall と同じ pattern で拡張。MCP/REST 同時公開。

## 4. retrieval geometry の三段構造

Phase J 完遂で見えた、本セッションの最大発見:

| 段 | 役割 | 機構 | 主入力 |
|---|---|---|---|
| 1. pool 入場 | 候補集合の確保 | Phase J Stage 2 (force inject) / FAISS top-K | embedding 距離 / 明示注入 |
| 2. pool 内 rerank | 候補同士の重み付け | Phase H Stage 1 (mass) / Phase J Stage 1 (persona graph) / Phase K (cohort) | 内部状態 (mass / displacement / proximity) |
| 3. forced 内 ordering | 強制注入された候補同士の順位 | Phase J Stage 3 (raw_score) | query semantic |

これは Reflections-Five-Layer-Philosophy で「retrieval geometry を曲げる signal」と表現したものの **具体的分解**。各段が独立した signal で動く設計が完成。

## 5. 学んだ lesson

### 5.1 「acceptance の `OK ⚠️` 分離は構造的境界を示す」 ★

Stage 2 acceptance で「top5 surface ✅ / top1 正解 ⚠️」が分離したのは、retrieval geometry の境界が表面化した瞬間。**「2 軸の判定基準が独立に動く」= 2 つの異なる機構が処理している** という構造的サイン。

将来の acceptance test 設計でも、複数の判定基準が独立か相関かを観察すると、内部の段構造が見える。

### 5.2 「forced と non-forced は別 sort key で良い」

「全体を 1 つの score で sort」ではなく「forced は raw_score / non-forced は final_score」と分けても問題ない。**caller の明示意図** と **内部の累積状態** はそもそも別 signal なので、別 ordering で扱う方が clean。

これは「signal を混ぜないことで debug 可能性を保つ」原則とも整合。

### 5.3 「Phase 完遂のタイミングは段構造で判定できる」

Phase J を「完遂」と宣言できるのは、retrieval geometry の三段構造が **独立に機能する** ことが test で確認されたから。各段の責任が明確、各段で独立 toggle / debug 可能。「core machinery 完成」=「責任分離が完成」。

### 5.4 「parity 鉄則は recall だけでなく explore/prefetch も」

CLAUDE.md の MCP/REST parity 鉄則は「機能を MCP に足すなら REST にも足す」だが、Phase J Stage 3 で **API surface 自体の parity (recall と explore/prefetch の引数集合の一致)** という副次原則が見えた。LLM 視点で「recall でできることが explore でもできる」が直観的。

## 6. 残る open tasks (Phase J 後)

Phase J 完遂後、以下は **Phase J Stage 4+** or **別 Phase L** として独立に判断可能:

1. **persona_context の TTL 検証** (commitment last_access ベース) — Stage 1 で省略済
2. **tag の階層 / namespace** (e.g., `harakiriworks/phase-4`) — タグ structuring
3. **tag_filter mode** — AND / exclude / threshold
4. **Reflect aspect "persona_field"** — graph + injection の可視化

### Phase I/G/H/K の継続 open tasks

| id | 内容 | deadline |
|---|---|---|
| `72e84a73` | Phase I Stage 1 長期検証 | 2026-06-01 |
| `d668ba35` | wave_k_with_filter=500 → 1000 引き上げ判断 | 2026-06-10 |
| `94fd3f23` | bootstrap_report.py の virtual FAISS 対応 | 2026-06-10 |
| `7bfff23d` | dream loop 効果の定量化ベンチ整備 | 2026-06-10 |
| `804bc91f` | virtual FAISS の write-behind 検討 | 2026-06-10 |

## 7. 次セッションでやるとよいこと (優先度順)

### 7.1 本番 acceptance 再走 (Stage 3 効果確認、最優先)

めいさん側で MCP 再起動 → 7 query で test:

```python
recall(query="80s レトロウェーブ", tag_filter=["harakiriworks-self-knowledge"], top_k=5)
recall(query="Eleventy Pipeline", tag_filter=["harakiriworks-self-knowledge"], top_k=5)
# ... 全 7
```

期待: Stage 2 の「top5 surface 7/7」を維持、かつ **top1 が「query semantic に最も近い harakiriworks memory」** に変わる:
- Eleventy Pipeline → Phase 5 R1 (.eleventy.js 責務) or .eleventy.js.backup
- 緊急復旧 → Phase 6 #7 緊急復旧 procedure
- sidebar SidebarManager → Phase 5 R16 (sidebar.js)
- 霧原めい → Phase 9 #4 (霧原めい関連 memory)

判定: top1 正解率 ≥ 5/7 を目標。

### 7.2 commit + push

本セッションの変更を 1 commit にまとめる:

```bash
git add -A
git commit -m "feat(engine): Phase J Stage 3 — forced ordering + prefetch/explore parity (Phase J 完遂)"
git push origin dev
```

### 7.3 Phase J 完遂後の方向検討

Phase J が完遂したので、次の Phase は何か:
- **Phase L**: 上記 Stage 4+ 候補 (TTL / 階層 / mode)
- **Phase M**: 別軸 (例: query 自体の拡張、embedder ensemble、retrieval-augmented prompt 構造)
- **Phase D 系の継続**: persona declared / inheritance UX の改善

これらは Phase J が落ち着いてからめいさんと相談。

## 8. 設計判断・トーン原則の継承

### 前 handover からの継承 (継続有効)

(全継承、省略)

### 本セッションで追加

- 「acceptance の `OK ⚠️` 分離は構造的境界を示す」(§5.1) ★
- 「forced と non-forced は別 sort key で良い」(§5.2)
- 「Phase 完遂のタイミングは段構造で判定できる」(§5.3)
- 「parity 鉄則は recall だけでなく explore/prefetch も」(§5.4)

## 9. 関連ドキュメント

- [前 handover (Phase J Stage 2)](handover-2026-05-13-phase-j-stage-2.md)
- [Plans — Phase J](../wiki/Plans-Phase-J-Persona-Anchored-Retrieval.md) — 完遂版 (Stage 1-3 + 完遂宣言)
- [Plans — Roadmap](../wiki/Plans-Roadmap.md)
- [Architecture — Overview](../wiki/Architecture-Overview.md) — 設計判断表に三段構造の各 Phase
- [Reflections — Five-Layer Philosophy](../wiki/Reflections-Five-Layer-Philosophy.md)

## 10. 付録: 本 session で変更したファイル

**コード** (+45 行):
- `gaottt/core/engine.py` (+10 行) — Step 4 sort key + prefetch 引数
- `gaottt/core/types.py` (+6 行) — PrefetchRequest / ExploreRequest 引数
- `gaottt/services/memory.py` (+4 行) — explore に新引数
- `gaottt/services/maintenance.py` (+5 行) — prefetch に新引数
- `gaottt/server/app.py` (+4 行) — /prefetch + /explore endpoint
- `gaottt/server/mcp_server.py` (+16 行) — tool 引数 + docstring 拡張

**テスト** (+~130 行): `tests/integration/test_engine_pool_injection.py` に Stage 3 用 3 件

**ドキュメント** (+~160 行): Plans-Phase-J Stage 3 セクション + 完遂宣言、Roadmap、Architecture、CLAUDE、SKILL ×2、本 handover

---

> *Phase J は、Phase I Stage 3 の acceptance 失敗 (0/7 → 1/7) で「declared identity が retrieval に翻訳されていない」と気付いた時に始まり、Phase K Stage 1 の acceptance (0/7) で「pool injection は美しくない代わりが必要」と気付いた時に Stage 2 で正面に位置づけ、Stage 2 acceptance (top5 ✅ / top1 ⚠️) で「forced 内 ordering という第三の段がある」と気付いた時に Stage 3 で完成した。最初の設計時に三段構造は見えていなかった。各 acceptance での失敗が、構造の境界を一つずつ表面化させた。「acceptance test は設計の正しさを検証する」という前 handover の lesson は、Phase J で literal に複数回作用した — failure ごとに次の段が見え、最後に三段構造が完成した。これは設計の **段階的発見** の典型例。Plans 段階で全部書こうとせず、acceptance での失敗を「次の構造境界の signal」として受け取る姿勢が、Phase J 全体を通して練習された。Phase J 完遂は、機構の完成と同時に、この設計姿勢自体の完成でもある。* — 2026-05-13
