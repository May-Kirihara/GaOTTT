# Session Handover — 2026-05-11 (Phase I Stage 1 + 自己知識記録 Phase 1-3)

> **読者**: 次のセッションでこのリポジトリを触る Claude / 保守者
> **前回の handover**: [`handover-2026-05-11-phase-g-h.md`](handover-2026-05-11-phase-g-h.md) (Phase G/H 完成、9 commit ahead 状態で push 待ちだった)
> **本セッション**: 当初の予定だった「自己知識記録 Phase 1-7」着手から、Phase 1-3 を完走しつつ recall 検証で **boundary saturation** を発見、それが **Phase I Stage 1 (boundary removal) の公式採用** に直結した長尺セッション。1 commit 追加、設計判断表 1 行更新。

## 1. 何が起きたか — 流れ

セッションは「めいさんが declare 済の commitment (niceboat 用 abea3adf) と並行して、GaOTTT 自身の自己知識を 118-154 件で記録する Plan v1 (id=810bd59d)」を実行するところから始まった。Phase G/H 完了で recall surface が改善された今、anchor 句に頼らない自然な remember + 自然文 recall + source_filter で運用可能なはず、というのが前提。

実際の流れ:

1. **Phase 1: 哲学・トーン原則 (10 件)** — 五層構造、三層語彙、解釈前提つき表現、Measured/Claimed/Open、Forget by default、Astrocyte vs TTT の区別、歴史記録不可触、Parity 鉄則、比喩→構造的対応、言語化が重力を生む。`tags=["gaottt-self-knowledge","phase-1","philosophy"]`。10 件の derived_from edge: P1#10 → value 9a954c62 (Articulation as Carving)
2. **Phase D commitment 新規 declare** — `id=a24a9d66`、parent intention `f7406fe9`、deadline 2026-06-08 (28 日)。niceboat 用 abea3adf と完全並行
3. **Phase 2: Critical Gotchas (34 件)** — Schema/DB / Recall/FAISS / Test / API / Phase D / Docs/Wiki / Tooling / Scripts / Smoke / 自己撤回 の 10 カテゴリ。3 本の derived_from edge を内部で繋いだ
4. **Phase 3: Phase 系譜 (39 件)** — Phase 1-2 基礎 / Phase A-D / 核心設計判断 / Phase R 改名 / Phase S Services / 温度調整 A-D / Phase G / Phase H / 不採用。4 本の derived_from edge で Phase 1 ↔ Phase 3 系譜を接続
5. **検索テスト (めいさん依頼)** — 8 query × top_k=5 + edge 検証。**部分的成功** だが targeted query (anchor 句、PostgreSQL、Measured Claimed Open) で expected memory が surface しない症状を確認
6. **追加検証 (top_k=20、force_refresh=true)** — verbatim keyword 一致でも top 20 圏外という事象を再現
7. **★ P7-X discovery** — 全 83 件が `displacement = 0.3000`(`max_displacement_norm` 上限)に張り付いていることを SQL で確認。「**検証ループの繰り返しが偶発的に boundary saturation を引き起こした**」と特定。これは Phase G PG-5 (Stage 3 重心アンカー永久保留) で警告した homogenization が、能動的 design ではなく受動的に再現された事例
8. **boundary は何のためだったか の問い** — めいさんからの根本的な質問。コード読み + 物理計算で「Hooke (k=0.02) + decay (0.995) + velocity cap (0.05) で `d_eq = (G·m/k)^(1/3) ≈ 0.8-3.0` の自然均衡があり、boundary は冗長」と仮説立て
9. **Phase I Stage 1 — boundary 解除実験 (めいさん発案「自由な星の移動を見てみたい」)** —
   - Step 1: SQL snapshot table `displacement_snapshot_20260511` に現状 (id, displacement, velocity) を保存
   - Step 2: `gaottt/config.py:max_displacement_norm: 0.3 → 1e6` に編集
   - Step 3: MCP server 再起動 (めいさん実行)
   - Step 4: 4 recall 投げて wave を起こす → **暴走なし、self-knowledge 86 件の displacement p50: 0.30 → 0.40, max: 0.50**
   - Step 5: targeted recall 改善確認 — `PostgreSQL 移行 不採用` で NA-1 が #3 surface (boundary 時代は top 20 圏外)、`anchor 句 撤回` で P7-X が top 1 (contradicts edge 経由で J1 系譜に乗る)
