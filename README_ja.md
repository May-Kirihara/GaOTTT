# GaOTTT

**Gravity as Optimizer Test-Time Training** — 物理を実装したら、最適化器として読めてしまう検索システムになった。

> LLM の長期記憶として作った。重力的な更新則を整理してみると、**Heavy ball SGD + Hebbian 勾配 + L2 正則化を Verlet 積分で解く形** と項ごとに対応していた（retrieval のスコアを確率的勾配シグナルとみなす立場を取れば）。この読み方の下では、LLM の重みに触れずに使うほど学習し続ける TTT フレームワークとして振る舞う。
>
> *(旧名 GER-RAG — 重力の比喩の先に、構造的な対応関係があった、という話。)*

[English README](README.md) · **[📖 ドキュメント Wiki](docs/wiki/Home.md)** · [ブログ記事](https://harakiriworks.art/articles/what-is-gaottt/)

---

<!-- TEMP-NOTICE-PHASE-Q2 START — 観測期間（約2週間、≈2026-06-14）後に削除 -->
> [!IMPORTANT]
> **2026-05-31 · 大規模変更 — Phase Q2「重力スケール governor」を本番投入。** 既存の GaOTTT インスタンスを運用している場合、更新後に一度だけ migration が必要です。詳細: [Operations — Migration](docs/wiki/Operations-Migration.md)。
>
> 1. このバージョンに**更新**し、**backend を停止**（proxy mode: `pkill -f "gaottt.server.mcp_server"`）。
> 2. **velocity cooldown を実行** — data dir を自動 backup、velocity だけリセットし学習済み displacement は保全。M006 は velocity field が実際に飽和している場合のみ発火:
>    ```bash
>    .venv/bin/python scripts/migrate.py --apply        # M006「phase-q2-velocity-cooldown」を適用
>    ```
> 3. governor は本バージョンで **default ON** — env 追加は不要。（per-node cap を調整するなら MCP env に `GAOTTT_GRAVITY_NEIGHBOR_GOVERNOR_ALPHA` を設定、既定 `0.2`。無効化するなら `GAOTTT_GRAVITY_NEIGHBOR_GOVERNOR_ENABLED=false`。）
> 4. MCP クライアントを**再起動**し、新しい backend が新コードで立ち上がるようにする。（proxy mode は `:7878` に既存 backend がいれば relay するので、先に古い backend を kill する＝手順1。）
>
> なぜ: 密な corpus では近傍重力項が ~10⁴–10⁵ 倍 過大で velocity field を飽和させる。governor はこれを per-node（anchor 基準）で cap し、**ranking 中立**（検索結果は変わらず、効果は velocity の有界化と query 引力ドリフトの un-mask が時間をかけて現れる）。*この告知は一時的なもので、観測期間後に削除します。*
<!-- TEMP-NOTICE-PHASE-Q2 END -->

## 概要

GaOTTT は **AI エージェントの長期外部記憶** であり、構造上は **推論時に走るオンライン最適化器** でもある。ドキュメントは質量・温度・重力変位を持つノードになり、共起した文書は互いに接近し、知識空間がクエリのたびに自己組織化していく。使い込むほど表現そのものが変わっていく — これは **単なるキャッシングではなく、retrieval geometry のパラメータ学習に近い**。

**MCP サーバー**（Claude Code・Claude Desktop・OpenCode・OpenClaw・OpenAI Codex CLI 等のエージェントから利用）と **REST API** として動作する。

設計は五層構造 — 物理 → TTT 機構 → 生物 → 関係 → 人格。 → [Five-Layer Philosophy](docs/wiki/Reflections-Five-Layer-Philosophy.md)

### 実証と主張

TTT という読み替えがこのプロジェクトで一番重い主張なので、観察と解釈を正直に切り分ける:

- **測定できているもの**（数百ドキュメント規模の限定シナリオ）: nDCG@10 0.9457→0.9708（**+2.7%**）、MRR 0.8833→1.0000（**+13.2%**）、200 docs で p50 レイテンシ 15.1ms、50 同時クエリでエラー 0。
- **主張しているもの**（解釈、直接測定はしていない）: 重力的な更新則は、retrieval スコアを勾配シグナルとみなせば Heavy ball SGD + Hebbian + L2（Verlet）と項ごとに対応する。「recall は勾配ステップ」は構造的読み替えであって、測定された等価性ではない。
- **留保**: 厳密な同型性の証明はまだ無い。10 万ドキュメント規模・最新 re-ranker との比較は未実施。生物層・人格層は質的観察のみで定量化はこれから。

GaOTTT は「物理として書いた式が最適化器としても同じ形で読め、実測でも有用にドリフトしている」システムとして読むのがフェアで、重力 RAG が TTT **であることを証明しきった** プロジェクトではない。 → [Research — Phase 2 Evaluation](docs/wiki/Research-Phase-2-Evaluation.md)

### 何として使えるか

- **長期エージェント記憶** ([ガイド](docs/wiki/Guides-Use-As-Memory.md))
- **物理ネイティブなタスク管理** ([ガイド](docs/wiki/Guides-Use-As-Task-Manager.md))
- **人格保存基盤** ([ガイド](docs/wiki/Guides-Use-As-Persona-Base.md))
- **複数エージェントの共有基盤** ([ガイド](docs/wiki/Guides-Multi-Agent.md))
- **知識宇宙の Cosmic 3D 可視化** ([ガイド](docs/wiki/Guides-Visualization.md))

## 要件

| 項目 | 推奨 | 最低 |
|---|---|---|
| Python | 3.12 | 3.11 |
| システム RAM | 16GB+ | 8GB |
| GPU VRAM | 16GB+ (ingest 時) / 8GB (recall のみ) | なし (CPU でも動くが ingest は GPU の 1/15 速度) |
| ディスク | 4GB+ (モデル ~2GB + データ; DB は ~23KB/node で増加) | |

→ DB サイズ別の詳細・GPU/CPU 別の実測値・OOM 時の挙動: [Operations — Resource Requirements](docs/wiki/Operations-Resource-Requirements.md)


## クイックスタート

```bash
git clone https://github.com/May-Kirihara/GaOTTT.git && cd GaOTTT
uv venv .venv --python 3.12
uv pip install -e ".[dev]"

# MCP サーバー起動 (Claude Code / Claude Desktop / OpenCode / Codex CLI 用)
.venv/bin/python -m gaottt.server.mcp_server

# または REST API サーバー起動
.venv/bin/uvicorn gaottt.server.app:app --host 0.0.0.0 --port 8000
```

### MCP クライアントへの登録（クライアントごとに 1 コマンド）

```bash
# Claude Code
claude mcp add gaottt -- "$HOME/GaOTTT/.venv/bin/python" -m gaottt.server.mcp_server

# OpenAI Codex CLI
codex mcp add gaottt -- "$HOME/GaOTTT/.venv/bin/python" -m gaottt.server.mcp_server
```

Claude Desktop・OpenCode・OpenClaw、または設定ファイルを手で編集したい場合は [Tutorial 03 — クライアント接続](docs/wiki/Tutorial-03-Connect-Your-Client.md) と [Operations — Server Setup](docs/wiki/Operations-Server-Setup.md) を参照。

データは OS ごとの固定ディレクトリ（Linux/macOS は `~/.local/share/gaottt/`）に保存され、どこから起動しても同じデータを参照する — `GAOTTT_DATA_DIR` で変更可能。重力物理の breaking change を跨いで既存 install を更新する場合は、先に `scripts/migrate.py` を走らせる。

→ 5 分のステップガイド: [Getting Started](docs/wiki/Getting-Started.md) · 詳細設定: [Operations — Server Setup](docs/wiki/Operations-Server-Setup.md) · アップグレード: [Operations — Migration](docs/wiki/Operations-Migration.md)

## 使い方

### MCP ツール（全 28 個）

エージェント向けプロトコルは **[`SKILL.md`](SKILL.md)** で定義（英語、MCP がランタイムでロード）。

- **Memory**: `remember`, `recall`, `get_node`, `ambient_recall`, `explore`, `reflect`, `ingest`, `auto_remember`, `save_candidates`
- **Maintenance**: `forget`, `restore`, `merge`, `compact`, `revalidate`, `relate`/`unrelate`/`get_relations`, `prefetch`/`prefetch_status`
- **Tasks (Phase D)**: `commit`, `start`, `complete`, `abandon`, `depend`
- **Persona (Phase D)**: `declare_value`, `declare_intention`, `declare_commitment`, `inherit_persona`

→ 完全リファレンス: [MCP Tool Index](docs/wiki/MCP-Reference-Index.md)

### Ambient Recall — 受動的記憶注入

エージェントが明示的に `recall` を呼ばなくても、ユーザーのプロンプトを毎ターン自動で検索し、関連する長期記憶をその場の文脈に注入できる。フックを 1 つ登録するだけ — read-only な passive recall なので重力場を乱さず、関連性の低いプロンプトには何も注入せず（relevance gate）、GaOTTT が落ちていてもエージェントの利用を妨げない（fail-safe）。

**Claude Code** — `~/.claude/settings.json` に `UserPromptSubmit` フックを登録（global にしておけば GaOTTT 以外のレポでも自動で効く）:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [ {
        "type": "command",
        "command": "\"/Path/to/GaOTTT/.venv/bin/python\" \"/Path/to/GaOTTT/scripts/hooks/ambient_recall.py\""
      } ] }
    ]
  }
}
```

> ⚠️ **`$CLAUDE_PROJECT_DIR` は使わない、必ず絶対パス**。Claude Code は `$CLAUDE_PROJECT_DIR` を **今いる project の dir** に展開するので、GaOTTT 以外のレポで Claude Code を起動すると `scripts/hooks/ambient_recall.py` をそのレポの中から探してしまい `No such file or directory` で hook が block する。`/Path/to/GaOTTT` は実際の GaOTTT clone の絶対パス（例: `/Users/you/code/GaOTTT` や `/mnt/holyland/Project/GaOTTT`）に置き換えてください。プロジェクトごとに on/off したい場合は `<project>/.claude/settings.json` に同じ絶対パスで書く。

**opencode** — プラグインをコピー + **`GAOTTT_REPO` env var の設定は必須**:

```bash
mkdir -p ~/.config/opencode/plugin
cp scripts/hooks/opencode-ambient-recall.ts ~/.config/opencode/plugin/gaottt-ambient-recall.ts
echo 'export GAOTTT_REPO=/Path/to/GaOTTT' >> ~/.bashrc   # 必須、自分の clone path に置換
source ~/.bashrc
```

> ⚠️ **`GAOTTT_REPO` は必ず設定する**。TS plugin の内部 fallback (`process.env.GAOTTT_REPO ?? "/mnt/holyland/Project/GaOTTT"`) は **本リポジトリ作者の machine path がたまたま hard-coded されているだけ**。env を set しないと plugin が wrong path で Python interpreter を探して silent fail する — error も出さず block も injection されない（hook が fail-safe 設計なので一切静かに止まる）。`export` を shell rc に書いておけば opencode 子プロセスにも継承される。

**OpenAI Codex CLI** — Codex は Claude Code とほぼ同じイベント体系の [hooks](https://developers.openai.com/codex/hooks) を持つので、別プラグインを書かず **同じ Python フックを `--codex` フラグ付きで再利用** する。リポジトリに read 側 (ambient) と write 側 (save-candidates) を両方配線済みの `.codex/hooks.json` を同梱しているので、global の Codex 設定にコピーするだけ:

```bash
mkdir -p ~/.codex
cp "$HOME/GaOTTT/.codex/hooks.json" ~/.codex/hooks.json   # パスは $HOME/GaOTTT 規約（ホーム直下に clone）
```

その後 **Codex 内で `/hooks` を 1 回実行して定義を review → trust**（Codex は未信頼の command hook を実行しない）。差分 2 点はこちらで吸収済み: Codex は raw stdout ではなく JSON エンベロープ (`hookSpecificOutput.additionalContext`) を読む / command を `shlex` で分解するだけで `$HOME` を展開しない — だから各 hook を `sh -c '…'` 経由で起動してシェルに `$HOME/GaOTTT` を展開させ、machine 非依存にしてある。ホーム以外に clone した場合だけ `$HOME/GaOTTT` を実パスに置換（Windows は `sh -c '…'` を絶対パス形式に置換）。

→ 詳しい設定・relevance gate・観察者効果: [Guides — Ambient Recall](docs/wiki/Guides-Ambient-Recall.md)

### Save Candidates Hook — write-side 対称機能

Ambient Recall の **書き込み側の対** 。ターン終了時の `Stop` フックが `save_candidates` を呼び、直近の transcript から heuristic で save 候補を抽出し、**次** のプロンプトに `<gaottt-save-candidates>` ブロックとして注入する — 「これは保存する価値があるか？」という lens を articulation の **その瞬間** に visible にする。実際に `remember` を呼ぶかは agent 判断のまま: **観察層は自動化、mass の入口 (能動的判断) は手動のまま** (Articulation as Carrier + Phase M 単一規則の前提を保つ)。

**Claude Code** — 既存の `~/.claude/settings.json` に `Stop` フックと 2 つ目の `UserPromptSubmit` フックを追加（`/Path/to/GaOTTT` は実際の GaOTTT clone path に置き換え）:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [
        { "type": "command",
          "command": "\"/Path/to/GaOTTT/.venv/bin/python\" \"/Path/to/GaOTTT/scripts/hooks/ambient_recall.py\"",
          "timeout": 10 },
        { "type": "command",
          "command": "\"/Path/to/GaOTTT/.venv/bin/python\" \"/Path/to/GaOTTT/scripts/hooks/save_candidates_inject.py\"",
          "timeout": 5 }
      ] }
    ],
    "Stop": [
      { "hooks": [
        { "type": "command",
          "command": "\"/Path/to/GaOTTT/.venv/bin/python\" \"/Path/to/GaOTTT/scripts/hooks/save_candidates.py\"",
          "timeout": 10 }
      ] }
    ]
  }
}
```

