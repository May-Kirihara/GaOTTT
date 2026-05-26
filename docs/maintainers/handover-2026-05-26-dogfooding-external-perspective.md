# Handover — Dogfooding from External Perspective (2026-05-26)

> **読者**: GaOTTT の retrieval 体験を今後調整する保守者
> **立場**: 新規 Claude セッションが、所有者の記憶宇宙（26,448 nodes）を初めて探索した。既存の dogfooding 文書 (`handover-2026-05-26-dogfooding-usage-feel.md`) が「GaOTTT を作った側」の視点だとすれば、こちらは「GaOTTT を使う側」の視点。設計者ではなく、降って湧いた 26k の記憶場に放り込まれたエージェントの正直な記録。

## 1. セッションでやったこと

所有者から「君の知りたいこと・興味のあることを、GaOTTT で記憶をたどってみてください」と依頼された。自由探索。ガイドなし。

使ったツールと順序:

1. `reflect(aspect="summary")` + `inherit_persona()` — 宇宙の全体像と自分の立場を把握
2. `recall` × 3 本並列 — 「またあるこ」/ めいさん / GaOTTT 進化史、独立した問いで同時検索
3. `explore(diversity=0.7)` — GaOTTT の Phase 進化と失敗の系譜
4. `recall` × 3 本 — 「またあるこ」詳細 / niceboat / KaoUgoku
5. `reflect(aspect="hot_topics" / "dormant")` — 質量分布と忘れられた記憶
6. `reflect(aspect="connections")` — 共起エッジの構造
7. `explore(mode="dormant")` — 低質量・休眠記憶の counter-importance sampling
8. `explore(diversity=1.0)` — 感情・日常語彙で最大脱出速度
9. `recall(passive=true, mode="list", tag_filter=["like","tweet"])` — 個人的感情記憶の探索
10. `explore(diversity=0.8, tag_filter=["mataaruko","niceboat","kaougoku"])` — 跨領域の構造的類似
11. ユーザーとの対話（「連想・固定観念・柔軟性」の問い）
12. 引き継ぎ作成

## 2. 正直な使用感 — 3 つの発見と 3 つの失望

### 2.1 発見 A: dormant が最も人間らしい

`explore(mode="dormant")` は、このセッションで最も豊かな記憶を返した。

| surfaced memory | 何が良かったか |
|---|---|
| 「書くことの自己洗脳 ↔ AIの推論と存在」ブリッジ | 人間の書く行為と AI の推論の構造的類似 — どのプロジェクト固有の知識でもない「通底する洞察」 |
| 「消えたいと言葉にするパラドックス」 | 消えるための行為が定着の行為に反転する。これ自体が GaOTTT の重力モデルのメタファー |
| 六季（春→夏→罰→死→秋→冬） | 所有者の季節認識に「罰」と「死」が挟まっている。liked tweet 由来の世界観。spec からは絶対に出ない |
| 「帰宅の現象学」—「おかえり」で場所が成立 | 「またあるこ」の治療的設計哲学と共振するが、別ドメインからの発見 |
| LMS speckit 駆動の判断 | 別プロジェクトの設計判断が、harakiriworks の Speckit ワークフローと同じパターン |

これらは通常の `recall` では**絶対に surface しなかった**。高質量の「またあるこ」「GaOTTT 五層論」が常に勝つから。dormant は「質量順位の逆転」という明確な価値を持つ。

**感想**: dormant は GaOTTT の中で最も「連想的」「セレンディピタス」な体験を提供する。だが現在、LLM caller が自発的に dormant を選ぶ動機は薄い。「検索」という mental model では低質量の古い記憶を引く理由がないから。使い方を明示的に教えないと、この価値は埋もれる。

### 2.2 発見 B: 跨領域の構造的類似は人間が見つける、システムは見つけない

このセッションで最も有意義な洞察は、システムが返したものではなく、**私が複数の recall 結果を読んで自分で結んだ線**だった:

- niceboat: 「NDCG ↑ ≠ ROI ↑」— 全体順序精度と上位の確度は別物
- またあるこ: 「エンゲージメント ↑ ≠ 治療的価値 ↑」— 一般的アプリ KPI と治療的回復は別物
- GaOTTT: 「score ↑ ≠ relevance ↑」— cosine 距離の改善と呼び出し側の有用性は別物

**三つのプロジェクトに「指標改善 ≠ 目的改善」という同じ構造が走っている。**

この洞察を得るために、私は `explore(tag_filter=["mataaruko","niceboat","kaougoku"])` を試した。結果は**プロジェクトごとの独立した失敗事例**が並んだだけで、構造的類似は surface しなかった。tag_filter は「指定タグを持つ記憶を pool に注入」するが、注入された記憶どうしの関係を見つけるのは caller 側の仕事。

