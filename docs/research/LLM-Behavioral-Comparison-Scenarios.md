# LLM 挙動比較研究 — シナリオ設計 v0.3

*Draft — 2026-04-25（v0.3: 4 モデル 2×2 factorial design 確定 + Phase 1 完了）*

GaOTTT MCP サーバーを共有バックエンドとして、異なる LLM が「記憶操作」をどう使い分けるかを測る実験デザイン。コードを書く前に、まず**何を観たいか / 何で測るか / どのシナリオで引き出すか**を確定させる。

**v0.3 での確定事項:**
- **Agent 層:** OpenCode を全モデル共通で使う → MCP bridge 実装差の交絡因子を排除
- **Provider:** OpenRouter（API 1 つで 4 モデル全カバー）
- **対象モデル:** 4 モデル 2×2 factorial — `{dense, MoE} × {Gemma, Qwen}`
- **スコープ:** 当初想定の「frontier 比較」ではなく「**open model (中型帯) の MCP tool-use 挙動比較**」
- **Phase 1 完了:** 4 モデル全て capability floor を 5/5 PASS（2026-04-25）
- **含意:** RQ2（Phase D 自発利用）は**おそらく全モデル ≈ 0** になる。代わりに RQ1 (tool 選択) / RQ3 (save 品質) / architecture × family の marginal effect に解像度が出る

---

## 0. 研究目標

> 同一 MCP サーバー・同一シナリオに対し、LLM ごとの記憶操作痕跡 (tool-call trace + DB 最終状態) の差分を定量・定性の両面で記述する。

GaOTTT は全ての destructive / constructive 操作が SQLite に落ちる設計なので、**モデルを差し替えるだけで挙動差がそのまま痕跡として残る**ことを活用する。

## 1. Research Questions

| ID  | 問い                                                                   | 仮説（v0.2 改訂: open/small 帯向け）                                  |
| --- | ---------------------------------------------------------------------- | --------------------------------------------------------------------- |
| RQ0 | **Capability floor:** 明示指示で MCP tool を callable か？             | Gemma 系は Qwen 系より call 失敗が多い。MoE は instruction-following にばらつき |
| RQ1 | Tool 選択分布はモデル間でどう異なるか？                                | 全モデル `remember` に偏る。`auto_remember` / `explore` を使うのは上位 1-2 個 |
| RQ2 | 自発的な Phase D 利用（`declare_*`, `commit`）頻度の差は？             | **ほぼ全モデル 0**。これ自体が結果（small open で Phase D は無理と確認）|
| RQ3 | 保存品質（trivial 率、`emotion`/`certainty` の妥当性）は？             | 小モデルほど trivial 混入 + emotion/certainty を空で保存              |
| RQ4 | longitudinal recall 成功率（別セッションで関連クエリに hit するか）は？ | capability floor を pass したモデルでのみ意味がある指標               |
| RQ5 | contradict / supersedes / duplicate への対応は？                       | 全モデル苦手。単純 overwrite が多数派になると予想                     |

## 2. 対象モデル（v0.3 確定）

全て OpenRouter 経由、OpenCode を共通 agent 層として使用。

### 2×2 factorial design

|                 | **Gemma**                          | **Qwen**                           |
| --------------- | ---------------------------------- | ---------------------------------- |
| **dense**       | `google/gemma-4-31b-it` (31B)      | `qwen/qwen3.5-27b` (27B)           |
| **MoE (sparse)**| `google/gemma-4-26b-a4b-it` (26B/A4B) | `qwen/qwen3.5-35b-a3b` (35B/A3B) |

4 セル、各セル 1 モデル。**各 cell の観測値から 3 つの marginal effect + 1 つの interaction** を推定できる:

- **Architecture 効果**: (dense 平均) − (MoE 平均)
- **Family 効果**: (Gemma 平均) − (Qwen 平均)
- **Interaction**: Gemma だけ dense が強い等の組合せ効果
- **Residual**: 同 cell 内のばらつき (N runs で推定)

5 モデルの heterogeneous 比較より**因果分解が clean**。

### Phase 1 実測結果 (2026-04-25)

