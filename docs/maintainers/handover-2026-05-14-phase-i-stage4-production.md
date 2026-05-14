# Phase I Stage 4 — 本番 DB acceptance ハンドオーバ (2026-05-14)

> 状態: **dev へ Stage 4 実装 + 受け入れ検証完了** (commits `867cab8`, `3ff5863`)、`docs/wiki/Plans-Phase-I-Free-Star-Movement.md` §Stage 4 + §受け入れ検証結果 に詳細。本ドキュメントは本番 23k corpus 上の **acceptance findings** と **使用感レポート** をまとめ、Stage 4 を本番で β>0 化する前にやるべきことを記録する。

## 検証経路

| 経路 | エージェント | 入力 | 目的 |
|---|---|---|---|
| (a) Quantitative | foreground (Claude Opus) | 本番 DB snapshot (`/mnt/holyland/Project/GaOTTT/.acceptance-snapshot/`、737 MB / 33,610 active) | β=0 vs β=1 / β=0 vs β=3 を `scripts/diag_production_acceptance.py` で per-query top-10 比較 |
| (b) Live qualitative | Agent (general-purpose, sonnet) | 本番 MCP `gaottt` (β=0 で稼働中) | 8 query を `recall(top_k=3)` で叩き「今の本番の使用感」を独立観察 |
| (c) Offline qualitative | opencode (background) | snapshot 比較 JSON 2 本 | 15 query を deep dive — **22 分後 0 byte output で hang、kill** (前 session 同様の opencode 沈黙パターン、Sonnet で代替できたので影響なし) |

## (a) Quantitative — snapshot 上の β-comparison

`scripts/diag_production_acceptance.py` で 15 本の production-realistic query (Phase I/J/K/L/M、persona、failure stories、surface-form) を本番 snapshot に対して β=0 / β=1 / β=3 で実行 (top-10):

| 指標 | β=0 vs β=1 | β=0 vs β=3 | 評価 |
|---|---|---|---|
| Jaccard 平均 | **0.966** | 0.966 | β=1 / β=3 で同等、極めて安定 |
| top-1 同一 | 14/15 | **15/15** | β=3 のほうが top1 安定 (反直感) |
| top-3 set 同一 | 13/15 | 14/15 | β=1 で 2 query、β=3 で 1 query が top-3 set に shift |
| 位置整合 (per query 平均) | 7.53 / 10 | 7.67 / 10 | top-10 中 2-3 位の入替が常時起きる |
| recall p50 latency | 740 ms | 706 ms (delta noise) | Stage 4 は latency に寄与しない |

