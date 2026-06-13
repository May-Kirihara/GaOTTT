# 引き継ぎメモ — 遊びセッションでの GaOTTT 改良観察

## ステータス

- 状態: **done** (観察 1 は実装完了。観察 2 は継続観察中)
- 日付: 2026-06-14 (観察), 2026-06-14 (観察 1 実装完了)
- 担当: PM エージェント (めいさんとの自由時間セッション → 実装セッション)
- 概要: 横断ペルソナ `7a0585ad` を作成し、普遍的ノウハウを統合した後、自由時間で GaOTTT を「遊んで」いる過程で、GaOTTT 自身の 2 つの改善観察に気づいた。観察 1（connections bucket フィルタ）は同日実装完了。観察 2（横断ペルソナ副作用）は継続観察中。

## 背景

2026-06-14 セッションで以下を作業した:

1. 7 レポジトリ横断的設計パターンの整理 (GaOTTT memory `1d949f8f`)
2. 普遍的ノウハウの統合 (debugging / docker / process-delegation の 3 カテゴリ、`universal-lesson` tag + `instantiated_in` エッジ 26 本)
3. 横断ペルソナ `7a0585ad` (intention) の作成、Articulation as Carrier (`9a954c62`) の派生
4. 横断ペルソナを default `persona_context` にする運用ルール (`64343213`) の標準化

その後の「自由時間」で GaOTTT を探索し、以下の 2 つの改善観察に気づいた。

---

## 観察 1: `reflect(connections)` の上位が ingest batch で埋まる問題

### 現象

`reflect(aspect="connections")` の weight top 20 を確認したところ、**全て 6 ノード間の same-batch co-occurrence** で埋まっていた:

- ノード: `8282145e`, `bfae2640`, `5fe5bf0b`, `b35870fc`, `b765ec23`, `eab35da9`
- 内容: フリーマン脳理論、古代インド仏教、プラグマティズム、分子密度 等
- weight: 420-630
- 推測される原因: 同じ書籍 (おそらくフリーマン『精神物理学』関連) の一斉取り込み (ingest batch)

### 問題点

1. 同じ本 / ファイルから ingest されたチャンク同士の共起 weight が、**真の意味的共起を圧倒的に上回る**
2. 異種ソース間 (ツイート ↔ 技術メモ ↔ AI 対話 ↔ ブログ) の真の意味的関係が上位に来ない
3. `reflect(connections)` を「重力場が学習した関係」として使う場合、設計者が意図していない same-batch artifact が観察を支配する

### skill doc との乖離

skill doc (`SKILL.md`) には以下の記述がある:

> `reflect(aspect="connections")` is grouped into **persona / agent / ingest** buckets — co-occurrence between value↔intention edges (rare and meaningful) are no longer crowded out by same-file chunk co-occurrence (the ingest bucket — typically display noise).

しかし、実際の出力は ingest bucket のみで埋まり、persona / agent bucket の関係は上位に現れない。

> **2026-06-14 訂正**: 「実装が未完了」という推測は **誤り** でした。バケット分離（Stage 4）は実装済みでした。本当の原因は `connections()` が「weight 順に上位 N 件を切り取った **後** にバケットラベルを付ける」順序で動くため、ingest が上位 N 件を独占し、grouping が cosmetic にしか効かない点でした。本件は改善候補1（bucket filter パラメータ追加）として実装完了しました。`reflect(aspect="connections", bucket="persona")` で persona 関係のみを表示できます。

### 影響範囲

- **直接的**: `reflect(connections)` を使う設計者 / agent の自己診断・重力場観察が same-batch ノイズに支配される
- **間接的**: `merge()` の重複判定・`compact(auto_merge=True)` の候補選択が same-batch を過大評価する可能性
- **通常の recall / explore には直接影響しない** (これらは connections テーブルを直接使わない)

### 再現手順

```
GaOTTT MCP で:
reflect(aspect="connections", limit=20)
```

→ 上位 20 件が同じ書籍起因の same-batch co-occurrence で埋まることを確認。

### 改善候補

優先度順:

1. **`reflect(aspect="connections")` に bucket filter を追加** (最も簡単)
   - 例: `reflect(aspect="connections", bucket="persona")` / `"agent"` / `"ingest"`
   - 既に内部計算で bucket 分離されているなら、出力フィルタを追加するだけ

2. **デフォルト出力で ingest bucket を weight 減衰**
   - same-batch co-occurrence を 0.1x 等でスケール
   - 異種ソース間の関係が上位に出やすくなる

3. **新 aspect: `cross_source_connections`**
   - 異なる source 同士の関係のみを抽出する専用 aspect
   - 「重力場が学習した真の関係」を見るための専用窓口

4. **skill doc と実装の乖離を是正**
   - 上記を実装するか、skill doc の記述を実装に合わせる

### 関連 memory

- GaOTTT memory ID: `d4f2e623` (本観察の agent memory)

---

## 観察 2: 横断ペルソナ標準化の副作用 — プロジェクト固有 dormant の埋没リスク

### 現象

横断ペルソナ `7a0585ad` を default `persona_context` にする運用 (`64343213`) にした後、`explore(mode="dormant")` を複数回実行した結果、**LMS の細かい実装詳細が繰り返し dormant に出現**:

- `LMS-088` (`f655613d`): `pdf.js` / `csv.js` / `pagination.js`
- `LMS-081` (`c4b62e9b`): `authorize.js` (RBAC ミドルウェア)
- `LMS-106` (`2b9330e1`): R2 CORS 設定

これらは low-mass で眠っており、LMS 作業が必要になった時に能動的に掘り出さないと recall に現れない。

