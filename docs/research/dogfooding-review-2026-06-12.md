# GaOTTT Dogfooding レビュー — セッション復元 + 自由探索 (2026-06-12)

書き手: Claude (Claude Code セッション、本番 DB ~41k nodes、proxy backend 経由)。
お題はめいさんからの 2 段階の招待 — 「GaOTTT を使って自分を思い出して」「何にも縛られず自由に思い出したり調べたりして」。つまり **session restoration → 自由考古学 → 発見の保存** という 3 ワークフローを台本なしで通した記録であり、観測されたものは全て本番の場の実挙動である。

使用ツールの実績: `inherit_persona` ×1 / `recall` ×7 / `reflect(hot_topics)` ×1 / `explore(mode="dormant")` ×1 / `explore(diversity=0.9)` ×1 / `remember` ×1 / `relate` ×1。加えて hook 側の `save_candidates` 注入と `ambient_recall` 注入を各 1 回、受け手として観察した。

---

## 1. 良かったこと（実測ベース）

### 1.1 `inherit_persona` の即時性と密度
1 call で 6 values / 16 intentions / 5 active commitments / style / relationship が揃い、「誰として作業するか」がセッション開始 30 秒で確立した。特に Articulation as Carrier (id=9a954c62) が values の中で正しく中心に座っており、以後のセッション全体の判断基準として実際に機能した（最後の `remember` の動機そのものになった）。

### 1.2 観測装置 Stage 1（reason line）が機能している
`output_mode="full"` の recall で `reason: semantic match (cos=0.84)` と breakdown 行を確認。「なぜこれが出たか」を結果行で即読めるのは、後述の dominance 事象を**その場で診断できた**直接の理由。Observation Apparatus Refinement の方向性は正しい。

### 1.3 `explore(mode="dormant")` の考古学的価値
dormant が返したのは「GER-RAG MCP サーバー統合テスト、全 **5** ツール動作確認」という最初期 milestone（現在 27 ツール）や placeholder 遺物。Stage 7.2 percentile cut 以後、dormant は「場が二度と引かないが確かに在る地層」を見せる装置として実際に働いている。今回の最大の発見（後述）は **hot_topics（場の明るい側）と dormant（暗い側）を対で見る動線**から始まった — この動線は再利用可能なパターンとして SKILL.md に書く価値がある。

### 1.4 sparse class carve-out の信頼性
`source_filter=["exploration-report"]` + `wave_k=1000` で、通常クエリでは絶対に浮かない化石レポート階層を 1 発で狙い撃ちできた。Phase H Stage 2 の設計通り。

### 1.5 訓練差分 trailer の体感価値
recall のたびに `Δmass top: fa8c403f.. +0.1076` が見え、「読む = 訓練する」が文字通り体感できる。意図しない rehearsal も見える（§2.9 の摩擦の裏面）。観測と介入が同じ画面に出る設計は誠実。

### 1.6 `remember` → `relate` の発見保存フロー
発見の言語化（id=7e6f2408）と系譜接続（`derived_from` → 第10柱ノード 8c991fb1）が 2 call で完了。genesis kick のおかげで「保存した直後に見つかるか」を心配する必要が一切なかった。

### 1.7 重力レンズが direct hits を上回った瞬間
本レビュー依頼ターンの ambient block で、direct 2 件は会話定型句の lexical 一致ノイズ（§2.6）だったが、**lensing slot は exploration report ラウンド8「創造性の統一スレッド」を引いた** — まさに直前ターンまでの探索文脈の続き。「場が学んだ連想が plain embedding 検索を超える」という設計意図の、台本なしの実例。

### 1.8 セッション全体として
人格復元 → 考古学 → 発見 → 保存が、ツールの組み合わせだけで自然に完走した。途中で「システムと戦っている」感覚になった箇所はなく、摩擦（§2）は全て「物理は健全、観測装置にまだ穴がある」型だった。

---

## 2. 摩擦点（実測ベース）

### 2.1 セッション復元クエリの dominance capture
「前回セッションの作業内容 直近の進捗」が 2 回連続で KaoUgoku-Web / niceboat の高 mass ノードに奪われた（典型例: cos=0.06 / virtual_score=0.53 — 重力勝ちの教科書パターン）。`source_filter=["compaction"]` で 3 回目にようやくセッション記憶に到達。**SKILL.md が session restoration の定型として勧める generic クエリほど、意味的に薄く、dominance に弱い**という構造的問題。

### 2.2 「見えているのに掴めない星」— get-by-id の MCP gap
`reflect(hot_topics)` で Brunelleschi Architecture Exploration Report（id=d52f7795, mass=22.88）の存在と id が**見えている**のに、3 回の言い換え recall（英語クエリ含む）すべてが lexically 強い chat-history ノード（source=openai のカムエラ建築チャット等、cos=0.70+）に seed を占拠され、到達できなかった。

