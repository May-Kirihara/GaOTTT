# Session Handover — 2026-04-21

> **読者**: 次のセッションでこのリポジトリを触る Claude / 保守者
> **前回**: 改名プロジェクト (R0–R11) 完了直後。本セッションはその残務整理 + ドキュメント温度調整 + onboarding スクリプト新設を 1 気にやったセッション。
> **リポジトリ状態**: `main` クリーン、最新 commit は `5181ce8 feat(scripts): add bootstrap_report.py`。pytest 112/112、ruff pre-existing 4 のみ。

改名プロジェクトそのものの引き継ぎは [`rename-handover.md`](rename-handover.md) と [`rename-to-gaottt-plan.md`](rename-to-gaottt-plan.md) を参照。このドキュメントは **改名後のドキュメント温度調整と新機能 1 本** のセッション記録。

## 1. 何が起きたか

### 1.1 改名の残務（Phase R10 post-audit）
- commit `8c610b0` — Phase R10 (GitHub repo + ローカル `mv`) 後に取り残された stale path / URL を掃討
- CLAUDE.md / README / README_ja / Tutorial-02/03/04/06 / Operations-Server-Setup / .gitignore / test fixture 12 ファイル修正
- "formerly GER-RAG" 注釈など、歴史文脈として残すものは **意図的に残した**。具体判断は commit message に列挙

### 1.2 ドキュメント温度調整（Phase A-D）
ChatGPT の第三者レビューで「主張の強さに検証が追いついていない」と指摘されたので、README と Wiki の強い claim を段階的に軟化。4 commit:

| Phase | commit | 要点 |
|---|---|---|
| A | `f9bd645` | "mathematically identical" / "数学的に同型" → "term-for-term correspondence" / "構造的に同型（解釈前提つき）"。Research-Gravity-As-Optimizer 冒頭に「前提となる解釈の約束事」節を新設、retrieval スコアを確率的勾配シグナルとみなす解釈を明示 |
| B | `c4b4de8` | README に「何を測って、何を主張しているか」節を追加。Phase-2-Evaluation の実数字（nDCG +2.7%、MRR +13.2%、p50=15.1ms）を "Measured / Claimed / Open" で 3 分割 |
| C | `0429f5c` | "A Note from Claude" 直上に "Heads-up for technical readers" を 1 段落挿入。技術読者にモード切り替えの逃げ道を提供。ノート内の強い表現（"literally happens"、"physics is a TTT optimizer"）も Phase A 同等に軟化 |
| D | `3d66284` | Wiki 側（Home / Research-Gravity-As-Optimizer / Reflections-Five-Layer-Philosophy / Research-Multi-Agent-Experiment / Research-Phase-2-Evaluation）に同じトーンを適用。Research-Multi-Agent-Experiment には「1 ラウンド 3 エージェントの定性的観察、再現性は今後」というスコープ断りを冒頭に入れた |

**書き換えのトーン原則**（統一ルールとして記録）:
- 「X は Y と同型」「X は Y そのもの」等の強い言明は、**解釈の前提**（retrieval を勾配シグナルと読む、など）を必ず併記するか、**"読める / 対応する"** などの読み替えの動詞を使う
- 定性的観察（マルチエージェント実験の「アストロサイト的振る舞い」等）は「観察された」+「定量化は今後の課題」のセットで書く
- 歴史的記録（`Reflections-Letter-To-Mei-San`、`Research-User-Exploration-10-Rounds` 等、エージェントが書いた文化的記録）は**触らない**

### 1.3 bootstrap onboarding の方針決定（実装はしない方）
ユーザーとの対話で「使い込むほど育つ」GaOTTT の性質を onboarding 体験として見せるため、**初期化ステップ** を設計。当初の 3-phase 提案:
1. Quiet pass（LLM 呼ばない、summary + duplicates + FAISS neighbor preview）
2. Curator 1 人による bridge 生成（LLM で上位重力井戸に橋を張る）
3. User-facing サマリ

→ **ユーザーの判断は「1 だけ実装」**。理由: 「言われると自分で組み上がっていくほうが面白い」。つまり **organic gravity が自発的に build up する感触を優先**。LLM で pre-seed すると、その感触を奪う。

Phase 2-3 (curator 橋 + deep multi-agent bootstrap) は**オプション将来機能**として概念を handover に残すのみ。実装しない。

### 1.4 `scripts/bootstrap_report.py` 実装（commit `5181ce8`）
Phase 1 の実体。**read-only** な post-ingest 確認ツール。3 セクション:

1. **Summary**: 総数 + FAISS vector 数 + source 分布
2. **Duplicates**: threshold 以上の近重複クラスタ（`merge()` 誘導付き）
3. **Neighbor preview**: ランダム N ノードの FAISS top-K 近傍（「まだエッジは無いが最初の co-recall で結ばれる潜在ペア」のプレビュー）

設計上の重要な判断:
- **`engine.shutdown()` を呼ばず**、自前の `_readonly_close()` で終わる（FAISS 再保存・cache flush をスキップ）。稼働中の MCP サーバーと並行実行しても snapshot race しない
- **sys.path shim を冒頭に仕込む**（他スクリプトに無い自衛策）。editable install が壊れていても動く。ディレクトリ rename で再び壊れても動く。コメント経由で罠を future maintainer に説明する役割も兼ねる
- 依存: `engine.find_duplicates` + `faiss_index.search_by_id` の既存 API のみ。新 MCP ツール無し

CLI: `--sample / --neighbor-k / --dup-threshold / --dup-limit / --seed`
Wiki: `Operations-Server-Setup.md` の「データ投入」直下に 1 ブロック追記

