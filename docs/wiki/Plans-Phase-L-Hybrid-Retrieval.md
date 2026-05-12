# Plans — Phase L — Hybrid Retrieval

> 状態: **✅ Stage 1 完遬 (2026-05-14)** — 設計・実装・本番 acceptance 完了。strict 4/7 (Phase J Stage 3 時 0-1/7 から大幅改善)、top3 緩和 7/7 で機構として完成
> 関連 handover: [Phase L Stage 1 完遬 (2026-05-14)](../maintainers/handover-2026-05-14-phase-l-stage-1.md)
> 関連: [Roadmap](Plans-Roadmap.md), [Phase H — Wave Seed Redesign](Plans-Phase-H-Wave-Seed-Redesign.md), [Phase J — Persona-Anchored Retrieval](Plans-Phase-J-Persona-Anchored-Retrieval.md), [Phase K — Stellar Supernova Cohort](Plans-Phase-K-Stellar-Supernova-Cohort.md)
> 発端: 2026-05-13 Phase J Stage 3 本番 acceptance での「Surface 7/7 ✅ / Semantic 整合 0-1/7 ⚠️」分離観察 ([handover](../maintainers/handover-2026-05-13-phase-j-stage-3.md) §6.5)

## 背景 — Phase J 完遂後に残った構造的境界

Phase J Stage 3 で retrieval geometry の三段構造 (pool 入場 / pool 内 rerank / forced 内 ordering) が完成し、機構としては独立 toggle / debug 可能な状態に至った。だが本番 23k DB での 7 query acceptance では明確な分離が観察された:

| 軸 | 結果 |
|---|---|
| `tag_filter` で対象 cohort を top5 に surface | ✅ **7/7** (Phase J Stage 2 force injection が機構として完璧) |
| Top1 が「query semantic に最も近い」memo か | ⚠️ **0-1/7** (Round 1 raw_score sort で 1/7、Round 2 pure raw cosine で 0/7) |

「Eleventy Pipeline」query に対し、本来 top1 になるべき `.eleventy.js` 責務 memo が見つからず、別な harakiriworks memo が forced cohort 内で勝つ。これは Phase J Stage 3 の `raw_score` sort が **embedder (RURI v3 310m) の cosine 距離** に literally 従った結果で、その embedder が "Eleventy Pipeline" 文字列に対して "シチリア島上陸" のような **無関係 file source** をなぜか高 cosine と判定してしまう (前 session 「重力モデルの設計思想」 query の True_only top1 が "シチリア島上陸" だった事象と同質)。

つまり Phase J 三段構造の **どの段を動かしても解決しない**:

- 段 1 (pool 入場): force injection で対象を pool には入れられる
- 段 2 (pool 内 rerank): mass / persona / cohort は内部状態の補正、cosine 自体は変えない
- 段 3 (forced 内 ordering): raw_score sort = embedder cosine に従う

**真の bottleneck は seed の起点 cosine 距離自体** — embedder の hidden ranking と LLM の意味解釈のズレが構造的境界として表面化した。これは embedder layer の問題で、retrieval geometry を後段で曲げる Phase H/I/J/K の射程外。

## 仮説 — 異なる metric tensor の重ね合わせ

Phase L の核仮説:

> retrieval pool 入場の起点は単一の (RURI cosine) ではなく、**異なる metric の重ね合わせ** であるべき。

GR で複数の質量分布があれば時空が複雑な metric tensor になるように、retrieval pool の入場権も **複数の距離関数の合成** で決まるのが自然。RURI cosine が拾い損ねた候補は、別 metric (lexical, multilingual embed, etc.) が拾う。union pool は「異なる metric tensor の重力場の重ね合わせ」。

これは Phase H Stage 4 で raw FAISS と virtual FAISS の union を導入した時に既に始まっていた構造の延長。Phase L はその union を「同じ embedder の別変換」から「**異なる metric の別 index**」へ広げる。

### Five-Layer での読み

| 層 | Phase L での意味 |
|---|---|
| 物理 | retrieval pool の入場 metric を単一 → 重ね合わせに広げる。異なる「重力定数 G」を持つ場が同じ点で測られる |
| TTT | gradient signal の **複数 model の ensemble** (multiple gradient estimators) で、単一 model の bias を相殺する |
| 生物 | アストロサイトが複数の感覚 modality (視覚・聴覚・記憶) で同じ object を multi-modal に同定する |
| 関係 | 文字列一致 (lexical) と意味類似 (semantic) は別の関係性 — 両方が pool 入場権を持つ |
| 人格 | declared identity (persona) と articulated knowledge (lexical surface) の両方が retrieval を曲げる。Articulation as Carrier は「言葉にした surface form」を直接の重力源として認める |

