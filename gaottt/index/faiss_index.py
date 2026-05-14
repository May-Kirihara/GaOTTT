from __future__ import annotations

import os

import faiss
import numpy as np


class FaissIndex:
    def __init__(self, dimension: int = 768):
        self._dimension = dimension
        self._index = faiss.IndexFlatIP(dimension)
        self._id_map: list[str] = []

    @property
    def size(self) -> int:
        return self._index.ntotal

    def add(self, vectors: np.ndarray, ids: list[str]) -> None:
        assert vectors.shape[0] == len(ids)
        assert vectors.shape[1] == self._dimension
        self._index.add(vectors.astype(np.float32))
        self._id_map.extend(ids)

    def search(self, query_vector: np.ndarray, top_k: int) -> list[tuple[str, float]]:
        if self._index.ntotal == 0:
            return []
        k = min(top_k, self._index.ntotal)
        scores, indices = self._index.search(query_vector.astype(np.float32), k)
        results = []
        id_map_len = len(self._id_map)
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= id_map_len:
                # Defensive: ntotal can briefly outpace _id_map under
                # multi-process write contention (corrupted .ids file or
                # mid-save interruption). Skip rather than IndexError.
                continue
            results.append((self._id_map[idx], float(score)))
        return results

    def save(self, path: str) -> None:
        """Atomically persist the FAISS index + id map.

        Writes to ``path.tmp`` first, then ``os.replace`` to the final
        location. ``os.replace`` is atomic on POSIX and on Windows
        (Python 3.3+), so a kill / crash mid-write leaves the previous
        valid file at ``path`` intact — the partial write only damages
        the orphan ``.tmp`` file, which the next save overwrites.

        Why: the previous implementation called ``faiss.write_index``
        directly against ``path``, truncating the existing file before
        the new contents were fully written. A SIGTERM/SIGKILL during
        the ~100 MB write of a 30k-vector index left ``gaottt.faiss`` /
        ``gaottt.virtual.faiss`` as 0-byte stubs that the next startup
        could not load (``Error: 'ret == (1)' failed: read error``).
        Observed twice on 2026-05-14 during routine backend restarts;
        the virtual_faiss_save_loop fires every 60 s, so any kill
        roughly during that window risks corruption.
        """
        tmp = path + ".tmp"
        faiss.write_index(self._index, tmp)
        os.replace(tmp, path)

        id_map_path = path + ".ids"
        id_map_tmp = id_map_path + ".tmp"
        with open(id_map_tmp, "w") as f:
            for node_id in self._id_map:
                f.write(node_id + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(id_map_tmp, id_map_path)

    def load(self, path: str) -> None:
        if not os.path.exists(path):
            return
        # Defensive: a 0-byte file is the signature of an interrupted
        # atomic save. faiss.read_index() raises RuntimeError on it,
        # which would break engine.startup() before diagnostics could
        # intervene. Skip the read and leave the index empty — the
        # Stage 1 startup diagnostic (gaottt/diagnostics/startup.py)
        # detects the empty state + nonzero SQLite and triggers a
        # rebuild from the store.
        if os.path.getsize(path) == 0:
            return
        self._index = faiss.read_index(path)
        id_map_path = path + ".ids"
        if os.path.exists(id_map_path):
            with open(id_map_path) as f:
                self._id_map = [line.strip() for line in f if line.strip()]

    def search_by_id(self, node_id: str, top_k: int) -> list[tuple[str, float]]:
        """Search nearest neighbors of a specific node's embedding."""
        vecs = self.get_vectors([node_id])
        vec = vecs.get(node_id)
        if vec is None:
            return []
        return self.search(vec.reshape(1, -1), top_k)

    def get_vectors(self, ids: list[str]) -> dict[str, np.ndarray]:
        """Retrieve original embedding vectors by IDs."""
        if self._index.ntotal == 0:
            return {}
        id_to_idx = {nid: i for i, nid in enumerate(self._id_map)}
        indices_needed = [(node_id, id_to_idx[node_id]) for node_id in ids if node_id in id_to_idx]
        if not indices_needed:
            return {}
        # Read full matrix once
        all_vecs = faiss.rev_swig_ptr(
            self._index.get_xb(), self._index.ntotal * self._dimension
        )
        all_vecs = np.array(all_vecs).reshape(self._index.ntotal, self._dimension)
        return {node_id: all_vecs[idx].copy().astype(np.float32) for node_id, idx in indices_needed}

    def reset(self) -> None:
        self._index = faiss.IndexFlatIP(self._dimension)
        self._id_map = []
