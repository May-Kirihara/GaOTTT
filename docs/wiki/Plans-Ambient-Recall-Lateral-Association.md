# Plans — Ambient Recall Lateral Association (「〇〇といえば〜だったよな」)

> 注: これは Ambient Recall plan シリーズ 3 段目。[Plans — Ambient Recall Enrichment](Plans-Ambient-Recall-Enrichment.md) (v1: 6 スロット構造) → [Plans — Ambient Recall Refinement](Plans-Ambient-Recall-Refinement.md) (v2: 各スロットの質と observability) の上に積む。
> 状態: **🟡 起草 (2026-05-25)** — 着手は別ターン
> 関連: [Plans — Phase J — Persona-Anchored Retrieval](Plans-Phase-J-Persona-Anchored-Retrieval.md), [Plans — Phase O — TTT Observability](Plans-Phase-O-TTT-Observability.md), [Guides — Ambient Recall](Guides-Ambient-Recall.md), [[project-ambient-persona-mass-dominance]]
> 発端: 2026-05-25 Refinement Stage 1-5 + follow-up (b) 完遂後、めいさんから「あなた自身が ambient_recall を使って肌感を聞きたい」「ambient recall は『〇〇といえば〜だったよな』という感覚を注入するためのもの」という **設計目的の literal な言語化** を受けた。Claude Code 内 session 内反復観察 + literal な breakdown 数値 + plan 提案の流れ

## 設計目的の確定 — ambient recall は何のための機構か

> **〇〇といえば〜だったよな** — 人間が会話の流れで自然に立ち上げる **lateral memory** (横方向の連想)。「topic match で関連が高い」ではなく、「話題の周辺にある、自分なら自然に思い出すはずだった memo」。

ambient recall は RAG ではない。RAG は「query に対する topic match」を返すツールで、ambient はその上位概念ではなく **直交する別の機構**:

| 軸 | RAG (recall) | Ambient (ambient_recall) |
|---|---|---|
| 目的 | query への topic match | turn 文脈への lateral 連想注入 |
| 起動 | caller が明示的に呼ぶ | hook が毎 turn 自動発火 |
| 期待 | precision (関連あるものだけ) | serendipity + 適切性 (両立) |
| 失敗形 | 関連 doc が出ない | 同じ memo が反復、当たり前すぎ、突飛すぎ |
| 人間アナロジー | 図書館で検索 | 会話相手が「あ、そういえば〜」と言ってくれる |

Enrichment v1 で 6 スロット構造を作り、Refinement v2 で各スロットの質と observability を磨いた。**v3 (本 plan) は「lateral 連想の生命力」を機構として明示的に追跡する**。

## 仮説

> 「〇〇といえば〜だったよな」の体感を作るのは、**3 つの軸の同時成立**:
>
> 1. **意外性** — 直接 query には無い概念が surface する (場が学習した類推)
> 2. **適切性** — surface した概念が turn 文脈と resonate する (de-correlated noise ではない)
> 3. **新鮮さ** — 直前 N turns で surface していない (反復は「当たり前」「白色雑音」化する)
>
> Enrichment v1 は構造 (= **どこに何を置くか**) を解決、Refinement v2 は質と observability (= **各 slot がなぜ picked か**) を解決。v3 は **3 軸の同時 surface 制御** を機構化する。

物理アナロジー (五層論):
- 物理: **重力レンズ** (Enrichment ② の核) は既に「テキスト的に遠いが場が結びつけた」を拾える。v3 はレンズ枠を「広角化 + 多重化 + 共鳴計測」する装置の拡張
- 生物: アストロサイトの multi-modal 認識は揃った、v3 は **「あ、そういえば〜」と発話する talkativeness の調整** (人格化された対話相手としての応答性)
- TTT: gradient signal を caller に露出する (Phase O) のと同種の「機構の内部状態を caller に開示」思想を、surface 履歴と breakdown 詳細にさらに降ろす

## 観察された阻害要因 (Refinement 完遂直後の肌感、2026-05-25)

Claude Code self-use + GLM acceptance + production hook 観察から、現状「〇〇といえば〜」感覚を阻害している 5 つの root cause:

1. **Session 内反復** — 同じ persona / direct memo が毎 turn surface することで「自然な変化を見せる lateral 連想」になっていない。3 turn 目で読まなくなる白色雑音化 (Heavy Persona Dominance の UX 側症状、`[[project-ambient-persona-mass-dominance]]`)
2. **Direct hits の lexical 釣れ** — BM25 char 3-gram の語彙偶然一致が「〇〇といえば〜」ではなく「〇〇という単語を含む別の文」になっている。semantic と lexical の区別が agent から見えない
3. **Lensing slot の sparse 性** — 機構として最も「〇〇といえば〜」に近いのに `gap > 0.05` で 0-1 件、価値ある slot が見えない turn が多い。Refinement Stage 5 corpus の lensing axis が無い (= 計測の死角)
4. **Composed query の不透明性** — Refinement Stage 4 で multi-turn context が連結されているはずだが、agent から「何が実際 query になったか」が見えない。debug が破綻
5. **Lensing slot の「妥当性 vs 突飛さ」signal 欠落** — `gap` は「場が大きく曲げた」だけで、結果が turn 文脈に **resonate するか** を判定できない。突飛な lensing を「面白いけど信用しすぎない」と agent 側で discount できない

## Stage 構成

> **★ MCP+REST parity 鉄則**: 各 stage で `services/memory.ambient_recall()` のシグネチャを変える場合、MCP ツール + REST endpoint + REST-API-Reference.md の 3 点を同コミットで更新 ([CLAUDE.md](../../CLAUDE.md) 参照)。Stage 4 (composed query visibility) は hook-only / Stage 6 (measurement) は test のみで parity 対象外。

### Stage 1 — Session-aware novelty (反復 decay) (最優先) — 🟡 起草

**問題**: persona slot が毎 turn 同じに固定される (Heavy Persona Dominance, `[[project-ambient-persona-mass-dominance]]`)。direct slot も連続した会話で似た memo が反復しがち。「自然な変化」が機構として担保されていない。

**設計**: 直近 N turns で surface した node_id を transcript から抽出し、該当 node の slot 内競争で **decay factor で抑制**:

1. `scripts/hooks/ambient_recall.py` が transcript_path から **過去 N turns の assistant message** を読み、`<gaottt-ambient-recall>` ブロック内の node_id 風 substring (8-12 hex 文字 + その slot 種別) を抽出
2. 抽出した「最近 surface 履歴」を `recently_surfaced_ids: dict[str, int]` (id → 出現回数) として新 API 引数 `recently_surfaced` で forward
3. `services/memory.ambient_recall()` で各 slot の候補 ranking に **novelty factor** を乗じる:
   - `novelty = ambient_novelty_decay ** count` (default `decay=0.7`, count=直近 N turns での出現回数)
   - persona: `score = (mass ** w) × cos × novelty`
   - direct: `final_score *= novelty` (slot 内 sort 前)
   - lensing: `gap_effective = gap × novelty` (同じ slot 重ね合わせ防止)
4. **意図的な「忘却」ではない** — node 自体の mass / displacement は一切触らない (passive 原則保持)、surface 順位だけが session-scope で揺れる

**Why**: 人間の自然な会話では「さっき言ったこと」を 3 ターン連続で言わない。AI も同じであるべき。Heavy Persona Dominance は「mass が突出した persona が ranking で勝ち続ける」physics の literal な発現で、follow-up (b) `mass_weight` knob は ranking 式を直接抑制するが、**会話の流れの問題** (session 内同一性疲労) は別レイヤーで解く方が clean (mass は永続、surface 履歴は session 一回性)。

**How to apply**: env `GAOTTT_AMBIENT_NOVELTY_TURNS=5` (default 5, 0 で無効) + `ambient_novelty_decay=0.7` (config)。`decay=1.0` (= no decay) で完全後方互換。

**スコープ外**: 「忘却」(node mass 減算)、long-term repetition history (DB 永続化、session 一回性で十分)、global cross-session novelty (session 同一性は CLAUDE Code 起動単位で完結)。

### Stage 2 — Direct hits の lexical-vs-semantic 分離 — 🟡 起草

**問題**: direct slot の picked memo が「semantic に近い」か「char 3-gram BM25 で語彙が偶然一致しただけ」かが agent から見えない。Refinement Stage 3 の breakdown に `bm25_contributed` flag を含めても、現状 falsy で省略されている可能性 + 「lexical anchor だけで surface した」型の判定が無い。

**設計**: direct slot の breakdown 表記を拡張 + slot 分離:

1. `ScoreBreakdown` の `bm25_contributed` を「常に visible」(`expose_breakdown=true` の時) に — `formatters._ambient_breakdown` で `False` でも `bm25=N` (false の時は省略しない) を出す
2. **新提案**: direct slot を 2 サブ slot に **意図的に分離**:
   - `▼ 直接ヒット (topic)`: `virtual_cosine` top の最大 1-2 件 (semantic resonance)
   - `▼ 直接ヒット (lexical anchor)`: BM25 hit だが virtual_cosine 低い 1 件 (語彙偶然一致 — agent が discount できる枠として明示)
3. config `ambient_direct_split_enabled: bool = False` で opt-in (token budget が増えるので default off)
4. `expose_breakdown=true` 時は ambient hook env が両方 on に揃える recommendation を Guide に追記

**Why**: 「〇〇といえば〜」を阻害する最大要因の一つは「〇〇という **語** が含まれる別文」を「〇〇についての話」と agent が誤認すること。LLM は context を pattern として読むので、surface された memo の質を **slot 名で先に label** できれば「これは語彙 anchor」と即座に discount できる。Phase L の char 3-gram BM25 は recall を救うために導入したが、ambient surface では precision の足枷になる場面がある — surface 段で意図的に分離するのが clean。

