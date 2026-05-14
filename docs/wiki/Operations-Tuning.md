# Operations — Tuning Hyperparameters

`gaottt/config.py` の `GERConfig` を編集してサーバー再起動で反映。

すべてのハイパーパラメータの一次ソース: [`gaottt/config.py`](../../gaottt/config.py)

---

## スコアリング・質量

| パラメータ | 既定 | 影響 | 上げると | 下げると |
|---|---|---|---|---|
| alpha | 0.05 | mass boost の重み | 頻出ドキュメントを強く優先 | 類似度ベースに近づく |
| delta | 0.01 | 時間減衰の速さ | 古いアクセスが早く忘れられる | 長期間アクセスが維持 |
| gamma | 0.5 | temperature の感度 | ノイズが大きくなり探索的に | 安定的な検索結果 |
| eta | 0.05 | mass 増加速度 | 少ないクエリで重要度↑ | ゆっくり蓄積 |
| edge_threshold | 5 | 共起エッジ形成の閾値 | 強い共起のみエッジ化 | 弱い共起でもエッジ化 |
| top_k | 10 | 既定返却件数 | 多くの結果を返す | 上位のみに絞る |

## 重力変位

| パラメータ | 既定 | 影響 | 上げると | 下げると |
|---|---|---|---|---|
| gravity_G | 0.01 | 万有引力定数 | 急速に引き寄せ合う（創発的） | 穏やかな変位（安定） |
| gravity_eta | 0.005 | 変位の学習率 | 1 回のクエリでの変位↑ | 段階的に変位 |
| displacement_decay | 0.995 | 変位の定期減衰 | 変位が長く維持 | 早く元に戻る |
| max_displacement_norm | 1e6 | 変位の上限 (Phase I で実質 ∞ 化) | n/a (cap が事実上 off) | 小さい値で疑似的なハードキャップに戻せる（緊急ノブ） |
| candidate_multiplier | 3 | FAISS 候補倍率 | 広い候補から選べる | 高速だが候補が狭い |

## 軌道力学

| パラメータ | 既定 | 影響 |
|---|---|---|
| orbital_friction | 0.05 | 速度の摩擦（毎ステップ） |
| orbital_max_velocity | 0.05 | 速度の上限ノルム |
| orbital_anchor_strength | 0.02 | アンカー復元力（Hooke's k） |

## Query 引力（Phase I — Stage 2 + Stage 3）

`compute_acceleration` の 4 番目の項。recall 時に retrieved nodes へ query 方向の小さな引力を加える。`F = α · score · gate · (q - pos)`, `a = F / m_i` で **mass damping** が自動で効く (BH 化 node はほぼ動かない)。**Stage 3** では `gate = tanh(m_i / θ)` で新規 (低 mass) ノードが anchor (Hooke) に守られる — 単一アトラクタ pathology の防止策。**transient force** — Hooke が raw embedding を anchor として引き続き保持するので anchor migration ではない。詳細: [Plans — Phase I](Plans-Phase-I-Free-Star-Movement.md) §Stage 2-3。

| パラメータ | 既定 | 影響 | 上げると | 下げると |
|---|---|---|---|---|
| query_kick_strength | 0.01 | 結合定数 α (G に類似) | recall ごとの drift ↑（短期で query 方向に集まる） | drift が緩慢、長期累積でしか効かない。`0` で完全 no-op (roll-back) |
| query_kick_enabled | `True` | グローバル off スイッチ | n/a | `False` で 4 項目を完全 skip (config 即時 off) |
| mass_anchor_threshold (θ) | 3.0 | Stage 3 gate の特徴点 (`tanh(1)≈0.76` が ここ) | 攻撃的 (`θ=1` → 新規 m=1 で gate=0.76、ほぼ満額)。新規ノードの drift 即時化 | 保守的 (`θ=10` → 新規 m=1 で gate=0.10、ほぼ動かない)。`0` で Stage 2 へ rollback (gate=1.0 強制) |