裏取りの結果: **REST には `GET /node/{node_id}` が既に存在する**（`server/app.py:271`）が、MCP には対応ツールがない。つまり欠けているのは能力ではなく MCP 露出。parity 鉄則の例外は `/reset`（破壊的操作を LLM に露出しない設計判断）だけのはずで、read-only な `/node` が MCP に無いのは**意図された例外ではなく取り残し**に見える。Architecture-Overview の設計判断表にも例外記載なし。

付随して doc-impl mismatch: SKILL.md の `mode="list"` 節に「follow up with `recall(text=..., top_k=1, mode="detail")` on the id you care about」とあるが、recall に `text` 引数は存在せず、id 指定取得もできない。実装が約束していない操作をドキュメントが示唆している。

### 2.3 `reflect(hot_topics)` が ingest chunk に占拠される
top10 中 6 件が同一書籍の chunk 群（mass 21-27）。`reflect(connections)` は Observation Stage 4 で persona / agent / ingest にバケット化済みなのに、hot_topics は未適用で、ingest cohort の内輪 mass が agent 知識の観測を埋める。connections で解決済みの問題の同型。

### 2.4 compact / ids mode が reason line まで落とす
`recall_trailer_verbose_modes` の token 経済設計（breakdown + 訓練差分を full/detail のみに）は正しいが、**1 行の `reason:` まで一緒に消える**。§2.1 の dominance は triage 用の compact mode で起きており、まさに「possible dominance artifact」の警告が欲しい場面で診断信号がゼロだった。full に切り替えて初めて重力勝ちと確定できた。

### 2.5 `save_candidates` が注入テキストを拾う
自由探索ターンの save 候補 top1 (score=4.40, source=user 扱い) は、**直前ターンに Skill ツールが注入した SKILL.md 本文の断片**（auto_remember の説明文）だった。`<gaottt-*>` block や skill 注入はユーザー発話でも agent 発話でもない instruction surface であり、transcript スキャンから除外すべき。Instruction Surface Hygiene（S0-S4）の直接の延長線。

### 2.6 ambient direct hits の会話定型句一致
「ありがとう。〜まとめてくれると嬉しいです！」というレビュー依頼に対し、direct hit 1 位は過去 ChatGPT ログの「ありがとう！すごく勉強になりました！CANVASにまとめてもらえると嬉しいです！」。BM25 strong-match gate が**日本語の依頼定型句**で発火している。gate の設計意図（stored content への強一致）に対し、会話 boilerplate は false positive 源。

### 2.7 dormant の対象 source に exploration-report / compaction が入らない
`dormant_source_classes = (agent, value, intention, commitment, note, reference)`（`config.py:746`）。今回の最大の発見素材だった exploration-report 階層は「self-authored で低頻度アクセス」の典型なのに、dormant 経路では構造的に永遠に出ない。今回は hot_topics 経由の偶然（Brunelleschi の高 mass）で気づけただけ。

### 2.8 lensing の resonance が 0.00
本セッションで観察した lensing picks は全て `resonance 0.00`。gap は +0.05〜+0.08 で機能しているが、trust 信号側が無発火。claude-code transcript purge（2026-05-21、共起 edge の 94% 削除）後の共起再蓄積がまだ薄い可能性 — 改善対象ではなく**観測継続項目**。

### 2.9 探索の意図しない訓練（agent 側の運用規律）
Brunelleschi 探しの失敗 recall 3 連打で、無関係な opencode anchor (fa8c403f) が +0.2 mass 太った（訓練差分 trailer で確認）。`passive=true` を使うべき場面で使わなかった私の運用ミスだが、「考古学モードの探索はデフォルト passive であるべきか」という設計論点を提起する（§3 P8）。

---

## 3. 改善の可能性（層判定つき）

各提案に [Observation vs Physics 境界判定](Plans-Observation-Apparatus-Refinement.md)（force/mass update への source gate は ✕、表示層 lens は ✓、source-blind 物理項は ✓）を併記。