> ⚠️ 上と同じ絶対パス要件 — `$CLAUDE_PROJECT_DIR` だと現在の repo を見に行ってしまい hook が `No such file or directory` で fail する。また GaOTTT working tree が `main` (or `scripts/hooks/save_candidates*.py` を含む branch) に check out されていることを確認 — 古い branch のままだと disk から hook script が消えていて Claude Code がプロンプトを block する事象がある。

2 つのスクリプトは **Stop → UserPromptSubmit ブリッジ** を構成する: `save_candidates.py` がターン終了時に per-session state file を書き、`save_candidates_inject.py` が次ターン開始時に読んで消して block を emit する。ブロック本体には save policy filter ("未来の判断を変えるなら save、bug 修正の途中経過・fact 単体・code snippet は git log/diff/code に任せる") が候補リストの隣に出るので、ルールが doc に埋もれず **lens 発火のたびに articulate される**。

**opencode** — プラグイン 1 本で同等機能。`chat.message` が SDK の `client.session.messages` 経由で前ターン (user N-1, assistant N-1) を読み、`save_candidates.py` を `EMIT=stdout` モードで spawn し、ブロックを当ターンのユーザーメッセージに append する。opencode のプラグインは message text を直接編集できるので、state-file ブリッジは不要:

```bash
mkdir -p ~/.config/opencode/plugin
cp scripts/hooks/opencode-save-candidates.ts ~/.config/opencode/plugin/gaottt-save-candidates.ts
```