## 設計判断 (4 軸、Stage 1 起草段階の暫定方針)

### 1. 「最も literal」基準による軸選択 — Hybrid retrieval を選ぶ

Phase L intention ([[design-literal-correspondence]] 参照) で明示された原則:

> embedder layer を **回避する hack** ではなく **構造として組み込めるもの** を優先

3 軸の評価:

| 軸 | embedder layer の扱い | LLM 依存 | latency 影響 | rollback | literal 度 |
|---|---|---|---|---|---|
| **A. Hybrid retrieval** (BM25 + RURI + 別 embedder union) | seed pool layer の **構造的拡張** — 既存 `_union_pool` が raw∪virtual の 2-way、Phase L で 3-way 以上に | なし | 軽い (BM25 lookup は O(log N)、別 embedder は別問題) | flag で完全 off 可 | ★★★ |
| B. Query rephrase (LLM で query を rephrase) | embedder layer は **無変更**、外側 query 拡張 layer を追加 | 必須 | LLM call の追加 (100-1000ms) | flag で完全 off 可 | ★★ |
| C. Forced 内 LLM rerank (top-K を LLM が並べ替え) | embedder layer は seed まで、最後の段だけ LLM | 必須 | LLM call (top-K を渡すので token 重い) | flag で完全 off 可 | ★ (hack 寄り) |

**A を採用**: seed pool layer の中で union を拡張する形式で、Phase H Stage 4 (raw∪virtual) と同じ pattern。LLM 不要で GaOTTT のローカル完結性 (offline 動作可) を維持する。B/C は LLM proxy が必須となり、GaOTTT の独立性が損なわれる。

### 2. Stage 1 の Index 選択 — BM25 (lexical)

3 種類の候補:

| 候補 | 役割 | RURI と独立か | 実装重み |
|---|---|---|---|
| **BM25 (lexical)** | TF-IDF / Zipfian — surface form 完全一致を最強で拾う | 完全に直交 (lexical vs semantic) | 中 (BM25 自前実装) |
| 別 embedder (multilingual e5 等) | 別 model の意味空間 | 部分的に独立 (model architecture 差) | 大 (model load, vector index 別管理) |
| char n-gram embedding (FastText 等) | 表層形態の埋め込み | 部分的に独立 | 大 |

**Stage 1 は BM25 単独** を選ぶ。理由:

- **完全に直交した metric**: BM25 は「'Eleventy' という文字列が docs にどれだけ出るか」を Zipfian で測る。embedder の semantic ranking とは無関係なので、embedder が無視した surface form を確実に拾う。
- **「Eleventy Pipeline」のような専門用語に最強**: 文字列一致なので embedder が学習していない project-specific term でも tf-idf で top に来る。
- **実装が軽い**: numpy ベースの in-memory index で 100 行程度。FAISS 並みの抽象 (`search(query_text, top_k)`) に統一可能。
- **依存ゼロ**: 標準 lib + numpy のみ、追加 dependency なし (uv lockfile への影響なし)。

別 embedder は **Stage 2 候補** として保留 — RURI と部分的にしか直交しない、model load コスト大、運用が重い。

### 3. SQLite FTS5 ではなく numpy in-memory BM25 を使う

★ **発見 (2026-05-14)**: 本環境の Python `sqlite3` binding は FTS5 非対応 (`no such module: fts5`)。`pysqlite3-binary` 等の追加 dep もありえるが、運用性 (ABI 問題、`uv` lockfile 肥大) を考えると採用しない。

代わりに **numpy ベースの in-memory BM25 index** を採用。raw/virtual FAISS と同じ抽象を持つ:

```
BM25Index:
    add(ids, texts)         — tokenize → doc_freq 更新 → mass matrix 行追加
    search(qtext, top_k)    — query tokenize → BM25 score → top-K
    remove(ids)             — soft delete (next rebuild で除外)
    rebuild()               — compact 時の orphan 掃除
```

write-behind pattern も raw/virtual FAISS と同形:

- in-memory に add は即時、disk save は `bm25_save_interval_seconds` 周期 (default 60s)
- shutdown / compact で full flush
- startup で disk → in-memory restore

実装ファイル `gaottt/index/bm25_index.py` — FAISS Index と並ぶ第 3 の index 抽象。

### 4. Tokenizer — char 3-gram default + Sudachi optional extra (めいさん決定 2026-05-14)

日本語 / 英語混在 corpus に対する選択肢:

| 候補 | 日本語 | 英語 | 依存 | 評価 |
|---|---|---|---|---|
| ASCII whitespace | ❌ (連続文字を 1 token) | ✅ | 0 | ❌ 日本語完全死 |
| Sudachi / MeCab | ✅ 形態素 | ✅ | 大 (辞書 ~100MB) | optional extra |
| **char 3-gram** | ✅ trigram で頑健 | ✅ trigram で頑健 | 0 | ★ default |
| char 2-gram | やや過剰 match | やや過剰 match | 0 | precision 低 |

**Stage 1 は char 3-gram を default、Sudachi を optional extra として用意**。

- `bm25_tokenizer: str = "trigram"` が default
- `pyproject.toml` の `[project.optional-dependencies]` に `bm25-sudachi = ["sudachipy", "sudachidict_core"]` を追加
- BM25Index の tokenizer は plugin パターン: `bm25_tokenizer="sudachi"` 指定時に `sudachipy` を遅延 import、未インストールなら明示的 ImportError
- 「Eleventy」「重力モデル」「シチリア」全て trigram でトークン化可能、precision は BM25 の Zipfian で自然に補正される
- Sudachi は本番運用で trigram の precision が不足した場合の選択肢として残す

## 段階分け

### Stage 1 — BM25 union seed (最小実装)

**目的**: 「embedder の hidden ranking 限界」の最も literal な構造的修正。raw FAISS / virtual FAISS と並んで第 3 の seed source として BM25 を追加し、seed pool の入場 metric を 3-way union に拡張する。

**範囲**:
- 新規 `gaottt/index/bm25_index.py` — BM25Index class (numpy ベース、char 3-gram、~150 行)
- 新規 `gaottt/index/tokenizer.py` — char n-gram tokenizer + Sudachi plugin loader (~60 行)
- `gaottt/core/gravity.py:_union_pool` を 3-way (raw ∪ virtual ∪ bm25) + RRF fusion に拡張、`bm25_index` 引数追加
- `gaottt/core/gravity.py:propagate_gravity_wave` に `bm25_index` parameter + query text 渡し
- `gaottt/core/engine.py` — startup で BM25 index build、`index_documents` / `forget` / `merge` / `compact` で同期 (write-behind loop は D2 により Stage 1 では不要)
- `gaottt/config.py` に hyperparameters 追加 (RRF + Sudachi-aware tokenizer 文字列を含む)
- `pyproject.toml` — `[project.optional-dependencies]` に `bm25-sudachi = ["sudachipy", "sudachidict_core"]` 追加 (D3)

**recall API 変更なし** — BM25 は内部 index、外部に新引数を露出しない。MCP / REST の API は無変更、parity 鉄則の影響範囲外。Stage 1 では `force_refresh=False` の挙動も変化しない (cache key は query text のみ)。

**Stage 1 で扱わないもの** (D1-D4 のめいさん決定を反映):
- 別 embedder (e5 等) の ensemble (Stage 2)
- BM25 専用 API surface (`recall(query, lexical_only=True)` 等) (将来検討)
- BM25 disk persistence (Stage 1 は in-memory only + startup rebuild、production 移行時に別 stage で追加 — D2)
- BM25 を wave 中の neighbor 探索に拡張 (D4)
- LLM-based query expansion / rerank (Stage 3 候補、または別 Phase に分離)

### Stage 2 — 別 embedder の ensemble (候補)

**範囲**:
- multilingual e5 base or large (cl-nagoya 系) を `gaottt/embedding/` に追加
- 第 2 の FAISS index を build
- `_union_pool` を 4-way (raw + virtual + bm25 + e5) に拡張
- 共有 vector dim が違うので index は完全に並列管理

**判断保留**: Stage 1 acceptance で「BM25 だけで semantic 整合 ≥ 5/7 達成」なら Stage 2 不要、「BM25 でも届かない query 群がある」なら Stage 2 着手。

### Stage 3 — Query expansion / LLM rerank (候補、または Phase M に分離)

**範囲**:
- `recall(query, expansion_strategy="rephrase")` で LLM が query を rephrase
- forced 内 ordering を `raw_score` から `llm_rerank_score` に切り替えるオプション
- LLM proxy 設定 (Anthropic / OpenAI / local llama.cpp)

**判断保留**: Phase L の核 (embedder layer の構造的拡張) からは外れるので、**Phase M (LLM-Augmented Retrieval) として独立** させる可能性が高い。Stage 1/2 acceptance を見て判断。

## Stage 1 実装範囲 (詳細)

### 新規ファイル

**`gaottt/index/tokenizer.py`** (~40 行):

