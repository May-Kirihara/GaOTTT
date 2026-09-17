# 引き継ぎメモ — multiverse supervisor: 他宇宙backend起動が main宇宙の owner.lock で 503

## ステータス

- 状態: **解決済み（2026-09-17、GaOTTT 側で原因特定・修正・検証完了。本番 supervisor 再起動のみ残作業）**
- 日付: 2026-09-17（発見・再現・同一日内に解決）。初出は 2026-09-16（hanaso WP16-E5 実機検証時・当時は環境由来と記録）
- 担当: PM エージェント（hanaso-prototype セッションでの診断。hanaso リポジトリ外の本件は GaOTTT 側での扱いを想定）
- 概要: supervisor の `/route` が、**起動対象とは別の宇宙（運用中 main 宇宙）の `owner.lock`** を取得しに行って
  `LeaseHeldError` → 503 になる。main backend が稼働中（heartbeat 生存）の間、
  他宇宙の cold start が**無期限に**阻害される。

## 解決の要約（2026-09-17 追記）

- **根因**: `~/.config/gaottt/config.json`（2026-09-05 変更）が `data_dir` を main 宇宙パスに固定。
  `data_dir` は `default_factory` フィールドのため `GaOTTTConfig._resolve_overrides()` の汎用 env
  ループは対象外で、**config file の `data_dir` が `GAOTTT_DATA_DIR` env に勝つ優先順位逆転**が存在した。
  supervisor は正しい env を渡していたが、backend 側で file 値に釣り戻され main 宇宙の lease を取りに行った。
  証拠: `logs/8aad216ab76c.log`（`Loaded config from ~/.config/gaottt/config.json` → main 宇宙の lock で
  `LeaseHeldError`）、成功ログは全て config 変更（9/5）以前、9/5 以降の non-main 宇宙 spawn は全滅
- **本質的疑問への回答**: spawner の lock パス解決は宇宙ごとに分離されていた（正しい）。
  backend 側の config 解決が悪かった。「全宇宙共通の起動排他」という設計意図も存在しない
  （多宇宙並立が設計どおり。優先順位バグが分離を壊していた）
- **補足観測の説明**: 「warm backend が 401 即時応答」は engine FAILED の zombie プロセス
  （transport は生存・engine は sticky FAILED）。probe は initialize handshake で OK を返すため
  supervisor は respawn せず、idle timeout 300s まで 503 が継続していた
- **修正** (2 点):
  1. `gaottt/config.py`: `GAOTTT_DATA_DIR`（/legacy `GER_RAG_DATA_DIR`）env があれば file の
     `data_dir` override を pop → dedicated resolver（env 第一優先）に委任。優先順位契約「env > file > default」復活
  2. `gaottt/multiverse/supervisor.py`: `/route` が readiness FAILED を観測したとき 1 回だけ
     stop + respawn（recycle）を試みる。PID 不明で生存の backend は kill せず断念（安全側）
- **検証**: unit 47 + integration 14 green（本環境の config pin がある実機で、修正前は
  `test_mutual_isolation` が逆転により失敗していたのが全 green化）。hermetic e2e で
  `GAOTTT_CONFIG` pin + `GAOTTT_DATA_DIR` env → engine が env 側で起動することを実際の
  mcp_server 起動で確認。Codex review: approve-with-notes（指摘は test 追加で対応済み）
- **残作業 (利用者)**: **supervisor (PID 確認の上) と backend の再起動** — 常駐 process は
  in-memory module を保持するため（CLAUDE.md「code deploy 時の backend 再起動」参照）。
  再起動後、hanaso 側 provisioning の実 route で 503→200 になることを確認。
  任意: `~/.config/gaottt/config.json` の `data_dir` pin 削除も検討（修正後は supervisor 経路に
  影響しないが、env なし直接起動の tool が main 宇宙の lease に衝突し得るのは残るため）
- 詳細: [計画書](../plans/2026-09-17-multiverse-data-dir-precedence.md) /
  [Operations — Troubleshooting](../wiki/Operations-Troubleshooting.md) 該当セクション

## 環境（解決時点の記録として残す）

- supervisor: `http://127.0.0.1:7880`（開発機上・単一プロセス）
- main宇宙: `7b068385a92c`（owner_label=`main`・port 7890・常設稼働）
- hanaso-prototype backend が supervisor client として利用
  （provisioning: 宇宙create → `/route` → seed投入 → ready）
- 宇宙登録簿: 総70（active 3 / deleted 67）。削除系は冪等で問題なし
  （`DELETE /admin/universes/{id}` は 200 + trash化、404 も成功扱い）

## 現象

### 再現手順（2026-09-17 16:2x JST に実測）