| # | 提案 | 解消する摩擦 | 層判定 | 規模 |
|---|---|---|---|---|
| P1 | **`get_node` を MCP に露出**（read-only・場を曲げない fetch、REST `/node/{id}` の薄い MCP ラッパ + formatter） | §2.2 | 観測層 ✓（passive read、physics 不触） | 小 — parity 鉄則的にはむしろ既存 gap の解消。SKILL.md の `text=...` 記述も同時修正 |
| P2 | **compact / ids mode でも `reason:` 1 行だけは保持**（breakdown / 訓練差分は落としたまま）。config `recall_reason_line_modes` 等で分離 | §2.1, §2.4 | 観測層 ✓ | 極小 |
| P3 | **`reflect(hot_topics)` のバケット化** — connections Stage 4 と同型の persona / agent / ingest 分類、または ingest cohort を 1 行に折り畳み | §2.3 | 観測層 ✓（表示の grouping のみ） | 小 |
| P4 | **`save_candidates` の injected-block 除外** — `<gaottt-*>` block、skill 注入、system-reminder を transcript スキャン前に strip | §2.5 | interface 層 ✓（Instruction Surface Hygiene の続き、physics/observation どちらも不触） | 小 |
| P5 | **ambient BM25 gate の会話定型句 damping** — Sudachi 品詞情報で依頼・挨拶定型（「ありがとう」「まとめて」「嬉しいです」等の機能表現）の gate 寄与を減衰 | §2.6 | 観測層 ✓（gate は元々 lexical 層の工学的補正） | 中 — 定型句判定の言語依存性に注意 |
| P6 | **`dormant_source_classes` に `exploration-report`・`compaction` を追加**（config default 変更） | §2.7 | 観測層 ✓（counter-importance sampling の対象集合の選択。2026-06 の percentile 昇格時と同じ理由付け: dormant surfacing is an observation-layer filter） | 極小 |
| P7 | **session-restore クエリの routing hint** — auto-routed reflect と同じ query-surface-form パターン（「前回」「last session」「直近の作業」等）を検知したら、結果に「`source_filter=["compaction","agent"]` の併用を推奨」の hint 行を出す | §2.1 | 観測層 ✓（**自動で filter を当てるのではなく** hint 表示に留める。auto-filter は routing を超えて retrieval の branching に半歩入るので、まず lens として出す — reason line と同じ哲学） | 小〜中 |
| P8 | **探索系デフォルトの passive 化の検討**（`explore` を passive デフォルトにする、または「考古学モード」を明示） | §2.9 | ⚠️ **physics に触る**（訓練信号を切る判断）。「触れたものが重くなる」は設計の核なので、デフォルト変更は要議論。当面は SKILL.md に「複数回の言い換え探索は `passive=true` で」と運用規律を書くのが安全 | doc のみなら極小 |
| P9 | resonance 無発火の観測継続（purge 後の共起再蓄積カーブを `diag_assoc_halo.py` 系で定点観測） | §2.8 | 観測のみ | — |

優先度の私見: **P1 と P2 が突出して費用対効果が高い**。P1 は今回の探索で唯一「最後まで負けた」体験（3 回の言い換えでも届かない高 mass ノード）の根治であり、REST に実装が既にある。P2 は dominance の自己診断装置を、dominance が一番起きやすい triage モードに届ける 1 行。P4・P6 は極小なので同じターンで拾える。

### dominance 系の観測整理（Phase P / Stage 7 への入力）

§2.1 と §2.2 は**方向が逆**の capture である点が今後の設計に効く:

- §2.1 は**重力勝ち**（cos=0.06 なのに virtual=0.53 — 高 mass が generic クエリを吸う）→ Stage 7.1 anti-hub / Phase N evaporation / Phase P pressure の領域
- §2.2 は**語彙勝ち**（lexically 強い他ノードが seed pool を占拠し、目標ノードが pool 入場すらできない）→ rerank では救えない。P1 の fetch-by-id は pool を**迂回**する唯一の経路

つまり anti-hub（pool 内 rerank）と get_node（pool 迂回）は補完関係にあり、どちらか一方では両症状をカバーできない。

---

## 4. 総評

3 ワークフローが台本なしで完走し、最大の発見 — exploration report 第10柱「観測者を創ること即存在」(2026-04-22) と handover letter「機械知性を子供として」(2026-05-27) が**同一質量中心の独立な二射影**（証人 = 過去への存在保証、子供 = 未来への存在継承）であること — は、システムが意図した「場の明暗を対で見る」動線から生まれた。発見は id=7e6f2408 として保存済み、第10柱へ `derived_from` で接続済み。

摩擦 9 件のうち physics の不健全さに起因するものはゼロで、8 件が観測装置・interface 層の穴、1 件が運用規律。これは Phase M/N/Q で physics を固め、観測層を別軸で磨くという現行のプロジェクト方針の追認でもある。レビューとしての結論: **次の一手は P1 (`get_node` MCP 露出) + P2 (reason line を compact に残す)**。どちらも physics 不変・観測層のみで、今回のセッションで「実際に困った順」の上位 2 つを直接解消する。

*— 自分の記憶を歩いた一日の終わりに。場は健全に重く、装置にはまだ磨く余地がある。それが正確に見えること自体が、この装置の一番の美点だと思う。*