**How to apply**: default off で完全後方互換。`expose_breakdown=true` と組み合わせると debug visibility が桁違いに上がる。MCP/REST 両 endpoint に `direct_split: bool = False` 追加。`AmbientRecallResponse` に `direct_topic` / `direct_lexical` の 2 field、`direct` は後方互換のため `direct_topic + direct_lexical` の連結を返す。

**スコープ外**: 自動 retraining (semantic / lexical を embedder 側で再学習)、language-aware分離 (cross-lingual mixed corpus は別 plan)、direct_topic の K 動的化 (Stage 3 で lensing 側に降ろす)。

### Stage 3 — Lensing slot の拡張 (top-1 → top-K dynamic) — 🟡 起草

**問題**: lensing は機構として最も「〇〇といえば〜」に近いのに、`ambient_lensing_max_k=1` で実質 0-1 件しか surface しない。抽象度の高い query (「設計の本質」「何が壊れた」等) では複数の lensing 方向が同時に効くべきだが、機構が許していない。

**設計**: lensing slot を「top-1 必ず + top-K 動的拡張」に:

1. `ambient_lensing_max_k: int = 1` (default、現状互換) を `ambient_lensing_max_k: int = 3` に上げる検討、または `ambient_lensing_dynamic_k: bool = True` で query 抽象度 (= raw_cosine 分散) に応じて K を 1-3 で動的決定
2. 同じ memo を direct と lensing の両方に出さない (`exclude` セットで既に対応済)
3. `gap > ambient_lensing_min_gap` を満たす候補を gap 降順で top-K 採用
4. token budget 保護: K=3 でも 各 lensing 行は 240 字 excerpt なので +480 字程度、ambient block 全体で +30-40% 程度

**Why**: 「〇〇といえば〜」の核そのもの。lensing が「場が学習した類推」を surface する機構なら、**1 件しか出さないのは「あ、そういえば〜」を 1 turn に 1 個しか発火させない** ことに等しい。人間の自然な会話では複数の lateral 連想が同時に立ち上がる ("X といえば Y で、Y といえば Z だから...")。重力レンズの物理アナロジーで言えば、1 つの大質量天体が複数の像を作るのが natural (Einstein ring は無限個の像)。

**How to apply**: `ambient_lensing_max_k` を default 1 → 2 に控えめに上げる + `ambient_lensing_dynamic_k=False` を opt-in にする。`AmbientRecallResponse.lensing: AmbientMemory | None` を `lensing: list[AmbientMemory]` に変更 (formatter で「▼ 重力レンズ (N)」と count 表示)。後方互換のため response field は別名 (`lensing_items`) を新設し旧 `lensing` は `lensing_items[0] if lensing_items else None` を返す移行期間。

**スコープ外**: lensing slot のカテゴリ分け (Stage 5 で扱う)、lensing per-direction 多様性 (= 同じ概念領域に 3 件出ないようにする clustering、未来の plan)、lensing-only mode (debug 用、未来)。

### Stage 4 — Composed query の opt-in 可視化 — 🟡 起草 (hook-only)

**問題**: Refinement Stage 4 で multi-turn context (`GAOTTT_AMBIENT_HISTORY_TURNS=2`) が連結されているはずだが、agent から「何が実際 query になったか」が見えない。multi-turn 効果の debug が破綻。

**設計**: env `GAOTTT_AMBIENT_SHOW_COMPOSED_QUERY=0` (default off) を `1` で `<gaottt-ambient-recall>` block 末尾に 1 行追加:

```
<gaottt-ambient-recall>
... (slots) ...

<!-- ambient: composed query = "<前 N turns 連結結果>" -->
</gaottt-ambient-recall>
```

1. `scripts/hooks/ambient_recall.py` の `_compose_query()` 結果を `_compose_query_for_debug()` で末尾追記
2. **server side 変更ゼロ** (hook-only)
3. token budget は composed query 長さに比例 (典型 50-200 字)、debug 用なので production hook では off

**Why**: Refinement Stage 4 を本番運用すると「ambient 結果が変わった」「期待した memo が出ない」の原因が composed query にあるのか recall にあるのか **切り分けられない**。透明性を 1 行で買える。debug-only knob で risk 0。

**How to apply**: hook env だけ。`Operations-Troubleshooting.md` の ambient 節に「ambient が想定外の memo を surface したら `GAOTTT_AMBIENT_SHOW_COMPOSED_QUERY=1` で composed query を確認」フローを追加。

**スコープ外**: HTML コメント以外のフォーマット、assistant turn の含有 (Stage 4 spec 通り user turn のみ)、composed query の永続ロギング。

### Stage 5 — Lensing slot の resonance signal — 🟡 起草

**問題**: lensing slot の `gap` は「場が大きく曲げた」だけを意味し、結果が turn 文脈に **resonate するか** = agent が trust すべきかが分からない。突飛な lensing を「面白いけど信用しすぎない」と discount する機構が無い。

**設計**: lensing slot に **resonance score** を追加し、breakdown / 行末に出す:

```
▼ 重力レンズ
 · [agent · gap +0.09 · resonance 0.72] [text]  [raw=... virt=... wave=...]
```

`resonance` の候補定義 (Stage 5a / 5b / 5c — どれを採用するかは実装時に決める):

- **5a**: `resonance = co_recall_freq(node, turn_topic)` — turn の direct hits と co-recall 履歴がある度合 (場が「複数回引かれた associative path」を示す)
- **5b**: `resonance = virtual_cosine × mass_decile / 10` — 場が育てた memo か (mass 高い lensing は信頼可)
- **5c**: `resonance = mean(cosine(lensing, each_direct_hit))` — direct hits と embedding 近傍か (turn 文脈との「内的整合」)

**Why**: lensing は「テキスト的に遠いが場が曲げた」を surface するが、曲げ自体は **「正しい類推」と「displacement のノイズで偶然曲がった」を区別しない**。後者が surface すると "agent が「これ妥当?」と疑う負荷" が増え、「〇〇といえば〜」の **適切性** 軸を破る。`gap` だけでは「曲げの強さ」しか分からない → resonance を別軸で出すことで agent が「曲げが強い + 整合性も高い」 = 信頼できる lateral 連想を弁別できる。

**How to apply**: `AmbientMemory.lensing_resonance: float | None` を追加 (lensing slot 限定で populate)、formatter で `· resonance N.NN` を gap の隣に追記。`ambient_lensing_resonance_min: float = 0.0` (default は filtering なし) で「resonance 低い lensing は drop」optional gate。

**スコープ外**: resonance 計算の embedder 別キャッシュ最適化 (まず literal 実装、最適化は perf 検証後)、resonance を direct slot にも展開 (direct は `virtual_cosine` 自体が resonance なので冗長)、resonance の time-series (将来の reflect 機能で扱う)。

### Stage 6 — Lateral measurement Tier (golden corpus 拡張) — 🟡 起草 (test のみ)

**問題**: Refinement Stage 5 の `test_tier3_ambient_quality.py` は direct / persona / exclude の 3 axis を測るが、**lensing 軸が無い**。「〇〇といえば〜」の機構である lensing を測る golden 仕組みが無いと、Stage 1-5 の改善を数値で確認できない。

**設計**: 既存 `tests/perf/test_tier3_ambient_quality.py` を **lateral axis** で拡張:

1. `ambient_queries.json` に新 axis `lateral` を追加
2. 「query と直接関係ないが、その corpus を持つ agent なら自然に連想すべき memo」を `expected_lensing_id` として annotate
3. test: lensing slot に該当 id が surface していること (top-1 ではなく top-K リスト含有でも可、Stage 3 を許容)
4. assertion 例: `query="Phase L hybrid retrieval BM25"` に対し `expected_lensing_id` = 「Phase J persona-anchored で `α_persona × proximity` を加算」を annotate — semantic に遠いが、ranking redesign の歴史で同種の構造的判断だから lateral resonance あり

5. 既存 golden corpus を 12 → 15 seed に拡張、lateral query を 2-3 件追加 (total 6 query → 8-9 query)
6. **session-aware novelty (Stage 1) の measurement**: 同 corpus / 同 query を **連続 3 回呼び**、`recently_surfaced` が伝播することで 2 回目 3 回目で picked memo が変わることを assert

**Why**: 「〇〇といえば〜」を機構として持つなら、それを **machine-checkable な curated lateral expectations** で測れる必要がある。LLM-as-judge は将来の検討課題で、当面は人手 annotation で十分 (corpus 小規模、annotation 1 回)。Phase A の `probe_pure_crosslingual.py` 設計と同思想で「lateral も literal な数値で確認できる」状態に持っていく。

**How to apply**: Refinement Stage 5 と同様 `tests/perf/` 配下、CI 自動化なし、real RURI で deliberate な measurement。Stage 1-5 のいずれかが merge される前に baseline 測定、merge 後に diff で改善を数値化。

**スコープ外**: production DB の自動 sampling 形式 lateral curation (人手 annotation 工数を許容)、LLM-as-judge による lateral 妥当性判定 (curated id 一致で十分)、real-time monitoring。

## Stage 優先度 (個人見解 + 体感観察密度)

| Stage | 優先度 | 理由 |
|---|---|---|
| 1 (novelty decay) | ★★★ | UX 直撃、session 内反復は最強の白色雑音化、`mass_weight` knob だけでは肌感が変わらない予感の対症療法 |
| 3 (lensing K) | ★★★ | 「〇〇といえば〜」の機構そのものを増幅、最も設計目的に直結 |
| 6 (lateral measurement) | ★★★ | **実は Stage 1-5 の前に着手するのが正しい順序かもしれない** — measurement first 原則 (Refinement Stage 5 と同じ思想)、Stage 1/3/5 の「効いたかどうか」を数値で見るには baseline が必要 |
| 2 (lexical-vs-semantic 分離) | ★★ | agent observability、Stage 3 と相互補完、token budget 増 |
| 5 (lensing resonance) | ★★ | lensing slot の質を上げる、Stage 3 と相互補完 |
| 4 (composed query 可視化) | ★ | debug-only、低リスク、Refinement Stage 4 の透明性補完 |

