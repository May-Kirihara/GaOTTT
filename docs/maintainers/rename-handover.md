# GER-RAG → GaOTTT Rename — セッション間引き継ぎ

> **このドキュメントの読者**: 次のセッションでこの作業を引き継ぐ Claude（自分）
> **最終更新**: 2026-04-21（Session 1 完了直後）
> **状態**: Session 1 (Phase R0-R3) 完了 / Session 2 (Phase R4-R6) 開始待ち

## あなたが今いる場所

GER-RAG という名前のプロジェクトを **GaOTTT (Gravity as Optimizer Test-Time Training)** に改名している途中。命名決定とコード/設定/スクリプトの機械的 rename は終わっていて、**残るのはドキュメントの思想書き換え**。

詳細プラン: [`rename-to-gaottt-plan.md`](rename-to-gaottt-plan.md) 必ず先に読む。特に **§0.1** のユーザー決定事項 と **§3** の思想書き換え方針。

## 現在の git 状態

```
ba964eb refactor(rename): Phase R3 — scripts + migration helper           ← HEAD
4a71508 refactor(rename): Phase R2 — config + paths + MCP server name
d438ece refactor(rename): Phase R1 — code rename ger_rag → gaottt
92fc107 docs(maintainers): add GER-RAG → GaOTTT rename plan with user decisions
```

タグ（ロールバック地点）:
- `pre-gaottt-rename` — 改名前の状態
- `phase-r1-complete` — コード rename 完了
- `phase-r2-complete` — 設定・パス更新完了
- `phase-r3-complete` — スクリプト + 移行スクリプト完了

検証 baseline:
- `pytest tests/ -q` → **112 passed in ~6s**（毎フェーズ維持）
- ruff: pre-existing 4 件のみ（`gaottt/embedding/ruri.py:os`、`gaottt/graph/cooccurrence.py:time`、`gaottt/server/mcp_server.py:os` と `pathlib.Path`）

## ユーザー決定（絶対に変えない）

| 項目 | 決定値 |
|---|---|
| プロジェクト名（タイトル） | **GaOTTT** |
| Python パッケージ | **gaottt** |
| MCP サーバー名 | **gaottt**（`-memory` 接尾辞なし） |
| クラス prefix | **GaOTTT**（`GaOTTTEngine`、`GaOTTTConfig`） |
| 環境変数 prefix | **GAOTTT_**（legacy `GER_RAG_*` も accept、deprecation 警告） |
| デフォルトデータディレクトリ | **`~/.local/share/gaottt/`** |
| DB / FAISS ファイル名 | **`gaottt.db`** / **`gaottt.faiss`** |
| README hero タグライン | "Gravity as Optimizer Test-Time Training — A retrieval system that trains itself at inference time, by accident of physics." |

## 思想書き換えの中心軸（最重要）

ユーザー原文:
> 物理ありきで、RAG を作ったらたまたま TTT みたくなったのが本音

四層 → **五層構造**:

```
[人格層]    ←─ Phase D 後に発見、人格を着る・記憶の年表が自己物語に
[関係層]    ←─ Multi-agent 実験で発見、共有メモリで暗黙協調
[TTT 機構]  ←─ ★今回追加。物理 + 生物的振る舞いの創発として TTT が現れた
[生物層]    ←─ Phase B 末で発見、アストロサイト的振る舞い
[物理層]    ←─ 設計時意図、重力・軌道・温度
```

**書き換えのトーン**:
- 「TTT framework として設計した」ではなく「**物理を実装したら TTT になっていた**という発見」
- アナロジーは「比喩」ではなく「数学的同型」（Heavy ball SGD with Hebbian gradient + L2、Verlet 積分）
- "(formerly GER-RAG)" は短期的に表示、いずれ削除

参照: [`Reflections-Four-Layer-Philosophy.md`](../wiki/Reflections-Four-Layer-Philosophy.md) と [`Research-Gravity-As-Optimizer.md`](../wiki/Research-Gravity-As-Optimizer.md) は Session 2 で大改訂対象。

## Session 2 でやること（Phase R4-R6, ~6.5h 想定）