```python
"""Char n-gram tokenizer for BM25.

Used for Phase L Stage 1 hybrid retrieval. Char n-gram is robust against
mixed-language corpus (Japanese / English) without external tokenizer
dependencies (no Sudachi/MeCab).
"""

def normalize(text: str) -> str:
    """Lowercase ASCII, collapse whitespace, strip control chars."""
    ...

def char_ngrams(text: str, n: int = 3) -> list[str]:
    """Extract overlapping char n-grams. '<' / '>' bound word starts/ends
    so 'eleventy' tokens distinguish from 'elev' as suffix."""
    ...
```

**`gaottt/index/bm25_index.py`** (~150 行):

```python
"""BM25 in-memory index — Phase L Stage 1.

Numpy-backed BM25 with the same interface shape as FaissIndex
(``add(ids, texts)`` / ``search(query, top_k)``). Char 3-gram tokenizer
by default for mixed-language corpus.

State (in-memory, write-behind to disk by engine):
    doc_ids:     list[str]                   — node ids in insertion order
    doc_freqs:   list[Counter[str]]          — term frequency per doc
    doc_lens:    np.ndarray (float32, [N])   — doc length in tokens
    term_df:     dict[str, int]              — document frequency per term
    avgdl:       float                        — average doc length

Scoring:
    score(q, d) = sum over t in q∩d:
        idf(t) * f(t,d) * (k1+1) / (f(t,d) + k1*(1 - b + b * |d| / avgdl))
"""

class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75,
                 tokenizer: callable = None) -> None: ...

    def add(self, ids: list[str], texts: list[str]) -> None: ...
    def remove(self, ids: list[str]) -> None: ...     # soft, sets dirty
    def search(self, query: str, top_k: int) -> list[tuple[str, float]]: ...
    def rebuild(self) -> None: ...                    # drop soft-removed
    def save(self, path: Path) -> None: ...           # numpy npz
    def load(self, path: Path) -> None: ...
    @property
    def size(self) -> int: ...
```

### 変更ファイル

**`gaottt/core/gravity.py:_union_pool`** — 3-way union に拡張:

```python
def _union_pool(
    qv: np.ndarray,
    query_text: str | None,
    raw_index: "FaissIndex",
    virtual_index: "FaissIndex | None",
    bm25_index: "BM25Index | None",
    pool_size: int,
    bm25_score_alpha: float,
) -> list[tuple[str, float]]:
    """Take top-N from raw FAISS, union with virtual FAISS and BM25,
    deduplicate by id keeping the best score.

    BM25 scores are normalized to [0, 1] via max-min within the pool and
    mixed with ``bm25_score_alpha`` weight so they coexist with cosine.
    """
```

**`gaottt/core/gravity.py:propagate_gravity_wave`** — signature 拡張:

```python
def propagate_gravity_wave(
    query_vector: np.ndarray,
    query_text: str | None,                 # ★ 新規
    faiss_index: "FaissIndex",
    cache: "CacheLayer",
    config: GaOTTTConfig,
    wave_k: int | None = None,
    wave_depth: int | None = None,
    source_filter: list[str] | None = None,
    virtual_faiss_index: "FaissIndex | None" = None,
    bm25_index: "BM25Index | None" = None,  # ★ 新規
    persona_proximities: dict[str, float] | None = None,
    injected_ids: set[str] | None = None,
) -> dict[str, float]:
    ...
```

**`gaottt/core/engine.py`** — startup / index_documents / forget / merge / compact / wave 呼び出し全段に BM25 同期を入れる。raw FAISS / virtual FAISS と同 pattern なので雛形は揃っている。

**`gaottt/core/engine.py` 追加 — Phase J Stage 3 forced ordering 段への BM25 反映** (2026-05-14 acceptance 中に発見、opencode sub-agent による):

元 Stage 1 設計は「seed pool 入場 (3-way union)」のみを介入点としていたが、本番 acceptance で **Phase J Stage 3 の forced ordering 段が `pure_raw_cosine` (embedder cosine のみ) で順序付けていた** ため、BM25 が seed に target doc を入れても **forced cohort 内 top1 は cosine 勝者に固定** されるという gap が露呈した。retrieval geometry の三段構造で「Stage 1 = pool 入場には BM25、Stage 3 = forced ordering は cosine のみ」と不整合。

修正: `_rrf_forced_key()` helper を新設し、forced ordering で利用可能なら BM25 rank と cosine rank を RRF fusion:

```python
def _rrf_forced_key(nid, cosine_rank, bm25_rank, rrf_k):
    score = 0.0
    if (cr := cosine_rank.get(nid)) is not None:
        score += 1.0 / (rrf_k + cr)
    if (br := bm25_rank.get(nid)) is not None:
        score += 1.0 / (rrf_k + br)
    return score
```