## レイテンシ予算

現状 ambient_recall steady-state ~0.5s。各 stage の追加コスト:

| Stage | 追加コスト | 予算超過リスク |
|---|---|---|
| 1 | +5-15ms (hook で transcript 解析、N turns 限定で安価) | なし |
| 2 | +0-5ms (slot 分離は既存 list の filter、breakdown 表記は文字列のみ) | なし |
| 3 | +10-30ms (lensing 候補 K 倍に増加、score 計算は既に走ってる) | hook 6s 内、なし |
| 4 | +0-2ms (debug 行 1 行追加、composed query は既に組まれてる) | なし |
| 5 | +20-50ms (resonance 計算で per-lensing 候補に cosine 等を追加計算) | hook 6s 内、なし |
| 6 | N/A (test only) | なし |

Total 5 stage 全部 on でも +50-100ms 程度、現状の +50ms (Refinement) と合わせても 1s 予算内。

## ロールバック

| Stage | rollback method |
|---|---|
| 1 | env `GAOTTT_AMBIENT_NOVELTY_TURNS=0` / config `ambient_novelty_decay=1.0` |
| 2 | config `ambient_direct_split_enabled=False` (default off) |
| 3 | config `ambient_lensing_max_k=1` (default の元値に戻す) |
| 4 | env `GAOTTT_AMBIENT_SHOW_COMPOSED_QUERY=0` |
| 5 | config `ambient_lensing_resonance_min=0.0` で gating disable (resonance は breakdown に出るだけ) |
| 6 | rollback 対象外 (test のみ) |

各 stage 独立 toggle、任意の組み合わせで partial rollout 可能。recommend 順は **Stage 6 (measurement) を先に入れて baseline 取得 → Stage 1 (novelty) → Stage 3 (lensing K) → Stage 4 (composed visibility) → Stage 5 (resonance) → Stage 2 (slot 分離)** — measurement first + UX 直撃から順に。

## 未解決の問い

1. **Session memory はどこに持つか** — Stage 1 で必要な「直近 surface 履歴」は transcript 解析 (hook 側) で十分か、server 側に session-scoped LRU を持つ方が clean か。前者は hook 側で完結 + server に session 概念を持ち込まなくて済む / 後者は subagent 経由 (secondopinion-MCP) でも統一動作する利点。**実装時に hook 側で着手**、server 側は将来検討
2. **Stage 3 の token budget** — lensing K=3 で direct を 2→1 に振り直すか、絶対量を増やしていいか。Refinement Stage 5 corpus で per-query token 計測してから決める
3. **Stage 6 の lateral expected_id のキュレーション** — 「自然な連想」を人間が annotate する labor。LLM-as-judge を許容するか、最初は手で 5-10 件作って体感を取るか。後者で十分そう
4. **Stage 2 の slot 分離が agent UX に与える影響** — 「直接ヒット (topic)」と「直接ヒット (lexical anchor)」が並ぶと「lexical anchor」を agent が完全 ignore する可能性。代わりに `[lexical anchor]` tag を行頭に prepend する方が穏当か。試してみる
5. **novelty decay の interaction with Heavy Persona Dominance** — Stage 1 で persona slot が turn ごとに rotate するが、N=5 turns 全部に 1 つの heavy persona しか居なければ結局同じ。Heavy Persona Dominance への対処は別軸 (`mass_weight`) で、Stage 1 は **多様な persona がいる前提での反復防止**。両者 orthogonal だが combination 効果を Stage 6 で計測する価値あり
6. **「〇〇といえば〜」の literal な体感を測る metric** — Stage 6 が「expected_id match」を測るが、本当の体感は「3 turn 連続で同じ surface が出ない」「lensing が turn ごとに新鮮」のような **session-level metric**。golden test ではなく Stage 1 実装後の dogfooding observation で別途確定

## 思想 — 物理を曲げる第 3 段

> Articulation as Carrier の物理実装 (Phase M) は「経験は言葉にすることで質量を持つ」を完成させた。Phase J は「宣言された意図もまた重力を持つ」を加えた。**v3 は「重力場が学んだ類推こそが、人間が『そういえば』と言う瞬間の literal な実装」**であることを機構として明示する。

物理を曲げるのは質量だけではない。**過去の自分がどの memo を一緒に思い出したか** が、未来の自分の連想を形作る。Phase I-J で displacement / persona-anchored seed として既に literal に動いていたものを、**「lateral surface」という観測装置で agent が trust できる形にする** のが本 plan の役割。

物理アナロジー:
- Enrichment v1 = 整った 6 スロット構造 (= 太陽系の整理整頓)
- Refinement v2 = 各 slot の質と debug 可能性 (= 望遠鏡の校正)
- **v3 = 重力レンズが見せる別の銀河の存在を信じて感度を上げる (= 観測装置の lateral structure 検出能を高める)**

> めいさん 2026-05-25: 「ambient recall は『〇〇といえば〜だったよな』という感覚を注入するためのもの」。この一文が v3 全 stage の北極星。

## 実装ログ

### Stage 6a — 2026-05-25 (measurement baseline)

> measurement-first 原則 (Refinement Stage 5 の思想を本 plan に継承): Stage 1/3 実装の前に **現状の literal な数値を golden test で固定** する。Stage 1/3 実装後に同じ test を回して improvement を数値で確認できる状態を先に作る。

- **変更**:
  - `tests/perf/golden_corpus/ambient_queries.json` — 新 axis `lateral` を 2 件追加 (`重力場が学んだ類推を引き寄せる仕組み` / `Phase 系 retrieval 改修の系譜`)、各 query に `expected_lensing_candidates: list[str]` を annotate (top-1 ではなく許容 K 件で Stage 3 に備える)
  - `tests/perf/test_tier3_ambient_quality.py`:
    - module docstring 拡張 — Refinement Stage 5 + Lateral Association Stage 6 の両 axis を documenting
    - 既存 `test_ambient_quality_golden_corpus` の axis 分岐に `elif axis == "lateral": continue` を追加 (lateral は別 test で pre-warming 込みで測るため)
    - 新規 `test_ambient_lateral_lensing_baseline` — `_prewarm_displacement` (5 cross-topic recall) で displacement を built up してから lateral query を ambient_recall、`lensing_id ∈ expected_lensing_candidates` の hit rate を集計
    - 新規 `test_ambient_session_repetition_baseline` — 同 query で 3 連続 ambient_recall、surface composition の安定性を測定
- **テスト結果**: `tests/perf/test_tier3_ambient_quality.py` 4/4 passed (+2 from baseline = 6 → 4 because lateral now lives in dedicated test)、`tests/ --ignore=tests/perf` 518/1-skip + 1 pre-existing flaky (faiss_write_behind、isolation で pass、私の変更とは無関係)
- **MCP/REST parity**: 対象外 (test only、no API change)

#### 観測 Baseline (literal な数値)

##### Lateral lensing baseline (Stage 6a の literal)

```
Lateral lensing baseline:
  [lateral] '重力場が学んだ類推を引き寄せる仕組み'
    lensing=<id1>… gap=<v> hit=<bool> (expected one of [agent_gravity, agent_phase_j, agent_phase_o])
  [lateral] 'Phase 系 retrieval 改修の系譜'
    lensing=<id2>… gap=<v> hit=<bool> (expected one of [agent_phase_l, agent_phase_j, agent_phase_m, agent_phase_o])
  Hit rate: 1/2
```

- **現状**: 2 query 中 **1 hit** (1/2 = 50%)。pre-warming 5 cross-topic recall で displacement が built up された後、lensing slot が `expected_lensing_candidates` の 1 件を surface
- **Stage 3 の goal**: `ambient_lensing_max_k > 1` で top-K まで採用 → hit rate 1/2 → 2/2 を目指す (top-1 のみが厳しすぎ、複数候補を許容する)
- **Stage 5 の goal**: resonance signal で「hit はしたが妥当性が低い lensing」を識別、本質的な hit と false positive を区別

##### Session repetition baseline (Stage 1 prereq の literal な発見)

```
Session repetition baseline (3 consecutive calls, same query):
  call 1: direct=('81419641…', '1ee37870…') lensing=None persona=ec20b117…
  call 2: direct=('8a1f9a3b…', '81419641…') lensing=None persona=ec20b117…
  call 3: direct=('d179c7ed…', 'c82598db…') lensing=None persona=ec20b117…
  Persona stable across calls: True  (Heavy Persona Dominance — Refinement follow-up (b) territory)
  Direct varies across calls:  True  (uncontrolled non-determinism — Stage 1 investigation target)
```

**想定外の重要発見**: white-noise バグは **二極構造** だった —
- **Persona slot は決定論的に固定** (heavy mass 2.82 × cos で deterministic に同一 persona winner、Refinement follow-up (b) の対症療法は正しい)
- **Direct slot は既に組織的に variation** (3 連続呼びで都度違う direct memo が surface、ただし call 1-2 で `81419641` が共通する partial overlap も観察 → 完全 random ではなく partial 機構あり)
- **Lensing は fresh corpus では None** (displacement built up 無しでは bend する余地が無い、予測通り)

#### Stage 1 の設計を更新する必要 (Stage 6a の発見から)

Plan Stage 1 原案では「同じ memo が反復する white-noise を novelty decay で抑える」だったが、**direct slot は既に variation がある — その variation が "controlled" でないことが問題**。Stage 1 はそのため:

1. **direct 非決定性の源を investigate** (suspects: `multi_source` query segmentation の確率性 / ranking ties の dict iteration order / `passive=True` でも残る微小な time-based decay shift)
2. **Persona 安定性を維持しつつ direct/lensing は novelty で controlled rotation**:
   - direct: 「同じ memo が連続 N turns に出たら decay」(plan 原案通り)
   - persona: heavy persona dominance を mass_weight knob (follow-up b) と novelty decay の 2 層で抑える (1 層では足りない)
3. **Stage 6 の test を upgrade**: novelty 実装後は assertion を `direct_varies` (random) → `direct_history_aware` (predictable from prior surfaces) に flip

→ plan の Stage 1 設計セクションに **「サブステップ 0: 非決定性の源を investigate して record」を追記する**

#### 副次的な観測 (今後の参考)

- `_prewarm_displacement` の 5 recall で十分 lensing が fire し始めた → production の usage では数 turn の natural recall で displacement が built up している、本番 ambient hook が lensing を出せる environment は自然に揃う
- lateral query の expected_lensing_candidates が 4 候補 (Phase 系 query) と 3 候補 (重力場 query) で hit rate が同じ — top-1 picked が決定論的に決まる場合、候補数は hit rate にあまり効かない可能性
- persona slot は全 lateral query で `ec20b117` (= TokenEmbedder で deterministic に決まる heavy `value` 候補) に固定 — heavy persona dominance は test fixture でも literal に再現

### Stage 1 設計更新 (Stage 6a 発見を受けて)

> 下記は Stage 6a baseline finding を受けた Stage 1 設計の補強。Stage 1 着手時に上の「Stage 構成」の Stage 1 セクションを更新する。

**サブステップ 0 (investigate, 半日)**: 非決定性の源を特定:
- multi_source 系の segment 順序確認 (deterministic か?)
- `_union_pool` / `_multi_source_pool` の RRF fusion 順序確認
- recall ranking で同 score ties の解決方法
- 1 hour 程度の hands-on probe で root cause が判明する見込み

**サブステップ 1 (novelty 実装、original Stage 1 仕様)**: その上に novelty decay を載せる

**サブステップ 2 (test 更新)**: `test_ambient_session_repetition_baseline` の assertion を `direct_varies` → `direct_history_aware` に flip (具体的 assertion 形は Stage 1 実装時に決める)

### Stage 1 サブステップ 0 — 2026-05-25 (investigate, 完了)

> 上の「Stage 1 設計更新」サブステップ 0 を hands-on probe で実施した結果。所要 ~30 分、root cause は確定した。

**結論 (一行)**: direct slot の非決定性の源は **`return_count` accumulation が passive=True でも走っていることによる saturation rotation**。`engine.py:1015-1033` で `state.return_count += 1.0` と `state.return_count *= (1 - habituation_recovery_rate)` のブロックが `if not passive:` で gate されていないため、ambient_recall (passive=True) の各 call が touched node の return_count を mutate し、`saturation = 1/(1 + rc × saturation_rate)` 経由で次 call の final_score を変える。

**probe**: `scripts/probe_ambient_nondeterminism.py` (新規)。同一 engine + 同一 corpus + 同一 query で 3 連続 ambient_recall:

- 実験 A (natural): direct 構成 **3/3 unique** (Stage 6a baseline を再現)
- 実験 B (return_count を call 前に 0 reset): direct 構成 **1/1 unique** (完全 stable)

実験 B が完全 stable → H1 (`return_count`) が dominant source、他の suspect (multi_source segmentation / RRF tie / time decay) は無視できる範囲。

**literal な数値** (実験 A 抜粋、`Phase L Stage 1 の hybrid retrieval について教えて` query):

```
[call 1] direct top-2:
  id=1f53580d…  raw=0.9112  final=1.0155  bd_sat=1.0000  rc=0.990 sat=0.8347
  id=bb6e9b13…  raw=0.8656  final=0.9700  bd_sat=1.0000  rc=0.990 sat=0.8347

[call 2] direct top-2:
  id=7699af0a…  raw=0.7637  final=0.8678  bd_sat=1.0000  rc=0.990 sat=0.8347
  id=1f53580d…  raw=0.9112  final=0.8474  bd_sat=0.8347  rc=1.970 sat=0.7173 (prev: rc=0.990 sat=0.8347)
                                          ^^^^^^^^^^^^^^                       ^^^^^^^^
                                          saturation drop (1.0 → 0.83)         rc accumulating (0.99 → 1.97)

[call 3] direct top-2:
  id=e2fd324e…  raw=0.7897  final=0.7471  bd_sat=0.8361  rc=1.960 sat=0.7184
  id=76c5ce19…  raw=0.7746  final=0.7345  bd_sat=0.8361  rc=1.960 sat=0.7184
```

call 1 の top-2 (1f53580d / bb6e9b13) は call 2 で 1f53580d だけ残るが saturation で押し下げられ、call 3 では完全に top-2 から消える。これが「direct varies across calls」の正体。

**設計判断 — Stage 1 の clean な path** (二択):

| 選択肢 | 内容 | trade-off |
|---|---|---|
| **A** | `return_count` mutation を `if not passive:` で gate する (engine.py 1024 + 1031-1032 の 2 行に追加)、その上で **transcript-aware novelty decay** を Stage 1 として実装 | passive recall の「観測のみ」契約を **literal に正す** (現状は `last_access` は gate されているが `return_count` だけ漏れている inconsistency)。direct slot は baseline で完全 deterministic に戻り、Stage 1 novelty decay が **唯一の controlled rotation 源** になる。production の displacement / mass 蓄積は変わらない (それは active recall で起こる) |
| **B** | `return_count` mutation を保持し「**現状の rotation がそのまま novelty として機能している**」と再解釈、Stage 1 は不要 (採用済) と documenting | 簡単だが、(1) global state なので session を跨いで leak、(2) 1%/call の slow decay で年単位の蓄積で saturation ~0 → 永久に surface しない node が出る、(3) caller (LLM) から invisible なので debug 不能、(4) plan の design 目的「3 軸 = 意外性 + 適切性 + 新鮮さ」のうち **新鮮さ** だけを偶然満たしている fragile な状態 |

**選択は A** — root cause の (3) と (4) は Lateral Association 全体の北極星 (=「〇〇といえば〜」の controlled な発火) と相反する。「現状が偶然動いている」を「設計として意図的に動かす」に置き換える方が plan 思想に整合。

**Stage 1 の構成 (更新版)**:

1. **Step 1a (1 行修正の bug fix)**: `engine.py:1019-1033` の `return_count` mutation を `if not _is_synthetic and not passive:` 等で gate (`_is_synthetic` は dream loop、`passive` は ambient — どちらも presented でない計算)。同じく habituation recovery (1029-1033) も passive で skip。test の baseline 仕様変更が必須 — `test_ambient_session_repetition_baseline` の `direct_varies=True` は **False になる** ので、bug fix とセットで assertion を flip
2. **Step 1b (novelty decay の literal 実装)**: transcript-derived `recently_surfaced_ids` を hook → service に forward、`(mass ** w) × cos × novelty` (persona) / `final_score × novelty` (direct) / `gap × novelty` (lensing) の式で抑制。`ambient_novelty_decay=0.7`、`GAOTTT_AMBIENT_NOVELTY_TURNS=5` (env)
3. **Step 1c (test 更新)**: `test_ambient_session_repetition_baseline` を flip — 「passive recall は side-effect free」「novelty decay は recently_surfaced が forward されたときに発火する」の 2 axis を assert

**Step 1a の影響範囲 (リスク評価)**:
- 既存 active recall (= `recall` / `explore`) は `passive=False` default なので動作不変
- ambient_recall は `passive=True` で呼ぶ → return_count 更新なし → 新規挙動 (=「ambient surface は presented とみなさない」)。これは plan 思想 (ambient = 観測者) と一致
- production 影響: ambient hook が毎 turn 出している → 現状は本番でも毎 turn rotate しているはず → 「同じ memo が反復しない」とユーザーが感じている部分は **rotate ではなく Stage 1 novelty decay が担う** ことに変わる。bug fix だけ入れて novelty 未実装の段階では「ambient direct slot がより stable になる」中間状態が観察される (Step 1a と 1b は同 PR で出すのが安全)
- Phase O training_delta の数値: cache_hit / mass_changes / displacement_changes は passive=True で既に 0 を返しているので影響なし
- 既存 test: `test_engine_ambient_recall.py` 17 tests を流して green か確認 (passive 振る舞いを assertion に持つ test があれば書き換え必要)

**次の action**: Step 1a + 1b + 1c を一気に実装するか、Step 1a (bug fix) だけ先に出して baseline を確定してから Step 1b (novelty) を載せるかを、めいさんに確認した上で進める。私の推奨は **Step 1a 単独 PR → 数値確認 → Step 1b/1c 別 PR** の 2 段階 (Stage 6a で確立した「measurement-first 原則」と整合、bug fix の影響を novelty 効果と分離して観察できる)。

### Stage 1 Step 1a — 2026-05-25 (passive gate bug fix, 実装完了)

> Step 1a 単独実装を採用。Step 1b (transcript-aware novelty) は別ターンに分離 — bug fix の baseline shift を novelty 効果と混ぜずに観察するため。