> **チューニング助言**: per-step acceleration は `orbital_max_velocity=0.05` で cap されるので、`α / m × score × gate × \|q-pos\|` が ~0.05 を超えると効きが頭打ち。質量 1 の新規 node + score=1 + |q-pos|=1.4 (unit-norm 直交) + θ=3 で gate=0.32 → α=0.11 が cap 境界 (Stage 2 単体の 0.035 から余裕拡大)。`α=0.01` (既定) は安全側、`mass_anchor_threshold=3.0` で **新規ノードは ~32%、mature ノード (mass≥10) はほぼ満額** という世代論的挙動。pathology が再発したら θ を上げる、新規ノードの surface が遅すぎたら θ を下げる。

## 馴化・温度脱出

| パラメータ | 既定 | 影響 | 上げると | 下げると |
|---|---|---|---|---|
| saturation_rate | 0.2 | 返却飽和の速さ | 少ない返却で飽和（新鮮さ重視） | 何度も同じ結果（安定重視） |
| habituation_recovery_rate | 0.01 | 馴化からの回復速度 | 早く新鮮さ回復 | 長く飽和持続 |
| thermal_escape_scale | 5000 | （Phase M で deprecated）共起 BH の温度脱出効果。`compute_acceleration` から呼び出し削除済、`scripts/visualize_3d.py` 互換のため定義は残存 |
| bh_mass_scale | 0.5 | （Phase M で deprecated）共起 BH 質量スケーリング。同上 |

## Mass Conservation + mass-based BH (Phase M Stage 1)

`engine._update_simulation` の mass update が **「外部 (`original_id` / `cohort_id` 一致しない parent) からの引力寄与のみで増える」** 規則に切り替わった。`compute_acceleration` 第 3 項の BH 引力も共起 cluster centroid 方式から **「mass しきい値を超えた neighbor からの直接引力」** に置き換え。詳細: [Plans — Phase M](Plans-Phase-M-Mass-Conservation.md)。

| パラメータ | 既定 | 影響 |
|---|---|---|
| mass_conservation_enabled | `True` | self-force filter の on/off。`False` で legacy「内輪取引も mass を生む」挙動に rollback |
| mass_bh_enabled | `True` | mass-based BH attractor の on/off。`False` で第 3 項を完全に切る (neighbor gravity + anchor + query attraction のみ) |
| mass_bh_theta (θ) | 5.0 | BH attractor 発動しきい値 — `bh_factor(m) = tanh((m-θ)/σ)`、`m ≤ θ-2σ` でクランプ 0 |
| mass_bh_sigma (σ) | 1.5 | tanh 遷移幅 — 小さいほど θ 付近で急峻な on/off、大きいほどなだらか |

> **本番ロールアウト手順**: 旧規則下で蓄積した chunk 内輪取引 inflation を一度ゼロにしてから新規則で観察する。(1) 他 MCP / REST プロセス停止 → (2) DB backup → (3) `.venv/bin/python scripts/reset_masses.py --apply` → (4) サーバー再起動 → (5) 1-2 週の自然蓄積を観測 → (6) `p99 mass` を θ に、`(p99.9 - p99)/2` を σ にして Stage 2 で確定。`reset_masses` は **MCP に非露出** (LLM 用途なし)、REST `POST /admin/reset_masses` のみ。

> **チューニング助言**: 新規 `remember` の original_id は `node_id` 自身 (自己一致なので自己フィルタの影響 0)。file ingest (`scripts/load_files.py`) は `original_id = file_path` で chunk 群を共通グループ化。Phase K supernova batch は `cohort_id = uuid4().hex[:12]` を共有 — `cohort_id` が **同じ** node 同士の force は mass update に寄与しない (Articulation as Carrier の literal な物理実装)。`mass_bh_theta` を下げ過ぎると低 mass node も attractor 化 → homogenization リスク。上げ過ぎると 1-2 週観測しても BH が発生しない (期待 1.7-5% の節点が θ 超え)。Stage 1 暫定 θ=5.0 は旧規則下の p99=26.5 から「新規則下は inflation が消えるので θ は大幅に下がる」前提の placeholder。