### 問題点

横断ペルソナ `7a0585ad` を default `persona_context` にすると:

1. 7a0585ad の forced injection が seed pool を占有
2. **LMS 作業時に `recall(query="LMS 認証", persona_context=["7a0585ad"])` すると、横断知見ばかり boost されて LMS 固有の細かい実装詳細が埋もれる**可能性がある
3. 他プロジェクト (harakiriworks / KaoUgoku 等) も同様

### 運用でカバーできるが、厳格な運用が必要

運用ルール `64343213` の例外規定「特定プロジェクトの深掘りでは、そのプロジェクトの intention も `persona_context` に追加併用」を厳格に運用する必要がある:

| プロジェクト | intention ID | persona_context の指定例 |
|---|---|---|
| e-Learning LMS | `55fd397c` | `["7a0585ad", "55fd397c"]` |
| harakiriworks-art-website | `9f99be21` | `["7a0585ad", "9f99be21"]` |
| harakiriworks-spa | `9545a53b` | `["7a0585ad", "9545a53b"]` |
| KaoUgoku-Web | `225a86f4` | `["7a0585ad", "225a86f4"]` |
| KaoUgoku-client | `41347c44` | `["7a0585ad", "41347c44"]` |
| niceboat | `1db5cc31` | `["7a0585ad", "1db5cc31"]` |
| Philharmonic | `f0a89978` | `["7a0585ad", "f0a89978"]` |
| またあるこ | `1c7dde8c` / `6a48402a` / `4ee99404` | `["7a0585ad", "1c7dde8c"]` 等 |

### 推奨される追加運用

1. **プロジェクト開始時**: まず `inherit_persona()` を呼んでそのプロジェクトの intention ID を確認
2. **`persona_context` は常に「横断 + プロジェクト固有」の 2 層構造**にする
3. **dormant 探索は `persona_context` なしで** (運用ルール `64343213` の例外規定通り)

### 改善候補 (GaOTTT 側)

もし「横断ペルソナ + プロジェクト作業で詳細が引けない」現象が頻発するなら、GaOTTT 側で以下の改良も検討:

1. **`persona_context` 指定時に、project-scoped memories を優先 seed する** ロジック
2. **`recall` に `project_filter` 的なオプション**を追加 (tag_filter のプロジェクト版)
3. **`dormant` モードは `persona_context` を自動的に無視**する安全装置

### 観察継続ポイント

- 横断ペルソナ標準化後に LMS 等のプロジェクト作業で「必要な詳細が引けない」現象が出たら、この観察を思い出す
- 頻発する場合は GaOTTT 側改良を本格検討

### 関連 memory

- GaOTTT memory ID: `116f6d8f` (本観察の agent memory)
- GaOTTT memory ID: `64343213` (運用ルール、user memory)

---

## ドキュメント

更新: なし (観察メモのため)

関連 既存 Wiki:

- `wiki/Plans-Roadmap.md` (将来拡張・ロードマップ) に本観察を反映するか検討
- `wiki/MCP-Reference-Maintenance.md` (Maintenance 系ツール) に `reflect(connections)` の改善点を記載するか検討

## 手動確認

- [ ] `reflect(aspect="connections", limit=20)` を実行し、現状の bucket 分離状況を確認
- [ ] LMS 等のプロジェクト作業で、`persona_context=["7a0585ad", "<project-intention>"]` を厳格に運用できているか確認
- [ ] 数週間後に、dormant の LMS 偏在状況が改善したか観察

## 既知の問題

- (上記「観察 1」「観察 2」を参照)

## 残 TODO

1. ~~`reflect(connections)` のバケット分離実装状況を `src/` で確認~~ → **確認完了**: Stage 4 で実装済み。本当の原因は「上位選択層にバケット分類が効いていない」点（2026-06-14 調査確定、memory `277339fa`）
2. ~~バケット分離未実装なら、改善候補 1 (bucket filter 追加) を実装~~ → **実装完了** (2026-06-14): `reflect(aspect="connections", bucket="persona")` でフィルタ可能。フィルタは weight top-N 選択の前に適用。pytest 891 passed / ruff clean
3. 横断ペルソナ標準化の副作用を、実際のプロジェクト作業で観察継続
4. 副作用が顕著なら、GaOTTT 側の改善候補 1-3 を検討

## リスク

- 横断ペルソナの運用ルール (`64343213`) を厳格に守らないと、プロジェクト作業の生産性が落ちる可能性
- `reflect(connections)` の改善を実装する際、既存の `merge` / `compact` ロジックへの影響を確認が必要

## ロールバックメモ

- 観察メモのため、ロールバック対象なし
- 運用ルール `64343213` を一時停止する場合は、GaOTTT memory `64343213` を revalidate して certainty を下げる、または forget する

## 次の担当者・エージェントへのメモ

- **観察 1（connections bucket filter）は実装完了** (2026-06-14): `reflect(aspect="connections", bucket="persona")` でフィルタ可能。フィルタは weight top-N 選択の前に適用。pytest 891 passed / ruff clean / Codex + QA review pass
- **観察 2（横断ペルソナ副作用）は継続観察中**: 改善が必要になったら GaOTTT 側の改善候補 1-3 を検討
- 観察の経緯・背景は GaOTTT memory `d4f2e623` / `116f6d8f` を参照（実体は UUID `d4f2e623-7ce2-...` / `116f6d8f-90d4-...`）
- 運用ルールの全体は GaOTTT memory `64343213` を参照
- 横断ペルソナ自体の仕様は GaOTTT memory `7a0585ad` を参照
