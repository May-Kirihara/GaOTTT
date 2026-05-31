# Plans — Instruction Surface Hygiene (指示表層と hook harness の衛生)

> 注: これは physics Phase ではなく、**observation ロジックですらない** — caller (LLM) が読む指示テキスト (MCP instructions / tool docstring / SKILL.md) と、それを運ぶ hook harness (登録 / timeout / fail-safe / frontend parity) という **interface 層** だけを整える計画。Phase レター非消費。[Plans — Lens Hygiene](Plans-Lens-Hygiene.md) の姉妹 — あちらが「lens が映す中身の衛生」なら、本計画は「**lens のラベル・取説・配管の衛生**」。
> 状態: **Stage 0 / 1 / 3 実装済 (2026-05-31, branch `feat/instruction-surface-hygiene`, commit `f594352`+`a8526a4`)** — caller 向けテキスト系の低リスクバッチを GLM-5.1 委託 + Opus 検証で完了 (token 総量は 12104 で不変 = signal-to-noise 改善、全 suite 786 passed + mcp_smoke green)。**Stage 2 (formatter token budget) と Stage 4 (hook harness) は高リスク別 PR で未着手** (§10 の分離方針通り、owner go 待ち)。
> 関連: [Plans — SKILL.md Improvement](Plans-SKILL-MD-Improvement.md), [Plans — Observation Apparatus Refinement](Plans-Observation-Apparatus-Refinement.md), [Plans — Lens Hygiene](Plans-Lens-Hygiene.md), [Plans — Phase O (TTT Observability)](Plans-Phase-O-TTT-Observability.md)
> トリガー: 2026-05-31 に hook / MCP / skill の **指示テキストを context engineering・harness engineering の 2 軸で監査**。3 フロントエンド (Claude Code / opencode / Codex) の hook、MCP server の instructions + 27 docstring、SKILL.md、そして実際に context へ注入される `formatters.py` の出力を精読。地力は高い (fail-safe の徹底・relevance gate による silent 注入・単一 source-of-truth) が、**「実装者向けの版管理語彙」が「caller 向け API リファレンス」に漏れている**点と、**毎ターン / 毎 recall に注入されるテキストの token 予算が一貫していない**点が signal-to-noise を確実に削っている。

## 1. 背景 — 何を監査したか

| 層 | 対象ファイル | caller が読むもの |
|---|---|---|
| MCP instructions | `gaottt/server/mcp_server.py:80-112` | session 常駐の server 概要 (全 27 ツールを 1 段落に連結) |
| Tool docstring | 同 `:120-943` | FastMCP が tool description として LLM へ渡す 27 個の docstring |
| Skill | `SKILL.md` / `.claude/skills/gaottt/SKILL.md` (同期、373 行) | 運用リファレンス |
| 注入ブロック | `gaottt/services/formatters.py::format_ambient` / `format_save_candidates` | **毎ターン** prompt 末尾に注入される `<gaottt-*>` block |
| recall trailer | 同 `::format_recall` (`_format_breakdown` / `_format_training_delta` / `_format_routing_hint`) | **毎 recall** に付く breakdown 行 + `## 訓練差分` + auto-routed reflect |
| Hook 配管 | `scripts/hooks/*.py` (Python ×3) + `*.ts` (opencode ×2) + `.codex/hooks.json` + `~/.claude/settings.json` | (caller には不可視、harness の robustness) |

監査は 2 軸:
- **Context Engineering** — caller の context window を占有するテキストの signal density / token budget / 曖昧さ / 重複 / 誤誘導。
- **Harness Engineering** — hook の fail-safe / timeout 階層 / 二重注入防止 / frontend parity / 登録の可搬性。

## 2. 設計原則 — 何を変えて何を変えないか

本計画は GaOTTT の [`feedback_observation_vs_physics_boundary`](../../home/misaki_maihara/.claude/projects/-mnt-holyland-Project-GaOTTT/memory/feedback_observation_vs_physics_boundary.md) を **さらに外側に一段** 適用する:

```
physics 層    : mass / force / displacement / velocity / edge weight     ← Phase M/N/P/Q が触る
observation 層: slot 構成 / gate 閾値 / dormant 発掘 / reason line       ← Observation Apparatus Refinement / Lens Hygiene が触る
interface 層  : 指示テキスト / 注入文字列の整形 / hook 配管             ← ★ 本計画はここだけ
```

