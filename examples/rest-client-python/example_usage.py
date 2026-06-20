"""End-to-end demo of the GaOTTT REST client.

Run a local server first (isolated /tmp DB):

    bash examples/rest-client-python/run_local_server.sh

then in another terminal:

    .venv/bin/python examples/rest-client-python/example_usage.py

The script walks through six realistic patterns:

  1. Remember + recall round-trip
  2. Bulk index from your own content
  3. Tag filter + source filter
  4. Relations (supersedes) + relation traversal
  5. Reflect / summary / hot topics
  6. Maintenance: forget -> restore round-trip

Each step prints what it did. Safe to re-run (duplicates are dedup'd
server-side).
"""

from __future__ import annotations

import os
import sys
import textwrap
import time
from pathlib import Path

# Allow running this file directly (python example_usage.py) by adding the
# script dir to sys.path so we can import the sibling gaottt_client module.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx

from gaottt_client import GaOTTTClient, GaOTTTError  # noqa: E402

GAOTTT_URL = os.environ.get("GAOTTT_URL", "http://localhost:8001")


def hr() -> None:
    print("\n" + "=" * 72)


def step(n: int, title: str) -> None:
    hr()
    print(f"[{n}] {title}")


def show_recalls(items: list[dict], limit: int = 3) -> None:
    for i, it in enumerate(items[:limit], 1):
        score = it.get("final_score", it.get("raw_score", 0.0))
        content = it.get("content", "").replace("\n", " ")[:80]
        tags = it.get("tags", [])
        print(f"  {i}. score={score:.3f}  tags={tags}  {content}")
    if len(items) > limit:
        print(f"  ... ({len(items) - limit} more)")