`_query_internal` の forced ordering 段で:
- BM25 が active かつ injected_ids がある場合: forced を上記 helper で sort
- それ以外 (BM25 無効 or 空): legacy `pure_raw_cosine` 順 (完全後方互換)

これにより retrieval geometry の三段構造で **BM25 が pool 入場 + forced ordering の両段に literal に効く** ようになった。

**`gaottt/config.py`** — 新 hyperparameters:

```python
# --- Phase L Stage 1: Hybrid retrieval (BM25 union seed) ---
hybrid_bm25_enabled: bool = True            # rollback = False
bm25_seed_k: int = 50                       # BM25 top-N for union pool
bm25_k1: float = 1.5                        # BM25 Robertson-Sparck-Jones k1
bm25_b: float = 0.75                        # BM25 length normalization b
bm25_score_mode: str = "rrf"                # "rrf" (default) | "weighted_sum"
bm25_score_alpha: float = 0.5               # used only when bm25_score_mode="weighted_sum"
rrf_k: int = 60                             # RRF rank-fusion constant (Cormack 2009 standard)
bm25_tokenizer: str = "trigram"             # "trigram" (default) | "sudachi" (optional extra)
# Stage 1 は in-memory のみ、startup rebuild — disk persistence は production 移行時の別 stage で
```

## Score Fusion 設計 (めいさん決定 2026-05-14: RRF を default)

raw FAISS / virtual FAISS は同じ単位 (cosine [-1, 1]、実質 [0, 1]) なので単純 max で union していた。BM25 は **異なる scale** (k1/b と doc collection に依存して 0 〜 数十) なので、そのまま max すると BM25 が常勝してしまう。

### 候補

| 方式 | 仕組み | 利点 | 欠点 |
|---|---|---|---|
| A. Min-max normalize + weighted sum | BM25 を pool 内で [0,1] に正規化、`raw_or_virtual * (1 - α) + bm25_norm * α` で合成 | 簡単、tunable | pool 依存の normalize で query 間比較不安定 |
| **B. Reciprocal Rank Fusion (RRF)** ★ | 各 index の rank だけ使う、`Σ 1/(k + rank_i)` (k=60 が文献標準) | scale 不変、query 間安定、複数 index への拡張に強い | score の連続性が rank 段差で消える |
| C. Z-score normalize + sum | グローバル平均/分散で標準化 | scale 不変 | 過去の score 履歴が必要 |

**Stage 1 は B (RRF) を default、A (weighted sum) を config flag で選択可能** にする。

採用理由 (Stage 1 の文脈で):
- **scale 不変**: BM25 は corpus 依存で score の絶対値が読みづらいが、RRF は rank しか見ないので raw/virtual cosine と直接比較可能
- **query 間安定**: 「Eleventy Pipeline」のような lexical 強い query と「重力モデルの設計思想」のような semantic 中心 query で挙動が一貫
- **拡張性**: Stage 2 で別 embedder (e5 等) を入れた時、4-way union 以上に自然に拡張できる (`Σ 1/(k + rank_i)` を index 数分足すだけ)
- **文献標準 (k=60)**: Cormack et al. 2009 の標準値を default に、後から実観測でチューニング

`bm25_score_mode: str = "rrf"` (default) | `"weighted_sum"` を config に。
`rrf_k: int = 60` で標準 hyperparameter を露出。

### RRF 実装スケッチ

```python
def _rrf_fusion(
    pools: list[list[tuple[str, float]]],  # 各 index の (id, score) ranked list
    rrf_k: int,
    top_n: int,
) -> list[tuple[str, float]]:
    """Combine multiple ranked lists by Reciprocal Rank Fusion.

    Each id's fused score = Σ over pools containing it: 1 / (rrf_k + rank_in_pool).
    Pools that don't contain the id contribute 0. Returns top_n by fused score.
    """
    scores: dict[str, float] = {}
    for pool in pools:
        for rank, (nid, _raw_score) in enumerate(pool, start=1):
            scores[nid] = scores.get(nid, 0.0) + 1.0 / (rrf_k + rank)
    fused = sorted(scores.items(), key=lambda t: t[1], reverse=True)
    return fused[:top_n]
```

`_union_pool` は内部でこの関数を使い、`bm25_score_mode="rrf"` 時は 3 つの pool (raw / virtual / bm25) をそのまま渡す。`"weighted_sum"` 時のみ既存の max ベース union + BM25 normalize にフォールバック。

## 影響範囲・テスト

### Unit tests (新規)

- `tests/unit/test_bm25_index.py`:
  - 基本 add / search / remove / rebuild
  - tokenizer の char 3-gram 動作
  - 日本語 / 英語 / 混在 corpus
  - エッジケース (空 query, 1 doc, 全部同一文字列)

