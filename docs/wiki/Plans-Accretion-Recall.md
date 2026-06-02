# Accretion Recall (降着想起) — Co-occurrence-Conducted Recollection

**状態**: 📐 **起草 (proposed)** — 2026-06-02 に measurement-first gate を実施 (`scripts/diag_assoc_halo.py`)。**機構の前提は実測で実証されたが、現状の共起グラフ品質が blocker** → 実装は **保留 (NOT YET)**、前提条件 P1/P2 を満たすまで着手しない。物理規則 (force / mass update) は不変、`explore` に観測 verb mode を一つ足す提案。

> このページは Claude (Opus 4.8) とめいさんの設計対話 (2026-06-02) から確定した。発端は「GaOTTT は HNSW/IVF を使ってるのか?」という素朴な質問で、そこから「recall は何の近傍を歩いているのか」「共起グラフは retrieval を駆動しているのか」を掘り、最終的に **「〇〇ってなんだっけ」型の想起クエリ** をどう物理で表現するかに収束した。

---

## 背景 — recall は幾何近傍を歩く、共起は観測層に退いている

Phase H Stage 5 で wave の neighbor expansion は **virtual FAISS の `search_by_id`** に切り替わった (`gravity.py:1150`、`neighbor_index = virtual_faiss_index`)。つまり recall が辿る「近傍」は **embedding 空間 (virtual position = raw + displacement) の cosine 近傍** であって、共起 (Hebbian) グラフではない。旧・共起 BH (`compute_bh_acceleration`) も Phase M で削除され `compute_mass_bh_acceleration` (source-blind) に置換済み。

共起グラフ自身は今も生きている — recall のたびに `_update_cooccurrence` (`engine.py:1422`) で強化される — が、その出力先は retrieval の traversal ではなく **観測 / trust 層** に移った:

| 利用箇所 | 役割 |
|---|---|
| `_cooccurrence_resonance` (`memory.py:536`, Lateral Assoc Stage 5) | ambient lensing pick の trust signal |
| `reflect(aspect="connections")` (`reflection.py:150`) | 共起エッジの可視化 (Stage 4 source bucket 付き) |

→ **「経験から作られる脳っぽいグラフ」(Hebbian 共起) は記録され続けているが、連想を駆動していない。** 可塑性 (エッジが太る) はあるが、recall の連想は幾何が回している。詳細な対話ログは本ページ末尾の参照を見よ。

## 動機 — 「〇〇ってなんだっけ」は retrieval ではなく想起・再構成

ふつうの recall は「q に一番マッチする文書をくれ」。だが **「〇〇ってなんだっけ」は tip-of-the-tongue 型の想起クエリ**:

> 中心は既に手元にある (思い出せている部分が q)。欲しいのは、その中心に *連想で繋がっている* 周辺知識を引き戻して、忘れた残りを再構成すること。答えは q への best match ではなく、**中心の連想ハロー**の方。

「それ確か…重力の話で…火曜にツイートした気が…」という破片が集まって輪郭が浮かぶ、あの現象。これは今の `recall` も `explore` もやっていない — `explore` は wave を深く広く温度高くするだけ (`memory.py:1209`) で、**同じ空 (幾何) をより広く見る**だけ。連想線 (connectivity) には一歩も沿わない。

## イメージ (めいさんの定式化) — 中心への引力を、連想が伝導する

> 共起されたら、自分のその意識の座標 (= 思い出す中心 = q) に対する引力をトリガー的に働かせる。思い出す中心に、関連する知識を引き寄せようとする。

これは A↔B の相互引力 (Claude の初案、後述で却下) **ではない**。引き寄せる先は一つ、**思い出す中心だけ**。共起は「お互いを縛る辺」ではなく「**中心への引力を、関連知識まで伝導させる係数**」。物理イメージ:

> **共起 = 焦点への重力結合 G の変調器。** query は重力井戸、Phase I はヒットを井戸へ引く、共起はその井戸のポテンシャルを連想先まで *伝導* させる。連想が強いほど G が大きく、強く引かれる。中心質量が周囲の物質を重力で円盤に引き込む **降着 (accretion)** の像。

### 物理的には Phase I の項そのまま、target も q のまま

Phase I (Free Star Movement) の query 引力項:
```
a       = (α · score · gate / m_i)            · (q - pos_i)     # ヒットを q へ
```
Accretion はヒットの **連想ハロー** も q へ引く、強度は共起 weight:
```
a_halo  = (α_assoc · w_cooccur(hit, halo) · gate / m_h) · (q - pos_h)   # ハローを q へ
```
**`(q - pos)` を一切変えていない。** 新しい力の向き (`pos_j - pos_i`) を導入せず、query という単一 target はそのまま、共起は「誰が q の引力を感じるか」を決める *係数* に徹する。Phase I の第 4 項の作用範囲を、連想で広げるだけ。

