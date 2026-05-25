#!/usr/bin/env python3
"""Phase A probe: RURI v3 310m vs RikkaBotan static bilingual.

Reads production DB (read-only) for realistic memo shapes, encodes them with
both embedders, prints a cos-sim heatmap for ambient-hook-shape queries.

See docs/wiki/Plans-Embedder-Comparison.md (Phase A Step A2).
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

PROD_DB = "file:/home/misaki_maihara/.local/share/gaottt/gaottt.db?mode=ro"

# ────────────────────────────────────────────────────────────────────────────
# Production memo fetch (read-only, content selected to match target queries)
# ────────────────────────────────────────────────────────────────────────────
DOC_QUERIES = {
    "agent_lms": (
        "SELECT id, content FROM documents "
        "WHERE json_extract(metadata, '$.source')='agent' "
        "  AND content LIKE '%[LMS-%' AND content LIKE '%マルチテナント%' LIMIT 1"
    ),
    "tweet_short": (
        # Pin the same tweet across runs by fixed id (2022-09-13 細胞膜 line)
        "SELECT id, content FROM documents WHERE id='46488d93-c5b8-43b4-9bb5-46f0aff0e60c'"
    ),
    "intention_phase_l": (
        "SELECT id, content FROM documents "
        "WHERE json_extract(metadata, '$.source')='intention' "
        "  AND content LIKE '%Phase L%' AND content LIKE '%embedder%' LIMIT 1"
    ),
    "value_articulation": (
        "SELECT id, content FROM documents "
        "WHERE json_extract(metadata, '$.source')='value' "
        "  AND content LIKE '%Articulation%' LIMIT 1"
    ),
    "agent_phase_m": (
        "SELECT id, content FROM documents "
        "WHERE json_extract(metadata, '$.source')='agent' "
        "  AND content LIKE '%カテゴリ C%' AND content LIKE '%Phase M%' LIMIT 1"
    ),
}

# Each query targets ONE doc by intent. (target, query) — ambient-hook shape.
QUERIES_JA = [
    ("agent_lms",          "LMS dev プロジェクトの記憶ってどこから探せばいい？"),
    ("tweet_short",        "暗い詩みたいなツイートを書いてた時期ある？"),
    ("intention_phase_l",  "Phase L の着手理由は何だっけ、embedder の限界の話"),
    ("value_articulation", "Articulation as Carrier ってどういう意味だっけ"),
    ("agent_phase_m",      "Phase M の単一規則と Phase N-β の対称命題について"),
]

# Cross-lingual probe: same intent in English. RURI should fail, RikkaBotan should hit.
QUERIES_EN = [
    ("intention_phase_l",  "Why did we start Phase L? The embedder ranking limitation"),
    ("value_articulation", "What does 'Articulation as Carrier' mean in our system"),
    ("agent_phase_m",      "Summary of Phase M single rule and Phase N-beta symmetric proposition"),
]


def fetch_docs() -> dict[str, tuple[str, str]]:
    """Returns {slug: (doc_id, content)}."""
    db = sqlite3.connect(PROD_DB, uri=True)
    db.row_factory = sqlite3.Row
    out = {}
    for slug, sql in DOC_QUERIES.items():
        rows = list(db.execute(sql))
        if not rows:
            print(f"WARN: no match for {slug}", file=sys.stderr)
            continue
        out[slug] = (rows[0]["id"], rows[0]["content"])
    db.close()
    return out


def encode_ruri(texts_q: list[str], texts_d: list[str]) -> tuple[np.ndarray, np.ndarray, float]:
    from gaottt.embedding.ruri import RuriEmbedder
    t0 = time.time()
    e = RuriEmbedder()
    load_time = time.time() - t0
    q = e.encode_queries(texts_q)
    d = e.encode_documents(texts_d)
    return q, d, load_time


def encode_rikka(texts_q: list[str], texts_d: list[str], dim: int | None = None) -> tuple[np.ndarray, np.ndarray, float]:
    """RikkaBotan: no prefix; optionally truncate to `dim` (MRL) and re-normalize."""
    from sentence_transformers import SentenceTransformer
    t0 = time.time()
    model = SentenceTransformer(
        "RikkaBotan/quantized-stable-static-embedding-fast-retrieval-mrl-bilingual-ja-en",
        trust_remote_code=True,
        device="cpu",
    )
    load_time = time.time() - t0
    q = model.encode(texts_q, normalize_embeddings=True, convert_to_numpy=True, batch_size=32)
    d = model.encode(texts_d, normalize_embeddings=True, convert_to_numpy=True, batch_size=32)
    if dim is not None and dim < q.shape[1]:
        q = q[:, :dim]
        d = d[:, :dim]
        # Re-normalize after MRL truncate
        q = q / np.linalg.norm(q, axis=1, keepdims=True)
        d = d / np.linalg.norm(d, axis=1, keepdims=True)
    return q.astype(np.float32), d.astype(np.float32), load_time


def print_heatmap(title: str, queries: list[tuple[str, str]], doc_slugs: list[str], sims: np.ndarray, judge_top1: bool = True) -> int:
    """Print sim matrix + judge top-1 against intended target. Returns hits."""
    print(f"\n=== {title} ===")
    header = " " * 30 + " | " + " | ".join(f"{s[:14]:>14}" for s in doc_slugs)
    print(header)
    print("-" * len(header))
    hits = 0
    for i, (target, qtext) in enumerate(queries):
        row_sims = sims[i]
        top1_idx = int(np.argmax(row_sims))
        top1_slug = doc_slugs[top1_idx]
        hit = top1_slug == target
        if hit:
            hits += 1
        marker = "✓" if hit else "✗"
        cells = []
        for j, s in enumerate(row_sims):
            is_target = doc_slugs[j] == target
            is_top1 = j == top1_idx
            if is_target and is_top1:
                cells.append(f"\033[1;32m{s:+.4f}\033[0m".rjust(14 + 9))  # green bold
            elif is_target:
                cells.append(f"\033[33m{s:+.4f}\033[0m".rjust(14 + 9))    # yellow (target missed)
            elif is_top1:
                cells.append(f"\033[31m{s:+.4f}\033[0m".rjust(14 + 9))    # red (false top1)
            else:
                cells.append(f"{s:+.4f}".rjust(14))
        print(f"{marker} {qtext[:28]:<28} | " + " | ".join(cells))
    print(f"  → top-1 hit rate: {hits}/{len(queries)}")
    return hits


def run(rikka_dim: int | None = None) -> None:
    docs = fetch_docs()
    doc_slugs = list(docs.keys())
    doc_texts = [docs[s][1] for s in doc_slugs]

    print(f"\n📚 Production docs ({len(docs)}):")
    for slug in doc_slugs:
        doc_id, text = docs[slug]
        print(f"  {slug:25} id={doc_id[:8]}  len={len(text):4}  '{text[:50]}...'")

    all_queries = QUERIES_JA + QUERIES_EN
    qtexts = [q for _, q in all_queries]

    # ── RURI ────────────────────────────────────────
    print("\n🟦 Loading RURI v3 310m ...")
    q_ruri, d_ruri, ruri_load = encode_ruri(qtexts, doc_texts)
    print(f"  loaded in {ruri_load:.1f}s, q.shape={q_ruri.shape}, d.shape={d_ruri.shape}")
    sims_ruri = q_ruri @ d_ruri.T  # (n_q, n_d)

    # ── RikkaBotan ──────────────────────────────────
    dim_label = f"RikkaBotan ({rikka_dim or 'native 512'}d)"
    print(f"\n🟩 Loading {dim_label} ...")
    q_rik, d_rik, rik_load = encode_rikka(qtexts, doc_texts, dim=rikka_dim)
    print(f"  loaded in {rik_load:.1f}s, q.shape={q_rik.shape}, d.shape={d_rik.shape}")
    sims_rik = q_rik @ d_rik.T

    # ── Side-by-side heatmaps ───────────────────────
    n_ja = len(QUERIES_JA)
    hits_ja_ruri = print_heatmap(
        "RURI 768d — JA queries (monolingual)",
        QUERIES_JA, doc_slugs, sims_ruri[:n_ja],
    )
    hits_ja_rik = print_heatmap(
        f"{dim_label} — JA queries (monolingual)",
        QUERIES_JA, doc_slugs, sims_rik[:n_ja],
    )
    hits_en_ruri = print_heatmap(
        "RURI 768d — EN queries (cross-lingual)",
        QUERIES_EN, doc_slugs, sims_ruri[n_ja:],
    )
    hits_en_rik = print_heatmap(
        f"{dim_label} — EN queries (cross-lingual)",
        QUERIES_EN, doc_slugs, sims_rik[n_ja:],
    )

    print("\n" + "=" * 70)
    print("📊 A2 結果サマリ")
    print("=" * 70)
    print(f"  JA→JA top-1: RURI {hits_ja_ruri}/{n_ja}   |   {dim_label} {hits_ja_rik}/{n_ja}")
    print(f"  EN→JA top-1: RURI {hits_en_ruri}/{len(QUERIES_EN)}   |   {dim_label} {hits_en_rik}/{len(QUERIES_EN)}")
    print("\n  H1 判定 (EN→JA cross-lingual, target ≥2/3):")
    print(f"    RikkaBotan {hits_en_rik}/{len(QUERIES_EN)} → "
          f"{'✅ PASS' if hits_en_rik >= 2 else '❌ FAIL'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dim", type=int, default=None, help="MRL truncate dim for RikkaBotan (256/512); default native")
    args = ap.parse_args()
    run(rikka_dim=args.dim)