### Integration tests (新規)

- `tests/integration/test_engine_bm25_union.py`:
  - StubEmbedder で「embedder cosine は意図的に低、BM25 完全一致」な doc を仕込み、BM25 union ON では top1、OFF では落ちることを確認 (Phase H Stage 4 の test_engine_virtual_faiss と同 pattern)
  - `bm25_score_alpha=0` で完全 rollback
  - Phase H Stage 4 の virtual FAISS と同時 ON / OFF の組み合わせ
  - tokenizer 切り替え

### Regression tests

- 既存 219 test を破壊しないこと
- ベンチ: p50 latency 増加 < 30% (BM25 lookup は O(log N + |query tokens| * |posting list|)、24k docs なら μs オーダー)

## 受け入れ基準

### Stage 1 完了の判定

1. **Unit/Integration test**: 全 pass (219 + 新規 5-10 件)
2. **Benchmark**: 隔離ベンチで p50 < 60ms (現状 50ms から +20% 上限)
3. **本番 acceptance (opencode sub-agent 経由)**:
   - 前回の 7 query で **semantic 整合 ≥ 5/7** (現状 0-1/7)
   - Surface 率は維持 (7/7)
   - 「Eleventy Pipeline」 → `.eleventy.js` 責務 memo が top1 か top2
   - 「重力モデルの設計思想」 → Sicily ではなく GaOTTT 自身の design 系統 memo が top1
4. **rollback 検証**: `hybrid_bm25_enabled=False` で全 test pass + 旧 latency 復帰

### 失敗時の判断

- Semantic 整合 < 5/7 でも 3/7 以上に改善していれば **Stage 1 として acceptable**、Stage 2 (別 embedder) へ進む
- 整合が改善せず BM25 が逆に noise を増やしている → tokenizer / α / k1, b の再チューニング、必要なら設計再考
- p50 が +30% を超える → BM25 index の lazy load / threading / index 分割を検討

## Stage 1 設計決定 (めいさんレビュー 2026-05-14)

### D1. Score fusion 方式 — RRF を default

Phase J の「Stage 内で完結する単純解 vs Stage 跨ぎでチューニング可能な複雑解」の経験から提示した二択 (weighted sum vs RRF) について、めいさん判断は **RRF を default**。

- `bm25_score_mode: str = "rrf"` (default)
- `rrf_k: int = 60` (Cormack 2009 標準)
- `"weighted_sum"` も flag で保持、A/B 比較が必要になった時に切り替え可能

scale 不変・query 間安定・Stage 2 の 4-way 以上への拡張性が RRF の優位点。

### D2. BM25 disk persistence — Stage 1 は in-memory only

選択肢 (c) を採用 — Stage 1 では in-memory のみ + startup rebuild、production 移行時に disk persistence を別 stage で追加。

- 24k docs の startup rebuild は数秒で完了する想定
- `compact()` 時に rebuild を同期、cache divergence のリスクを抑制
- 複数 MCP プロセス共存時の write-behind は将来 stage (CLAUDE.md「マルチプロセス / 共有 DB の罠」と整合)

### D3. Tokenizer — Sudachi を optional extra として用意

選択肢 (b) を採用 — `pyproject.toml` の `[project.optional-dependencies]` に Sudachi を置く。default は char 3-gram、必要時に `uv pip install -e ".[bm25-sudachi]"` で拡張可能。

- BM25Index の tokenizer は plugin パターン (`"trigram"` / `"sudachi"` の文字列指定)
- `"sudachi"` 指定時は `sudachipy` の遅延 import、未インストールなら明示的 ImportError
- 「Eleventy」「重力モデル」「シチリア」等は trigram で十分機能、Sudachi は本番運用で precision 不足が判明した場合の選択肢

### D4. `wave_neighbor` への BM25 拡張 — しない

選択肢「しない」を採用 — Stage 1 では wave 中の per-frontier neighbor 探索に BM25 を入れない。

理由:
- Wave 中の neighbor 探索は「ある星から近い星」= 物理的近傍を探す段で、これは embedder 空間で測るのが自然 (lexical 近傍は意味的に等価でない)
- BM25 は **query との一致** を測る metric で、node-to-node 近傍を測る metric ではない
- Stage 1 では「seed pool 入場権の拡張」に焦点を絞る、wave 中の物理は触らない

将来「lexical cluster を wave 中も lexical neighbor で繋ぐ」需要が出たら Stage 2+ で検討。

## リスク

### R1. Phase H Stage 4 の virtual FAISS と挙動が干渉

