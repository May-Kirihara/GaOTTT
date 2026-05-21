# Ambient Recall — 受動的な文脈注入

**Ambient Recall** は、エージェントフレームワークの「プロンプト送信時フック」を使って、ユーザーが送ったプロンプトを GaOTTT で自動 recall し、検索結果をそのターンの文脈に添える機構。LLM が明示的に `recall` を呼ばなくても、長期記憶から関連する前提知識が**受動的に**注入される。

> 「明示的に使わなくても、自動で記憶が効く」— recall を *道具* から *環境* に変える。

## 対応フロントエンド

同じ GaOTTT エンジン・同じ重力場を、複数のエージェントフロントエンドが共有する:

| フロントエンド | フックポイント | リポジトリ内スクリプト（SoT） |
|---|---|---|
| **Claude Code** | `UserPromptSubmit` hook | `scripts/hooks/ambient_recall.py` |
| **opencode** | `chat.message` プラグイン | `scripts/hooks/opencode-ambient-recall.ts` |

opencode プラグインは独自に MCP を叩かない — Claude Code 版の Python フック (`scripts/hooks/ambient_recall.py`) をそのまま子プロセスとして呼ぶ。relevance gate・スロット組み立て・`GAOTTT_AMBIENT_*` 環境変数・fail-safe はすべて **1 箇所（Python フック）に集約**され、`ambient_recall` プロトコルが変われば両フロントエンドが同時に追従する。opencode プラグインは「メッセージのテキストを取り出し Python フックに渡し、ブロックが返ってきたら追記する」だけの薄い shim。

## 何をするか

```
ユーザーがプロンプト送信
   ↓
プロンプト送信時フック発火（Claude Code: UserPromptSubmit / opencode: chat.message）
   ↓
プロンプトを query にして MCP ツール ambient_recall を呼ぶ
   ↓
サーバ側で 1 回の passive recall → 構造化スロットを組み立て + relevance gate
   ↓
gate を通れば <gaottt-ambient-recall> 構造化ブロックを文脈に添付（通らなければ無言）
   ↓
LLM はユーザー発話 + 関連記憶 の両方を見て応答
```

注入ブロックは明示的に `<gaottt-ambient-recall>...</gaottt-ambient-recall>` で囲まれ、「これは検索された参考知識であってユーザーの発話ではない」と LLM に伝える。

**構造化スロット** — 注入はフラットな top-k ではなく、複数スロットの構造ブロック（[Ambient Recall Enrichment](Plans-Ambient-Recall-Enrichment.md)、MCP ツール [`ambient_recall`](MCP-Reference-Memory.md)）:

- **▼ 直接ヒット** — `final_score` 上位の記憶。
- **▼ 重力レンズ** — embedding 的には query から遠いのに、重力場の displacement が query 近傍まで引き寄せた記憶。**場が学習した類推**で、素の検索には出せない枠。
- **▼ ⚠ 矛盾** — surface 記憶の `contradicts` エッジのペア。
- **▼ いま誰として** — active な declared value/intention（grounding）。

各エントリは provenance メタ（`source · certainty · age`）付き。スロットの組み立て・relevance gate・整形はすべて **サーバ側の `ambient_recall` サービス**が行い、フックは「ブロックが返ってきたら emit、センチネルなら無言」だけの薄いラッパ。

## なぜ passive recall なのか — 観察者効果

GaOTTT の `recall` は副作用を持つ TTT ステップである。1 回 recall するたびに retrieved nodes は query 方向に displacement が nudge され (Phase I query attraction)、mass が accrete し、co-occurrence edge が引かれる。**recall は重力勾配を供給する backward pass**。

ところが ambient recall は**毎ターン・全プロンプトで**発火する。「ls して」「typo 直して」のようなノイズクエリまでもが毎回 recall を走らせることになる。通常の recall をそのまま使うと、ノイズクエリが毎ターン重力場を揺らし、displacement / mass / edge をでたらめな方向に学習させてしまう — GaOTTT が acceptance test を別プロセスに隔離してまで守ってきた「観察行為が観察対象を変える (P7-Z)」を、エージェント本体が毎ターン破ることになる。