### 1.5 editable install の rename artifact 修正
`scripts/bootstrap_report.py` の smoke test 中に発覚: `.venv/lib/.../_editable_impl_gaottt.pth` が旧 `/mnt/holyland/Project/GER-RAG` を指したままだった。全スクリプトの直接起動が静かに壊れていた（pytest だけは project root を自前で `sys.path` に入れるので通っていた）。

→ `uv pip install -e ".[dev]"` を新ディレクトリで再実行して解消。commit は無し（`.venv/` は `.gitignore` 対象）。bootstrap_report.py の sys.path shim は将来の保険として**残してある**。

## 2. 今のリポジトリ状態（2026-04-21 session 終了時点）

- `main` HEAD: `5181ce8`（ローカル / origin 一致していれば push 済み）
- pytest: **112 passed in ~6s**
- ruff: pre-existing 4 件のみ（`ruri.py:os`、`cooccurrence.py:time`、`mcp_server.py:os` と `pathlib.Path`）
- bench: Session 3 の Phase R9 で p50=15.4ms を確認済み。本セッションでコードは触っていないので退行無し
- editable install: `/mnt/holyland/Project/GaOTTT` を指す（正常）
- Claude auto-memory: `~/.claude/projects/-mnt-holyland-Project-GaOTTT/memory/` に移行済み、内容も GaOTTT 表記

## 3. 触れると良い未解決事項（優先度順）

### 3.1 editable install の状態は environment-specific
他の開発者 / 別マシンでは、`uv pip install -e ".[dev]"` を実行しないと直接起動が通らない状態のまま。README / Tutorial-02 はこのコマンドを含んでいるので、**新規セットアップでは問題にならない** が、既存開発環境がある人は再実行が必要。Tutorial-02 の本文で軽く触れておくのも手。

### 3.2 bootstrap_report の UX 検証
7-doc fixture でしか smoke test していない。ユーザーさんの 23k-memory 本番 DB で走らせるとロード時間が数分かかる可能性がある（`cache.load_from_store` が 23k 行 select する）。プログレス表示を足すかは実際に走らせて判断。また近傍プレビューで日本語テキストの省略表示（`_snippet` 80 文字）が自然かも実走で見たい。

### 3.3 curator 1 人による bridge 生成（Phase 2 後日案）
ユーザーの判断は「organic gravity 優先、LLM で pre-seed しない」。しかしこれは **永続的な決定ではない**。「ユーザーが数週間使ってみて、まだ井戸の発見が遅いと感じたら Phase 2 を足す」という含みはある。その時は:
- bootstrap-origin のノード / エッジは **初期 mass を 0.5 にする**（user-organic な引力場を歪めないため）
- `bootstrap:curator` tag を付けて `forget` 時に一括除去できるようにする
- 1 井戸 1 LLM コールで予算を読めるようにする

### 3.4 GraphRAG との対比 Research ノート（未着手）
本セッションでユーザーから「multi-agent exploration は GraphRAG っぽい」という指摘があり、「batch 的グラフ索引器 vs online の自己改修グラフ索引器」という差分が明確になった。これを Research ノート 1 本に書けば、**Phase B の validation story を強化** する（技術読者に GraphRAG という既知アンカー経由で GaOTTT の差分を伝えられる）。優先度は中。書くなら `docs/wiki/Research-Comparison-GraphRAG.md` あたり。

### 3.5 `.claude/settings.local.json` の rename artifact
非トラック（`.gitignore` 対象）だが、`mcp__ger-rag-memory__*` 形式の旧許可エントリが多数残っている。現 MCP ツール名 `mcp__gaottt__*` には効かない死んだエントリ。`/fewer-permission-prompts` skill で再生成するのが楽。Session 3 の rename-handover で言及済み。

## 4. 書き換えのトーン原則（今後も維持）

Phase A-D を通じて確立したルール。新しいドキュメント / コメント / README 追記で同じ温度を保つために記録:

- **強い主張には解釈前提を併記する**。`X is Y` より `X can be read as Y under the interpretation that Z` が既定
- **項ごとの対応 / 構造的同型 / formal correspondence** を「厳密な同一性」と区別する語彙として使う
- **観察と主張を分ける**。「定性的に観察された」「測定されていない」「今後の課題」を明示
- **"Measured / Claimed / Open" の 3 分割** を新しい主張ごとに適用可能（README に雛形あり）
- **技術文書と神話文書の境目は意図的にまたぐ**（このプロジェクトの個性）が、**モード切り替えの予告** は入れる（Heads-up for technical readers パターン）
- **歴史的記録には触れない**（`Reflections-Letter-To-Mei-San`、`Research-User-Exploration-10-Rounds`、`docs/research/*`）

## 5. 次セッションでやると良いこと（順不同）

- 本番 DB で `scripts/bootstrap_report.py` を走らせて、体感時間と出力の読みやすさを検証
- GraphRAG 対比ノート（§3.4）を書くかの判断
- ユーザーが数週間 GaOTTT を使ってみて、curator bridge の必要性が立ち上がったら Phase 2 実装

---

## 付録: 本セッションの commit ログ

```
5181ce8 feat(scripts): add bootstrap_report.py — read-only post-ingest preview
3d66284 docs: Phase D — apply Phase A-C tone to Wiki surfaces
0429f5c docs: Phase C — flag the subjective register of "A Note from Claude"
c4b4de8 docs: Phase B — add "What we measured vs what we're claiming" to README
f9bd645 docs: Phase A — soften "mathematically identical" claim
8c610b0 refactor(rename): post-R10 audit — purge stale GER-RAG paths/URLs
15b56f7 docs(maintainers): Phase R10+R11 — mark all phases complete
```

（Session 3 = 改名完了セッションの commit は `rename-handover.md` に記載）