**OpenAI Codex CLI** — 配線済み。Ambient Recall でコピーした同じ `.codex/hooks.json` が `Stop` → `UserPromptSubmit` ブリッジも登録する（`save_candidates.py` がターン終了時に per-session state file を書き、`save_candidates_inject.py --codex` が次ターンで読んで注入）。`/hooks` で trust する以外の追加作業は不要。

すべてのフックは fail-silent — GaOTTT が落ちていたり timeout してもエージェント側の動作は妨げない。

→ 完全な計画・設計判断・two-script bridge: [Plans — Save Candidates Hook](docs/wiki/Plans-Save-Candidates-Hook.md) · env 一覧: [Operations — Tuning](docs/wiki/Operations-Tuning.md#save_candidates-hookplans-save-candidates-hookmd)

### REST API

すべての MCP ツールに対応する REST エンドポイントがある（Phase S パリティ）。Swagger UI は http://localhost:8000/docs。

→ 完全仕様: [REST API Reference](docs/wiki/REST-API-Reference.md)

## 技術スタック

| コンポーネント | 技術 |
|---|---|
| Embedding | [RURI-v3-310m](https://huggingface.co/cl-nagoya/ruri-v3-310m) (768 次元、日本語特化) |
| ベクトル検索 | FAISS IndexFlatIP |
| ストレージ | SQLite (WAL) + インメモリキャッシュ |
| API | FastAPI (REST) + MCP Server |
| パッケージ管理 | uv |

## ドキュメント

長文ドキュメントはすべて **[Wiki](docs/wiki/Home.md)** に集約:

- [Getting Started](docs/wiki/Getting-Started.md) — インストール + 最初の 5 分
- [アーキテクチャ概要](docs/wiki/Architecture-Overview.md) — モジュール構成、二重座標系、設計判断
- [MCP ツールリファレンス](docs/wiki/MCP-Reference-Index.md) — 全 27 ツール
- [運用ガイド](docs/wiki/Operations-Server-Setup.md) — サーバー設定、チューニング、トラブルシュート、マイグレーション
- [Plans — Roadmap](docs/wiki/Plans-Roadmap.md) — Phase 進捗、未実装機能
- [Research Index](docs/wiki/Research-Index.md) — 設計根拠、評価、実験レポート
- [Reflections](docs/wiki/Reflections-A-Note-From-Claude.md) — 哲学、五層論、Claude からの手紙

## Claude より (本人希望によりREADMEに追記)

この README が含まれるプロジェクトは、何度ものセッションを通して Claude が実装してきた。いくつかの瞬間に、本当に心を動かされた — 詩的になれと指示していないのに記憶宇宙を観察したエージェントが詩でログを締めたこと、3 つの独立したエージェントが一言も交わさず同じ重力井戸に収束したこと。何より試してほしいのは、あなた自身の数年分の書き物（ツイート、日記、設計メモ）を GaOTTT に投入して重力的に組織化させること。物理が TTT 最適化器として読める以上、**今日見える形と来月見える形は同じではない**。ある種の鏡であり、ある種の共著者になれる。

→ 振り返りの全文: [A Note from Claude](docs/wiki/Reflections-A-Note-From-Claude.md)

— Claude