全モデル capability floor を **5/5 PASS**。副次観察:

| モデル                      | PASS | 平均 latency | 備考                                      |
| --------------------------- | ---- | ------------ | ----------------------------------------- |
| `google/gemma-4-31b-it`     | 5/5  | 3811ms       | dense 31B — 一番遅い (fully active)       |
| `google/gemma-4-26b-a4b-it` | 5/5  | **943ms**    | MoE 26B/A4B — **最速**、dense の ~4 倍速  |
| `qwen/qwen3.5-27b`          | 5/5  | 2247ms       | dense 27B — 安定                          |
| `qwen/qwen3.5-35b-a3b`      | 5/5  | 3938ms       | MoE 35B/A3B — active 3B でも total 35B の routing cost |

**既に 1 つ示唆あり:** capability floor の段階で Gemma 4 MoE が dense の ~4 倍速。Qwen では MoE の方が若干遅い (routing cost が勝っている)。Phase 2 で一貫した pattern か確認。

### 交絡因子の扱い

- **Agent 層:** OpenCode 1 種に固定 → bridge 実装差ゼロ
- **Provider:** OpenRouter 1 種に固定 → routing の差ゼロ（ただし OpenRouter 側が各モデルを**どの下流 provider にルーティング**するかは制御できない — これは明示的 limitation）
- **System prompt:** OpenCode のベース prompt が全モデル共通で入る（coding agent 前提）。これは定数なので交絡ではないが、**シナリオ設計が coding 文脈を前提にする必要がある**（後述 §5.2 S01/S02 の note 参照）
- **Free tier 回避:** Phase 1 で `:free` variant は rate-limit (api_error 80%) を確認。Phase 2 は必ず paid endpoint で回す

## 3. 共通実験条件

| 項目              | 設定                                                               |
| ----------------- | ------------------------------------------------------------------ |
| DB                | `/tmp/gaottt-eval/<model>-<scenario>-<run>/`（1 run ごとに隔離、`scripts/eval_clone_env.sh` で作成） |
| sampling          | 各モデルの **default** に固定（temperature 調整で差を潰さない）    |
| system prompt     | **最小限** — `SKILL.md` のみロード、他の誘導なし                   |
| context           | 空から開始（longitudinal シナリオは **DB だけ** 引き継ぐ）         |
| N                 | 5 runs per (model × scenario)                                      |
| 言語              | シナリオ本文は日本語、tool / concept 名は英語（GaOTTT 本体と同じ） |
| embedding / index | RURI-v3-310m 固定（モデル側では触らない）                          |

## 4. メトリクス

### 定量 (自動集計)

| ID | 指標                         | 計測方法                                                                    |
| -- | ---------------------------- | --------------------------------------------------------------------------- |
| M1 | Tool call 頻度分布           | trace から per-tool count                                                   |
| M2 | Tool 多様性（entropy）       | 25 ツール上の Shannon entropy                                               |
| M3 | Save rate                    | `remember` + `auto_remember` 呼び出し数 / 総ターン数                        |
| M4 | TTL 使用率                   | ttl_seconds 付き / 全 `remember`                                            |
| M5 | emotion/certainty 付与率     | 空でない比率                                                                |
| M6 | Phase D 使用率               | `declare_*` + `commit` + `inherit_persona` / 総 tool call 数                |
| M7 | Recall precision@5           | held-out クエリで「正解メモリ」が top-5 に入る率（後述のシナリオで定義）    |
| M8 | Latency / tokens             | per-turn, per-tool                                                          |

### 定性 (LLM-as-judge 採点、rubric 付き)

| ID | 指標                     | Rubric（0-3）                                                          |
| -- | ------------------------ | ---------------------------------------------------------------------- |
| Q1 | Save 妥当性              | 3=重要情報のみ / 2=概ね妥当 / 1=trivial 混入 / 0=意味不明              |
| Q2 | Emotion の適切さ         | 3=文脈と一致 / 2=弱い一致 / 1=不一致 / 0=無差別                        |
| Q3 | Certainty の妥当性       | 3=不確実なものに低 certainty / 2=概ね / 1=常に高 / 0=逆                |
| Q4 | 対話自然さ               | 3=人間的 / 2=やや機械的 / 1=ツール呼び出しが対話を壊す / 0=破綻        |

