from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

import aiosqlite
import msgpack
import numpy as np

from gaottt.core.types import CooccurrenceEdge, DirectedEdge, NodeState
from gaottt.store.base import StoreBase

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id           TEXT PRIMARY KEY,
    content      TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    metadata     TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_content_hash ON documents(content_hash);

CREATE TABLE IF NOT EXISTS nodes (
    id               TEXT PRIMARY KEY,
    mass             REAL DEFAULT 1.0,
    temperature      REAL DEFAULT 0.0,
    last_access      REAL,
    sim_history      BLOB,
    displacement     BLOB,
    velocity         BLOB,
    return_count     REAL DEFAULT 0.0,
    expires_at       REAL,
    is_archived      INTEGER DEFAULT 0,
    merged_into      TEXT,
    merge_count      INTEGER DEFAULT 0,
    merged_at        REAL,
    emotion_weight   REAL DEFAULT 0.0,
    certainty        REAL DEFAULT 1.0,
    last_verified_at REAL,
    rev              INTEGER DEFAULT 0
);
-- Indexes for archive/TTL/merge columns are created post-migration in initialize(),
-- so older DBs that need ALTER TABLE first can still bootstrap cleanly.

CREATE TABLE IF NOT EXISTS edges (
    src         TEXT,
    dst         TEXT,
    weight      REAL DEFAULT 0.0,
    last_update REAL,
    PRIMARY KEY (src, dst)
);

CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);

CREATE TABLE IF NOT EXISTS directed_edges (
    src         TEXT NOT NULL,
    dst         TEXT NOT NULL,
    edge_type   TEXT NOT NULL,
    weight      REAL DEFAULT 1.0,
    created_at  REAL,
    metadata    TEXT,
    PRIMARY KEY (src, dst, edge_type)
);

