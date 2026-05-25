#!/usr/bin/env python3
"""Phase A Step A2.2 — Pure cross-lingual probe.

The earlier A2 test was contaminated: JA production docs contain English jargon
(Phase L, embedder, RURI, ...), and the EN queries shared those tokens with
the JA docs, so both embedders could match via substring overlap rather than
true cross-lingual semantics.

This script isolates true cross-lingual ability:
  - JA docs: 5 tweets (prefix stripped) with ZERO Latin/digit characters
  - JA queries: paraphrase of each doc's theme in JA (control)
  - EN queries: pure semantic paraphrase in English, ZERO shared substrings

RURI is JA-specialized, no cross-lingual ability claimed → expect EN→JA fail.
RikkaBotan is JA-EN bilingual → expect EN→JA success.

If RikkaBotan still fails on the pure test, its cross-lingual claim doesn't
materialize for our use case, and Phase C has no premise.

See docs/wiki/Plans-Embedder-Comparison.md.
"""
from __future__ import annotations

import re
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

PROD_DB = "file:/home/misaki_maihara/.local/share/gaottt/gaottt.db?mode=ro"

# ────────────────────────────────────────────────────────────────────────────
# Pure-JA tweet fixtures (prefix stripped). Each ID + JA query + EN query.
# Picked for distinct topics and zero Latin/digit shared substrings.
# ────────────────────────────────────────────────────────────────────────────
TWEET_IDS = {
    "quantum_skeptic":   "f66d5087-8df6-4872-95bd-09fb69ac1a67",  # 量子なんちゃら医学への懐疑
    "spam_lament":       "ac01abae-2ff0-46ab-b1b0-9e487a1cb28d",  # 侍魂時代からのネット文化の嘆き
    "sleep_together":    "523eab52-ab03-464b-b4ed-71fb62ad5396",  # 一緒に寝ようね (占い起点)
    "fear_overcome":     "b49def17-ca05-428e-aa27-99dcca152441",  # 恐怖の壁を超える、強くなれる
    "morning_grey":      "520b9dc1-8afa-4fa7-9aca-1dcfbec5a1ce",  # 灰色の雲と太陽の光、朝の挨拶
}

# (target_slug, JA paraphrase query) — for control, JA→JA must hit
QUERIES_JA = [
    ("quantum_skeptic", "わかりやすく書かれた疑似科学への懐疑のツイート"),
    ("spam_lament",     "昔のインターネット文化の終わりを嘆くツイート"),
    ("sleep_together",  "皆で寝ようと呼びかけるツイート"),
    ("fear_overcome",   "恐怖を乗り越えて強くなれるという自己肯定のツイート"),
    ("morning_grey",    "曇り空の中の朝の挨拶と太陽の光のツイート"),
]

# (target_slug, EN paraphrase query) — pure semantic, zero shared substring
QUERIES_EN = [
    ("quantum_skeptic", "Tweet expressing skepticism about pseudoscientific medicine"),
    ("spam_lament",     "Tweet lamenting the decline of early internet culture"),
    ("sleep_together",  "Tweet inviting everyone to go to sleep"),
    ("fear_overcome",   "Tweet about overcoming fear and growing stronger"),
    ("morning_grey",    "Tweet greeting a cloudy morning with sunlight"),
]


def strip_tweet_prefix(s: str) -> str:
    return re.sub(r'^\[(Tweet|\d+/\d+, liked)[^\]]*\]\s*\n?', '', s).strip()


def fetch_docs() -> dict[str, tuple[str, str]]:
    """Returns {slug: (doc_id, body_text_no_prefix)}."""
    db = sqlite3.connect(PROD_DB, uri=True)
    db.row_factory = sqlite3.Row
    out = {}
    for slug, doc_id in TWEET_IDS.items():
        row = db.execute("SELECT id, content FROM documents WHERE id=?", (doc_id,)).fetchone()
        if row is None:
            print(f"WARN: missing {slug} ({doc_id[:8]})", file=sys.stderr)
            continue
        body = strip_tweet_prefix(row["content"])
        # Sanity: assert no Latin/digit in body
        if re.search(r'[A-Za-z0-9]', body):
            print(f"WARN: {slug} body still has Latin/digit: {body[:50]!r}", file=sys.stderr)
        out[slug] = (row["id"], body)
    db.close()
    return out


def encode_ruri(qs: list[str], ds: list[str]) -> tuple[np.ndarray, np.ndarray]:
    from gaottt.embedding.ruri import RuriEmbedder
    e = RuriEmbedder()
    return e.encode_queries(qs), e.encode_documents(ds)


def _encode_with(model_name: str, qs: list[str], ds: list[str]) -> tuple[np.ndarray, np.ndarray]:
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(model_name, trust_remote_code=True, device="cpu")
    q = model.encode(qs, normalize_embeddings=True, convert_to_numpy=True, batch_size=32)
    d = model.encode(ds, normalize_embeddings=True, convert_to_numpy=True, batch_size=32)
    return q.astype(np.float32), d.astype(np.float32)