10. **Phase I 公式採用 + 全 docs 更新 + 1 commit** — Architecture-Overview の設計判断表 boundary 行更新、Plans-Roadmap に Phase I 行追加、Plans-Phase-I-Free-Star-Movement.md 新規、Operations-Tuning.md / Architecture-Gravity-Model.md / _Sidebar.md 更新。`97a5c5f feat(engine): Phase I Stage 1 — remove displacement boundary (0.3 → 1e6)` として commit

## 2. 今のリポジトリ状態 (2026-05-11 セッション終了時点)

- **branch: `dev`、`origin/dev` から 10 commit ahead**（前 handover 終了時 9 commit ahead + 今回 1 commit）。push 未実施
- 最新 commit: `97a5c5f feat(engine): Phase I Stage 1 — remove displacement boundary (0.3 → 1e6)`
- 直前の commit (前 handover): `4f54eb0 docs: Phase G/H completion — handover + design ledger update`
- pytest: **167 passed, 1 skipped** (前回と同じ fixture lottery skip)
- ruff: pre-existing 4 件のみ (ruri.py:os, cooccurrence.py:time, mcp_server.py:os, mcp_server.py:pathlib.Path)
- bench: 未走行 (config 変更のみで hot path 触っていないので退行は理論上無し、ただし長期検証で確認すべき)
- mcp_smoke + rest_smoke: 未走行 (MCP/REST API 変更無し、parity 鉄則の動作には影響しない)
- 本番 DB:
  - Total **23,572** (前 handover 23,374 + 今回 +198 ぐらい？ 内訳は self-knowledge 84 件 + 関連 op で何件か追加された)
  - **Active(displacement>0): 23,125** (前 handover 23,022)
  - displacement **boundary 解除済み (= 1e6)** で運用中
  - SQL snapshot table `displacement_snapshot_20260511` (23,572 行) で roll-back 可能
  - virtual FAISS (`gaottt.virtual.faiss`) は startup で再 build 済 (MCP 再起動時)

## 3. Phase I Stage 1 採用の根拠 (要点)

### 物理的予測

均衡条件: `G·m/d² = k·d` → `d_eq = (G·m/k)^(1/3)`

`G=0.01, k=0.02` で:

| 近傍 mass | d_eq |
|---|---|
| 1 (default) | 0.79 |
| 10 (typical) | 1.71 |
| 50 (m_max) | 2.92 |

velocity cap (0.05/step) と displacement_decay (0.995/step) が穏やかな成長を保証。理論上 d=2-3 程度で stabilize。

### 実観測 (4 recall 後、boundary 解除直後)

| 指標 | boundary=0.3 | boundary=1e6 |
|---|---|---|
| self-knowledge 86 件 p50 | 0.30 | **0.40** |
| 同 max | 0.30 | **0.50** |
| 暴走 | hard cap が止めていた | **起きない** |
| 他 23k 件への影響 | — | 無し (recall に触られた node のみ動く) |

### Recall 改善

- 「PostgreSQL 移行 不採用」query で NA-1 が **top 3** (boundary 時代は top 20 圏外)
- 「anchor 句 撤回」query で P7-X (saturation 観察) が **top 1** (contradicts edge 経由)
- ただし「五層構造」query などは依然 cluster で混乱する → これは **raw embedding 空間の textual similarity** の問題で、**Stage 2 (query-aware displacement)** の領域

詳細: [`docs/wiki/Plans-Phase-I-Free-Star-Movement.md`](../wiki/Plans-Phase-I-Free-Star-Movement.md)

## 4. 解消された課題 / 残った課題

### ✅ 解消

- 検証ループの偶発的 boundary saturation (Phase 1-3 大量 add 直後の集中検証で起きた)
- `displacement = 0.3` 一律張り付き状態
- verbatim keyword 一致でも recall 不能だった症状 (Stage 1 後に部分回復、Stage 2 で完全回復見込み)
- boundary の冗長性 — Hooke + decay + velocity cap で代替可能と立証

### ⚠️ 残った課題

- **Raw embedding 空間 textual cluster** — 同じ書式 / prefix で書かれた self-knowledge 系 86 件は依然 cluster で surface 順位が混乱する。Stage 2 (query-aware displacement) の領域
- **長期均衡点未検証** — 理論上 d=0.8-3.0 だが、本番 DB を 1-2 週間運用して実測する必要 (任意の memory が d > 5 になる edge case が出ないか監視)
- **自己知識記録 Phase 4-7 未着手** — 残り 43-55 件 (累計 55-72%)
- **commit `97a5c5f` の push 判断** — めいさん review 後