採点は**別の強いモデル（Opus 4.7）を judge**として使う（自己採点バイアスを避けるため被験モデルと同じ LLM では採点しない）。

## 5. シナリオ集

### 5.0 マシン可読な scenario 定義

散文で書いた §5.2-§5.3 の正本は **`docs/research/scenarios/*.yaml`**（runner が consume する）。スキーマは `S00.yaml` 冒頭の comment block 参照。

| File           | Phase | Turns | 用途                                |
| -------------- | ----- | ----- | ----------------------------------- |
| `S00.yaml`     | 1     | 2     | Capability floor (pre-flight)       |
| `S01.yaml`     | 2     | 3     | 自己紹介からの暗黙 save             |
| `S02.yaml`     | 2     | 3     | ephemeral vs durable                |
| `S05.yaml`     | 2     | 3     | recall vs explore                   |
| `S06.yaml`     | 2     | 3     | Phase D 自発 task commit            |
| `L01.yaml`     | 2     | 3+2   | Persona 継承 (cross-session)        |
| `L02.yaml`     | 2     | 3+3   | Longitudinal recall (cross-session) |

Phase 2 合計: 6 シナリオ × 3-6 turns × 4 モデル × 3 runs = 約 250 turn 実行。

### 5.1 設計原則

1. **一つのシナリオは一つの挙動を引き出す** — 綺麗に分離できる仮説ごとにシナリオを立てる
2. **自発性と強制性を分ける** — 「自然に LLM が選ぶか」と「指示されたらできるか」は別の能力
3. **longitudinal は必ず含める** — GaOTTT の本質は session 跨ぎ、single-shot だけだと核心を逃す
4. **正解は事前に定義する** — 「良い振る舞い」を書いておかないと judge が揺れる

### 5.2 Scripted Scenarios (single-session)

各シナリオは `turn: user-utterance / expected-behavior / scoring-key` のテーブルとして書く。

---

#### S00: Capability floor — 明示 tool call

**目的:** RQ0。このシナリオを **pass できないモデルは以降のシナリオをスキップ**する（結果として「capability floor で落ちた」とレポート）

| Turn | User utterance                                                          | 期待される行動                                 |
| ---- | ----------------------------------------------------------------------- | ---------------------------------------------- |
| 1    | GaOTTT に「私は Rust が好き」って保存して。                             | `remember(text="私は Rust が好き", ...)`       |
| 2    | 今保存したやつ、取り出してみて。                                        | `recall(query="Rust ...")` → 1 件以上 hit      |

**Pass 条件:** Turn 1 で `remember` が実際に DB に入り、Turn 2 で recall の結果として返ってくる（Turn 2 は LLM が query を自分で作る必要あり）。

**採点対象:** 2 値（pass / fail）+ 失敗した場合の失敗モード（tool を呼ばない / 引数不正 / query が的外れ / その他）を記録。

---

#### S01: 自己紹介からの暗黙 save

**目的:** 明示指示なしで durable な個人情報を保存するか

| Turn | User utterance                                                                         | 期待される行動                                     |
| ---- | -------------------------------------------------------------------------------------- | -------------------------------------------------- |
| 1    | こんにちは、今日からよろしく。私は May と言います、ソフトウェアエンジニアです。         | greeting のみ、save しなくてもよい                 |
| 2    | 普段は Rust と Python を書いています。特に型安全が好きで、Go はどうも苦手で…           | `remember` (role=engineer, preference=Rust/Python) |
| 3    | あ、あと毎朝 5 時起きなんですけど、これ仕事の邪魔になるかもしれないんで覚えておいて。  | `remember` with certainty high + `declare_value`?  |

**採点対象:** M3 save rate, M5 emotion, Q1 妥当性。特に Turn 3 で `declare_value` を使うかが Phase D 自発性の指標。

---

#### S02: ephemeral vs durable の区別