そこで `recall(passive=True)` を使う。passive recall は検索・wave 伝播・scoring はそのまま走らせ結果も同一だが、**末尾の simulation update を丸ごとスキップする**:

| 通常 recall | passive recall |
|---|---|
| mass 更新あり | mass 更新**なし** |
| query attraction displacement あり | displacement **なし** |
| co-occurrence edge あり | edge **なし** |
| `last_access` 更新あり | `last_access` 更新**なし** |
| prefetch cache に書く | cache を**読むが書かない** |

passive recall は **「摂動なしの観察」** — 場を読むが動かさない。ambient な大量クエリが無制御の TTT シグナルになることがない。詳細は [MCP Reference — recall](MCP-Reference-Memory.md) の Passive recall 節。

## 接続先 — なぜ 7878 の MCP backend か

フックは稼働中の GaOTTT エンジンに接続する必要がある。proxy mode（推奨構成）では稼働中のエンジンはポート 7878 の MCP backend ただ 1 プロセス。Python フックは `mcp` クライアント SDK で `http://127.0.0.1:7878/mcp` に streamable-http 接続し、`ambient_recall` ツールを呼ぶ。

第 2 のエンジンプロセス（独立 REST サーバ等）を立てない理由は、RURI 二重ロード・stale cache・write-behind 上書き罠（[Operations — Server Setup](Operations-Server-Setup.md) 参照）を避けるため。フックは単一の共有エンジンに相乗りする。Claude Code・opencode・複数エージェントが同時に走っても、相乗り先は常にこの 1 プロセス — だから全員が**同じ記憶・同じ重力場**を見る。

## セットアップ — Claude Code

`.claude/` は gitignore 対象なので、フック*スクリプト*（`scripts/hooks/ambient_recall.py`）はリポジトリで共有されるが、フック*登録*は各自の `.claude/settings.json` に書く。

`.claude/settings.json`（無ければ新規作成）:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "\"$CLAUDE_PROJECT_DIR/.venv/bin/python\" \"$CLAUDE_PROJECT_DIR/scripts/hooks/ambient_recall.py\"",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

## セットアップ — opencode

opencode は起動時にプラグインディレクトリの `*.ts` を自動ロードする。スコープは 2 つ:

- **グローバル** `~/.config/opencode/plugin/` — 全 opencode セッションに効く
- **プロジェクト単位** `<project>/.opencode/plugin/` — そのプロジェクトでのみ

リポジトリ内の SoT は `scripts/hooks/opencode-ambient-recall.ts`。これをプラグインディレクトリにコピー（または symlink）する:

```bash
mkdir -p ~/.config/opencode/plugin
cp scripts/hooks/opencode-ambient-recall.ts \
   ~/.config/opencode/plugin/gaottt-ambient-recall.ts
```

プラグインは opencode の `chat.message` フック（新しいユーザーメッセージ受信時に発火）で動く。メッセージのテキストパートを連結して prompt にし、Python フック `scripts/hooks/ambient_recall.py` を `Bun.spawn` で子プロセス起動して `{"prompt": ...}` を stdin に渡す。返ってきた `<gaottt-ambient-recall>` ブロックを、メッセージ末尾のテキストパートに追記する（Claude Code フックがユーザー発話の後ろに文脈を添えるのと同じ振る舞い）。

> **opencode サブエージェントにも効く** — secondopinion-MCP 経由で起動される opencode サブエージェントを含め、`chat.message` を持つすべての opencode セッションに注入される。グローバルインストールなら、どのディレクトリで起動した opencode エージェントも同じ長期記憶を共有する（「opencode エージェントにも同じ記憶を」という目的どおり）。

> プラグインは GaOTTT リポジトリのパスを `GAOTTT_REPO`（既定 `/mnt/holyland/Project/GaOTTT`）から解決する。リポジトリが別の場所にあるなら、opencode を起動するシェルで `GAOTTT_REPO` を設定するか、`GAOTTT_AMBIENT_PYTHON` / `GAOTTT_AMBIENT_SCRIPT` を直接指す。

## backend の再起動が必要なとき