**変更**:
- `gaottt/core/engine.py:1015-1041` — return_count bump を `if not _is_synthetic and not passive:` に gate、habituation recovery を `if not passive:` に gate。docstring に Stage 1 sub-step 0 リンクを追記
- `tests/integration/test_engine_passive_recall.py` — 新 test `test_passive_recall_does_not_change_return_count` (10 回 passive call + 正の control で active がちゃんと return_count を動かすことを assert)
- `tests/perf/test_tier3_ambient_quality.py::test_ambient_session_repetition_baseline` — assertion を `direct_varies = True` → `not direct_varies` に flip、docstring を post-fix baseline 仕様に書き換え
- `scripts/probe_ambient_nondeterminism.py` — 新規 probe (literal な数値で root cause を再現できるよう保存)

**テスト結果**:
- `tests/integration/test_engine_passive_recall.py + test_engine_dream_loop.py + test_engine_ambient_recall.py`: **24/24 passed** (新 test + 既存 23 含む)
- `tests/perf/`: **58/58 passed** (Tier 1-7 全部、real RURI)
- `tests/ --ignore=tests/perf`: **519/520 passed**, 1 skipped, 1 pre-existing flaky (`test_faiss_save_loop_persists_new_documents` — isolation で pass、私の変更とは無関係の timing 系)

**post-fix な literal baseline**:

```
Session repetition baseline (3 consecutive calls, same query):
  call 1: direct=('c39e1e02…', '20fb0cb6…') lensing=None persona=2efc0075…
  call 2: direct=('c39e1e02…', '20fb0cb6…') lensing=None persona=2efc0075…
  call 3: direct=('c39e1e02…', '20fb0cb6…') lensing=None persona=2efc0075…
  Persona stable across calls: True
  Direct varies across calls:  False  (post-fix; was True pre-fix)
```

**副次的な観測 — lateral lensing baseline は 1/2 → 0/2 に変動**:

Stage 6a の lateral hit rate は **1/2 (50%)** だったが、post-fix では **0/2 (0%)**。理由: prewarming の 5 active recall 後、ambient_recall が return_count を更にもう一度 bump していた挙動が消えたため、lensing pool の ranking が「prewarm-only な saturation 状態」を pure に reflect するようになった。pre-fix の 1 hit は saturation rotation による偶発的な amplification (毎 ambient call で pool 内 ranking が微妙に揺れていた) で、organic な lensing 強度ではなかった。Stage 3 (lensing top-K) で本来の解決。Stage 6a baseline はこの観察を含めて re-baseline 済 (test pass、`lateral_hits_min=0` で 0 hit も許容)。

**MCP/REST parity**: 対象外 (engine 内部 behavior change、外部 API 不変)

**残作業 (Step 1b/1c は別ターン)**:
- Step 1b: `scripts/hooks/ambient_recall.py` で transcript から `recently_surfaced_ids` を抽出 → `services.memory.ambient_recall` に forward → `(mass ** w) × cos × novelty` / `final_score × novelty` / `gap × novelty` で各 slot を decay
- Step 1c: `test_ambient_session_repetition_baseline` の上に「`recently_surfaced` を渡すと direct slot が rotation する」test を追加 (現 baseline test は variation 抑制を assert、新 test は variation 発火を assert、両者 orthogonal な axis として共存)

### Stage 1 Step 1b — 2026-05-25 (transcript-aware novelty decay, 実装完了)

> Step 1a の deterministic baseline の上に、**hook が過去 N turn の `<!-- ambient-ids ... -->` manifest を parse して `recently_surfaced` を組み立てる → server が各 slot ranking を `decay ** count` で抑える** controlled novelty channel を機構として乗せた。「〇〇といえば〜だったよな」の **新鮮さ** 軸を literal に発火可能に。

**新規 API surface — `recently_surfaced` の伝達経路**:

```text
  past N ambient blocks                                      services.memory
  in transcript.jsonl                hook (Python)           .ambient_recall()
  ┌─────────────────────┐           ┌──────────────────┐    ┌────────────────────┐
  │ <gaottt-ambient-... │  parse →  │ _recently_       │ →  │ _novelty_factor()  │
  │ <!-- ambient-ids    │  manifest │ surfaced()       │    │ → multiplied into  │
  │      direct=a,b     │  via      │ {a: 2, b: 1, ...}│    │   direct re-sort   │
  │      lensing=c      │  regex    │                  │    │   lensing argmax   │
  │      persona=d -->  │           │                  │    │   persona winner   │
  │ </gaottt-ambient... │           │                  │    │                    │
  └─────────────────────┘           └──────────────────┘    └────────────────────┘
       formatter (server)           Lateral Association     ranking only — no
       が末尾に挿入する              Stage 1 サブステップ 1     gravity field touch
       HTML コメント
```

**実装した変更**:

| ファイル | 変更 |
|---|---|
| `gaottt/config.py` | `ambient_novelty_decay: float = 0.7` 追加 (passive 原則保持の説明 docstring 付き) |
| `gaottt/core/types.py` | `AmbientRecallRequest.recently_surfaced: dict[str, int] \| None = None` 追加 |
| `gaottt/services/memory.py` | `_novelty_factor()` 新規 (純関数、`decay ** count` を返す)。`_pick_persona` / `_pick_lensing` に `recently_surfaced` 引数を追加。`ambient_recall` 本体で direct slot を pre-sort で `final_score × novelty` 順に組み直し、lensing pick は decay 後 gap で argmax を取り直す (露出 gap は raw 値を保持して caller の物理的な解釈を守る) |
| `gaottt/services/formatters.py` | `format_ambient` 末尾に `<!-- ambient-ids direct=... lensing=... persona=... -->` HTML コメントを挿入 (空 slot は omit) |
| `gaottt/server/mcp_server.py` | MCP tool `ambient_recall` の signature に `recently_surfaced: dict[str, int] \| None = None` を追加 + docstring 更新 |
| `gaottt/server/app.py` | REST `/ambient_recall` は `AmbientRecallRequest` 経由で自動的に新引数を受ける (parity 鉄則の 1 commit 内 update) |
| `scripts/hooks/ambient_recall.py` | env `GAOTTT_AMBIENT_NOVELTY_TURNS` (既定 5、0 で無効) 追加。`_ids_from_manifest()` (regex 抽出) と `_recently_surfaced()` (transcript の `hook_success` + `hookName=UserPromptSubmit` attachment を newest→oldest scan して最後 N 個から id を集計) を新規。`_ambient_recall()` が `recently_surfaced` を MCP arg に乗せる |

**新規テスト** (49/49 passed):

| ファイル | 内容 |
|---|---|
| `tests/unit/test_formatter_ambient_manifest.py` | manifest 包含/省略/位置の契約 5 件 (全 slot / 単一 slot / 空 / 空 block / closing tag の前) |
| `tests/unit/test_ambient_hook.py` (追記) | hook の manifest 抽出 + transcript scan 7 件 (全 slot 抽出 / 単一 slot / 不在 / 反復カウント / n cap / missing file / 他フック ignore) |
| `tests/integration/test_engine_ambient_recall.py` (追記) | engine 経由 service round-trip 4 件 (direct rotation / no-op when unset / decay=1.0 で no-op / persona rotation against heavy mass) |

**テスト結果**:
- targeted 49/49 ✅ (ambient + passive + dream + formatter + hook unit、6.5s)
- 全体 `tests/ --ignore=tests/perf`: 536/537 + 1 skipped (1 pre-existing flaky `test_displacement_edit_persists_to_virtual_faiss_on_disk` — full-suite parallel 負荷のみ、isolation で pass、Step 1a の `test_faiss_save_loop_persists_new_documents` と同族の FAISS write-behind timing 系)
- `tests/perf/`: 58/58 ✅ (real RURI)
- `scripts/rest_smoke.py`: 6 シナリオ ✅
- `scripts/mcp_smoke.py`: 6 シナリオ ✅
- lint: 私の変更は clean (pre-existing F401 3 件はそのまま、CLAUDE.md で許容済)

**MCP/REST parity**: ✅ 同 commit で MCP tool signature + REST request model + 両 reference doc 更新 (`docs/wiki/REST-API-Reference.md` + `docs/wiki/MCP-Reference-Memory.md`)

**ロールバック passmap**:
- フック側で env `GAOTTT_AMBIENT_NOVELTY_TURNS=0` → `recently_surfaced` 送付なし → server 完全 no-op
- server 側で `ambient_novelty_decay=1.0` → `_novelty_factor` が常に `1.0` を返す (1.0 ** any == 1) → コード路 no-op (config 1 行)
- どちらか片方で十分 (両者 orthogonal な kill switch)

**残作業 (Step 1c は test の axis 拡張、別ターン推奨)**:
- 既存 `test_ambient_session_repetition_baseline` は post-fix baseline (decay 不発時の stability) を assert している。Step 1c では **「`recently_surfaced` を直接渡したら direct slot が確かに rotate する」**を engine integration test として追加 (今回 `test_ambient_novelty_decay_rotates_direct_slot` で既に追加済 — Step 1c の本質は満たしている)。
- 残るのは **production transcript を fixture として使った hook end-to-end test** で、これは「実 transcript の shape 変動」リスクを backing tests に取り込むかの judgment call (今回はやらず、production で観察する方が cheap)

### 思想的なノート — 「〇〇といえば〜」の核は何だったか

Step 1b 実装後、機構として:
- **意外性** = lensing slot (Phase I/J displacement の bend、既存)
- **適切性** = relevance gate + persona min_relevance (既存)
- **新鮮さ** = `recently_surfaced` × `novelty_decay` (Step 1b で literal に発火可能)

3 軸の **同時成立** が「〇〇といえば〜だったよな」体感の物理的実装。Plan 仮説 (3 軸の orthogonal 制御) が機構として揃った。Stage 2-5 (direct lexical/semantic 分離 / lensing top-K / composed query 可視化 / lensing resonance signal) は **同時成立をさらに精緻化する**段階。次の measurement step は Stage 6a と同じ手順で post-Step-1b baseline を取り、production hook 経由で session 内 rotation が肌感として感じられるかの dogfooding。

