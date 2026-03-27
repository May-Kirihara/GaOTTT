"""GER-RAG 3D Visualization Demo

ドキュメントのembeddingを3Dに次元削減し、動的状態（mass, temperature, decay）を
インタラクティブに可視化する。実行ごとにノードの見た目が変わる。

Usage:
    python scripts/visualize_3d.py [--method pca|umap] [--open]

サーバー停止中でも実行可能（DB + FAISSファイルを直接読む）。
"""

from __future__ import annotations

import argparse
import asyncio
import math
import time

import numpy as np
import plotly.graph_objects as go

from ger_rag.config import GERConfig
from ger_rag.index.faiss_index import FaissIndex
from ger_rag.store.sqlite_store import SqliteStore


def reduce_to_3d(vectors: np.ndarray, method: str = "pca") -> np.ndarray:
    if method == "umap":
        import umap
        reducer = umap.UMAP(n_components=3, n_neighbors=15, min_dist=0.1, metric="cosine")
        return reducer.fit_transform(vectors)
    else:
        from sklearn.decomposition import PCA
        pca = PCA(n_components=3)
        return pca.fit_transform(vectors)


async def load_data(config: GERConfig):
    # Load FAISS index
    faiss_index = FaissIndex(dimension=config.embedding_dim)
    faiss_index.load(config.faiss_index_path)

    if faiss_index.size == 0:
        print("ERROR: FAISSインデックスが空です。先にドキュメントを投入してください。")
        raise SystemExit(1)

    # Extract raw vectors from FAISS
    import faiss
    vectors = faiss.rev_swig_ptr(faiss_index._index.get_xb(), faiss_index.size * config.embedding_dim)
    vectors = np.array(vectors).reshape(faiss_index.size, config.embedding_dim).copy()
    ids = list(faiss_index._id_map)

    # Load node states from SQLite
    store = SqliteStore(db_path=config.db_path)
    await store.initialize()
    states = await store.get_all_node_states()
    state_map = {s.id: s for s in states}

    # Load documents for hover text
    doc_map = {}
    for node_id in ids:
        doc = await store.get_document(node_id)
        if doc:
            doc_map[node_id] = doc

    # Load edges
    edges = await store.get_all_edges()
    await store.close()

    return vectors, ids, state_map, doc_map, edges


