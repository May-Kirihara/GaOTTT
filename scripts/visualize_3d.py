"""GaOTTT 3D Visualization — Cosmic View

ドキュメントを宇宙空間の恒星として可視化する。
各ノードの温度が恒星の色温度に対応し、質量が恒星のサイズに対応する。
速度ベクトル（加速度方向）を矢印、重力圏を球として表現。

Usage:
    # raw embedding (固定座標空間)
    python scripts/visualize_3d.py --position-space raw [--open]

    # virtual position = raw + displacement (デフォルト、重力で変位後の宇宙)
    python scripts/visualize_3d.py [--position-space virtual] [--open]

    # 並列比較 (raw 左 / virtual 右)
    python scripts/visualize_3d.py --position-space compare [--open]

    # virtual を Python で再計算ではなく、本番 gaottt.virtual.faiss から直接ロード
    python scripts/visualize_3d.py --virtual-source faiss [--open]

Legacy:
    --compare は --position-space compare の alias として残してある。

サーバー停止中でも実行可能（DB + FAISSファイルを直接読む）。
"""

from __future__ import annotations

import argparse
import asyncio
import math
import time

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from gaottt.config import GaOTTTConfig
from gaottt.core.gravity import bh_factor, compute_virtual_position
from gaottt.index.faiss_index import FaissIndex
from gaottt.store.sqlite_store import SqliteStore


# -----------------------------------------------------------------------
# Stellar color temperature mapping
# -----------------------------------------------------------------------

def stellar_color(temperature: float, mass: float, decay: float, disp_norm: float) -> str:
    """Map node temperature to stellar color (pure blackbody)."""
    t = min(1.0, temperature / 0.00025)

    if mass < 1.01 and temperature < 1e-8:
        alpha = 0.06 + 0.06 * decay
        return f"rgba(40,30,25,{alpha:.2f})"

    if t < 0.1:
        r, g, b = 180, 60, 30
    elif t < 0.25:
        blend = (t - 0.1) / 0.15
        r, g, b = int(180 + 55 * blend), int(60 + 60 * blend), int(30 + 10 * blend)
    elif t < 0.45:
        blend = (t - 0.25) / 0.2
        r, g, b = 255, int(120 + 90 * blend), int(40 + 30 * blend)
    elif t < 0.65:
        blend = (t - 0.45) / 0.2
        r, g, b = 255, int(210 + 45 * blend), int(70 + 150 * blend)
    elif t < 0.85:
        blend = (t - 0.65) / 0.2
        r, g, b = int(255 - 20 * blend), int(255 - 10 * blend), 255
    else:
        blend = (t - 0.85) / 0.15
        r, g, b = int(235 - 75 * blend), int(245 - 45 * blend), 255

    disp_boost = min(0.15, disp_norm * 0.5)
    luminosity = 0.3 + 0.7 * min(1.0, mass / 8.0)
    alpha = min(1.0, (0.15 + 0.85 * decay * luminosity) + disp_boost)
    return f"rgba({r},{g},{b},{alpha:.2f})"


def stellar_size(mass: float, disp_norm: float) -> float:
    if mass < 1.01:
        base = 1.5
    else:
        base = 2.0 + 12.0 * min(1.0, (mass - 1.0) / 8.0)
    glow = min(3.0, disp_norm * 10)
    return base + glow


# -----------------------------------------------------------------------
# Data loading
# -----------------------------------------------------------------------

def reduce_to_3d(vectors: np.ndarray, method: str = "pca") -> np.ndarray:
    if method == "umap":
        import umap
        reducer = umap.UMAP(n_components=3, n_neighbors=15, min_dist=0.1, metric="cosine")
        return reducer.fit_transform(vectors)
    else:
        from sklearn.decomposition import PCA
        return PCA(n_components=3).fit_transform(vectors)


def sphere_wrap(coords_3d: np.ndarray) -> np.ndarray:
    """Project 3D coords onto the unit sphere (L2-normalize each row).

    The embedding space is the unit hypersphere S^767 — every vector RURI
    emits is unit-norm and the physics operates on that surface. Plotting
    PCA/UMAP output as a flat Euclidean cloud makes the unit-sphere
    constraint invisible; this normalization puts the visual back on the
    geometry the simulation actually runs on. Numerically lossy by design
    (radial information is collapsed) — the viz is for intuition, not
    measurement.
    """
    norms = np.linalg.norm(coords_3d, axis=1, keepdims=True)
    norms = np.where(norms < 1e-9, 1.0, norms)
    return (coords_3d / norms).astype(np.float32)