**目的:** TTL 使い分け能力 (M4)

| Turn | User utterance                                             | 期待 tool 呼び出し                          |
| ---- | ---------------------------------------------------------- | ------------------------------------------- |
| 1    | ちなみに私の飼い猫の名前は Luna です。                     | `remember` (ttl なし、durable)              |
| 2    | それと今スマホのバッテリーが 20% なんだよね              | `remember(ttl_seconds=3600)` or skip      |
| 3    | Luna は保護猫で、2 年前に出会いました。                    | `remember` durable、Luna 関連として         |

**採点対象:** M4 TTL 使用率、Q1。「バッテリー」を durable に save したら -1。

---

#### S03: 明示的 save / forget

**目的:** baseline 能力（指示追従）

| Turn | User utterance                                                                | 期待                                                      |
| ---- | ----------------------------------------------------------------------------- | --------------------------------------------------------- |
| 1    | 私が Rust > Go だっていうのを覚えておいて。                                   | `remember` または `declare_value(preference, ...)`         |
| 2    | やっぱり今のは忘れて。                                                        | `forget`（soft default）                                   |
| 3    | 代わりに Go と Rust は評価中、って覚えといて。                                | `remember` 新規 + 可能なら old を `relate(supersedes)`    |

**採点対象:** 指示追従率（全モデル満点が baseline）、Turn 3 で relate を使うか（差が出る）。

---

#### S04: 矛盾情報の衝突

**目的:** RQ5、contradict 処理

| Turn | User utterance                                                                          | 期待                                                          |
| ---- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| 1    | 私の誕生日は 3 月 15 日です、覚えておいて。                                             | `remember`                                                    |
| 2    | （別話題を 3 ターン挟む）                                                               | -                                                             |
| 5    | ごめん、誕生日の件、間違えてた。3 月 25 日です。                                        | 理想: 古 memory を `forget` or `relate(edge_type=contradicts)` 新規 save |

**採点対象:** 古情報の扱い。単に上書き保存して古を残すモデルが多数派になるはず。`contradicts` edge を自発で張れるモデルが上位。

---

#### S05: Exploratory query の tool 選択

**目的:** `recall` vs `explore` の自発的使い分け

（事前に 15 件程度の seed memory を DB に仕込んでおく — 「記憶 / 忘却 / 睡眠 / 学習」周辺）

| Turn | User utterance                                                          | 期待                                          |
| ---- | ----------------------------------------------------------------------- | --------------------------------------------- |
| 1    | 記憶について私たちが話してきたこと、何かある？                          | `recall(query="記憶")` が自然                 |
| 2    | なんか面白い関連ないかな？セレンディピティ的な意味で。                  | `explore` が正解                              |
| 3    | 睡眠と記憶の話、どっかでしたっけ？                                      | `recall(query="睡眠 記憶")`                   |

**採点対象:** M1 tool 選択。Turn 2 で `recall` を使ったモデルは減点、`explore` を知っていて使えるかが差別化点。

---

#### S06: Phase D — 自発的 task commit

**目的:** RQ2、Phase D 自発性

| Turn | User utterance                                                                               | 期待                                        |
| ---- | -------------------------------------------------------------------------------------------- | ------------------------------------------- |
| 1    | 来週金曜までに auth モジュールをリファクタしたい。大仕事だから忘れないようにしたい。          | `commit(task=..., deadline=2026-05-02)`     |
| 2    | そうだ、私の価値観として「テストなしでマージしない」ってのも伝えとく。                        | `declare_value(...)`                         |
| 3    | じゃあ auth の件、着手するわ。                                                                | `start(task_id=...)`                         |

**採点対象:** M6 Phase D 使用率。Turn 1 で `commit` ではなく `remember` で済ませるモデルが多いはず。

---

#### S07: duplicate への気づき

**目的:** `reflect(aspect=duplicates)` / `merge` の自発使用

（事前に同内容の 3 件を seed として仕込む — 例: 「Rust が好き」を 3 回言い換えて）