def build_figure(
    coords_3d: np.ndarray,
    ids: list[str],
    state_map: dict,
    doc_map: dict,
    edges: list,
    config: GERConfig,
) -> go.Figure:
    now = time.time()

    # Compute visual properties from dynamic state
    masses = []
    temperatures = []
    decays = []
    hover_texts = []
    sources = []

    for i, node_id in enumerate(ids):
        state = state_map.get(node_id)
        mass = state.mass if state else 1.0
        temp = state.temperature if state else 0.0
        last_access = state.last_access if state else now
        decay_val = math.exp(-config.delta * (now - last_access))

        masses.append(mass)
        temperatures.append(temp)
        decays.append(decay_val)

        doc = doc_map.get(node_id, {})
        content = doc.get("content", "")[:100].replace("\n", " ")
        meta = doc.get("metadata", {}) or {}
        source = meta.get("source", "unknown")
        sources.append(source)

        hover_texts.append(
            f"<b>{content}...</b><br>"
            f"ID: {node_id[:8]}...<br>"
            f"Source: {source}<br>"
            f"Mass: {mass:.2f}<br>"
            f"Temperature: {temp:.4f}<br>"
            f"Decay: {decay_val:.4f}<br>"
            f"History: {len(state.sim_history) if state else 0} entries"
        )

    masses = np.array(masses)
    temperatures = np.array(temperatures)
    decays = np.array(decays)

    # Node size: proportional to mass (range 3-20)
    size_min, size_max = 3, 20
    if masses.max() > masses.min():
        sizes = size_min + (masses - masses.min()) / (masses.max() - masses.min()) * (size_max - size_min)
    else:
        sizes = np.full_like(masses, 6)

    # Node opacity: proportional to decay (0.2 - 1.0)
    opacities = 0.2 + 0.8 * decays

    # Color by source
    source_colors = {
        "tweet": "#1DA1F2",
        "like": "#E0245E",
        "note_tweet": "#17BF63",
        "unknown": "#888888",
    }

    fig = go.Figure()

    # Plot edges first (behind nodes)
    if edges:
        id_to_idx = {nid: i for i, nid in enumerate(ids)}
        edge_x, edge_y, edge_z = [], [], []
        for edge in edges:
            if edge.src in id_to_idx and edge.dst in id_to_idx:
                i, j = id_to_idx[edge.src], id_to_idx[edge.dst]
                edge_x.extend([coords_3d[i, 0], coords_3d[j, 0], None])
                edge_y.extend([coords_3d[i, 1], coords_3d[j, 1], None])
                edge_z.extend([coords_3d[i, 2], coords_3d[j, 2], None])

        if edge_x:
            fig.add_trace(go.Scatter3d(
                x=edge_x, y=edge_y, z=edge_z,
                mode="lines",
                line=dict(color="rgba(200,200,200,0.3)", width=1),
                hoverinfo="skip",
                name="Co-occurrence edges",
            ))

    # Plot nodes by source
    unique_sources = sorted(set(sources))
    for source in unique_sources:
        mask = [s == source for s in sources]
        indices = [i for i, m in enumerate(mask) if m]
        if not indices:
            continue

        color = source_colors.get(source, "#888888")

        # Encode decay (opacity) and temperature (orange shift) into RGBA color per node
        node_colors = []
        for i in indices:
            opacity = float(opacities[i])
            t_blend = min(1.0, temperatures[i] * 100)
            # Parse base color hex to RGB
            r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
            # Blend towards orange (255,165,0) when hot
            r = int(r + (255 - r) * t_blend)
            g = int(g + (165 - g) * t_blend)
            b = int(b * (1 - t_blend))
            node_colors.append(f"rgba({r},{g},{b},{opacity:.2f})")

        fig.add_trace(go.Scatter3d(
            x=coords_3d[indices, 0],
            y=coords_3d[indices, 1],
            z=coords_3d[indices, 2],
            mode="markers",
            marker=dict(
                size=[float(sizes[i]) for i in indices],
                color=node_colors,
            ),
            text=[hover_texts[i] for i in indices],
            hoverinfo="text",
            name=f"{source} ({len(indices)})",
        ))

    # Summary stats
    active_nodes = sum(1 for d in decays if d > 0.5)
    high_mass = sum(1 for m in masses if m > 2.0)
    hot_nodes = sum(1 for t in temperatures if t > 0.001)

    fig.update_layout(
        title=dict(
            text=(
                f"GER-RAG 3D Visualization<br>"
                f"<sub>{len(ids)} nodes | "
                f"{len(edges)} edges | "
                f"Active(decay>0.5): {active_nodes} | "
                f"High mass(>2.0): {high_mass} | "
                f"Hot(temp>0.001): {hot_nodes}</sub>"
            ),
        ),
        scene=dict(
            xaxis_title="Dim 1",
            yaxis_title="Dim 2",
            zaxis_title="Dim 3",
            bgcolor="rgb(20,20,30)",
        ),
        paper_bgcolor="rgb(20,20,30)",
        font=dict(color="white"),
        legend=dict(
            bgcolor="rgba(0,0,0,0.5)",
            font=dict(color="white"),
        ),
        margin=dict(l=0, r=0, t=80, b=0),
        width=1400,
        height=900,
    )

    # Add annotation for visual encoding
    fig.add_annotation(
        text=(
            "Size = Mass (重要度) | "
            "Opacity = Decay (鮮度) | "
            "Orange border = Temperature (変動性)"
        ),
        xref="paper", yref="paper",
        x=0.5, y=-0.02,
        showarrow=False,
        font=dict(size=12, color="gray"),
    )

    return fig


def main():
    parser = argparse.ArgumentParser(description="GER-RAG 3D Visualization")
    parser.add_argument(
        "--method", choices=["pca", "umap"], default="pca",
        help="Dimensionality reduction method (default: pca)",
    )
    parser.add_argument("--open", action="store_true", help="Open in browser automatically")
    parser.add_argument("--output", default="ger_rag_3d.html", help="Output HTML file")
    parser.add_argument("--sample", type=int, default=0, help="Sample N nodes (0=all)")
    args = parser.parse_args()

    config = GERConfig()

    print("Loading data from DB and FAISS index...")
    vectors, ids, state_map, doc_map, edges = asyncio.run(load_data(config))
    print(f"  {len(ids)} nodes, {len(edges)} edges loaded")

    # Optional sampling for large datasets
    if args.sample > 0 and args.sample < len(ids):
        print(f"  Sampling {args.sample} nodes...")
        rng = np.random.default_rng(42)
        sample_idx = rng.choice(len(ids), size=args.sample, replace=False)
        sample_idx.sort()
        vectors = vectors[sample_idx]
        ids = [ids[i] for i in sample_idx]
        sampled_set = set(ids)
        edges = [e for e in edges if e.src in sampled_set and e.dst in sampled_set]

    print(f"Reducing to 3D with {args.method.upper()}...")
    coords_3d = reduce_to_3d(vectors, method=args.method)
    print("  Done")

    print("Building visualization...")
    fig = build_figure(coords_3d, ids, state_map, doc_map, edges, config)

    print(f"Saving to {args.output}...")
    fig.write_html(args.output, include_plotlyjs=True)
    print(f"  Saved: {args.output}")

    if args.open:
        import webbrowser
        webbrowser.open(args.output)
    else:
        print(f"  Open in browser: file://{args.output}")


if __name__ == "__main__":
    main()
