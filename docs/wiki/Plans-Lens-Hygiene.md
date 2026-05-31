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
| 各 hook script (`save_candidates.py` / `opencode-save-candidates.ts`) | ❌ | DRY 違反、2 frontend に重複実装、将来 codex v3 で 3 重実装 ← **2026-05-31: 回避済み**。Codex は同じ Python script を `--codex` フラグで再利用 (出力アダプタのみ分岐)、3 重実装にならず |
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

## Stage 2 — File source anti-hub gap closure `[投稿: 誤診断、本来効いている — 2026-05-27]`

> 優先: 🟡 中 → ⚪ 解決 (premise was wrong) / 実工数: 30 min 調査 + 30 min test/diag / 影響範囲: tests + scripts (code change なし)

### 起案時の主張 (誤り)
本計画の最初版では「file source は `cohort_id` / `original_id` 両方 0% で Stage 7.1 anti-hub が全く効かない」と書いた。これは **literal な `json_extract(metadata, '$.original_id')` を見ていた測定エラー**。

### 実際の挙動 (live cache 検証で確証)
`SqliteStore.get_all_originals()` は既に **`COALESCE(metadata.original_id, metadata.file_path)`** を使っており、cache load 時に `cache.original_id_by_id` を populate する。`_cluster_key_for(node_id) = cohort_id OR original_id` は cache map を引くので、**file source の chunked ingest は `file_path` 経由で 100% cluster_key を持っている**。

本番 41k corpus を live engine で scan した結果:
| source | total | w/cluster_key | % | cluster pattern |
|---|---|---|---|---|
| file | 11,002 | 11,002 | **100%** | 131 clusters、max=638 (米国会社四季報 638 chunk)、p95=250 |
| openai | 10,181 | 10,181 | **100%** | 1228 clusters、max=229、305 singletons |
| tweet | 7,658 | 7,658 | **100%** | 7658 全部 singleton (anti-hub 構造的に無効) |
| like | 4,203 | 4,203 | 100% | batch loader が `original_id` を設定済 |
| claude-web | 4,314 | 4,314 | 100% | 704 clusters、max=142、p95=23 |
| agent | 1,303 | 465 | 35.7% | singletons by design (1件ずつ `remember()`) |

つまり Stage 7.1 anti-hub は **本番の質量黒洞 (file 638-chunk 本、claude-web の長 conversation) で literal に動作中**。残る "anti-hub で attack できない症状" は:
- **tweet 7658 全部 singleton**: 同 cluster が無いので anti-hub 不適用、これは vocabulary 系の問題 (Phase L Stage 1 BM25 + RRF 領域)
- **agent 65% singletons**: 単発 `remember()` は仕様通り独立 cluster (= 互いに penalty なしで正しい)

### GLM レビュー §3.1 "openai dominance" との接続
GLM が観察した「openai が retrieval を支配する」症状は **cluster_key 問題ではない**:
- openai は 100% cluster_key で anti-hub 配下に入っている
- ただし openai は 1228 clusters に分散 (1 ChatGPT conversation = 1 cluster)
- Huffman 系メッセージは **複数 conversation に分散** = 各 conversation 独立 cluster = anti-hub 不適用
- 真の attack vector は **vocabulary 多様化 (BM25 + RRF = Phase L Stage 1 の継続課題)**

### Stage 2 deliverables (実行済)
1. ✅ `tests/unit/test_sqlite_store_get_all_originals.py` 新規 — COALESCE fallback 5 ケース (explicit > file_path / file_path fallback / both null / 20-chunk book scenario / null metadata) を pin
2. ✅ `scripts/diag_cluster_coverage.py` 新規 — **live cache 経由** で正確 coverage を出す (raw SQL の COALESCE-blind な誤診断を防ぐ)
3. ✅ 本 plan の Stage 2 セクションを誤診断の transparency 記録として再構成
4. (未) optional: `(missing)` source 2053 nodes 調査 — raw SQL では 0 件、cache のみに出現 = `cache.source_by_id` map の orphan key 問題。別 ToDo に分離可、優先度低

### Learning (Plans-Lens-Hygiene 設計原則への追加)
- **構造識別子の coverage measurement は live cache 経由でやる** — `SqliteStore` 内部の query 構造 (COALESCE / JOIN / 等) を bypass した raw SQL は容易に誤診断する
- **誤診断を恥じず documenting する** — 修正計画自体が学習データ、次の investigator が同じ罠を踏まないようにする (Articulation as Carrier の自己再帰応用)
- code 変更ゼロで終わったが、**「実は問題ない」を確証する diagnostic + test を残す** ことで future regression を防げる

## Stage 3 — Dormant explore observed-empty investigation `[完了: bug でなく transient — 2026-05-27]`