```bash
# 1) 新規宇宙作成 — これは成功する（201・即時）
curl -X POST -H "X-Admin-Key: $KEY" http://127.0.0.1:7880/admin/universes \
  -d '{"owner_label":"shabero-diag-pm-20260917-routecheck"}'
# => 201 {"universe_id":"8aad216ab76c","api_key":"...","port":7893} (0.02s)

# 2) その鍵で route — ここが失敗する（503・5.4s）
curl -X POST http://127.0.0.1:7880/route -d '{"api_key":"<作成時のapi_key>"}'
# => 503 {"detail":"Backend startup failed: LeaseHeldError: owner.lock at
#      /home/misaki_maihara/.local/share/gaottt-multiverse/universes/7b068385a92c/owner.lock
#      is held by active owner '3066791da0684d58a2dfab0a06eef9ec' (heartbeat_age=8.7s)"}

# 3) main backend は実際に稼働中（heartbeat_age=8.7s は生存している正常値）
```

診断用宇宙は確認後すぐ削除済み（200 / trash化）。

### 本質的な疑問

失敗したのは宇宙 `8aad216ab76c` の起動なのに、取得しに行った lock は
**`universes/7b068385a92c/`（main宇宙）の `owner.lock`**。

- spawner の lock パス解決が宇宙ごとに分離されていない（常に main / 先頭宇宙の
  lock を見ている）可能性
- あるいは「全宇宙共通の起動排他」として main の lock を意図的に使っているなら、
  **main 常設稼働が他宇宙の起動を永久にブロックする設計**になる（その意図は
  README/設計書に見当たらない要確認）

### 補足の観測（状態不一致の疑い）

- 過去に起動に成功した宇宙 backend（port 7891 / 7892）は**今も生きていて
  `/mcp` に即時 401 応答**する（プロセス warm）
- にもかかわらず、それらの宇宙に対する `/route` も同種の 503 に落ちる
  （hanaso 側 provision job の `SUPERVISOR_HTTP_ERROR` が warm 後も継続したため）
- → supervisor が「backend 未起動」と判断して起動を試み、main の lock に当たって
  いる可能性。実プロセスの生死と supervisor の管理状態が乖離していないか確認価値あり

## 影響（hanaso-prototype 側）

1. **パスキー登録アカウントの provisioning が完了しない**: 宇宙createは成功するが
   seed投入（`/route` → MCP remember ~20件）に到達できない。job が
   `SUPERVISOR_HTTP_ERROR` で retry_wait を繰り返し、account が `provisioning` に
   滞留（本日16時台の実測: 試行8回・すべて失敗）
2. アカウントが `active` にならないため、そのアカウントの機能（記憶recall・
   WP16開発用リセット等の account 必須機能）が使えない
3. **2026-09-16 の WP16-E5 実機検証**で full_init の宇宙再作成周期
   （旧宇宙trash → 再provision → seed確認）が全く通らず、
   「admin契約は検証済み・route/MCP は環境503で skip」として正直に未実施扱いに
   した原因が本件（hanaso `docs/runbook.md` §5.12 に記録済み）

## 回避策・暫定対処

- ~~supervisor 再起動~~ → 修正された supervisor で解決（下記検証）
- hanaso 側は診断目的の宇宙作成後は必ず削除する運用で対応（今回も実施）

## 確認して ほしい箇所（GaOTTT 側）

1. `/route` → backend 起動経路の **owner.lock パス解決**
   （起動対象宇宙 ID ではなく `7b068385a92c` の lock を見ている直接原因）
2. 実 backend プロセス稼働中に supervisor が「未起動」と判定して起動を試みる
   条件（状態管理・heartbeat の読み先）
3. （設計意図として）多宇宙並立を許すなら、main 常設稼働と他宇宙起動の
   排他関係の仕様化

## 関連記録

- hanaso-prototype `docs/runbook.md` §5.12（開発用リセット・実supervisor実施状況）
- hanaso-prototype `docs/handoff/wp16-handoff.md`（E5 real supervisor skip の記録）
- 同時刻の本件とは独立: LLM host（別機 192.168.82.191）が約5秒/tokenに低速化する
  現象が同日発生——GaOTTT backend の RURI embedder cold start との資源競合の
  可能性あり（未確証・参考まで）

## hanaso側での修正後検証（2026-09-17・PMエージェント実施）

1. **route 再現試験**: 診断宇宙create→`/route`→**200**（`{"url":"http://127.0.0.1:7893/mcp","token":...}`・
   cold start 5.4s・main宇宙稼働中）→削除（200）。旧503は再現せず
2. **滞留provisioningの回収**: 修正前から `SUPERVISOR_HTTP_ERROR` で
   retry_wait中だった shabero の provision job（試行8-9回）が再試行で成功——
   滞留アカウント2件とも `active`・宇宙 `ready`（seed_version=nagi-core-v4）
3. **WP16-E5 実機検証の完了**: `SHABERO_REAL_SUPERVISOR=1 uv run pytest
   tests/integration/test_debug_reset_real_supervisor.py` → **2 passed**
   （admin契約 + full_init宇宙周期: 実route・実MCP seed・新宇宙読み書き込み）。
   当レポートの影響3に挙げた未検証項目は解消。hanaso側 runbook §5.12・
   wp16-handoff の記録も実測に更新済み