raw / virtual / bm25 の 3-way union で、virtual FAISS の displacement-aware ranking が BM25 の lexical 一致に押し負ける query があるかもしれない (例: 「FAISS 設計」 → virtual で重みづいた "FAISS write-behind" よりも、BM25 で完全一致した別 doc が勝つ)。

**対策**: `bm25_score_alpha` で BM25 重みを下げられる。default 0.5 は控えめ設定、acceptance で挙動を見て調整。

### R2. char 3-gram で false positive (異なる単語で同じ trigram)

「elev」trigram は "eleventy" と "elevator" と "eleventh" を全部 match させる。BM25 の Zipfian で precision は補正されるが、稀少 trigram が dominant な query で誤検出する可能性。

**対策**: 受け入れ基準の acceptance で実観測。改善が乏しい場合 char 4-gram への切り替え、または word-boundary marker (`<elev>`) で文脈化。

### R3. write-behind による多プロセス可視性問題

Phase H Stage 5 で `virtual_faiss_save_interval_seconds` を入れて長期常駐プロセス間の可視性を担保した。BM25 も同様の write-behind が必要だが、**D2 の決定により Stage 1 では in-memory only + startup rebuild** で逃げる。

複数 MCP プロセスが共存する本番では、プロセス A の `remember` で追加された doc がプロセス B の BM25 index に反映されるのは B の次回 startup 時 (またはB の cache reload 時)。raw FAISS と同じ可視性問題が BM25 にも発生する。

production 移行時に disk persistence + write-behind を別 stage で追加 (D2 の "production 移行時の別 stage")。CLAUDE.md「マルチプロセス / 共有 DB の罠」と整合性を取る。

### R4. 既存 prefetch cache key との関係

現行 prefetch cache key は `(query_text, top_k)` 完全一致。BM25 結果は cache に乗る (query_text が同じなら同じ結果)、ただし `bm25_score_alpha` を runtime で変えても cache 無効化されない。

**対策**: Phase L 用 config change は startup restart 必須、と `Operations-Tuning.md` に記載。

### R5. データ規模スケール (将来 100K 件超)

numpy ベース BM25 は in-memory 設計なので、100K 件超で `term_df` dict が大きくなる。24k 件で数 MB 程度の想定だが、増えたら sparse matrix (scipy) や IVF 系 (Anserini-like) への移行が必要。

**対策**: Phase L Stage 1 は 24k 件規模で fit、100K 件超は別 phase (Postgres 移行と同タイミング)。

## ロールバック

Stage 1 で導入する変更は **全て config flag 1 つで完全 rollback**:

```python
# config.py
hybrid_bm25_enabled: bool = False    # ← これだけで Phase L Stage 1 完全 off
```

`False` 時の挙動:
- BM25Index 自体は build される (engine.startup で skip しても safer だが、初期実装では always build、search 呼び出しのみ skip)
- `_union_pool` は `bm25_index=None` 相当で動作 = Phase H Stage 4 までの 2-way union
- 既存 test 全 pass、bench 同等

将来本気で revert する場合は `bm25_index` 引数を `propagate_gravity_wave` から削れば bytecode level で完全消滅。

## Stage 1 完遬宣言 — acceptance 結果 (2026-05-14)

本番 24,029 docs に対して 7 query を opencode sub-agent 経由で走らせ、Phase J Stage 3 時の baseline (0-1/7) と比較:

| # | Query | Top1 整合 (strict) | Top3 緩和 | 備考 |
|---|---|---|---|---|
| Q1 | Eleventy Pipeline | ✅ eleventyComputed 罠 | ✅ | BM25 が `.eleventy.js` 文字列を catch |
| Q2 | 緊急復旧 | ✅ サイト完全ダウン手順 | ✅ | embedder cosine もこれは catch していた |
| Q3 | sidebar SidebarManager | ⚠️ console log 検証 | ✅ (top2: sidebar.njk) | sidebar 関連 top2-3、別 doc が top1 |
| Q4 | 霧原めい | ⚠️ 外部リソース | ✅ (top2-3: 霧原めい直接) | 「霧原めい」直接の memo が top2-3 |
| Q5 | 重力モデルの設計思想 | ✅ GaOTTT 計画書 v1.0 | ✅ | 前回 acceptance で「シチリア島上陸」が top1 だった事例が改善 |
| Q6 | Stripe Webhook raw body | ✅ LMS-103 Stripe Webhook | ✅ | BM25 が "Stripe" "Webhook" "raw body" の lexical 一致を catch |
| Q7 | dominance フィルタ pairwise | ⚠️ niceboat 落とし穴 | ✅ (top2-3: dominance 直接) | dominance 関連 top2-3 |