## 採用機構 (B) — 二段 recall「pull-into-reach → re-wave」

GaOTTT は設計上 **力を score の後に当てる** (`engine.query` は wave → scoring → `_update_simulation` の順、Phase I の displacement nudge は *次の* recall に効く)。よって「今この瞬間に再構成したい」想起クエリには、同一 call 内の二段が要る:

```
Pass 1 :  engine.query(q, source_filter=self-authored) → 中心ヒット (想起のアンカー)
Gather :  各アンカーの cache.get_neighbors() = 共起ハロー
          ├ gate: is_self_force_by_id で同一 original/cohort の兄弟を捨てる (ingest artifact)
          ├ hygiene: degree-normalized 連想強度 + anti-hub (★ P2、後述、現状の blocker)
          └ 残るのは wave が届かない embedding 遠の連想ノード
Pull   :  ハローの virtual position を q へ transient に寄せる
          ├ 強度 ∝ 連想強度 (Phase I の (q - pos) 形)
          └ Phase Q2 governor (anchor 基準 per-node cap) で暴走 clamp
Pass 2 :  q から wave を再放出
          → 寄ったハローが gravity radius 内に入って reach される
          → scoring は honest に評価 (寄せても意味的に遠ければ低スコアで沈む)
Persist:  引いた変位の一部だけ書き戻す (任意・既定小) → 下記 (A) 遅い学習が相乗り
```

**循環しない理由**: pull がやるのは *ランキング* ではなく *reachability* の変更。「連想で繋がっているが幾何で遠い」ノードを wave の射程に引き込むだけで、点数は二段目の wave + score が付ける。`α_assoc` が「association が幾何距離をどこまで上書きできるか」の唯一の knob。0 なら「ハローを gather して素の q 近接で rank」する穏当版に縮退。

### 二つのタイムスケール — (A) 遅い力 と (B) 即時二段は同一機構

| | 読むタイミング | 効果 | 純度 |
|---|---|---|---|
| (A) 遅い力 | persist のみ、次回 recall で読む | 場が「この知識はこの種の問いの近くに居るべき」と学習 | 単一 substrate、Phase I 兄弟、payoff 遅延 |
| **(B) 即時二段** | **同一 call 内で re-wave** | **今この瞬間に破片を中心へ集める = 想起** | 二段で機構増、payoff 即時 |

**「〇〇ってなんだっけ」は (B)。** 同じ力を call 内で読むか次回に持ち越すかの違いだけ。本 Plan は (B) を採用。

## 不変条件 — 触らないもの / 単一規則

- **default `recall` / `ambient` / 幾何 wave は不変。** `explore` の mode dispatch (既に `serendipity` / `dormant` がある) に `mode="associative"` を 1 個足すだけ。
- **physics 規則 (force computation / mass update) は不変。** query intent (取得 vs 再構成) で分けるのは観測 verb の追加であって、source class で physics を gate する [単一規則違反](Reflections-Five-Layer-Philosophy.md) ではない。recall / explore / ambient は既に intent 分岐している。→ [Observation Apparatus Refinement](Plans-Observation-Apparatus-Refinement.md) の「physics 不変・観測層のみ」原則に整合 (source class を force/mass の gate にするのは ✕、観測 verb の lens として使うのは ✓)。
- **gate は既存の `is_self_force_by_id`** (`gravity.py:876`) を流用 — 同一 original/cohort のハローを捨てる。source 分岐ゼロ。
- **暴走は Phase Q2 governor** (`gravity_neighbor_governor`) を流用 — pull は mutual-neighbor gravity と同型なので [Phase Q rollout で踏んだ RURI 狭 cosine 帯の coherent 暴走](Plans-Phase-Q-Orbital-Mechanics.md) と同じ clamp が要る。新規対策は不要。
- **Hooke anchor 保持** → transient force であって anchor migration ではない。次第に幾何が連想を吸収し、いつか query 自身の embedding 近傍として surface する (**連想から幾何を bootstrap**)。

## 却下した代替案