**所見**: β を 1 → 3 に上げても **本質的に同じパターン**。これは [前 session の小 corpus acceptance](Plans-Phase-I-Free-Star-Movement.md#受け入れ検証結果-2026-05-14opencode-独立観察) で観察した「β-scaling saturate」現象が **本番 33k corpus でも再現** したことを意味する。

成果物: `.acceptance-report-beta1.json` / `.acceptance-report-beta3.json` (project-local、~318 KB 各、gitignore 配下)

## (b) Live qualitative — Sonnet による本番 MCP 体感テスト

**critical finding**: Stage 4 を活性化する前に、本番 DB の**既存 mass 状態に重大な歪み**があることが live MCP recall で露呈した。

### Query 別観察 (β=0 = 本番現状)

| # | Query | top-1 source / score | 整合 | 所感 |
|---|---|---|---|---|
| 1 | Articulation as Carrier の物理実装 | like / 0.25 | ⚠️ 外れ | top-3 全員 like/tweet、設計知識に届かず。最高 score 0.25 |
| 2 | Phase I Stage 4 Mass-dependent Hooke の設計 | like / **0.92** | ⚠️ 外れ | score 0.91 高だが奈良の道路ツイート + おやすみ + SakanaAI 批評 — **数字詐欺** |
| 3 | Phase L hybrid retrieval BM25 RRF | claude-code / 0.82 | ➖ 微妙 | "hybrid" 語の表層マッチ (競馬 ML の `evaluate_hybrid_policy`) |
| 4 | 現在 active な commitment | agent / 0.84 | ➖ 微妙 | startup-diagnostic 設計案。commitment タグに届かず |
| 5 | 持っている value と intention | agent / 0.69 | ➖ 微妙 | 同上、persona declared 知識が surface しない |
| 6 | MCP と REST の parity 鉄則 | claude-code / 0.71 | ➖ 微妙 | "falling back to REST" 実例、設計原則文書には届かず |
| 7 | 今日の作業で印象に残った設計判断 | file (SF 小説) / 0.66 | ⚠️ 外れ | 完全に意図と無関係 |
| 8 | 本番 acceptance を opencode で回す理由 | claude-code / 0.77 | ➖ 微妙 | blog 表現改善の会話、間接的かすり |

### 発見された 3 つの構造的問題

#### 問題 1: like/tweet の mass 肥大による semantic-無関係 top 占領

Q1, Q2 で **score 0.9+ なのに完全に無関係な like/tweet が top-1** という現象が複数 query で再現。
本番 DB の mass 分布:
- mass max = 33.99 (理論上限 50 の 68%)
- mass average = 1.65
- mass distribution は heavy tail — 高 mass nodes が一部 source に集中

source 比率: file (11k) / tweet (7.6k) / claude-code (7.5k) / like (4.2k) / agent (896)。like / tweet の **絶対数による相互引力で historical mass が育っている**。Phase M Stage 1 (mass conservation) は本日実装+rollout 済みだが、**それ以前に蓄積された mass を遡及修正していない**。

#### 問題 2: Persona 層の不可視性

Q4 (「active commitment」)、Q5 (「value と intention」) で **declared persona ノードが surface しない**。`source_filter=["agent"]` 等を使わない素の `recall` では埋もれてしまう。
Phase J Stage 1-3 (persona-anchored retrieval) が active 化されていても、persona ノード絶対数が少ない (value=3, intention=9, commitment=4) ため、dense な agent/claude-code クラスタに raw FAISS で押し負ける。

#### 問題 3: score 数字の信頼性低下 ("score deception")

Q2 で score 0.91 の top-1 が semantic-無関係 — **「score 高=正解」の見た目に騙される罠**。acceptance test 自動化で final_score をしきい値判定すると false positive を生む。これは [前 session 失敗事例 F-1 (StubEmbedder で性能評価)](https://github.com/May-Kirihara/GaOTTT/) と同じ「数値だけ見て質を見ない」罠の retrieval 版。

### Sonnet の β=1 化予想

> mass の大きいノード (like 群) への Hooke 引力が強まるため、短期的には like/tweet 支配がさらに悪化する可能性がある。ただし query 方向への attraction (Stage 2 の `α·score·gate` 項) と組み合わさると、mass 成熟ノードが query 方向に displacement されてきた場合のみ Hooke 復元力が拮抗するため、**self-force filtering (Phase M) が先行して like 群の mass inflation を抑えてからでないと β=1 の恩恵が出ないと予想する**。

これは **Plans-Phase-I §Stage 4 残課題「本番 β=1 観察」が単独では成立しない** ことを意味する。Phase M Stage 2 (mass reset 後の θ 確定 + 1-2 週観測) が前提条件として明示的に上に立つ。

### Sonnet の判定

> **微調整必要** — β=0 での現状は "安全だが persona/agent 系 knowledge が実用上ほぼ不可視" であり、source_filter=["agent"] を使わない素の recall では value/commitment が出てこない。β=1 活性化より先に Mass Conservation (Phase M) の self-force filtering による like 群の mass 抑制が優先事項と判断。

## 統合判定

### Stage 4 main merge: **✅ OK**

理由:
- β=0 default で挙動変化ゼロを 3 経路 (unit / integration / production snapshot) で確認
- 本番 33k corpus で β=1 化しても jaccard 0.966 / top1 14/15 で破壊的でない
- latency 影響ゼロ
- mass update 経路に触らないことが production data でも検証 (mass_delta = 0%)

### β=1 本番活性化: **⚠️ 待ち**

理由 (Sonnet finding + 既存 design 判断の合流):
- 既存 mass 肥大 (like/tweet) が支配的問題で、Stage 4 単独では解決しない
- Phase M Stage 2 の **mass reset → 1-2 週観測 → θ 確定** が先行して必要
- mass inflation が抑制されていない状態で β を上げると、肥大した like 群への Hooke 引力が強まる **逆効果リスク**

### 本日確定された Stage 4 残課題の優先順位 (Plans-Phase-I §残課題に追記済)

1. **(highest)** Phase M Stage 2 — mass reset migration (M003 wizard) を本番に適用、1-2 週間運用
2. mass 分布が rebalance した後、`scripts/diag_production_acceptance.py` を再実行して β=1 効果を再評価
3. それでも persona/agent surface が改善しない場合は **Stage 5 候補 (source-aware Hooke / β-θ decoupling)** を起草

## 検証ツール (本 session 追加)

`scripts/diag_production_acceptance.py` — 本番 DB snapshot に対して任意 GaOTTTConfig override で N query を比較、top-K に content/mass/displacement_norm を含めて JSON 出力。Stage 5 以降 (β-θ decoupling、source-aware Hooke) の検証や Phase M Stage 2 完了後の **β=1 再評価** でそのまま使える。

Live MCP feel test は **Agent (general-purpose, sonnet)** で実施。`recall(top_k=3)` × 8 query を 85 秒で完了、context 汚染なし、CLAUDE.md の「本番 acceptance test の workflow (sub-agent 方式)」§代替に従う。

## 参考 / 関連

- [Plans — Phase I — Free Star Movement](../wiki/Plans-Phase-I-Free-Star-Movement.md) §Stage 4 + §受け入れ検証結果
- [Plans — Phase M — Mass Conservation](../wiki/Plans-Phase-M-Mass-Conservation.md) §Stage 2 (mass reset 後の θ 確定)
- [Operations — Performance Testing](../wiki/Operations-Performance-Testing.md) §Tier 4 dynamics
- 実装 commits: `867cab8` (Stage 4 実装) / `3ff5863` (受け入れ検証 + diag tools)
- 本番 acceptance snapshot: `/mnt/holyland/Project/GaOTTT/.acceptance-snapshot/` (~950 MB、gitignore、Phase M Stage 2 完了後に削除可)
