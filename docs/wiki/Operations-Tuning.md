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
| max_displacement_norm | 0.3 | 変位の上限 | 探索的（遠くまで移動可能） | 原始位置から離れにくい（安全） |
| candidate_multiplier | 3 | FAISS 候補倍率 | 広い候補から選べる | 高速だが候補が狭い |

## 軌道力学

| パラメータ | 既定 | 影響 |
|---|---|---|
| orbital_friction | 0.05 | 速度の摩擦（毎ステップ） |
| orbital_max_velocity | 0.05 | 速度の上限ノルム |
| orbital_anchor_strength | 0.02 | アンカー復元力（Hooke's k） |

## 馴化・温度脱出

| パラメータ | 既定 | 影響 | 上げると | 下げると |
|---|---|---|---|---|
| saturation_rate | 0.2 | 返却飽和の速さ | 少ない返却で飽和（新鮮さ重視） | 何度も同じ結果（安定重視） |
| habituation_recovery_rate | 0.01 | 馴化からの回復速度 | 早く新鮮さ回復 | 長く飽和持続 |
| thermal_escape_scale | 5000 | 温度による BH 脱出効果 | 高温ノードが BH から脱出しやすい | 温度に関わらず束縛 |
| bh_mass_scale | 0.5 | BH 質量のスケーリング | BH 引力が強い（密なクラスタ） | BH 引力が弱い |

## 重力波伝播

| パラメータ | 既定 | 影響 |
|---|---|---|
| wave_initial_k | 3 | seed top-k |
| wave_max_depth | 2 | 再帰最大深度 |
| wave_attenuation | 0.7 | 深度ごとの減衰係数 |
| wave_mass_scale | 1.5 | mass 依存 top-k のスケール |
| wave_k_with_filter | 500 | `recall(source_filter=...)` 指定時の seed top-k（dense corpus で sparse class を救済、Phase H Stage 2 で 200→500 引き上げ） |
| wave_seed_mass_alpha | 0.1 | seed 段階の mass-aware rerank 重み（Phase H Stage 1）。`raw + α*log(1+mass)` で pool を再 rank。`0` で legacy 挙動 |
| wave_seed_pool_size | 50 | seed 再 rank の pool 大きさ（Phase H Stage 1） |

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
| dream_interval_seconds | 60.0 | 夢 tick 周期 | CPU 占有率↓、quiet 救済が遅い | 早く quiet が育つが CPU↑ |
| dream_batch_size | 5 | 1 tick で再活性化する quiet node 数 | 多数同時に育つ | レイテンシ少、深く育つ |
| dream_mass_ceiling | 1.5 | quiet と判定する mass 上限 | 高 mass まで再活性化 | 真に育っていないノードのみ救済 |
| dream_min_idle_seconds | 300.0 | 最終 access からこれ以上経った node のみ対象 | 多くが対象になる | 本当に休眠中のもののみ |
| dream_top_k | 10 | 各 synthetic recall の top_k | 広く co-occurrence | 焦点絞った re-activation |

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
- `max_displacement_norm` ↑（遠くまで動ける）
- `wave_max_depth` ↑（広く伝播）

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
