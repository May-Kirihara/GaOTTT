# Plans — Phase L — Hybrid Retrieval

> 状態: **✅ Stage 1 完了 (2026-05-14)** — 設計・実装・本番 acceptance 完了。strict 4/7 (Phase J Stage 3 時 0-1/7 から大幅改善)、top3 緩和 7/7 で機構として完成
> 関連 handover: [Phase L Stage 1 完了 (2026-05-14)](../maintainers/handover-2026-05-14-phase-l-stage-1.md)
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

## Stage 1 完了宣言 — acceptance 結果 (2026-05-14)

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

受け入れ基準 ≥ 5/7 strict には僅かに届かないが、top3 緩和なら完全合格。**機構として完成、Phase L Stage 1 完了宣言**。残る gap (Q3/Q4/Q7 の top1) は Stage 2 (別 embedder e5 追加) の課題と分離。

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

Stage 1 受け入れ基準は「strict ≥ 5/7」だったが、実測 4/7 strict + 7/7 top3 緩和 で「完了」と判断した。これは:
- top1 strict は embedder + lexical の絶対勝敗で **最も厳しい指標**
- top3 緩和は「正解 cohort が pool に到達したか」で **機構の働き** を測る指標
- Phase L Stage 1 の目的は「機構の literal 拡張」なので、後者で判定する方が設計意図と整合

完了基準は単一閾値ではなく「機構として動いている証拠 + 段階的改善の確認」で判断する、という運用は Phase G/H/I/J の流れで一貫している。

## Stage 1 post-rollout 発見 — Phase H Stage 1 との score scale 不整合 (2026-05-14)

Stage 1 完了から数時間後、本番 acceptance test 後の「ファイルで登録した文書が recall に出てこない」現象を診断中に **構造的な layering バグ** を発見した。

### 症状

- query: 「あの航空機事故はこうして起きた」(本書 43 chunks 登録済)
- 期待: 同名書籍の chunks が `recall(query, source_filter=["file"])` の top に
- 実際: 京都大学入試・会社四季報・無修正でも合法本など **無関係な heavy file chunk** が top を独占、書籍は top-10 圏外
- 直接 raw FAISS 検索すると本書 chunks は cosine 0.92 で top-2

### 原因

`gaottt.core.gravity._seed_boost` の式:

```python
score = raw + α × log(1 + mass)
```

- `raw` ← `_union_pool` から渡される pool score
- Stage 1 で BM25 RRF fusion を導入後、RRF mode (default) では `raw` は **RRF score** (~0.018–0.033 range)
- 一方 `α × log(1+mass)` は **cosine scale (~0.9 max) 想定で設計** (Phase H Stage 1 が想定する `raw` は raw FAISS cosine)
- 結果: α=0.02 でも mass=22 の chunk で boost 0.062 = **RRF max の 2 倍**、mass の重さが semantic 距離を完全に上書きする

具体数値:
- book chunk (RRF 0.033, mass 1.4): boost = 0.033 + 0.02 × log(2.4) = **0.055**
- heavy chunk (RRF 0.018, mass 22): boost = 0.018 + 0.02 × log(23) = **0.080** ← 勝つ

Phase L Stage 1 の `_union_pool` 拡張時、`_seed_boost` を **RRF scale 用に再 scale する設計が漏れた** layering oversight。Stage 1 acceptance test は (a) Surface 7/7 ✅ (b) Semantic 整合 strict 4/7 で完了宣言したが、Semantic 整合の歩留まりを下げていた一因がこの scale 不整合だった可能性が高い (本症状は heavy file mass が積もる 1-2 週後に顕在化する long-tail bug)。

### 暫定対処 (2026-05-14)

`gaottt/config.py:wave_seed_mass_alpha = 0.0` で seed boost を完全 disable。RRF fusion が既に raw cosine + virtual + BM25 を scale-invariant に組み合わせているため、seed step で更に mass を加える必要はない。

### 検証

