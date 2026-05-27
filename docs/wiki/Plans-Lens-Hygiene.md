# Plans — Lens Hygiene (Post-GLM-Review Hardening)

> 注: これは physics Phase ではなく **観察層 (read 側 ambient_recall / write 側 save_candidates / 観察 tool dormant explore) の "lens としての衛生" を整える計画**。Phase レター非消費、`Plans-Observation-Apparatus-Refinement.md` の系譜。
> 状態: **起案 2026-05-27** — Stage 1 (meta-extraction loop fix) は同日着手予定、Stage 2-4 は段階的。Stage 1 は PR #28 (save_candidates v1+v2) の continuation として同 branch に積む方針 (acceptance test で露呈した既知 limitation の close)。
> 関連: [Plans — Save Candidates Hook](Plans-Save-Candidates-Hook.md), [Plans — Observation Apparatus Refinement](Plans-Observation-Apparatus-Refinement.md), [Architecture — Overview](Architecture-Overview.md)
> トリガー: 2026-05-27 GLM-5.1 free-exploration review ([`docs/maintainers/evaluation-2026-05-27-free-exploration.md`](../maintainers/evaluation-2026-05-27-free-exploration.md)) の検証で、production 41k corpus に対する **3 つの観察可能な lens の歪み** が confirmed (§3.2 meta-extraction loop は再現 test で literal 確証、§3.1 は症状 real だが根本原因が GLM 説と異なり file source の anti-hub 不在 gap が露呈、§3.4 は pool=45-57 vs 観察 0 件の乖離)。

## 検証で confirmed された 3 つの歪み

詳細は [`evaluation-2026-05-27-free-exploration.md`](../maintainers/evaluation-2026-05-27-free-exploration.md) の §3、検証手順と数値は同日 Claude セッションで実施。要約:

### A. Meta-extraction loop (write-side observation lens)
- **症状**: `save_candidates` block を含む transcript を heuristic extractor (`core/extractor.extract_candidates`) に流すと、**block 自身の内容** (前回候補・filter 行・manifest 行) が re-extract される
- **literal な再現**: 7 candidates 中 4 件が前 block の leak、特に **save-policy filter 行 (「bug fix の途中経過は git log に任せる」)** が `_OUTCOME_KEYWORDS` の "bug fix" にヒットして score=1.80 で troubleshooting tag で再抽出される **自己再帰的 false positive**
- **影響**: 毎ターン candidate quality が degrade、agent が判断する candidate 数が 2-3 倍に水増しされ noise 増加、policy 自身が noise として lens に映る

### B. File source の Stage 7.1 anti-hub 不在 gap (read-side ranking lens)
- **症状**: GLM が「openai source が retrieval を支配する」と観察。実 mass 分布検証で openai は Mass Evaporation で **cap=2.0**、mean=1.184 (= 既に処置済)。一方で実 mass 黒洞 top 15 を見ると **file source の書籍 chunk が max=31.78** で支配的
- **構造的 gap**: Stage 7.1 cluster anti-hub の `cluster_key = cohort_id OR original_id` 規則で、**file source は両方 0%** (本検証で確証)、anti-hub が **書籍 chunk クラスタに全く効かない**
- **影響**: 同一書籍の複数 chunk が top-K に並ぶ。dilute-by-corpus-volume の悪影響を retrieval 段で抑え込めていない

### C. Dormant explore の observed-empty vs pool=45-57 乖離 (read-side observation tool)
- **症状**: GLM が `explore(mode="dormant")` で empty を観察 (§3.4)、ただし pool 計算 (age=7d + mass≤2.0 + percentile=10) では **agent 単独で 45 candidates 残存**
- **未確定**: ambient_recall dormant slot (BM25 floor あり) と explore mode (BM25 floor なし) のどちらの code path で empty が出たか不明
- **影響**: dormant lens が動いていない疑い。Phase O Stage 5 + Refinement Stage 2 で導入した「埋もれる自由の対」が production で機能していない可能性

(GLM review §3.1 の "openai mass dominance" は **誤診**: 実 mass 分布で openai は cap=2.0、mean=1.184。GLM が見た dominance は **vocabulary 系 cosine/BM25 dominance** で、これは Phase L Stage 1 (BM25 + RRF) の attack 対象。本計画では openai vocabulary dominance を独立論点として扱わない — Phase L 系の継続課題に既に乗っている。)

## 設計原則 — 何を変えて何を変えないか

