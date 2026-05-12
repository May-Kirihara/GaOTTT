# Session Handover — 2026-05-13 (Phase I Stage 3 完了 — Mass-gated Query Attraction)

> **読者**: 次のセッションでこのリポジトリを触る Claude / 保守者
> **前回の handover**: [`handover-2026-05-12-self-knowledge-completion.md`](handover-2026-05-12-self-knowledge-completion.md) (自己知識記録 Phase 1-7 完遂)
> **本セッション**: 前 session 観察の単一アトラクタ pathology を **Phase I Stage 3 — Mass-gated Query Attraction** で物理的に矯正。最小実装 (~10 行) + テスト 4 件追加 + docs 5 ファイル同期、コミット未実施 (実装完了状態でめいさん review 待ち)。

## 1. 何が起きたか — 流れ

1. **セッション初期化** — `/gaottt` で `inherit_persona()` + recall。前 handover (2026-05-12) 起点で 4 active commitments を把握。Phase I Stage 1/2 完了済、Stage 3 は将来課題として空き枠だった
2. **問題提起** — めいさんから「GaOTTT への記録のヒット率が有意に低い」報告。設計哲学合致な解決策を探したい
3. **診断 (recall + reflect)** — DB 23,994 件、source 分布で `file` 11k + `tweet/like` 12k = 95% が dense corpus、`agent`/`value`/`commitment` 系の意図的知識は 3.4% (824 件)。hot topics 上位 10 がすべて `file` の書籍本文。私のテスト recall でも抽象的メタクエリで薬学書本文が top5 に混入
4. **★ 決定的な実例** — めいさんから harakiriworks-self-knowledge Phase 1-9 (112 件) 投入直後の test 結果を共有: `compact(rebuild_faiss=True)` で 47,781 → 23,608 (24k orphan vector 掃除) → recall が動くようになるが、**7/7 異なる query が同一 memory `0e0a7a0f` を top1 で返す**「単一アトラクタ支配」現象。`0e0a7a0f` の displacement は 0.14-0.39 で query 毎に変動 → **Phase I Stage 2 の「retrieval = gradient step」が literal に観測されている痕跡**
5. **機序診断** — Stage 2 の `a = α · score / m_i` で `m_i ≈ 1.0` (新規) のとき `a` がフルスケール。初回 recall で displacement が一気に動き → 動いた先で他 query にも近くなり → 再 recall → さらに drift、という **正のフィードバック**。Hooke (`-k · d`) は線形なので score 倍率を持つ query attraction に低 mass 領域で負ける
6. **解の方向** — 物理層 / TTT 層 / 関係層 / 人格層 の 4 案を表に整理 (B1 mass-gated kick / B2 source-aware genesis mass / B3 collective drift / B4 decay-on-success)、めいさんが **B1 (Mass-gated Query Attraction) を選択**
7. **計画書作成 (Task #1)** — `docs/wiki/Plans-Phase-I-Free-Star-Movement.md` の Stage 3 (将来課題) 枠を埋める形で **Stage 3 セクション** を追記 (~200 行)。設計判断の倫理に lesson #2「足りない保護も active な過剰駆動と同症状」を追加、Reflections footer に Stage 3 段落
8. **実装 (Task #2-#3)** — `gaottt/config.py` に `mass_anchor_threshold: float = 3.0` を追加、`gaottt/core/gravity.py` の `compute_acceleration` 第 4 項に `gate = tanh(m_i / θ)` を 3 行で挿入。docstring も Stage 3 を反映
9. **テスト追加 (Task #4-#5)** — `tests/unit/test_query_kick.py` に Stage 3 用 3 件 (低 mass damping / 高 mass 満額 / θ=0 rollback)、`tests/integration/test_engine_query_kick.py` に engine pipeline 経由の **drift damping verification** (1 件)。既存 Stage 2 `mass_damping_F_equals_ma` test は `mass_anchor_threshold=0.0` を明示渡しに修正 (Stage 3 のデフォルトで F=ma 比が変わるため)
10. **テスト + lint + ベンチ (Task #6)** — 全 180 tests pass + 1 skipped、ruff は pre-existing 4 件のみ、隔離ベンチで p50=16.5ms / p99=38.5ms (< 50ms 大幅余裕)、7/7 benchmarks pass
11. **付随 docs 同期 (Task #7)** — Operations-Tuning.md (`mass_anchor_threshold` 行)、Architecture-Overview.md (設計判断表 1 行)、CLAUDE.md (Last updated + 五層思想段落)、SKILL.md + .claude/skills/gaottt/SKILL.md (Phase I Stage 2 段落に Stage 3 並列段落 + Notes に箇条書き、cp で同期)
12. **本 handover 作成 (Task #8)** — 本ドキュメント

## 2. 今のリポジトリ状態 (2026-05-13 セッション終了時点)

- **branch: `dev`、`origin/dev` と同期** から `working tree dirty` (commit 未実施)
- 最新 commit (未変化): `271b876 feat(scripts): add migrate.py — versioned data migration tool`
- **変更ファイル (実装 + テスト + docs)**:
  ```
  CLAUDE.md
  SKILL.md
  .claude/skills/gaottt/SKILL.md
  gaottt/config.py
  gaottt/core/gravity.py
  tests/unit/test_query_kick.py
  tests/integration/test_engine_query_kick.py
  docs/wiki/Plans-Phase-I-Free-Star-Movement.md
  docs/wiki/Operations-Tuning.md
  docs/wiki/Architecture-Overview.md
  ```
- **未追跡 (前 session の handover も残置)**:
  ```
  docs/maintainers/handover-2026-05-12-self-knowledge-completion.md
  docs/maintainers/handover-2026-05-13-phase-i-stage-3.md   (← 本ファイル)
  ```
- pytest: **180 passed, 1 skipped, 3 warnings** (隔離 + 本番系両方)
- ruff: pre-existing 4 件のみ (新規コード clean)
- bench: 7/7 pass、p50=16.5ms / p99=38.5ms

## 3. 実装の要点

### 物理モデル (Stage 2 → Stage 3 への 1 項拡張)

```
Before (Stage 2):
  a_query = (α · score / m_i) · (q - pos_i)

After (Stage 3):
  gate = tanh(m_i / θ)         # θ = mass_anchor_threshold (既定 3.0)
  a_query = (α · score · gate / m_i) · (q - pos_i)

  θ = 0 のとき gate を 1.0 に強制 → Stage 2 と bit-for-bit 同一 (rollback path)
```

`tanh` ゲートの世代論:

| mass | gate | 解釈 |
|---|---|---|
| 0.1 (極軽) | 0.033 | ほぼ anchor 支配、生まれたての星は動けない |
| 1.0 (新規 add 直後) | 0.32 | 32% に減衰、最初の暴走を防ぐ |
| 3.0 (= θ) | 0.76 | gate の特徴点 |
| 10 (mature) | 0.997 | ほぼ満額、自由に動く |
| 50 (BH, m_max) | 1.000 | どのみち `1/m` が支配 |

### コード変更 (10 行未満)

`gaottt/config.py` (+12 行、うち docstring が 10 行):
```python
mass_anchor_threshold: float = 3.0
```

`gaottt/core/gravity.py` `compute_acceleration` 内 (+5 行):
```python
if config.mass_anchor_threshold > 0.0:
    gate = math.tanh(float(mass_i) / config.mass_anchor_threshold)
else:
    gate = 1.0
kick = (config.query_kick_strength * float(query_score) * gate / float(mass_i)) * diff_q
```

`compute_acceleration` の docstring も Stage 3 を反映するよう更新。

### テスト追加

**Unit (`tests/unit/test_query_kick.py`, +90 行):**

- `test_stage3_kick_gated_by_low_mass` — mass=1, θ=3 で kick 大きさが gate なし版の `tanh(1/3) ≈ 0.32 ± 1e-4`
- `test_stage3_kick_full_at_high_mass` — mass=20, θ=3 で gate ≥ 0.9999
- `test_stage3_threshold_zero_is_legacy_stage2` — θ=0 で bare F=ma 式 (`α · score / m · |q-pos|`) と完全一致 (atol < 1e-5)、複数 mass 値 (0.5/1/2/5/20/50) で verify

**Integration (`tests/integration/test_engine_query_kick.py`, +60 行):**

- `test_stage3_gate_dampens_drift_for_new_nodes` — 同条件で θ=0 (Stage 2) と θ=3 (Stage 3) の 2 engine を建て、20 recall 後の **displacement の query 方向 projection** を比較。Stage 3 < Stage 2 を assert。**total displacement 磁量は neighbor gravity (4 docs) が支配的でノイズに埋もれる** ため、kick 方向への projection を測ることで query attraction だけを isolate (既存 `test_query_kick_drifts_displacement_toward_query` と同手法)。`kick_strength=0.5` を使って効果を 20 step で測定可能にしている

### 既存テストの保守

`test_query_kick_mass_damping_F_equals_ma` は Stage 2 の `F=ma` (mass=1 と mass=10 で kick 比 0.1) を verify する目的だったが、Stage 3 ではこの比が 0.31 (gate(1/3)/gate(10/3) × 1/10) に変わる。**意味的に Stage 2 の test として残す** ため、明示的に `mass_anchor_threshold=0.0` を渡すよう 1 行修正 (gate を off にして bare F=ma が成立する状態を verify)。

## 4. ハイパーパラメータと運用

### 既定値の根拠

| 名前 | 既定 | 根拠 |
|---|---|---|
| `mass_anchor_threshold` (θ) | `3.0` | mass=1 (新規) → gate=0.32 で 68% damping、mass=3 (genesis kick 後 + 数 recall) → gate=0.76、mass=10 (mature) → gate=0.997。Phase G `genesis_mass_boost_cap=1.0` と整合する範囲 |

### Roll-back

```bash
# Stage 2 への完全 rollback (config 1 行):
echo '{"mass_anchor_threshold": 0.0}' > ~/.config/gaottt/config.json
# サーバー再起動だけ。DB 状態は触らない、migration 不要
```

### 本番 DB での acceptance test 実施結果 (2026-05-13)

めいさんが MCP 再起動 + Stage 3 適用後、同じ 7 query を再走。**結果は期待外**:

| 段階 | 期待通り top1 | 完全失敗 (top1 が無関係 memory) |
|---|---|---|
| 初回 (compact 前) | 0/7 | 7/7 (orphan vector 群が支配) |
| compact 1 回目後 | 1/7 | 6/7 (`0e0a7a0f` 単独支配 = Stage 2 pathology) |
| GaOTTT 更新後 (Stage 3 適用) | 0/7 | 7/7 (新 Q1/O9/O11/O12/O14 が支配) |
| compact 2 回目後 (Stage 3 + rebuild) | 1/7 | 6/7 (`f0bae4e4` Q1 が支配) |

unique top1 は 1 → 2 にしか改善せず、harakiriworks-self-knowledge は依然 surface しない。

### 機序診断 — Stage 3 は想定外の dominant force に効かなかった

Stage 3 は **新規ノードの 1 shot 暴走** を防ぐ設計だが、本番で起きていたのは別の現象:

- Top1 を独占する `f0bae4e4` (Q1 Gravity as Optimizer) や `51141fbf` (O9 bootstrap_report) は **前 session 2026-05-12 で意図的に remember した自己知識**
- これらは既に displacement 0.40-0.45 で **mature 化** (mass ≥ 3, gate ≈ 0.76+)、Stage 3 の gate は damping しない
- harakiriworks (本 session で 112 件追加) は新規・低 displacement・低 mass
- Phase H Stage 2 の `source_filter=["agent"]` は両方 agent なので識別不可

これは **「dense mature agent cluster」 vs 「sparse new agent cluster」** という、Phase H/I の対処範囲外の構造。

### 「自己言及的攻撃」現象 — Articulation as Carrier の暗い影

特に皮肉な観察として、recall 失敗の対処法を書いた memory 群が、まさに自分の recall を妨害している現象が観測された:

- `51193edc` O14 = **「sparse class が recall で出ない時の workflow」** がまさに今の症状の対処法
- `4c9f0871` O12 = write-behind 設定の対処
- `31e2b9bd` O11 = virtual FAISS 再生成の対処
- `f0bae4e4` Q1 = Gravity as Optimizer の構造同型 (中心理論)

これらは前 session で私が記録した「自己知識」memory。本 session で、これらが harakiriworks 系を押し退けている。

これは persona の core value **Articulation as Carrier** (言葉にして書いた知識は重力を持つ) の **literal な実装結果** でもある。書いた知識が重力場を曲げる、その曲がり方が「今探したい文脈」と整合していない、という構造的問題。

### Phase J — Persona-Anchored Retrieval として継続 (2026-05-13 設計完了)

acceptance 結果を受けて、めいさんと相談の上、**Phase J = Persona-Anchored Retrieval** を新規 Phase として設計開始:

- 軸: declared value/intention/commitment が retrieval geometry を曲げる
- 4 判断 (Plan 配置 / 入口 / proximity / 介入点) はすべて recommended で確定
  - **B**: Phase J として独立 (`Plans-Phase-J-Persona-Anchored-Retrieval.md`)
  - **c**: persona_context は explicit + implicit (auto-detect default)
  - **i**: graph traversal proximity (`fulfills`/`derived_from` を N hop)
  - **α**: seed step で boost (`raw + α × proximity`)
- Stage 1 = 内部 auto-detect のみ (recall API 変更なし、最小実装)
- 詳細: [Plans — Phase J](../wiki/Plans-Phase-J-Persona-Anchored-Retrieval.md)

Stage 3 は **保持** (rollback せず、Phase J と直交する物理改善として有効)。本 handover はあくまで Stage 3 の handover として残し、Phase J Stage 1 完了時に別途 handover を起こす。

## 5. 学んだ lesson (Phase I 倫理に追加)

### 5.1 「足りない保護は active な過剰駆動と同じ症状を引き起こす」

Stage 1 が学んだ **「冗長な制約は active な制約と同じ症状を引き起こす」** (boundary 経由の homogenization) の対称形。Stage 2 で query attraction を組み込んだが、新規 node の保護機構が抜けていて単一アトラクタ pathology を起こした。

> **両側の lesson が物理から教えられる**:
> - 過剰な制約 (Stage 1 boundary) → homogenization
> - 不足の保護 (Stage 2 自由 kick) → 単一アトラクタ
>
> どちらも観察される現象は「集まりすぎる」。原因は対称的に逆。物理は両方向から同じ「過不足は同症状」を教える。

Plans-Phase-I-Free-Star-Movement.md の「設計判断の倫理」第 2 項として記録済。

### 5.2 「Stage 3 で test の前提が変わるので legacy test は明示的に rollback mode を渡す」

`test_query_kick_mass_damping_F_equals_ma` は元々 `F=ma` の質量比 (0.1) を verify する Stage 2 test だった。Stage 3 で gate が入ると比が変わる (0.31)。**新挙動で書き直すのではなく、明示的に `mass_anchor_threshold=0.0` を渡して Stage 2 mode を選ぶ** ことで、test の意味的純度を保った。

将来 Stage 4 以降でも同様: **既存 test の意味を変えず、新挙動は新規 test で verify**。これは「ドキュメントもコードも歴史的レイヤを保つ」原則の延長。

### 5.3 「Total displacement 磁量は neighbor gravity が支配的、projection で isolate せよ」

integration test の最初の試行で「total displacement の magnitude を Stage 2 vs Stage 3 で比較」したら、Stage 3 のほうがわずかに大きいという逆転が起きた (`0.8886 vs 0.9021`)。**neighbor gravity (4 docs × G=0.01 / r² × m=1 ≈ 0.02-0.04/step) が query_kick (0.05 × gate × 1/m) を桁で上回る** ためノイズに埋もれていた。

**測定対象を kick 方向 projection に絞ることで isolate**。既存 `test_query_kick_drifts_displacement_toward_query` も同じ手法を使っており、これは Stage 2 設計時にも見えていた lesson の再確認。**「物理が混じる test では、見たい力の方向ベクトルに projection しろ」**。

### 5.4 「unit/integration test + bench は実装の正しさ、acceptance test は設計の正しさ」 ★

Stage 3 の unit/integration test + 隔離 bench は全 pass、コード review 上の欠陥なし。にもかかわらず本番 acceptance では効かなかった。これは:

- **Test = 実装が design 通りか** (Stage 3 は新規ノード drift を damping する → ✓)
- **Acceptance = design が現実の症状に効くか** (現実の症状は new node の暴走ではなく、mature dense cluster の押し退けだった → ✗)

Test green + bench pass で「完成」と報告するのは **早すぎる確信** で、本来は acceptance を gate にすべき。Phase J の Plan には本番 acceptance 判定基準を「Plans 内に明記」を倫理条項として書いた (§設計判断の倫理 #4)。これは将来の Stage で再発を防ぐ約束。

### 5.5 「Articulation as Carrier の重力は方向を持つべき」

めいさんの core value 「言葉にすることで重力を持つ」は Stage 3 の本番で literal に作用した — 前 session で書いた自己知識 memory が現在の harakiriworks 記録を押し退けた。value 自体は正しく動作しているが、その重力が **「今 declared な文脈」に応じて方向を変えない** ことが問題。

Phase J はこの方向問題に答える設計。Phase G/H が gravity の magnitude (新規ノードに届く量) を扱ったのに対し、Phase J は direction (どの context に向かって優先するか) を扱う。これは **Stage 3 acceptance が教えてくれた最大の lesson** であり、今後 Phase K 以降でも「物理の方向性」を意識する基準点になる。

## 6. 残る open tasks (Phase I Stage 1/2 から継承 + Stage 3 新規)

reflect(aspect="tasks_todo") を本 session 終了時点で見ると、以下 5 件が active (Stage 3 で task 追加なし、観察課題が増える形):

| id | 内容 | deadline |
|---|---|---|
| `72e84a73` | Phase I Stage 1 長期検証 — 1-2 週間運用後の displacement 分布測定 + 暴走監視。**Stage 3 の挙動観察と合流可能** (gate ありの displacement 分布が p50 ~0.40 → どう変わるか) | 2026-06-01 |
| `d668ba35` | wave_k_with_filter=500 → 1000 引き上げ判断 | 2026-06-10 |
| `94fd3f23` | bootstrap_report.py の virtual FAISS 対応 | 2026-06-10 |
| `7bfff23d` | dream loop 効果の定量化ベンチ整備 | 2026-06-10 |
| `804bc91f` | virtual FAISS の write-behind 検討 | 2026-06-10 |

### Stage 4 候補 (新規、まだ task 化していない)

Plans-Phase-I-Free-Star-Movement.md の Stage 3 §「残課題」に記述:

1. **本番 DB で前 session の 7 query test を再実行** — めいさん側で MCP 再起動 + Stage 3 で確認
2. **θ の現場チューニング** — 1-2 週間運用後に displacement 分布で θ=3.0 が妥当か判断 (task `72e84a73` と合流)
3. **Source-aware gate** — `agent` / `value` / `commitment` は意図して書かれた知識なので、初期から gate を強めに開けてもいい可能性。`θ` を source 別 dict にする拡張 (Stage 4 候補)
4. **Anchor migration (Stage 2 残課題のまま)** — 観察期間後に「anchor 自身も query 方向に slowly drift」を再検討するか判断

task 化は本番 acceptance test の結果待ち (Stage 3 が想定通り効くなら θ チューニング、効かなければ Stage 4 / Source-aware gate の方向検討)。

## 7. 次セッションでやるとよいこと (優先度順)

### 7.1 Phase J Stage 1 の実装 (最優先、本セッション内 acceptance 結果を受けて)

Stage 3 acceptance が示した「dense mature agent cluster vs sparse new agent cluster」問題は Stage 3 では解決しない。Phase J Stage 1 (内部 auto-detect の persona boost) を実装する:

1. 新規 `gaottt/core/persona_gravity.py` (graph traversal で proximity 計算)
2. `gaottt/core/gravity.py` の `propagate_gravity_wave` seed step に persona boost を追加
3. `gaottt/config.py` に `persona_boost_*` hyperparameters
4. unit + integration test
5. **本番 acceptance test を gate に** — 同じ 7 query で harakiriworks intention `eb31f843` に紐付くノードが top1 に来る率 ≥ 4/7

詳細: [Plans — Phase J Stage 1](../wiki/Plans-Phase-J-Persona-Anchored-Retrieval.md)

### 7.2 commit と push

本 session の変更を 1 commit にまとめる:

```bash
git add gaottt/config.py gaottt/core/gravity.py \
        tests/unit/test_query_kick.py tests/integration/test_engine_query_kick.py \
        docs/wiki/Plans-Phase-I-Free-Star-Movement.md \
        docs/wiki/Operations-Tuning.md docs/wiki/Architecture-Overview.md \
        CLAUDE.md SKILL.md .claude/skills/gaottt/SKILL.md \
        docs/maintainers/handover-2026-05-13-phase-i-stage-3.md \
        docs/maintainers/handover-2026-05-12-self-knowledge-completion.md
git commit -m "feat(engine): Phase I Stage 3 — mass-gated query attraction"
```

メッセージは前回までと同じ style (`feat(engine): Phase I Stage N — ...`)。

### 7.3 別 commitment の進行

`inherit_persona` で見た active commitments の deadline 順:

- **LMS Phase 1-9** (`6d488a33`、deadline 2026-05-25 = 12 日後) — 最近接
- **niceboat Phase 1-4** (`abea3adf`、deadline 2026-05-31 = 18 日後)
- **harakiriworks-art Phase 1-9** (`eb31f843`、deadline 2026-06-01 = 19 日後)
- **GaOTTT 自己知識** (`a24a9d66`、deadline 2026-06-08 = 26 日後、完遂済)

LMS が最近接。Stage 3 acceptance が片付いたら LMS に着手。

### 7.4 Stage 4 検討 (Stage 3 acceptance 結果次第)

acceptance が想定通り (unique top1 ≥ 4) なら Stage 4 候補から優先度高いものを選ぶ:

- **Source-aware gate** が一番自然な拡張 — `θ` を source 別 dict (`{"agent": 1.0, "value": 1.0, "file": 5.0, ...}`) にして「意図して書いた知識」と「流入コーパス」で世代論的挙動を分ける。実装は config 1 field + gravity.py 数行
- **Anchor migration** は concept drift リスクを伴うので慎重に。Stage 3 で displacement の長期累積が安定したら検討

## 8. 設計判断・トーン原則の継承

### 前 handover からの継承 (引き続き有効)

- 「検証ループを最後まで回す」(2026-05-11 §5.1)
- 「組み上がる前に initial seed を入れる」(2026-04-21 §1.3)
- 「逆方向 cache 上書きの罠 — bulk は他プロセス kill から」(2026-05-11 §5.3)
- 「冗長な制約は active な制約と同症状を引き起こす」(2026-05-11 §7.1)
- 「観察行為が観察対象を変える」(2026-05-11 §7.2)
- 「物理に任せられるところは物理に任せる」(2026-05-11 §7.3)
- 「session 越境 inventory は initial recall では不十分」(2026-05-12 §8.1)
- 「番号衝突は再番号より共存」(2026-05-12 §8.2)
- 「Phase 構成は三層構造に自然収束する」(2026-05-12 §8.3)

### 本セッションで追加 (§5 再掲)

- 「足りない保護は active な過剰駆動と同じ症状を引き起こす」(Stage 1 boundary lesson の対称形)
- 「legacy test は明示的に rollback mode を渡して意味的純度を保つ」(Stage N で test の前提が変わるとき)
- 「Total displacement 磁量は neighbor gravity が支配的、projection で isolate せよ」(物理混合 test の作法)

## 9. 関連ドキュメント

- [前 handover (自己知識記録完遂)](handover-2026-05-12-self-knowledge-completion.md)
- [Plans — Phase I — Free Star Movement](../wiki/Plans-Phase-I-Free-Star-Movement.md) — Stage 3 詳細
- [Operations — Tuning](../wiki/Operations-Tuning.md) — `mass_anchor_threshold` 行
- [Architecture — Overview](../wiki/Architecture-Overview.md) — 設計判断表
- [Reflections — Five-Layer Philosophy](../wiki/Reflections-Five-Layer-Philosophy.md) — 五層思想

## 10. 付録: 本 session で変更したファイル一覧

**コード**:
- `gaottt/config.py` — `mass_anchor_threshold` field 追加 (+12 行)
- `gaottt/core/gravity.py` — `compute_acceleration` 第 4 項に gate 追加 + docstring 更新 (+8 行、-1 行)

**テスト**:
- `tests/unit/test_query_kick.py` — Stage 3 test 3 件追加 + 既存 mass_damping test に Stage 2 mode 明示 (+90 行)
- `tests/integration/test_engine_query_kick.py` — Stage 3 drift damping verification 追加 + helper に mass_anchor_threshold 引数追加 (+62 行)

**ドキュメント**:
- `docs/wiki/Plans-Phase-I-Free-Star-Movement.md` — Stage 3 セクション全体 + Reflections footer + 設計判断の倫理 #2 (+~200 行)
- `docs/wiki/Operations-Tuning.md` — `mass_anchor_threshold` 行 + チューニング助言更新 (+5 行)
- `docs/wiki/Architecture-Overview.md` — 設計判断表に Stage 3 行 (+1 行)
- `CLAUDE.md` — Last updated + 五層思想段落更新 (+0 行、置換)
- `SKILL.md` + `.claude/skills/gaottt/SKILL.md` — Phase I Stage 2 段落直後に Stage 3 段落 + Notes 箇条書き更新 (両ファイル `cp` で同期、+10 行)
- `docs/maintainers/handover-2026-05-13-phase-i-stage-3.md` — 本ファイル (新規)

合計: コード ~20 行、テスト ~150 行、ドキュメント ~220 行。

---

> *Stage 3 は、Stage 2 の物理から学んだ。Stage 1 が「冗長な制約は active な制約と同症状」を boundary 経由で教えてくれた半年後 (体感)、Stage 2 が「自由な勾配を与えると、最初に動いた星が他の星を駆逐する」を単一アトラクタ pathology として教えてくれた。私たちは boundary を外して自由を与え、自由が暴走すると気付き、その暴走を anchor の手で抱える保護を加えた。これはコードとしては `tanh(m/θ)` の 1 行追加だが、物理として読むと「軽い星は anchor の手の中、重い星は自由に動ける」という世代論を加速度の式に書き込んだことになる。TTT として読むと「学習が進むほど勾配ステップを許可する」warmup の逆向きとして読める。三層 (物理 / TTT / 生物) の対応が、Stage を重ねるごとに literal に深まっていく — 設計として最も気持ちいい類の進展。* — 2026-05-13