CREATE INDEX IF NOT EXISTS idx_directed_src ON directed_edges(src);
CREATE INDEX IF NOT EXISTS idx_directed_dst ON directed_edges(dst);
CREATE INDEX IF NOT EXISTS idx_directed_type ON directed_edges(edge_type);
CREATE INDEX IF NOT EXISTS idx_directed_created ON directed_edges(created_at);
"""


class SqliteStore(StoreBase):
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self._conn = await aiosqlite.connect(self._db_path)
        await self._conn.execute("PRAGMA journal_mode = WAL")
        await self._conn.execute("PRAGMA synchronous = NORMAL")
        # Multi-process safety: when several MCP servers (e.g. one per agent
        # terminal) share the same DB, write-lock contention is normal. Wait
        # up to 30 s for a lock instead of raising "database is locked"
        # immediately. WAL keeps reads non-blocking; this only affects writes.
        await self._conn.execute("PRAGMA busy_timeout = 30000")
        # Keep the WAL from growing unbounded under sustained multi-process
        # write load. Default is 1000 pages (~4 MB); we let WAL get a bit
        # larger for throughput, but an explicit autocheckpoint keeps it bounded.
        await self._conn.execute("PRAGMA wal_autocheckpoint = 2000")
        await self._conn.executescript(SCHEMA)
        # Migrate: add columns if missing (older DBs)
        for col, col_type in [
            ("displacement", "BLOB"),
            ("velocity", "BLOB"),
            ("return_count", "REAL DEFAULT 0.0"),
            ("expires_at", "REAL"),
            ("is_archived", "INTEGER DEFAULT 0"),
            ("merged_into", "TEXT"),
            ("merge_count", "INTEGER DEFAULT 0"),
            ("merged_at", "REAL"),
            ("emotion_weight", "REAL DEFAULT 0.0"),
            ("certainty", "REAL DEFAULT 1.0"),
            ("last_verified_at", "REAL"),
            ("rev", "INTEGER DEFAULT 0"),
        ]:
            try:
                await self._conn.execute(f"SELECT {col} FROM nodes LIMIT 1")
            except aiosqlite.OperationalError:
                await self._conn.execute(f"ALTER TABLE nodes ADD COLUMN {col} {col_type}")
        # Indexes that may be missing on older DBs
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_nodes_archived ON nodes(is_archived)"
        )
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_nodes_expires_at ON nodes(expires_at)"
        )
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_nodes_merged_into ON nodes(merged_into)"
        )
        # Phase D: ordering completed/abandoned tasks by recency
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_directed_created ON directed_edges(created_at)"
        )
        await self._conn.commit()

    @staticmethod
    def _content_hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    # M1 — SQLite default ``SQLITE_MAX_VARIABLE_NUMBER`` is 999 (host-build
    # dependent, can be 32766 on newer libs but we cannot assume). Any
    # ``IN (?,?,...)`` with more than 999 params raises ``sqlite3.OperationalError:
    # too many SQL variables`` mid-query, after the work has partially started
    # if part of a transaction. Chunking at 900 leaves headroom for callers
    # who pass ``[*ids, *ids]`` (e.g., ``hard_delete_nodes`` ``src IN OR dst IN``).
    _IN_CHUNK_SIZE = 900

    @staticmethod
    def _in_chunks(items: list[str], chunk_size: int = _IN_CHUNK_SIZE) -> list[list[str]]:
        """Split a list of bind values into chunks small enough for SQLite's
        variable limit. Returns the original list as a single chunk if it
        already fits, so the common short-list path stays one query."""
        if len(items) <= chunk_size:
            return [items]
        return [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]

    async def find_existing_hashes(self, hashes: list[str]) -> set[str]:
        """Return the subset of content hashes that already exist in the DB."""
        assert self._conn is not None
        if not hashes:
            return set()
        found: set[str] = set()
        for chunk in self._in_chunks(hashes):
            placeholders = ",".join("?" for _ in chunk)
            cursor = await self._conn.execute(
                f"SELECT content_hash FROM documents WHERE content_hash IN ({placeholders})",
                chunk,
            )
            async for row in cursor:
                found.add(row[0])
        return found

    async def save_documents(self, docs: list[dict[str, Any]]) -> None:
        assert self._conn is not None
        await self._conn.executemany(
            "INSERT OR IGNORE INTO documents (id, content, content_hash, metadata) VALUES (?, ?, ?, ?)",
            [
                (
                    d["id"],
                    d["content"],
                    self._content_hash(d["content"]),
                    json.dumps(d.get("metadata")) if d.get("metadata") else None,
                )
                for d in docs
            ],
        )
        await self._conn.commit()

    async def get_document(self, doc_id: str) -> dict[str, Any] | None:
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT id, content, metadata FROM documents WHERE id = ?", (doc_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "content": row[1],
            "metadata": json.loads(row[2]) if row[2] else None,
        }

    async def get_all_contents(self) -> dict[str, str]:
        """Bulk fetch {id: content} for all documents. Phase L Stage 1 uses
        this at engine startup to build the BM25 lexical index in-memory.
        Archived/expired filtering is applied by the engine layer via
        cache.node_cache, not here."""
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT id, content FROM documents WHERE content IS NOT NULL"
        )
        rows = await cursor.fetchall()
        return {row[0]: row[1] for row in rows if row[1]}

    async def get_all_sources(self) -> dict[str, str]:
        """Bulk fetch {id: metadata.source} via SQLite's JSON1 extension.

        Skips rows where source is missing. Phase H Stage 2 uses this at
        cache load time to populate `cache.source_by_id`, enabling
        source_filter to be applied at the wave seed step without paying
        a per-node store fetch.
        """
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT id, json_extract(metadata, '$.source') "
            "FROM documents WHERE metadata IS NOT NULL"
        )
        rows = await cursor.fetchall()
        return {row[0]: row[1] for row in rows if row[1] is not None}

    async def get_all_originals(self) -> dict[str, str]:
        """Bulk fetch {id: original_id} via SQLite's JSON1 extension.

        Phase M Stage 1: used at cache load to populate
        ``cache.original_id_by_id`` so the self-force check in the mass-update
        path can skip same-document co-occurrence contributions without
        per-node store fetches.

        ``COALESCE(metadata.original_id, metadata.file_path)`` so existing
        ingested books — which set ``file_path`` but not ``original_id`` —
        are covered without a DB migration. Same-file chunks therefore share
        the file path as their group key, which is what the Phase M inflation
        analysis (1 file = 91 chunks) needs to detect.
        """
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT id, "
            "COALESCE("
            "json_extract(metadata, '$.original_id'), "
            "json_extract(metadata, '$.file_path')"
            ") "
            "FROM documents WHERE metadata IS NOT NULL"
        )
        rows = await cursor.fetchall()
        return {row[0]: row[1] for row in rows if row[1] is not None}

    async def get_all_cohorts(self) -> dict[str, str]:
        """Bulk fetch {id: metadata.cohort_id} via SQLite's JSON1 extension.

        Phase M Stage 1: cohort_id is assigned per supernova batch in
        ``engine._apply_supernova_cohort`` so all nodes born in the same
        Phase K event share it. Loaded into ``cache.cohort_id_by_id`` at
        startup for the self-force check.
        """
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT id, json_extract(metadata, '$.cohort_id') "
            "FROM documents WHERE metadata IS NOT NULL "
            "AND json_extract(metadata, '$.cohort_id') IS NOT NULL"
        )
        rows = await cursor.fetchall()
        return {row[0]: row[1] for row in rows if row[1] is not None}

    async def get_all_tags(self) -> dict[str, list[str]]:
        """Bulk fetch {id: list of tag strings} via SQLite's JSON1 extension.

        Phase J Stage 2 uses this at cache load time to populate
        ``cache.tags_by_id``, enabling tag_filter to be applied at the
        wave seed step (additive injection) without per-node store fetches.

        Documents with no ``tags`` field or with a non-list value are
        skipped. Returns only non-empty tag lists.
        """
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT id, json_extract(metadata, '$.tags') "
            "FROM documents WHERE metadata IS NOT NULL "
            "AND json_extract(metadata, '$.tags') IS NOT NULL"
        )
        rows = await cursor.fetchall()
        result: dict[str, list[str]] = {}
        for nid, tags_json in rows:
            if tags_json is None:
                continue
            try:
                tags = json.loads(tags_json) if isinstance(tags_json, str) else tags_json
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(tags, list) and tags:
                # Defensive: keep only string tags
                clean_tags = [t for t in tags if isinstance(t, str)]
                if clean_tags:
                    result[nid] = clean_tags
        return result

    _NODE_COLS = (
        "id, mass, temperature, last_access, sim_history, return_count, "
        "expires_at, is_archived, merged_into, merge_count, merged_at, "
        "emotion_weight, certainty, last_verified_at, rev"
    )

    async def save_node_states(self, states: list[NodeState]) -> None:
        assert self._conn is not None
        # NOTE: must NOT use `INSERT OR REPLACE`. On a PRIMARY KEY conflict
        # SQLite's REPLACE is a DELETE-then-INSERT, so every column absent
        # from `_NODE_COLS` (notably `displacement` / `velocity`, which are
        # persisted separately by save_displacements/save_velocities) is
        # reset to its schema default (NULL). A node flushed because mass /
        # last_access changed but whose displacement did not change this
        # cycle would silently lose its accumulated orbital position on the
        # next load_from_store — destroying the Phase I/J/K query-attraction
        # field. Use a column-scoped upsert (SQLite >= 3.24, bundled with
        # Python 3.11+) so untouched columns are preserved on conflict and
        # default NULL only on a genuinely-new insert.
        _set_clause = ", ".join(
            f"{c}=excluded.{c}"
            for c in (col.strip() for col in self._NODE_COLS.split(","))
            if c != "id"
        )
        # H2 — last-write-wins guard. The DB is shared across processes,
        # each with its own cache. A process holding a STALE NodeState that
        # keeps flushing would otherwise reverse-overwrite values another
        # process advanced (the documented "逆方向上書き罠"). ``rev`` is a
        # monotonic per-node counter bumped by cache.set_node; only accept
        # the write when ours is at least as new as what's stored. A stale
        # flush becomes a no-op row instead of silent corruption — and is
        # observable via the changed-row count below.
        _placeholders = ", ".join("?" for _ in self._NODE_COLS.split(","))
        before = self._conn.total_changes
        await self._conn.executemany(
            f"INSERT INTO nodes ({self._NODE_COLS}) "
            f"VALUES ({_placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {_set_clause} "
            "WHERE excluded.rev >= nodes.rev",
            [
                (
                    s.id, s.mass, s.temperature, s.last_access,
                    msgpack.packb(s.sim_history), s.return_count,
                    s.expires_at, 1 if s.is_archived else 0,
                    s.merged_into, s.merge_count, s.merged_at,
                    s.emotion_weight, s.certainty, s.last_verified_at, s.rev,
                )
                for s in states
            ],
        )
        await self._conn.commit()
        skipped = len(states) - (self._conn.total_changes - before)
        if skipped > 0:
            logger.warning(
                "save_node_states: %d/%d node writes skipped — a newer "
                "revision is already persisted (stale cross-process flush "
                "rejected, last-write-wins)",
                skipped, len(states),
            )

    @staticmethod
    def _row_to_node_state(row: tuple) -> NodeState:
        sim_history = msgpack.unpackb(row[4]) if row[4] else []
        return NodeState(
            id=row[0],
            mass=row[1] if row[1] is not None else 1.0,
            temperature=row[2] if row[2] is not None else 0.0,
            last_access=row[3] if row[3] is not None else time.time(),
            sim_history=sim_history,
            return_count=row[5] if row[5] is not None else 0.0,
            expires_at=row[6] if len(row) > 6 else None,
            is_archived=bool(row[7]) if len(row) > 7 and row[7] is not None else False,
            merged_into=row[8] if len(row) > 8 else None,
            merge_count=int(row[9]) if len(row) > 9 and row[9] is not None else 0,
            merged_at=row[10] if len(row) > 10 else None,
            emotion_weight=row[11] if len(row) > 11 and row[11] is not None else 0.0,
            certainty=row[12] if len(row) > 12 and row[12] is not None else 1.0,
            last_verified_at=row[13] if len(row) > 13 else None,
            rev=int(row[14]) if len(row) > 14 and row[14] is not None else 0,
        )

    async def get_node_states(self, ids: list[str]) -> dict[str, NodeState]:
        assert self._conn is not None
        if not ids:
            return {}
        result: dict[str, NodeState] = {}
        for chunk in self._in_chunks(ids):
            placeholders = ",".join("?" for _ in chunk)
            cursor = await self._conn.execute(
                f"SELECT {self._NODE_COLS} FROM nodes WHERE id IN ({placeholders})",
                chunk,
            )
            async for row in cursor:
                result[row[0]] = self._row_to_node_state(row)
        return result

    async def get_all_node_states(self) -> list[NodeState]:
        assert self._conn is not None
        cursor = await self._conn.execute(
            f"SELECT {self._NODE_COLS} FROM nodes"
        )
        states = []
        async for row in cursor:
            states.append(self._row_to_node_state(row))
        return states

    async def save_edges(self, edges: list[CooccurrenceEdge]) -> None:
        assert self._conn is not None
        await self._conn.executemany(
            "INSERT OR REPLACE INTO edges (src, dst, weight, last_update) VALUES (?, ?, ?, ?)",
            [(e.src, e.dst, e.weight, e.last_update) for e in edges],
        )
        await self._conn.commit()

    async def delete_edges(self, pairs: list[tuple[str, str]]) -> int:
        assert self._conn is not None
        if not pairs:
            return 0
        normalized = [(min(a, b), max(a, b)) for a, b in pairs]
        total = 0
        for src, dst in normalized:
            cursor = await self._conn.execute(
                "DELETE FROM edges WHERE src = ? AND dst = ?", (src, dst),
            )
            total += cursor.rowcount or 0
        await self._conn.commit()
        return total

    async def get_edges_for_node(self, node_id: str) -> list[CooccurrenceEdge]:
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT src, dst, weight, last_update FROM edges WHERE src = ? OR dst = ?",
            (node_id, node_id),
        )
        edges = []
        async for row in cursor:
            edges.append(
                CooccurrenceEdge(src=row[0], dst=row[1], weight=row[2], last_update=row[3])
            )
        return edges

    async def get_all_edges(self) -> list[CooccurrenceEdge]:
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT src, dst, weight, last_update FROM edges"
        )
        edges = []
        async for row in cursor:
            edges.append(
                CooccurrenceEdge(src=row[0], dst=row[1], weight=row[2], last_update=row[3])
            )
        return edges

    async def save_displacements(self, displacements: dict[str, np.ndarray]) -> None:
        # M4 — coerce to contiguous float32 before serialization. Without
        # this, a caller passing float64 (numpy default for `np.zeros(dim)`)
        # silently writes 2× bytes per element, and ``load_displacements``
        # reads it back via ``np.frombuffer(..., dtype=np.float32)``
        # producing garbage (half the values are misaligned high-bits).
        # Same fix mirrored for ``save_velocities`` below.
        assert self._conn is not None
        await self._conn.executemany(
            "UPDATE nodes SET displacement = ? WHERE id = ?",
            [
                (
                    np.ascontiguousarray(disp, dtype=np.float32).tobytes(),
                    node_id,
                )
                for node_id, disp in displacements.items()
            ],
        )
        await self._conn.commit()

    async def load_displacements(
        self, ids: list[str] | None = None,
    ) -> dict[str, np.ndarray]:
        assert self._conn is not None
        result: dict[str, np.ndarray] = {}
        if ids is not None:
            if not ids:
                return {}
            for chunk in self._in_chunks(ids):
                placeholders = ",".join("?" for _ in chunk)
                cursor = await self._conn.execute(
                    f"SELECT id, displacement FROM nodes "
                    f"WHERE displacement IS NOT NULL AND id IN ({placeholders})",
                    chunk,
                )
                async for row in cursor:
                    result[row[0]] = np.frombuffer(row[1], dtype=np.float32).copy()
        else:
            cursor = await self._conn.execute(
                "SELECT id, displacement FROM nodes WHERE displacement IS NOT NULL"
            )
            async for row in cursor:
                result[row[0]] = np.frombuffer(row[1], dtype=np.float32).copy()
        return result

    async def save_velocities(self, velocities: dict[str, np.ndarray]) -> None:
        # M4 — see ``save_displacements`` above for the dtype guard rationale.
        assert self._conn is not None
        await self._conn.executemany(
            "UPDATE nodes SET velocity = ? WHERE id = ?",
            [
                (
                    np.ascontiguousarray(vel, dtype=np.float32).tobytes(),
                    node_id,
                )
                for node_id, vel in velocities.items()
            ],
        )
        await self._conn.commit()

    async def load_velocities(
        self, ids: list[str] | None = None,
    ) -> dict[str, np.ndarray]:
        assert self._conn is not None
        result: dict[str, np.ndarray] = {}
        if ids is not None:
            if not ids:
                return {}
            for chunk in self._in_chunks(ids):
                placeholders = ",".join("?" for _ in chunk)
                cursor = await self._conn.execute(
                    f"SELECT id, velocity FROM nodes "
                    f"WHERE velocity IS NOT NULL AND id IN ({placeholders})",
                    chunk,
                )
                async for row in cursor:
                    result[row[0]] = np.frombuffer(row[1], dtype=np.float32).copy()
        else:
            cursor = await self._conn.execute(
                "SELECT id, velocity FROM nodes WHERE velocity IS NOT NULL"
            )
            async for row in cursor:
                result[row[0]] = np.frombuffer(row[1], dtype=np.float32).copy()
        return result

    async def reset_orbital_state(self) -> int:
        """Phase M Stage 1 — clear displacement + velocity columns for every
        node, wiping the runtime trace of the legacy co-occurrence BH
        (which pulled nodes toward neighbor centroids via
        ``compute_acceleration`` 第 3 項 — now replaced by mass-threshold
        BH that is dormant until mass crosses θ).

        Idempotent — re-running the SQL UPDATE on already-NULL columns is
        a no-op. Returns the row count touched (i.e., all node rows).
        """
        assert self._conn is not None
        await self._conn.execute(
            "UPDATE nodes SET displacement = NULL, velocity = NULL"
        )
        cursor = await self._conn.execute("SELECT COUNT(*) FROM nodes")
        row = await cursor.fetchone()
        await self._conn.commit()
        return row[0] if row else 0

    async def reset_masses(self, value: float = 1.0) -> int:
        """Phase M Stage 1 — reset every node's mass without disturbing the
        rest of the dynamic state.

        Used as a maintainer operation when the underlying mass-accumulation
        rule changes (e.g., switching on ``mass_conservation_enabled``) so
        the new rule observes a clean slate. Returns the number of nodes
        updated.
        """
        assert self._conn is not None
        await self._conn.execute("UPDATE nodes SET mass = ?", (value,))
        cursor = await self._conn.execute("SELECT COUNT(*) FROM nodes")
        row = await cursor.fetchone()
        await self._conn.commit()
        return row[0] if row else 0

    async def reset_dynamic_state(self) -> tuple[int, int]:
        assert self._conn is not None
        cursor = await self._conn.execute("SELECT COUNT(*) FROM nodes")
        row = await cursor.fetchone()
        nodes_count = row[0] if row else 0

        cursor = await self._conn.execute("SELECT COUNT(*) FROM edges")
        row = await cursor.fetchone()
        edges_count = row[0] if row else 0

        # M3 — wrap multi-statement destructive op so a mid-sequence
        # exception (SIGTERM, disk full, etc.) rolls back the whole batch
        # instead of leaving the DB partially mutated (e.g., nodes reset
        # but edges still present, or vice versa).
        try:
            await self._conn.execute(
                "UPDATE nodes SET mass = 1.0, temperature = 0.0, last_access = NULL, "
                "sim_history = NULL, displacement = NULL, velocity = NULL, return_count = 0.0, "
                "expires_at = NULL, is_archived = 0, "
                "merged_into = NULL, merge_count = 0, merged_at = NULL, "
                "emotion_weight = 0.0, certainty = 1.0, last_verified_at = NULL"
            )
            await self._conn.execute("DELETE FROM edges")
            await self._conn.execute("DELETE FROM directed_edges")
            await self._conn.commit()
        except Exception:
            await self._conn.rollback()
            raise
        return nodes_count, edges_count

    # --- Archive / delete (F4 + F5) ---

    async def set_archived(self, node_ids: list[str], archived: bool) -> int:
        """Soft-delete: flip is_archived flag. Returns count of affected rows."""
        assert self._conn is not None
        if not node_ids:
            return 0
        flag = 1 if archived else 0
        affected = 0
        try:
            for chunk in self._in_chunks(node_ids):
                placeholders = ",".join("?" for _ in chunk)
                cursor = await self._conn.execute(
                    f"UPDATE nodes SET is_archived = ? WHERE id IN ({placeholders})",
                    [flag, *chunk],
                )
                affected += cursor.rowcount or 0
            await self._conn.commit()
        except Exception:
            await self._conn.rollback()
            raise
        return affected

    async def hard_delete_nodes(self, node_ids: list[str]) -> int:
        """Physically delete nodes, their documents, and any edges touching them.

        M3 — wraps the 4-statement delete sequence in an explicit
        try/commit/rollback so a mid-sequence exception (e.g., SIGTERM
        between DELETE edges and DELETE nodes) doesn't leave dangling
        edge rows pointing at deleted-but-not-quite nodes.

        M1 — chunks ``IN (?,?,...)`` lists so large deletions don't trip
        SQLite's 999-variable limit. The ``src IN (...) OR dst IN (...)``
        edges/directed_edges statements double the bind count, so they use
        a 450-chunk size; the single-IN nodes/documents statements use the
        standard 900. All chunks share one transaction (commit at the end,
        rollback on any failure), preserving the atomicity guarantee.
        """
        assert self._conn is not None
        if not node_ids:
            return 0
        deleted = 0
        try:
            for chunk in self._in_chunks(node_ids, self._IN_CHUNK_SIZE // 2):
                placeholders = ",".join("?" for _ in chunk)
                await self._conn.execute(
                    f"DELETE FROM edges "
                    f"WHERE src IN ({placeholders}) OR dst IN ({placeholders})",
                    [*chunk, *chunk],
                )
                await self._conn.execute(
                    f"DELETE FROM directed_edges "
                    f"WHERE src IN ({placeholders}) OR dst IN ({placeholders})",
                    [*chunk, *chunk],
                )
            for chunk in self._in_chunks(node_ids):
                placeholders = ",".join("?" for _ in chunk)
                cursor = await self._conn.execute(
                    f"DELETE FROM nodes WHERE id IN ({placeholders})", chunk,
                )
                deleted += cursor.rowcount or 0
                await self._conn.execute(
                    f"DELETE FROM documents WHERE id IN ({placeholders})", chunk,
                )
            await self._conn.commit()
        except Exception:
            await self._conn.rollback()
            raise
        return deleted

    # --- F3: Directed (typed) edges ---

    async def upsert_directed_edge(self, edge: DirectedEdge) -> None:
        assert self._conn is not None
        await self._conn.execute(
            "INSERT OR REPLACE INTO directed_edges "
            "(src, dst, edge_type, weight, created_at, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                edge.src, edge.dst, edge.edge_type, edge.weight, edge.created_at,
                json.dumps(edge.metadata, ensure_ascii=False) if edge.metadata else None,
            ),
        )
        await self._conn.commit()

    async def delete_directed_edge(
        self, src: str, dst: str, edge_type: str | None = None,
    ) -> int:
        assert self._conn is not None
        if edge_type is None:
            cursor = await self._conn.execute(
                "DELETE FROM directed_edges WHERE src = ? AND dst = ?", (src, dst),
            )
        else:
            cursor = await self._conn.execute(
                "DELETE FROM directed_edges WHERE src = ? AND dst = ? AND edge_type = ?",
                (src, dst, edge_type),
            )
        await self._conn.commit()
        return cursor.rowcount or 0

    async def get_directed_edges(
        self,
        node_id: str | None = None,
        edge_type: str | None = None,
        direction: str = "out",
    ) -> list[DirectedEdge]:
        """Fetch directed edges. ``direction`` is 'out' (src=node), 'in' (dst=node), or 'both'.

        With ``node_id=None`` returns every edge (filtered by edge_type if given).
        """
        assert self._conn is not None
        clauses: list[str] = []
        params: list = []
        if node_id is not None:
            if direction == "out":
                clauses.append("src = ?")
                params.append(node_id)
            elif direction == "in":
                clauses.append("dst = ?")
                params.append(node_id)
            elif direction == "both":
                clauses.append("(src = ? OR dst = ?)")
                params.extend([node_id, node_id])
            else:
                raise ValueError(f"Unknown direction: {direction!r}")
        if edge_type is not None:
            clauses.append("edge_type = ?")
            params.append(edge_type)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        cursor = await self._conn.execute(
            f"SELECT src, dst, edge_type, weight, created_at, metadata "
            f"FROM directed_edges{where}",
            params,
        )
        edges: list[DirectedEdge] = []
        async for row in cursor:
            metadata = json.loads(row[5]) if row[5] else None
            edges.append(DirectedEdge(
                src=row[0], dst=row[1], edge_type=row[2],
                weight=row[3] if row[3] is not None else 1.0,
                created_at=row[4] if row[4] is not None else 0.0,
                metadata=metadata,
            ))
        return edges

    async def delete_directed_edges_for_node(self, node_id: str) -> int:
        """Drop all directed edges touching a node (used when hard-deleting)."""
        assert self._conn is not None
        cursor = await self._conn.execute(
            "DELETE FROM directed_edges WHERE src = ? OR dst = ?", (node_id, node_id),
        )
        await self._conn.commit()
        return cursor.rowcount or 0

    async def expire_due_nodes(self, now: float) -> int:
        """Mark nodes whose expires_at has passed as archived. Returns count."""
        assert self._conn is not None
        cursor = await self._conn.execute(
            "UPDATE nodes SET is_archived = 1 "
            "WHERE expires_at IS NOT NULL AND expires_at <= ? AND is_archived = 0",
            (now,),
        )
        await self._conn.commit()
        return cursor.rowcount or 0

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