## 重力波伝播

| パラメータ | 既定 | 影響 |
|---|---|---|
| wave_initial_k | 3 | seed top-k |
| wave_max_depth | 3 | 再帰最大深度 (Phase M follow-up 2026-05-13 で 2→3。1 recall で touch される displacement 範囲が ~20-50 → ~60-150 nodes に拡大、per-recall latency +20-30%。`wave_attenuation=0.5` で第 3 段以降は force<0.001 で自動 filter) |
| wave_attenuation | 0.7 | 深度ごとの減衰係数 |
| wave_mass_scale | 1.5 | mass 依存 top-k のスケール |
| wave_k_with_filter | 1000 | `recall(source_filter=...)` 指定時の seed top-k（dense corpus で sparse class を救済、Phase H Stage 2 で 200→500、2026-05-12 本番 23k DB 検証で 500→1000 引き上げ） |
| wave_seed_mass_alpha | **0.0** | seed 段階の mass-aware rerank 重み（Phase H Stage 1）。`raw + α*log(1+mass)` で pool を再 rank。**2026-05-14 に 0.1 → 0.02 → 0.0 と段階的に下げて最終 disabled**(下記注を参照)。`> 0` に戻すと Phase L Stage 1 の RRF score scale (~0.03 max) と Phase H Stage 1 の mass term (cosine scale ~0.9 想定) が干渉し、mass の重い無関係 chunk が semantic 距離を上書きする structural bug が発生 |
| wave_seed_pool_size | 50 | seed 再 rank の pool 大きさ（Phase H Stage 1） |
| wave_dynamic_k_enabled | `True` | top-N 密度応答型の seed 拡大（Phase H Stage 3）。`False` で固定 initial_k |
| wave_density_window | 10 | density 評価で見る top-N の N |
| wave_density_threshold | 0.95 | tail/top 比率の閾値。これ未満で「sparse」と判定して seed 拡大 |
| wave_initial_k_max | 50 | sparse 判定時の effective_k 上限（Phase H Stage 3） |

> **⚠️ `wave_seed_mass_alpha` の scale 不整合バグ (2026-05-14 発見、`0.0` に固定で回避)**
>
> Phase L Stage 1 (RRF fusion) と Phase H Stage 1 (`raw + α × log(1+mass)`) は **score scale が異なる**:
> - `raw` に来る値 — RRF mode: ~0.018–0.033 / cosine mode (legacy): ~0.5–1.0
> - `α × log(1+mass)` — 例: α=0.02 × log(23) = **0.062** ← RRF max の 2 倍!
>
> 結果、RRF が semantic にランクした top を **mass の重い無関係 chunk が完全に上書き**する。例: 「あの航空機事故はこうして起きた」を recall すると、cosine 0.92 で raw FAISS top の book chunks (mass 1.4) が、cosine 0.79 で **mass 22 の京都大学入試 / 会社四季報 chunk** に seed step で押し出される。
>
> **修正**: `wave_seed_mass_alpha = 0.0` で seed boost を完全 disable。RRF fusion が既に raw cosine + virtual + BM25 を scale-invariant に組み合わせているので、seed step での mass 介入は不要。Phase H Stage 1 の意図(heavy node lift)を RRF mode で正しく実現する **RRF-scale aware mass boost** は Phase N で再設計予定([Plans — Roadmap](Plans-Roadmap.md))。
>
> 詳細・診断手順は [Operations — Troubleshooting](Operations-Troubleshooting.md) の「ファイルで登録した文書が recall に出てこない」節。

## Persona-anchored seed boost (Phase J Stage 1)

`propagate_gravity_wave` の seed step で `α_persona × proximity` を加算。declared value / intention / commitment から `fulfills`/`derived_from`/`completed` で graph 連結するノードを優先入場させる。詳細: [Plans — Phase J](Plans-Phase-J-Persona-Anchored-Retrieval.md)。

