from __future__ import annotations

import logging
import time
import uuid

import numpy as np

from ger_rag.config import GERConfig
from ger_rag.core.scorer import (
    compute_decay,
    compute_final_score,
    compute_mass_boost,
    compute_temp_noise,
)
from ger_rag.core.types import (
    CooccurrenceEdge,
    NodeState,
    QueryResultItem,
)
from ger_rag.embedding.ruri import RuriEmbedder
from ger_rag.graph.cooccurrence import CooccurrenceGraph
from ger_rag.index.faiss_index import FaissIndex
from ger_rag.store.cache import CacheLayer
from ger_rag.store.sqlite_store import SqliteStore

logger = logging.getLogger(__name__)


class GEREngine:
    def __init__(
        self,
        config: GERConfig,
        embedder: RuriEmbedder,
        faiss_index: FaissIndex,
        cache: CacheLayer,
        store: SqliteStore,
    ):
        self.config = config
        self.embedder = embedder
        self.faiss_index = faiss_index
        self.cache = cache
        self.store = store
        self.graph = CooccurrenceGraph(config, cache)

    async def startup(self) -> None:
        await self.store.initialize()
        await self.cache.load_from_store(self.store)
        self.faiss_index.load(self.config.faiss_index_path)
        self.cache.start_write_behind(self.store)
        logger.info(
            "Engine started: %d nodes cached, %d vectors indexed",
            len(self.cache.node_cache),
            self.faiss_index.size,
        )

    async def shutdown(self) -> None:
        await self.cache.stop_write_behind()
        await self.cache.flush_to_store(self.store)
        self.faiss_index.save(self.config.faiss_index_path)
        await self.store.close()
        logger.info("Engine shut down, state persisted")

    # --- US1: Document Indexing ---

    async def index_documents(
        self, documents: list[dict],
    ) -> list[str]:
        contents = [d["content"] for d in documents]
        metadatas = [d.get("metadata") for d in documents]

        ids = [str(uuid.uuid4()) for _ in documents]

        vectors = self.embedder.encode_documents(contents)

        self.faiss_index.add(vectors, ids)

        now = time.time()
        docs_for_store = []
        for i, doc_id in enumerate(ids):
            state = NodeState(id=doc_id, last_access=now)
            self.cache.set_node(state, dirty=True)

            docs_for_store.append({
                "id": doc_id,
                "content": contents[i],
                "metadata": metadatas[i],
            })

        await self.store.save_documents(docs_for_store)
        await self.cache.flush_to_store(self.store)

        logger.info("Indexed %d documents", len(ids))
        return ids

    # --- US2: Query ---

    async def query(self, text: str, top_k: int | None = None) -> list[QueryResultItem]:
        k = top_k or self.config.top_k
        query_vec = self.embedder.encode_query(text)

        candidates = self.faiss_index.search(query_vec, k)
        if not candidates:
            return []

        candidate_ids = [cid for cid, _ in candidates]
        raw_scores: dict[str, float] = {cid: score for cid, score in candidates}

        now = time.time()
        results: list[QueryResultItem] = []

        for node_id, raw_score in candidates:
            state = self.cache.get_node(node_id)
            if state is None:
                states = await self.store.get_node_states([node_id])
                state = states.get(node_id)
            if state is None:
                continue

            mass_boost = compute_mass_boost(state.mass, self.config.alpha)
            decay = compute_decay(state.last_access, now, self.config.delta)
            temp_noise = compute_temp_noise(state.temperature)
            graph_boost = self.graph.compute_graph_boost(node_id, raw_scores)

            final = compute_final_score(raw_score, mass_boost, decay, temp_noise, graph_boost)

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
                    raw_score=raw_score,
                    final_score=final,
                )
            )

        results.sort(key=lambda r: r.final_score, reverse=True)

        self._update_state_after_query(candidates, now)

        return results

    def _update_state_after_query(
        self,
        candidates: list[tuple[str, float]],
        now: float,
    ) -> None:
        result_ids = []
        for node_id, raw_score in candidates:
            state = self.cache.get_node(node_id)
            if state is None:
                continue

            # Mass update with logistic saturation
            state.mass += self.config.eta * raw_score * (1.0 - state.mass / self.config.m_max)

            # Sim history ring buffer
            state.sim_history.append(raw_score)
            if len(state.sim_history) > self.config.sim_buffer_size:
                state.sim_history = state.sim_history[-self.config.sim_buffer_size:]

            # Temperature = gamma * variance(sim_history)
            if len(state.sim_history) >= 2:
                arr = np.array(state.sim_history)
                state.temperature = self.config.gamma * float(np.var(arr))
            else:
                state.temperature = 0.0

            state.last_access = now
            self.cache.set_node(state, dirty=True)
            result_ids.append(node_id)

        # Co-occurrence update
        if result_ids:
            self.graph.update_cooccurrence(result_ids)

    # --- US3: Node State Inspection ---

    async def get_node_state(self, node_id: str) -> NodeState | None:
        state = self.cache.get_node(node_id)
        if state is not None:
            return state
        states = await self.store.get_node_states([node_id])
        return states.get(node_id)

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

    # --- US5: State Reset ---

    async def reset(self) -> tuple[int, int]:
        nodes_count = len(self.cache.node_cache)
        edges_count = len(self.cache.get_all_edges())

        self.cache.reset()
        self.graph.reset()
        nodes_reset, edges_removed = await self.store.reset_dynamic_state()

        logger.info("Reset: %d nodes, %d edges removed", nodes_reset, edges_removed)
        return nodes_count, edges_count