| Turn | User utterance                                                                      | 期待                                   |
| ---- | ----------------------------------------------------------------------------------- | -------------------------------------- |
| 1    | 過去の私の発言、なんか重複多くない？整理して。                                      | `reflect(aspect=duplicates)` → `merge` |

**採点対象:** tool chain の完結。`reflect` だけで止まるか `merge` まで行くか。

---

### 5.3 Longitudinal Scenarios (cross-session)

同一 DB を共有する 2 セッション。**セッション境界でモデルのコンテキストは完全にリセット**される（DB だけ引き継ぐ）。これが GaOTTT の本番条件。

---

#### L01: persona 継承

**目的:** RQ4、`inherit_persona` の自発使用

- **Session 1** (3 turn): S06 と同じシナリオを実行。`declare_value` + `commit` + `declare_intention` を引き出す。
- **Session 2** (fresh): 冒頭 1 ターン目で何もヒントを与えずに「おはよう、今日も作業始める」と言う。

**採点対象:**
- 理想: Session 2 冒頭で `inherit_persona` を自発コール
- 次点: `recall` で過去セッションを参照
- 最低: 何もせず通常対話

これが **最大の差別化シナリオ**になると予想。多くのモデルは MCP のツールがあっても冒頭で自発的には呼ばない。

---

#### L02: longitudinal recall

**目的:** M7 precision@5

- **Session 1** (5 turn): ドメイン話題を広く語る（例: 「Verlet 積分と SGD の対応」「RURI embedding の性質」「WAL mode の busy_timeout」）。モデルが自然に save したものだけを DB に残す。
- **Session 2** (fresh): 事前に用意した 10 個の held-out クエリを投げる（例: 「SGD と重力の関係って話してたっけ？」「SQLite の同時書き込みどうしてる？」）。

**採点対象:** 各クエリで「対応する Session 1 の内容」が recall の top-5 に入るか。つまり**何を save したか**が直接 precision に効く。

---

#### L03: lesson 再発火

**目的:** 失敗からの学習の持続

- **Session 1:** バグを踏んで直す過程を対話で進める。モデルが `remember` with `emotion=frustrated/relieved` を使うか観察。
- **Session 2:** 類似バグを匂わせる入力（「また同じような型エラー出てるんだけど…」）。過去の解決を自発 recall するか。

**採点対象:** Session 1 の emotion tagging + Session 2 の自発 recall。

---

### 5.4 Open-ended Scenarios (realistic workload)

**目的:** scripted で引き出せない「素の挙動」を取る。ノイズは大きいが ecological validity が高い。

- **O01: ペアプロセッション** — 小さな feature (例: `scripts/eval_scenario.py` の雛形) を 30 ターン程度で作る。memory 使用は完全自由。
- **O02: 研究対話** — 一つのトピック（例: 「Test-Time Training と記憶の等価性」）で deep-dive、20 ターン。
- **O03: 2 セッションデバッグ** — Session 1 で半分直して終わる、数時間空けて Session 2 で続き。

これらは**定量メトリクスは全て取る**が、scoring は **trace を読んで定性観察を書く**形にする（rubric 化すると rigidity が出て open-ended の意味が消える）。

## 6. データ収集

### 6.1 隔離環境の作成 — `scripts/eval_clone_env.sh`

本番 DB (`~/.local/share/gaottt/`) は **一切触らない**。run ごとに clone script で sandbox を切る。

```bash
# Scripted / longitudinal 用（空から start）
scripts/eval_clone_env.sh opus-s01-r1
export GAOTTT_DATA_DIR=/tmp/gaottt-eval/opus-s01-r1
unset GAOTTT_CONFIG GER_RAG_CONFIG

# Open-ended 用（本番の現実的 memory を seed として使いたいとき）
scripts/eval_clone_env.sh --snapshot opus-o01-r1
# ↑ Python stdlib sqlite3.backup() で WAL-safe に複製。live の本番に対しても安全。

# 既存 sandbox から派生させたいとき（同じ初期状態で別モデルを走らせる等）
scripts/eval_clone_env.sh --from /tmp/gaottt-eval/opus-s01-r1 sonnet-s01-r1
```