| パラメータ | 既定 | 影響 | 上げると | 下げると |
|---|---|---|---|---|
| persona_boost_enabled | `True` | グローバル off スイッチ | n/a | `False` で完全 skip、collect/proximity 計算も走らない |
| persona_boost_alpha (α_persona) | 0.5 | 結合定数 (`wave_seed_mass_alpha=0.1` の 5×) | persona-tied ノードが seed pool で勝ちやすい (intention 直下の task/agent が surface しやすい) | 弱まる、`0.0` で計算は走るが boost なし |
| persona_max_hop | 2 | graph traversal の hop 上限 | 3 hop で間接的関連も拾える (false positive ↑) | 1 hop で fulfills 直下のみ (狭い) |
| persona_hop_decay | 0.5 | hop あたり減衰率 | 0.7 で 2 hop=0.49 (遠隔まで強い) | 0.3 で 2 hop=0.09 (急減衰) |
| persona_active_ttl_seconds | 14 日 | active 判定の TTL (Stage 2 で commitment に適用) | n/a | n/a — Stage 1 では未使用 |

> **チューニング助言**: `persona_boost_alpha=0.5` は acceptance test (本番 23k DB) で「persona-tied ノードが seed pool に届く」を目的に置いた初期値。届かなければ `1.0` まで上げる、効きすぎ (persona ノードが全 query で top1 を独占) なら `0.2` まで下げる。`persona_max_hop=2` は Phase D の典型チェーン (intention → task → outcome) を拾える深さ、3 以上にすると間接的な関連 (誰かが derive した知識の派生) も混入。`persona_boost_enabled=False` で Stage 0 (Phase J 前) 挙動に完全 rollback。

## Hybrid retrieval — BM25 union seed (Phase L Stage 1)

Seed pool は raw FAISS (semantic) ∪ virtual FAISS (semantic+history) ∪ BM25 (lexical) の 3-way union。異なる metric tensor の重ね合わせで、embedder の hidden ranking が拾えない surface-form 一致 (例: 「Eleventy Pipeline」 → `.eleventy.js`) を BM25 が直接 catch する。RRF fusion (Reciprocal Rank Fusion) が default で scale 不変・query 間安定。詳細: [Plans — Phase L](Plans-Phase-L-Hybrid-Retrieval.md)。

| パラメータ | 既定 | 役割 |
|---|---|---|
| hybrid_bm25_enabled | `True` | Phase L Stage 1 全体の on/off。`False` で Phase H Stage 4 (raw+virtual) と同等挙動に rollback |
| bm25_seed_k | `50` | BM25 が seed pool に提供する top-N 数。raw/virtual の `wave_seed_pool_size` / `wave_k_with_filter` と同オーダー |
| bm25_k1 | `1.5` | Robertson-Sparck-Jones の term-saturation 制御。文献標準 1.2-2.0 の中央付近 |
| bm25_b | `0.75` | length-normalization。文献標準 0.75 が標準 corpus 向き、固定長 doc 多めなら 0.5、長文ばかりなら 0.9 |
| bm25_score_mode | `"rrf"` | `"rrf"` で Reciprocal Rank Fusion (Cormack 2009 標準、scale 不変)、`"weighted_sum"` で legacy 2-way max-merge + BM25 normalize blend |
| rrf_k | `60` | RRF の rank-fusion 定数。Cormack 2009 標準 |
| bm25_score_alpha | `0.5` | `"weighted_sum"` mode 専用、BM25 normalized share。`"rrf"` mode では無視 |
| bm25_tokenizer | `"trigram"` | char 3-gram (依存ゼロ、日英混在に頑健)。`"sudachi"` は `uv pip install -e ".[bm25-sudachi]"` 後に選択可 |

