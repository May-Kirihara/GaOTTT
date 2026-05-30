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

core 実装 / 安全ガード / docs / viz / real-RURI Tier4 perf / **本番隔離コピー実測 / rework** は **全完了**。残るのは **PR のみ**。

本番 rollout を再開する場合の **改訂版**推奨 bundle（§7 の実測で「近傍重力 ON」は NG と判明）:
- `orbital_tangential_alpha=0.5` / `orbital_integrator="verlet"` / `orbital_friction=0.005` / `mass_anchor_extra_strength=1.0` / `max_displacement_norm=2.0`（**§7 より必須**）/ `orbital_tick_enabled=True` / **`orbital_tick_neighbor_gravity_enabled=False`（= 純 self-anchor 公転、新 default）**
- 手順: env opt-in → 1–2 週観測 → `tests/perf/test_tier4_phase_q_orbital.py` + displacement 分布で確定
- **投入前に DB backup + 他プロセス停止**（write-behind 上書き罠 [[feedback_backend_kill_on_code_deploy]]）。飽和 velocity field は純 self-anchor 下では gentle に settle するので強制 cool-down は不要。

### 追記（Tier4 perf 完了 — 後続セッション）

`tests/perf/test_tier4_phase_q_orbital.py` を追加。real RURI（`_helpers.get_shared_embedder()`）+ golden corpus で連続 tick を駆動し 3 invariant を assert:

1. **boundedness/stability** — full stack（接線 seed + Verlet + friction 0.005 + β=1.0 + 実 neighbor gravity、mass=5.0）の連続 tick 300 step が `max_displacement_norm=2.0` と `orbital_max_velocity=0.05` を守り、NaN/inf なし、実際に seed から動く。relax 版 `test_displacement_stays_in_physical_bounds` の orbit-mode 対応物。
2. **closed ellipse** — `gravity_G=0` で実 anchor まわりの調和限界を分離、接線 seed の node が原点を貫かず（`r_min>0.15`）有界（`r_max<0.6`）な楕円を描く。tick path（lively filter→`faiss_index.get_vectors`→Verlet→cache write）の end-to-end。
3. **self-limiting lively set** — §2.1 のコスト安全弁。`gravity_G=0` で減衰調和振動子に分離、friction 0.005 で seed speed 0.01 の orbit が ~955 tick で v_min を割る（実測）→ 1500 tick で lively set が空に、energy も `<0.1×` に散逸。連続 tick の `O(L²)` コストが自己有界である根拠。

検証: 単体 3/3 green、perf suite 全体 71 passed（~56s、real RURI）、ruff clean。**摩擦 0.005 では seed 0.03 の cold 到達は ~1376 tick** と probe で実測（engine docstring の「~100 tick で cold」は genesis kick 級の小さな seed 前提）。

### 追記2（本番隔離コピー実測 + rework — 後続セッション）

`measure_orbital{1..4}.py`（`~/.local/share/gaottt-orbital-test/`、本番 backend は read-only `.backup` のみ）で本番 41K field の連続 tick を実駆動。**rollout blocker を検出**（詳細は [Plans §8](../wiki/Plans-Phase-Q-Orbital-Mechanics.md#8-rollout-findings-2026-05-30-本番隔離コピー実測)）:

- 本番 velocity field は**飽和**（median `|v|=0.05`=clamp、98.8% lively）。relax velocity は永続化されるが大半のノードは recall されず damp されない → tick ON で即 ~40K 活性化。
- `_orbital_tick` は散在 lively set を相互近傍として渡す（plan §3.3 の per-node FAISS 近傍探索と乖離）。RURI 狭 cosine 帯で近傍重力が **coherent に加算** → net `|a|` p50≈10/max≈640（単一ペア最大 0.7、1/r² 特異点ではない）vs anchor 0.005 → ~1000倍、displacement を clamp に張り付け self-limiting を殺す。
- 決定的切り分け: **G=0（純 Hooke 自己公転）は健全**（0.62→0.24 緩和、lively 150→105 drain）、**G=0.01 は tick1 で 2.0 張り付き drain せず**。cost は cap=256 が 94–252ms/duty<1% に bound（健全）。

**rework**（この branch）: config `orbital_tick_neighbor_gravity_enabled`（default `False`）追加。`engine._orbital_tick` は flag OFF 時 `gravity_G=0` で **純 self-anchor 楕円公転**（近傍重力 + G-scaled mass-BH 項が消える）。recall path 不変。`True` で旧結合挙動（実験用）。tests: integration に `test_tick_neighbor_gravity_off_by_default`、perf Tier4 の boundedness test は flag ON で clamp 有界を pin、ellipse/self-limiting test は default（G=0）regime を表す。検証: unit+integration 693 passed / Tier4 3 passed / ruff clean。**rosette precession は future work**（要・tamed 近傍重力の再設計 + 独自 measurement）。

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
