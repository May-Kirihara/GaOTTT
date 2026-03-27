"""Run test queries against GER-RAG and display results.

Usage:
    python scripts/test_queries.py [--url URL]
"""

from __future__ import annotations

import argparse
import json

import httpx

DEFAULT_URL = "http://localhost:8000"

TEST_QUERIES = [
    "人工知能と機械学習について",
    "映画やアニメの感想",
    "プログラミングや技術的な話題",
    "日常の面白い出来事",
    "紅茶や食べ物の話",
]


def query(client: httpx.Client, url: str, text: str, top_k: int = 5) -> dict:
    resp = client.post(f"{url}/query", json={"text": text, "top_k": top_k}, timeout=60.0)
    resp.raise_for_status()
    return resp.json()


def show_node(client: httpx.Client, url: str, node_id: str) -> None:
    resp = client.get(f"{url}/node/{node_id}", timeout=10.0)
    if resp.status_code == 200:
        data = resp.json()
        print(f"    Node: mass={data['mass']:.3f}, temp={data['temperature']:.4f}, "
              f"history_len={len(data['sim_history'])}")


def show_graph(client: httpx.Client, url: str) -> None:
    resp = client.get(f"{url}/graph?min_weight=1.0", timeout=10.0)
    if resp.status_code == 200:
        data = resp.json()
        print(f"\nCo-occurrence graph: {data['count']} edges (weight >= 1.0)")
        for edge in data["edges"][:10]:
            print(f"  {edge['src'][:8]}... <-> {edge['dst'][:8]}... weight={edge['weight']:.1f}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--rounds", type=int, default=2, help="Query rounds to show dynamic behavior")
    args = parser.parse_args()

    with httpx.Client() as client:
        for round_num in range(1, args.rounds + 1):
            print(f"\n{'='*60}")
            print(f"Round {round_num}")
            print(f"{'='*60}")

            for q in TEST_QUERIES:
                print(f"\nQuery: {q}")
                result = query(client, args.url, q, args.top_k)
                print(f"  Results: {result['count']}")
                for i, r in enumerate(result["results"][:3]):
                    content_preview = r["content"][:80].replace("\n", " ")
                    print(f"  [{i+1}] score={r['final_score']:.4f} (raw={r['raw_score']:.4f})")
                    print(f"      {content_preview}...")
                    if round_num == args.rounds and i == 0:
                        show_node(client, args.url, r["id"])

        show_graph(client, args.url)

        # Show dynamic behavior
        print(f"\n{'='*60}")
        print("Dynamic behavior check: re-querying first topic")
        print(f"{'='*60}")
        result = query(client, args.url, TEST_QUERIES[0], 3)
        for r in result["results"]:
            content_preview = r["content"][:60].replace("\n", " ")
            print(f"  score={r['final_score']:.4f} (raw={r['raw_score']:.4f}) | {content_preview}...")
            show_node(client, args.url, r["id"])


if __name__ == "__main__":
    main()