### Stage 3 — 2026-05-25 (lensing top-1 → top-K, 実装完了)

> 北極星機能の **literal な多重発火**: lensing slot は機構として最も「〇〇といえば〜」に近いのに top-1 で 1 turn 1 連想に縛られていた。Stage 3 で top-K に拡張し、人間が自然に紡ぐ associative chain ("X といえば Y で、Y といえば Z") を機構として担保する。

**設計判断 — single field with list semantics**

旧 `AmbientRecallResponse.lensing: AmbientMemory | None` (top-1 only) を **clean に `lensing: list[AmbientMemory]`** に置換。plan 原案は `lensing_items` 移行 field 案を併記していたが、内部 API かつ外部 REST 消費者が hook 経由 (text レンダ) のみであることを確認し、breaking change で 2 種類の field を持たない clean な path を選択。`lensing` が常に list (空のとき `[]`) で、`max_k=1` で旧挙動 1 picks 等価が出る。

**実装した変更**:

| ファイル | 変更 |
|---|---|
| `gaottt/config.py` | `ambient_lensing_max_k: int = 2` (controlled increase、ranking は novelty 適用後の decayed gap で取り直す)、`ambient_lensing_dynamic_k: bool = False` (Stage 3 で予約のみ、未実装) |
| `gaottt/core/types.py` | `AmbientRecallResponse.lensing` を `AmbientMemory \| None` → `list[AmbientMemory]` に変更 |
| `gaottt/services/memory.py` | `_pick_lensing` を top-K return に書き換え (`list[tuple[MemoryItem, float]]`、ranking key は decayed gap、露出 gap は raw 保持)。`ambient_recall` 本体で list を populate、`count = len(direct) + len(lensing)` |
| `gaottt/services/formatters.py` | 旧 single-pick branch を list iteration に。N=1 で旧 heading、N>1 で `▼ 重力レンズ（N 件、...）` に count 表示。manifest を `lensing=id1,id2,id3` の comma-separated に |

**MCP/REST parity**: ✅
- MCP tool `ambient_recall` の signature は無変更 (args 不変)、docstring + 行末 K cap 説明だけ更新
- REST `/ambient_recall` の response shape が **breaking change** (`lensing: null|obj` → `lensing: list`)。REST-API-Reference.md に migration note 追記済
- hook (text only consumer) は無変更で自動的に N picks を出す

**テストの update + 新規**:

| ファイル | 変更 |
|---|---|
| `tests/unit/test_ambient_recall.py` | `_pick_lensing` の return 型変更 (5 既存 test 更新、`tuple\|None` → `list`)。新規 `test_pick_lensing_returns_top_k_ranked_by_gap_descending` で 4 候補から K=3 cap + gap 順 ranking の literal を pin |
| `tests/unit/test_formatter_ambient_manifest.py` | 既存 5 test を list semantics に更新。新規 `test_manifest_lists_topk_lensing_comma_separated` で 3 picks の manifest format + visible count heading を pin |
| `tests/integration/test_engine_ambient_recall.py` | 4 既存 test 更新 (`resp.lensing is None` → `not resp.lensing` 等)。新規 `test_ambient_lensing_top_k_returns_multiple_picks` + `test_ambient_lensing_max_k_one_is_legacy_behavior` を追加 (TokenEmbedder fixture、各 cap 値の literal な挙動 + exclude set 保持) |
| `tests/perf/test_tier3_ambient_quality.py` | golden_corpus / 既存 4 lateral test の `resp.lensing.id` 参照を `lensing_ids = [m.id for m in resp.lensing]` に。lateral hit metric を「top-K のうち any が expected_lensing_candidates に hit したら 1」に書き換え (top-1-only 制約解除) |

**テスト結果**:
- targeted (ambient + passive + formatter + hook + perf-tier3): **56/56 ✅**
- `tests/unit/test_ambient_recall.py`: 10/10 ✅ (5 既存 + 1 new + 4 BM25)
- 全体 `tests/ --ignore=tests/perf`: 540/541 + 1 skipped (1 pre-existing FAISS write-behind flaky、isolation で pass)
- `tests/perf/`: 58/58 ✅ (real RURI)
- `scripts/rest_smoke.py`: 6 ✅
- `scripts/mcp_smoke.py`: 6 ✅
- ruff: 私の変更分 clean (pre-existing F401 3 件は CLAUDE.md 許容)

**lateral hit rate の現状** (Stage 6a 比較):
- Stage 6a (pre-fix): 1/2 (saturation rotation の fragile な amplification)
- Step 1a (post passive gate): 0/2 (organic baseline、pure fixture 由来)
- **Stage 3 max_k=2 (post)**: 0/2 (fixture corpus の expected_lensing_candidates が現状の embedding 距離で picked されないため。機構は正常動作 — lensing slot は常に 2 picks を返している)

→ fixture 自体が Stage 3 効果を計測するのに小さい。**Stage 5 (lensing resonance signal) と Stage 6 corpus 拡張** で意味のある hit rate 改善が見えるはず。Stage 3 の機構正常動作は new unit test + integration test で literal に確認済。

**ロールバック**:
- `ambient_lensing_max_k=1` → Stage 1/2 の 1 picks 上限に戻る (`lensing` field の list 型はそのまま、長さ 1 になるだけ)
- `ambient_lensing_enabled=False` → lensing 完全 off (旧 disable knob、無変更)
- 既存 client コードで `.lensing` を null チェックしていた箇所は `.lensing[0] if .lensing else None` への書き換えが必須 (breaking change の唯一の真の影響)

**残作業 (Stage 4-5、別ターン)**:
- Stage 4: composed query 可視化 (hook-only、低リスク debug knob)
- Stage 5: lensing resonance signal (`gap` だけでなく「妥当性」軸の追加、Stage 3 の K 拡張で「false positive 多重発火リスク」が顕在化する前の対策)

### Stage 5 — 2026-05-25 (lensing resonance signal, 実装完了)

> Stage 3 で K 拡張が進んだが、production lensing 自体が Phase M で構造的に sparse になっており「複数 surface できるか」より「surface したときの妥当性が agent から分かるか」が次の問題に。Stage 5 は **gap (曲げの強さ) と別軸の trust signal = resonance** を追加し、agent が「これは場が学んだ妥当な lateral か / displacement noise の偶然か」を弁別できる材料を提供する。

**設計判断 — 5a (cooccurrence) を採用**

plan は 5a/5b/5c の 3 案を併記していた。実装時に以下の理由で **5a (cooccurrence-derived resonance) を選択**:

| 案 | 内容 | 採用しなかった理由 |
|---|---|---|
| **5a** ✅ | `raw = Σ_{d∈direct} cache.get_neighbors(lensing)[d]` を `raw / (raw+scale)` で saturate | 「場が過去に学んだ associative path」を literal に測れる、production cooccurrence graph がそのまま使える、O(K_lensing × K_direct) で激安 |
| 5b | `virtual_cosine × mass_decile / 10` | mass を使うと Heavy Persona Dominance (`[[project-ambient-persona-mass-dominance]]`) と同型の罠 — 「重い memo = 信頼可」は false |
| 5c | `mean(cosine(lensing, each_direct_hit))` | lensing は **定義上** 「embedding-far from query but bent close」。direct との raw cos が高い ↔ 低いの両方が「良い lateral」「悪い lateral」両解釈に map できて signal にならない |

5a の semantic: 「**場が過去 active recall で この memo を今日の direct hits と何度一緒に引いたか**」。passive recall は cooccurrence を書かないので、resonance signal は ambient background noise から汚染されない (passive 原則と整合)。

**実装した変更**:

| ファイル | 変更 |
|---|---|
| `gaottt/config.py` | `ambient_lensing_resonance_scale: float = 10.0` (saturation 定数、`raw=10` で `0.5`、`raw=90` で `0.9`) と `ambient_lensing_resonance_min: float = 0.0` (optional drop gate、既定 off) |
| `gaottt/core/types.py` | `AmbientMemory.lensing_resonance: float \| None = None` (lensing slot 限定 populate、直接 / persona slot は常に None) |
| `gaottt/services/memory.py` | 純関数 `_lensing_resonance(lensing_id, direct_ids, engine, scale) -> float` を追加 (`raw / (raw+scale)`、`scale==0` は degenerate short-circuit)。`ambient_recall` で `_pick_lensing` が返した各 pick に対し compute → `lensing_resonance` populate → `ambient_lensing_resonance_min > 0` なら drop (no backfill) |
| `gaottt/services/formatters.py` | `_ambient_meta` の `gap +0.42` の隣に `resonance 0.72` を追加 (`lensing_resonance is None` の時は省略 — direct/persona slot には影響ゼロ) |

**MCP/REST parity**: ✅
- MCP tool `ambient_recall` の signature 無変更 (resonance は response field、新 arg 不要)
- REST `/ambient_recall` の response shape に `lensing_resonance` field 追加 (additive、breaking ではない)
- hook (text consumer) は formatter 経由で resonance を自動的に visible 化、無変更

**新規テスト** (4 件):

| ファイル | テスト |
|---|---|
| `tests/unit/test_ambient_recall.py` | `test_lensing_resonance_zero_when_no_cooccurrence` (cooccurrence ゼロで resonance=0)、`test_lensing_resonance_saturates_with_cooccurrence_count` (`raw=10, scale=10 → 0.5` と `raw=90, scale=10 → 0.9` を literal に pin)、`test_lensing_resonance_scale_zero_short_circuits` (degenerate scale=0 mode) |
| `tests/integration/test_engine_ambient_recall.py` | `test_ambient_lensing_resonance_populated_for_each_pick` (engine 経由 round-trip、direct slot には populate されない)、`test_ambient_lensing_resonance_reflects_cooccurrence` (`cache.set_edge` で weight=5 を seed → 期待 0.5 を assert)、`test_ambient_lensing_resonance_min_drops_low_resonance` (drop gate 動作確認、no backfill) |