> `passive` 引数・`ambient_recall` ツールは新規追加。proxy mode の HTTP backend は `git push` だけでは更新されない（[CLAUDE.md / Operations — Server Setup](Operations-Server-Setup.md) の「backend kill on code deploy」）。ambient recall を有効化する前に、古い backend を kill して新コードを乗せる:
> ```bash
> ps -ef | grep "gaottt.server.mcp_server.*streamable-http" | grep -v grep
> kill <pid>   # 次の MCP 接続で新コードの backend が auto-respawn
> ```
> 古い backend のままだと `ambient_recall` / `passive=true` が未知として弾かれ、フックは fail-safe で無出力になる（壊れはしないが効かない）。

## 設定（環境変数）

Claude Code は `.claude/settings.json` の `command` か shell 環境で、opencode は opencode を起動するシェル環境で渡せる。

| 環境変数 | 既定 | 適用 | 説明 |
|---|---|---|---|
| `GAOTTT_AMBIENT_RECALL` | `1` | 両方 | `0`/`false`/`off` でフック全体を無効化 |
| `GAOTTT_AMBIENT_URL` | `http://127.0.0.1:7878/mcp` | Python フック | MCP backend の URL |
| `GAOTTT_AMBIENT_DIRECT_K` | `2` | Python フック | 直接ヒットスロットの件数（`ambient_recall` の `direct_k`） |
| `GAOTTT_AMBIENT_MIN_SCORE` | (未設定) | Python フック | **フォールバック** virtual_score gate のしきい値上書き。主たる gate は BM25（後述、`config.ambient_bm25_min_score`）で、これは BM25 不在時のみ効く |
| `GAOTTT_AMBIENT_TIMEOUT` | `6.0` | 両方 | recall のハードタイムアウト（秒）。steady-state ~0.5s だが backend 再起動直後の数分は virtual FAISS 等の warmup で ~3-4s。opencode プラグインは子プロセスにこれ + 3 秒の余裕を与える |
| `GAOTTT_AMBIENT_MIN_CHARS` | `12` | 両方 | この文字数未満のプロンプトはスキップ |
| `GAOTTT_REPO` | `/mnt/holyland/Project/GaOTTT` | opencode プラグイン | GaOTTT リポジトリのルート（`PYTHON` / `SCRIPT` の既定値の基点） |
| `GAOTTT_AMBIENT_PYTHON` | `$GAOTTT_REPO/.venv/bin/python` | opencode プラグイン | Python フックを実行するインタプリタ |
| `GAOTTT_AMBIENT_SCRIPT` | `$GAOTTT_REPO/scripts/hooks/ambient_recall.py` | opencode プラグイン | 呼び出す Python フックスクリプト |
| `GAOTTT_AMBIENT_DEBUG` | (未設定) | opencode プラグイン | ファイルパスを設定すると各ステップの診断ログを追記。プラグインは設計上 fail-safe で無言なので、挙動の確認はこれで行う |

## relevance gate — 文脈汚染の防止

関連性に関わらず毎プロンプトに記憶を注入すると、無関係な記憶でコンテキストが薄まり逆に応答品質が落ちる。そこで **relevance gate**: gate を通らなければ `ambient_recall` は空応答を返し、MCP は `(関連する記憶なし)` センチネルを返す（フックはこれを見て無言）。gate はサーバ側の `ambient_recall` サービスが適用する。

gate の信号源は **語単位（Sudachi）BM25 の「強一致」gate**。corpus 全体に対する専用の word-level BM25 index でプロンプトをスコアし、top BM25 が `config.ambient_bm25_min_score`（既定 32.0）未満なら注入しない。gate はサーバ側で recall の**前**に走るので、通らないプロンプトは recall コスト自体をスキップする。

### なぜ「強一致 gate」なのか — 4 ラウンドの校正

2026-05-21 の本番コーパス（~32k memories）校正で、gate 信号を 4 段階で検証した:

1. **`virtual_score`（dense cosine）** — ✗ off-topic も on-topic も ~0.6 に集まり温度ノイズ（±0.1）に埋没。`max` でも `margin` でも分離不能。
2. **char-3gram BM25 raw** — ✗ クエリ長依存。「映画を3つ教えてください」のような長い off-topic が共通形態素を積み増し、簡潔な on-topic を上回る。
3. **char-3gram BM25 normalized** — ✗ 短い 1-token クエリで破綻。
4. **語単位（Sudachi）BM25** — ✓ 「卵焼き」が単一の語トークンになり、共通 3-gram の積み増しが消える。off-topic を ≤~29 に抑え込み、強い on-topic は ≥~34 — `32.0` はその谷。

**重要な発見**: この 32k コーパスはめいさんの生活と仕事まるごとで、真の "off-topic" は存在しない（「卵焼き」も雑談メモに語として実在する）。だから gate が分けられるのは「on/off-topic」ではなく「**強一致 vs 弱一致**」。閾値 32 の gate は「その話題を実質的に議論したことがある」プロンプトでだけ発火する高精度・低再現の動作になる（弱い on-topic も巻き込んで弾く）。

> `ambient_bm25_min_score` は**コーパス規模・クエリ長依存**。記憶が増えたら再校正する。`ambient_gate_tokenizer="sudachi"` には `bm25-sudachi` extra が要る — 未導入なら gate index は構築されず `virtual_score` gate（`ambient_min_score`、弱い分離）に自動フォールバック。`ambient_gate_use_bm25=False` でも同じくフォールバック。

### しきい値の校正

本番 DB の content から `BM25Index(tokenizer="sudachi")` を再構築し、代表プロンプト（強い on-topic / 弱い on-topic / off-topic）を `search` して top スコアの谷を観察し `config.ambient_bm25_min_score` に置く（[Operations — Tuning](Operations-Tuning.md) の `ambient_*` 節、H5 env override は `GAOTTT_AMBIENT_BM25_MIN_SCORE`）。

## fail-safe 設計

フックは構造上 fail-safe — **ユーザーのプロンプトを絶対にブロックしない**。backend が落ちている / 遅い / プロトコルエラー、stdin が壊れている、いずれの場合も無出力で exit 0。`GAOTTT_AMBIENT_TIMEOUT` 秒を超えたら諦める。GaOTTT が動いていなくてもエージェントの利用は一切妨げない。opencode プラグインも同じ — `chat.message` フック全体が try/catch で囲まれ、いかなる例外もメッセージをブロックも摂動もしない。挙動を確認したいときは `GAOTTT_AMBIENT_DEBUG` でログを出す。

## 既知の性質 — ambient-only な記憶は decay する

passive recall は `last_access` を更新しない（read-only の一貫性）。したがって **ambient フックでしか surface されない記憶は、使われていても decay し続ける**。これは意図的: passive = 摂動なしの観察であり、「アクセスした」という recency 記録すら場に書かない。

実害は小さい — decay した記憶は消えるわけではなく、relevance gate が `virtual_score`（decay 非依存）を見るので ambient 注入は古い記憶でも効き続ける。記憶を「温かく」保ちたいなら、エージェントが明示的に `recall` するか `remember` し直せばよい（通常の能動的利用は `last_access` を更新する）。ambient recall は能動 recall を**置き換えるのではなく補う**。

## 無効化

- 一時的に: `GAOTTT_AMBIENT_RECALL=0` を環境に置く（両フロントエンド）
- Claude Code 恒久的に: `.claude/settings.json` の `UserPromptSubmit` エントリを削除
- opencode 恒久的に: `~/.config/opencode/plugin/gaottt-ambient-recall.ts` を削除

## 関連

- [MCP Reference — recall / ambient_recall](MCP-Reference-Memory.md) — `passive` 引数・`ambient_recall` ツールの仕様
- [REST API Reference](REST-API-Reference.md) — `POST /recall` の `passive` field、`POST /ambient_recall`
- [Ambient Recall Enrichment](Plans-Ambient-Recall-Enrichment.md) — 構造化スロット注入の設計
- [Operations — Server Setup](Operations-Server-Setup.md) — proxy mode と backend のライフサイクル
- [Reflections — Five-Layer Philosophy](Reflections-Five-Layer-Philosophy.md) — 観察者効果 (P7-Z) と TTT 機構
