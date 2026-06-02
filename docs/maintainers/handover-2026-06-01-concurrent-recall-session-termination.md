# Handover 2026-06-01 — 並列 recall によるセッション終了 (Session terminated) の調査

**種別**: 既知バグの調査レポート → **修正完了 (2026-06-01)**
**重大度**: 中 (クライアント側の運用回避が可能。データ破損は未確認)
**ステータス**: ~~ユーザー判断で今回は修正見送り (option D)~~ → **fix 実装済み** (branch `fix/proxy-concurrent-recall-serialization`)。当初の見送りは別リポ (niceboat) 作業中だったため。GaOTTT 本体ではフルスコープで修正:
> - **Stage 1a** proxy 直列化 — 単一 upstream `ClientSession` への全 forwarder + ping を `asyncio.Lock` で 1 in-flight に直列化 (`proxy_serialize_requests_enabled`)
> - **Stage 1b** 自動再接続 — `_Upstream` holder が session 終了系例外で session を rebuild し 1 回 retry (`_ensure_backend` 再利用で backend 死/idle/cold-start も自己修復、`proxy_auto_reconnect_enabled`)。正常な tool error (`isError=True`) は素通し
> - **Stage 2** FAISS thread-race — `to_thread` save ↔ event-loop `add()` の真のクロススレッド競合を `FaissIndex` 内 `threading.Lock` で封じる (`faiss_index_lock_enabled`)。asyncio lock では防げない箇所
> - **Stage 3 (handler hardening) は不要と判明** — FastMCP は既に tool 例外を `isError` 結果に変換する (session を巻き込まない)
> - **broad engine RW-lock は意図的に不採用** — `test_engine_concurrent.py` の C2 注記が既に決着 (`_update_simulation`/`_update_cooccurrence` は await ゼロで cooperative scheduling 下 atomic)。hot path を無益に直列化するだけ
>
> 検証: 全 747 + perf 71 tests green、proxy 直列化/再接続の新規 test 6 件 + engine 並列 test 3 件、FAISS lock の recall latency 影響は p50 +1.9% / p95 +0.1% / p99 +7.4% (予算内)。
**調査時の HEAD**: `f3f6ce3`
**トランスポート**: proxy モード (`.mcp.json` が `python -m gaottt.server.mcp_server` を引数なしで起動 → default `--transport proxy`)

---

## 0. TL;DR

- **症状**: 1回のエージェントターンで `recall` を **2件並列**で呼ぶと、以後その MCP クライアントの全 GaOTTT 呼び出しが `MCP error 32600: Session terminated` になる。`/mcp` 再接続で復旧。
- **根本原因 (2層)**:
  1. **トランスポート層 (今回の主因・確度高)**: proxy が `call_tool` を**単一 upstream `ClientSession` 上で同時 POST** し、streamable-HTTP の1セッションが同時 in-flight リクエストで壊れる。直列化ガードが無い。
  2. **エンジン層 (潜在・別の地雷)**: engine に recall のミューテーションを守るロックが無く、非passive並列 recall や複数エージェント同時アクセスで gravity field 状態が壊れうる (過去に同種バグを個別修正した痕跡あり)。
- **重要な切り分け事実**: 今回クラッシュした2件は**両方 `passive=true`** だった。passive は perturbation 書き込みをしないので、**主因はエンジンの状態破壊ではなくトランスポート層**である可能性が高い。
- **推奨修正**: 直列化 (キューイング)。最小は **proxy 層の `asyncio.Lock`** (1セッション1 in-flight)。完全版は **engine 層の read-write lock**。
- **現状の回避策**: クライアント側で **GaOTTT 呼び出しを並列にしない** (逐次化)。コード変更ゼロで今すぐ効く。

---

## 1. 発生状況

niceboat プロジェクト (別リポ) の作業中、GaOTTT へ学習ノウハウを保存するセッションで発生。重複チェックのため次の2件を**同一ターンで並列**に発行した:

```
recall(query="確率キャリブレーション 温度スケーリング ...", top_k=6, passive=true)
recall(query="relevance_scheme top2_heavy NDCG@2 ...",     top_k=6, passive=true)
```

直後から `reflect` / `recall` / `remember` すべてが `MCP error 32600: Session terminated`。

- バックグラウンドで ~20s 待機してターン境界を跨いでも復旧せず。
- 一方で **UserPromptSubmit フックの `ambient_recall` は正常応答**していた → バックエンドプロセス自体は生存 (または再生成) しており、**壊れたのは当該クライアントの proxy セッションだけ**。
- `pgrep` でバックエンドが見つからなかったのは、調査までの数分で **idle watchdog (default 300s, `mcp_server.py` の `--idle-timeout`)** がバックエンドを落としたためと考えられる (即時 segfault ではない)。
- **`/mcp` で gaottt を reconnect** したら復旧 → proxy セッションを張り直したことが効いた、という観測と整合。