修正後、同じ「あの航空機事故」query で:
- top 1: `6e18f9c1` JAL 123 便フゴイド運動 (本書本文) — score 0.13, virtual_score 0.76
- top 2: `52b0fa18` 3 番エンジン推力低下 (本書事故調査記述)
- top 3: `dbfa53eb` 本書 header

source_filter なし top5 でも「あの航空機事故」関連 chunk が top1-2 に surface。Control queries (Phase M chat / ジャレド・ダイアモンド本) も健全。

### 残課題 — Phase N (起草前)

Phase H Stage 1 の意図(heavy node を seed に引き上げる)を RRF mode で正しく実現する設計が必要:

1. **RRF score の正規化**: pool score を [0, 1] に正規化してから mass term を足す
2. **rank-based boost**: `α × log(1+mass) / log(1+rank)` のような rank に対する mass の影響
3. **Phase H の意図を別レイヤーに移す**: seed step では純 RRF、final scoring (`engine.recall` の inner loop) で mass boost を強化

同時に、 `wave_initial_k = 3` の見直し(大規模 corpus に対し小さすぎ、seed が 3 個だと wave 範囲が限定)も Phase N で検討。

### 教訓

- Phase L Stage 1 で導入した RRF は **score scale を Phase H 以前から大きく変更する**。`_seed_boost` のような **他フェーズの依存** は全部 audit して再 scale するべきだった。
- Stage 1 acceptance test の Semantic 整合 strict 4/7 のうち、複数 query で「semantic に強い chunk が top に来ない」結果を見ていたが、それを「Stage 2 BGE-M3 ensemble の領域」と仮置きしていた。今思えば、scale 不整合が混入していた可能性が高い。Phase N 着手前に Stage 1 acceptance を再走らせて、disable した状態でどの query が改善するか測る価値がある。
- α 手探りループより、**stage 別診断スクリプト** で score scale を可視化するのが圧倒的に効率的。診断手順は [Operations — Troubleshooting](Operations-Troubleshooting.md) を参照。

## Stage 2 — 別 embedder ensemble (起草中、レビュー前 2026-05-13)