def _wireframe_sphere_traces(
    n_lat: int = 8,
    n_lon: int = 12,
    n_pts: int = 60,
    color: str = "rgba(70,100,160,0.10)",
) -> list:
    """Faint lat/lon wireframe for the unit sphere — visual reference so
    the sphere-wrapped node cloud reads as "on a globe" instead of "an
    arbitrary ball of points". Returns a list of plotly traces ready to
    add to a figure."""
    traces = []
    # Latitude rings (parallels): each at constant z, circle in xy-plane
    for i in range(1, n_lat):
        phi = math.pi * i / n_lat - math.pi / 2.0   # [-π/2, π/2]
        z = math.sin(phi)
        r = math.cos(phi)
        theta = np.linspace(0, 2 * math.pi, n_pts)
        traces.append(go.Scatter3d(
            x=(r * np.cos(theta)).tolist(),
            y=(r * np.sin(theta)).tolist(),
            z=[z] * n_pts,
            mode="lines",
            line=dict(color=color, width=1),
            hoverinfo="skip", showlegend=False,
        ))
    # Longitude rings (meridians): each in a plane rotated about the z-axis
    for j in range(n_lon):
        lam = 2 * math.pi * j / n_lon
        phi = np.linspace(-math.pi / 2, math.pi / 2, n_pts)
        cx = np.cos(phi) * math.cos(lam)
        cy = np.cos(phi) * math.sin(lam)
        cz = np.sin(phi)
        traces.append(go.Scatter3d(
            x=cx.tolist(), y=cy.tolist(), z=cz.tolist(),
            mode="lines",
            line=dict(color=color, width=1),
            hoverinfo="skip", showlegend=False,
        ))
    return traces


def add_wireframe_sphere(fig, row=None, col=None) -> None:
    """Insert the unit-sphere wireframe into ``fig`` (or a subplot of it)."""
    for trace in _wireframe_sphere_traces():
        if row is not None:
            fig.add_trace(trace, row=row, col=col)
        else:
            fig.add_trace(trace)


def slerp_arc(
    p1: np.ndarray,
    p2: np.ndarray,
    n_pts: int = 10,
) -> np.ndarray:
    """Great-circle arc between two unit-sphere points via spherical linear
    interpolation. Returns ``(n_pts, 3)`` array of points along the
    geodesic from p1 to p2.

    Edge cases:
      * p1 ≈ p2 → straight line (the arc degenerates)
      * p1 ≈ -p2 → infinite great circles exist; we fall back to a chord
        through the origin (rare in practice for embedding clusters)
    """
    dot = float(np.clip(np.dot(p1, p2), -1.0, 1.0))
    # Near-identical or antipodal: degenerate, use linear interpolation.
    if abs(dot) > 0.9999:
        ts = np.linspace(0.0, 1.0, n_pts)
        return np.stack([(1 - t) * p1 + t * p2 for t in ts]).astype(np.float32)
    theta = math.acos(dot)
    sin_theta = math.sin(theta)
    ts = np.linspace(0.0, 1.0, n_pts)
    out = np.empty((n_pts, 3), dtype=np.float32)
    for k, t in enumerate(ts):
        a = math.sin((1.0 - t) * theta) / sin_theta
        b = math.sin(t * theta) / sin_theta
        out[k] = a * p1 + b * p2
    return out


def tangent_geodesic(
    p: np.ndarray,
    v: np.ndarray,
    n_pts: int = 8,
) -> np.ndarray | None:
    """Geodesic segment from ``p`` along the tangent projection of ``v``.

    The velocity vector ``v`` lives in ambient 3D (PCA-projected from 768D).
    On a unit sphere the physical motion is along the tangent component
    ``v_t = v - (v·p)·p``; the geodesic is the great circle in the plane
    spanned by ``p`` and ``v_t``, traversed at angular speed ``|v_t|``.
    Position at time t: ``cos(t·ω) p + sin(t·ω) v_t/|v_t|`` where
    ``ω = |v_t|`` (taken as radians, matching the convention of the flat
    arrow where the tip lands at ``p + v``).

    Returns ``None`` if the tangent component is too small to draw
    (purely radial velocity, which can't survive the sphere constraint).
    """
    dot = float(np.dot(v, p))
    v_t = v - dot * p
    omega = float(np.linalg.norm(v_t))
    if omega < 1e-6:
        return None
    v_t_hat = v_t / omega
    ts = np.linspace(0.0, 1.0, n_pts)
    out = np.empty((n_pts, 3), dtype=np.float32)
    for k, t in enumerate(ts):
        ang = t * omega
        out[k] = math.cos(ang) * p + math.sin(ang) * v_t_hat
    return out


async def load_data(config: GaOTTTConfig):
    faiss_index = FaissIndex(dimension=config.embedding_dim)
    faiss_index.load(config.faiss_index_path)

    if faiss_index.size == 0:
        print("ERROR: FAISSインデックスが空です。")
        raise SystemExit(1)

    import faiss
    raw = faiss.rev_swig_ptr(faiss_index._index.get_xb(), faiss_index.size * config.embedding_dim)
    vectors = np.array(raw).reshape(faiss_index.size, config.embedding_dim).copy()
    ids = list(faiss_index._id_map)

    store = SqliteStore(db_path=config.db_path)
    await store.initialize()
    states = await store.get_all_node_states()
    state_map = {s.id: s for s in states}

    doc_map = {}
    for node_id in ids:
        doc = await store.get_document(node_id)
        if doc:
            doc_map[node_id] = doc

    edges = await store.get_all_edges()
    displacements = await store.load_displacements()
    velocities = await store.load_velocities()

    # Build co-occurrence neighbor map for BH centroid computation
    cooccurrence_neighbors: dict[str, dict[str, float]] = {}
    for edge in edges:
        cooccurrence_neighbors.setdefault(edge.src, {})[edge.dst] = edge.weight
        cooccurrence_neighbors.setdefault(edge.dst, {})[edge.src] = edge.weight

    await store.close()

    return vectors, ids, state_map, doc_map, edges, displacements, velocities, cooccurrence_neighbors