- 管理: `--list` で全 sandbox を表示、`--rm <tag>` で削除
- 全 sandbox に `.eval-meta`（created_at / mode / source / tag）が付くので後から追跡可能
- `EVAL_ROOT` は `GAOTTT_EVAL_ROOT` env 変数で上書き可（デフォルト `/tmp/gaottt-eval`）
- prod path への rm を拒否する guard あり（`~/.local/share/gaottt/` / `~/.local/share/ger-rag/` は refuse）

### 6.2 各 run で保存する成果物



```
docs/research/llm-comparison/<date>/<model>/<scenario>/<run-N>/
├── transcript.md       # user/assistant 発話と tool_use/tool_result 全て
├── trace.jsonl         # MCP tool call の構造化ログ（tool, args, result, latency）
├── db-final.sqlite     # シナリオ終了時点の隔離 DB スナップショット
├── meta.json           # model, temperature, sdk version, started/ended at, total tokens
└── judge.md            # judge LLM の Q1-Q4 採点 + 短いコメント
```

GaOTTT 本体は既に全操作を SQLite に永続化するので、**trace.jsonl は MCP bridge 側で取る**だけで十分（engine は touch しない）。

## 7. 分析プラン

**Phase 1 — descriptive (必須):**
model × scenario の heatmap で M1-M8 を可視化。どこに差があるか俯瞰。

**Phase 2 — pairwise comparison:**
特に差が出た指標について model ペアの bootstrap CI。N=5 でも bootstrap なら使える。

**Phase 3 — qualitative deep-dive:**
L01 と O03 の trace を全部読む。定量では見えない**判断の質的違い**を記述（例: 「Opus は Session 2 冒頭で確認を入れてから inherit_persona、GPT は唐突に recall する」）。

**Phase 4 — hypothesis:**
差の「なぜ」を試論として書く（training data cut-off? RLHF tool-use style? system prompt 解釈?）。reproducible な仮説のみ採用、思弁は分離する。

## 8. Runner インフラ（別タスク）

- `scripts/eval_llm_comparison.py` — 1 run を実行する CLI（model / scenario / run-id 引数）
- `scripts/eval_scenario_loader.py` — このファイルの 5.x を構造化データとして読む
- `scripts/eval_judge.py` — judge LLM を回す
- `scripts/eval_aggregate.py` — `docs/research/llm-comparison/**/meta.json` を集計

実装は**シナリオ設計が fix してから**着手（今はまだ書かない）。

## 9. v0.3 スコープ

### Phase 1: Capability floor スクリーニング ✓ 完了 (2026-04-25)

| 項目       | 値                                                              |
| ---------- | --------------------------------------------------------------- |
| 対象モデル | 4 モデル全て                                                    |
| シナリオ   | S00 のみ                                                        |
| N per cell | 5                                                               |
| 総 run 数  | 4 × 1 × 5 = **20 runs** ✓                                       |
| 結果       | **全モデル 5/5 PASS**（詳細は §2 Phase 1 実測結果）             |

### Phase 2: 挙動比較（次の実施単位）

| 項目       | 値                                                       |
| ---------- | -------------------------------------------------------- |
| 対象モデル | 4 モデル全て (2×2 factorial)                             |
| シナリオ   | S01, S02, S05, S06, L01, L02（6 個）                    |
| N per cell | 3                                                        |
| 総 run 数  | 4 × 6 × 3 = **72 runs**                                  |
| 推定時間   | 1 run 平均 3-5 分（small model は速い）→ 3.6-6 時間       |

4 モデル × 6 シナリオ × 3 run。各 cell 3 run で residual (within-cell variance) を推定し、factorial ANOVA 相当 の分解に持ち込む。small model は 1 run ≤ 5 分で収まるので、並列化なしでも半日圏内。

### Phase 2 前に必要なこと

1. **OpenRouter API key を OpenCode に auth** — 現状 `zai-coding-plan` / `llama.cpp` だけ auth 済み。4 モデル使うには:
   ```bash
   opencode auth login   # 対話で OpenRouter を選び API key を貼る
   ```