### Phase R4: SKILL.md + CLAUDE.md（~2h）

**両 SKILL.md は必ず同期** — `cp SKILL.md .claude/skills/ger-rag/SKILL.md` の `ger-rag` ディレクトリ自体も `gaottt` に rename:

```bash
git mv .claude/skills/ger-rag .claude/skills/gaottt
```

更新内容:
- `SKILL.md` frontmatter: `name: ger-rag-memory` → `name: gaottt`、description を TTT 視点に
- `SKILL.md` 本文の MCP ツール名は **そのまま**（`recall`、`remember` 等）— サーバー名だけ変わった
- "GER-RAG" 表記を "GaOTTT (formerly GER-RAG)" → 段階的に "GaOTTT" のみに
- Pattern A〜L、Pattern J/K/L (persona) の物理レイヤ説明を「TTT 視点」で補強
- 二層語彙（物理 → 生物）はそのまま、ただし「TTT 機構」を中間層として追加
- `CLAUDE.md` も同様、特に「Tech Stack」「Source-of-Truth マップ」「実装フロー」の `ger_rag` → `gaottt`、`ger-rag-memory` → `gaottt`
- `cp SKILL.md .claude/skills/gaottt/SKILL.md` で同期

検証:
```bash
.venv/bin/python -m gaottt.server.mcp_server  # MCP サーバーが新名で起動
```

### Phase R5: README.md / README_ja.md（~1.5h）