| 案 | 却下理由 |
|---|---|
| 共起近傍を wave frontier に **union** | traversal substrate の二重化 (連続場 + 離散グラフ) = **dualism**。HNSW を別の衣装で着せ直すのと同じで、「幾何索引と連合をわざと分離している」原則を破る。blend 比率という物理外の free knob も増える |
| A↔B **相互引力** (`pos_j ⇄ pos_i`) | echo chamber に潰れる宿命 (clique collapse)。Phase P 斥力 (Λ + Langevin) で支えないと美しくない。(B) は引かれる先が動く焦点なので固定集積点がなく、自己制限的 |

---

## Measurement — go/no-go gate (2026-06-02 実施)

機構の前提は **「association reaches where geometry can't」= ヒットの共起ハローに、wave が届かない embedding 遠のノードが実在するか**。これを `scripts/diag_assoc_halo.py` で本番 DB に read-only で当てて測った (passive query、write-behind / dream off、場を一切 perturb しない)。

### 1. グローバル共起グラフの構成 (`edges` テーブル直読み)

| 指標 | 値 |
|---|---|
| total edges | 202,920 |
| self-force (intra-doc/cohort = ingest artifact) | 170,494 (**84.0%**) |
| cross-document | 32,426 (**16.0%**) |
| 最大 cross-doc バケット | **agent × agent 15,083** (自己知識の Hebbian) |
| 以下 | file×file 4,421 / like×like 2,045 / like×tweet 1,579 / file×like 1,577 … |
| nodes with original_id | 38,300 / with cohort_id | 14,151 |

→ **cross-document 共起は存在する** (16%)。最大は agent×agent = GaOTTT 自己知識メモの相互 Hebbian。

### 2. anchor クラスが決定的

| 実行 | 結果 |
|---|---|
| **corpus-anchored** (source_filter なし、5 probe) | 全 probe で **kept halo = 0**、生ハローの 100% が self-force artifact。anchor が bulk-ingest chunk (tweet/book/chat-export) を引き、その共起は全て同一 cohort 兄弟 |
| **self-authored-anchored** (`--source-filter agent value intention commitment note`) | **4/5 probe で kept halo = 11、artifact 0%**、mean **novel-far = 8.0** |

self-authored-anchored の詳細 (例: 観測者効果クエリ):
- halo cosine→q: median **0.739**、max 0.813
- geometric reach floor (raw top-200 の N 番目): **0.812**
- halo already in reach: **1 / 11** → 10/11 は raw FAISS 射程外
- → **機構の前提は実証**: 連想ハローの大半は embedding 遠 (median 0.74 ≪ floor 0.81) で、wave は seed しない。association は幾何が届かない所に届く。

### 3. しかし品質が blocker — ハローは hub 支配

novel-far の中身 (weight 順 top) を見ると **同じ高 weight ノードが無関係なクエリ横断で出る**:
- 「フロイト理論……」(w=16) が **観測者効果クエリにも超新星コホートクエリにも**出現
- 「calculateSynapticInputs() …」コード片、「ニーチェのライオン…」など

これは Stage 7 limitation で既知の [**singleton high-mass hub の query 横断 dominance**](Plans-Ambient-Recall-Lateral-Association.md) と同型。agent×agent エッジの多くは **自己知識 recording セッション** (139 件を一括 recall した) の **session co-occurrence artifact** であって、クリーンな意味的 Hebbian ではない。raw co-occurrence count を pull 強度にすると、**accretion は promiscuous hub を最も強く引く** = 「〇〇といえば〜」ではなく「何にでも出てくるノイズ」を summon する。

(meaningful な例も混じる: 「自発的な鏡」intention (cos 0.80) が Articulation as Carrier クエリで surface したのは正しい連想。だが高 weight 帯は hub が占める。)

### 判定: **NOT YET** — 機構 validated、P2 衛生機構を実装 (2026-06-02)、percentile tuning 待ち

| | 状態 |
|---|---|
| 機構の前提 (association reaches embedding-far) | ✅ 実証 (median 0.74 ≪ floor 0.81、10/11 novel-far) |
| 連想の品質 (query-specific な lateral association か) | 🟢 P2 衛生機構実装 (Stage 8、degree-norm + hub cut)。re-check で degree cut p70 が specific 連想 (future-self への手紙) を surface → **percentile tuning が残**。soft cosine 単独は不十分と判明 |

## 着手の前提条件