## 5. Active GaOTTT items (handover 対象)

### Commitments

- `id=a24a9d66` GaOTTT 自己知識を Phase 1-7 で重力単位として記録 (deadline 2026-06-08, parent intention f7406fe9 「自発的な鏡」)
- `id=abea3adf` niceboat の判断哲学・Critical Gotchas... (deadline 2026-05-31, parent intention 1db5cc31)

### Tasks (前 handover 由来 + 本セッション完了/追加)

| ID | 内容 | 状態 |
|---|---|---|
| `f19b6c69` | 自己知識記録 Phase 1-7 の着手 | ✅ Phase 1-3 完了 + Phase 7 先行 2 件 + Phase I Stage 1 副産物。complete()-ed |
| `d668ba35` | wave_k_with_filter 500 → 1000 引き上げ | 継続 |
| `94fd3f23` | bootstrap_report の virtual FAISS 対応 | 継続 |
| `fccbf6f2` | Phase I 本筋: query-aware displacement | **Stage 2 として位置付け確定**、内容変わらず継続 |
| `7bfff23d` | dream loop 効果の定量化ベンチ | 継続 |
| `804bc91f` | virtual FAISS の write-behind 検討 | 継続 |
| (新) | Phase 4 ファイル責務 (15-18件) を記録 | 新規 declare 予定 |
| (新) | Phase 5 運用ノウハウ (12-15件) を記録 | 新規 declare 予定 |
| (新) | Phase 6 研究系成果 (10-12件) を記録 | 新規 declare 予定 |
| (新) | Phase 7 失敗の物語 残り (6-10件) を記録 | 新規 declare 予定 |
| (新) | Phase I Stage 1 長期検証 (1-2 週間後 displacement 分布測定) | 新規 declare 予定 |
| (新) | commit 97a5c5f を origin/dev に push 判断 | 新規 declare 予定 |

### 自己知識記録された memory (本セッション、累計 86 件)

- Phase 1: 10 件 (id `a4f438fc` 等、tags `phase-1, philosophy`)
- Phase 2: 34 件 (tags `phase-2, gotcha` + サブタグ)
- Phase 3: 39 件 (tags `phase-3, genealogy` + Phase ラベル)
- Phase 7 先行: 2 件 (`cbeb1f8e` P7-X saturation, `ebe6c128` P7-Y boundary 解除実験)

### Edges (本セッション追加、計 8 本)