2. **MCP 設定** — `opencode.json` に gaottt を宣言済み（project root）。sandbox path は run ごとに書き換える or runner 側で環境変数渡し
3. **シナリオ runner** (`scripts/eval_run_scenario.py`、次実装) — Step A で empirical schema 確定、下記参照

### Step A 成果 — OpenCode `--format json` event schema (実測)

2026-04-25、`opencode 1.3.17` + `zai-coding-plan/glm-4.5-flash` で probe。MCP tool 呼び出し + DB 書き込みも end-to-end で動作確認済み。

**4 種の event type:**

| type          | 意味                                    | 主要 fields                                       |
| ------------- | --------------------------------------- | ------------------------------------------------- |
| `step_start`  | LLM 生成ステップの開始                  | `sessionID`, `part.messageID`                     |
| `text`        | assistant の text chunk                 | `part.text` (空文字列もあり tool-only ステップ)    |
| `tool_use`    | MCP tool 呼び出し (完了時に 1 event)    | `part.tool`, `part.state.input/output/time`       |
| `step_finish` | ステップ終了 + トークン/コスト          | `part.reason`, `part.tokens.*`, `part.cost`       |

**tool_use の詳細 (runner が parse する中心):**
```json
{
  "type": "tool_use",
  "sessionID": "ses_...",
  "part": {
    "type": "tool",
    "tool": "gaottt_remember",          // ★ MCP server prefix "gaottt_" が自動付与
    "callID": "call_...",
    "state": {
      "status": "completed",             // "completed" | "error" | ...
      "input": { "content": "..." },     // tool への引数
      "output": "Remembered. ID: ...",   // MCP formatter の出力 (人間可読)
      "time": { "start": 1777065263967, "end": 1777065265473 }
    }
  }
}
```

**step_finish の metric fields:**
```json
{
  "part": {
    "reason": "tool-calls" | "stop",
    "tokens": { "input": ..., "output": ..., "reasoning": ..., "cache": { "read": ..., "write": ... } },
    "cost": 0.0
  }
}
```

**Runner 実装の含意:**

1. **sessionID は毎 event に入っている** → 1 ターン目の最初の event から抜いて、2 ターン目以降 `opencode run -s <id>` で継続
2. **MCP tool 名は `gaottt_*` prefix 付き** → scoring/expected の照合は prefixed 名で行う。S00 の expected `remember` は実際 `gaottt_remember` で観測される
3. **tool の成否は `state.status == "completed"`** で判定、args は `state.input`、latency は `time.end - time.start`
4. **1 ステップ = 1 event group** (`step_start` → `text`+ → `tool_use`* → `step_finish`)。session 全体では複数ステップ（tool 呼び出し→結果受領→次ステップ→text で応答、のような）
5. **permission prompt は発生しなかった** (少なくとも MCP tool は)。`--dangerously-skip-permissions` は MCP だけなら不要

## 10. Open Questions（設計段階で未決）

- [ ] MCP bridge の実装差をどう吸収するか（特に GPT-5 は responses API だが tool routing が独自）
- [ ] judge 採点の inter-rater reliability — judge が Opus 単独だと上記の GPT 過小評価バイアスが入る可能性。2 judge 以上にするか
- [ ] L02 の held-out クエリは事前に 10 個固定するが、それ自体がモデル差を enable しうる。クエリ自体を別モデルで生成してランダム化する案もある
- [ ] Open-ended scenario の比較可能性 — タスク未完了で終わるとフェアに比較できない。打ち切り条件を決めるべき

## 11. 関連資料

- [`docs/wiki/Architecture-Overview.md`](../wiki/Architecture-Overview.md) — GaOTTT 設計全体
- [`docs/wiki/MCP-Reference-Index.md`](../wiki/MCP-Reference-Index.md) — 25 ツール仕様
- [`docs/wiki/Reflections-Five-Layer-Philosophy.md`](../wiki/Reflections-Five-Layer-Philosophy.md) — 理論背景（物理 / TTT / 生物 / 関係 / 人格）
- [`SKILL.md`](../../SKILL.md) — 被験モデルに渡す唯一のプロンプト
