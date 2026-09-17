# 計画 — multiverse supervisor /route 503: data_dir 優先順位逆転の修正

ステータス: **完了 (2026-09-17)** — WP-1/WP-2 実装・検証 green、Codex approve-with-notes
（指摘の test 追加対応済み）、手動 e2e PASS。本番 supervisor 再起動は利用者作業。

日付: 2026-09-17
リスク: normal / モード: fast（診断は deep 相当の証拠収集済み）
入力: docs/handoff/2026-09-17-multiverse-owner-lock-route-503.md

## 目標

他宇宙 backend の cold start が main 宇宙の `owner.lock` で 503 になる問題を、
根因（config の優先順位逆転）から解消し、hanaso-prototype の provisioning が
再開できるようにする。

## 根因（実機証拠付き・確定）

`gaottt/config.py::_resolve_overrides()` において:

1. `data_dir` は `field(default_factory=_default_data_dir)` のため、汎用 env
   ループ（`f.default is MISSING → continue`）の対象外
2. config file（`~/.config/gaottt/config.json`）に `data_dir` があると
   `overrides["data_dir"]` が file 値で確定し、`cls(**overrides)` が
   constructor 引数として優先 → default_factory（env 第一優先の dedicated
   resolver）が発火しない
3. 結果: 文書化された H5 優先順位「env > file > default」が `data_dir` に
   限り「file > env」に逆転

実機では `~/.config/gaottt/config.json`（2026-09-05 変更）が
`data_dir = ~/.local/share/gaottt-multiverse/universes/7b068385a92c`（main 宇宙）
に固定しているため:

- supervisor の `_build_spawn_env` は正しく `GAOTTT_DATA_DIR=<起動対象宇宙>` を渡す
- しかし spawn された backend の `from_config_file()` が file 値で上書き
- engine startup の `OwnerLease(Path(config.data_dir))` が **main 宇宙の**
  `owner.lock` 取得を試み、稼働中 main backend（heartbeat 生存）と衝突 →
  `LeaseHeldError` → readiness FAILED → `/route` 503

証拠:
- `logs/8aad216ab76c.log`: `Loaded config from ~/.config/gaottt/config.json` →
  `LeaseHeldError: owner.lock at .../7b068385a92c/... (heartbeat_age=8.7s)`
- 成功ログ（"Engine started" を含む log file）はすべて 8/29 以前 =
  config.json 変更（9/5）より前。9/5 以降の non-main 宇宙 spawn は全て失敗
- lease 機構自体は正常（main データの無断オープンを阻止）。データ破壊なし

### 副次事象の説明（handoff の補足観察）

- 「warm backend が 401 即時応答」: engine startup 失敗後も uvicorn プロセスは
  存続（transport は生きる / engine は sticky FAILED）。401 は token 不一致
  probe の応答。これらは failed-engine zombie
- 「supervisor が未起動と判断して起動を試みる」: 正確には zombie は
  initialize handshake に 200 を返すため PROBE_OK → ensure_backend は即 return →
  readiness FAILED で 503。**respawn は試みられない**（idle timeout 300s まで
  zombie が port を占有し続け、運悪く retry が全部 503 になる）
- → 副次 fix (WP-2): readiness FAILED を route 経路で 1 回だけ bounded recycle
  する硬化を入れる

## スコープ / 非スコープ

スコール:
- WP-1: `gaottt/config.py` — `GAOTTT_DATA_DIR`（/legacy `GER_RAG_DATA_DIR`）env が
  config file の `data_dir` に優先するよう `_resolve_overrides` を修正 +
  unit test
- WP-2: `gaottt/multiverse/supervisor.py` — `/route` で readiness FAILED の
  backend を 1 回だけ stop+respawn（recycle）+ unit test
- ドキュメント（PM 直接編集）: Troubleshooting 追記、handoff 更新

非スコープ:
- `~/.config/gaottt/config.json` の pin 自体の削除（利用者環境。修正後は
  supervisor 経路に影響しない。レポートに記載）
- supervisor の本番再起動（PM の shell policy で kill 不可。次ステップとして文書化）
- probe/readiness のセマンティクス変更（`_stop_backend` の 409 挙動等は不変）

## 実装方針

### WP-1: config.py（リグレッション fix）

`_resolve_overrides()` の file overrides 構築直後に:

```python
env_data_dir = (
    os.environ.get("GAOTTT_DATA_DIR")
    or os.environ.get("GER_RAG_DATA_DIR")
)
if env_data_dir:
    overrides.pop("data_dir", None)
    sources["data_dir"] = "env"
```

- pop により `default_factory=_default_data_dir()` が走り、env 第一優先の
  既存 semantics（mkdir・legacy 警告含む）と完全一致
- env 未設定時は file 値がそのまま有効（既存挙動不変）
- `resolve_config_with_sources` の provenance も "env"/"file"/"default" で正しく

テスト（`tests/unit/test_config_env_override.py` に追加）:
1. file data_dir + env → env 勝つ（今回のリグレッション）
2. file data_dir + env なし → file 勝つ（既存挙動の担保）
3. legacy `GER_RAG_DATA_DIR` も file に勝つ
4. provenance: env/file/default の各ケース

### WP-2: supervisor.py（route 経路の recycle）

`_Supervisor.recycle_failed_backend(universe) -> tuple[str, str] | None`:

- `ensure_backend` と同じ二層 lock（asyncio.Lock + flock）を取得
- lock 内で readiness を再取得し、FAILED 以外（健康回復・legacy・transient）は
  現在の (url, token) を返し recycle しない
- `_stop_backend`（PID 既知 → SIGTERM/SIGKILL、PID 不明で生存 →
  `_BackendAliveConflict` → None 返却で recycle 断念）
- `_ensure_locked` で respawn（例外面は ensure_backend と同一）

`/route` handler:

- 既存の `_await_backend_readiness` が dict かつ state==FAILED のとき
  1 回だけ recycle を試み、成功なら新 (url, token) で readiness を再取得
- 再取得後も FAILED なら従来どおり 503（新しい error 文面）
- 1 route call = 1 recycle で上限（loop なし）

テスト（`tests/unit/test_supervisor.py` に追加、既存の probe monkeypatch 基盤を使用）:
1. FAILED → recycle（stop + respawn）→ 健康 → 200 with fresh token
2. FAILED + PID 不明で生存 → recycle 断念 → 503（従来挙動）
3. recycle 後も FAILED → 503（新しい error）

## 検証

1. `.venv/bin/python -m pytest tests/unit/test_config_env_override.py tests/unit/test_config_provenance.py tests/unit/test_supervisor.py tests/integration/test_supervisor.py -q`
2. 全スイート: `.venv/bin/python -m pytest tests/ -q` + `ruff check gaottt/ tests/`
3. 手動 e2e（hermetic・本番不触）:
   `GAOTTT_CONFIG=<tmp pin>` + `GAOTTT_DATA_DIR=<tmp envdir>` で
   `from_config_file().data_dir` と mcp_server の readiness/実データ配置先が
   envdir になることを確認（修正前は pinned 側に作られる＝逆転の実証）
4. Codex final review
5. tests/perf は対象外（retrieval geometry / hot path 不変）

## 想定される異常と対処

- 既存テストが file 勝ち data_dir に依存していた場合 → それは文書化契約に
  反する前提。該当テストを特定し、正当な意図があれば要協議（現時点で
  grep 上は該当なし・implementer が確認）

## 受け入れ基準

- 上記テスト群が全て green
- 手動 e2e で env > file が実機コードパスで確認できる
- 本番再起動後の実 route 確認は次ステップ（ユーザー作業）として文書化