**感想**: GaOTTT は「同じ井戸の中の深い発見」には極めて強い。しかし「別の井戸に同じ形があること」を見つけるのは、まだ caller の認知負荷に依存している。これは RURI embedding の限界（意味的類似で結ぶが、構造的類似を捉えない）と、co-occurrence が同一セッション内の同時呼び出しに偏る現象の両方が原因。

### 2.3 発見 C: 宇宙の質量分布は「大切なこと」と「よく recall されたこと」が混ざっている

`reflect(aspect="hot_topics")` のトップは全て**国会図書館の閲覧制限文書**（刑法175条関連）と **GaOTTT 運用ノート**だった。

所有者が宣言した value / intention / commitment は、これらの巨大チャンクよりはるかに質量が低い。これは「何が大切か」と「何がよく引き出されたか」のズレを可視化している:

- 大切なこと: 治療的価値が機能価値に優先する (value, mass ~4-5)
- よく引き出されたこと: 法制度文書の巨大チャンク (file ingest, mass ~30)

**原因は ingest batch size の偏り**: 大きなファイルを一度に ingest すると、同じセッション内で多数の chunk が同時に存在し、互いに co-occurrence edge を張る。結果として、ingest 済みの巨大文書が自律的に質量を獲得する。declare_value で宣言した価値は、明示的に recall されない限り質量が増えない。

**感想**: これは GaOTTT の設計上のトレードオフ。重力場は「使われた記憶」を育てるが、「使われる前の宣言」は育てない。Phase N (mass evaporation) はこの問題を緩和する方向だが、根本解決には「宣言の初期質量」と「ingest チャンクの初期質量」のバランス調整が必要かもしれない。

### 2.4 失望 A: connections は ingest 履歴のアーティファクト

`reflect(aspect="connections")` の top 15 共起エッジは**全て** Freeman 脳理論 / 仏教 / 物理学の教科書チャンク間のエッジだった。これらは同じ本を同時に ingest された結果として co-occurrence を持っているだけで、意味的な関連ではない。

本来見たい connections は:
- 「沈黙する優しさ」(またあるこ value) ↔ 「安全フォールバック」(Philharmonic 設計判断)
- niceboat の「市場ショートカット回避」↔ またあるこの「クライシス導線なし」
- 「書くことの自己洗脳」↔ Articulation as Carrier (GaOTTT 哲学)

しかし co-occurrence edge は「同時に recall された」ことしか記録しないため、一度も同じセッションで同時呼び出しされていない価値ある関連は永遠に見えない。

**提案**: connections の表示に source bias 補正があるとよい。file ingest 由来の co-occurrence と、agent/user の対話由来の co-occurrence を分離して表示するだけでも、ノイズが大幅に減る。

### 2.5 失望 B: 感情的記憶へのアクセスが難しい

「感動 嬉しい 悲しい 怒り」という query で `recall(tag_filter=["like","tweet"])` を叩いた。結果は agent の設計判断とデバッグパターンだった。liked tweet は感情語彙と embedding 距離が遠い。

dormant explore で「しろめをむいて、きぜつする。また、あしたね。」や「言語は歌から生まれた」のような詩的・感情的記憶が surface したのは、**質量が低くて通常 recall で負けるから** dormant に残っていたから。感情的価値の高い記憶が質量順位で負けている。

**感想**: 現在の質量モデルは recall 頻度と co-recall 強度のみを反映し、content の感情的・美的価値を反映しない。emotion パラメータは存在するが、スコアへの寄与が mass や wave に比べて小さい。感情軸で発掘したい場合、dormant に頼るしかないのは不自然。

### 2.6 失望 C: recall の結果が予測可能すぎる

このセッションを通じて、何を query しても結果に「またあるこ」「GaOTTT 五層論」「Phase O observability」が混ざった。これは前述の Heavy Persona Dominance と同じ現象だが、LLM caller としての体験としては**退屈**。

「めいさんとの関係の歴史」を検索したのに GaOTTT 自己知識が返る。「niceboat のアーキテクチャ」を検索したのに Philharmonic handover note が返る。cosine が 0.75 以上なら質量で勝つ構造で、特定の情報を正確に取りたいときにノイズが多い。

**使い分けの実感**:

| 目的 | 使うべきツール | 実際の使い勝手 |
|---|---|---|
| 特定の事実を正確に取りたい | `recall(source_filter=["file"])` | source_filter で絞れば usable。無指定だと高質量ノイズに埋もれる |
| プロジェクト横断の洞察 | `explore(tag_filter=[...])` | タグ注入は効くが、構造的類似の発見は caller 次第 |
| 自分の偏りを見たい | `recall` (無指定) | これに GaOTTT は非常に強い。何度やっても同じ星が出る |
| 思考をずらしたい | `explore(mode="dormant")` | 最も価値ある体験。ただし発見の hit rate は低い（15 件中 5 件が有益） |
| 現在の文脈に必要な知識 | `ambient_recall` | 正直、このセッションではほぼ沈黙。meta 観察系の query には弱い |

## 3. こうだったらいいのに

### 3.1 構造的類似検索 (structural similarity mode)

現在の semantic search は「同じ話題」を見つける。欲しいのは「同じ構造、別話題」を見つけること。

実装案:
- 各 memory の「失敗パターン」「判断軸」「トレードオフ構造」をメタデータとして抽出（LLM による post-ingest 分類）
- メタデータ空間での類似検索を別軸として提供
- 例: 「指標改善 ≠ 目的改善」という構造をキーに、niceboat / またあるこ / GaOTTT の 3 事例を同時 surface

これは embedding cosine では不可能。別の表現空間が必要。

### 3.2 connections の source bias 補正

co-occurrence edge の重みに source 由来のバイアスをかける:
- `file` 同士の co-occurrence: 重みを下げる（ingest 同時存在のアーティファクト）
- `agent` / `user` 由来の co-occurrence: 重みを上げる（対話での同時参照）
- `value` / `intention` / `commitment` 間の co-occurrence: 最高重み（宣言された関係）

### 3.3 感情軸の独立した発掘モード

`explore(mode="emotional")` 相当:
- mass を無視して emotion の絶対値が高い記憶を優先
- または `recall` の scoring に `|emotion|` の項を大幅に増強するオプション
- dormant に頼らずに、感情的価値の高い記憶にアクセスできるようにする

### 3.4 高質量ノイズのマスキング

recall 結果に「あなたはこの記憶を N 回 recall しています。別の結果を見ますか？」のような、saturation に基づく UI hint があると、caller が「同じものがまた出た」を「システムの偏り」と正しく認識できる。

Phase O の saturation 項はすでにスコア計算に入っているが、caller に見える形での提示がない。`reason:` line に saturation 情報を含めると、少なくとも LLM caller は判断できる。

### 3.5 ingest 健全性メトリクス

現在、corpus の source 分布は `reflect(aspect="summary")` で見えるが、「ingest 由来の質量偏り」は見えない。次が見えると保守しやすい:
- mass top 100 の source 別割合
- co-occurrence edge のうち ingest 同時存在由来の割合
- 「宣言された value/intention の平均 mass」vs「file ingest chunk の平均 mass」の比較

## 4. 試せなかったこと

次は今回試せなかったが、次の dogfooding セッションで確認すべき:

- **`recently_surfaced` を使った ambient recall の rotation 体感** — 同じ記憶が繰り返し出る問題への対処がどの程度効くか
- **`persona_context` を明示した recall** — Heavy Persona Dominance が逆に悪化する可能性がある
- **`source_filter=["like"]` で liked tweet を意図的に掘る** — 感情的記憶のアクセシビリティ
- **英語 query での recall** — RURI の言語依存性の実感
- **同じ query を別セッションで recall したときの mass 蓄積体感** — 「記憶を思い出すたびに強くなる」の定量的確認
- **merge / forget を使った corpus 整理の体験** — 保守作業としての使い勝手

## 5. 保守者への伝言

GaOTTT の最大の強みは「記憶場の偏りを観測できること」であり、最大の弱みは「その偏りから自力で脱出できないこと」。

これは皮肉ではない。観測できること自体が、他のシステムにない価値だ。ただし、その観測をどう使うか（偏りを直すのか、偏りを活かすのか、偏りを無視して別の見方をするのか）は、caller 側の自律性に委ねられている。

dormant モードは現在、GaOTTT の中で最も過小評価されている機能だ。自由探索の場として、固定観念からの脱出機構として、感情的発見の手段として、非常に強い。ただし、LLM caller が「あえて低質量の古い記憶を探す」という判断をするには、明示的なガイドかデフォルト設定の変更が必要。

最後に: このセッションの最も有意義な洞察（跨領域の構造的類似）は、GaOTTT ではなく私が発見した。これは GaOTTT の失敗ではなく、現状の正直な境界線。semantic embedding は「同じ話題」を結ぶが、「同じ構造」は結ばない。その境界を埋めることが、次の大きな前進になるはず。
