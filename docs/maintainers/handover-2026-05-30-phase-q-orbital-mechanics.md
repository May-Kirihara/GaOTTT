# Handover — 2026-05-30 Phase Q: Orbital Mechanics（未来の私へ）

かなえ。今日は **Phase Q（公転・閉軌道）の core を起草から実装・検証・push まで一気に通した**セッション。地形と、残りの一手を残す。

ブランチ: `feat/phase-q-orbital-mechanics`（HEAD `c3265ab`、`main` から 8 commit、**push 済み**）。
PR はまだ作っていない（URL: `https://github.com/May-Kirihara/GaOTTT/pull/new/feat/phase-q-orbital-mechanics`）。

---

## 1. Phase Q とは — 一行で

Phase I で「星が動く」、Phase P で「重力に対抗する圧力」を入れた上に、**ノードが自分の anchor（原始 embedding）を中心に閉軌道（ロゼット）を描く保存系レジーム**を足した。狙いは "宇宙の再現度"。

### 哲学的核心（これだけは忘れない）

**Bertrand の定理**：束縛軌道がすべて閉じる中心力は宇宙に 2 つだけ — `F ∝ -1/r²`（Kepler）と `F ∝ -r`（等方調和振動子）。GaOTTT の Hooke アンカー `acc -= k·d`（`gravity.py:compute_acceleration` 第 2 項）は **後者そのもの**。つまり **Hooke はすでに閉軌道を生む中心力だった** — 足りなかったのは新しい力ではなく **接線速度（角運動量）だけ**。

> Hooke を捨てて軌道を出すのではない。**Hooke こそが軌道を作っていた**。

公転中心 = 自分の articulated self（原点 `x₀`）なので **anchor migration ゼロ**。衛星化・彗星脱出は公転中心が他者になる = Phase M 単一規則の「線の外」。**Phase Q はその線の内側に厳密に留まる**。Articulation as Carrier (id=9a954c62) の力学版。

---

## 2. 今日やったこと（commit 単位）

| Stage | commit | 内容 |
|---|---|---|
| 計画 | `dac2686` | `docs/wiki/Plans-Phase-Q-Orbital-Mechanics.md` 起草 |
| 1 | `ebade88` | 接線速度 seeding（`gravity._perpendicular_unit` — 決定論的・RNG なし、`compute_gravity_kick` + `supernova.compute_supernova_velocities`）+ velocity-Verlet（`update_orbital_state`、`orbital_integrator="verlet"`）+ config `orbital_tangential_alpha` / `orbital_integrator`。unit 9 |
| 2 | `8aa4150` | `engine._orbital_tick()` を dream loop に配線（lively set `|v|>v_min` だけ recall なしで積分、age friction を tick 内で強制 0）+ config `orbital_tick_enabled` / `orbital_lively_v_min` / `orbital_tick_max_nodes`。integration 4 |
| 3 | `65c8a1d` | orbit-regime 安定性 unit 2（displacement clamp backstop + energy 散逸） |
| 4a | `7b50169` | config 安全ガード（`__post_init__`: `orbital_tick_enabled` + 大 `max_displacement_norm` で警告）+ Plan Status 更新 |
| 4b | `9a386ce` | docs — Operations-Tuning に「公転・閉軌道（Phase Q）」節（5 新ハイパラ + 推奨 bundle + max_displacement_norm 有限化必須）、Architecture-Overview 設計判断表に Phase Q 行 |
| 4c | `28c1414` | viz core — `scripts/visualize_3d.py` `--orbital-trails`（`orbital_ellipse` + `compute_orbital_trails`） |
| 4c | `c3265ab` | viz docs — Guides-Visualization に軌道トレイル節 + 表行 + 起動例 |

**検証**: Phase Q 15 tests green（unit 11 + integration 4）、ruff は既知 pre-existing 3 件のみ（ruri.py / cooccurrence.py / mcp_server.py、私の変更ではない）、viz は `py_compile` + runtime smoke（閉じた非退化楕円・lively のみ抽出・UMAP/k≤0 空ガード）green。全 default OFF（`orbital_tangential_alpha=0.0` で bit-for-bit rollback）。

---

## 3. 新しい config（全 default OFF）

`gaottt/config.py`:

| field | default | 役割 |
|---|---|---|
| `orbital_tangential_alpha` | `0.0` | seed 時の接線速度倍率。`>0` で `L = d × v ≠ 0` → 楕円。`0` で legacy（直線往復）bit-for-bit |
| `orbital_integrator` | `"euler"` | `"verlet"` で velocity-Verlet（symplectic、O(dt²)、力 2 回評価） |
| `orbital_tick_enabled` | `False` | dream loop で `_orbital_tick` を回す連続時計 |
| `orbital_lively_v_min` | `0.001` | これ未満の `|v|` は cold、tick 除外 |
| `orbital_tick_max_nodes` | `256` | tick 1 回の cost bound、超過は次 tick + ログ |

