# MCP Reference — Memory Tools

GaOTTT の中核となる 6 つの記憶ツール。詳細仕様は [`SKILL.md`](../../SKILL.md) のツールセクションを正とする。

## remember

知識を長期記憶に保存する。

```
remember(
  content: str,
  source: str = "agent",                  # agent/user/system/compaction/hypothesis/task/commitment/value/intention/style/relationship:<name>
  tags: list[str] | None = None,
  context: str | None = None,
  ttl_seconds: float | None = None,       # 既定: source が hypothesis なら 7日、task なら 30日、commitment なら 14日
  emotion: float = 0.0,                   # [-1.0, 1.0]、|magnitude| が boost
  certainty: float = 1.0,                 # [0.0, 1.0]、半減期 30日で減衰
)
→ "Remembered. ID: <uuid>" or "Already exists in memory (duplicate content)."
```

## recall

重力波伝播による検索。`prefetch` キャッシュを透過消費する。

```
recall(
  query: str,
  top_k: int = 5,
  source_filter: list[str] | None = None, # 制限フィルタ: 指定 source のみが seed pool に入る
  wave_depth: int | None = None,
  wave_k: int | None = None,
  force_refresh: bool = False,            # True で prefetch キャッシュを無視
  persona_context: list[str] | None = None, # Phase J Stage 2: 明示的 ID リスト。seed pool に強制注入 + persona boost
  tag_filter: list[str] | None = None,   # Phase J Stage 2: タグ substring (OR 一致) の node を seed pool に強制注入。source_filter を bypass
  output_mode: str = "full",             # MCP 専用トークン節約。"full"=全文, "compact"=300字切詰, "ids"=ID+スコアのみ
)
→ 各結果に id=<uuid> が含まれる
```

**`tag_filter` vs `source_filter` の使い分け:**
- `source_filter` — 制限フィルタ。seed pool の範囲を絞る（source が一致しないノードは入場できない）
- `tag_filter` — 拡張注入。embedding 距離に関わらず tag が一致したノードを強制的に seed pool へ追加。`source_filter` も bypass する（呼び出し側の明示的指定が優先）

**`output_mode` の選択:**
- `"full"` — 全文返却（詳細確認時）
- `"compact"` — 300 字切り詰め（通常利用、トークン節約に推奨）
- `"ids"` — ID + スコア行のみ（大量 ID を把握したいが内容不要な場合）

**Score breakdown (Phase O Stage 1):** 各結果に additive な内訳が 1 行で付く。`final_score = (vcos·decay + wave + mass + emo + cert) × sat` を literal に再現する 8 数 + 補助情報 (`persona_prox`, `cos`, flags `[bm25]` / `[forced]`)。LLM caller が「mass で勝ってる」「semantic 弱い」を一発判定できる:

```
[1] id=abc12345... (score=0.4231, virtual_score=0.1850, source=agent, displacement=0.0234)
  breakdown: cos=0.142 vcos=0.185·decay=1.000 +wave=0.060 +mass=0.245 +emo=0.000 +cert=0.000 ×sat=0.910 persona_prox=0.000
```

| field | 意味 | 出方 |
|---|---|---|
| `cos` | `raw_cosine` — pure cosine(query, original_emb) | informational (sum に入らない) |
| `vcos` | `virtual_cosine` — query · virtual_pos (displacement 反映) | sum に入る |
| `decay` | recency decay multiplier | vcos に掛かる |
| `wave` | gravity wave propagation の追加項 | additive |
| `mass` | `α · log(1+mass)` | additive |
| `emo` | emotion weighting | additive |
| `cert` | certainty boost | additive |
| `sat` | habituation saturation multiplier | 全体に掛かる |
| `persona_prox` | persona-graph 近接度 | informational (wave に baked-in) |
| `[bm25]` flag | BM25 lexical hit (informational) | wave に baked-in |
| `[forced]` flag | `tag_filter` / `persona_context` で強制注入された | informational |