> **チューニング助言**: 本番 acceptance で「Surface ✅ / Semantic 整合 ⚠️」が分離した query (Eleventy Pipeline 等) を起点に、BM25 寄与を確認。RRF default で大半は十分だが、lexical match が overshoot して semantic 整合が落ちる場合は `"weighted_sum"` + `bm25_score_alpha=0.3` で BM25 影響を弱める。tokenizer は trigram で「重力」「Eleventy」両方扱えるが、固有名詞の同形異義語が頻出する corpus なら Sudachi extra に切り替えて形態素解析する。Stage 1 では disk persistence なし — `compact()` か再起動で SQLite content から rebuild される (24k docs で数秒)。複数 MCP プロセス共存環境は raw FAISS と同じ可視性問題があり、片方プロセスでの `remember` が他方プロセスの BM25 index に届くのは次回 startup or compact 後。

## Stellar supernova cohort (Phase K Stage 1)

`index_documents` の batch を 1 超新星イベントとして扱い、batch 内 N 件 (N≥`supernova_min_cohort_size`) に **相互 co-occurrence edge** + **centroid からの outward velocity** を付与。新規 cohort が「互いに重力を持たない散発的塵」状態から「同イベント残骸群」になる。Phase G genesis kick (個別重力) の隣で適用。詳細: [Plans — Phase K](Plans-Phase-K-Stellar-Supernova-Cohort.md)。

| パラメータ | 既定 | 影響 | 上げると | 下げると |
|---|---|---|---|---|
| supernova_enabled | `True` | グローバル off スイッチ | n/a | `False` で完全 skip、Phase G 単独に rollback |
| supernova_min_cohort_size | 2 | 発火する最小 batch サイズ | 3+ で小規模 batch が cohort 化しない | 1 にすると単独 remember で edge を張ろうとする (相手いない) |
| supernova_initial_weight | 1.0 | 相互 edge の初期 weight | 2.0+ で強い cohort (seed pool の mass-aware boost が `log(1+w)` で強く効く) | 0.5 で弱い cohort、0.0 で edge 形成 skip |
| supernova_velocity_alpha | 0.03 | 爆発の運動量 α | 0.05 で `orbital_max_velocity` cap に到達 (爆発が一気に膨張) | 0.01 で穏やかな爆発、0.0 で velocity 形成 skip |

> **チューニング助言**: Phase K は **将来 session の新規 cohort** に効くが、**既存 orphan ノードは遡及できない** (cohort 形成は index 時のみ)。既存 harakiriworks-self-knowledge 112 件のような遡及対象には別途 ritual script で edge + velocity を後付けする必要。`supernova_initial_weight=1.0` は Phase B `edge_threshold=5` と独立 (Phase K は event-driven、Phase B は recall 累積 driven)。一括投入では cohort が大きくなりすぎる場合は `index_documents` の batch を分割するのが運用上の手段 (例: 100 件投入を 4×25 件に分けて 4 つの cohort にする)。
| virtual_faiss_enabled | `True` | virtual_pos でビルドした第二 FAISS を並走（Phase H Stage 4）。priming 後の displacement を seed step に反映する |
| virtual_faiss_save_interval_seconds | 60.0 | virtual FAISS の write-behind 周期。`cache.virtual_faiss_dirty` が立つたびに次の tick で full rebuild + disk save。`0` で無効化（compact / shutdown 時のみ rebuild、Phase J Stage 1 以前のレガシー挙動）。**長期常駐 MCP サーバーでは非ゼロ必須** — そうしないと Phase I/J の query attraction 累積が次の起動まで他プロセスの seed pool に反映されない。23k node 規模で rebuild ~数百 ms、60s 間隔なら 1% 未満の負荷 |
| wave_neighbor_use_virtual | `True` | Phase H Stage 5。wave propagation の per-frontier `search_by_id` を virtual FAISS で行う（「星同士の引力」原則に沿った形）。raw FAISS は静的な天球で displacement を見ないため、`False` でレガシー（raw のみ）に戻せる。virtual FAISS が空 / None / 無効のときは自動 fallback。p50 への影響は誤差範囲（同サイズの index search） |