本計画は **どの記憶を surface するか (observation) も、どう力学が動くか (physics) も一切変えない**。変えるのは「surface した結果を caller にどう言葉で見せるか」と「その配管の堅牢性」だけ。

### 2.1 [Plans — SKILL.md Improvement](Plans-SKILL-MD-Improvement.md) との関係 — 矛盾しない

SKILL.md Improvement は「**物理メタファー** (Hawking radiation / gravitational lensing / Lagrange point) を **付ける**」計画だった。本計画 Stage 1 は「**版管理ラベル** (Phase J Stage 2 / Refinement Stage 3) を **削る**」計画。一見逆向きだが両立する:

| 語彙の種類 | 例 | caller への価値 | 本計画の扱い |
|---|---|---|---|
| **物理メタファー** | `gravitational lensing`, `Hawking radiation`, `genesis kick`, `supernova cohort` | 動作の直感を与える + literal 説明とペア | **残す** (SKILL.md Improvement の資産) |
| **版管理ラベル** | `Phase J Stage 2`, `Phase O Stage 3`, `Refinement Stage 3`, `Lateral Association Stage 1` | ゼロ (caller は Phase J が何かを知らない) | **削る** (動作説明は残し、ラベルだけ落とす) |

メタファーは「機能の名前」、版ラベルは「いつ実装したかの履歴」。履歴は wiki / [Plans — Roadmap](Plans-Roadmap.md) が SoT であり、caller 向け表層に持ち込む必然がない。

## 3. 単一規則 — Interface Surface Conservation

```
∀ change in this plan:
  must not modify {
    retrieval geometry, mass / force / displacement / velocity,
    slot composition (どの記憶を direct/lensing/dormant に入れるか),
    gate 閾値 (BM25 floor, min_score, lensing gap), edge weight
  }
  may modify {
    tool docstrings, MCP instructions, SKILL.md prose,
    formatter の出力文字列 (truncate 長 / trailer を出す条件),
    hook 登録 / timeout / fail-safe ガード / frontend parity
  }
```

### 3.1 何が保証されるか