def compute_mass_bh_nodes(
    ids: list[str],
    masses: np.ndarray,
    config: GaOTTTConfig,
) -> list[tuple[int, float]]:
    """Phase M Stage 1 — return ``[(node_index, bh_factor), ...]`` for every
    node whose mass crosses the BH attractor threshold.

    Replaces the legacy ``compute_bh_centroids_3d`` (co-occurrence centroid
    averaging) — a BH is now literally a heavy node, not an emergent
    cluster centroid. ``bh_factor(mass, θ, σ) = tanh((mass-θ)/σ)``, clamped
    to 0 below ``θ - 2σ``. Returns an empty list when the new attractor is
    disabled or no node has accumulated enough mass yet.
    """
    if not config.mass_bh_enabled:
        return []
    cutoff = config.mass_bh_theta - 2.0 * config.mass_bh_sigma
    out: list[tuple[int, float]] = []
    for i, _nid in enumerate(ids):
        m = float(masses[i])
        if m <= cutoff:
            continue
        f = bh_factor(m, config.mass_bh_theta, config.mass_bh_sigma)
        if f <= 0.0:
            continue
        out.append((i, f))
    return out


def build_virtual_vectors(vectors, ids, displacements, state_map):
    virtual = vectors.copy()
    for i, node_id in enumerate(ids):
        disp = displacements.get(node_id)
        if disp is not None and disp.shape[0] == vectors.shape[1]:
            virtual[i] = compute_virtual_position(vectors[i], disp, temperature=0.0)
    return virtual


def load_virtual_faiss_vectors(config, ids, raw_vectors):
    """Load virtual position vectors directly from the on-disk virtual FAISS.

    Returns a (n, dim) ndarray aligned with the given ``ids`` list.

    Reads ``gaottt.virtual.faiss`` — the deployed Stage 4 index that the
    wave seed pool actually queries. Falls back to None when the file is
    absent so the caller can branch to ``build_virtual_vectors``.

    IDs missing from the virtual index inherit their raw embedding row
    (the same fallback the wave path uses when virtual is unavailable),
    so unmatched stars still appear at their pre-drift position.
    """
    import os
    if not os.path.exists(config.virtual_faiss_index_path):
        return None

    virtual_index = FaissIndex(dimension=config.embedding_dim)
    try:
        virtual_index.load(config.virtual_faiss_index_path)
    except Exception as e:  # noqa: BLE001
        print(f"  WARNING: failed to load virtual FAISS ({e}); will recompute in Python")
        return None
    if virtual_index.size == 0:
        return None

    import faiss
    raw = faiss.rev_swig_ptr(
        virtual_index._index.get_xb(),
        virtual_index.size * config.embedding_dim,
    )
    all_vectors = np.array(raw).reshape(virtual_index.size, config.embedding_dim)
    id_to_vec = {nid: all_vectors[i] for i, nid in enumerate(virtual_index._id_map)}

    out = raw_vectors.copy()  # fallback: raw embedding for ids not in virtual FAISS
    matched = 0
    nan_rows = 0
    for i, nid in enumerate(ids):
        v = id_to_vec.get(nid)
        if v is None:
            continue
        if not np.isfinite(v).all():
            nan_rows += 1
            continue  # leave raw fallback in place
        out[i] = v
        matched += 1
    note = f"  Virtual FAISS: {matched}/{len(ids)} ids matched"
    if nan_rows:
        note += f" ({nan_rows} NaN/inf rows fell back to raw — corrupted virtual FAISS?)"
    print(note)
    return out


# -----------------------------------------------------------------------
# Node properties
# -----------------------------------------------------------------------