## 誕生時の重力 kick（Phase G — Stage 1）

新規 `remember` 時に既存重力場から 1 step の kick を適用、新規ノードを「裸」(mass=1, displacement=0, velocity=0) で gravity 場に置かないための補正。詳細: [Plans — Phase G — Memory Genesis](Plans-Phase-G-Memory-Genesis.md)。

| パラメータ | 既定 | 影響 | 上げると | 下げると |
|---|---|---|---|---|
| genesis_kick_enabled | `True` | Phase G G.1 の全体 ON/OFF | — | レガシー挙動（裸投入） |
| genesis_kick_neighbor_k | 5 | kick 計算で使う高 mass 近傍数 | 多くの近傍からの引力で軌道が安定 | ノイズ少、近傍偏在に弱い |
| genesis_kick_pool_size | 50 | FAISS top-N pool（mass 降順で K に絞る前段） | 真の重力中心を見つけやすい | 計算速い |
| genesis_mass_boost_alpha | 0.5 | `|acc|` → mass boost 変換係数 | 新規が surface しやすい | homogenization 抑制 |

## 夢による継続的軌道捕獲（Phase G — Stage 2）

quiet node を idle 時間に synthetic recall で再活性化し、co-occurrence エッジ + gravity 場を時間軸で build up するバックグラウンドループ。`_is_synthetic=True` で `return_count` は増やさない（saturation 非発火）。

| パラメータ | 既定 | 影響 | 上げると | 下げると |
|---|---|---|---|---|
| dream_enabled | `True` | Phase G G.2 の全体 ON/OFF | — | 夢ループ無し（Stage 1 のみ） |
| dream_interval_seconds | 30.0 | 夢 tick 周期 (Phase M follow-up 2026-05-13 で 60→10 にしたが foreground starvation が判明し 10→30 に再調整、`_dream_loop` 内で `await asyncio.sleep(0)` 挿入で per-tick yield も追加) | CPU 占有率↓、quiet 救済が遅い | 早く quiet が育つが CPU↑ |
| dream_batch_size | 10 | 1 tick で再活性化する quiet node 数 (50 → 10 へダウン、batch 中の連続 CPU 占有 2.5s → 0.5s に短縮して foreground recall が timeout しなくなった) | 多数同時に育つ | レイテンシ少、深く育つ |
| dream_mass_ceiling | 1.5 | quiet と判定する mass 上限 | 高 mass まで再活性化 | 真に育っていないノードのみ救済 |
| dream_min_idle_seconds | 300.0 | 最終 access からこれ以上経った node のみ対象 | 多くが対象になる | 本当に休眠中のもののみ |
| dream_top_k | 10 | 各 synthetic recall の top_k | 広く co-occurrence | 焦点絞った re-activation |

> **チューニング助言**: dream loop のチューニング結果を実測したいときは `scripts/bench_dream_loop.py` を使う。本番 DB を汚さず `/tmp/gaottt-dream-bench-*` で隔離実行し、N 件 add 後の baseline と M dream tick 後の差分 (edge 重み / mass 分布 / probe top-K stability) を計測。`--docs 200 --ticks 30 --batch 10` で 30 秒程度。Phase K supernova が edge **count** を index 時に saturate させるので、dream の signal は edge **weight** に出ることに注意。

## TTL 短期記憶（F4 + Phase D）

| パラメータ | 既定 | 用途 |
|---|---|---|
| default_hypothesis_ttl_seconds | 7 日 | hypothesis ソース |
| default_task_ttl_seconds | 30 日 | task ソース |
| default_commitment_ttl_seconds | 14 日 | commitment ソース |

`remember(ttl_seconds=...)` / `commit(deadline_seconds=...)` で個別上書き可能。

## auto_remember（F1）

