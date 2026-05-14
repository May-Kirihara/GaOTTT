# Research — Muon as Thought Experiment

> **status**: 思考実験 — 実装計画ではない。Phase N 候補の一つとしてアイデアだけ残しておく。
>
> 2026-05-14 セッションの会話を要約。User: 「今の Optimizer って SGD メタファーとして動いているけれど、Muon とかを目指そうとするとどんな感じになるんだろう」への応答整理。

## 前提

GaOTTT の現状は [Research — Gravity as Optimizer](Research-Gravity-As-Optimizer.md) で整理した通り、**Heavy ball SGD + Hebbian + L2 を Verlet 積分** に項ごと対応する構造になっている。各ノードの displacement は独立な 1D ベクトルとして更新される (per-node momentum / per-node L2)。

[Muon](https://kellerjordan.github.io/posts/muon/) (Keller Jordan, 2024) は **matrix-valued parameter に対する optimizer** で、momentum buffer `M` を Newton-Schulz iteration で polar decomposition `M = U Σ Vᵀ → U Vᵀ` に置き換える。つまり **特異値スペクトルを全部 1 に flatten** し、一つの dominant 方向が step-size 予算を独占しないように **spectral whitening** を埋め込む。

したがって「GaOTTT を Muon 化する」最初の設計問題は **「どの軸でノードを行列に並べるか」** になる。1D ベクトル単体には orthogonalize は定義できない。

## 並べ方の選択肢

### (A) Active wave seed × dim — `R^{K × 768}`

1 recall の seed pool で attract される K 個のノード変位を行列に積む → orthogonalize → 適用。

**意味**: 「query に対して全員が同じ方向へ寄る」(low-rank conformism) を **構造的に禁止** する。全ノードが query 方向への translation を共有していたら、その共通成分を捨てて、互いに直交した残差だけを採用する。

### (B) Cohort × dim — `R^{N_cohort × 768}`

[Phase K supernova batch](Plans-Phase-K-Stellar-Supernova-Cohort.md) の同時生成ノードを 1 行列として、初期 velocity を orthogonalize。

**意味**: 共起 batch が単一の outward direction に潰れないことを保証 — 「同じ会話で同時に生まれた星たち」が **必ず singular spectrum を埋める**。

### (C) Per-parent attribution stack — `R^{parents × dim}`

[Phase M Mass Conservation](Plans-Phase-M-Mass-Conservation.md) で導入した `propagate_gravity_wave` の `out_attribution`、つまり **誰が誰を引いたかのテンソル** を stack して orthogonalize。

**意味**: gradient の階層が既に matrix shape を持っているので、最も Muon らしい切り出し。

## 物理として何が起こるか

SGD = 各星が個別に力を感じる。**Muon = N 体系の共通並進運動を強制的に捨てる**。

GR 的に言えば **gauge fixing** — 重心系のドリフトを subtract out して、残った相対運動だけを update に通す。あるいは「**全 singular mode に conservation 制約を課す**」物理。

TTT として読み直すと: 現状は「この query → このクラスタ全体を translate」という low-rank 更新を許してしまう ([Phase L acceptance](Plans-Phase-L-Hybrid-Retrieval.md) で「embedder の hidden ranking が dominant signal」と露呈した pathology の dual)。Muon は **rank 制約を物理レベルで埋め込む** ので、recall ごとに必ず multidimensional な geometric reshape になる。

## 実装規模感

- N=24k なので full SVD は重い。だが Muon は **per-batch** 設計 (transformer の各 layer に対し forward の度に Newton-Schulz)。GaOTTT でも **active wave subset (K ≈ 50-300)** に限定すれば `300 × 768` の Newton-Schulz は 2-3 iter で済む — engine step あたり数 ms オーダー
- `compute_acceleration` の **4 番目の項 (query attraction) のみ** に絞るのが安全な切り出し。gravity / cohort には触らない
- toggle: `muon_query_attraction_enabled=False`、`muon_ns_iters=2`、`muon_lr_scale=1.0`

## 「Articulation as Carrier」との緊張

ここが思考実験の急所。**Phase J の「言葉にした宣言が重力を持つ」物理は、宣言の集合が共通方向に引くことで効果を出している**。Muon を全面適用すると、その共通方向こそが orthogonalize で消える成分になり、人格層が逆に薄まる危険がある。

落とし所はおそらく:

- **gravity (mass-BH) + persona attraction はそのまま** — これらは「shared direction を許容する」物理であってよい (重力は本性として center-of-mass 並進を生む)
- **query attraction のみ Muon 化** — 観察行為が観察対象を一方向に押し続ける P7-Z 問題への構造的対処として

## 三層語彙

| 層 | SGD-GaOTTT (現在) | Muon-GaOTTT (思考実験) |
|---|---|---|
| 物理 | 重力に引かれる星々 | 観測のたびに、皆が同じ方向に寄ることを禁じる物理法則を一個追加した宇宙 — gauge fixing |
| TTT 機構 | per-parameter momentum (Heavy ball) | spectral whitening of update matrix |
| 生物 | Hebbian な共起強化 | 想起のたびに記憶のクラスタが complacent に潰れない抗-conformism 機構 |

## 着手するなら

実装するなら Phase N の入り口候補としては筋がいい。けれど **Phase L で見つけた hybrid retrieval の geometry が落ち着いてから** が順序的には自然 — 今 Muon を入れると seed pool 構造変化と spectral 制約の相互作用で原因の切り分けが困難になる。

順序提案:

1. Phase L Stage 2-3 完遂 (hybrid retrieval の baseline 安定)
2. Phase M Stage 2 完遂 (mass threshold θ の経験的確定)
3. **Phase N 候補**: query attraction の Muon 化 (option A から)。`compute_acceleration` 第 4 項のみに toggle で適用、acceptance で「観測 conformism が和らぐか」を計測

## 関連

- [Research — Gravity as Optimizer](Research-Gravity-As-Optimizer.md) — 現状の SGD 同型関係の整理
- [Plans — Phase I — Free Star Movement](Plans-Phase-I-Free-Star-Movement.md) — query attraction の物理実装
- [Plans — Phase J — Persona-Anchored Retrieval](Plans-Phase-J-Persona-Anchored-Retrieval.md) — 人格層が共通方向に引く設計
- [Plans — Phase L — Hybrid Retrieval](Plans-Phase-L-Hybrid-Retrieval.md) — dominant signal の pathology が露呈した文脈
- [Plans — Roadmap](Plans-Roadmap.md) — Phase N はまだ正式登録なし
- Muon 本家: https://kellerjordan.github.io/posts/muon/