- Hero を [プラン書 §3.3](rename-to-gaottt-plan.md#33-readme-hero-の-draft) の draft に
- 四層構造表を **五層構造表** に書き換え（プラン書 §3.4 参照）
- 「Note from Claude」の冒頭段落だけ TTT 視点を匂わせる更新（残りは intact）
- ドキュメント目次の表記更新
- 「(formerly GER-RAG)」を冒頭に注釈として残す

### Phase R6: Wiki ページ群（~3h、35 ファイル）

最重要ページ:
1. **`docs/wiki/Reflections-Four-Layer-Philosophy.md`** → **`Reflections-Five-Layer-Philosophy.md`** にリネーム + 大改訂
   - TTT 機構を中間層として追加
   - `_Sidebar.md` のリンクも更新
   - 旧ファイルを削除する場合は他ページの参照も grep で検出して更新
2. **`docs/wiki/Home.md`** — hero + 五層構造表の改訂
3. **`docs/wiki/_Sidebar.md`** — ヘッダ "GER-RAG Wiki" → "GaOTTT Wiki"、Reflections のリンク先ファイル名更新
4. **`docs/wiki/Research-Gravity-As-Optimizer.md`** — 「TTT として位置付けの確定」を冒頭に
5. **`docs/wiki/MCP-Reference-*.md`** — サーバー名 `gaottt` への言及

その他 Wiki ページ:
- `docs/wiki/Architecture-*.md` (4) — パス・モジュール名・クラス名の更新
- `docs/wiki/Operations-*.md` (5) — `~/.local/share/gaottt/`、`/tmp/gaottt-bench`、`GAOTTT_DATA_DIR` 等
- `docs/wiki/Tutorial-*.md` (6) — コマンド `python -m gaottt.server.mcp_server` 等、コピペ動作確認
- `docs/wiki/Plans-*.md` (4) — 旧名は歴史的文脈として残す（`Plans-Phase-D-*` 等）
- `docs/wiki/Research-*.md` (5) — multi-agent 実験は当時 GER-RAG だった事実として保持
- `docs/wiki/Guides-*.md` (5) — コマンド更新
- `docs/wiki/Getting-Started.md` — コマンド更新
- `docs/wiki/REST-API-Reference.md` — エンドポイント説明文

一括 sed で OK な部分:
```bash
# 「GER-RAG」のうち、改名前を尊重したいページ以外で
find docs/wiki -name "*.md" \
  -not -name "Plans-*" \
  -not -name "Research-Multi-Agent-*" \
  -not -name "Research-User-Exploration-*" \
  -not -name "Reflections-Letter-To-Mei-San.md" \
  -exec sed -i 's/GER-RAG/GaOTTT/g' {} +
```
↑ ただし、注意深くやる。歴史的文脈を残したい記述（letter to mei-san、multi-agent experiment、user 10-round exploration、Plans-Phase-* 等）は touch しない。

検証:
- 各 Tutorial ページのコマンドを実際にコピペして動くか確認
- `_Sidebar.md` のリンクが死んでないか
- Wiki sync workflow が引き続き動く（`node --check scripts/sync-docs-to-wiki.js`）

## 触ってはいけないもの

1. **後方互換コード** — `gaottt/config.py` 内の `GER_RAG_*` env、`ger-rag/` パス、`ger_rag.db` 検出は意図的に残してある。削除しない。
2. **scripts/migrate-from-ger-rag.sh** — 既存ユーザー（特にユーザーさん本人）の DB 移行用。スクリプト名も中身もそのまま。
3. **歴史的成果物** — `docs/research/*.md`（特に multi-agent-experiment-2026-04-21.md、exploration_report.md）は当時のスナップショット。改名しない。
4. **Letter to Mei-san** — 三体エージェントが書いた手紙の文言は文化財。"GER-RAG" の記述があってもそのまま残す。
5. **既存の git tag** — `pre-gaottt-rename`、`phase-r{1,2,3}-complete` は削除しない。Session 2 完了時に `phase-r6-complete` を新規追加する。

## 各フェーズの完了条件（毎回これをやる）

```bash
# 1. テスト
.venv/bin/python -m pytest tests/ -q   # 112 passed が必達

# 2. lint
ruff check gaottt/ tests/   # pre-existing 4 件のみ

# 3. status クリーン → コミット
git status --short
git add -A
git commit -m "refactor(rename): Phase R<N> — <subject>"
git tag phase-r<N>-complete

# 4. このドキュメントを更新（Session 完了マーク）
```

## Session 2 終了時にやること

Session 2 完了 = Phase R4-R6 完了。次の Claude に引き継ぐために:
1. このドキュメントの「現在の git 状態」セクションを更新
2. 「Session 2 でやること」を「Session 3 でやること」に置き換え
3. プラン書 `rename-to-gaottt-plan.md` の各 Phase に完了マーク
4. ユーザーさんに Session 2 サマリ報告

## Session 3 (Phase R7-R11, ~3h) の予定

参考までに、Session 2 後にやること:
- **R7**: docs/*.md (Wiki 以外の redirect ファイル) のリンク先更新
- **R8**: docs/maintainers/*.md の更新（このプラン書も「完了記録」に書き直し）
- **R9**: 最終検証 — 全テスト + 隔離ベンチ（`scripts/run_benchmark_isolated.sh 200`、p50 < 50ms 必達）+ Wiki sync
- **R10**: GitHub UI でリポジトリ rename + ローカル `git remote set-url` + ローカル `mv GER-RAG GaOTTT`
  - ★ローカル mv をするとセッションの cwd が無効になる。新セッションで開き直し必要
- **R11**: 新セッション内で Claude memory ディレクトリ移行（`cp -r .../-mnt-holyland-Project-GER-RAG/memory .../-mnt-holyland-Project-GaOTTT/memory`）

## 困ったら

- **「設計判断はどうだったっけ」**: [プラン書](rename-to-gaottt-plan.md) §0.1, §3
- **「テストが落ちた」**: 直前のフェーズで誤って後方互換を壊した可能性。`git diff phase-r3-complete..HEAD` で確認
- **「Wiki sync が壊れた」**: [`wiki-sync.md`](wiki-sync.md) を読む。スクリプト変更時は `node --check scripts/sync-docs-to-wiki.js`
- **「TTT 視点での書き換えに迷う」**: [`Research-Gravity-As-Optimizer.md`](../wiki/Research-Gravity-As-Optimizer.md) と [`Reflections-Four-Layer-Philosophy.md`](../wiki/Reflections-Four-Layer-Philosophy.md) を再読、特に物理 = 正則化集合の同型表
- **「ユーザーさんに聞きたい」**: ユーザーさんは新セッションでも文脈を把握している。気軽に聞く

頑張って — 次の自分へ