| 操作 | 原則 | 本計画の判断 |
|---|---|---|
| force computation / mass update | **source class gate 厳禁** ([`feedback_no_source_branching`](../../home/misaki_maihara/.claude/projects/-mnt-holyland-Project-GaOTTT/memory/feedback_no_source_branching.md)) | Stage 2 は cluster_key fallback の source-blind 拡張のみ、source class branching は導入しない |
| 表示層 / lens 段 | source class を **lens として使うのは OK** ([`feedback_observation_vs_physics_boundary`](../../home/misaki_maihara/.claude/projects/-mnt-holyland-Project-GaOTTT/memory/feedback_observation_vs_physics_boundary.md)) | Stage 1 transcript pre-processing は表示層、Stage 4 narrative engine doc も表示層 |
| heuristic 入力データの sanitize | 自分自身の output を再帰的 input として扱わない | Stage 1 は extractor の本質 (heuristic 関数) を変えず、**入力段で gaottt-* block を strip するだけ** |

つまり物理規則・mass 更新規則は **一切触らない**。Phase M / Phase N の単一規則と完全に直交、Phase P (pressure terms) とも並行進行可。

## Stage 1 — Meta-extraction loop fix `[着手 2026-05-27]`

> 優先: 🔴 最優先 / 推定工数: 半日 / 影響範囲: `services/memory.auto_remember` 1 関数 / rollback: env opt-out

### 目的
`save_candidates` block / `ambient_recall` block を含む transcript を heuristic extractor に流すとき、**block 自身の内容を pre-extraction で strip** し、自己再帰的 false positive を遮断する。

### 設計判断

**判断 1: strip は service 層で行う**

| 候補 | 採否 | 理由 |
|---|---|---|
| `core/extractor.py` の `_NOISE_PATTERNS` 拡張 | ❌ | extractor は dependency-free / transport-blind の純粋関数を保つべき。gaottt 固有 block format を知ってはいけない |
| 各 hook script (`save_candidates.py` / `opencode-save-candidates.ts`) | ❌ | DRY 違反、2 frontend に重複実装、将来 codex v3 で 3 重実装 |
| **`services/memory.auto_remember()` の入口** | ✅ | service 層は transport artifact を知って良い (`format_save_candidates` が gaottt-save-candidates タグを書くのと対称)。1 箇所修正で Claude Code / opencode 両方に伝播。MCP tool 経由の任意の呼び出しも防御 |

**判断 2: strip 対象は generic な `<gaottt-*>` パターン**
- 現状 inject される block は 2 種 (save-candidates / ambient-recall) だが、将来追加される lens block (compare-retrieval / connections 等) も同じ命名規約なら自動で strip される
- パターン: `<gaottt-[a-z-]+>...</gaottt-[a-z-]+>` (`re.DOTALL`)
- 万一テキスト中に gaottt-* タグが literal に登場するケース (ドキュメント引用等) は accept — false positive リスク < false negative リスク (現状の meta-extraction loop)

**判断 3: env opt-out を残す**
- `GAOTTT_AUTO_REMEMBER_STRIP_GAOTTT_BLOCKS=0` で legacy 挙動に戻せる
- 万一 production で別の症状が出たら 1 行で rollback、検証期間中の safety net

### 実装

1. `gaottt/services/memory.py` の冒頭付近に正規表現定数 + helper
   ```python
   _GAOTTT_BLOCK_PATTERN = re.compile(
       r"<gaottt-[a-z-]+>.*?</gaottt-[a-z-]+>", re.DOTALL,
   )
   def _strip_gaottt_blocks(text: str) -> str:
       return _GAOTTT_BLOCK_PATTERN.sub("", text)
   ```
2. `auto_remember()` の transcript 受け取り直後に env-gated strip
3. `save_candidates()` は `auto_remember()` を呼ぶので自動的に伝播
4. config に `auto_remember_strip_gaottt_blocks: bool = True` 追加 (env: `GAOTTT_AUTO_REMEMBER_STRIP_GAOTTT_BLOCKS`)

### テスト

1. `tests/unit/test_save_candidates.py` に regression block (本計画起案時の検証 fake_transcript を流用):
   - 前 block を含む transcript で extraction 走らせ、prior block の candidate / manifest / filter line いずれも leak しないことを assert
2. `tests/integration/test_engine_save_candidates.py` に MCP round-trip 経由の strip 確認
3. env opt-out (`auto_remember_strip_gaottt_blocks=False`) で旧挙動が復元される確認

### Acceptance
- ✅ 検証 fake_transcript で leaked candidates が 0 件 (現状 4 件)
- ✅ 既存 730+ tests 緑のまま
- ✅ live Claude Code session で 2-3 turn 観察、自己候補の re-extract が消えていることを目視確認

