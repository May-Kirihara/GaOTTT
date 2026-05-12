from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid

import numpy as np

from gaottt.config import GaOTTTConfig
from gaottt.core.clustering import Cluster, cluster_by_similarity, find_merge_candidates
from gaottt.core.collision import MergeOutcome, merge_pair, pick_survivor
from gaottt.core.gravity import (
    compute_gravity_kick,
    compute_virtual_position,
    propagate_gravity_wave,
    update_orbital_state,
)
from gaottt.core.persona_gravity import (
    collect_active_persona_ids,
    compute_persona_proximities,
)
from gaottt.core.prefetch import PrefetchCache, PrefetchPool
from gaottt.core.scorer import (
    compute_certainty_boost,
    compute_decay,
    compute_emotion_boost,
    compute_mass_boost,
)
from gaottt.core.types import (
    CooccurrenceEdge,
    DirectedEdge,
    NodeState,
    QueryResultItem,
)
from gaottt.embedding.ruri import RuriEmbedder
from gaottt.graph.cooccurrence import CooccurrenceGraph
from gaottt.index.faiss_index import FaissIndex
from gaottt.store.cache import CacheLayer
from gaottt.store.sqlite_store import SqliteStore

logger = logging.getLogger(__name__)


class GaOTTTEngine:
    def __init__(
        self,
        config: GaOTTTConfig,
        embedder: RuriEmbedder,
        faiss_index: FaissIndex,
        cache: CacheLayer,
        store: SqliteStore,
        virtual_faiss_index: FaissIndex | None = None,
    ):
        self.config = config
        self.embedder = embedder
        self.faiss_index = faiss_index
        self.virtual_faiss_index = virtual_faiss_index
        self.cache = cache
        self.store = store
        self.graph = CooccurrenceGraph(config, cache)
        self.prefetch_cache = PrefetchCache(
            max_size=config.prefetch_cache_size,
            ttl_seconds=config.prefetch_ttl_seconds,
        )
        self.prefetch_pool = PrefetchPool(
            max_concurrent=config.prefetch_max_concurrent,
        )
        # FAISS write-behind state. New vectors enter only the in-memory
        # FAISS index; without periodic save, other processes' startup()
        # would load a stale index and never see them until this process
        # called shutdown(). The background loop below saves the index on
        # a fixed cadence whenever `_faiss_dirty` is set.
        self._faiss_dirty: bool = False
        self._faiss_save_task: asyncio.Task | None = None
        self._faiss_save_stop: asyncio.Event | None = None
        # Phase G — Dream loop: revisits quiet nodes on a slow cadence with
        # synthetic recalls so co-occurrence and gravity state build up even
        # without user query (hippocampal-replay analog). Disabled when
        # dream_enabled=False or dream_interval_seconds<=0.
        self._dream_task: asyncio.Task | None = None
        self._dream_stop: asyncio.Event | None = None

    async def startup(self) -> None:
        await self.store.initialize()
        expired = await self.store.expire_due_nodes(time.time())
        if expired:
            logger.info("Auto-expired %d nodes past their TTL", expired)
        await self.cache.load_from_store(self.store)
        self.faiss_index.load(self.config.faiss_index_path)
        if self.virtual_faiss_index is not None:
            virtual_path = self.config.virtual_faiss_index_path
            self.virtual_faiss_index.load(virtual_path)
            if self.virtual_faiss_index.size == 0 and self.faiss_index.size > 0:
                # No persisted virtual index yet — rebuild from raw + cache.
                logger.info(
                    "Virtual FAISS missing; building from raw + displacement"
                )
                await self._rebuild_virtual_faiss_index()
        self.cache.start_write_behind(self.store)
        if self.config.faiss_save_interval_seconds > 0:
            self._faiss_save_stop = asyncio.Event()
            self._faiss_save_task = asyncio.create_task(self._faiss_save_loop())
        if (
            self.config.dream_enabled
            and self.config.dream_interval_seconds > 0
        ):
            self._dream_stop = asyncio.Event()
            self._dream_task = asyncio.create_task(self._dream_loop())
        logger.info(
            "Engine started: %d nodes cached, %d vectors indexed, %d displacements",
            len(self.cache.node_cache),
            self.faiss_index.size,
            len(self.cache.displacement_cache),
        )

    async def shutdown(self) -> None:
        await self.prefetch_pool.drain(timeout=5.0)
        if self._dream_stop is not None:
            self._dream_stop.set()
        if self._dream_task is not None:
            try:
                await asyncio.wait_for(self._dream_task, timeout=10.0)
            except asyncio.TimeoutError:
                self._dream_task.cancel()
        if self._faiss_save_stop is not None:
            self._faiss_save_stop.set()
        if self._faiss_save_task is not None:
            try:
                await asyncio.wait_for(self._faiss_save_task, timeout=10.0)
            except asyncio.TimeoutError:
                self._faiss_save_task.cancel()
        await self.cache.stop_write_behind()
        await self.cache.flush_to_store(self.store)
        # Final synchronous save guarantees durability even if the loop
        # was disabled or skipped a final tick.
        await asyncio.to_thread(
            self.faiss_index.save, self.config.faiss_index_path,
        )
        if self.virtual_faiss_index is not None:
            await asyncio.to_thread(
                self.virtual_faiss_index.save,
                self.config.virtual_faiss_index_path,
            )
        self._faiss_dirty = False
        await self.store.close()
        logger.info("Engine shut down, state persisted")

    async def _faiss_save_loop(self) -> None:
        """Background FAISS save: persists in-memory FAISS additions on a
        fixed cadence. Crucial for multi-process visibility.
        """
        assert self._faiss_save_stop is not None
        interval = self.config.faiss_save_interval_seconds
        path = self.config.faiss_index_path
        while not self._faiss_save_stop.is_set():
            try:
                await asyncio.wait_for(
                    self._faiss_save_stop.wait(), timeout=interval,
                )
                break  # stop signalled
            except asyncio.TimeoutError:
                pass  # interval elapsed, try a save tick
            if self._faiss_dirty:
                # Claim before save so any add() during the save itself
                # leaves dirty=True for the next tick to handle.
                self._faiss_dirty = False
                try:
                    await asyncio.to_thread(self.faiss_index.save, path)
                except Exception:  # noqa: BLE001
                    self._faiss_dirty = True
                    logger.exception("Periodic FAISS save failed; will retry")

    def _pick_dream_candidates(self, limit: int) -> list[str]:
        """Quiet nodes worth revisiting in a dream tick.

        Picks non-archived nodes whose mass is still below
        ``dream_mass_ceiling`` and whose ``last_access`` is older than
        ``dream_min_idle_seconds``. Sorted by oldest-access-first so the
        coldest memories get revived earliest.
        """
        now = time.time()
        ceiling = self.config.dream_mass_ceiling
        min_idle = self.config.dream_min_idle_seconds
        quiet = [
            s for s in self.cache.get_all_nodes()
            if not s.is_archived
            and s.mass < ceiling
            and (now - s.last_access) > min_idle
        ]
        quiet.sort(key=lambda s: s.last_access)
        return [s.id for s in quiet[:limit]]

    async def _dream_loop(self) -> None:
        """Hippocampal-replay analog. While the user is silent, revisit
        quiet nodes via synthetic recall so they accumulate co-occurrence
        and gravity field updates without ever being shown to the LLM.
        """
        assert self._dream_stop is not None
        interval = self.config.dream_interval_seconds
        while not self._dream_stop.is_set():
            try:
                await asyncio.wait_for(
                    self._dream_stop.wait(), timeout=interval,
                )
                break  # stop signalled
            except asyncio.TimeoutError:
                pass

            try:
                candidates = self._pick_dream_candidates(
                    limit=self.config.dream_batch_size,
                )
                for nid in candidates:
                    if self._dream_stop.is_set():
                        break
                    doc = await self.store.get_document(nid)
                    if not doc:
                        continue
                    await self._query_internal(
                        text=doc["content"],
                        top_k=self.config.dream_top_k,
                        wave_depth=None,
                        wave_k=None,
                        _is_synthetic=True,
                    )
            except Exception:  # noqa: BLE001
                # A bad tick should not kill the loop. Log and try again.
                logger.exception("Dream tick failed; will retry next cycle")

    # --- US1: Document Indexing ---

    async def index_documents(
        self, documents: list[dict],
    ) -> list[str]:
        hashes = [
            hashlib.sha256(d["content"].encode("utf-8")).hexdigest()
            for d in documents
        ]
        existing = await self.store.find_existing_hashes(hashes)
        filtered = [
            (d, h) for d, h in zip(documents, hashes) if h not in existing
        ]
        if not filtered:
            logger.info("All %d documents already exist, skipping", len(documents))
            return []

        docs_to_index = [d for d, _ in filtered]
        skipped = len(documents) - len(docs_to_index)
        if skipped:
            logger.info("Skipping %d duplicate documents", skipped)

        contents = [d["content"] for d in docs_to_index]
        metadatas = [d.get("metadata") for d in docs_to_index]
        ids = [str(uuid.uuid4()) for _ in docs_to_index]

        vectors = self.embedder.encode_documents(contents)
        self.faiss_index.add(vectors, ids)
        if self.virtual_faiss_index is not None:
            # Fresh nodes have displacement=0, so virtual_pos == raw.
            # The genesis kick below mutates cache.displacement; for now,
            # raw and virtual stay aligned, and a later compact (or the
            # next kick step) will pull virtual_pos away from raw if
            # needed.
            self.virtual_faiss_index.add(vectors, ids)

        now = time.time()
        docs_for_store = []
        for i, doc_id in enumerate(ids):
            doc_in = docs_to_index[i]
            state = NodeState(
                id=doc_id,
                last_access=now,
                expires_at=doc_in.get("expires_at"),
                emotion_weight=float(doc_in.get("emotion", 0.0)),
                certainty=float(doc_in.get("certainty", 1.0)),
                last_verified_at=now if "certainty" in doc_in else None,
            )
            self.cache.set_node(state, dirty=True)
            meta = metadatas[i] or {}
            src = meta.get("source")
            if src:
                self.cache.set_source(doc_id, src)
            # Phase J Stage 2: mirror tags so tag_filter injection sees
            # them without waiting for a cache reload.
            tags = meta.get("tags")
            if isinstance(tags, list):
                self.cache.set_tags(doc_id, [t for t in tags if isinstance(t, str)])
            docs_for_store.append({
                "id": doc_id,
                "content": contents[i],
                "metadata": metadatas[i],
            })

        await self.store.save_documents(docs_for_store)

        # Phase G — Genesis kick: apply one-step Newtonian gravity so the
        # new nodes enter the field with non-zero orbital state instead of
        # competing against established clusters from a "naked" mass=1,
        # displacement=0 starting point. See Plans-Phase-G-Memory-Genesis.md.
        if self.config.genesis_kick_enabled:
            self._apply_genesis_kick(ids, vectors)

        # Phase K — Stellar supernova cohort: when the batch is large enough,
        # form mutual co-occurrence edges + outward initial velocity so the
        # newly-born cohort has internal gravity from birth. See
        # Plans-Phase-K-Stellar-Supernova-Cohort.md. Applied after Phase G so
        # cohort-internal coupling stacks on top of existing-system binding.
        if self.config.supernova_enabled:
            self._apply_supernova_cohort(ids, vectors)

        await self.cache.flush_to_store(self.store)
        self._faiss_dirty = True

        logger.info("Indexed %d documents", len(ids))
        return ids

    def _top_k_heavy_neighbors(
        self,
        vec: np.ndarray,
        k: int,
        pool_size: int = 50,
    ) -> list[tuple[np.ndarray, float]]:
        """Pull a wide FAISS top-N pool, rerank by cached mass, return the
        top-k as (embedding, mass) pairs. Used by the genesis kick to find
        the heavy bodies whose gravity will bend the new node's orbit."""
        pool = self.faiss_index.search(vec.reshape(1, -1), pool_size)
        if not pool:
            return []
        candidates: list[tuple[str, float]] = []
        for nid, _cos in pool:
            state = self.cache.get_node(nid)
            if state is None or state.is_archived:
                continue
            candidates.append((nid, state.mass))
        if not candidates:
            return []
        candidates.sort(key=lambda t: t[1], reverse=True)
        candidates = candidates[:k]
        ids_only = [nid for nid, _ in candidates]
        vec_map = self.faiss_index.get_vectors(ids_only)
        out: list[tuple[np.ndarray, float]] = []
        for nid, mass in candidates:
            v = vec_map.get(nid)
            if v is not None:
                out.append((v, mass))
        return out

    def _apply_genesis_kick(
        self, new_ids: list[str], new_vecs: np.ndarray,
    ) -> None:
        """Run one Verlet step of neighbor gravity on each freshly-indexed
        node, seeding cache displacement/velocity and bumping mass.
        Skips nodes with no qualifying neighbors (an empty DB or a region
        with no heavy bodies)."""
        for i, new_id in enumerate(new_ids):
            new_vec = new_vecs[i]
            neighbors = self._top_k_heavy_neighbors(
                new_vec,
                k=self.config.genesis_kick_neighbor_k,
                pool_size=self.config.genesis_kick_pool_size,
            )
            if not neighbors:
                continue
            disp, vel, m_boost = compute_gravity_kick(
                new_vec, neighbors, self.config,
            )
            disp_norm = float(np.linalg.norm(disp))
            if disp_norm <= 1e-9 and m_boost <= 0.0:
                continue
            self.cache.set_displacement(new_id, disp)
            self.cache.set_velocity(new_id, vel)
            state = self.cache.get_node(new_id)
            if state is not None and m_boost > 0.0:
                state.mass = max(state.mass, 1.0 + m_boost)
                self.cache.set_node(state, dirty=True)

    def _apply_supernova_cohort(
        self, new_ids: list[str], new_vecs: np.ndarray,
    ) -> None:
        """Form mutual co-occurrence edges + outward initial velocity for
        the supernova cohort.

        Velocity is *added* to whatever Phase G genesis kick already put
        in cache (typically Phase G writes a velocity toward existing
        heavy bodies; Phase K adds an outward push from the batch
        centroid; the two compose). Edges are written via
        ``cache.set_edge`` which mirrors both directions of the
        undirected graph and marks them dirty for write-behind flush.
        """
        from gaottt.core.supernova import (
            compute_supernova_velocities,
            form_supernova_edges,
        )

        # Mutual co-occurrence edges
        edges = form_supernova_edges(new_ids, self.config)
        for src, dst, weight in edges:
            self.cache.set_edge(src, dst, weight, dirty=True)

        # Outward initial velocity (added to any Phase G velocity)
        velocities = compute_supernova_velocities(new_ids, new_vecs, self.config)
        for nid, v_supernova in velocities.items():
            existing = self.cache.get_velocity(nid)
            if existing is not None:
                combined = existing + v_supernova
            else:
                combined = v_supernova
            from gaottt.core.gravity import clamp_vector
            combined = clamp_vector(combined, self.config.orbital_max_velocity)
            self.cache.set_velocity(nid, combined.astype(np.float32))

    # --- US2: Query (Gravity Wave Propagation) ---

    async def query(
        self,
        text: str,
        top_k: int | None = None,
        wave_depth: int | None = None,
        wave_k: int | None = None,
        use_cache: bool = False,
        source_filter: list[str] | None = None,
        persona_context: list[str] | None = None,
        tag_filter: list[str] | None = None,
    ) -> list[QueryResultItem]:
        """Run a recall query.

        ``use_cache=True`` consults the prefetch cache first; on hit the
        cached results are returned without re-running embedding/wave/scoring
        (and crucially, without re-applying simulation updates — the prefetch
        already paid that cost). Cache hits are bounded by
        ``config.prefetch_ttl_seconds``.

        ``source_filter`` (Phase H Stage 2) lets the seed step trim the
        FAISS pool to nodes whose ``metadata.source`` matches. Source
        filtering is not part of the prefetch cache key, so any call with
        ``source_filter`` set bypasses the cache.

        ``persona_context`` (Phase J Stage 2) — explicit list of declared
        value/intention/commitment IDs overriding the Stage 1 auto-detect,
        plus additive seed injection of those IDs.

        ``tag_filter`` (Phase J Stage 2) — substring list (OR match) for
        additive seed injection of every node whose ``metadata.tags`` list
        contains any substring. Bypasses ``source_filter``.

        Either explicit argument bypasses the prefetch cache.
        """
        k = top_k or self.config.top_k
        if source_filter or persona_context or tag_filter:
            use_cache = False
        if use_cache:
            cached = self.prefetch_cache.get(text, k)
            if cached is not None:
                return cached
        results = await self._query_internal(
            text=text, top_k=k, wave_depth=wave_depth, wave_k=wave_k,
            source_filter=source_filter,
            persona_context=persona_context,
            tag_filter=tag_filter,
        )
        if use_cache:
            self.prefetch_cache.put(text, k, results)
        return results

    async def _query_internal(
        self,
        text: str,
        top_k: int,
        wave_depth: int | None,
        wave_k: int | None,
        _is_synthetic: bool = False,
        source_filter: list[str] | None = None,
        persona_context: list[str] | None = None,
        tag_filter: list[str] | None = None,
    ) -> list[QueryResultItem]:
        k = top_k
        query_vec = self.embedder.encode_query(text)

        # Phase J Stage 1 / Stage 2: compute persona proximities once per
        # recall. Stage 2 explicit `persona_context` takes precedence over
        # the Stage 1 auto-detected active set.
        persona_proximities: dict[str, float] | None = None
        if self.config.persona_boost_enabled and self.config.persona_boost_alpha > 0.0:
            if persona_context:
                persona_ids: set[str] = set(persona_context)
            else:
                persona_ids = collect_active_persona_ids(
                    self.cache, self.config, time.time(),
                )
            if persona_ids:
                persona_proximities = compute_persona_proximities(
                    persona_ids, self.cache, self.config,
                )

        # Phase J Stage 2: build the additive injection set — explicit
        # persona_context ids plus every node matching the tag_filter
        # substring(s).
        injected_ids: set[str] | None = None
        if persona_context or tag_filter:
            injected_ids = set()
            if persona_context:
                injected_ids |= set(persona_context)
            if tag_filter:
                injected_ids |= self.cache.find_ids_by_tag_filter(tag_filter)
            if not injected_ids:
                injected_ids = None

        # Step 1: Gravity wave propagation — recursive neighbor expansion
        reached = propagate_gravity_wave(
            query_vec, self.faiss_index, self.cache, self.config,
            wave_k=wave_k, wave_depth=wave_depth,
            source_filter=source_filter,
            virtual_faiss_index=self.virtual_faiss_index,
            persona_proximities=persona_proximities,
            injected_ids=injected_ids,
        )

        if not reached:
            return []

        # Step 2: Get original embeddings for all reached nodes
        reached_ids = list(reached.keys())
        original_embs = self.faiss_index.get_vectors(reached_ids)

        # Step 3: Score all reached nodes with virtual coordinates + wave boost
        now = time.time()
        query_vec_flat = query_vec[0] if query_vec.ndim == 2 else query_vec
        results: list[QueryResultItem] = []

        for node_id in reached_ids:
            state = self.cache.get_node(node_id)
            if state is None:
                states = await self.store.get_node_states([node_id])
                state = states.get(node_id)
            if state is None or state.is_archived:
                continue
            if state.expires_at is not None and state.expires_at <= now:
                continue

            original_emb = original_embs.get(node_id)
            if original_emb is None:
                continue

            displacement = self.cache.get_displacement(node_id)
            virtual_pos = compute_virtual_position(
                original_emb, displacement, state.temperature
            )

            gravity_sim = float(np.dot(query_vec_flat, virtual_pos))
            mass_boost = compute_mass_boost(state.mass, self.config.alpha)
            decay = compute_decay(state.last_access, now, self.config.delta)
            wave_boost = self.config.wave_boost_weight * reached[node_id]
            emotion_boost = compute_emotion_boost(
                state.emotion_weight, self.config.emotion_alpha,
            )
            certainty_boost = compute_certainty_boost(
                state.certainty, state.last_verified_at, now,
                self.config.certainty_alpha, self.config.certainty_half_life_seconds,
            )

            # Presentation saturation: frequently returned nodes get lower scores
            saturation = 1.0 / (1.0 + state.return_count * self.config.saturation_rate)

            final = (
                gravity_sim * decay + mass_boost + wave_boost
                + emotion_boost + certainty_boost
            ) * saturation

            if final <= 0.0:
                continue

            doc = await self.store.get_document(node_id)
            if doc is None:
                continue

            results.append(
                QueryResultItem(
                    id=node_id,
                    content=doc["content"],
                    metadata=doc.get("metadata"),
                    raw_score=gravity_sim,
                    final_score=final,
                )
            )

        # Step 4: Sort and take top-K for presentation to LLM.
        # Phase J Stage 2: when explicit injection is requested, force the
        # injected ids into the top-K result. Seed-pool injection alone
        # isn't enough — once the target is a seed, its own wave neighbours
        # can outrank it by sheer cluster mass. The caller's explicit ask
        # has to survive the final cut, not just the entry gate.
        #
        # Critical: when ``len(injected_ids) > k`` (e.g. ``tag_filter``
        # matching 112 nodes with ``top_k=5``), we still respect the
        # caller's ``top_k`` budget — pick the top-K *of the injected
        # set itself* — but rank the forced set by ``raw_score`` rather
        # than ``final_score`` (Phase J Stage 3). Final score is dominated
        # by mass / wave / emotion / certainty, which makes "frequently
        # touched memos win" regardless of query semantic. Inside a
        # caller-injected set, the right ordering is "which of these
        # tagged memos is closest to the query" — i.e. raw cosine.
        # Non-injected results still rank by final_score.
        if injected_ids:
            forced = [r for r in results if r.id in injected_ids]
            others = [r for r in results if r.id not in injected_ids]
            forced.sort(key=lambda r: r.raw_score, reverse=True)
            others.sort(key=lambda r: r.final_score, reverse=True)
            if len(forced) >= k:
                results = forced[:k]
            else:
                results = forced + others[: k - len(forced)]
        else:
            results.sort(key=lambda r: r.final_score, reverse=True)
            results = results[:k]

        # Step 5: Update return_count for presented nodes + habituation recovery for all.
        # Synthetic recalls (Phase G dream loop) skip return_count so that
        # background revisits don't trip presentation saturation — the user
        # never saw these results, so habituation must not punish them.
        result_ids = [r.id for r in results]
        if not _is_synthetic:
            for node_id in result_ids:
                state = self.cache.get_node(node_id)
                if state:
                    state.return_count += 1.0
                    self.cache.set_node(state, dirty=True)

        # Habituation recovery: all reached nodes slowly recover freshness
        all_reached_ids = list(reached.keys())
        for node_id in all_reached_ids:
            state = self.cache.get_node(node_id)
            if state and state.return_count > 0:
                state.return_count *= (1.0 - self.config.habituation_recovery_rate)
                self.cache.set_node(state, dirty=True)

        # Step 6: Simulation update — ALL reached nodes.
        # Phase I Stage 2: pass the query vector + wave scores so the orbital
        # step can apply the query-attraction term to reached nodes.
        self._update_simulation(
            all_reached_ids, reached, original_embs, now,
            query_anchor=query_vec_flat,
        )
        self._update_cooccurrence(result_ids)

        return results

    def _update_simulation(
        self,
        all_reached_ids: list[str],
        reached: dict[str, float],
        original_embs: dict[str, np.ndarray],
        now: float,
        query_anchor: np.ndarray | None = None,
    ) -> None:
        """Update gravity simulation for ALL wave-reached nodes.

        This is the simulation layer: every node the wave touched gets
        mass/temperature updates and orbital mechanics (acceleration → velocity → position).
        Like dark matter, these invisible updates reshape the gravitational field.
        """
        dim = self.config.embedding_dim
        masses = {}
        last_accesses = {}

        for node_id in all_reached_ids:
            state = self.cache.get_node(node_id)
            if state is None:
                continue

            force = reached.get(node_id, 0.0)

            # Mass update scaled by force
            state.mass += self.config.eta * force * (1.0 - state.mass / self.config.m_max)

            # Sim history ring buffer
            state.sim_history.append(force)
            if len(state.sim_history) > self.config.sim_buffer_size:
                state.sim_history = state.sim_history[-self.config.sim_buffer_size:]

            # Temperature
            if len(state.sim_history) >= 2:
                arr = np.array(state.sim_history)
                state.temperature = self.config.gamma * float(np.var(arr))
            else:
                state.temperature = 0.0

            last_accesses[node_id] = state.last_access
            state.last_access = now
            self.cache.set_node(state, dirty=True)
            masses[node_id] = state.mass

        # Orbital mechanics: acceleration → velocity → displacement
        active_ids = [nid for nid in all_reached_ids if nid in original_embs]
        if len(active_ids) >= 2:
            current_displacements = {}
            current_velocities = {}
            for nid in active_ids:
                cached_d = self.cache.get_displacement(nid)
                current_displacements[nid] = cached_d if cached_d is not None else np.zeros(dim, dtype=np.float32)
                cached_v = self.cache.get_velocity(nid)
                current_velocities[nid] = cached_v if cached_v is not None else np.zeros(dim, dtype=np.float32)

            new_disps, new_vels = update_orbital_state(
                active_ids, original_embs,
                current_displacements, current_velocities,
                masses, last_accesses, now, self.config,
                cache=self.cache,
                query_anchor=query_anchor,
                query_scores=reached if query_anchor is not None else None,
            )

            for nid in new_disps:
                self.cache.set_displacement(nid, new_disps[nid])
                self.cache.set_velocity(nid, new_vels[nid])

    def _update_cooccurrence(self, result_ids: list[str]) -> None:
        """Update co-occurrence graph for LLM-returned results only.

        Co-occurrence is based on what the user/LLM actually "sees" together,
        not the full simulation reach.
        """
        if result_ids:
            self.graph.update_cooccurrence(result_ids)

    # --- US3: Node State Inspection ---

    async def get_node_state(self, node_id: str) -> NodeState | None:
        state = self.cache.get_node(node_id)
        if state is not None:
            return state
        states = await self.store.get_node_states([node_id])
        return states.get(node_id)

    def get_displacement_norm(self, node_id: str) -> float:
        disp = self.cache.get_displacement(node_id)
        if disp is None:
            return 0.0
        return float(np.linalg.norm(disp))

    # --- US4: Graph Inspection ---

    def get_graph(
        self,
        min_weight: float = 0.0,
        node_id: str | None = None,
    ) -> list[CooccurrenceEdge]:
        all_edges = self.cache.get_all_edges()
        filtered = []
        for edge in all_edges:
            if edge.weight < min_weight:
                continue
            if node_id is not None and node_id not in (edge.src, edge.dst):
                continue
            filtered.append(edge)
        return filtered

    # --- F5: Forget / Archive ---

    async def archive(self, node_ids: list[str]) -> int:
        """Soft-delete: mark nodes as archived. They are evicted from cache
        and excluded from recall/explore/reflect, but remain in the store
        and can be restored.
        """
        if not node_ids:
            return 0
        await self.cache.flush_to_store(self.store)
        affected = await self.store.set_archived(node_ids, archived=True)
        for nid in node_ids:
            self.cache.evict_node(nid)
        if affected:
            self.prefetch_cache.invalidate()
        logger.info("Archived %d nodes", affected)
        return affected

    async def restore(self, node_ids: list[str]) -> int:
        """Un-archive nodes and reload them into the cache."""
        if not node_ids:
            return 0
        affected = await self.store.set_archived(node_ids, archived=False)
        if affected:
            states = await self.store.get_node_states(node_ids)
            for state in states.values():
                state.is_archived = False
                self.cache.set_node(state, dirty=False)
            disps = await self.store.load_displacements(ids=node_ids)
            vels = await self.store.load_velocities(ids=node_ids)
            for nid, disp in disps.items():
                self.cache.displacement_cache[nid] = disp
            for nid, vel in vels.items():
                self.cache.velocity_cache[nid] = vel
            self.prefetch_cache.invalidate()
        logger.info("Restored %d nodes", affected)
        return affected

    async def forget(self, node_ids: list[str], hard: bool = False) -> int:
        """Forget nodes. hard=False archives them (reversible); hard=True
        physically removes them from the store. Vectors in the FAISS index
        are not removed (rebuild on next reset), but archived nodes are
        filtered out at query time.
        """
        if not node_ids:
            return 0
        if not hard:
            return await self.archive(node_ids)
        await self.cache.flush_to_store(self.store)
        for nid in node_ids:
            self.cache.evict_node(nid)
        deleted = await self.store.hard_delete_nodes(node_ids)
        if deleted:
            self.prefetch_cache.invalidate()
        logger.info("Hard-deleted %d nodes", deleted)
        return deleted

    # --- F6: Background prefetch ---

    def prefetch(
        self,
        text: str,
        top_k: int | None = None,
        wave_depth: int | None = None,
        wave_k: int | None = None,
        persona_context: list[str] | None = None,
        tag_filter: list[str] | None = None,
    ) -> object:
        """Schedule a background recall and cache its result.

        Returns the asyncio.Task handle (mostly opaque to callers; tests can
        ``await`` it for determinism). The next ``query(text, top_k,
        use_cache=True)`` within ``prefetch_ttl_seconds`` will be served from
        the cache without re-running the simulation.

        Phase J Stage 3: `persona_context` / `tag_filter` are forwarded so
        the prefetched result matches what an explicit `recall(...)` with
        the same arguments would return. Cache key is still `(text, top_k)`
        — callers re-running the same prefetch with different injection
        args will overwrite the cache entry, which is the correct semantic
        ("the latest call wins" for predictive pre-firing).
        """
        k = top_k or self.config.top_k

        async def _run() -> list[QueryResultItem]:
            results = await self._query_internal(
                text=text, top_k=k, wave_depth=wave_depth, wave_k=wave_k,
                persona_context=persona_context, tag_filter=tag_filter,
            )
            self.prefetch_cache.put(text, k, results)
            return results

        return self.prefetch_pool.schedule(_run)

    def prefetch_status(self) -> dict:
        return {
            "cache": self.prefetch_cache.stats(),
            "pool": self.prefetch_pool.stats(),
        }

    # --- F3: Directed (typed) relations ---

    async def relate(
        self,
        src_id: str,
        dst_id: str,
        edge_type: str,
        weight: float = 1.0,
        metadata: dict | None = None,
    ) -> DirectedEdge:
        """Create (or replace) a directed typed edge from src to dst.

        Reserved edge types are documented in ``KNOWN_EDGE_TYPES``; the API
        does not enforce them so callers can experiment with new relations.
        """
        if src_id == dst_id:
            raise ValueError("Self-relations are not allowed")
        edge = DirectedEdge(
            src=src_id, dst=dst_id, edge_type=edge_type,
            weight=weight, created_at=time.time(), metadata=metadata,
        )
        await self.store.upsert_directed_edge(edge)
        # Phase J Stage 1: mirror into the in-memory cache so persona
        # traversal in the next recall sees the new edge without waiting
        # for a cache reload.
        self.cache.set_directed_edge(src_id, dst_id, edge_type)
        return edge

    async def unrelate(
        self, src_id: str, dst_id: str, edge_type: str | None = None,
    ) -> int:
        deleted = await self.store.delete_directed_edge(src_id, dst_id, edge_type)
        if deleted > 0:
            self.cache.remove_directed_edge(src_id, dst_id, edge_type)
        return deleted

    async def get_relations(
        self,
        node_id: str,
        edge_type: str | None = None,
        direction: str = "out",
    ) -> list[DirectedEdge]:
        return await self.store.get_directed_edges(
            node_id=node_id, edge_type=edge_type, direction=direction,
        )

    # --- F7: Emotional weight & certainty ---

    async def revalidate(
        self,
        node_id: str,
        certainty: float | None = None,
        emotion: float | None = None,
    ) -> NodeState | None:
        """Stamp a node with fresh certainty/emotion (re-verification ritual).

        ``certainty`` updates last_verified_at; pass without value to just
        refresh the timestamp at the existing certainty level.
        Returns the updated state or None if the node doesn't exist.
        """
        state = self.cache.get_node(node_id)
        if state is None:
            states = await self.store.get_node_states([node_id])
            state = states.get(node_id)
        if state is None or state.is_archived:
            return None
        if certainty is not None:
            state.certainty = max(0.0, min(1.0, certainty))
        if emotion is not None:
            state.emotion_weight = max(-1.0, min(1.0, emotion))
        state.last_verified_at = time.time()
        self.cache.set_node(state, dirty=True)
        return state

    # --- F2 / F2.1: Clustering, Collision, Compaction ---

    def _virtual_position_for(self, node_id: str) -> np.ndarray | None:
        """Best-effort virtual position (original embedding + displacement)."""
        embs = self.faiss_index.get_vectors([node_id])
        original = embs.get(node_id)
        if original is None:
            return None
        state = self.cache.get_node(node_id)
        temperature = state.temperature if state else 0.0
        displacement = self.cache.get_displacement(node_id)
        return compute_virtual_position(original, displacement, temperature)

    def _active_virtual_positions(
        self, *, top_n_by_mass: int | None = None,
    ) -> dict[str, np.ndarray]:
        """Collect virtual positions for non-archived nodes.

        ``top_n_by_mass`` restricts to the heaviest N nodes (cheaper for large
        memories; matches the "hot topic neighborhood" heuristic in the plan).
        """
        nodes = [n for n in self.cache.get_all_nodes() if not n.is_archived]
        if top_n_by_mass is not None and len(nodes) > top_n_by_mass:
            nodes = sorted(nodes, key=lambda s: s.mass, reverse=True)[:top_n_by_mass]
        out: dict[str, np.ndarray] = {}
        for state in nodes:
            pos = self._virtual_position_for(state.id)
            if pos is not None:
                out[state.id] = pos
        return out

    def find_duplicates(
        self, *, threshold: float = 0.95, top_n_by_mass: int | None = 500,
    ) -> list[Cluster]:
        """Detect near-duplicate clusters among active memories."""
        positions = self._active_virtual_positions(top_n_by_mass=top_n_by_mass)
        return cluster_by_similarity(positions, threshold=threshold)

    async def merge(self, node_ids: list[str], keep: str | None = None) -> list[MergeOutcome]:
        """Manual collision: collapse the given IDs into one survivor.

        If ``keep`` is given, that ID survives. Otherwise the heaviest among
        ``node_ids`` is chosen (ties broken by recency).
        Returns one ``MergeOutcome`` per absorbed node.
        """
        unique_ids = list(dict.fromkeys(node_ids))
        if len(unique_ids) < 2:
            return []

        states_by_id: dict[str, NodeState] = {}
        for nid in unique_ids:
            state = self.cache.get_node(nid)
            if state is None:
                states = await self.store.get_node_states([nid])
                state = states.get(nid)
            if state is None or state.is_archived:
                continue
            states_by_id[nid] = state

        if len(states_by_id) < 2:
            return []

        if keep is not None and keep in states_by_id:
            survivor = states_by_id.pop(keep)
            keep_explicit = True
        else:
            ordered = sorted(
                states_by_id.values(),
                key=lambda s: (s.mass, s.last_access),
                reverse=True,
            )
            survivor = ordered[0]
            states_by_id.pop(survivor.id)
            keep_explicit = False

        outcomes: list[MergeOutcome] = []
        now = time.time()
        for absorbed in states_by_id.values():
            if not keep_explicit:
                # Auto-pick the heavier body so mass conservation feels right.
                # When the caller explicitly passed keep=, that intent wins —
                # otherwise Phase-G mass perturbations could silently override
                # the user's choice.
                survivor, _ = pick_survivor(survivor, absorbed)
                if survivor.id == absorbed.id:
                    survivor, absorbed = absorbed, survivor
            outcome = merge_pair(survivor, absorbed, self.cache, self.config, now=now)
            outcomes.append(outcome)
            # Evict absorbed from cache after marking dirty so flush persists state
            await self.cache.flush_to_store(self.store)
            self.cache.evict_node(absorbed.id)
        if outcomes:
            self.prefetch_cache.invalidate()
        return outcomes

    async def compact(
        self,
        *,
        expire_ttl: bool = True,
        rebuild_faiss: bool = True,
        auto_merge: bool = False,
        merge_threshold: float = 0.95,
        merge_top_n: int = 500,
    ) -> dict:
        """Periodic maintenance: TTL expiry, FAISS rebuild, optional auto-merge.

        Returns a dict report of what changed:
            {
              "expired": int,
              "merged_pairs": int,
              "faiss_rebuilt": bool,
              "vectors_before": int,
              "vectors_after": int,
            }
        """
        report = {
            "expired": 0,
            "merged_pairs": 0,
            "faiss_rebuilt": False,
            "vectors_before": self.faiss_index.size,
            "vectors_after": self.faiss_index.size,
        }

        if expire_ttl:
            now = time.time()
            n = await self.store.expire_due_nodes(now)
            for state in list(self.cache.get_all_nodes()):
                if state.expires_at is not None and state.expires_at <= now:
                    self.cache.evict_node(state.id)
            report["expired"] = n

        if auto_merge:
            positions = self._active_virtual_positions(top_n_by_mass=merge_top_n)
            candidates = find_merge_candidates(positions, threshold=merge_threshold)
            done_pairs = 0
            absorbed_ids: set[str] = set()
            for a, b, _sim in candidates:
                if a in absorbed_ids or b in absorbed_ids:
                    continue
                outcomes = await self.merge([a, b])
                if outcomes:
                    done_pairs += len(outcomes)
                    for o in outcomes:
                        absorbed_ids.add(o.absorbed_id)
            report["merged_pairs"] = done_pairs

        if rebuild_faiss:
            await self._rebuild_faiss_index()
            report["faiss_rebuilt"] = True
        report["vectors_after"] = self.faiss_index.size

        # Drop orphan directed edges (endpoints hard-deleted by the user)
        all_relations = await self.store.get_directed_edges()
        valid_ids = {state.id for state in self.cache.get_all_nodes()}
        orphan_count = 0
        for edge in all_relations:
            if edge.src not in valid_ids and edge.dst not in valid_ids:
                await self.store.delete_directed_edge(edge.src, edge.dst, edge.edge_type)
                orphan_count += 1
        report["orphan_relations_removed"] = orphan_count

        await self.cache.flush_to_store(self.store)
        # Compaction may have changed scoring — invalidate prefetch cache
        self.prefetch_cache.invalidate()
        return report

    async def _rebuild_faiss_index(self) -> None:
        """Drop archived/merged vectors from FAISS by rebuilding the flat index."""
        active_ids = [
            state.id for state in self.cache.get_all_nodes() if not state.is_archived
        ]
        if not active_ids:
            self.faiss_index.reset()
            self._faiss_dirty = True
            return
        vecs = self.faiss_index.get_vectors(active_ids)
        present = [(nid, vecs[nid]) for nid in active_ids if nid in vecs]
        if not present:
            return
        matrix = np.stack([v for _, v in present]).astype(np.float32)
        self.faiss_index.reset()
        self.faiss_index.add(matrix, [nid for nid, _ in present])
        self._faiss_dirty = True
        if self.virtual_faiss_index is not None:
            await self._rebuild_virtual_faiss_index()

    async def _rebuild_virtual_faiss_index(self) -> None:
        """Build the virtual FAISS index from raw embeddings + cached
        displacement (Phase H Stage 4).

        Uses ``compute_virtual_position`` for each active node so that
        Phase G priming (which moves displacement on every active node)
        becomes seedable. Without this index, raw FAISS top-K never sees
        priming-induced cluster shifts."""
        if self.virtual_faiss_index is None:
            return
        active_ids = [
            s.id for s in self.cache.get_all_nodes() if not s.is_archived
        ]
        if not active_ids:
            self.virtual_faiss_index.reset()
            return
        raw_vecs = self.faiss_index.get_vectors(active_ids)
        virtual_vectors: list[np.ndarray] = []
        virtual_ids: list[str] = []
        for nid in active_ids:
            original = raw_vecs.get(nid)
            if original is None:
                continue
            displacement = self.cache.get_displacement(nid)
            state = self.cache.get_node(nid)
            temperature = state.temperature if state is not None else 0.0
            virtual_pos = compute_virtual_position(
                original, displacement, temperature,
            )
            virtual_vectors.append(virtual_pos)
            virtual_ids.append(nid)
        if not virtual_vectors:
            self.virtual_faiss_index.reset()
            return
        matrix = np.stack(virtual_vectors).astype(np.float32)
        self.virtual_faiss_index.reset()
        self.virtual_faiss_index.add(matrix, virtual_ids)
        logger.info(
            "Virtual FAISS rebuilt: %d active vectors", len(virtual_ids),
        )

    # --- US5: State Reset ---

    async def reset(self) -> tuple[int, int]:
        nodes_count = len(self.cache.node_cache)
        edges_count = len(self.cache.get_all_edges())

        self.cache.reset()
        self.graph.reset()
        nodes_reset, edges_removed = await self.store.reset_dynamic_state()

        logger.info("Reset: %d nodes, %d edges removed", nodes_reset, edges_removed)
        return nodes_count, edges_count