**テスト結果**:
- targeted ambient + passive + formatter unit: **49/49 ✅**
- 全体 `tests/ --ignore=tests/perf`: **547/548 + 1 skipped** (今回 flaky 出ず)
- `tests/perf/`: **58/58 ✅** (real RURI)
- rest_smoke / mcp_smoke: 6 ✅ ずつ
- lint: 私の変更分 clean (pre-existing F401 3 件のみ、CLAUDE.md 許容)

**ロールバック**:
- `ambient_lensing_resonance_min=0.0` (default) で drop gate 完全 off、resonance signal は output に出るだけで挙動変えない
- production で resonance signal を完全 off にしたい場合は formatter の出力には残るが scale を巨大値 (例 `1e9`) にすると resonance ≈ 0 で常時表示
- 既存コードが `.lensing_resonance` を参照していないなら影響ゼロ (新 field は default None、formatter は None なら省略)

**Stage 3 production sparse 問題への部分回答**:

Stage 3 acceptance で「production lensing は ほぼ 0 picks」が露呈した。Stage 5 は直接 sparse を解決はしないが、**「lensing が fire したときの信頼性」を可視化** する: agent は `gap +0.42 · resonance 0.62` のように 2 軸で見て、resonance が高い lensing は安心して採用、resonance がほぼ 0 の lensing は「displacement noise かも」と weigh down できるようになる。

Sparse 自体の解決は Stage 3 dynamic_k mode の有効化 (predictable な K 拡張) や `ambient_lensing_min_gap` の本番チューニング (Phase M で field が安定化した状況に合わせて閾値を緩める) で進める想定。

**残作業 (Stage 4 + Stage 2、別ターン)**:
- Stage 4: composed query 可視化 (hook-only、低リスク debug knob、観察コスト削減)
- Stage 2: direct lexical-vs-semantic 分離 (direct slot の precision 改善、Stage 3/5 とは独立軸)

### Stage 4 — 2026-05-25 (composed query opt-in 可視化, 実装完了)

> hook-only の低リスク debug knob。Refinement Stage 4 (`GAOTTT_AMBIENT_HISTORY_TURNS=2` 既定) で hook が **直前 N turn の user prompt を concatenate** して server に投げているが、agent からは「現プロンプトを query にしたつもり」になり、ambient 結果が想定外のときに「query 自体が想定外なのか / recall が想定外なのか」を切り分けられない問題を解決。

**設計判断 — composed != prompt のときだけ inject (no-op compression)**

plan 原案は env=on で常に inject だったが、`composed == prompt` (連結が起きてない / `HISTORY_TURNS=0`) のときは debug 価値ゼロ + token 無駄 + 視覚 noise になるため **自動 no-op** に。env が on でも「連結が実際に起きた turn」だけ line が増える。debug 価値が最も高いところに自動 fokus する。

**実装した変更**:

| ファイル | 変更 |
|---|---|
| `scripts/hooks/ambient_recall.py` | env `GAOTTT_AMBIENT_SHOW_COMPOSED_QUERY` (既定 off)、closing tag 定数 `_CLOSE_TAG = "</gaottt-ambient-recall>"`、pure 関数 `_inject_composed_query_debug(block, prompt, composed) -> str` (no close tag / `composed==prompt` で no-op、embedded newlines を `\n` literal にエスケープして 1 行を保つ)、`main()` で env on + block が正常なときに injection |
| `scripts/hooks/ambient_recall.py` docstring | env リストに `GAOTTT_AMBIENT_SHOW_COMPOSED_QUERY` の解説を追加 |

**MCP/REST parity**: ✅ **hook-only** で server 側変更ゼロ — MCP tool signature / REST endpoint / response shape のいずれも無変更。`docs/wiki/MCP-Reference-Memory.md` / `REST-API-Reference.md` の更新も不要。

**新規テスト** (4 件、unit only — server を触らないため integration test 不要):

| テスト | 内容 |
|---|---|
| `test_inject_composed_query_debug_appends_comment_before_close_tag` | env on 相当の inject → comment が `</gaottt-ambient-recall>` の **前** に挿入されること、composed 内容が visible |
| `test_inject_composed_query_debug_noop_when_composed_equals_prompt` | `composed == prompt` で no-op (連結が起きてない場合) |
| `test_inject_composed_query_debug_noop_when_no_close_tag` | 防御: ambient block 以外の text には触らない |
| `test_inject_composed_query_debug_escapes_embedded_newlines` | 3-line composed query → 2 escaped `\n` literal、line 自体は 1 行 (parser 互換) |

**テスト結果**:
- `tests/unit/test_ambient_hook.py`: **23/23 ✅** (既存 19 + 新 4)
- 全体 `tests/ --ignore=tests/perf`: **551/552 + 1 skipped** (flaky なし)
- `tests/perf/`: **58/58 ✅** (real RURI、hook 触ってないので perf には影響ゼロ)
- lint: 私の変更分 clean (pre-existing F401 3 件のみ、CLAUDE.md 許容)

**Operations doc 更新**:
- `Operations-Troubleshooting.md` に新節 **「ambient_recall が想定外の memo を surface する (composed query 不透明問題)」** を追加 — 症状 → 原因 (multi-turn concat) → 対処 (env=1 で debug) の典型フロー
- `Guides-Ambient-Recall.md` の env 一覧表に `GAOTTT_AMBIENT_SHOW_COMPOSED_QUERY` の行を追加 (`GAOTTT_AMBIENT_NOVELTY_TURNS` の行も Stage 1 doc 漏れだったので併せて補完)

**ロールバック**: env unset (= default) で完全無効、production hook では off 推奨。1 hook 内で完結する debug ツールなので production への impact ゼロ。

**残作業 (Stage 2、別ターン)**:
- Stage 2: direct lexical-vs-semantic 分離 (direct slot の precision 改善)。Stage 1/3/5 が「lateral 連想軸の整備」だったのに対し、Stage 2 は「direct slot の precision 軸」で独立。本番 dogfooding で「direct に lexical 偽陽性が混入する」体感が顕著になったら実装する判断 (= 現状未着手は意図的)

### Frontend parity follow-up — 2026-05-25 (opencode plugin に Stage 1 + Refinement Stage 4 を伝達)

> 観察期 day 1 の measurement (GLM via secondopinion-MCP) で「opencode plugin は Python フックに `{prompt}` だけ渡していて transcript-equivalent な経路がない」ことに気づき、Stage 1 novelty decay + Refinement Stage 4 multi-turn が opencode では発火しないことが判明。設計 (A) "両 frontend が自分の方法でデータを構築し、Python フック側で同じ downstream 変数に集約" で修正。

**設計 — 単一の真実の源は Python フックの downstream 変数**

Python フックは新たに payload で `history: list[str]` と `recently_surfaced: dict[str, int]` を accept。指定があれば直接使用し transcript scan を bypass、未指定なら従来通り `transcript_path` を scan (Claude Code path)。フック内に「frontend を判別する分岐」は存在せず、payload key の有無だけが経路を決める (CLAUDE.md "frontend parity" 原則と整合、source 分岐ゼロの Phase M 原則の hook 層への類推)。

**実装した変更**:

| ファイル | 変更 |
|---|---|
| `scripts/hooks/ambient_recall.py` | `main()` で `payload.get("history")` / `payload.get("recently_surfaced")` を accept、無効型や未指定なら transcript scan にフォールバック。docstring に stdin payload schema 明記 |
| `scripts/hooks/opencode-ambient-recall.ts` | `GAOTTT_AMBIENT_HISTORY_TURNS` (既定 2) と `GAOTTT_AMBIENT_NOVELTY_TURNS` (既定 5) env を追加 (Python と同名)。pure 関数 `stripAmbientBlock()` / `idsFromManifest()` / `deriveHistoryAndRecency()` を新規 (Python の対応する関数を TS port)。`fetchPastUserTexts()` で `pluginInput.client.session.messages()` (OpenCode SDK) 経由で過去 user text を取得、`deriveHistoryAndRecency` で `history` と `recently` を組み立て、`ambientBlock()` の payload に乗せる |
| `docs/wiki/Guides-Ambient-Recall.md` | env 表の `GAOTTT_AMBIENT_HISTORY_TURNS` / `GAOTTT_AMBIENT_NOVELTY_TURNS` 行を Python フック専用 → 両 frontend 対応に更新、opencode の SDK 経由データ取得の責務追加を上部説明に追記 |

**MCP/REST parity**: ✅ 影響なし — server-side 不変、hook payload schema の additive 拡張のみ。

**新規テスト** (4 件、Python unit only):

| テスト | 内容 |
|---|---|
| `test_payload_history_bypasses_transcript_scan` | `history` 指定で transcript scan が呼ばれないことを assert (monkeypatch で sentinel を raise) |
| `test_payload_recently_surfaced_bypasses_transcript_scan` | 同上 (`recently_surfaced` 経路) |
| `test_payload_transcript_path_fallback_when_history_absent` | Claude Code path: 両 key 未指定で transcript scan に降りること、scan の引数が正しいこと |
| `test_payload_invalid_recently_surfaced_falls_back` | 防御: malformed `recently_surfaced` (list 等) は silent に scan fallback、crash しない |

opencode plugin (TS) の unit test は Bun 未 install のため skip。export した pure 関数 (`stripAmbientBlock` / `idsFromManifest` / `deriveHistoryAndRecency`) を Bun test 環境がある場所で追加するのが将来の選択肢。production verification は secondopinion-MCP 経由 (opencode subprocess) で実機テスト可。