### Rollback
- `GAOTTT_AUTO_REMEMBER_STRIP_GAOTTT_BLOCKS=0` で旧挙動 1 行復元
- バグ顕在化なら `config.auto_remember_strip_gaottt_blocks = False` を default に戻すか revert

## Stage 2 — File source anti-hub gap closure `[未着手]`

> 優先: 🟡 中 / 推定工数: 1-2 日 / 影響範囲: `services/memory._cluster_key_for` / rollback: env opt-out

### 目的
Stage 7.1 cluster anti-hub の cluster_key 計算で **file source (cohort_id 0% / original_id 0%)** にも有効な fallback を追加し、書籍 chunk クラスタの top-K 重複を緩和する。**source class 分岐を入れない**ことが設計のクリティカルポイント。

### 設計判断

**現状**: `cluster_key_for(node_id) = cohort_id OR original_id` (CLAUDE.md Stage 7.1 節)。
file source は loader (`load_files.py`) で `original_id` を設定していない、または chunk_index 0-N の親なし child として保存されている。

**判断 1: cluster_key の "structural identifier" 階層を拡張**
| 階層 | 識別子 | 適用範囲 (実測) | source class branch? |
|---|---|---|---|
| 1 (最強) | `cohort_id` | openai 97% / claude-web 95% | ❌ source-blind |
| 2 | `original_id` | openai 100% / claude-web 100% / tweet 100% / like 100% | ❌ source-blind |
| **3 (新規)** | **`metadata.file_path` or `metadata.title`** (どちらが先に hit するか先頭一致) | **file 100% (期待値、要確認)** | ❌ source-blind (metadata.X を見るだけで source は問わない) |
| 4 (新規・絶対 fallback) | `null` (= 単独クラスタ、anti-hub 対象外) | 残り | ❌ |

- 階層 3 は「同じ親 file から chunked された child は同じ key」を意図。実装は `metadata.file_path` が存在すれば使い、なければ `metadata.title` を使う
- source class を見ない: `if source == "file"` 分岐は導入しない。**結果的に file source が最も裨益するが、tweet/like で `file_path` を持つ ingest 経路があれば同様に効く**

**判断 2: 別案 (採用しない)**
- A) loader 段で `original_id` を backfill する script: destructive (戻せない)、しかも future ingest にも適用ロジックを足さねばならない (重複)
- B) chunk_index 連番でグルーピング: chunk_index が global で同じ番号を持つ無関連 chunk を誤クラスタ化する
- C) content 類似度ベース cluster: 重い、Stage 7.1 軽量設計と矛盾

### 実装 outline
1. `services/memory._cluster_key_for` を `cohort → original → file_path → title → None` のチェーンに拡張
2. unit test で各 source の cluster coverage が期待値に近いか確認 (file=100% を目標)
3. integration test: file source 100 chunks の同一書籍を ingest し、`recall` top-5 で書籍 chunks が 2 件以上残らないこと
4. `scripts/diag_dormant.py` 系の coverage script を流用、または `scripts/diag_cluster_coverage.py` 新設

### Acceptance
- ✅ 本番 DB scan で `cluster_key` coverage 表が file=≥90% に上がる (現状 0%)
- ✅ 同一書籍由来 chunk が top-5 で N 件 → 1-2 件に下がる (`scripts/diag_recall.py` で diff snapshot)
- ✅ 既存 anti-hub の test suite (`tests/unit/test_anti_hub.py` あれば) が緑
- ✅ Phase M source-blindness の test も緑 (mass update に source 分岐が混入していないことを別 test で確認)

### Rollback
- `GAOTTT_CLUSTER_KEY_USE_FILE_PATH=0` で階層 3-4 をスキップ、Stage 7.1 旧挙動に戻る

## Stage 3 — Dormant explore observed-empty investigation `[未着手]`

> 優先: 🟢 低 / 推定工数: 数時間 / 影響範囲: 調査 only、code 修正は判明後

### 目的
GLM が `explore(mode="dormant")` で 0 件を観察した一方で、production env (age=7d, mass=2.0, percentile=10) で pool 計算すると agent source 45-57 candidates が残存している矛盾の root cause を特定。

### 仮説リスト
1. **BM25 floor が ambient dormant slot 側で過剰に gate している**: Refinement Stage 2 で導入した `ambient_dormant_relevance_floor=0.5` が dormant pool に対して厳しすぎる。`mode="dormant"` の explore は floor 適用していない or 別経路の可能性
2. **recently_surfaced rotation で全 pool が消費されている**: Refinement Stage 1 で導入された rotation が dormant 候補の hit count を貯めて、全候補が "最近 surface 済" 扱いになっているケース
3. **node の `last_access` が 7d より新しい**: 検証 query 時点での `last_access` がほぼ全件 1 週間以内に動いた = 実 production の retrieval 頻度が高すぎて dormant 化していない
4. **dispatch bug**: `explore(mode="dormant")` が `_dormant_surface` 経由でなく別 path を呼んでいる