---

## 2. アーキテクチャ (proxy モード)

```
Claude Code ──stdio──▶ [proxy 内 lowlevel Server]
                          │  call_tool を毎回素通しで:
                          ▼
                    upstream: 単一 ClientSession ──streamable-HTTP──▶ [共有 backend: 単一 engine シングルトン]
                          ▲
                    ping_loop も同じ upstream session を共有 (60s 毎 send_ping)
```

- 各エージェントが自分の proxy を stdio で起動し、共有 HTTP backend に1本の `ClientSession` でつながる。
- backend 側は engine シングルトン (`mcp_server.py` `get_engine()` / `_engine_lock`)。**`_engine_lock` は初期化専用**で、リクエスト処理経路には掛かっていない。

---

## 3. 根拠 (コード上の事実)

### 3.1 proxy: 同時 in-flight を直列化していない
`gaottt/server/mcp_proxy.py`

- `_build_proxy_server` の `call_tool` は **ロック無しで素通し転送** (L228-232):
  ```python
  async def call_tool(req):
      result = await upstream.call_tool(req.params.name, req.params.arguments or {})
      return types.ServerResult(result)
  ```
- proxy の lowlevel `Server` は受信リクエストを**並行ディスパッチ**する (タスク/リクエスト)。よって2件の `call_tool` ハンドラが**同時に同じ `upstream` セッションへ POST** する。
- `upstream` は1本の `ClientSession` (`_proxy_session` L266-267)。`ping_loop` も**同じ session を共有** (L184-200, L274)。
- streamable-HTTP の単一セッションは、同時 in-flight POST のレスポンス対応付けに弱い (実装/仕様の境界)。ここでセッションが壊れると、以後そのクライアントの全呼び出しが `Session terminated`。

### 3.2 engine: recall のミューテーションにロックが無い
`gaottt/core/engine.py`

- `asyncio.Lock` / `self._lock` の grep が **engine.py で 0 ヒット**。recall (`query` → `_query_internal`, L841-) は複数の処理を跨いで `self.cache` / `self.faiss_index` / `self.virtual_faiss_index` を読み書きする。
- 非passive recall は後段で gravity field を perturb する (mass 更新 / displacement / co-occurrence)。passive はこれをスキップ (`query` docstring L884-890)。
- 背景の **virtual-FAISS リビルドは `asyncio.to_thread` で別スレッド実行** (`save` が L266/270/354/395、periodic rebuild が L360-401) され、recall の読み書きと**排他されていない** (dirty フラグの claim はあるが lock ではない)。
- **決定的な痕跡** (L877-882):
  > `gamma_override` … Lets `explore` widen the thermal noise **without monkey-patching the shared config across an await (which corrupted concurrent recalls)**.

  → **過去に「並列 recall が共有状態を壊す」バグを踏み、gamma の monkeypatch という1事例だけ個別修正した**ことを示す。全体を守るロックは導入されていない = 同種の地雷が他にも残っている可能性。

### 3.3 切り分け: 今回は passive 2件
今回クラッシュした2件は**両方 `passive=true`**。passive は §3.2 の perturbation 書き込みを行わない。したがって**今回の引き金はエンジンの状態破壊 (3.2) ではなくトランスポート層 (3.1) が濃厚**。ただし 3.2 は非passive並列 / 複数エージェントで独立に顕在化しうる別問題として残る。

---

## 4. 「キューイングが良いか?」→ はい (直列化が正しい)

ユーザーの直感どおり**直列化が正攻法**。どの層で直列化するかで効き方・工数・リスクが変わる。

| 案 | 内容 | 効く範囲 | 工数/リスク |
|---|---|---|---|
| **A. proxy ロック** | `mcp_proxy.py` の `call_tool` を `asyncio.Lock` で囲み 1セッション1 in-flight に | 今回のクラッシュ (同一エージェントの並列呼び) を直接解消 | ~5行 / 極小 |
| **B. engine RW ロック** | `engine.query` / writer を read-write lock で直列化 | 共有 backend を全エージェント横断で保護。§3.2 の地雷も封じる | 中 / 中 (粒度設計が必要) |
| **C. 両方** | A+B の多層防御 | 完全 | 中 / 中 |
| D. 直さない | クライアント側で「逐次呼び」運用 (現状) | 規律次第・破られうる | 0 |