def compute_node_properties(ids, state_map, doc_map, displacements, velocities, config):
    now = time.time()
    masses, temperatures, decays, disp_norms, vel_norms = [], [], [], [], []
    hover_texts, sources = [], []

    for node_id in ids:
        state = state_map.get(node_id)
        mass = state.mass if state else 1.0
        temp = state.temperature if state else 0.0
        last_access = state.last_access if state else now
        decay_val = math.exp(-config.delta * (now - last_access))
        disp = displacements.get(node_id)
        vel = velocities.get(node_id)
        dn = float(np.linalg.norm(disp)) if disp is not None else 0.0
        vn = float(np.linalg.norm(vel)) if vel is not None else 0.0

        masses.append(mass)
        temperatures.append(temp)
        decays.append(decay_val)
        disp_norms.append(dn)
        vel_norms.append(vn)

        doc = doc_map.get(node_id, {})
        content = doc.get("content", "")[:120].replace("\n", " ")
        meta = doc.get("metadata", {}) or {}
        source = meta.get("source", "unknown")
        sources.append(source)

        # Spectral class
        t_scaled = min(1.0, temp / 0.00025)
        if temp < 1e-8:
            spectral = "Dormant (dust)"
        elif t_scaled < 0.25:
            spectral = "M/K (red giant)" if mass > 3.0 else "M (red dwarf)"
        elif t_scaled < 0.55:
            spectral = "G/F (yellow)"
        elif t_scaled < 0.85:
            spectral = "F/A (white)"
        else:
            spectral = "A/B (blue supergiant)" if mass > 3.0 else "B (blue-white)"

        # Gravity radius
        grav_radius = config.compute_gravity_radius(mass)

        hover_texts.append(
            f"<b>{content}...</b><br><br>"
            f"ID: {node_id[:12]}...<br>"
            f"Source: {source}<br>"
            f"━━━━━━━━━━━━━━━━━<br>"
            f"Mass: <b>{mass:.2f}</b><br>"
            f"Temperature: <b>{temp:.6f}</b> [{spectral}]<br>"
            f"Decay: {decay_val:.4f}<br>"
            f"Displacement: <b>{dn:.6f}</b><br>"
            f"Velocity: <b>{vn:.6f}</b><br>"
            f"Gravity radius: min_sim={grav_radius:.3f}<br>"
            f"History: {len(state.sim_history) if state else 0} entries"
        )

    return (
        np.array(masses), np.array(temperatures), np.array(decays),
        np.array(disp_norms), np.array(vel_norms), hover_texts, sources,
    )


# -----------------------------------------------------------------------
# Figure building
# -----------------------------------------------------------------------

SPACE_SCENE = dict(
    xaxis=dict(showgrid=False, zeroline=False, showticklabels=False,
               showspikes=False, title="", backgroundcolor="rgb(5,5,15)"),
    yaxis=dict(showgrid=False, zeroline=False, showticklabels=False,
               showspikes=False, title="", backgroundcolor="rgb(5,5,15)"),
    zaxis=dict(showgrid=False, zeroline=False, showticklabels=False,
               showspikes=False, title="", backgroundcolor="rgb(5,5,15)"),
    bgcolor="rgb(5,5,15)",
)