def encode_rikka_q(qs: list[str], ds: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """Quantized variant (SSEQ module)."""
    return _encode_with(
        "RikkaBotan/quantized-stable-static-embedding-fast-retrieval-mrl-bilingual-ja-en", qs, ds,
    )


def encode_rikka_fp32(qs: list[str], ds: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """Non-quantized variant (SSE module) — isolates whether quantization
    is the cause of low discriminative power."""
    return _encode_with(
        "RikkaBotan/stable-static-embedding-fast-retrieval-mrl-bilingual-ja-en", qs, ds,
    )


def heatmap(title: str, queries: list[tuple[str, str]], slugs: list[str], sims: np.ndarray) -> int:
    print(f"\n=== {title} ===")
    head = " " * 35 + " | " + " | ".join(f"{s[:14]:>14}" for s in slugs)
    print(head)
    print("-" * len(head))
    hits = 0
    for i, (target, qtext) in enumerate(queries):
        row = sims[i]
        top1 = int(np.argmax(row))
        ok = slugs[top1] == target
        if ok:
            hits += 1
        mark = "✓" if ok else "✗"
        cells = []
        for j, s in enumerate(row):
            is_t = slugs[j] == target
            is_top = j == top1
            if is_t and is_top:
                cells.append(f"\033[1;32m{s:+.4f}\033[0m".rjust(23))
            elif is_t:
                cells.append(f"\033[33m{s:+.4f}\033[0m".rjust(23))
            elif is_top:
                cells.append(f"\033[31m{s:+.4f}\033[0m".rjust(23))
            else:
                cells.append(f"{s:+.4f}".rjust(14))
        q_short = (qtext[:33] + "..") if len(qtext) > 33 else qtext
        print(f"{mark} {q_short:<33} | " + " | ".join(cells))
    print(f"  → top-1 hit rate: {hits}/{len(queries)}")
    return hits


def run() -> None:
    docs = fetch_docs()
    slugs = list(docs.keys())
    if len(slugs) != 5:
        print(f"ERROR: only {len(slugs)} docs found, need 5", file=sys.stderr)
        sys.exit(1)

    print("\n📚 Pure-JA fixture docs (prefix stripped, no Latin/digit):")
    for slug in slugs:
        doc_id, body = docs[slug]
        print(f"  {slug:18}  id={doc_id[:8]}  len={len(body):3}")
        print(f"    {body[:140]!r}")

    all_q = QUERIES_JA + QUERIES_EN
    qtexts = [q for _, q in all_q]
    dtexts = [docs[s][1] for s in slugs]

    print("\n🟦 RURI v3 310m encoding ...")
    t0 = time.time()
    q_r, d_r = encode_ruri(qtexts, dtexts)
    print(f"  done in {time.time()-t0:.1f}s, q={q_r.shape}, d={d_r.shape}")
    sims_r = q_r @ d_r.T

    print("\n🟧 RikkaBotan fp32 512d encoding (non-quantized) ...")
    t0 = time.time()
    q_f, d_f = encode_rikka_fp32(qtexts, dtexts)
    print(f"  done in {time.time()-t0:.1f}s, q={q_f.shape}, d={d_f.shape}")
    sims_f = q_f @ d_f.T

    print("\n🟩 RikkaBotan quantized 512d encoding ...")
    t0 = time.time()
    q_k, d_k = encode_rikka_q(qtexts, dtexts)
    print(f"  done in {time.time()-t0:.1f}s, q={q_k.shape}, d={d_k.shape}")
    sims_k = q_k @ d_k.T

    n_ja = len(QUERIES_JA)
    h_ja_r = heatmap("RURI 768d — JA control (JA→JA)", QUERIES_JA, slugs, sims_r[:n_ja])
    h_ja_f = heatmap("RikkaBotan fp32 512d — JA control (JA→JA)", QUERIES_JA, slugs, sims_f[:n_ja])
    h_ja_k = heatmap("RikkaBotan quantized 512d — JA control (JA→JA)", QUERIES_JA, slugs, sims_k[:n_ja])
    h_en_r = heatmap("RURI 768d — EN test (EN→JA, pure cross-lingual)", QUERIES_EN, slugs, sims_r[n_ja:])
    h_en_f = heatmap("RikkaBotan fp32 512d — EN test (EN→JA, pure cross-lingual)", QUERIES_EN, slugs, sims_f[n_ja:])
    h_en_k = heatmap("RikkaBotan quantized 512d — EN test (EN→JA, pure cross-lingual)", QUERIES_EN, slugs, sims_k[n_ja:])

    print("\n" + "=" * 80)
    print("📊 A2.2 Pure cross-lingual 結果 (3-way 比較)")
    print("=" * 80)
    print(f"                          RURI 768d  | fp32 512d  | quantized 512d")
    print(f"  JA→JA control top1:    {h_ja_r}/{n_ja}        | {h_ja_f}/{n_ja}        | {h_ja_k}/{n_ja}")
    print(f"  EN→JA pure cross top1: {h_en_r}/{len(QUERIES_EN)}        | {h_en_f}/{len(QUERIES_EN)}        | {h_en_k}/{len(QUERIES_EN)}")
    print()
    # quantization の影響を診断
    if h_ja_f > h_ja_k or h_en_f > h_en_k:
        print(f"  🔍 quantization は discriminative power を下げている (fp32 が quantized より良い)")
    elif h_ja_f == h_ja_k and h_en_f == h_en_k:
        print(f"  🔍 quantization は score に影響なし (static 構造そのものの限界)")
    # RURI vs fp32 (best RikkaBotan) で総合判定
    best_rikka_ja, best_rikka_en = max(h_ja_f, h_ja_k), max(h_en_f, h_en_k)
    if best_rikka_en > h_en_r and best_rikka_ja >= h_ja_r:
        print(f"  ✅ RikkaBotan (best) が RURI を超える — Phase B 進行に値する")
    elif best_rikka_en == h_en_r and best_rikka_ja == h_ja_r:
        print(f"  ⚠️ RikkaBotan (best) は RURI 同点 — cross-lingual 利点なし、Phase B 進行根拠薄い")
    else:
        print(f"  ❌ RikkaBotan (best) は RURI に劣る — Phase B 進行根拠なし")


if __name__ == "__main__":
    run()