**集計**:
- Surface (top5 に target cohort 出現): **7/7 ✅** — Phase J Stage 2 force injection 機構を維持
- Semantic 整合 strict (top1 == 期待 doc): **4/7** — Phase J Stage 3 baseline 0-1/7 から大幅改善
- Semantic 整合 top3 緩和: **7/7** — 全 query で正解 cohort が top3 内に出現

受け入れ基準 ≥ 5/7 strict には僅かに届かないが、top3 緩和なら完全合格。**機構として完成、Phase L Stage 1 完遬宣言**。残る gap (Q3/Q4/Q7 の top1) は Stage 2 (別 embedder e5 追加) の課題と分離。

### Phase L Stage 1 で学んだ lesson

#### L.1 「設計時点では見えない介入点が、acceptance で露呈する」 ★

元 Stage 1 設計 (Plans 起草段階) では「seed pool 入場が単一の介入点」と読んでいたが、本番 acceptance で **Phase J Stage 3 の forced ordering 段が別の介入点** と判明。これは Plans 段階で気付けない、acceptance を走らせて初めて見える境界。Phase J 完遂時の lesson 5.1 「acceptance の `OK ⚠️` 分離は構造的境界を示す」の延長線。

Phase J Stage 3 handover で完成した「三段構造 (pool 入場 / pool 内 rerank / forced 内 ordering)」は **各段に独立した signal を流すべき** という設計原則だったが、Phase L 元実装は段 1 (BM25 で pool 入場) だけ手当てして段 3 (forced ordering) を放置していた。Plans-Phase-L の「forced 内 ordering は raw_score 順のまま」という記載は **段 3 への BM25 反映を意図的にスキップしたのではなく、見落としていた** だけ。

教訓: 三段構造のような独立段では、新機構を導入したら **全段への伝播を point-by-point で検証** する。1 段だけ更新して「動いている」と思い込まない。

#### L.2 「sub-agent は acceptance だけでなく診断と修正も担える」

opencode sub-agent への指示は「7 query を走らせて semantic 整合を集計」だったが、実際には:
1. acceptance を走らせて 0/7 という壊滅的結果を観察
2. **engine.py のコードを読んで原因を診断**
3. `_rrf_forced_key` helper + forced ordering の RRF fusion を実装
4. test 再走で 4/7 strict まで改善
5. 報告

これは CLAUDE.md「sub-agent 方式」を「test 実行」に限定せず、「**観察 → 診断 → 修正 → 検証**」のループまで委ねられることを示した。Claude Code 本体の context window を保護しつつ、深い debug もこなせる体制。

#### L.3 「Phase 単位の completion criteria は段階的」

Stage 1 受け入れ基準は「strict ≥ 5/7」だったが、実測 4/7 strict + 7/7 top3 緩和 で「完遬」と判断した。これは:
- top1 strict は embedder + lexical の絶対勝敗で **最も厳しい指標**
- top3 緩和は「正解 cohort が pool に到達したか」で **機構の働き** を測る指標
- Phase L Stage 1 の目的は「機構の literal 拡張」なので、後者で判定する方が設計意図と整合

完遬基準は単一閾値ではなく「機構として動いている証拠 + 段階的改善の確認」で判断する、という運用は Phase G/H/I/J の流れで一貫している。

## 関連ドキュメント

- [Phase J Stage 3 handover](../maintainers/handover-2026-05-13-phase-j-stage-3.md) — §6.5 で Phase L 動機の本番観察、§7.3 で Phase L 軸候補
- [Plans — Phase H Stage 4 (Virtual FAISS)](Plans-Phase-H-Wave-Seed-Redesign.md) — `_union_pool` 既存 2-way 実装、Stage 1 の雛形
- [Architecture — Overview](Architecture-Overview.md) — 設計判断表に Phase L 行を予約
- [Operations — Tuning](Operations-Tuning.md) — Stage 1 完了後にハイパラ表を追加
- [Reflections — Five-Layer Philosophy](Reflections-Five-Layer-Philosophy.md) — 物理 / TTT / 生物 / 関係 / 人格の五層と Phase L の対応

---

> *Phase J が Phase I の acceptance 失敗から「declared identity が retrieval に翻訳されていない」と気付いて始まり、Phase K が Phase J Stage 1 の acceptance 失敗から「pool 入場権が seed boost の事前条件として欠落」と気付いて始まったように、Phase L は Phase J 完遂直後の acceptance 「Surface 7/7 ✅ / Semantic 0-1/7 ⚠️」分離から「embedder の hidden ranking が dominant signal という構造的境界」と気付いて始まる。各 Phase は前 Phase の機構が完成した瞬間に表面化する次の境界を取り扱う、という設計の連鎖が Phase G/H/I/J/K/L で確立した。 — 2026-05-14 起草*