| 性質 | 帰結 |
|---|---|
| physics 不変 | Phase M/N/P/Q の rollback flag を全 OFF にしても本計画の挙動は変わらない |
| observation 不変 | どの記憶が surface するかは不変 — 同じ recall は同じ id 集合を返す。**見せ方 (長さ・ラベル)** だけ変わる |
| 既存テスト互換 | formatter 出力に触れる Stage は **既存 substring assertion を壊さない範囲で default を決める** ([CLAUDE.md](https://github.com/May-Kirihara/GaOTTT) 鉄則: `tests/integration/test_mcp_tools.py` 等が specific substring を assert) |
| ロールバック粒度 | 各 Stage が独立に env opt-out / config default で戻せる |

## 4. 監査で見つかった指摘 → Stage マッピング

| ID | 指摘 | 軸 | 優先 | Stage |
|---|---|---|---|---|
| C1 | 版ラベル (Phase X / Stage Y) が docstring / instructions / SKILL に大量漏れ | CtxEng | 🔴 | S1 |
| C2 | ambient block の content が無 truncate (毎ターン注入の最大コスト源) | CtxEng | 🔴 | S2 |
| C3 | recall trailer (訓練差分 / breakdown) が output_mode と独立に常時 ON | CtxEng | 🟡 | S2 |
| C4 | cross-lingual 警告ほかの三重複 (instructions / docstring / SKILL) | CtxEng | 🟡 | S3 |
| C5 | MCP instructions が単一巨大文字列で decision tree 不在 | CtxEng | 🟡 | S3 |
| C6 | SKILL.md `ambient_recall` 節が単一巨大パラグラフ (scan 不能) | CtxEng | 🟢 | S3 |
| H1 | Codex 雛形の「machine 非依存」が実態と乖離 (`$HOME/GaOTTT` 前提の罠) | Harness | 🟡 | S4 |
| H3 | 二重注入防止が非対称 (opencode のみ marker、Python hook に無し) | Harness | 🟢 | S4 |
| H4 | save_candidates の Codex 経路が session_id parity に暗黙依存 | Harness | 🟢 | S4 |
| H5 | inject hook の 5s timeout が実態 (file read のみ) に対し過大 | Harness | 🟢 | S4 |
| H2 | fail-safe / timeout 階層 = 模範 | Harness | — | §6 守る |

## 5. Stage 詳細

### Stage 0 — Instruction token baseline `[measurement-first]`

> 優先: 🔵 入口 / 工数: 0.5 day / 影響: scripts のみ (read-only)

**目的**: Stage 1-4 の効果を before/after で測れるようにする。「何 token を節約したか」を主観でなく数値で示す ([`perf_baseline.py`](Operations-Performance-Testing.md) の精神を指示レイヤに適用)。

**実装**: `scripts/measure_instruction_tokens.py` 新規 (read-only)。

- MCP instructions / 27 docstring 合計 / SKILL.md / 代表的 ambient block (golden corpus の 1 query で実際に生成) / 代表的 recall trailer のトークン量を測る。
- tokenizer は概算で十分 (文字数ベース or `tiktoken` cl100k、本番 caller の分布に厳密一致は不要 — 相対変化を見る)。
- `--json` で before/after diff。

**Stage 0 deliverables**:
- D1. 現状 baseline を 1 度取り、本 plan §7 の「概算」を実測値に置換
- D2. `--json` 出力で Stage 1-4 の各 PR が削減量を回帰チェックできる

### Stage 1 — 版ラベル除去 (C1) `[最優先・最小労力]`

> 優先: 🔴 / 工数: 0.5 day / 影響: docstring + instructions + SKILL.md (テキストのみ、コードロジック不変) / rollback: revert (テキスト変更のみ)

**目的**: `Phase J Stage 2` / `Phase O Stage 3` / `Refinement Stage 3` / `Lateral Association Stage 1` 等の版ラベルを caller 向け表層から機械的に除去。**動作説明はそのまま、ラベルだけ落とす**。

**before / after の型** (動作説明は不変):

```diff
- auto_route: Phase O Stage 3 — when True (default), the service detects
+ auto_route: when True (default), the service detects
```
```diff
- **Training delta (Phase O Stage 2):** every recall ends with a `## 訓練差分`
+ **Training delta:** every recall ends with a `## 訓練差分`
```

**残すリスト / 削るリスト** (Stage 1 の判定基準):

| 削る (版ラベル) | 残す (物理メタファー + literal 説明) |
|---|---|
| `Phase G/H/I/J/K/L/M/N/O/P/Q Stage N` | `gravitational lensing` (+ "textually far ... bent onto its path") |
| `Refinement Stage N` / `Lateral Association Stage N` | `Hawking radiation` / `genesis kick` / `supernova cohort` |
| `(Phase O Stage 1 ScoreBreakdown ...)` の括弧注 | `astrocyte` (ただし §6.2 で literal 説明の薄い箇所は補強) |

**実装箇所**: `mcp_server.py` の instructions + 27 docstring、`SKILL.md` (+ `.claude/skills/gaottt/SKILL.md` に `cp` 同期)。

**Stage 1 D1-D3**:
- D1. docstring は MCP protocol の tool description として LLM に渡る (FastMCP 仕様) — つまり版ラベルは literal に caller の context に届いている。除去対象として正当。
- D2. **既存テストとの衝突確認**: 版ラベルを assert している test が無いことを確認 (`grep -rn "Phase O Stage" tests/`)。docstring は formatter 出力ではないので `test_mcp_tools.py` の substring とは独立のはず — 要確認。
- D3. SKILL.md は `cp` 同期を忘れない (CLAUDE.md 鉄則)。

### Stage 2 — 注入ブロック / trailer の token budget (C2 + C3)

> 優先: 🔴 (C2) + 🟡 (C3) / 工数: 0.5-1 day / 影響: `formatters.py` + `config.py` / rollback: env / config default

#### 2-a. ambient block の slot 別 content 上限 (C2)

**問題**: `format_ambient` は direct hits (`formatters.py:348`) も lensing (`:369`) も dormant (`:383`) も `m.content` を **そのまま全文**注入。`save_candidates` は 200 字 (`:585`)、`recall(compact)` は 300 字で切るのに、**毎ターン自動で出る ambient だけ青天井**。本のチャンクや長文設計判断が direct hit に来ると 1 件で数百 token を毎ターン消費。

**設計**: slot ごとに content 上限を config 化。

```python
ambient_direct_max_chars: int = 0      # 0 = 無制限 (既存挙動互換、既存テスト不破壊)
ambient_lensing_max_chars: int = 300   # lensing / dormant(ささやき) slot の上限
```

- **default 方針**: direct は `0` (既存挙動維持 = 既存 substring テスト不破壊)。lensing/dormant は `300` で切る (既存テストが lensing の full content を assert していないことを D1 で確認できれば default ON 可、衝突するなら direct と同じく `0` 始まりにして本番 env で有効化)。
- truncate は「**同じ記憶を短く見せる**」だけ — どの記憶を surface するか (slot composition) は不変なので observation 層に踏み込まない。
- 切り詰め表記は既存 `recall(compact)` の `…(N chars)` 様式に合わせ、caller が「続きは recall できる」と分かる形に。

#### 2-b. recall trailer の output_mode 連動 (C3)

**問題**: `format_recall` (`formatters.py:230-233`) は output_mode に **関係なく** breakdown 行 (各結果) + `## 訓練差分` (末尾) を付ける。SKILL.md:86 は `"ids" — header only`、`"compact" — Saves significant tokens` と説明するが、**実装は ids でも breakdown 行 (`:211-213`) と訓練差分が残る** — ドキュメントと実態の齟齬。caller が「ids は最軽量」と信じて多用すると予想外に token を食う。

**設計**: 軽量 output_mode では trailer を抑制。

```python
recall_trailer_verbose_modes: tuple[str, ...] = ("detail", "full")  # これ以外 (ids/list/compact) は trailer 抑制
```

- **Phase O 哲学との緊張**: `## 訓練差分` は [Phase O (TTT Observability)](Plans-Phase-O-TTT-Observability.md) の「caller を TTT loop の participant に昇格させる」成果。これを **消す** のは Phase O の後退。だから「**軽量 triage モード (ids/list) でのみ抑制、default の detail/full では維持**」とする — caller が意図的に triage している時だけ静かにする。
- 併せて **SKILL.md:86 の記述を実態に合わせて訂正** (「ids — header only」→ trailer 抑制が効くなら正しくなる、効かせないなら「+ breakdown + 訓練差分」と明記)。ドキュメントと実装の一致を回復する。

**Stage 2 D1-D3**:
- D1. 既存 `tests/integration/test_mcp_tools.py` / `test_ambient_*.py` が assert する substring を列挙し、default を非破壊に設定。
- D2. truncate は `_COMPACT_LIMIT` (`formatters.py:85`) と同じ「`content[:N] + …(len chars)`」様式を再利用。
- D3. `scripts/mcp_smoke.py` + `scripts/rest_smoke.py` 両方で trailer 抑制 / truncate を end-to-end 確認。

### Stage 3 — instructions の decision tree + 重複集約 (C4 + C5 + C6)

> 優先: 🟡 / 工数: 0.5-1 day / 影響: instructions 文字列 + SKILL.md (テキストのみ) / rollback: revert

#### 3-a. cross-lingual 警告の三重複を解消 (C4)

「RURI は cross-lingual でない」が **instructions (`:108-111`) + recall docstring 17 行ブロック (`:251-259`) + SKILL.md:84** の 3 箇所に長文重複。ingest にも近い注記。

- instructions は **1 文** に圧縮 (「query は対象記憶と同言語で。橋渡しは `tag_filter`」)。
- 詳細 (silent fail の理由・narrow cosine band) は **docstring 1 箇所に集約**。
- SKILL は要点 1 行 + docstring 参照。
- instructions は **session 常駐** で最も高価な場所 — ここを最短に。

#### 3-b. instructions に decision tree (C5)

`mcp_server.py:80-112` は全 27 ツールを 1 パラグラフに連結。列挙はあるが「**いつ recall / ambient_recall / explore / recall(passive) を使い分けるか**」の決定木がない。27 ツールはツール選択の認知負荷が高い。

SKILL.md の "When to use" (`SKILL.md:10-52`) は状況→ツールの対応が秀逸 — この決定木を **1 段圧縮して instructions 側にも持つ** (MCP 経由では SKILL が常時読まれない可能性があるため)。案:

```
recall          — 明示的に過去を引く (訓練ステップ、場を更新)
recall(passive) — 背景で引く (場を乱さない、自動/反復 query)
ambient_recall  — 構造化マルチスロット (hook 用、常に passive)
explore         — セレンディピティ / mode="dormant" で固定観念崩し
prefetch        — 先読みウォームアップ
remember        — 保存 / reflect — 状態点検 / Phase D — 人格・タスク層
```

#### 3-c. SKILL.md `ambient_recall` 節の箇条書き化 (C6)

`SKILL.md:126` は lensing/resonance/gate/exclude_tags/expose_breakdown/recently_surfaced を 1 段落に詰めて scan 不能。同ファイルの recall 節 (箇条書き、読みやすい) と非対称。箇条書きに割る (情報は不変、構造だけ変える)。

### Stage 4 — hook harness の堅牢化と parity (H1 + H3 + H4 + H5)

> 優先: 🟡 (H1) + 🟢 (H3/H4/H5) / 工数: 0.5 day / 影響: 雛形 + Python hook の防御 1 行 + docstring / rollback: revert

#### 4-a. Codex 雛形の「machine 非依存」を実態化 (H1)

監査で `diff` した結果、repo 同梱 `.codex/hooks.json` と実インストール済 `~/.codex/hooks.json` が **別物**:
- repo 版: `sh -c '"$HOME/GaOTTT/.venv/bin/python" ...'` (machine 非依存志向・`_comment` なし)
- インストール版: `"/mnt/holyland/Project/GaOTTT/..."` (絶対パス・`_comment` あり)

**罠**: このマシンの `$HOME` は `/home/misaki_maihara`、実 repo は `/mnt/holyland/Project/GaOTTT`。repo 雛形の `$HOME/GaOTTT` を **そのままコピーすると動かない**。CLAUDE.md は雛形を「machine 非依存」と称するが、実態は「`$HOME/GaOTTT` にクローンした人専用」で **規約外パスのユーザー (= owner 自身) には不適合**。

**対応** (どちらか):
- (i) [Tutorial-03](Tutorial-03-Connect-Your-Client.md) §E に「**`$HOME/GaOTTT` 以外に置いた場合は雛形のパスを置換せよ**」を明記し、「machine 非依存」の謳い文句を「**`$HOME/GaOTTT` 規約に従えば machine 非依存**」と正直化。
- (ii) より可搬な雛形 (例: `GAOTTT_REPO` env を読む wrapper script を 1 枚噛ませ、Claude Code / opencode / Codex の 3 フロントが同じ `GAOTTT_REPO` 解決を共有) — opencode plugin は既に `GAOTTT_REPO` を読む (`opencode-ambient-recall.ts:60`) ので、Codex/Claude もこれに揃えると 3 フロント完全対称。

#### 4-b. Python hook に二重注入 marker ガード (H3)

opencode plugin は `INJECTED_MARKER` で再注入を検出 (`opencode-ambient-recall.ts:264`) するが、**Claude Code 側の Python hook に同等ガードが無い**。現状 UserPromptSubmit は確定後 1 回なので実害ゼロだが、「frontend parity」を謳う以上 **非対称は将来の落とし穴**。Python hook 側にも marker チェックを入れ、どのフロントから呼ばれても安全側に倒す (fail-safe の対称化、コスト 1 行)。

#### 4-c. Codex の session_id parity を明記 (H4)

Codex 経路は Stop hook (`save_candidates.py` state mode、`session_id` で state ファイル命名 `:226`) → 次 UserPromptSubmit (`save_candidates_inject.py` が同 `session_id` で読む `:101`)。**Codex が両イベントで同一 session_id を渡す前提** が、この state-file 橋渡しの暗黙の依存。opencode は plugin 1 本に畳んでこの依存を消している (`opencode-save-candidates.ts` の設計が優秀) が、Codex はこの前提が docstring に明記も検証もされていない。`save_candidates_inject.py` の Codex 節に「**Codex の session_id 一致を前提とする**」を 1 文追記 (+ 可能なら smoke で確認)。

#### 4-d. inject hook の timeout 適正化 (H5)

毎 UserPromptSubmit で `ambient_recall` (最悪 6s) → `save_candidates_inject` が直列。後者は state file を read するだけ (`save_candidates_inject.py:106`) なのに `~/.claude/settings.json` / `.codex/hooks.json` で **5s budget は過大**。2s に絞り、直列累積 latency を削る (cold start 後の数分の体感に効く)。

## 6. 守るべき既存設計 (監査で「優秀」と評価、変えない)

GaOTTT 文化に倣い、良い設計も literal に記録する (撤回案・良点とも残す)。

### 6.1 Harness の模範 (H2)
- **全 hook の fail-safe**: 例外 / timeout / backend down → exit 0・無出力・ブロックしない (`ambient_recall.py:492`, `save_candidates.py:255`)。
- **timeout 階層が正しい**: Python 内 (6.0/3.0s) < 外側 hook (10/5s)、opencode は `+3000ms` headroom で「Python 側が先に clean timeout」を保証 (`opencode-ambient-recall.ts:72`)。
- **`os.write` 直書き** (`ambient_recall.py:405-417`) で asyncio teardown のバッファ落ちを回避。
- **単一 source-of-truth**: opencode plugin が MCP 呼び出しを再実装せず **同じ Python hook を spawn** (`opencode-ambient-recall.ts:177`)、Codex は `--codex` フラグで同 script 再利用 — 3 フロント分岐ゼロ。
- **state file を emit 前に delete** (`save_candidates_inject.py:113`) で二重注入を構造的に防止。
- **relevance gate で off-topic を silent** (`(関連する記憶なし)`) = ノイズ注入を構造的に防ぐ。
- **save policy を判断の瞬間に注入** (`formatters.py:572`) = just-in-time instruction の好例。

### 6.2 メタファーの literal 説明補強 (Stage 1 と同時に)
Stage 1 で版ラベルを削る一方、**メタファーだけで literal 説明が薄い箇所**は逆に補強する。例: `prefetch` docstring の "astrocyte's true workload" (`:485`) は詩的だが機能説明が弱い — 「先読みで gravity well を pre-warm し後続 recall を cache hit させる」の literal 1 文を残す。メタファー + literal のペアは context engineering のベストプラクティス。

## 7. 副次予測 — 検証可能な仮説

| 仮説 | 観測方法 | 期待値 |
|---|---|---|
| 版ラベル除去で instructions + docstring の token が削れる | Stage 0 baseline の before/after | docstring 群で測定可能な減少 (実数は Stage 0 で確定) |
| ambient truncate で長文 direct hit の毎ターン注入が減る | golden corpus の長文ヒット query で ambient block token を測る | 長文 1 件あたり数百 token → 上限内に収束 |
| 軽量モード trailer 抑制で `mode="ids"` が実際に軽量化 | `recall(top_k=20, mode="ids")` の出力 token を before/after | trailer 分 (訓練差分 + breakdown×20) が消える |
| decision tree でツール誤選択が減る | dogfooding 1 週、`ambient_recall` を直接呼ぶべきでない所での誤用回数 | 主観評価で改善 |

## 8. テスト計画

- **既存 substring 不破壊が最優先制約** (CLAUDE.md 鉄則)。Stage 1 (docstring) / Stage 2 (formatter) / Stage 3 (instructions) は全て caller 向けテキストに触れる。
  - `grep -rn "Phase O Stage\|Phase J Stage\|Refinement Stage" tests/` で版ラベルを assert するテストが無いことを Stage 1 着手時に確認。
  - `tests/integration/test_mcp_tools.py` / `test_ambient_recall_*.py` の assert substring を列挙し、Stage 2 default を非破壊に決める。
- 新規 unit: `tests/unit/test_ambient_truncate.py` (slot 別 content 上限が効く / direct=0 で無制限維持)、`tests/unit/test_recall_trailer_modes.py` (detail で trailer 出る / ids で消える)。
- Smoke: `scripts/mcp_smoke.py` + `scripts/rest_smoke.py` 両方 (parity 鉄則)。
- Stage 4 は hook 単体で `echo '{"prompt":"..."}' | python ambient_recall.py` の手動 round-trip + marker 二重注入の再現テスト。

## 9. config / env 追加

```python
# gaottt/config.py に追加 (Instruction Surface Hygiene)

# --- Stage 2a: ambient block content budget ---------------------------------
ambient_direct_max_chars: int = 0       # 0 = 無制限 (既存挙動)、>0 で direct hit を切り詰め
ambient_lensing_max_chars: int = 300    # lensing / dormant(ささやき) slot の content 上限

# --- Stage 2b: recall trailer verbosity -------------------------------------
recall_trailer_verbose_modes: tuple[str, ...] = ("detail", "full")  # これ以外は trailer 抑制
```

env opt-out / override:
- `GAOTTT_AMBIENT_DIRECT_MAX_CHARS` / `GAOTTT_AMBIENT_LENSING_MAX_CHARS`
- `GAOTTT_RECALL_TRAILER_VERBOSE_MODES` (カンマ区切り)
- Stage 4-b: `GAOTTT_HOOK_ANTI_RESTACK=1` (Python hook の marker ガード、default on、`0` で legacy)

Stage 1 / 3 はテキスト変更のみで config 不要。

## 10. Stage plan (着手順・工数)

```
Stage 0 (token baseline)     ─┐ 0.5d  measurement-first、以降の効果測定の前提
Stage 1 (版ラベル除去)        ─┤ 0.5d  最小労力・最大効果、grep 置換 + cp 同期
                              ├─→ 同 PR にまとめ可 (S0+S1 = 低リスク、テキスト/script のみ)
Stage 3 (instructions/SKILL) ─┘ 0.5-1d テキストリライト、MCP smoke

Stage 2 (token budget)       ──→ 別 PR (formatter 触る、既存 substring と要慎重)
Stage 4 (harness)            ──→ 別 PR (hook 配管、frontend 横断で smoke)
```

着手順の論理: **Stage 0 → 1 → 3 (caller 向けテキスト系、低リスク・同系統)** を先に束ね、**Stage 2 (formatter 出力、既存テスト直撃リスク)** と **Stage 4 (harness)** を独立 PR に分離。

## 11. 既存計画との緊張・直交関係

| 計画 | 介入軸 | 本計画との関係 |
|---|---|---|
| Phase M/N/P/Q | physics (mass/force/displacement) | 完全直交 — 本計画は physics に一切触れない |
| Observation Apparatus Refinement | observation (reason line / dormant slot / connections bucket) | **隣接** — あちらは lens が映す中身、本計画は lens のラベル/取説。Stage 1 の reason line を SKILL に書く時に交差 |
| Lens Hygiene | observation (meta-extraction / anti-hub / dormant empty) | **姉妹** — あちらは lens の衛生、本計画は配管とラベルの衛生 |
| SKILL.md Improvement | interface (物理メタファーを付ける) | **逆方向だが両立** — メタファー残し / 版ラベル削り (§2.1) |
| Phase O (TTT Observability) | observation (trailer を公開) | **緊張** — Stage 2b の trailer 抑制は「軽量モードのみ」に限定して Phase O 哲学を尊重 (§5 2-b) |

## 12. 関連

- [Plans — Lens Hygiene](Plans-Lens-Hygiene.md) — 姉妹計画 (lens が映す中身の衛生)
- [Plans — Observation Apparatus Refinement](Plans-Observation-Apparatus-Refinement.md) — observation 層の道具立て
- [Plans — SKILL.md Improvement](Plans-SKILL-MD-Improvement.md) — 物理メタファー付与 (§2.1 で非矛盾を整理)
- [Plans — Phase O (TTT Observability)](Plans-Phase-O-TTT-Observability.md) — trailer の出自 (§5 2-b で哲学の緊張)
- [Guides — Ambient Recall](Guides-Ambient-Recall.md) — ambient block の caller 向け解説
- [Operations — Performance Testing](Operations-Performance-Testing.md) — Stage 0 baseline の手法 (`perf_baseline.py` の精神)

### 関連 memory id
- `701e7822` [Observation vs Physics boundary](../../home/misaki_maihara/.claude/projects/-mnt-holyland-Project-GaOTTT/memory/feedback_observation_vs_physics_boundary.md) — 本計画は境界の **interface 側** (observation よりさらに外)
- `93035d35` Save policy (user durable preference) — `formatters.py:572` の just-in-time 注入 (§6.1 で「守る」と判定)
- [`project_ambient_persona_mass_dominance`](../../home/misaki_maihara/.claude/projects/-mnt-holyland-Project-GaOTTT/memory/project_ambient_persona_mass_dominance.md) — ambient persona slot の habituation (Stage 2a の truncate と同じ「毎ターン注入の token 衛生」軸)