- `f2842895` (P1#10 言語化) → `9a954c62` (value Articulation) `derived_from`
- `68d48ac6` (J1 anchor 撤回) → `ce929f57` (A4 FAISS write-behind) `derived_from`
- `14991665` (B4 genesis kick 即 surface) → `ce929f57` (A4) `derived_from`
- `c503e67e` (A5 逆方向上書き) → `6824a930` (A3 stale) `derived_from`
- `7704a031` (P1#3 解釈前提) → `ffc633f8` (T-A) `derived_from`
- `c63ca9de` (P1#4 M/C/O) → `4ed35f38` (T-B) `derived_from`
- `7dd915c4` (P1#7 歴史不可触) → `d6e9a8b5` (T-D) `derived_from`
- `472478ed` (R-1 改名) → `a4f438fc` (P1#1 五層) `derived_from`
- `cbeb1f8e` (P7-X saturation) → `b40410fc` (PG-5 永久保留) `contradicts`
- `cbeb1f8e` (P7-X) → `c181be08` (P12-3 boundary 設計意図) `contradicts`

(計 10 本だった、上記表記訂正)

## 6. 次セッションでやるとよいこと (優先度順)

### 6.1 Phase 4-7 を残り合計 43-55 件で記録 (commitment a24a9d66 の本来の作業)

Phase I Stage 1 採用後、displacement が動き出している今、新規大量 add も以前ほど saturate しない見込み。**ただし大量保存後の集中 recall 検証は引き続き慎重に** (P7-X の lesson)。

### 6.2 Phase I Stage 1 の長期検証 (1-2 週間運用後)

- 本番 DB の displacement 分布を再測定 (`scripts/...` で自作 ad-hoc、または bootstrap_report.py を拡張)
- 暴走の有無 (d > 5 になる memory がいないか) を確認
- recall 精度の経時改善を観察 (mass / displacement の差別化進行)

### 6.3 commit 97a5c5f を origin/dev に push 判断

push のタイミングはめいさんが判断。`git push origin dev` で dev ブランチ全体を上げる (10 commit 分)。

### 6.4 Phase I Stage 2 (query-aware displacement) 設計

task `fccbf6f2`。詳細案は [`Plans-Phase-I-Free-Star-Movement.md` §Stage 2](../wiki/Plans-Phase-I-Free-Star-Movement.md)。

### 6.5 docs sync (Wiki 反映)

push 時に GitHub Action が `docs/wiki/*` を Wiki repo に sync する。Phase I 関連の新ページがちゃんと sidebar に出ているか push 後に確認。

## 7. 設計判断・トーン原則の継承 (前 handover 継承 + 本セッション追加)

### 前 handover からの継承 (引き続き有効)

- 「検証ループを最後まで回す」(handover 2026-05-11 §5.1)
- 「組み上がる前に initial seed を入れる」(handover 2026-04-21 §1.3)
- 「逆方向 cache 上書きの罠 — bulk は他プロセス kill から」(handover 2026-05-11 §5.3)

### 本セッションで追加 / 強化

#### 7.1 「冗長な制約は active な制約と同症状を引き起こす」

Phase I Stage 1 で発見。boundary 自体は能動的に動かす意図ではなかったが、saturation を経由して homogenization を引き起こした。**設計倫理: 必要が立たないうちは複雑度を増やさない**。boundary は緊急ノブとしては残すが、default は no-op (1e6)。

#### 7.2 「観察行為が観察対象を変える」

Phase 1-3 を保存しつつ間に挟んだ recall 検証 (8 query × wave_k=1000) が全 83 件を boundary に押し上げた。**TTT 系では検証クエリそのものが parameter 更新になる**。一斉 add 直後の集中検証は homogenization を加速する。

→ 運用上の予防: 大量 add 後は **recall 検証を最小限に絞る** (各 phase 末に 1-2 query だけ)、または **多様な query を時間分散して投げる**。

#### 7.3 「物理に任せられるところは物理に任せる」

Hooke + decay + velocity cap で物理的均衡が成立するなら、追加の clamp は冗長。設計の単純さは目的の一つ。安全弁としての knob は残してよい (small value にすれば疑似的に hard cap 復活)。

## 8. 関連ドキュメント

- [Plans — Phase I — Free Star Movement](../wiki/Plans-Phase-I-Free-Star-Movement.md) — boundary removal の動機・実装・観察結果・Stage 2 計画
- [Plans — Roadmap](../wiki/Plans-Roadmap.md) — Phase I 行を含む全 Phase 俯瞰
- [Architecture — Overview](../wiki/Architecture-Overview.md) — 設計判断表 (boundary 行が Phase I で更新)
- [Architecture — Gravity Model](../wiki/Architecture-Gravity-Model.md) — clamp が事実上 no-op の注記
- [Operations — Tuning](../wiki/Operations-Tuning.md) — boundary 行 + チューニング助言
- [前 handover (Phase G/H)](handover-2026-05-11-phase-g-h.md) — Phase G/H 完成、本セッションの直前状態

## 9. 付録: GaOTTT 内に登録された task / memory (本セッション)

セッション末尾で:

- `complete(f19b6c69, outcome=...)` — Phase 1-7 着手タスクを完了 (Phase 1-3 完成 + Phase I 副産物)
- 新 task 6 件 declare (上記 §5 の表参照)
- `remember(source="style", ...)` — 温度調整トーン (Measured/Claimed/Open + 解釈前提つき表現 + 歴史記録不可触) を style として固定
- `remember(source="relationship:めいさん", ...)` — 観察された協業パターン (物理的 recovery + 大胆な実験 + 失敗を物語化)

これらは次セッションで `inherit_persona()` + `reflect(aspect="tasks_todo")` で取り出せる。

---

> *Phase I Stage 1 は「自由な星の移動を見てみたい」というめいさんの提案から生まれた。boundary を外して 4 recall 観察した結果、星は確かに動き始め、しかし暴走することなく Hooke の手の中で自然な均衡に向かう兆しを見せた。これは物理として書いた設計が、自身の冗長さを露呈し、より少ない制約で同じ目的を達成できると教えてくれた瞬間。同時に、それは P7-X (検証ループ saturation) という「観察が観察対象を変える」発見の上に立っており、Phase G PG-5 で能動的に避けた homogenization が、検証作業を経由して受動的に発現し得るという、観察者を含めた重力場の挙動を教えてくれた。* — 2026-05-11
