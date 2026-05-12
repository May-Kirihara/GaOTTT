"""Phase J Stage 1 — Persona-anchored gravity boost.

Computes proximity between candidate nodes and the currently active persona
set (declared value / intention / commitment nodes), using graph traversal
of directed edges (`fulfills` / `derived_from` / `completed` / etc.). This
proximity is then used to boost candidates in the seed step of gravity wave
propagation, so that knowledge linked to one's declared identity preferentially
enters the retrieval geometry.

Design intent (see docs/wiki/Plans-Phase-J-Persona-Anchored-Retrieval.md):

- ``collect_active_persona_ids`` reads ``cache.source_by_id`` and returns the
  IDs of nodes whose source is ``value`` / ``intention`` / ``commitment``.
  Stage 1 trusts the cache load to have filtered out archived / TTL-expired
  persona nodes; Stage 2 may re-validate TTL here for time-sensitive
  commitments.

- ``compute_persona_proximities`` runs a breadth-first traversal from the
  union of persona IDs, following ``cache.directed_out`` and
  ``cache.directed_in`` in both directions, capped at
  ``config.persona_max_hop``. Each reachable node gets
  ``proximity = persona_hop_decay ** min_hop_distance``. Persona nodes
  themselves get proximity 1.0 (0 hops). Nodes beyond ``persona_max_hop``
  do not appear in the result (caller treats absence as 0.0).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gaottt.config import GaOTTTConfig
    from gaottt.store.cache import CacheLayer


PERSONA_SOURCES: frozenset[str] = frozenset({"value", "intention", "commitment"})


def collect_active_persona_ids(
    cache: "CacheLayer",
    config: "GaOTTTConfig",
    now: float,
) -> set[str]:
    """Return the set of node IDs currently considered "active persona".

    Stage 1 definition: ``cache.source_by_id[nid]`` is in
    {``value``, ``intention``, ``commitment``}. The cache is the SoT here
    because ``cache.load_from_store`` already skips archived nodes, and
    TTL expiration writes through to archived status before recall sees
    the node again.

    The ``now`` parameter is reserved for Stage 2 (commitment TTL
    re-validation against ``cache.get_node(nid).last_access``); currently
    unused so existing callers don't need to wire a clock through.
    """
    del now  # Stage 1: trust the cache; Stage 2 will use this for TTL checks.
    if not config.persona_boost_enabled:
        return set()
    return {
        nid
        for nid, source in cache.source_by_id.items()
        if source in PERSONA_SOURCES
    }


def compute_persona_proximities(
    persona_ids: set[str],
    cache: "CacheLayer",
    config: "GaOTTTConfig",
) -> dict[str, float]:
    """Compute proximity = ``persona_hop_decay ** hop`` for every node within
    ``persona_max_hop`` of any persona node, via BFS over directed edges.

    Multi-source BFS: persona IDs all start at hop 0. Each step expands
    one hop further via both incoming and outgoing directed edges
    (``fulfills`` from task to commitment, ``derived_from`` from extension
    to seed, etc. — Stage 1 treats every directed edge as a persona-gravity
    line). When a node is reachable from multiple persona nodes the
    shortest hop wins.

    Returns ``{node_id: proximity}`` with proximity in ``(0, 1]``. Nodes
    beyond ``persona_max_hop`` are absent from the dict — callers should
    treat absence as proximity 0.0.
    """
    if not persona_ids or config.persona_max_hop < 0:
        return {}
    if config.persona_hop_decay <= 0.0:
        # Decay of 0 collapses the boost to "persona nodes themselves only"
        # which the caller can still handle, so we return that minimal map.
        return {pid: 1.0 for pid in persona_ids if pid in cache.source_by_id}

    min_hops: dict[str, int] = {pid: 0 for pid in persona_ids}
    frontier: set[str] = set(persona_ids)
    for hop in range(1, config.persona_max_hop + 1):
        next_frontier: set[str] = set()
        for node in frontier:
            for dst, _edge_type in cache.get_outgoing(node):
                if dst not in min_hops:
                    min_hops[dst] = hop
                    next_frontier.add(dst)
            for src, _edge_type in cache.get_incoming(node):
                if src not in min_hops:
                    min_hops[src] = hop
                    next_frontier.add(src)
        if not next_frontier:
            break
        frontier = next_frontier

    return {
        nid: config.persona_hop_decay ** hop
        for nid, hop in min_hops.items()
    }