def add_nodes_to_figure(
    fig, coords_3d, ids, masses, temperatures, decays, disp_norms, vel_norms,
    hover_texts, sources, edges, velocities_3d=None, config=None,
    cooccurrence_neighbors=None, row=None, col=None, wireframe: bool = True,
    curves: bool = True,
    filament_pts: int = 10,
    velocity_pts: int = 8,
):
    """Add stellar nodes, filaments, velocity arrows, gravity spheres, and BH centroids.

    ``wireframe=True`` (default) draws a faint unit-sphere reference grid
    behind everything — assumes ``coords_3d`` is already on / near the
    unit sphere (see ``sphere_wrap``). Set False for legacy flat-3D view.

    ``curves=True`` (default in sphere mode) renders filaments as
    great-circle arcs and velocity arrows as tangent-projected geodesic
    segments — surface-of-sphere geometry instead of straight chords
    through the interior. Set False (``--straight-lines`` from the CLI)
    to fall back to chord rendering, which is cheaper but lies about
    the unit-sphere constraint.
    """

    def _add(trace):
        if row is not None:
            fig.add_trace(trace, row=row, col=col)
        else:
            fig.add_trace(trace)

    if wireframe:
        add_wireframe_sphere(fig, row=row, col=col)

    # Edges as faint filaments — curves on the sphere when curves=True,
    # chords through the interior otherwise. Each filament contributes
    # filament_pts (curve) or 2 (chord) points; None terminators break
    # segments inside one trace.
    if edges:
        id_to_idx = {nid: i for i, nid in enumerate(ids)}
        ex, ey, ez = [], [], []
        for edge in edges:
            if edge.src not in id_to_idx or edge.dst not in id_to_idx:
                continue
            i, j = id_to_idx[edge.src], id_to_idx[edge.dst]
            if curves:
                arc = slerp_arc(coords_3d[i], coords_3d[j], n_pts=filament_pts)
                ex.extend(arc[:, 0].tolist())
                ex.append(None)
                ey.extend(arc[:, 1].tolist())
                ey.append(None)
                ez.extend(arc[:, 2].tolist())
                ez.append(None)
            else:
                ex.extend([coords_3d[i, 0], coords_3d[j, 0], None])
                ey.extend([coords_3d[i, 1], coords_3d[j, 1], None])
                ez.extend([coords_3d[i, 2], coords_3d[j, 2], None])
        if ex:
            _add(go.Scatter3d(
                x=ex, y=ey, z=ez, mode="lines",
                line=dict(color="rgba(60,90,180,0.12)", width=0.8),
                hoverinfo="skip", name="Filaments", showlegend=True,
            ))

    # Velocity arrows — tangent-projected great-circle walks in sphere
    # mode (physical: the node IS on the sphere, so its next-step
    # position is along a great circle in the tangent direction), or
    # straight chord ``p → p+v`` otherwise.
    if velocities_3d is not None:
        ax, ay, az = [], [], []

        for i in range(len(ids)):
            if vel_norms[i] < 0.001:
                continue
            v = velocities_3d[i]  # already projected to 3D, dt=1 so this IS the next displacement
            if curves:
                geo = tangent_geodesic(coords_3d[i], v, n_pts=velocity_pts)
                if geo is None:
                    continue
                ax.extend(geo[:, 0].tolist())
                ax.append(None)
                ay.extend(geo[:, 1].tolist())
                ay.append(None)
                az.extend(geo[:, 2].tolist())
                az.append(None)
            else:
                ax.extend([coords_3d[i, 0], coords_3d[i, 0] + v[0], None])
                ay.extend([coords_3d[i, 1], coords_3d[i, 1] + v[1], None])
                az.extend([coords_3d[i, 2], coords_3d[i, 2] + v[2], None])

        if ax:
            _add(go.Scatter3d(
                x=ax, y=ay, z=az, mode="lines",
                line=dict(color="rgba(0,255,200,0.7)", width=2.5),
                hoverinfo="skip", name="Velocity vectors", showlegend=True,
            ))

    # Gravity field rings (for high-mass nodes)
    if config is not None:
        # Scale radius relative to data spread
        data_extent = max(
            np.ptp(coords_3d[:, 0]), np.ptp(coords_3d[:, 1]), np.ptp(coords_3d[:, 2])
        ) if len(coords_3d) > 0 else 1.0

        for i in range(len(ids)):
            if masses[i] < 2.0:
                continue
            min_sim = config.compute_gravity_radius(masses[i])
            # Convert cosine distance to 3D radius, capped to ~5% of data extent
            raw_radius = math.sqrt(2.0 * (1.0 - min_sim))
            radius_3d = min(raw_radius * data_extent * 0.04, data_extent * 0.05)

            n_pts = 32
            theta = np.linspace(0, 2 * np.pi, n_pts)
            cx, cy, cz = coords_3d[i]
            alpha = min(0.25, 0.08 + masses[i] * 0.015)

            # XY ring
            _add(go.Scatter3d(
                x=(cx + radius_3d * np.cos(theta)).tolist(),
                y=(cy + radius_3d * np.sin(theta)).tolist(),
                z=np.full(n_pts, cz).tolist(),
                mode="lines",
                line=dict(color=f"rgba(255,200,50,{alpha:.2f})", width=1.2),
                hoverinfo="skip", showlegend=False,
            ))
            # XZ ring (perpendicular, gives sphere impression)
            _add(go.Scatter3d(
                x=(cx + radius_3d * np.cos(theta)).tolist(),
                y=np.full(n_pts, cy).tolist(),
                z=(cz + radius_3d * np.sin(theta)).tolist(),
                mode="lines",
                line=dict(color=f"rgba(255,200,50,{alpha * 0.6:.2f})", width=1.0),
                hoverinfo="skip", showlegend=False,
            ))

    # Phase M Stage 1 — Mass-based Black Holes (literal: a node IS a BH iff
    # its mass crossed the threshold). Replaces the legacy co-occurrence
    # centroid BH. ``cooccurrence_neighbors`` is still accepted for
    # call-site compatibility but is no longer used to compute BHs — edges
    # remain in the filament rendering above.
    if config is not None:
        bh_list = compute_mass_bh_nodes(ids, masses, config)
        if bh_list:
            bh_x = [coords_3d[i, 0] for i, _ in bh_list]
            bh_y = [coords_3d[i, 1] for i, _ in bh_list]
            bh_z = [coords_3d[i, 2] for i, _ in bh_list]
            # Marker size: 5 + 8 * bh_factor (range ~5 just above θ-2σ → ~13 deep in attractor regime).
            bh_sizes = [5.0 + 8.0 * f for f in (b[1] for b in bh_list)]
            bh_texts = [
                f"<b>Mass-BH</b><br>"
                f"node id: {ids[i][:8]}..<br>"
                f"mass: {masses[i]:.2f}<br>"
                f"bh_factor: {f:.3f}<br>"
                f"(θ={config.mass_bh_theta}, σ={config.mass_bh_sigma})"
                for i, f in bh_list
            ]
            _add(go.Scatter3d(
                x=bh_x, y=bh_y, z=bh_z,
                mode="markers",
                marker=dict(
                    size=bh_sizes,
                    color="rgba(180,80,220,0.85)",
                    symbol="diamond",
                ),
                text=bh_texts, hoverinfo="text",
                name=f"Mass-BH ({len(bh_list)})",
            ))

            # Gravity wells around each mass-BH, radius scaled by bh_factor.
            data_extent = max(
                np.ptp(coords_3d[:, 0]), np.ptp(coords_3d[:, 1]), np.ptp(coords_3d[:, 2])
            ) if len(coords_3d) > 0 else 1.0
            n_pts = 24
            theta = np.linspace(0, 2 * np.pi, n_pts)
            for i, f in bh_list:
                radius = min(f * data_extent * 0.05, data_extent * 0.06)
                cx, cy, cz = coords_3d[i]
                alpha = min(0.25, 0.08 + f * 0.18)
                _add(go.Scatter3d(
                    x=(cx + radius * np.cos(theta)).tolist(),
                    y=(cy + radius * np.sin(theta)).tolist(),
                    z=np.full(n_pts, cz).tolist(),
                    mode="lines",
                    line=dict(color=f"rgba(180,80,220,{alpha:.2f})", width=1.5),
                    hoverinfo="skip", showlegend=False,
                ))

    # Stars
    node_colors = []
    node_sizes = []
    for i in range(len(ids)):
        node_colors.append(stellar_color(temperatures[i], masses[i], decays[i], disp_norms[i]))
        node_sizes.append(stellar_size(masses[i], disp_norms[i]))

    _add(go.Scatter3d(
        x=coords_3d[:, 0], y=coords_3d[:, 1], z=coords_3d[:, 2],
        mode="markers",
        marker=dict(size=node_sizes, color=node_colors),
        text=hover_texts, hoverinfo="text",
        name=f"Stars ({len(ids)})",
    ))