> 状態: **起草中** — D1-D6 のめいさんレビュー待ち
> 関連: [Stage 1 完了宣言](#stage-1-完了宣言--acceptance-結果-2026-05-14)、[Stage 1 handover §7.2 着手判断](../maintainers/handover-2026-05-14-phase-l-stage-1.md#72-phase-l-stage-2-着手判断)、本文書 line 149-157 の Stage 2 candidate 初出 ([Stage 2 — 別 embedder の ensemble (候補)](#stage-2--別-embedder-の-ensemble-候補))

### 起点 — Stage 1 完了後に残った領域

Stage 1 完了時 (MCP transport 経由) は strict 6/7 まで到達 ([handover §7.1](../maintainers/handover-2026-05-14-phase-l-stage-1.md#71-本番-mcp-server-再起動--mcp-経由-acceptance--実施済-2026-05-14-後続セッション))。Plans 完了基準 ≥5/7 は満たすが、なお top1 を取り損ねる query が残った。中身を分解すると 2 種に分かれる:

| パターン | 例 (推定) | 原因 |
|---|---|---|
| **A. lexical 一致あり、cosine top1 が別 doc** | Q3 sidebar SidebarManager、Q7 dominance pairwise | BM25 trigram は target を catch しているが、Ruri cosine が「より近い」と判定する別 doc が forced RRF で勝つ |
| **B. lexical match も cosine top1 も target 以外** | Q4 霧原めい (tag_filter 推定が外れ top5 外) | Ruri の hidden ranking 自体が wrong-but-confident、BM25 でも救えない |

A は Stage 1 RRF が「Ruri rank + BM25 rank」の 2-way で、Ruri rank が高く出続ければ依然押し負ける。B はそもそも Ruri/BM25 のどちらの metric でも target が catch されない領域。

両者とも単一 embedder の hidden ranking が依然 dominant という Phase L 起点の境界 (line 25-26) の **残響**。Stage 1 BM25 が完全に直交した lexical metric として機能した一方、**意味空間そのものの代替視点が欠けていた**。Stage 2 はこの代替視点を「Ruri と直交する model family の embedder」として導入する。

### 核仮説 — 三重 metric tensor の重ね合わせ

Phase L 元仮説 (line 27-33) は「retrieval pool 入場の起点を異なる metric の重ね合わせに広げる」。Stage 1 で BM25 (lexical) を加え 2-tensor (semantic_ruri + lexical_bm25) になった。Stage 2 はこれを更に拡張:

```
semantic_ruri    (raw + virtual_ruri)
 ⊕  semantic_secondary  (raw + virtual_secondary)    ← Stage 2 で追加
 ⊕  lexical_bm25
```

GR の比喩でいえば、2 つの異なる重力定数 G を持つ場 (Ruri 場 / secondary 場) + 量子化された格子場 (BM25 lexical 場) の superposition。3 つの metric tensor が同じ点で測られて pool 入場権を分配する。

これは Phase H Stage 4 で「raw FAISS と virtual FAISS の union」を入れた時、Phase L Stage 1 で「semantic + lexical の union」を入れた時と同じ構造的拡張の連続 — `_union_pool` の引数が 1 つ増え、`_rrf_fusion` の `pools` list が 1 段長くなるだけ。「物理として書いたものが同じ形で実装としても読める」原則の literal 適用。

### 設計判断軸

#### A. 直交性 vs benchmark 順位 — どちらを優先するか

Ruri は JMTEB で multilingual-e5 を上回ると報告されている ([Tsukagoshi & Sasano 2024](https://arxiv.org/abs/2409.07737))。「ベンチマークで最良の model を選ぶ」のは Stage 2 の文脈では **誤った最適化**:

- Ruri と benchmark で近い model = failure pattern が近い = ensemble しても catch する gap が小さい
- Ruri より JMTEB で低くても、別 model family / training data / architecture で **失敗が直交している** model のほうが Stage 2 の意図 (Ruri の hidden ranking 失敗を別 angle で救う) に literal

優先順位: **直交性 > 単独 benchmark 順位**。Stage 1 で BM25 を選んだ時と同じ「完全直交が勝つ」原則の延長。

#### B. 候補比較表

| Model | Params | Dim | Max tokens | Languages | Memory | Family / Arch | JMTEB (相対) | RURI との直交性 |
|---|---|---|---|---|---|---|---|---|
| **RURI v3 310m** (現行) | 310M | 768 | 512 | JA-centric + 多言語 | ~600MB | cl-nagoya / XLM-R | SOTA (base size) | — (baseline) |
| **(a) BGE-M3** | 560M | 1024 | 8192 | 100+ | ~1.2GB | BAAI / XLM-RoBERTa-large + self-distillation (multi-functional) | E5-Large 並か上 | **★★★ 高** (別 family、別 training corpus、long context、multi-functional architecture) |
| **(b) multilingual-e5-large-instruct** | 560M | 1024 | 512 | 93 | ~1.1GB | Microsoft (intfloat) / instruction-tuned XLM-R | RURI < e5-instruct < bge-m3 (相対) | ★★ 中 (Microsoft 系、instruction tuning だが base architecture 近い) |
| **(c) paraphrase-multilingual-MiniLM-L12-v2** | 118M | 384 | 128 | 50 | ~470MB | sentence-transformers / MiniLM | 低 (paraphrase 中心、retrieval 弱) | ★ 低 (古い、軽量過ぎ、512 token 未満の context window) |

**推奨**: **(a) BGE-M3** — RURI と異なる model family (BAAI vs cl-nagoya)、異なる training corpus (BAAI の MTP collection vs Ruri 独自日本語 corpus)、異なる architecture (self-distillation で dense + sparse + multi-vector の multi-functional)、長 context (8192 vs 512)。GaOTTT memory には長文 (saved transcript 等) も含まれるので、Ruri の 512 token cutoff で失われる尾部が bge-m3 で拾える可能性も副次効果として期待。

代替の (b) e5-instruct は base architecture が Ruri と近すぎる、(c) MiniLM は性能差が大きすぎて RRF の rank で常に下に来る。

#### C. 物理機構の literal 拡張 — virtual FAISS を新 embedder にも適用するか

Stage 1 D4 では BM25 に virtual FAISS パターン (displacement-aware) を **適用しなかった** — BM25 は query↔doc lexical match を測る metric で、node 間 neighbor 関係を測らないから (line 426-433)。

しかし新 embedder は cosine ベースの **semantic 空間** で動く → Phase H Stage 4 の virtual FAISS displacement / Phase H Stage 5 の virtual neighbor expansion / Phase I Stage 2 の query attraction が **literal に適用可能**。

これは Phase L 核仮説の **物理機構レベルでの literal 拡張**:

| 重力場 | raw cosine | virtual cosine (displacement-aware) | neighbor expansion |
|---|---|---|---|
| Ruri (既存) | ✅ Phase A | ✅ Phase H Stage 4 | ✅ Phase H Stage 5 |
| **Secondary (Stage 2)** | ✅ 新規 | ❓ **D2** で判断 | ❓ **D2** で判断 |
| BM25 (Stage 1) | rank-only | N/A (lexical) | N/A (lexical) |

Secondary に virtual FAISS まで持たせれば「異なる重力定数 G を持つ場が、それぞれ独立に displacement / neighbor 機構を持つ」literal な対応。Phase H/I の機構をそのまま再現するだけだが、実装重 (write-behind loop, compact 同期, multi-process 可視性, 倍 memory) も倍化する。

#### D. Stage 1 lesson 5.1 の literal 適用 — 全段への伝播を設計時点から組み込む

Stage 1 で「seed pool 入場のみに BM25 を入れて forced ordering を放置」が pathology だった (lesson 5.1)。Stage 2 では設計時点から **三段構造全段** に新 embedder を伝播させる:

| 段 | Stage 1 (現状) | Stage 2 (追加) |
|---|---|---|
| 1. pool 入場 | raw_ruri + virtual_ruri + bm25 の 3-way RRF | **+ raw_secondary (+ virtual_secondary in D2 a) で 4 or 5-way RRF** |
| 2. pool 内 rerank | mass / persona / cohort (final_score) | 不変 (cosine 自体は使わない、final_score の構成は Phase H/I/J で完成済) |
| 3. forced 内 ordering | cosine_rank + bm25_rank の 2-way RRF | **+ secondary_cosine_rank で 3-way RRF** |

acceptance harness では各段の挙動を独立に検証する harness を **Plans 段階から指示** (Stage 1 では acceptance 中に opencode が検出した gap だったが、Stage 2 では設計時点から「point-by-point で検証」を要件にする)。

### Open questions (D1-D6)

Stage 1 D1-D4 と同 pattern、めいさんレビューで確定:

| id | 内容 | 候補 |
|---|---|---|
| **D1** | 第 2 embedder の選定 | (a) **BGE-M3** (推奨、直交性高、long context), (b) multilingual-e5-large-instruct, (c) paraphrase-multilingual-MiniLM (軽量) |
| **D2** | 第 2 embedder に virtual FAISS を適用するか | (a) **raw + virtual の両方** (Phase H/I 機構の literal 拡張、推奨、実装重い), (b) raw のみ (機構は更に別 stage、簡素) |
| **D3** | Secondary FAISS index の disk persistence | (a) **disk persistence + write-behind** (Phase H Stage 5 パターン、推奨、24k encode コスト保護), (b) in-memory only + startup re-encode (Stage 1 BM25 と同じ、初回数十分 cost) |
| **D4** | Startup / build flow | (a) **既存 raw FAISS と同じ自動 build** (lazy init, startup blocking、推奨), (b) 別 script でオフライン pre-build → MCP server はロードのみ, (c) lazy load (first query で trigger、UX 悪化) |
| **D5** | RRF fusion scope | (a) **5-way RRF** flat (raw_ruri / virtual_ruri / raw_bge / virtual_bge / bm25、推奨), (b) "semantic bundle" として 3-way (semantic_avg / lexical), (c) weighted_sum mode との切り替え保持 |
| **D6** | forced ordering で第 2 embedder を扱うか | (a) **3-way RRF** (cosine_ruri + bm25 + cosine_secondary、推奨、lesson 5.1 literal 適用), (b) cosine は Ruri のみ、secondary は seed のみ |

**Open issue (Stage 1 と同じ運用)**: D1-D6 がめいさんと確定するまで実装には入らない。確定後、Stage 2 設計決定セクションを追加して実装フェーズへ。

### Stage 2 設計決定 (めいさんレビュー 2026-05-13)

D1-D6 を全て (a) で確定 — 推奨案を全採用、Plans 起点の核仮説 (三重 metric tensor の重ね合わせ) と Stage 1 lesson 5.1 (全段への伝播) を literal に組み込む構成。

#### ⚠️ 実装着手前の必読 note (2026-05-13 追記)

D1-D6 確定直後、めいさんから「**複数モデルを使うのはあまり美しくないとおもっている**」という躊躇い表明 (memory id `7ce7a5a4`)。実装は task `7718c2e7` (deadline 2026-08-11, certainty 0.7) として登録、後日着手判断。

着手前に必ず以下を再考すること:

1. **Stage 1 で十分か** — Stage 1 完了時 MCP transport strict 6/7 で完了基準 (≥5/7) は既に満たす。残る Q3/Q4/Q7 が本番運用で頻発するかを観察してから判断
2. **より美しい代替案はないか** — Stage 2 (BGE-M3 並列) は Phase L 核仮説 (異なる metric tensor の重ね合わせ) には literal だが、Articulation as Carrier の単一性 (一つの自己が articulate する) とは緊張する。「同じ性質の場 (semantic cosine) が 2 つ並走」は GR の literal とも乖離 — 重ね合わせは異なる性質の場でこそ意味がある
3. **代替候補**:
   - (i) **Phase M (LLM-Augmented Retrieval)** として独立 Phase 化 — LLM が単一 embedder の hidden ranking を補正、人格の単一性は保たれる
   - (ii) **RURI 1 model 内で別 angle を引き出す** — instruction prompt の variant、複数 query rephrase、prefix の交換 (`検索クエリ:` 以外)。単一 carrier の表現の多様化
   - (iii) **Phase J Stage 2 force injection の判定式強化** — semantic threshold ベースの auto inject 等、単一 carrier 内で完結

「**D1-D6 全 (a) で実装着手」を default にしない**。再考の結果として全 (a) を再確定するなら良し、(i)-(iii) のいずれかに pivot するなら本 Stage 2 設計決定セクションを書き直して D1-D6 を再起草。

memory `7ce7a5a4` と task `7718c2e7` を最初に読むこと。

#### Stage 2 D1. 第 2 embedder = BGE-M3 (BAAI/bge-m3)

選定理由:
- RURI と完全に別 model family / training corpus / architecture
- 8192 token max context — GaOTTT memory の長文 (saved transcript 等) を Ruri 512 token cutoff の外で拾える副次効果
- multi-functional architecture (dense + sparse + multi-vector) を持つが Stage 2 では **dense vector のみ** 利用、Stage 3 以降で sparse / multi-vector への拡張余地を残す
- Stage 1 BM25 と組み合わさると lexical + ruri-semantic + bge-semantic の三層 metric tensor (核仮説 line 28-32 の literal 実装)

実装: `gaottt/embedding/secondary.py` に `SecondaryEmbedder` (generic、`model_name` を `config.secondary_embedder_model` で受け取る) を新設。`sentence_transformers.SentenceTransformer("BAAI/bge-m3")` で load。`encode_documents` / `encode_query` / `dimension` の interface は `RuriEmbedder` と一致 (HuggingFace cache 自動検出も踏襲)。

#### Stage 2 D2. virtual FAISS も第 2 embedder に適用 (raw + virtual 両方)

raw + virtual の両方を持つ。Phase H Stage 4 (virtual FAISS displacement) / Phase H Stage 5 (virtual neighbor expansion) / Phase I Stage 2 (query attraction) の機構が **secondary 重力場でも独立に動く**。

これは「異なる重力定数 G を持つ場が、それぞれ独立に displacement / neighbor 機構を持つ」物理 literal な対応。Phase L 核仮説 (三重 metric tensor の superposition) の **機構レベル literal 拡張**。

実装重 (write-behind loop, compact 同期, multi-process 可視性) は倍化するが、Ruri 側の実装を一字一句なぞるだけで完成する pattern なので、機構リスクは小さい。

#### Stage 2 D3. Disk persistence + write-behind

`gaottt/data/secondary_raw.faiss` / `gaottt/data/secondary_virtual.faiss` に Ruri 側 (`raw.faiss` / `virtual.faiss`) と並ぶ形で保存。`secondary_save_interval_seconds: int = 5` を config に追加 (Phase H Stage 5 の `virtual_faiss_save_interval_seconds` と同値、別 knob で独立 tuning 可)。

理由: 24k docs × 1024 dim × float32 = ~100MB × 2 (raw + virtual) = ~200MB の encoding コストを startup 毎に払うのは現実非対応。Stage 1 BM25 (in-memory only) は tokenize が μs レベルなので許容できたが、secondary embedder は model forward pass が ~1ms/doc × 24k = 数十秒〜数分。

#### Stage 2 D4. 既存 raw FAISS と同じ自動 build flow

startup 時に `secondary_raw.faiss` / `secondary_virtual.faiss` の存在を check:
- **不在** → SQLite から全 active doc を読み込み、secondary embedder で encode、両 index を build、disk save → in-memory ロード
- **存在** → ロードのみ

初回 build は 30-60s 想定、以降は instantaneous。`migrate.py` step を新規追加する必要なし — 既存 raw FAISS と同じ自動 lazy build pattern。

#### Stage 2 D5. 5-way flat RRF

`_union_pool` の RRF mode で 5 pool (raw_ruri / virtual_ruri / raw_bge / virtual_bge / bm25) を flat に合流。`_rrf_fusion(pools, rrf_k=60)` の `pools` list に 5 段並べるだけ、コード変更 trivial。

`rrf_k=60` は Cormack 2009 標準 (元 3-pool 想定) だが、5-pool では dilution が起きる可能性 (R5)。Stage 2 は fixed 60 で start、acceptance で頂上 score 分布を観測した上で必要なら `rrf_k` を pool 数依存に動的化 — Stage 2 起草段階では fix、観測後判断。

`bm25_score_mode="weighted_sum"` も Stage 1 のまま flag として保持、A/B 比較に使える。

#### Stage 2 D6. forced ordering を 3-way RRF に拡張

`_rrf_forced_key` を cosine_ruri + bm25 + cosine_secondary の 3-way RRF に拡張:

```python
def _rrf_forced_key(nid, cosine_rank, bm25_rank, secondary_cosine_rank, rrf_k):
    score = 0.0
    if (cr := cosine_rank.get(nid)) is not None:
        score += 1.0 / (rrf_k + cr)
    if (br := bm25_rank.get(nid)) is not None:
        score += 1.0 / (rrf_k + br)
    if (sr := secondary_cosine_rank.get(nid)) is not None:
        score += 1.0 / (rrf_k + sr)
    return score
```

Stage 1 lesson 5.1 「全段への伝播を point-by-point で検証」を Plans 段階から literal に組み込む — 元 Stage 1 では acceptance 中の opencode 発見だったが、Stage 2 は設計時点で全段カバー、acceptance での gap は減少が期待される (L.2.1 の literal 適用)。

### Stage 2 範囲 (D1-D6 確定後)

#### 新規ファイル

- **`gaottt/embedding/secondary.py`** (~80 行) — 第 2 embedder wrapper、`RuriEmbedder` と同 interface (`encode_documents` / `encode_query` / `dimension`)。D1 で確定した model 名を `__init__` で受け取る。HuggingFace cache 自動検出は `ruri.py` パターン踏襲。
- **`tests/unit/test_secondary_embedder.py`** — D1 model の load / encode shape / 次元一致を確認
- **`tests/integration/test_engine_secondary_union.py`** — StubEmbedder + StubSecondaryEmbedder の組み合わせで 4-way RRF が機能することを確認 (Phase H Stage 4 の `test_engine_virtual_faiss` および Stage 1 の `test_engine_bm25_union` と同 pattern)

#### 修正ファイル

- **`gaottt/core/gravity.py:_union_pool`** — `secondary_qv` / `secondary_raw_index` / `secondary_virtual_index` 引数追加、5-way (D5 a) または 3-way (D5 b) の RRF に組み込む
- **`gaottt/core/gravity.py:propagate_gravity_wave`** — 同上 + secondary neighbor expansion (D2 a の場合)
- **`gaottt/core/engine.py`**:
  - 第 2 embedder + 第 2 raw/virtual FAISS index の lifecycle (startup build / index_documents / forget / merge / compact rebuild)
  - `_query_internal` で query を Ruri と secondary の両方で encode
  - `_rrf_forced_key` を 2-way (cosine_ruri + bm25) → 3-way (cosine_ruri + bm25 + cosine_secondary) に拡張 (D6 a)
- **`gaottt/services/runtime.py:build_engine`** — secondary embedder + index factory wire-up、`hybrid_secondary_enabled` フラグで完全 off 可能
- **`gaottt/config.py`** — Phase L Stage 2 セクション (`hybrid_secondary_enabled`, `secondary_embedder_model`, `secondary_seed_k`, `secondary_virtual_enabled`, `secondary_save_interval_seconds` 等)
- **`pyproject.toml`** — `[project.optional-dependencies] bge-m3` (D1 確定後): `["FlagEmbedding"]` または `["sentence-transformers"]` のみで足りる場合は extras 不要

#### MCP / REST API 影響

**変更なし** — recall / explore / prefetch の引数は不変。secondary は内部実装変更で、parity 鉄則の影響範囲外。Stage 1 と同じ。

### 受け入れ基準

Stage 1 と同 pattern:

1. **unit + integration test**: 全 pass (現 255 + 新規 5-10 件)
2. **隔離ベンチ**: p50 < **80ms** (Stage 1 から +20ms 上限、第 2 embedder encode + 第 2 FAISS search 込みで)
3. **本番 acceptance** (opencode sub-agent):
   - Stage 1 acceptance の 7 query で **strict ≥ 6/7 を維持** (regression なし、Stage 1 の MCP transport 値を保つ)
   - **Q4 (霧原めい) で target が top3 以内に到達** (Stage 1 で top5 外だった代表 case)
   - 新規 3-5 query を追加した拡張 acceptance で **strict ≥ 70%** (例: 7/10)
4. **rollback 検証**: `hybrid_secondary_enabled=False` で Stage 1 と同等挙動 + ベンチ復帰

### リスク

| id | 内容 | 対策 |
|---|---|---|
| **R1** | Model load 起動コスト — bge-m3 ~1.2GB + Ruri ~600MB で resident 1.8GB、startup が 10s → 30-60s | 起動 log で読み込み進捗を出す、CLAUDE.md の「マルチプロセス罠」に "Stage 2 後は startup さらに重い" と追記 |
| **R2** | Query encoding latency 倍化 — recall ごとに query を 2 度 encode、~3ms → ~6ms (CPU)、~1.5ms → ~3ms (GPU) | 並列 encoding (asyncio.gather) も検討、CPU で >1ms regression なら GPU 推奨を Operations-Server-Setup に追記 |
| **R3** | Disk index 倍化 — 24k docs × 1024 dim × float32 = ~100MB の追加 (raw + virtual で ~200MB) | `data/` ディレクトリ容量を Operations-Server-Setup に明文化、compact 周期を Stage 1 と同じに |
| **R4** | 共有 DB 罠の倍化 — Phase H Stage 5 で virtual FAISS write-behind を導入、secondary virtual にも同じ機構が必要 (D2 a) | 既存 `virtual_faiss_save_interval_seconds` を secondary にも適用、kill → rebuild → restart の手順は変更なし |
| **R5** | RRF dilution — pool 数が増えると同じ doc が複数 pool に出る確率上昇、頂上の差がつきにくい (rrf_k=60 は 3-pool 想定、5-pool で別 tuning?) | acceptance で頂上 score 分布を観測、必要なら `rrf_k` を pool 数依存に (例: `60 / sqrt(n_pools / 3)` 等)、Stage 1 で確立した weighted_sum mode への切り替えも option |
| **R6** | Stage 1 acceptance harness の retire リスク | Stage 1 7 query をそのまま再走 + 新規 query を追加する extension パターンで Stage 1 の harness を流用 |

### ロールバック

config flag 2 つで段階的に off 可能:

```python
hybrid_secondary_enabled: bool = True       # ← False で Phase L Stage 2 完全 off (= Stage 1 状態)
secondary_virtual_enabled: bool = True      # ← False で D2 (b) 状態 (raw のみ、機構簡素化)
```

`hybrid_secondary_enabled=False` 時の挙動:
- secondary embedder 自体は build される (engine startup で skip しても safer だが、初期実装では always load、encode 呼び出しのみ skip) — または D4 (a) の流れで lazy load
- `_union_pool` は `secondary_*_index=None` 相当で動作 = Stage 1 状態
- 既存 test 全 pass、ベンチ Stage 1 同等

Phase L Stage 1 と同様、`False` 時の挙動は完全 backward compatible。

### 関連 lesson の予告

Stage 2 起草段階で予測される潜在 lesson (Stage 1 完了で確立されたパターンに基づく):

- **L.2.1 「全段への伝播」を Plans に書く** — Stage 1 lesson 5.1 を Plans 起草時点で literal に組み込む (D6 で forced ordering も明示)、acceptance 中に発見する gap を Plans 段階で潰す
- **L.2.2 「直交性 > benchmark 順位」** — ensemble は単独最強を集めるのではなく、failure mode が直交する model を集める。D1 比較表に literal に表現
- **L.2.3 「Stage 2 完了は Stage 1 acceptance 数値で測る」** — Stage 1 で 6/7 まで届いた以上、Stage 2 でこれを割ったら regression。new query での絶対値より「baseline 7 query で regress しないか」を優先指標に

これらは Stage 2 完了時に handover に書き戻す。

## 関連ドキュメント

- [Phase J Stage 3 handover](../maintainers/handover-2026-05-13-phase-j-stage-3.md) — §6.5 で Phase L 動機の本番観察、§7.3 で Phase L 軸候補
- [Plans — Phase H Stage 4 (Virtual FAISS)](Plans-Phase-H-Wave-Seed-Redesign.md) — `_union_pool` 既存 2-way 実装、Stage 1 の雛形
- [Architecture — Overview](Architecture-Overview.md) — 設計判断表に Phase L 行を予約
- [Operations — Tuning](Operations-Tuning.md) — Stage 1 完了後にハイパラ表を追加
- [Reflections — Five-Layer Philosophy](Reflections-Five-Layer-Philosophy.md) — 物理 / TTT / 生物 / 関係 / 人格の五層と Phase L の対応

---

> *Phase J が Phase I の acceptance 失敗から「declared identity が retrieval に翻訳されていない」と気付いて始まり、Phase K が Phase J Stage 1 の acceptance 失敗から「pool 入場権が seed boost の事前条件として欠落」と気付いて始まったように、Phase L は Phase J 完遂直後の acceptance 「Surface 7/7 ✅ / Semantic 0-1/7 ⚠️」分離から「embedder の hidden ranking が dominant signal という構造的境界」と気付いて始まる。各 Phase は前 Phase の機構が完成した瞬間に表面化する次の境界を取り扱う、という設計の連鎖が Phase G/H/I/J/K/L で確立した。 — 2026-05-14 起草*