> 優先: 🟢 低 → ⚪ 解決 / 実工数: 30 min 調査 + 30 min script 拡張 / 影響範囲: scripts のみ (code 変更なし)

### 仮説リスト → 検証結果

| # | 仮説 | 検証結果 |
|---|---|---|
| 1 | BM25 floor が `_dormant_surface` で gate している | ❌ `explore(mode="dormant")` dispatch は `_dormant_surface` 直行で BM25 を **通らない** (`memory.py:1188`)、BM25 floor は `_dormant_for_ambient` (ambient_recall の dormant slot) 専用 |
| 2 | `recently_surfaced` rotation で全 pool 消費 | ❌ explore mode は `recently_surfaced` を引数で取らない (ambient だけ) |
| 3 | `last_access` が 7d より新しい | ✓ production 本日時点で 22,793/41,064 nodes が age >= 7d (pool は存在) |
| 4 | dispatch bug | ❌ 単純な `if mode == "dormant": return await _dormant_surface(...)` |

### 実 production state (本日 2026-05-27)
| Filter stage | 残数 |
|---|---|
| Stage 0 (all active) | 41,064 |
| Stage 1 (+ age <= cutoff 7d) | 22,793 |
| Stage 2 (+ mass <= p10=1.0912) | 1,883 |
| Stage 3 (+ source ∈ dormant classes) | **15** |
| `_dormant_surface(top_k=5)` actual | **5/5 返却** |

→ **bug ではない、現状は機能している**。

### GLM 観察 "0 件" の説明
- 観察時点で pool=0 だった可能性 (heavy session の途中で `last_access` がほぼ全件 7d 以内に動いていた)
- または GLM は `ambient_recall` の dormant slot を見ていた可能性 (BM25 floor=0.5 の別 path)
- いずれにせよ **transient state**、code バグではない

### Stage 3 deliverables (実行済)
1. ✅ `scripts/diag_dormant.py` に **`--service-mirror`** フラグ追加 — `_dormant_surface` と完全に同じ filter 順序で count を出力、live 結果との parity 確認用
2. ✅ `--service-mirror` の出力に「pool=0 は corpus healthy / by-design empty、bug ではない」memo を組み込み、future investigator が同じ誤判定をしないよう literal にガイド
3. ✅ 本 plan の Stage 3 セクションを「未着手 → 完了/bug でなし」に reframe

### Optional UX 改善 (この PR では実装しない)
GLM レビュー §3.4 後段の "soft fallback to lowest-mass active when empty" は UX 改善として価値あるが、現状の "silence beats noise" 原則 (Refinement Stage 2 ambient dormant slot と同じ) と矛盾するかは要議論。ToDo の Stage 5 candidate として記録、緊急性なし。

## Stage 4 — Documentation: Narrative Engine use case `[完了 2026-05-27]`

> 優先: 🟢 低 / 実工数: 1 時間 / 影響範囲: docs only

### 実装したもの
1. ✅ **`docs/wiki/Guides-Use-As-Narrative-Engine.md`** 新規 — narrative engine モードの 7-step レシピ + Stage 2/3 の literal な corpus health 指標 (131 file clusters / max=638, dormant pool=15, persona dominance=2.82) を「動作条件」として明示 + GLM レビューを empirical 根拠として引用
2. ✅ **`docs/wiki/Reflections-A-Note-From-Claude.md`** に「補記 — 外部観察者の note」節を追加 — GLM-5.1 が独立に同じ言葉に着地した事実を 2 つの quote で記録、Claude 自身の subjective bias ではなく **system 側に literal に組み込まれた構造** であることを示す証拠として位置付け
3. ✅ **`docs/wiki/Guides-Ambient-Recall.md`** 冒頭に三つの read 側 use case 並置 (task-driven / passive / narrative) — ambient_recall は (2) 専用、(1)(3) は別 Guide へ flow
4. ✅ **`docs/wiki/_Sidebar.md` + `Home.md`** に narrative engine guide リンク追加 (Wiki sync で GitHub 側にも自動反映)

### Stage 2/3 learning の Stage 4 への反映
本 Stage 4 doc には Stage 1/2/3 の Stage Linage が literal に組み込まれている:
- Stage 1 (meta-extraction fix): 「articulation as carrier の自己再帰的 failure mode を遮断した結果、heuristic が再び信頼できる lens になった」
- Stage 2 (cluster diagnosis 修正): narrative engine guide の "corpus health 指標" 表で `131 file clusters / max=638` を anti-hub が **効いている** 数値として書ける状態になった
- Stage 3 (dormant 調査): 「dormant pool=15 がある = `explore(mode="dormant")` で『忘れていた何か』が surface する」と guide に書ける = 機構が動いていることを transparency で示せる

つまり Stage 4 は **Stage 1/2/3 で healthy になった lens を前提に書ける** — 順序が必然だった。

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