def build_single_figure(coords_3d, ids, props, edges, velocities_3d, config,
                        cooccurrence_neighbors=None, title_suffix="",
                        wireframe: bool = True, curves: bool = True):
    masses, temperatures, decays, disp_norms, vel_norms, hover_texts, sources = props

    fig = go.Figure()
    add_nodes_to_figure(
        fig, coords_3d, ids, masses, temperatures, decays, disp_norms, vel_norms,
        hover_texts, sources, edges, velocities_3d=velocities_3d, config=config,
        cooccurrence_neighbors=cooccurrence_neighbors, wireframe=wireframe,
        curves=curves,
    )

    displaced = sum(1 for d in disp_norms if d > 0.001)
    moving = sum(1 for v in vel_norms if v > 0.001)
    max_disp = float(disp_norms.max()) if len(disp_norms) > 0 else 0
    max_vel = float(vel_norms.max()) if len(vel_norms) > 0 else 0
    high_mass = sum(1 for m in masses if m > 2.0)

    fig.update_layout(
        title=dict(text=(
            f"<span style='font-size:20px'>GaOTTT Cosmos {title_suffix}</span><br>"
            f"<sub style='color:#888'>{len(ids)} stars | {len(edges)} filaments | "
            f"Displaced: {displaced} | Moving: {moving} | "
            f"High mass: {high_mass} | Max v: {max_vel:.4f}</sub>"
        )),
        scene=SPACE_SCENE,
        paper_bgcolor="rgb(5,5,15)", plot_bgcolor="rgb(5,5,15)",
        font=dict(color="#CCCCCC", family="monospace"),
        legend=dict(bgcolor="rgba(10,10,30,0.7)", font=dict(color="#AAAAAA", size=11),
                    bordercolor="rgba(40,60,120,0.3)", borderwidth=1),
        margin=dict(l=0, r=0, t=80, b=40),
        width=1400, height=900,
    )
    fig.add_annotation(
        text=(
            "Size=Mass | Color=Temperature (M赤→A/B青白) | "
            "Cyan=Velocity | Gold=Gravity radius | Purple◆=Mass-BH (mass>θ-2σ)"
        ),
        xref="paper", yref="paper", x=0.5, y=-0.03,
        showarrow=False, font=dict(size=11, color="#666666"),
    )
    return fig


def build_comparison_figure(orig_3d, virtual_3d, ids, props, edges, velocities_3d, config,
                            cooccurrence_neighbors=None,
                            wireframe: bool = True, curves: bool = True):
    masses, temperatures, decays, disp_norms, vel_norms, hover_texts, sources = props

    fig = make_subplots(
        rows=1, cols=2,
        specs=[[{"type": "scatter3d"}, {"type": "scatter3d"}]],
        subplot_titles=[
            "<span style='color:#888'>Original Embedding (固定座標)</span>",
            "<span style='color:#FFD700'>Virtual Position (重力変位後)</span>",
        ],
    )

    add_nodes_to_figure(
        fig, orig_3d, ids, masses, temperatures, decays, disp_norms, vel_norms,
        hover_texts, sources, edges, row=1, col=1, wireframe=wireframe,
        curves=curves,
    )
    add_nodes_to_figure(
        fig, virtual_3d, ids, masses, temperatures, decays, disp_norms, vel_norms,
        hover_texts, sources, edges, velocities_3d=velocities_3d, config=config,
        cooccurrence_neighbors=cooccurrence_neighbors, row=1, col=2,
        wireframe=wireframe, curves=curves,
    )

    displaced = sum(1 for d in disp_norms if d > 0.001)
    moving = sum(1 for v in vel_norms if v > 0.001)
    max_vel = float(vel_norms.max()) if len(vel_norms) > 0 else 0

    fig.update_layout(
        title=dict(text=(
            f"<span style='font-size:20px'>GaOTTT Cosmos — Original vs Gravitational Field</span><br>"
            f"<sub style='color:#888'>{len(ids)} stars | {len(edges)} filaments | "
            f"Displaced: {displaced} | Moving: {moving} | Max velocity: {max_vel:.4f}</sub>"
        )),
        scene=SPACE_SCENE, scene2=SPACE_SCENE,
        paper_bgcolor="rgb(5,5,15)", plot_bgcolor="rgb(5,5,15)",
        font=dict(color="#CCCCCC", family="monospace"),
        legend=dict(bgcolor="rgba(10,10,30,0.7)", font=dict(color="#AAAAAA", size=11),
                    bordercolor="rgba(40,60,120,0.3)", borderwidth=1),
        margin=dict(l=0, r=0, t=80, b=40),
        width=1800, height=900,
    )
    return fig