| パラメータ | 既定 | 影響 |
|---|---|---|
| auto_remember_default_max | 5 | 候補数の既定 |
| auto_remember_min_chars | 12 | 候補の最短文字数 |
| auto_remember_max_chars | 400 | 候補の最長文字数 |

## 情動・確信度（F7）

| パラメータ | 既定 | 影響 | 上げると | 下げると |
|---|---|---|---|---|
| emotion_alpha | 0.04 | \|emotion\| の boost 重み | 情動的記憶を強く優先 | 影響を抑える |
| certainty_alpha | 0.02 | certainty の boost 重み | 高確信度を強く優先 | 影響を抑える |
| certainty_half_life_seconds | 30 日 | 確信度の半減期 | 確信度が長く保たれる | 早く減衰、`revalidate` 推奨頻度↑ |

## バックグラウンド prefetch（F6）

| パラメータ | 既定 | 影響 |
|---|---|---|
| prefetch_cache_size | 64 | LRU エントリ上限 |
| prefetch_ttl_seconds | 90 | キャッシュ寿命 |
| prefetch_max_concurrent | 4 | 並列 prefetch 数 |

## Write-behind

| パラメータ | 既定 | 影響 |
|---|---|---|
| flush_interval_seconds | 5.0 | キャッシュ → DB の flush 間隔 |
| flush_threshold | 100 | dirty 件数による即時 flush 閾値 |
| faiss_save_interval_seconds | 5.0 | in-memory FAISS → `.faiss` ファイル保存間隔。`0` で無効化（shutdown 時のみ save、レガシー挙動）。**MCP サーバーのような長期常駐プロセスでは必ず非ゼロ**にしないと他プロセスから新規 remember が見えなくなる |

## Embedding

| パラメータ | 既定 | 用途 |
|---|---|---|
| model_name | `cl-nagoya/ruri-v3-310m` | Embedding モデル |
| embedding_dim | 768 | 次元数（モデル変更時は要連動） |
| batch_size | 32 | バッチエンコード時 |

---

## チューニングの典型シナリオ

### 「もっと探索的にしたい」

- `gamma` ↑（temperature が大きくなる）
- `gravity_G` ↑（引力が強い）
- `wave_max_depth` ↑（広く伝播）

> Note: Phase I 以降、`max_displacement_norm` は事実上 ∞ (`1e6`)。displacement の届く距離は Hooke (`orbital_anchor_strength`) + `displacement_decay` + `orbital_max_velocity` で物理的に均衡する。「もっと遠くまで」したい時は `orbital_anchor_strength` ↓ または `gravity_G` ↑。

### 「もっと安定的にしたい」

- `saturation_rate` ↓（馴化を緩める）
- `gravity_G` ↓
- `thermal_escape_scale` ↓（温度脱出を抑える）

### 「タスクが消えやすすぎる」

- `default_task_ttl_seconds` を大きく（例 90 日）
- `default_commitment_ttl_seconds` を大きく（例 30 日）

### 「prefetch のヒット率を上げたい」

- `prefetch_ttl_seconds` ↑（90 → 300）
- `prefetch_cache_size` ↑

### 「`recall(source_filter=...)` で agent / value / commitment が surface しない」

DB が大きくなる（~10k 超）と、デフォルト `wave_initial_k=3` の seed 段階で dense cluster（Twitter / 書籍 / コーパス系）が独占し、sparse class（`agent` / `value` / `intention` / `commitment` / `compaction`）が seed に入らないまま post-filter で空集合になる。対処:

- `wave_k_with_filter` ↑（200 → 500/1000）— seed pool を広げて sparse class を含める。レイテンシは線形に増えるので `scripts/run_benchmark_isolated.sh` で p50 < 50ms を確認
- それでも不足なら呼び出し側で `recall(query, source_filter=[...], wave_k=N)` を明示
- target が極端に sparse（< 50 件）な場合、`tag` ベースの `reflect` で発掘する方が確実

→ より広い文脈: [Operations — Troubleshooting](Operations-Troubleshooting.md)