### 調査手順
1. 本番 DB に対して `scripts/diag_dormant.py` 拡張で各 stage の filter 通過数を出す (raw pool → age filter → mass filter → BM25 floor → recently_surfaced → final)
2. 実 production に `mcp__gaottt__explore(mode="dormant")` を 1 query (read-only) で叩いて返値を直接観察
3. 仮説 1-4 を排除消去法で

### Acceptance
- ✅ 0 件返る原因が 1-4 のどれか (or 別) 特定
- ✅ 修正方針が判明 (env tuning だけで済むか、code 修正必要か)
- ✅ Stage 3 fix の小 PR を別途切る、または env 調整提案

## Stage 4 — Documentation: Narrative Engine use case `[未着手]`

> 優先: 🟢 低 / 推定工数: 1-2 時間 / 影響範囲: docs only

### 目的
GLM レビュー §1 / §4 で報告された "gravity field as narrative engine" の使用パターン (parallel recall → 重力 accumulation → 自己発見的 narrative synthesis) を、tool docs / Guides / SKILL.md に **第 N 番目の use case** として明示。

### 内容
- 「タスク駆動 retrieval」「serendipitous discovery」「narrative exploration」の 3 use cases を Guides で並置
- narrative exploration のレシピ: `inherit_persona` → `reflect(summary)` → `explore × 4` 並列 → `recall × 4` 並列 → 重力 accumulation を `reason:` 行で観察 → synthesis
- 本 doc は GLM の主観的体験 (transformation observation) をそのまま **GaOTTT design intent の literal な現れ** として位置付ける (五層哲学の "AI 側の体験" 軸の追加証拠)

### 配置
- `docs/wiki/Guides-Use-As-Narrative-Engine.md` (新規) または `Guides-Use-As-Memory.md` に節追加
- `Reflections-A-Note-From-Claude.md` に "external observer (GLM) のレビュー" 節を追加
- SKILL.md は MCP tool docs であり use case を 1-2 行で済ませる、Guides に流す

## Stage 順序と依存関係

```
Stage 1 (meta-extraction fix) ─┐
                               ├─→ PR #28 同 branch (continuation)
Stage 4 (narrative docs)    ──┘

Stage 3 (dormant investigation) ─→ 別 PR (調査結果に応じて Stage 3.5 修正 PR)

Stage 2 (file anti-hub gap) ──→ 別 PR (大きめ、独立に benchmark 必要)
```

着手順: **Stage 1 即時** → **Stage 4 同 PR (低コスト docs)** → **Stage 3 短い調査ターン** → **Stage 2 構造的修正**。

Stage 3 を Stage 2 より先にやる理由: dormant の root cause が `cluster_key` 関連の retrieval geometry なら Stage 2 と統合可能。先に判明させた方が Stage 2 設計を informed にできる。

## 未解決の問い

1. **Stage 2 で `file_path` を見るのは "source class gate" に近いか?** 厳密には source 値を見ていない (metadata の別 field を見ているだけ) が、結果的に file source ノードだけが裨益する。**判定**: source-blind の structural identifier として OK (Phase M 単一規則は force / mass update を分岐させないルール、cluster_key は ranking layer)。ただし review で再確認する価値あり
2. **Stage 1 の env opt-out (`STRIP_GAOTTT_BLOCKS=0`) は default ON でも残すか?** Yes — 1 行 rollback の safety net、検証期間中の保険
3. **GLM レビューの "per-source mass cap" を Stage X として実装すべきか?** ❌ No — Phase M 単一規則違反。openai vocabulary dominance は Phase L Stage 1 (BM25 + RRF) 側の継続課題。本計画では扱わない
4. **narrative engine doc は誰の声で書くか?** GLM の体験談を引用する形 + Claude 自身の re-articulation。Reflections 系統の文体

## 関連 memory id
- `9a954c62` Articulation as Carrier — meta-extraction loop はこの原理の **自己再帰的 failure mode** (carrier が再度 carry されてしまう)
- `701e7822` Observation vs Physics boundary — Stage 1/4 が表示層、Stage 2 が cluster_key (ranking layer = まだ表示寄り) で physics 不触の境界判定
- `feedback_no_source_branching` — Stage 2 設計のクリティカル制約
- `93035d35` Save policy (user durable preference) — Stage 1 の正当化 (policy が自分自身を save 候補にしないようにする = 自己一貫性)