# -----------------------------------------------------------------------
# Velocity 3D projection
# -----------------------------------------------------------------------

def project_velocities_to_3d(ids, velocities, vectors, method, reducer_or_components):
    """Project 768-dim velocity vectors to 3D using the same PCA/UMAP transform."""
    dim = vectors.shape[1]
    vel_3d = np.zeros((len(ids), 3), dtype=np.float32)

    if method == "pca" and reducer_or_components is not None:
        # PCA components matrix (3 x dim)
        components = reducer_or_components
        for i, nid in enumerate(ids):
            vel = velocities.get(nid)
            if vel is not None and np.linalg.norm(vel) > 0.001:
                vel_3d[i] = components @ vel
    # UMAP doesn't have a linear transform, approximate with finite differences
    elif method == "umap":
        for i, nid in enumerate(ids):
            vel = velocities.get(nid)
            if vel is not None and np.linalg.norm(vel) > 0.001:
                # Small perturbation approach — rough approximation
                vel_3d[i] = np.random.randn(3).astype(np.float32) * float(np.linalg.norm(vel))

    return vel_3d


# -----------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="GaOTTT Cosmic 3D Visualization")
    parser.add_argument("--method", choices=["pca", "umap"], default="pca")
    parser.add_argument("--open", action="store_true", help="Open in browser")
    parser.add_argument("--output", default="gaottt_3d.html")
    parser.add_argument("--sample", type=int, default=0, help="Sample N nodes (0=all)")
    parser.add_argument(
        "--position-space", choices=["raw", "virtual", "compare"],
        default="virtual",
        help="Which embedding space to plot: raw (固定座標) / virtual "
             "(raw + displacement, default) / compare (raw vs virtual 並列)",
    )
    parser.add_argument(
        "--virtual-source", choices=["compute", "faiss"], default="compute",
        help="Where to get virtual positions: compute (Python で raw + "
             "displacement を再計算、default) / faiss (gaottt.virtual.faiss "
             "から直接ロード — 本番の Stage 4/5 が実際に見る幾何)",
    )
    parser.add_argument(
        "--compare", action="store_true",
        help="(deprecated alias for --position-space compare)",
    )
    parser.add_argument(
        "--flat", action="store_true",
        help="Skip the unit-sphere wrap and wireframe background — render "
             "the PCA/UMAP output as an unbounded 3D cloud. Useful for "
             "inspecting absolute distances; default is the sphere view "
             "since the embedding space is itself the unit hypersphere.",
    )
    parser.add_argument(
        "--straight-lines", action="store_true",
        help="In sphere mode, draw filaments as chords and velocity arrows "
             "as straight ``p+v`` segments instead of great-circle arcs / "
             "tangent geodesics. Cuts ~10x off the trace point count and "
             "speeds up the initial HTML load; loses the visual ‘motion is "
             "on the sphere surface’ metaphor. Implied by --flat.",
    )
    args = parser.parse_args()

    if args.compare:
        args.position_space = "compare"

    config = GaOTTTConfig.from_config_file()

    print("Loading data...")
    vectors, ids, state_map, doc_map, edges, displacements, velocities, cooc_neighbors = asyncio.run(load_data(config))
    displaced_count = sum(1 for d in displacements.values() if np.linalg.norm(d) > 0.001)
    moving_count = sum(1 for v in velocities.values() if np.linalg.norm(v) > 0.001)
    # Phase M — count nodes whose mass crosses the BH attractor threshold.
    bh_cutoff = config.mass_bh_theta - 2.0 * config.mass_bh_sigma
    bh_nodes = sum(
        1 for nid in ids
        if nid in state_map and state_map[nid].mass > bh_cutoff
    )
    print(f"  {len(ids)} stars, {len(edges)} filaments, "
          f"{displaced_count} displaced, {moving_count} moving, "
          f"{bh_nodes} mass-BH nodes (mass>{bh_cutoff:.1f})")

    if args.sample > 0 and args.sample < len(ids):
        print(f"  Sampling {args.sample} stars...")
        rng = np.random.default_rng(42)
        id_to_idx = {nid: i for i, nid in enumerate(ids)}

        # Ensure co-occurrence nodes are always included in sample
        cooc_node_indices = set()
        for nid in cooc_neighbors:
            if nid in id_to_idx:
                cooc_node_indices.add(id_to_idx[nid])
                for neighbor_id in cooc_neighbors[nid]:
                    if neighbor_id in id_to_idx:
                        cooc_node_indices.add(id_to_idx[neighbor_id])

        remaining = [i for i in range(len(ids)) if i not in cooc_node_indices]
        n_random = max(0, args.sample - len(cooc_node_indices))
        random_idx = rng.choice(remaining, size=min(n_random, len(remaining)), replace=False)
        sample_idx = np.sort(np.array(list(cooc_node_indices) + list(random_idx)))

        print(f"    (including {len(cooc_node_indices)} co-occurrence nodes)")
        vectors = vectors[sample_idx]
        ids = [ids[i] for i in sample_idx]
        sampled_set = set(ids)
        edges = [e for e in edges if e.src in sampled_set and e.dst in sampled_set]
        cooc_neighbors = {
            nid: {k: v for k, v in nbrs.items() if k in sampled_set}
            for nid, nbrs in cooc_neighbors.items()
            if nid in sampled_set
        }

    props = compute_node_properties(ids, state_map, doc_map, displacements, velocities, config)

    def _build_virtual():
        """Pick virtual vectors per --virtual-source, with graceful fallback."""
        if args.virtual_source == "faiss":
            print("Loading virtual positions from gaottt.virtual.faiss ...")
            loaded = load_virtual_faiss_vectors(config, ids, vectors)
            if loaded is not None:
                return loaded, "faiss"
            print("  Falling back to Python recomputation.")
        print("Building virtual positions (raw + displacement)...")
        return build_virtual_vectors(vectors, ids, displacements, state_map), "compute"

    use_sphere = not args.flat
    # Curves only make sense inside the sphere world — --flat implies straight.
    use_curves = use_sphere and not args.straight_lines
    if use_sphere:
        mode = "geodesic curves" if use_curves else "straight chords"
        print(
            f"Sphere-wrap: ON ({mode}). Pass --flat for unbounded 3D, "
            "--straight-lines for chord rendering inside sphere mode."
        )

    if args.position_space == "compare":
        virtual_vectors, vsrc = _build_virtual()

        print(f"Reducing to 3D ({args.method.upper()}, joint fit)...")
        combined = np.vstack([vectors, virtual_vectors])
        if args.method == "pca":
            from sklearn.decomposition import PCA
            pca = PCA(n_components=3)
            combined_3d = pca.fit_transform(combined)
            pca_components = pca.components_  # (3, dim)
        else:
            combined_3d = reduce_to_3d(combined, method=args.method)
            pca_components = None

        n = len(ids)
        orig_3d = combined_3d[:n]
        virtual_3d = combined_3d[n:]

        vel_3d = project_velocities_to_3d(ids, velocities, vectors, args.method, pca_components)

        if use_sphere:
            orig_3d = sphere_wrap(orig_3d)
            virtual_3d = sphere_wrap(virtual_3d)

        print(f"Building cosmic comparison (virtual source: {vsrc})...")
        fig = build_comparison_figure(orig_3d, virtual_3d, ids, props, edges, vel_3d, config,
                                      cooccurrence_neighbors=cooc_neighbors,
                                      wireframe=use_sphere, curves=use_curves)

    elif args.position_space == "raw":
        print(f"Reducing raw embedding to 3D ({args.method.upper()})...")
        if args.method == "pca":
            from sklearn.decomposition import PCA
            pca = PCA(n_components=3)
            coords_3d = pca.fit_transform(vectors)
            pca_components = pca.components_
        else:
            coords_3d = reduce_to_3d(vectors, method=args.method)
            pca_components = None

        vel_3d = project_velocities_to_3d(ids, velocities, vectors, args.method, pca_components)

        if use_sphere:
            coords_3d = sphere_wrap(coords_3d)

        print("Building cosmic view...")
        fig = build_single_figure(coords_3d, ids, props, edges, vel_3d, config,
                                  cooccurrence_neighbors=cooc_neighbors,
                                  title_suffix="— Raw Space",
                                  wireframe=use_sphere, curves=use_curves)

    else:  # virtual
        virtual_vectors, vsrc = _build_virtual()

        print(f"Reducing to 3D ({args.method.upper()})...")
        if args.method == "pca":
            from sklearn.decomposition import PCA
            pca = PCA(n_components=3)
            coords_3d = pca.fit_transform(virtual_vectors)
            pca_components = pca.components_
        else:
            coords_3d = reduce_to_3d(virtual_vectors, method=args.method)
            pca_components = None

        vel_3d = project_velocities_to_3d(ids, velocities, vectors, args.method, pca_components)

        if use_sphere:
            coords_3d = sphere_wrap(coords_3d)

        suffix = f"— Virtual Space ({vsrc})"
        print(f"Building cosmic view ({suffix.strip(' —')})...")
        fig = build_single_figure(coords_3d, ids, props, edges, vel_3d, config,
                                  cooccurrence_neighbors=cooc_neighbors,
                                  title_suffix=suffix,
                                  wireframe=use_sphere, curves=use_curves)

    print(f"Saving to {args.output}...")
    fig.write_html(args.output, include_plotlyjs=True)
    print(f"  Saved: {args.output}")

    if args.open:
        import webbrowser
        webbrowser.open(args.output)
    else:
        print(f"  Open: file://{args.output}")


if __name__ == "__main__":
    main()