REST (`POST /recall`) では `items[].score_breakdown` に上記 11 field がそのまま JSON で返る。`expose_score_breakdown=false` で全体 off (legacy 互換用)。

## explore

温度を上げた創発的探索。離れた記憶も引き寄せる。

```
explore(
  query=...,
  diversity=0.0-1.0,
  top_k=10,
  persona_context: list[str] | None = None,  # recall と同じ注入引数
  tag_filter: list[str] | None = None,
)
```

- `diversity=0.0` 通常検索に近い
- `diversity=0.5` 適度な探索（既定）
- `diversity=1.0` 最大多様性

## reflect

メモリ状態の分析。**11 種類の aspect**:

| aspect | 内容 |
|---|---|
| `summary` | 全体統計 |
| `hot_topics` | 高質量ノード |
| `connections` | 強い共起エッジ |
| `dormant` | 長期間未アクセス |
| `duplicates` | 近接重複クラスタ |
| `relations` | 有向リレーション |
| `tasks_todo` / `tasks_doing` / `tasks_completed` / `tasks_abandoned` | Phase D タスク系 |
| `commitments` / `values` / `intentions` / `relationships` / `persona` | Phase D 人格系 |

→ Phase D の使い方は [Tasks & Persona](MCP-Reference-Tasks-and-Persona.md)

## ingest

ファイル / ディレクトリの一括取り込み。

```
ingest(
  path: str,
  source: str = "file",
  recursive: bool = False,
  pattern: str = "*.md,*.txt",
  chunk_size: int = 2000,
  include_tool_results: bool = False,
)
```

対応形式:

- `.md` — `##` 見出し or サイズで分割
- `.txt` — 段落で分割
- `.csv` — 行単位、`content`/`text`/`body`/`message` 列を自動検出（`id` 列があれば `original_id` に使う）
- `.jsonl` — Claude Code 形式のチャット履歴（user prompt + 続く assistant 群を **1 exchange** にまとめて 1 document、CLI 注入や `permission-mode` / synthetic 行は skip、`tool_use` は `[tool:<name>]` で要約）

`include_tool_results` は `.jsonl` 専用。`true` にすると `tool_result` の生 stdout/stderr も exchange 本文に追記する（DB 容量が増えるので既定 `false`）。チャット履歴を流し込むときは `pattern="*.jsonl"`, `source="claude-code"` を渡す。詳細は [Operations — Ingestion](Operations-Ingestion.md)。

> **既存 backend は再起動が必要**: `.jsonl` ディスパッチと `include_tool_results` は loader 改修後の機能。古いプロセスがメモリにロードしていると `.jsonl` をプレーンテキスト扱いする。

## auto_remember

会話 transcript から保存候補をヒューリスティック抽出（**保存はしない**）。

```
auto_remember(transcript=..., max_candidates=5, include_reasons=True)
```

抽出される傾向:
- 決定・結論・採用/却下
- 失敗・成功・エラー・解決
- ユーザーの好み・禁止・制約
- 教訓・次回への申し送り
- 数値（メトリクス候補）

返り値の各候補には推奨 `source` と `tags` が付くので、内容を確認してから `remember` で正式保存する。

## ソースの使い分け

| source | TTL | 用途 |
|---|---|---|
| `agent` | 永続 | あなた自身の判断・発見・学び |
| `user` | 永続 | ユーザーの発言・好み・指示 |
| `compaction` | 永続 | コンテキスト圧縮時の退避 |
| `system` | 永続 | システム情報 |
| `hypothesis` | 7 日 | 仮説（自動消滅） |
| `task` | 30 日 | タスク（要 complete/abandon/revalidate） |
| `commitment` | 14 日 | 期限付き約束 |
| `value` / `intention` / `style` / `relationship:<name>` | 永続 | Phase D 人格層 |

→ 関連: [Tasks & Persona](MCP-Reference-Tasks-and-Persona.md), [Maintenance](MCP-Reference-Maintenance.md)