def main() -> None:
    print(f"Connecting to {GAOTTT_URL}")
    client = GaOTTTClient(GAOTTT_URL)

    # --- sanity check ---
    # The server being unreachable raises httpx.RequestError (ConnectError,
    # TimeoutException, ...) — NOT GaOTTTError, which only wraps non-2xx
    # responses. Catch both so new users see the friendly hint instead of
    # a traceback when they forget to start the server.
    try:
        s = client.summary()
    except (GaOTTTError, httpx.RequestError) as e:
        print(f"ERROR: cannot reach GaOTTT server at {GAOTTT_URL}: {e}")
        print("Start one with: bash examples/rest-client-python/run_local_server.sh")
        sys.exit(2)
    print(f"Connected. active_memories={s.get('active_memories', '?')}")

    # ------------------------------------------------------------------
    step(1, "remember() + recall() — round-trip")
    # ------------------------------------------------------------------
    # NOTE: New memory + immediate recall works because Phase G Stage 1
    # genesis kick gives fresh nodes enough mass to surface without anchor
    # phrases (see CLAUDE.md). The recall also perturbs the gravity field
    # (mass bump + query-attraction displacement), which is the TTT signal.
    res = client.remember(
        "Our deploy script is scripts/deploy.sh. It runs gh release upload "
        "after building the wheel.",
        source="agent",
        tags=["infra", "deploy"],
        context="example_usage.py step 1",
    )
    print(f"  remembered: id={res.get('id')}  duplicate={res.get('duplicate')}")

    hits = client.recall("how do we publish a release?", top_k=3)
    print(f"  recall() returned {hits['count']} hits")
    show_recalls(hits.get("items", []))

    # ------------------------------------------------------------------
    step(2, "index() — bulk insert pre-chunked docs")
    # ------------------------------------------------------------------
    # /index is the right call when you already have content in your app
    # (scraped docs, tickets, code comments) and want to push it in bulk.
    # /ingest by contrast takes a *server-side path*, which is wrong for
    # remote clients — use /index for app-driven content.
    docs = [
        {
            "content": "Runbook: when the API returns 502, check backend health "
                       "endpoint (/healthz) and the load balancer's threshold. "
                       "Lowering threshold from 5 to 3 fixed incident #142.",
            "metadata": {
                "source": "file",
                "tags": ["runbook", "incident"],
                "original_id": "runbook.md",   # groups these chunks for
                                                # Phase M self-force filtering
            },
        },
        {
            "content": "Runbook: database migrations run via `alembic upgrade "
                       "head`. Always back up prod DB first (pg_dump).",
            "metadata": {
                "source": "file",
                "tags": ["runbook", "db"],
                "original_id": "runbook.md",
            },
        },
        {
            "content": "Architecture: we use FastAPI + uvicorn behind Caddy. "
                       "Caddy does auto-TLS and basic auth; FastAPI serves "
                       "the app.",
            "metadata": {
                "source": "file",
                "tags": ["architecture"],
                "original_id": "architecture.md",
            },
        },
    ]
    idx = client.index(docs)
    print(f"  indexed={idx['count']}  skipped={idx.get('skipped', 0)}")
    # Small wait so the gravity field has a chance to settle (genesis kick
    # + initial displacement). 0.5s is plenty for this small batch.
    time.sleep(0.5)

    hits = client.recall("502 gateway error", top_k=3)
    print(f"  recall('502 gateway error') -> {hits['count']} hits")
    show_recalls(hits.get("items", []))

    # ------------------------------------------------------------------
    step(3, "tag_filter / source_filter — scoped retrieval")
    # ------------------------------------------------------------------
    # Use tags to keep your retrieval surgical: 'just my runbook notes',
    # 'just incidents', etc.
    hits = client.recall("deploy", top_k=5, tag_filter=["runbook"])
    print(f"  recall(tag_filter=['runbook']) -> {hits['count']} hits")
    show_recalls(hits.get("items", []))

    hits = client.recall("deploy", top_k=5, source_filter=["agent"])
    print(f"  recall(source_filter=['agent']) -> {hits['count']} hits")
    show_recalls(hits.get("items", []))

    # ------------------------------------------------------------------
    step(4, "relate() — knowledge revision (supersedes)")
    # ------------------------------------------------------------------
    # The supersedes edge is how GaOTTT tracks "this conclusion replaces
    # that older one". Use it whenever you revise a judgment.
    old = client.remember(
        "Threshold of 5 is fine for health checks.",
        source="agent", tags=["incident", "obsolete"],
    )
    new = client.remember(
        "Threshold of 5 was too aggressive; we lowered to 3 in incident #142.",
        source="agent", tags=["incident", "current"],
    )
    if old.get("id") and new.get("id"):
        client.relate(new["id"], old["id"], "supersedes",
                      metadata={"reason": "post-incident revision"})
        print(f"  {new['id']}  --supersedes-->  {old['id']}")
        rels = client.get_relations(new["id"], direction="out")
        print(f"  outgoing relations: {rels}")

    # ------------------------------------------------------------------
    step(5, "reflect() — observe the space")
    # ------------------------------------------------------------------
    summary = client.summary()
    print("  summary:")
    print(textwrap.indent(
        "\n".join(f"{k}: {v}" for k, v in summary.items()
                  if not isinstance(v, (list, dict))),
        "    ",
    ))
    if summary.get("sources"):
        print(f"    sources: {summary['sources']}")

    hot = client.hot_topics(limit=5)
    items = hot.get("items", [])
    print(f"  hot_topics (top {len(items)}):")
    for it in items[:5]:
        preview = (it.get("content_preview") or "").replace("\n", " ")[:60]
        mass = it.get("mass", 0.0)
        print(f"    mass={mass:.2f}  {preview}")

    # ------------------------------------------------------------------
    step(6, "forget() + restore() — soft archive round-trip")
    # ------------------------------------------------------------------
    ephemeral = client.remember(
        "Temporary scratch note for example_usage.py — will be forgotten.",
        source="hypothesis",  # hypothesis source has a TTL by default
        tags=["scratch"],
    )
    nid = ephemeral.get("id")
    if nid:
        print(f"  created ephemeral node: {nid}")
        print(f"  forget([nid]) -> {client.forget([nid])}")
        # recall should no longer surface it
        hits = client.recall("Temporary scratch note", top_k=5)
        ids = [i.get("id") for i in hits.get("items", [])]
        print(f"  recall() ids after forget: {ids}  (expected: {nid} not in list)")
        # restore reverses it
        print(f"  restore([nid]) -> {client.restore([nid])}")

    hr()
    print("Done. Inspect the full state at:")
    print(f"  {GAOTTT_URL}/docs       (Swagger UI)")
    print(f"  {GAOTTT_URL}/reflect/summary  (POST with empty body)")


if __name__ == "__main__":
    main()
