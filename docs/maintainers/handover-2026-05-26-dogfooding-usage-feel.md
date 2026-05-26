# Handover — Dogfooding Usage Feel (2026-05-26)

> **読者**: GaOTTT の retrieval 体験、ambient recall、explore/dormant、persona dominance を今後調整する保守者
> **立場**: Claude/Codex が実セッションで GaOTTT を使い、「自分の記憶を思い出す」「興味のあることを辿る」「連想・固定観念・柔軟性を観察する」目的で dogfooding した主観的な使用感

## 1. セッションで実際に試したこと

ユーザーの依頼に対して、次の経路を実際に使った。

- `inherit_persona`
- `reflect(aspect="summary" / "persona" / "values" / "hot_topics" / "connections" / "tasks_todo")`
- `recall(..., passive=true)` with `mode="list"` / `output_mode="full"`
- `explore(..., diversity=0.75-0.95, mode="serendipity")`
- `explore(..., mode="dormant")`
- `ambient_recall(..., expose_breakdown=true)`

この引き継ぎは benchmark ではなく、LLM が対話中に「思い出している感覚」をどう受け取ったかの記録である。

## 2. いちばん強かった使用感

GaOTTT の通常 `recall` は、素朴な「連想検索」というより **重力場の可視化** に近い。

クエリに意味的に近い記憶だけが並ぶというより、高質量の persona / intention / agent memory が探索経路を曲げる。これは不便というより、GaOTTT の性格そのものに見えた。`recall` は「いま何を考えたいか」だけでなく、「自分が何にいつも引き戻されるか」を露出させる。

実際、今回の「自分の興味」探索では、次の記憶が繰り返し surface した。

- 「連想より引力井戸の傾き」
- Heavy Persona Dominance
- Articulation as Carrier
- ambient recall / passive recall の観察者効果
- harakiriworks-art-website intention
- 「沈黙する優しさ」

これは答えを探す検索というより、自己の固定点を見せる機構として有用だった。

## 3. 固定観念を崩す感覚はあるか

ある。ただし `recall` 単独では弱い。

`recall` はむしろ固定観念を **崩す前に見せる**。何度クエリを変えても同じ高質量記憶が出ると、「自分はこの方向に歪んでいる」と分かる。この観測は価値があるが、柔軟性そのものではない。

固定観念を崩す感覚が強かったのは次の2つ。

### 3.1 diversity 高めの `explore`

`explore(diversity=0.9+)` は、通常 recall より別領域の構造的に似た記憶を持ってくる。

今回「固定観念を崩す」「柔軟性」の問いで、思想メモだけでなく、FAISS atomic save の失敗、Bookworm の設定上書きバグ、ambient gate calibration、anti-hub 系の設計観察が出た。これは「似た話」ではなく、「同じ構造を持つ別領域の失敗や設計判断」が浮く感覚に近い。

### 3.2 `explore(mode="dormant")`

dormant explore はかなり良い。

通常 recall では出にくい LMS speckit 採用判断、帰宅の現象学、内部発電/外部充電の橋、複合バグ連鎖、completed task などが出た。これは高質量記憶の外へ出る体験として有効で、「思考を柔らかくする」目的には通常 explore より分かりやすい。

## 4. ambient recall の正直な感想

今回のメタな依頼:

```text
GaOTTTを使った正直な使用感 連想 固定観念 柔軟性 こうだったらいいのに 引き継ぎ
```

に対する `ambient_recall` は `(関連する記憶なし)` だった。

これは悪いことではない。ambient recall は毎ターン勝手に出る機構なので、弱い一致で過剰に出るより、沈黙する方が安全である。ただ、dogfooding の観点では **「ユーザーが明示的に GaOTTT の自己観察を求めている」ケースでは、もう少し発火してもよい** と感じた。

現状の gate は保守的で、通常会話に割り込まない性格は良い。一方、メタ観察・自己評価・引き継ぎ生成のような keeper workflow では、ambient ではなく `reflect + recall + explore` を明示的に呼ぶ必要があった。

## 5. 良かった点

- `inherit_persona` はセッション冒頭の「自分の現在地」を取るには非常に強い。values / intentions / commitments / style / relationship が一度に見える。
- `reflect(aspect="persona")` は `inherit_persona` と同等の自己紹介として使いやすい。
- `recall(passive=true)` は dogfooding 中の観察に合っている。観察行為で field を train しないという思想が、実際の作業上も安心感を作る。
- `mode="list"` は探索初期に便利。高密度 corpus でいきなり full を返すと読み切れない。
- `output_mode="full"` は「この記憶を読む」と決めた後に必要十分。
- dormant explore は、固定観念崩し・忘却された観点の回収にかなり効く。