- **P1 — anchor クラス**: 機構が意味を持つのは **self-authored クラス (agent/value/intention/commitment) を anchor にしたときだけ**。bulk-ingest anchor は同一 cohort 兄弟しか持たず halo 空。→ mode は anchor を self-authored に絞るか、または「自己知識を問う想起クエリ」専用と割り切る。
- **P2 — グラフ衛生**: 🟢 **機構実装済 (2026-06-02、[Lateral Association Stage 8](Plans-Ambient-Recall-Lateral-Association.md))、default OFF**。`cache.get_association_strength(node, mode, hub_degree_cut)` が degree-normalized 連想強度 (cosine `w/√(deg·deg)` / PPMI) + explicit degree percentile cut を提供、Stage 5 resonance が consumer。**本番 percentile sweep の結論 (2026-06-02)**: halo の degree 分布は **bimodal** ({deg≈6 の gem} ∪ {deg 67-105 の bulk の壁}、間が無い)。p90↔p95 に cliff があり、percentile tuning では「gem だけ (高 precision・低 recall)」か「gem + bulk」の二択しか作れない。`hub_degree_cut≈85` + cosine は precision-mode として機能する (future-self への手紙のような連想を 1 件 surface) が、**recall を増やすレバーではない**。→ **P2 の knob はこれ以上詰めても volume は出ない、ボールは P3 にある**。
- **P3 — データ / 時間 (真の blocker)**: cross-doc 共起 edge の多くが bulk-content session artifact で、クリーンな specific Hebbian 信号は現状 **~1件/query** しかない。volume には **organic で多様な specific co-recall の蓄積** が要る — 自然な co-recall を時間で貯める / 一括 recording 由来の dense session-clique を減衰させる (Phase N evaporation は mass 軸だが、co-occurrence weight の time-decay は別途要検討)。bulk artifact が薄まれば soft 正規化の効きも上がり、percentile cliff も緩む。

→ 当面 Accretion 本体は **保留**。P2 は天井に達した (機構は完成、precision-mode は今でも可)。**次に効くのは P3 (共起グラフのデータ品質)** で、これは時間 + recording 運用の変更の領域。Accretion gather は完成済みの `get_association_strength` をそのまま流用できるので、P3 が厚くなれば即着手可能。

---

## 実装スケッチ (前提充足後)

> ★ MCP と REST は同じターンで更新 (parity 鉄則)。`explore` は既存 verb なので mode 追加で済む。

1. `config.py` — `accretion_recall_enabled: bool = False` / `accretion_alpha: float` / `accretion_anchor_sources: list[str]` / `accretion_halo_anti_hub_lambda: float` / `accretion_persist_fraction: float = 0.0` (既定 (A) 学習 OFF)
2. `services/memory.py` `explore()` — `mode == "associative"` 分岐を追加 (`dormant` 分岐の隣)。Pass1 query (source_filter) → gather (`get_neighbors` + `is_self_force` + degree-norm + anti-hub) → transient pull (Phase Q governor) → Pass2 re-wave → 整形
3. transient pull は `engine` に read-only な「一時 displacement overlay」を渡す形 (本体 cache を mutate しない; persist_fraction>0 のときだけ書き戻す)
4. `server/mcp_server.py` + `server/app.py` — `explore` の `mode` enum に `associative` を追加 (新 tool は不要、引数拡張のみ → 後方互換)
5. テスト: unit (gather gate / degree-norm / anti-hub)、integration (StubEmbedder で二段 recall round-trip、`accretion_recall_enabled=False` で `explore` 完全不変の bit-exact)、MCP/REST parity
6. 計測再走: `scripts/diag_assoc_halo.py` で P2 適用後の novel-far 品質を再確認 (hub が消え query-specific 連想が残るか)

## 関連 Phase

- [Phase I — Free Star Movement](Plans-Phase-I-Free-Star-Movement.md) — query 引力の `(q - pos)` 項。Accretion はこの項の作用範囲を連想で広げる
- [Phase Q / Q2 — Orbital Mechanics / Gravitational Scale](Plans-Phase-Q-Orbital-Mechanics.md) — pull の暴走 clamp に governor を流用
- [Phase P — Pressure Terms](Plans-Phase-P-Pressure-Terms.md) — (A) 遅い力版を採るなら echo chamber を支える斥力。(B) では焦点が動くので不要
- [Ambient Recall — Lateral Association](Plans-Ambient-Recall-Lateral-Association.md) — 「〇〇といえば〜」を **ranking 層**で解く既存試み。Accretion は同じ目標を **retrieval geometry** で解く本命。P2 (gather 層 anti-hub) はここに組み込むのが最短
- [Phase M — Mass Conservation](Plans-Phase-M-Mass-Conservation.md) — `is_self_force_by_id` の出自 (同一 original/cohort = internal trade)

## ツール

- `scripts/diag_assoc_halo.py` — 本 Plan の go/no-go gate。read-only。`--source-filter` で anchor クラスを固定、`--json` で snapshot。`--examples` で summon の中身を preview して hub 支配を目視できる