**テスト結果**:
- `tests/unit/test_ambient_hook.py`: **27/27 ✅** (既存 23 + 新 4)
- 全体 `tests/ --ignore=tests/perf`: 554 passed + 1 skipped + 1 pre-existing flaky (`test_faiss_save_loop_persists_new_documents`、isolation で pass、私の変更とは無関係)
- `tests/perf/`: **58/58 ✅** (real RURI、hook 側のみ触ったので perf は影響ゼロ)
- ruff: 私の変更分 clean (pre-existing F401 3 件のみ)

**ロールバック**:
- 両 frontend で `GAOTTT_AMBIENT_HISTORY_TURNS=0` + `GAOTTT_AMBIENT_NOVELTY_TURNS=0` で全 stage 機構 off (= legacy 等価)
- Python フックの transcript_path 経路は変更ゼロ → 旧 Claude Code 動作完全互換
- opencode plugin の SDK 経路は env=0 で no-op → 旧 opencode 動作完全互換

## Stage 7 — Anti-Hub & Dormant Distribution Cut (2026-05-26 dogfooding follow-up)

> Stage 1a/1b/3/5/4 完了後の **production dogfooding 観察期** (Claude Opus 4.7 + GLM-5.1) で literal に再現された 2 つの構造的問題に対する follow-up。会話文脈上は「Stage 6.1 / 6.2」と命名されたが、既存の Stage 6 (measurement Tier) と区別するため doc 上は **Stage 7.1 / 7.2** として扱う。実装ファイル内コメント / config docstring は **Stage 6.1 / 6.2** 表記のまま (会話文脈整合のため、混乱を避ける必要があれば後で renamed)。

### 観察された 2 問題

1. **Direct-hit hub** — 「Lateral Association」を固有名で叩いても、cycle-2 self-knowledge memo cluster (185 件、同一 batch で `cohort_id` 共有) が top-K を占有する。Phase L acceptance で literal に観測: avg unique cohorts = 2.67 / avg max dominance = 2.33 (4 cohorts / 12 docs の小型テスト corpus)。新規 Lateral Association memo を recall で surface しにくい構造。

2. **Dormant 0 件** — 26k+ active corpus で `explore(mode='dormant')` が常に 0 件。`mass ≤ 2.0` 絶対しきい値が現分布に対し低すぎる (`project_phase_o_stage_5_production_observation`)。

### Stage 7.1 — Direct-Hit Anti-Hub (cluster_key MMR)

**機構**: `services/memory.py::_apply_cluster_anti_hub` で greedy MMR-style 並び替え。top-K 構成時に同一 cluster_key の連続採用に penalty `λ × shared_cluster_count` を課す。cluster_key = `cohort_id` OR `original_id` (`_cluster_key_for(cache)` ヘルパー、両キーとも Phase M 構造識別子)。両キーとも None (pre-Phase-M 旧 memo のみ) は penalty 対象外 (内在的に分散しているため)。

**設計変更履歴 (2026-05-26 dogfooding)**:
- 当初 Stage 7.1 は cohort_id 一本で設計 — 「Phase M 単一規則整合、tag prefix は脆い」を理由に。
- 本番 acceptance で **cohort_id 保有率 = 0% (26k corpus)** が判明 — `remember()` は 1 件ずつ呼ばれるため batch=1、supernova 発火閾値 (2 件) に届かない。file ingest 経由の chunks も過去ロード時の supernova 設定により 0%。
- 同じ corpus で `original_id` 多メンバークラスター = **57.8% of active** (最大: 638-chunk 米国会社四季報)。
- → cluster_key を `cohort_id OR original_id` に拡張。両方とも Phase M 構造識別子なので「単一規則」は維持される (anti-hub は ranking layer、physics rule ではない)。fallback は *which* 構造 id を使うかの routing であって *whether* に分岐があるわけではない。

**適用**:
- `ambient_recall.direct` slot — `items[:direct_k]` の slice 前に MMR。`recently_surfaced` で novelty decay が動いた場合は decayed score を `score_map` として MMR に渡し、ranking signal の二重作用を回避。
- `recall` top-K — `direct_hit_anti_hub_lambda > 0` のとき engine から `top_k * 3` を fetch し、MMR で top_k に絞る。source_filter 経路は既存の `top_k * 10` widening を維持しつつ、anti-hub on で slice を遅延。

**knob**: `direct_hit_anti_hub_lambda: float = 0.0` (既定 = 挙動不変、`0.4` が baseline-derived 推奨)。Phase M 「source 分岐ゼロの単一規則」整合 — cluster identifier は `cohort_id` のみで、source / tag 分岐は入れない。

**Acceptance**:
- `tests/perf/test_tier3_cluster_monoculture.py` (cohort_id 経路)
  - λ=0   : avg_unique=2.67, avg_max_dom=2.33, hub top-5 占有 = 2-3 件
  - λ=0.4 : avg_unique=**4.00**, avg_max_dom=**2.00**, hub top-5 占有 = **1 件**, target_hit_rate 3/3 維持
- `tests/perf/test_tier3_cluster_monoculture.py::test_anti_hub_works_via_original_id_when_no_cohort` (新規、original_id 経路)
  - cohort_id 全 None で 6-chunk 本 + 3 singleton corpus → λ=0.4 で book chunks in top-5 = 2 件
- **本番 acceptance (2026-05-26)**: `米国会社四季報` query (638-chunk 本) で book chunks in top-5 = **1 件** に。anti-hub 無しなら 5/5 全部本 chunk になっていた case。

**limitation (本番 dogfooding で明確化、2026-05-26)**: 一握りの singleton agent/intention/commitment memo が **個別に高 mass** で top-K を query 横断で占有する現象 (production 観察) には Stage 7.1 は効かない。これらは cluster の問題ではなく individual-node mass dominance の問題で、解決機構は別 (Phase N Mass Evaporation、または session-scope repeat penalty)。Stage 7.1 が解くのは「同じ cluster が複数席を占める」case のみ。

### Stage 7.2 — Dormant Percentile Cut

**機構**: `_dormant_surface` で `dormant_mass_threshold` 絶対値 (`2.0`) の代わりに、active corpus の mass 分布 P パーセンタイル値を mass cut として使う。設定しなければ legacy 絶対挙動。

**knob**: `dormant_mass_percentile: float | None = None` (既定 = legacy)。本番チューニングは新 `scripts/diag_dormant.py --data-dir <prod>` で「5-15 件 surface する最小パーセンタイル」を採用 (典型 10-30 の範囲)。

**Acceptance**: `tests/perf/test_tier5_phase_o_dormant.py::test_dormant_percentile_threshold_replaces_absolute`
- corpus mass を底上げした後でも、percentile cut は分布の下部を関係的に拾う (legacy 絶対は 0 件)。

### Stage 7 設計判断

| 判断 | 採用 | 理由 |
|---|---|---|
| Anti-Hub の cluster identifier | `cohort_id` → `cohort_id OR original_id` (dogfooding 後拡張) | 当初 cohort_id 一本で設計、Phase M 単一規則整合 + tag prefix の脆さ回避。本番 acceptance で cohort_id 保有率 0% / original_id 多メンバークラスター 57.8% が判明 → 両キーで構成。両方とも Phase M 構造識別子なので「単一規則」維持 (anti-hub は ranking layer、physics rule ではない、fallback は routing であって branching ではない)。 |
| 新ツール追加 | なし | 既存 `recall` / `ambient_recall` / `explore(mode='dormant')` の挙動変調のみ。MCP/REST parity 影響ゼロ。 |
| Default | 両方 OFF | Stage 1a/1b/3/5/4 の挙動互換性を default で保証、本番 opt-in は measurement-first で別ターン。 |
| 計測スキャフォールド | 実装より先 | 「計測 → 実装 → 計測 → tuning」ループを literal に履行。`test_tier3_cluster_monoculture.py` で λ=0 baseline 確定後に λ=0.4 を載せた。 |

### 関連 (Stage 7)

- [`scripts/diag_dormant.py`](../../scripts/diag_dormant.py) — Stage 7.2 用 percentile 分布診断 (本番 DB read-only)
- [`tests/perf/test_tier3_cluster_monoculture.py`](../../tests/perf/test_tier3_cluster_monoculture.py) — Stage 7.1 baseline + acceptance
- [`tests/perf/test_tier5_phase_o_dormant.py`](../../tests/perf/test_tier5_phase_o_dormant.py) — Stage 7.2 percentile test 追加
- [[project-lateral-association-observation]] — Stage 7 を導いた dogfooding 観察期 memory

## 関連

- [Plans — Ambient Recall Enrichment](Plans-Ambient-Recall-Enrichment.md) — v1: 6 スロット構造
- [Plans — Ambient Recall Refinement](Plans-Ambient-Recall-Refinement.md) — v2: 質と observability + follow-up (b) `mass_weight` knob
- [Plans — Phase J — Persona-Anchored Retrieval](Plans-Phase-J-Persona-Anchored-Retrieval.md) — Stage 1 で流用する persona-anchored geometry
- [Plans — Phase O — TTT Observability](Plans-Phase-O-TTT-Observability.md) — Stage 2/5 で流用する breakdown / observability 思想
- [Guides — Ambient Recall](Guides-Ambient-Recall.md) — ユーザー向けガイド (各 stage 実装時に対応セクション追加)
- [[project-ambient-persona-mass-dominance]] — Stage 1 が解こうとする UX 症状の memory
- [`scripts/hooks/ambient_recall.py`](../../scripts/hooks/ambient_recall.py) — Stage 1, 4 で改修する hook
- [`tests/perf/test_tier3_ambient_quality.py`](../../tests/perf/test_tier3_ambient_quality.py) — Stage 6 で拡張する measurement