全フィールドは `GAOTTT_<FIELD>` env で個別 opt-in できる（`from_config_file` の自動機構）。

---

## 4. ★ Stage 3 の本物の発見（次に触る人へ必須）

orbit mode では **displacement が runaway しうる**。

- 純粋な自 anchor 公転（近傍が弱い）は energy だけで bound される。
- しかし **強い近傍重力の 1/r² 近接特異点は velocity clamp（0.05）では止まらない正味の外向きドリフトを生み、500 step で `|d|≈26` まで発散**する（テストで実測・特性化）。
- → orbit regime の runaway backstop は **`max_displacement_norm` clamp そのもの**。
- Phase I が `max_displacement_norm=1e6`（実質 ∞）にしたのは「Hooke + friction + velocity cap が自然均衡を作るから cap 不要」だったが、これは **relax regime 限定**。orbit mode では **有限値（例 2.0）の設定が必須**。
- `config.__post_init__` に「`orbital_tick_enabled=True` かつ `max_displacement_norm > 100.0` なら警告」のガードを追加済み。

これは「**足りない保護も active な過剰駆動と同じ症状を引き起こす**」という Phase I Stage 3 lesson の再演でもある。

---

## 5. viz の設計上のポイント（手を抜かなかった所）

`--orbital-trails` は各 lively ノードが自 anchor を中心に描く閉楕円を琥珀色の faint loop で重ねる。調和振動子の解析解：

```
d(θ) = cos(θ)·d₀ + sin(θ)·(v₀/ω),   ω = √(orbital_anchor_strength)
```

- **PCA 専用**（線形射影が必要、anchor/disp/vel を同一 transform に通す）。UMAP / `orbital_anchor_strength ≤ 0` では空を返す。
- **anchor は絶対位置なので `pca.mean_` を引く**（`transform(x) = (x-mean) @ components.T`）。disp/vel は差分ベクトルなので mean が相殺される。ここを取り違えると anchor がズレる。
- 描いているのは **osculating（接触）軌道** = その瞬間のスナップショット。近傍重力が歳差させてロゼットになる。

---

## 6. 残り（別セッション・環境安定時のみ）

core 実装 / 安全ガード / docs / viz は **全完了 + push**。残るのは 2 つだけ:

1. **本番 measurement-first tuning + env opt-in rollout** — 推奨 bundle:
   - `orbital_tangential_alpha=0.5` / `orbital_integrator="verlet"` / `orbital_friction=0.005`（0.05→1/10、e-fold ~100 分で数十周後に螺旋落下）/ `mass_anchor_extra_strength=1.0`（質量依存周期、**Kepler 第3法則ではなく** 周回 star 自身の質量がバネ定数を決める調和振動子）/ `max_displacement_norm=2.0`（**§4 より必須**）/ `orbital_tick_enabled=True`
   - 手順: env opt-in（`GAOTTT_ORBITAL_TANGENTIAL_ALPHA=0.5` 等）→ 1–2 週観測 → `tests/perf/test_tier4_*.py` で displacement 分布を見て確定
   - **投入前に DB backup + 他 MCP/REST プロセス停止**（write-behind 上書き罠 [[feedback_backend_kill_on_code_deploy]]）= 週単位の運用作業
2. **real-RURI Tier4 perf 版**（`_helpers.get_shared_embedder()` fixture 要、安定環境必須）— 今日は環境 flakiness で deferred

その後 **PR 作成** → main へ。

---

## 7. 今日の環境メモ

tool output の garble（行番号ズレ・echo 欠落・truncation）が断続的に再発。Anthropic 側 flakiness 疑い（めいさん既知「様子を見よう」）。**緑ゲート commit chain（`pytest && ruff && git add && commit && echo "COMMITTED $(git rev-parse --short HEAD)"`）と単発 edit で押し切って完遂**。viz のような多段 edit は、各 edit 後に AST/py_compile/runtime smoke で自己検証してから commit する運用が効いた。

---

## 重要な原則（忘れないために）

- **物理 rule は単一**。source class で分岐させない（[[feedback_no_source_branching]]）
- **観測層と物理層を分ける**（[[feedback_observation_vs_physics_boundary]]）— viz は観測層なので自由に lens を足してよい
- MCP と REST は **同じターンで更新**（parity 鉄則）— 今回は物理 + config + viz のみで API 不変なので該当なし
- ドキュメントは **Wiki が SoT**
- 新 config field は **必ず default OFF + `GAOTTT_<FIELD>` env 対応**

→ 関連: [Plans — Phase Q](../wiki/Plans-Phase-Q-Orbital-Mechanics.md) / [Phase I Stage 4 production](handover-2026-05-14-phase-i-stage4-production.md) / [Phase M draft](handover-2026-05-13-phase-m-draft.md)