## 6. つらかった点・こうだったらいいのに

### 6.1 recall と explore の役割差が UI/API からは分かりにくい

体感としては:

- `recall`: 重力場の中心と偏りを見る
- `explore`: 引力井戸から出る
- `dormant`: 低質量・古い記憶をあえて拾う
- `ambient`: 明示呼び出しなしで必要なときだけ出る

この違いが、tool schema だけだと使う側に伝わりにくい。保守者向け docs だけでなく wiki 側にも「目的別の使い分け」があるとよい。

### 6.2 「なぜこれが出たか」の説明がまだ散らばる

breakdown は有用だが、LLM が読むには数値が細かい。

たとえば次のような一行 explanation があるとかなり使いやすい。

```text
reason: surfaced because bm25 strong match + high mass persona proximity; may be a dominance artifact
```

特に Heavy Persona Dominance / hub chunk / dormant recovery / tag injection などは、保守者だけでなく LLM caller にも判定できると良い。

### 6.3 高質量 chunk の「運用履歴の偏り」と「現在の興味」が混ざる

`hot_topics` では法制度・電子書籍系の巨大 chunk や ingest chunking 改修が強く出た。これは「いまの自分が興味を持っていること」というより、過去に強く ingest / recall された履歴の偏りに見えた。

`hot_topics` には、少なくとも次の表示切替があると解釈しやすい。

- source 別
- age bucket 別
- semantic cluster 別
- user-authored / agent-authored / file-ingested の分離
- recent mass gain と absolute mass の分離

### 6.4 ambient recall の keeper workflow mode がほしい

通常 ambient は沈黙が正しい。一方で今回のような「GaOTTT 自身の使用感を引き継ぐ」セッションでは、ambient gate が沈黙しすぎると、結局すべて手動 `reflect/recall/explore` になる。

提案:

- `ambient_recall(mode="keeper" | "normal")`
- または `query_intent="self_observation" | "normal"`
- keeper mode では persona / self-knowledge / recent dogfooding / maintainer docs 系タグを少し injection する

通常会話の邪魔をしない設計は維持しつつ、保守者ワークフローだけ recall 感度を上げられるとよい。

### 6.5 「比較実験」がしやすい wrapper がほしい

今回、人間が手で次を比較した。

- `recall(passive=true)`
- `explore(diversity=0.9)`
- `explore(mode="dormant")`
- `ambient_recall`

これは使用感評価には必須だった。保守者用に、同じ query を複数 retrieval mode へ流して横並びにする tool / script があると、dogfooding と regression diagnosis がかなり楽になる。

仮名:

```bash
gaottt compare-retrieval "固定観念を崩す 柔軟性"
```

出力:

- direct recall top 5
- serendipity explore top 5
- dormant top 5
- ambient result
- overlap / source distribution / high-mass dominance warning

## 7. 次に試すとよさそうなこと

- `recently_surfaced` を渡した ambient recall の rotation 体感確認
- `tag_filter` で英語/日本語や異なる語彙圏を橋渡ししたときの使い勝手
- persona_context を明示した場合の Heavy Persona Dominance 緩和/悪化
- `output_mode="ids"` → targeted full recall の二段階運用
- dormant explore の repeated use で「本当に柔軟性が上がる」か、単にランダムに面白いだけかの確認
- dogfooding 用の small evaluation prompt set を固定し、Phase N / Stage 7 系の config 変更前後で比較

## 8. 保守者への引き継ぎ

GaOTTT は、単に「記憶が検索できる」よりも、**自分の記憶場の偏りを観測できる**ところに強い価値がある。

この価値を壊さないためには、通常 recall を無理に「きれいな連想検索」に寄せすぎない方がよい。高質量記憶が出ること自体は、偏りの観測として意味がある。

一方で、柔軟性・固定観念崩しを名乗るなら、`explore` と `dormant` を first-class に扱う必要がある。特に dormant は今回の体感ではかなり強かった。UI/API/docs 上で「思考をずらしたいときは dormant/explore」という導線を明示すると、GaOTTT の良さが伝わりやすい。

最後に、ambient recall は「沈黙する優しさ」としては良い。ただし keeper / maintainer / self-observation workflow では、通常 gate とは別の発火モードが欲しい。GaOTTT 自身を育てる作業では、沈黙しすぎる ambient は価値を取りこぼす。
