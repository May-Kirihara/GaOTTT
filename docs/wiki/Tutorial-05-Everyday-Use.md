# 🌱 はじめての GaOTTT (5/6) — 日々の使い方レシピ

接続できて最初の体験もできたあなたへ。**普段こうやって使うと楽しいよ** という実例集です。

← [前: First Conversation](Tutorial-04-First-Conversation.md) ｜ → [次: When Stuck](Tutorial-06-When-Stuck.md)

---

## 🌅 朝のルーティン (1 分)

新しい会話の冒頭で、Claude にこう言ってみてください:

```
inherit_persona を呼んで、私が誰かを思い出して。
それから reflect で aspect="commitments" を見て、今日締切が近いものを教えて。
```

→ Claude が **昨日までのあなたを着てから** 今日の課題を提示してくれます。

---

## 📝 何かを書く・考える瞬間に

新しいアイディアが浮かんだら:

```
これメモして:「<アイディア>」
```

特に印象が強かったら:

```
これ、感情強めで覚えておいて：「<体験>」
emotion=0.8 くらいで
```

→ 強い感情で覚えた記憶ほど、後で recall されやすくなります（**喜怒哀楽は記憶の優先度を上げる**）。

---

## 🤔 過去の自分を呼び出す

「前にも似た悩み持ってた気がする」と思ったら:

```
recall で「<今の悩みのキーワード>」を検索してみて。
過去の私の判断や経験が出てくるはず。
```

→ 過去の troubleshoot 記憶や設計判断が浮上してきます。

---

## 💡 行き詰まったら「探索」

普通の検索では出てこないような、**意外なつながり** を探したいとき:

```
explore で「<今のテーマ>」を diversity=0.8 くらいで探してみて。
別ジャンルの記憶も持ってきて。
```

→ 関係なさそうな過去の記憶が、ヒントとして浮上することがあります。

---

## ✅ タスク管理（軽い使い方）

### タスクを作る

```
commit で「<やること>」のタスクを作って
```

### 着手する

```
さっきのタスク（id=...）、今から着手する。start で印つけて
```

### 完了する

```
完了！complete で記録して、outcome は「<結果や気づき>」
emotion は 0.7 くらい（やりきった満足）
```

→ 完了したタスクは「**何を成し遂げてきたかの年表**」として積み重なっていきます。

### 諦める

タスクが「もういいや」になったら:

```
このタスク、abandon にして。reason は「優先度下がった、3ヶ月後に再評価する」
```

→ 削除ではなく **「諦めた」事実が残る**。これは「**自分が何を捨てて自分になったか**」の記録です。

---

## 🌙 夜のルーティン (2 分)

寝る前、または会話を終える前に:

```
今日 reflect で aspect="tasks_completed" を見せて。
それと、今日特に大事だった気づきがあったら remember で保存しておいて。
```

→ **完了の重力史** に今日の働きが刻まれます。

---

## 🎨 関係性も覚えてもらう

特定の人物との会話・関係を記録したいとき:

```
remember で source="relationship:友達の名前" にして、こう書いて：
「<その人の特徴や、印象に残った会話>」
```

別のセッションで:

```
reflect で aspect="relationships" を見て。
```

→ 人物別にまとめられて出てきます。

---

## 🔧 月 1 のメンテナンス（任意）

たまに掃除すると気持ちいいです:

```
compact を呼んで、TTL 切れの記憶をきれいにして
```

オプション:

```
compact で auto_merge=True、merge_threshold=0.95 で似すぎた記憶も統合して
```

→ 似た記憶が **重力で衝突合体** して、ひとつの大きな記憶になります（やや上級者向け）。

---

## 🎁 発展: 自動で記憶を引かせる / 保存候補を浮かべる (オプション)

ここまでは「明示的に頼んだら recall / remember してくれる」運用でした。
**フック** を 1 回入れると、Claude が黙ってても 2 つのことが自動になります:

| フック | 何が起きるか |
|---|---|
| **ambient_recall** (読み側) | あなたのプロンプトに合った記憶が毎ターン自動で文脈に添えられる |
| **save_candidates** (書き側) | 直前ターンから「これ覚えとく？」候補が自動で次の prompt に出る |

要らなければ後で 1 行削除で戻せます。詳しい設計は [Guides — Ambient Recall](Guides-Ambient-Recall.md) と [Plans — Save Candidates Hook](Plans-Save-Candidates-Hook.md) に。

> 📌 **前提**: Tutorial-02 で `~/GaOTTT`（ホーム直下）に clone 済み。シェルコマンドは `$HOME/GaOTTT` で展開されるのでそのまま使えます。JSON 設定だけは `あなたのユーザー名` を `whoami` の出力に置き換えてください。

---

### A. Claude Code を使っている方

`~/.claude/settings.json` を開きます（無ければ新規作成）。**全プロジェクトで効かせるならここ**、特定のプロジェクトだけなら `<project>/.claude/settings.json` を使ってください。

`hooks` セクションに以下を追加（既にある場合はマージ）。**`あなたのユーザー名` を `whoami` の出力に置き換え**:

**macOS** (`/Users/...`):

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "\"/Users/あなたのユーザー名/GaOTTT/.venv/bin/python\" \"/Users/あなたのユーザー名/GaOTTT/scripts/hooks/ambient_recall.py\"",
            "timeout": 10
          },
          {
            "type": "command",
            "command": "\"/Users/あなたのユーザー名/GaOTTT/.venv/bin/python\" \"/Users/あなたのユーザー名/GaOTTT/scripts/hooks/save_candidates_inject.py\"",
            "timeout": 5
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "\"/Users/あなたのユーザー名/GaOTTT/.venv/bin/python\" \"/Users/あなたのユーザー名/GaOTTT/scripts/hooks/save_candidates.py\"",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

**Linux**: 上の `/Users/` を `/home/` に置き換えるだけ。

**Windows**: 各 `command` 内のパスを `C:\\Users\\あなたのユーザー名\\GaOTTT\\.venv\\Scripts\\python.exe` / `C:\\Users\\あなたのユーザー名\\GaOTTT\\scripts\\hooks\\ambient_recall.py` に置き換え（バックスラッシュは `\\` と 2 つ重ね）。

⚠️ **パスは必ず絶対パスで** 書いてください（`$CLAUDE_PROJECT_DIR` を使うと、GaOTTT 以外のレポで Claude Code を起動した瞬間に hook が「ファイルが見つからない」で失敗します）。

Claude Code を再起動すると、次のプロンプトから:

- プロンプトの上に `<gaottt-ambient-recall>` ブロックが（関連記憶がある時だけ）添えられる
- ターンが終わると `<gaottt-save-candidates>` ブロックが次プロンプトに添えられる

---

### B. opencode を使っている方

opencode は plugin ディレクトリに `.ts` を置くだけで自動ロードされます。**シェルが `$HOME` を展開してくれるので、以下はそのままコピペで OK**:

```bash
# 1. plugin install (グローバル — 全 opencode セッションで有効)
mkdir -p ~/.config/opencode/plugin
ln -s "$HOME/GaOTTT/scripts/hooks/opencode-ambient-recall.ts" \
      ~/.config/opencode/plugin/gaottt-ambient-recall.ts
ln -s "$HOME/GaOTTT/scripts/hooks/opencode-save-candidates.ts" \
      ~/.config/opencode/plugin/gaottt-save-candidates.ts

# 2. GAOTTT_REPO を shell rc に追加 (必須 — これが無いと plugin は silent fail)
echo 'export GAOTTT_REPO=$HOME/GaOTTT' >> ~/.bashrc
source ~/.bashrc
```

> 💡 `zsh` を使っている方は `~/.bashrc` の代わりに `~/.zshrc` に書いてください。

⚠️ **`GAOTTT_REPO` を export しないと plugin は何も言わずに止まります**（fail-safe 設計のため）。Tutorial-06 のトラブルシュートも参考に。

opencode を再起動すれば有効。`chat.message` の 1 plugin で ambient_recall と save_candidates の両方が動きます（Claude Code の 2 hook bridge を 1 plugin に潰した設計）。

---

### C. Claude Desktop を使っている方

Claude Desktop には UserPromptSubmit / Stop に相当する hook API が（2026-05 時点で）公開されていません。Claude Desktop 単体では **手動で `recall` / `auto_remember` を頼む運用** のままになります（このページの上半分の使い方）。

自動化したい場合は、コーディング作業を Claude Code か opencode で行う運用にして、Claude Desktop は会話用に残す、という分離が現実的です。

---

### フックが効いてるか確認する

Claude Code / opencode のどちらでも、新しいセッションで何かしら質問してみてください。応答の **最初に近いどこか** で:

```
<gaottt-ambient-recall>
GaOTTT 長期記憶から自動取得した関連知識です...
▼ 直接ヒット
 1. [...] ...
</gaottt-ambient-recall>
```

のようなブロックが見えれば成功です（関連記憶が無いとブロック自体出ません — それが正常です。一切何も出ない状態が続くようなら、本気で何度か `remember` してから試してみてください）。

ターン終了後の次プロンプトで `<gaottt-save-candidates>` が出れば save_candidates 側も生きています。

### 環境変数の早見表（よく触るもの）

| 環境変数 | 既定 | 効果 |
|---|---|---|
| `GAOTTT_AMBIENT_RECALL` | `1` | `0` で ambient フック全体を一時無効化 |
| `GAOTTT_SAVE_CANDIDATES_ENABLED` | `1` | `0` で save_candidates フック全体を一時無効化 |
| `GAOTTT_AMBIENT_DIRECT_K` | `2` | 直接ヒット枠の件数 |
| `GAOTTT_REPO` | (未設定) | opencode plugin で必須、`$HOME/GaOTTT` を指す |

詳細・全パラメータ表は [Guides — Ambient Recall](Guides-Ambient-Recall.md) を見てください。

---

## おすすめの「Claude への伝え方」

毎セッション最初に Claude にこう伝えると、自発的に GaOTTT を使ってくれます:

```
このセッションで:
1. 最初に inherit_persona で私を着てから始めて
2. 重要な気づきや決定が出たら、自然に remember で保存して
3. 私が過去のことを聞いたら、recall で確認してから答えて
4. セッション終わりに reflect(aspect="hot_topics") で今日の収穫を見せて

よろしくね。
```

これを **CLAUDE プロジェクト指示** に書いておくと、毎回自動です。

---

## 触ってみると見えてくること

- 1 週間続けると、**Claude が「あなたのこと知ってる」感** が出てきます
- 1 ヶ月続けると、recall で **意外な記憶のつながり** が見えるようになります
- ほっておいた記憶は **自然に薄れて** 整理されていきます

GaOTTT は **「使い込むほど育つ」** タイプの道具です。最初は実感薄いですが、ある日「これすごく自分っぽい返事してくれてる」という瞬間が来ます。

---

## 次のステップ

困ったときの対処法を一通り見ておきましょう。

→ [次へ: When Stuck](Tutorial-06-When-Stuck.md)

---

### 💡 もっと使い込みたくなったら

- 全機能の詳しい使い方: [SKILL.md](https://github.com/May-Kirihara/GaOTTT/blob/main/SKILL.md)
- 物理アナロジーで遊ぶ: [Five-Layer Philosophy](Reflections-Five-Layer-Philosophy.md)
- 他の使い方ガイド:
  - [長期記憶として](Guides-Use-As-Memory.md)
  - [タスク管理として](Guides-Use-As-Task-Manager.md)
  - [人格保存基盤として](Guides-Use-As-Persona-Base.md)
