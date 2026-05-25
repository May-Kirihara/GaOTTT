# Plans — Embedder Comparison (RURI vs RikkaBotan Bilingual Static)

> 状態: **❌ Phase A STOP (2026-05-25)** — RikkaBotan は quantized / fp32 のどちらでも RURI に discriminative power で劣り、Phase B/C 進行根拠なし。**副次成果**: RURI が pure cross-lingual (英数字共有ゼロ EN→JA) を小規模 (5 docs) では 5/5 成功できることを実機確認、`project_ruri_crosslingual_behavior` memory の前提を「条件付き」に修正する根拠を獲得 ([Phase A 観察記録](#phase-a-観察記録-2026-05-25-実行) 参照)
> 関連: [Roadmap](Plans-Roadmap.md), [RURI cross-lingual 制約 memo (project_ruri_crosslingual_behavior)](../maintainers/handover-2026-05-21-self-knowledge-cycle-2.md)
> 発端: 2026-05-25 ブレスト — JA-EN bilingual retrieval ユースケースに対し現状 RURI が cross-lingual を橋渡しできない構造的境界を確認済み (memory 上では)。代替候補として MRL + static + quantized の bilingual embedder ([RikkaBotan/quantized-stable-static-embedding-fast-retrieval-mrl-bilingual-ja-en](https://huggingface.co/RikkaBotan/quantized-stable-static-embedding-fast-retrieval-mrl-bilingual-ja-en)) を評価。Phase A 実機検証で **2 つの前提が同時に揺らいだ** — (1) RURI の cross-lingual 失敗は条件付きだった、(2) RikkaBotan は static 構造の限界で代替にならない

## 背景 — RURI の構造的境界と代替候補

GaOTTT は現状 `cl-nagoya/ruri-v3-310m` (768 dim, JA-specialized fine-tuned BERT) を embedder として使う。本番運用と複数 acceptance test から以下の制約が確認されている:

- **Cross-lingual を橋渡しできない** — EN クエリ → JA 文書、JA クエリ → EN 文書はどちらも recall が崩れる ([project_ruri_crosslingual_behavior](../maintainers/handover-2026-05-21-self-knowledge-cycle-2.md))
- **EN 文書同士の retrieval も JA optimization の余波で品質低下する**
- ingest 時の embed コストは production p50 ~35ms (RURI v3 310m on CPU)

候補 embedder `RikkaBotan/quantized-stable-static-embedding-fast-retrieval-mrl-bilingual-ja-en` の特徴 (仕様面、Phase A で実機確認予定):

| 項目 | RURI v3 310m (現状) | RikkaBotan bilingual (候補) |
|---|---|---|
| アーキテクチャ | contextual (BERT fine-tune) | static (token-average 系) |
| 言語 | JA-specialized | JA-EN bilingual |
| 次元 | 768 固定 | MRL **native 512**、truncate で 256 (768 は native に存在しない、A1 で実機確認) |
| quantization | float32 | quantized (int8 想定、要確認) |
| 推測 latency | ~35ms (production 実測) | 数 ms オーダー (static + quantized) |
| 推測品質 | 文脈・否定・語順を取れる | 語順・否定に弱い、語彙レベルは強い |

## 仮説 — 三つの可能性

### H1: Cross-lingual gain は確実にある
JA-EN bilingual 訓練を受けているなら、EN クエリで JA 文書を、JA クエリで EN 文書を retrieve できるはず。これは RURI が原理的に提供できない能力なので、**最小 prerequisite として満たさなければ評価続行する意味がない**。

### H2: JA 単言語では RURI が勝つ
contextual vs static の構造的差で、JA 単言語の semantic 類似度 (特に reasoning や否定を含むクエリ) では RURI 優位が予想される。**どの程度の品質劣化を cross-lingual と引き換えに許容できるか** が Phase B の判断材料。

### H3: GaOTTT 機構との相性は frozen history caveat 付きで観察するしかない
mass / cohort / virtual FAISS の現在状態は RURI 駆動の recall 履歴から育ったもの。RikkaBotan に embedder を差し替えた場合、

- 既存 mass 地形は新 embedding 空間にとってランダムに近い分布になる可能性
- mass-BH attractor は依然として機能するが、attractor までの「道」が embedding 空間で変わる
- cohort 内引力 (Phase K) は cohort_id ベースで embedding 非依存なので不変

→ **「frozen history で機構が壊れないか」しか測れない**。「RikkaBotan ネイティブ GaOTTT」の評価には Phase C の full reingest が必要。

## Phase A — Smoke probe (1 時間〜2 時間、本日着手可能)

> **目的**: RikkaBotan を `.venv` に入れて実機 load・encode が動くか、production の実 query × 実 memory shape で bilingual / 語順 / prefix sensitivity が本当に効くかを確認する。Phase B 本格設計の前提を空振りさせない。

### 設計原則 — production の実 shape を使う

ambient_recall hook ([`scripts/hooks/ambient_recall.py`](../../scripts/hooks/ambient_recall.py)) は **ユーザーの prompt 全文** を min 12 文字フィルタだけ通して `ambient_recall(query=prompt)` に投げる。document 側は production DB の実 shape を持つ。toy 例 ("こんにちは"/"Hello") は production の query 分布も memory 分布も反映しない。

production 実 shape の特徴 (2026-05-25 survey 結果):

| 種別 | 実 shape の例 | 特徴 |
|---|---|---|
| **Query (ambient hook 流入)** | `"ありがとう。テスト文章について、Hookでのambient recallで使う前提だから、この文章のような文字列でもテストがしたいです"` | カジュアル JA + tech 用語 (Katakana + 英字) 混在、複数 clause、12 文字以上の自然文 |
| **agent memo** | `"[LMS-100] マルチテナント: tenant_settings (ホワイトラベル)。tenant 毎に外観カスタマイズを保持するテーブル。..."` | `[ANCHOR/CODE]` prefix、JA + EN tech terms、長文 (500-700 chars) |
| **tweet** | `"[Tweet, 2023-05-27 00:02 UTC]\nばかめ生きておるわ\n\nおはよ。..."` | `[Tweet, ...]` prefix が text に baked、短文 conversational |
| **like** | `"[47/50, liked ~2022-10-20]\nGoogle Colabで試せる..."` | `[N/50, liked ~YYYY-MM-DD]` prefix |
| **file** | `"ろうか<br>ホロとコルには目配せだけをして..."` | `<br>` 付き本文 chunk、ruby annotations 含む 2-3000 chars |
| **value/intention** | `"設計思想と実装の literal 対応を選好する..."` | manifesto 調、JA + EN tech terms |

**Static embedder 特有のリスク**: text に baked された prefix (`[Tweet, ...]`, `[N/50, ...]`, `[ANCHOR: ...]`) は token-average 系 embedder では **全 tweet 同士が prefix だけで近接する** 可能性。RURI は fine-tune で重み下げを学習しているはずだが、static は構造的に学習できない。これは A3 で必ず測る。

### Step A1 — 環境準備

```bash
.venv/bin/python -c "
from sentence_transformers import SentenceTransformer
model = SentenceTransformer('RikkaBotan/quantized-stable-static-embedding-fast-retrieval-mrl-bilingual-ja-en')
print('dim:', model.get_sentence_embedding_dimension())
print('max_seq:', model.max_seq_length)
print('modules:', [type(m).__name__ for m in model])
"
```

確認事項:
- sentence-transformers でそのまま load 可能か (`StaticEmbedding` module 系か、独自 module か)
- native dim (MRL truncate 前のフル次元)
- query/document の prefix 規約が必要か (RURI の `検索クエリ: ` / `検索文書: ` のような)
- `normalize_embeddings` の default 挙動
- quantization 形式 (int8 / uint8 / fp16)

### Step A2 — Realistic ambient-recall probe

ambient hook で実際に流れる shape の query を、production DB から取った実 memory に対して投げる。**5 query × 2 model = 10 回 encode + cos sim**。

```python
# scripts/probe_rikka_botan.py
# production DB から事前に取得した実 memory text (read-only snapshot から)
DOCS = {
    "agent_lms":     "[LMS-100] マルチテナント: tenant_settings ...",      # 実 agent memo
    "tweet_short":   "[Tweet, 2023-05-27 00:02 UTC]\nばかめ生きておるわ\n\nおはよ。...",  # 実 tweet
    "intention_lms": "e-Learning LMS dev プロジェクトの引き継ぎ・ノウハウを GaOTTT に...",  # 実 intention
    "value_articulation": "経験は言葉にすることで初めて重力を持つ。めいさんの記憶宇宙の質量中心は...",
    "agent_phase_m": "[ANCHOR: GaOTTT-c2-phase-m] Mass Conservation: 自己関与は mass を生まない...",
}

# Mei さんが投げそうな現実 query
QUERIES_JA = [
    "LMSのマルチテナント設計どうなってたっけ",          # → agent_lms hit 期待
    "ありがとう、テスト用の文章を教えて",                # → どれにも weak hit 期待 (semantic noise base)
    "Articulation as Carrier って結局なに",              # → value_articulation hit 期待
    "Phase M の単一規則ってどういう意味",                # → agent_phase_m hit 期待
    "めいさんのTwitter での発言の傾向",                  # → tweet_short hit 期待
]

# Cross-lingual の本命: 同じ内容を EN で問う
QUERIES_EN = [
    "How is multi-tenancy designed in the LMS",          # → agent_lms hit, RURI 失敗予想
    "What does Articulation as Carrier mean",            # → value_articulation hit, RURI 失敗予想
    "Phase M single-rule meaning",                       # → agent_phase_m hit, RURI 失敗予想
]

# 出力: 5x5 + 3x5 のヒートマップ (各 query × 各 doc の cos sim)
# 両 model で並べて出力、top1 が期待 doc になるか + score の分離度を観察
```

期待:
- **JA→JA**: RURI も RikkaBotan も top1 正解、scores は両者とも 0.4-0.7 帯。RURI 優位を予想 (contextual + JA-specialized)
- **EN→JA**: RURI は top1 を当てられない or scores が flat (例: 0.1-0.3 帯で順位混乱)、RikkaBotan は top1 正解で 0.5+

### Step A3 — Prefix sensitivity probe (static embedder 特有の構造的リスク)

「`[Tweet, ...]` prefix が text に baked されている」せいで全 tweet 同士が近接するかを直接測る。これは RURI 比較ではなく **RikkaBotan 単体で構造を見る** test。

```python
# 中身が完全に違う 3 tweet が、prefix だけで近接していないか
TWEETS = [
    "[Tweet, 2023-05-27 00:02 UTC]\nばかめ生きておるわ",            # 怒り
    "[Tweet, 2023-07-27 02:30 UTC]\nしあわせである",                 # 平穏
    "[Tweet, 2022-03-15 22:25 UTC]\n具体的には、現実の仕事が一段落して、昨日の本を読み進めたあと、彼らを、ここに、呼び寄せます。",  # 静かな宣言
]
# Prefix 抜きで同じ中身
NO_PREFIX = ["ばかめ生きておるわ", "しあわせである", "具体的には、現実の仕事が一段落して..."]

# 期待: with-prefix cos sim 平均 > without-prefix cos sim 平均 + 0.2 だと「prefix がノイズ」
# 期待: with-prefix での tweet 間 cos sim > 0.6 (= 中身違うのに近い) は危険信号
```

判定:
- 差 0.05 以下: prefix の影響は無視可能、現状の memo shape のまま使える
- 差 0.05〜0.20: 注意、Phase C で prefix 剥がし or 別 field の検討
- 差 0.20 以上: **構造的問題**、Phase C 前に shape 設計の見直しが必要 (production の `[Tweet, ...]` prefix を text 外メタに移す等)

### Step A4 — Word-order / negation probe (realistic shape)

production text からの抜粋ベースで、語順入れ替え・否定を作る:

```python
PAIRS = [
    # 実 agent memo 風、肯定 vs 否定
    ("Phase M の単一規則: 自己関与は mass を生む",
     "Phase M の単一規則: 自己関与は mass を生まない"),
    # 実 intention 風、語順入れ替え
    ("LMS プロジェクトを GaOTTT に記録する",
     "GaOTTT を LMS プロジェクトに記録する"),
    # 実 value 風、対立概念
    ("経験は言葉にすることで重力を持つ",
     "言葉は経験にすることで重力を持つ"),
]
# 各ペアで両 model の cos sim を比較
```

期待: RURI は 0.4-0.6 程度離れる、RikkaBotan (static) は 0.85+ で「ほぼ同じ」と判定する可能性。**離れなくても Phase B 進行可** だが Phase B B2 の "reasoning 系クエリ" 重みを増やす根拠になる。

### Step A5 — Latency micro-benchmark

```python
# warmup 5 回 → 100 文 × encode (production の長さ分布を反映)
texts_short = ["[Tweet, 2023-05-27 00:02 UTC]\nばかめ生きておるわ"] * 33     # short
texts_med   = ["[LMS-100] マルチテナント: tenant_settings ..."] * 33         # med
texts_long  = ["ろうか<br>ホロとコルには目配せだけをして..." * 5] * 34        # long
# encode_query (single) と encode_documents (batch) を別計測
# p50 / p95 / p99 を RURI と並べる
```

### Step A6 — Phase A 結論判断

| H1 (bilingual: EN→JA top1) | H2 (語順感度) | H3 (prefix noise) | Phase B への進み方 |
|---|---|---|---|
| ✅ 3/3 正解 | 任意 | 差 <0.10 | **GO** — 予定通り Phase B 本格設計 |
| ✅ 3/3 正解 | 全く離れない | 差 0.10-0.20 | **GO with caveats** — query battery に reasoning/否定厚め、Phase C 時に prefix 設計再考 |
| ⚠️ 2/3 正解 | 任意 | 任意 | **CONDITIONAL** — Phase B やるが期待値下げる |
| ⚠️ 任意 | 任意 | 差 >0.20 | **CONDITIONAL** — Phase B 着手前に prefix 剥がし側で再 probe |
| ❌ 0-1/3 正解 | 任意 | 任意 | **STOP** — モデル選定からやり直し |

Phase A 結果は **このページ末尾の「Phase A 観察記録」セクションに追記**、Phase B 着手判断はそれを根拠にする。

## Phase B — 本格比較 script (Phase A GO 判定後、1 日タスク)

> **目的**: 本番 DB read-only snapshot に対し両 embedder の FAISS index を並べて build、4 つの signal を体系的に測る

### 構造

```
.perf-acceptance/embedder-compare/
├── db-snapshot/                  # 本番 DB の read-only コピー
│   ├── gaottt.db
│   └── gaottt.virtual.faiss      # RURI 由来、参考用に残す
├── faiss-ruri.idx                # 既存 RURI で rebuild
├── faiss-rikka-512.idx           # RikkaBotan native dim (MRL 512 base)
├── faiss-rikka-256.idx           # MRL 256 truncate
└── report-2026-05-25.md          # 結果サマリ
```

実行 entry point: `scripts/compare_embedders.py`

### 4 signal の測定設計

#### B1: Cross-lingual JA↔EN

- **設計**: 本番 DB から **既知の JA chunk を ~20 件** human-pick (内容を Mei さんが知っているもの)
- 各 chunk の主旨を Mei さん or LLM (GLM-5.1) で **EN 短文に要約 → これを EN query として投げる**
- 両 embedder で top-10 retrieve、**元の JA chunk が top-k に含まれるか** を ground truth として測定
- 逆方向 (EN ingest → JA query) は本番 DB に EN 文書がほぼ無いので **Phase B では割愛、Phase C で reingest 時に**

| Metric | 期待 |
|---|---|
| Recall@10 (RURI) | <10% (構造的に橋渡しできない) |
| Recall@10 (RikkaBotan-512) | >70% を期待、>50% で acceptable |

#### B2: JA 単言語品質 (ambient recall shape)

- **設計**: ambient hook の流入が「ユーザーの prompt 全文」なので、production の実 query 分布を反映した battery を作る:
  - **(a) Mei さんの過去 ~1 週間の発話から 20 件 hand-pick** — Claude Code 会話履歴があれば抜く、無ければ Mei さんに 20 件提供してもらう
  - **(b) reflect/recall 系の典型短文 query 10 件** — "Phase M とは"、"昨日の決定" 等の短い問い
  - **(c) reasoning/否定を意図的に含む 5 件** — Step A4 の結果次第で重みを増やす
  - 合計 35 件、すべて **min 12 文字 + 自然文 JA + tech term 混在** の ambient hook 通過形態
- 両 embedder で top-10、以下を計算:
  - **Jaccard@5, @10** — 両モデルの top-k 集合の重なり (1.0 = 完全一致、0.0 = disjoint)
  - **RBO (Rank-Biased Overlap, p=0.9)** — 順序込みの類似度
  - **LLM-as-judge** — secondopinion-MCP 経由で GLM-5.1 に top-5 ペアを relevance 判定させる ([secondopinion フロー参照](../../CLAUDE.md#本番-acceptance-test-の-workflow-sub-agent-方式))
  - **Source-mix dominance** — top-10 の source 分布 (agent/tweet/file/like 比率) を比較。RURI で奪われがちな agent 優位が RikkaBotan でも保たれるか (Phase L Stage 1 acceptance で観測された file/tweet dominance 問題が再発しないか)

| Metric | 期待 |
|---|---|
| Jaccard@5 | 0.3-0.5 (大きく違うはず) |
| LLM judge "RURI better" | 60-70% (contextual 優位) |
| LLM judge "RikkaBotan better or tied" | 30-40% |
| agent surface rate (top-10 中) | 両者で同等が望ましい |

**閾値判定**: RikkaBotan の relevance が RURI の **80% 以上 を維持** していれば cross-lingual 利益と引き換えに正当化可能。50% 未満なら Phase C に進まず棚上げ。

#### B3: Latency / throughput

```python
# warmup 後、本番 DB の代表 query 100 件
# - encode_query latency: p50, p95, p99
# - FAISS search latency (k=10): p50, p95, p99
# - ingest throughput (100 文 batch × 10 回): docs/sec
```

| Metric | RURI (production) | RikkaBotan 期待 |
|---|---|---|
| encode_query p50 | ~35ms | <5ms (一桁速い) |
| FAISS search p50 | ~2ms | 同等 (index 構造が同じ) |
| ingest throughput | >500 docs/sec (Tier 6) | >2000 docs/sec を期待 |

#### B4: GaOTTT 機構との相性 (frozen history)

- **設計**: snapshot の SQLite (mass / cohort / edges) はそのまま、FAISS だけ RikkaBotan で rebuild
- `engine.query` を 10 query 通し、**以下を観察**:
  - mass-BH attractor (高 mass ノード) が top-5 に surface するか
  - cohort 内 propagation (Phase K) が機能するか
  - virtual FAISS の displacement 効果が残るか
- **Caveat 明記**: 「これは frozen mass-history 評価であって、RikkaBotan-native GaOTTT の評価ではない」を結果 doc 冒頭に書く

### Phase B 完遂条件

- `scripts/compare_embedders.py` が再現実行可能
- `docs/research/embedder-comparison-2026-05-25.md` (research レポート) に 4 signal の結果表 + 観察 + Phase C 進行可否の推奨を書き切る
- Mei さんが結果を読んで Phase C 進行 / 棚上げ / RURI 継続 を判断できる材料が揃う

## Phase C — Conditional: branch + full reingest (Phase B 数値次第)

> **目的**: Phase B で RikkaBotan が "production 価値あり" と判定された場合のみ着手。本気の swap を branch で実装、full reingest で「RikkaBotan-native GaOTTT」を構築して評価

### 着手条件 (すべて満たすこと)

- Phase B B1: Recall@10 (cross-lingual) > 50%
- Phase B B2: relevance が RURI の 80% 以上
- Phase B B3: latency 改善が >3x または同等
- Mei さんの直感的判断で "GO"

### Phase C スコープ (着手時に詳細化)

- `feature/embedder-rikka-botan` branch
- `gaottt/embedding/` を embedder protocol で抽象化、RURI/RikkaBotan 両対応
- `gaottt/config.py` に `embedder_model` 設定追加
- 別 DB (`gaottt-rikka.db`) を full reingest、~23k chunks
- mass / cohort も RikkaBotan-driven で再育成、1-2 週間観察
- 両 DB を並列運用しユーザー体感比較
- 最終判断 → main 採用 or 棚上げ

## Open questions

1. **MRL truncate の実装**: sentence-transformers の `encode(truncate_dim=...)` が使えるか、それとも `embedding[:dim]` で手動切り出し + 再 normalize か
2. **Quantization の精度劣化**: int8 quantized なら float32 と比べて cos sim 値域が荒れる可能性、Phase A で hand probe 時に観察
3. **本番 DB の query log**: GaOTTT 内に query log は無い (ambient hook も recall も query を保存しない設計)。Phase B B2 は **Claude Code 会話履歴 + Mei さん提供 hand-pick 20 件** で構成する。production 分布の代理として、ambient hook が実際に通した shape (min 12 文字、自然文、tech term 混在) を制約として課す
4. **Phase A の所要時間**: 30 分見積もりは sentence-transformers でそのまま load できる前提。仮に独自 loader が必要なら 2-3 時間に伸びる
5. **embedder protocol 抽象化**: 現状 `gaottt/core/engine.py` は `RuriEmbedder` を直接 import している箇所がある。Phase C で抽象化する時に grep で 全箇所洗い出しが必要

## Caveats (Phase A 着手前に既に確認済み)

- **「機構との相性」は frozen history 評価のみ** — Phase C の full reingest なしでは "RikkaBotan-native GaOTTT" の真の挙動は測れない
- **production DB に ground truth ラベルがない** — cross-lingual は「狙った chunk が surface するか」で代用、JA 単言語は LLM judge で代用
- **Static embedding は語順・否定に弱いはず** — reasoning 系クエリで RURI 優位が出る可能性、query battery で意図的に混ぜる
- **Phase A/B の DB は read-only snapshot** — 本番 mass / cache を絶対に汚さない、別ディレクトリで完結

## Phase A 観察記録 (2026-05-25 実行)

> **状態**: ❌ **STOP 判定** — A1 + A2 + A2.2 (3-way) で十分なシグナルを得て、A3/A4/A5 はスキップ

### Step A1 — load 可否確認 (quantized 版)

```
[9.2s] model loaded
dim: 512                                              # ← native は 512 (README の "MRL JA" は 512 base)
max_seq: inf                                          # token 数制限なし (static の利点)
modules: [('0', 'SSEQ')]                              # custom module、trust_remote_code=True が必須
param 0.embedding.weight: shape=(96867, 512) dtype=fp32

cos sim per pair (toy JA-EN):
  +0.6944  | 東京は日本の首都 <-> Tokyo is the capital of Japan   ← pass
  +0.4885  | これはテストです <-> This is a test
  +0.4816  | 猫は動物です <-> A cat is an animal
  +0.2418  | 重力は物体を引き寄せる <-> Gravity attracts objects   ← 低い
  +0.1457  | こんにちは <-> Hello                                   ← 短文壊滅
```

判定: 短文・抽象概念で崩れる傾向。判断は production-shape の A2 まで保留。

**重要発見 (load 過程)**:
- HF repo に model weights が無く、`SSE_quantize.py` を `trust_remote_code=True` でローカル実行する仕組み
- native dim は 512 で 768 ではない → plan の MRL 比較を 256/512 のみに修正

### Step A2 — Production-shape probe (4 docs × 5 JA + 3 EN queries)

`scripts/probe_rikka_botan.py` 実行結果:

```
                 RURI 768d    RikkaBotan 512d
JA→JA top-1:        3/5            2/5
EN→JA top-1:        1/3            1/3
cos sim 値域:    0.76-0.90      -0.03 to 0.62
```

**重大な test design 問題発見**: EN queries に "Phase L" "embedder" "RURI" 等の英字 jargon が含まれ、対象 JA docs も同じ英字 substring を含んでいた。両モデルとも substring 一致で hit/miss を判定しているだけで、真の cross-lingual を測れていない。**Step A2.2 で test を再設計**。

### Step A2.2 — Pure cross-lingual probe (5 純JA tweets × 5 JA + 5 EN queries)

`scripts/probe_pure_crosslingual.py` で fixture 設計を厳格化:
- **JA docs**: `[Tweet, ...]` prefix 除去後の本体に **英数字を一文字も含まない** tweet 5 件 (量子疑似科学/spam嘆き/睡眠誘い/恐怖克服/朝の挨拶)
- **EN queries**: 意味の paraphrase のみ、固有名詞・technical term ゼロ、shared substring ゼロ

**3-way 比較結果**:

```
                              RURI 768d  |  fp32 512d  |  quantized 512d
JA→JA control top1:              5/5     |    3/5      |     3/5
EN→JA pure cross top1:           5/5     |    3/5      |     3/5
cos sim 値域 (top1 範囲):    0.84-0.90   |  0.05-0.32  |   0.05-0.30
```

**主要発見**:

1. **RURI は pure cross-lingual を 5/5 で成功** — 「英字 query → 英数字一切なしの JA tweet」で全 5 件正しく top1 を当てる。例: `"Tweet expressing skepticism about pseudoscientific medicine"` → 「わかりやすく書いてある時点で、この量子なんちゃら医学は、あやしいのです」を top1 (cos sim 0.846)
2. **fp32 vs quantized で score がほぼ同一** (例: quantum_skeptic top1 が 0.0980 vs 0.0973) — quantization は影響なし、**static architecture そのものが discriminative power を持たない** ことが分離
3. **RikkaBotan の cos sim 値域が極端に低い** (-0.07 to 0.32) — top1 と 2nd の差が小さく noise に弱い

**ただし重要な留保 — production scale で未検証**:
- 我々の test は 5 docs / 異なるトピック (最もイージーな条件)
- RURI の top1 が他 doc より +0.06 程度しか上がらない (margin 細い)
- production の 23k docs / トピック重複多数では noise floor 0.78 に埋まる可能性が **依然残る**

つまり「**RURI cross-lingual fails の memory が完全に間違いだった**」とは言い切れない — production scale (Needle-in-haystack) は未測定。

### Step A6 — Phase A 結論

**STOP 判定** ([2026-05-25 user 判断](https://github.com/May-Kirihara/GaOTTT/pull/issues)):

- A1 + A2 + A2.2 で RikkaBotan の評価は終了
  - quantization の有無に関わらず static 構造の限界
  - JA→JA で RURI 5/5 vs RikkaBotan 3/5
  - EN→JA で RURI 5/5 vs RikkaBotan 3/5
  - 4 条件すべて RikkaBotan が劣る → Phase B/C 進行根拠なし
- A3 (prefix sensitivity) / A4 (語順・否定) / A5 (latency) は STOP に伴いスキップ
  - latency 改善は確認できているが (RikkaBotan 2.6s load / quality 50ms vs RURI 5.5s / 5.5s) 品質劣化を埋め合わせない

**Phase B (本格 script) と Phase C (branch + reingest) は abandoned**。

### 副次成果 — RURI cross-lingual に関する新しい知見

memory `project_ruri_crosslingual_behavior` は「RURI は EN↔JA を橋渡しできない」と書いていたが、Phase A 実機検証で **「条件付きで使える」** が判明:

| 条件 | RURI の cross-lingual 挙動 |
|---|---|
| **小規模 (5 docs) / 異なるトピック** | ✅ pure EN→JA で 5/5 (実測) |
| **production 規模 (23k docs) / 類似トピック多数** | ⚠️ 未検証 — +0.06 margin が noise floor に埋まる可能性 |

このため `project_ruri_crosslingual_behavior` memory を「失敗」から **「条件付き能力、small/distinct topics では機能するが production scale は未検証」** に更新する (separate follow-up task)。

### 残された open question (next iteration の種)

1. **Needle-in-haystack test** で RURI の cross-lingual margin が production scale でも持つかを直接測る ([Plans-Roadmap.md](Plans-Roadmap.md) の「研究 / 検討中」配下に option として残す)
2. もし RURI が production scale で破綻するなら、**contextual な multilingual embedder** (BGE-M3、multilingual-e5 等) を別 Phase で評価。Static は RikkaBotan で構造的に no-go と判明
3. **Articulation as Carrier の literal な実装** として、もし embedder layer を交換するなら mass 地形の再育成も必要 (Phase C スコープ) — どの代替 embedder でも共通課題

### 生成物 (再現用)

- `scripts/probe_rikka_botan.py` — A2: production-shape probe (production DB read-only)
- `scripts/probe_pure_crosslingual.py` — A2.2: pure cross-lingual 3-way 比較

## 関連メモリ (GaOTTT 内 anchor)

- `project_ruri_crosslingual_behavior` — RURI が EN↔JA を橋渡しできない構造的確認
- `feedback_no_source_branching` — physics rule は構造的識別子のみで普遍適用 (embedder 切替後も same 原則)