### 案 A のスケッチ (proxy 層・最小)
```python
# gaottt/server/mcp_proxy.py
_call_lock = asyncio.Lock()

async def call_tool(req):
    async with _call_lock:                # 1セッション1 in-flight に直列化
        result = await upstream.call_tool(req.params.name, req.params.arguments or {})
    return types.ServerResult(result)
```
- `ping_loop` の `send_ping` も同じ `_call_lock` で保護すると、ping とツール呼びの同時 in-flight も無くせる。
- **限界**: これは「同一エージェント (= 同一 proxy/セッション) の並列呼び」を直す。**別エージェント同士の同時アクセス**は別 proxy = 別セッションなので backend で依然同時に当たり、§3.2 のエンジン地雷が残る → そこは案 B が必要。

### 案 B の注意点
- engine は単一プロセス asyncio。`query` 全体 (embedding + wave + scoring) を1本の lock で囲むと全 recall が直列化しレイテンシ増。実運用が単一〜少数エージェントなら許容範囲 (ops は ms〜低100ms)。
- 厳密にやるなら **read-write lock**: passive/読みは共有、perturbation/writer (remember, relate, merge, compact, 背景 FAISS rebuild) は排他。
- 背景 virtual-FAISS rebuild (`to_thread`) と search の競合を lock 化すると、§3.2 の潜在 segfault 経路も塞げる。

---

## 5. 再現手順

1. proxy モードで GaOTTT を起動 (= 既定の `.mcp.json` 構成)。
2. 1つのエージェントターンで `recall` を**2件以上並列**に発行 (passive/非passive どちらでも再現する可能性が高い; 今回は passive×2 で発生)。
3. 以後その接続の全 GaOTTT 呼び出しが `MCP error 32600: Session terminated`。
4. `/mcp` で gaottt を reconnect すると復旧。

> 注意: §3.2 の状態破壊だけを狙うなら **非passive recall × 2 並列** か、**recall と remember/merge を並列**にして field write を競合させると再現しやすいはず (未検証・要確認)。

---

## 6. 現状の回避策 (コード変更なし)

- **クライアント側で GaOTTT 呼び出しを並列化しない** (1ターン1 in-flight で逐次)。
  - 今回のセッションでは、remember / relate を**逐次**に切り替えて以降は無事に7件保存できた。
- 落ちた場合は `/mcp` → gaottt reconnect で復旧。

---

## 7. 確度と未確認事項

- **高確度**: proxy が単一セッションを無ロックで共有 (§3.1)、engine にミューテーション lock が無い (§3.2)、過去に並列 recall 状態破壊を個別修正した痕跡 (§3.2 の gamma コメント)。
- **中確度 (主仮説)**: 今回の `Session terminated` は streamable-HTTP セッションが同時 in-flight POST で壊れた現象。理由 = クラッシュ2件が passive で、エンジン状態書き込みを伴わないため。
- **未確認**:
  - エンジン側ハンドラ例外が session を巻き込んだ可能性 (vs 純トランスポート) の確定切り分け。再現環境でバックエンドログを取れば判別可能。
  - §3.2 の状態破壊が実害 (gravity field の数値破損) を出すか、出すならどのデータか。
  - MCP Python SDK の `ClientSession` / streamable-http が「1セッション同時リクエスト」を本来どこまでサポートするか (SDK 側の仕様確認)。

---

## 8. 次にやるなら (推奨アクション順)

1. **案 A (proxy ロック)** を入れて今回の症状を即封じる (最小・低リスク)。
2. 再現環境でバックエンドログを取り、トランスポート由来かエンジン例外由来かを確定。
3. 複数エージェント運用があるなら **案 B (engine RW ロック)** を追加し共有 backend を横断保護。
4. ついでに **背景 FAISS rebuild と search の排他** を lock 化し §3.2 の潜在 segfault 経路を塞ぐ。
5. ツールハンドラ全体を try/except で包み、1リクエストの例外が**セッションを終了させない** (JSON-RPC エラーで返す) ようハードニング。

---

## 付録: 参照ファイル / 行 (調査時 HEAD `f3f6ce3`)

- `gaottt/server/mcp_proxy.py` — `call_tool` 転送 L228-232 / 単一 upstream `ClientSession` L266-267 / `ping_loop` 共有 L184-200, L274 / `_build_proxy_server` L206
- `gaottt/server/mcp_server.py` — default transport `proxy` (argparse default) / idle-timeout 300s / engine シングルトン `get_engine` + 初期化専用 `_engine_lock` L52-73 / `recall` tool L228-324
- `gaottt/core/engine.py` — `query`/`_query_internal` L841- / passive 仕様 docstring L884-890 / 並列 recall 状態破壊の痕跡コメント L877-882 / FAISS save `to_thread` L266,270,354,395 / 背景 virtual rebuild L360-401 / perturbation 書き込み (`cache.set_displacement` 等) L797-802, L824-837
- `gaottt/services/memory.py` — `recall` サービス L274-
