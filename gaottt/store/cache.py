from __future__ import annotations

import asyncio
import logging
import time

import numpy as np

from gaottt.core.types import CooccurrenceEdge, NodeState
from gaottt.store.base import StoreBase

logger = logging.getLogger(__name__)


class CacheLayer:
    def __init__(self, flush_interval: float = 5.0, flush_threshold: int = 100):
        self.node_cache: dict[str, NodeState] = {}
        self.graph_cache: dict[str, dict[str, float]] = {}
        self.displacement_cache: dict[str, np.ndarray] = {}
        self.velocity_cache: dict[str, np.ndarray] = {}
        # Phase H Stage 2: id → metadata.source. Populated on load_from_store
        # and on index_documents. Lets propagate_gravity_wave apply
        # source_filter at the seed step without per-node store fetches.
        self.source_by_id: dict[str, str] = {}
        # Phase J Stage 1: in-memory mirror of directed_edges so that
        # persona-anchored gravity boost can perform graph traversal in the
        # sync propagate_gravity_wave path without per-recall DB hits.
        # Each entry holds (other_id, edge_type). Loaded on startup, kept
        # in sync by engine.relate / unrelate / forget(hard) / compact paths.
        self.directed_out: dict[str, list[tuple[str, str]]] = {}
        self.directed_in: dict[str, list[tuple[str, str]]] = {}
        # Phase J Stage 2: tag reverse index for the tag_filter additive
        # seed injection. ``tag_to_ids[tag_substring]`` does NOT live here
        # — instead we keep the per-node tag list so callers can do
        # substring matching at recall time (substring patterns vary by
        # query). ``tags_by_id[node_id]`` = list of tag strings as written
        # in documents.metadata.tags.
        self.tags_by_id: dict[str, list[str]] = {}
        # Phase M Stage 1 — Mass conservation: per-node structural identifiers
        # used to detect "self-force" co-occurrence (same source document,
        # same supernova cohort). Mirrored from documents.metadata.
        # original_id_by_id[nid]: id of the source document/object the node
        #   was chunked from (single-doc remember uses node_id itself, file
        #   chunks share the file's stable id, csv rows use the csv id).
        # cohort_id_by_id[nid]: id of the supernova cohort the node was born
        #   in (set on every Phase K batch; absent for singleton remember).
        self.original_id_by_id: dict[str, str] = {}
        self.cohort_id_by_id: dict[str, str] = {}
        self.dirty_nodes: set[str] = set()
        self.dirty_edges: set[tuple[str, str]] = set()
        self.dirty_displacements: set[str] = set()
        self.dirty_velocities: set[str] = set()
        # Phase H Stage 4 (cont.) — virtual FAISS write-behind tracker.
        # Flipped True when displacement changes (the only input to
        # compute_virtual_position aside from raw embedding + temperature,
        # and temperature mutations always co-occur with displacement
        # mutations via update_orbital_state). The engine's virtual-FAISS
        # save loop reads this flag, rebuilds + saves, then clears it.
        # Kept on the cache (not the engine) so unit tests that mutate
        # displacement without an engine still set it consistently.
        self.virtual_faiss_dirty: bool = False
        self._flush_interval = flush_interval
        self._flush_threshold = flush_threshold
        self._write_behind_task: asyncio.Task | None = None

    # --- Node state ---

    def get_node(self, node_id: str) -> NodeState | None:
        return self.node_cache.get(node_id)

    def set_node(self, state: NodeState, dirty: bool = True) -> None:
        self.node_cache[state.id] = state
        if dirty:
            self.dirty_nodes.add(state.id)

    def get_all_nodes(self) -> list[NodeState]:
        return list(self.node_cache.values())

    # --- Source lookup (Phase H Stage 2) ---

    def get_source(self, node_id: str) -> str | None:
        return self.source_by_id.get(node_id)

    def set_source(self, node_id: str, source: str) -> None:
        self.source_by_id[node_id] = source

    # --- Displacement ---

    def get_displacement(self, node_id: str) -> np.ndarray | None:
        return self.displacement_cache.get(node_id)

    def set_displacement(self, node_id: str, displacement: np.ndarray) -> None:
        self.displacement_cache[node_id] = displacement
        self.dirty_displacements.add(node_id)
        self.virtual_faiss_dirty = True

    # --- Velocity ---

    def get_velocity(self, node_id: str) -> np.ndarray | None:
        return self.velocity_cache.get(node_id)

    def set_velocity(self, node_id: str, velocity: np.ndarray) -> None:
        self.velocity_cache[node_id] = velocity
        self.dirty_velocities.add(node_id)

    # --- Graph edges ---

    def get_neighbors(self, node_id: str) -> dict[str, float]:
        return self.graph_cache.get(node_id, {})

    def set_edge(self, src: str, dst: str, weight: float, dirty: bool = True) -> None:
        self.graph_cache.setdefault(src, {})[dst] = weight
        self.graph_cache.setdefault(dst, {})[src] = weight
        if dirty:
            key = (min(src, dst), max(src, dst))
            self.dirty_edges.add(key)

    def remove_edge(self, src: str, dst: str) -> None:
        if src in self.graph_cache:
            self.graph_cache[src].pop(dst, None)
        if dst in self.graph_cache:
            self.graph_cache[dst].pop(src, None)
        key = (min(src, dst), max(src, dst))
        self.dirty_edges.add(key)

    def get_all_edges(self) -> list[CooccurrenceEdge]:
        seen: set[tuple[str, str]] = set()
        edges: list[CooccurrenceEdge] = []
        for src, neighbors in self.graph_cache.items():
            for dst, weight in neighbors.items():
                key = (min(src, dst), max(src, dst))
                if key not in seen:
                    seen.add(key)
                    edges.append(
                        CooccurrenceEdge(src=key[0], dst=key[1], weight=weight, last_update=time.time())
                    )
        return edges

    # --- Directed edges (Phase J Stage 1) ---

    def set_directed_edge(self, src: str, dst: str, edge_type: str) -> None:
        """Mirror an upserted directed edge into the in-memory cache.

        SQLite is the SoT (upsert / delete go through SqliteStore). This cache
        is read-only authoritative for the sync recall path — engine.relate /
        unrelate / forget(hard) call this after writing to the store so the
        next recall sees the change without waiting for a cache reload.
        """
        pair = (dst, edge_type)
        out_list = self.directed_out.setdefault(src, [])
        if pair not in out_list:
            out_list.append(pair)
        in_list = self.directed_in.setdefault(dst, [])
        rev = (src, edge_type)
        if rev not in in_list:
            in_list.append(rev)

    def remove_directed_edge(self, src: str, dst: str, edge_type: str | None = None) -> None:
        """Drop an edge from the cache. ``edge_type=None`` removes all
        edges between the pair."""
        if src in self.directed_out:
            self.directed_out[src] = [
                (d, et)
                for (d, et) in self.directed_out[src]
                if d != dst or (edge_type is not None and et != edge_type)
            ]
            if not self.directed_out[src]:
                self.directed_out.pop(src, None)
        if dst in self.directed_in:
            self.directed_in[dst] = [
                (s, et)
                for (s, et) in self.directed_in[dst]
                if s != src or (edge_type is not None and et != edge_type)
            ]
            if not self.directed_in[dst]:
                self.directed_in.pop(dst, None)

    def get_outgoing(self, node_id: str) -> list[tuple[str, str]]:
        """Return [(dst_id, edge_type), ...] for edges going out of node_id."""
        return self.directed_out.get(node_id, [])

    def get_incoming(self, node_id: str) -> list[tuple[str, str]]:
        """Return [(src_id, edge_type), ...] for edges coming into node_id."""
        return self.directed_in.get(node_id, [])

    # --- Tag index (Phase J Stage 2) ---

    def set_tags(self, node_id: str, tags: list[str]) -> None:
        """Mirror the tags of a (just-indexed) document into the cache. Empty
        ``tags`` list is dropped (no need to keep an entry that never matches)."""
        clean = [t for t in tags if isinstance(t, str) and t]
        if clean:
            self.tags_by_id[node_id] = clean
        else:
            self.tags_by_id.pop(node_id, None)

    def get_tags(self, node_id: str) -> list[str]:
        return self.tags_by_id.get(node_id, [])

    # --- Cohort / original lookup (Phase M Stage 1) ---

    def get_original(self, node_id: str) -> str | None:
        """Stable id of the document/object the node was chunked from. None
        when absent — callers must treat this as "no self-force linkage"."""
        return self.original_id_by_id.get(node_id)

    def set_original(self, node_id: str, original_id: str) -> None:
        if original_id:
            self.original_id_by_id[node_id] = original_id

    def get_cohort(self, node_id: str) -> str | None:
        """Supernova cohort id, or None for singleton remember."""
        return self.cohort_id_by_id.get(node_id)

    def set_cohort(self, node_id: str, cohort_id: str) -> None:
        if cohort_id:
            self.cohort_id_by_id[node_id] = cohort_id

    def find_ids_by_tag_filter(self, tag_substrings: list[str]) -> set[str]:
        """OR-match: return ids whose tag list contains any string that
        contains any of the requested substrings (substring match per
        Phase J Stage 2 §「設計判断 2」). Returns an empty set on no
        filters / no hits."""
        if not tag_substrings:
            return set()
        # Pre-lowercase substrings? Phase H Stage 2 source_filter is case-
        # sensitive; mirror that for consistency.
        hits: set[str] = set()
        for nid, tags in self.tags_by_id.items():
            for tag in tags:
                if any(sub in tag for sub in tag_substrings):
                    hits.add(nid)
                    break
        return hits

    # --- Load from store ---

    async def load_from_store(self, store: StoreBase) -> None:
        states = await store.get_all_node_states()
        archived_ids: set[str] = set()
        for s in states:
            if s.is_archived:
                archived_ids.add(s.id)
                continue
            self.node_cache[s.id] = s

        edges = await store.get_all_edges()
        loaded_edges = 0
        for e in edges:
            if e.src in archived_ids or e.dst in archived_ids:
                continue
            self.graph_cache.setdefault(e.src, {})[e.dst] = e.weight
            self.graph_cache.setdefault(e.dst, {})[e.src] = e.weight
            loaded_edges += 1

        self.displacement_cache = await store.load_displacements()
        self.velocity_cache = await store.load_velocities()
        self.source_by_id = await store.get_all_sources()

        # Phase J Stage 2: tag reverse index for tag_filter additive injection.
        tags_map = await store.get_all_tags()
        # Drop archived ids so tag_filter does not surface zombie nodes.
        self.tags_by_id = {
            nid: tags for nid, tags in tags_map.items() if nid not in archived_ids
        }

        # Phase M Stage 1 — mass-conservation identifiers.
        original_map = await store.get_all_originals()
        self.original_id_by_id = {
            nid: oid for nid, oid in original_map.items() if nid not in archived_ids
        }
        cohort_map = await store.get_all_cohorts()
        self.cohort_id_by_id = {
            nid: cid for nid, cid in cohort_map.items() if nid not in archived_ids
        }

        # Phase J Stage 1: mirror directed edges into the in-memory cache.
        # Skip edges that touch archived nodes so the sync recall path never
        # traverses zombie connections.
        self.directed_out.clear()
        self.directed_in.clear()
        loaded_directed = 0
        directed = await store.get_directed_edges()
        for e in directed:
            if e.src in archived_ids or e.dst in archived_ids:
                continue
            self.directed_out.setdefault(e.src, []).append((e.dst, e.edge_type))
            self.directed_in.setdefault(e.dst, []).append((e.src, e.edge_type))
            loaded_directed += 1

        logger.info(
            "Cache loaded: %d active nodes (%d archived skipped), %d edges, "
            "%d directed_edges, %d displacements, %d velocities, %d sources",
            len(self.node_cache), len(archived_ids), loaded_edges,
            loaded_directed,
            len(self.displacement_cache), len(self.velocity_cache),
            len(self.source_by_id),
        )

    # --- Archive (F4 + F5) ---

    def evict_node(self, node_id: str) -> None:
        """Drop a node and its associated state from the in-memory cache.

        Used when a node is archived or deleted; the canonical state still
        lives in the store (or is removed there separately for hard delete).
        """
        self.node_cache.pop(node_id, None)
        self.displacement_cache.pop(node_id, None)
        self.velocity_cache.pop(node_id, None)
        self.source_by_id.pop(node_id, None)
        self.tags_by_id.pop(node_id, None)
        self.original_id_by_id.pop(node_id, None)
        self.cohort_id_by_id.pop(node_id, None)
        self.dirty_nodes.discard(node_id)
        self.dirty_displacements.discard(node_id)
        self.dirty_velocities.discard(node_id)
        # Active-set membership changed → virtual FAISS needs rebuild.
        self.virtual_faiss_dirty = True
        neighbors = self.graph_cache.pop(node_id, {})
        for other in neighbors:
            self.graph_cache.get(other, {}).pop(node_id, None)
        # Phase J Stage 1: prune directed edges touching this node so the
        # cache stays consistent with what the persona traversal expects.
        outgoing = self.directed_out.pop(node_id, [])
        for dst, _et in outgoing:
            if dst in self.directed_in:
                self.directed_in[dst] = [
                    (s, et) for (s, et) in self.directed_in[dst] if s != node_id
                ]
                if not self.directed_in[dst]:
                    self.directed_in.pop(dst, None)
        incoming = self.directed_in.pop(node_id, [])
        for src, _et in incoming:
            if src in self.directed_out:
                self.directed_out[src] = [
                    (d, et) for (d, et) in self.directed_out[src] if d != node_id
                ]
                if not self.directed_out[src]:
                    self.directed_out.pop(src, None)

    # --- Flush to store ---

    async def flush_to_store(self, store: StoreBase) -> None:
        if self.dirty_nodes:
            dirty_states = [
                self.node_cache[nid]
                for nid in self.dirty_nodes
                if nid in self.node_cache
            ]
            if dirty_states:
                await store.save_node_states(dirty_states)
            self.dirty_nodes.clear()

        if self.dirty_displacements:
            dirty_disp = {
                nid: self.displacement_cache[nid]
                for nid in self.dirty_displacements
                if nid in self.displacement_cache
            }
            if dirty_disp:
                await store.save_displacements(dirty_disp)
            self.dirty_displacements.clear()

        if self.dirty_velocities:
            dirty_vel = {
                nid: self.velocity_cache[nid]
                for nid in self.dirty_velocities
                if nid in self.velocity_cache
            }
            if dirty_vel:
                await store.save_velocities(dirty_vel)
            self.dirty_velocities.clear()

        if self.dirty_edges:
            dirty_edge_list: list[CooccurrenceEdge] = []
            removed_pairs: list[tuple[str, str]] = []
            for src, dst in self.dirty_edges:
                if dst in self.graph_cache.get(src, {}):
                    weight = self.graph_cache[src][dst]
                    dirty_edge_list.append(
                        CooccurrenceEdge(src=src, dst=dst, weight=weight, last_update=time.time())
                    )
                else:
                    removed_pairs.append((src, dst))
            if dirty_edge_list:
                await store.save_edges(dirty_edge_list)
            if removed_pairs:
                await store.delete_edges(removed_pairs)
            self.dirty_edges.clear()

    # --- Write-behind background task ---

    async def _write_behind_loop(self, store: StoreBase) -> None:
        while True:
            await asyncio.sleep(self._flush_interval)
            try:
                if (
                    self.dirty_nodes
                    or self.dirty_edges
                    or self.dirty_displacements
                    or self.dirty_velocities
                ):
                    await self.flush_to_store(store)
            except Exception:
                logger.exception("Write-behind flush failed")

    def start_write_behind(self, store: StoreBase) -> None:
        if self._write_behind_task is None:
            self._write_behind_task = asyncio.create_task(self._write_behind_loop(store))

    async def stop_write_behind(self) -> None:
        if self._write_behind_task is not None:
            self._write_behind_task.cancel()
            try:
                await self._write_behind_task
            except asyncio.CancelledError:
                pass
            self._write_behind_task = None

    # --- Reset ---

    def reset(self) -> None:
        for state in self.node_cache.values():
            state.mass = 1.0
            state.temperature = 0.0
            state.last_access = time.time()
            state.sim_history = []
        self.dirty_nodes.update(self.node_cache.keys())
        self.graph_cache.clear()
        self.dirty_edges.clear()
        self.displacement_cache.clear()
        self.dirty_displacements.clear()
        self.velocity_cache.clear()
        self.dirty_velocities.clear()
