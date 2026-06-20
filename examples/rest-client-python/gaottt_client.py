"""Minimal GaOTTT REST client.

A small, dependency-light wrapper around the GaOTTT REST API
(``gaottt.server.app:app``). Use this when you want to give your own
application (running in a separate process / repo) a long-term-memory
backend without going through MCP.

The wrapper covers the endpoints most apps need day-to-day:
remember / recall / query / explore / index / relations / forget /
restore / revalidate / reflect / compact. For everything else, hit the
REST API directly — full schema is at ``http://<host>:<port>/docs``.

Example:
    >>> from gaottt_client import GaOTTTClient
    >>> c = GaOTTTClient("http://localhost:8001")
    >>> res = c.remember("deploy script lives in scripts/deploy.sh")
    >>> res["id"]
    'a1b2c3...'
    >>> hits = c.recall("where is the deploy script?", top_k=3)
    >>> hits["items"][0]["content"]
    'deploy script lives in scripts/deploy.sh'

See ``example_usage.py`` for end-to-end demos.
"""

from __future__ import annotations

from typing import Any

import httpx


class GaOTTTError(RuntimeError):
    """Raised when the server returns a non-2xx response."""

    def __init__(self, status_code: int, payload: Any):
        super().__init__(f"GaOTTT {status_code}: {payload}")
        self.status_code = status_code
        self.payload = payload


class GaOTTTClient:
    """Thin REST client.

    Args:
        base_url:   e.g. ``http://localhost:8001`` (no trailing slash).
        api_key:    Optional bearer token. The stock GaOTTT REST server has
                    no auth — this is only useful when you've put an auth
                    proxy (Caddy / nginx) in front of it.
        timeout:    Per-request timeout in seconds. ``/recall`` against a
                    cold cache can take a few seconds on first hit; 30s is
                    a safe default.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8001",
        *,
        api_key: str | None = None,
        timeout: float = 30.0,
    ):
        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout,
        )

    # ----------------------------- lifecycle -----------------------------

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "GaOTTTClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ----------------------------- helpers --------------------------------

    def _post(
        self,
        path: str,
        json: dict[str, Any] | None = None,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        r = self._client.post(path, json=json or {}, params=params or {})
        if r.status_code >= 400:
            try:
                payload = r.json()
            except Exception:
                payload = r.text
            raise GaOTTTError(r.status_code, payload)
        return r.json()

    def _get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        r = self._client.get(path, params=params or {})
        if r.status_code >= 400:
            try:
                payload = r.json()
            except Exception:
                payload = r.text
            raise GaOTTTError(r.status_code, payload)
        return r.json()

    # --------------------------- core memory ------------------------------

    def remember(
        self,
        content: str,
        *,
        source: str = "agent",
        tags: list[str] | None = None,
        context: str | None = None,
        ttl_seconds: float | None = None,
        emotion: float = 0.0,
        certainty: float = 1.0,
    ) -> dict[str, Any]:
        """Store a single memory. Returns ``{id, duplicate, expires_at}``.

        ``id`` is ``None`` when the input was deduplicated against an
        existing node (check ``duplicate`` in that case).
        """
        body: dict[str, Any] = {"content": content, "source": source}
        if tags is not None:
            body["tags"] = tags
        if context is not None:
            body["context"] = context
        if ttl_seconds is not None:
            body["ttl_seconds"] = ttl_seconds
        body["emotion"] = emotion
        body["certainty"] = certainty
        return self._post("/remember", body)

    def recall(
        self,
        query: str,
        *,
        top_k: int = 5,
        source_filter: list[str] | None = None,
        tag_filter: list[str] | None = None,
        persona_context: list[str] | None = None,
        wave_depth: int | None = None,
        wave_k: int | None = None,
        force_refresh: bool = False,
        auto_route: bool = True,
        mode: str = "detail",
        passive: bool = False,
    ) -> dict[str, Any]:
        """Gravity-biased retrieval. Prefer this over ``query()``."""
        body: dict[str, Any] = {
            "query": query,
            "top_k": top_k,
            "force_refresh": force_refresh,
            "auto_route": auto_route,
            "mode": mode,
            "passive": passive,
        }
        if source_filter is not None:
            body["source_filter"] = source_filter
        if tag_filter is not None:
            body["tag_filter"] = tag_filter
        if persona_context is not None:
            body["persona_context"] = persona_context
        if wave_depth is not None:
            body["wave_depth"] = wave_depth
        if wave_k is not None:
            body["wave_k"] = wave_k
        return self._post("/recall", body)

    def query(
        self,
        text: str,
        *,
        top_k: int = 10,
    ) -> dict[str, Any]:
        """Legacy raw-FAISS search (no gravity bias, no cache).

        Useful as a comparison baseline against ``recall()``. New code
        should default to ``recall()``.
        """
        return self._post("/query", {"text": text, "top_k": top_k})

    def explore(
        self,
        query: str,
        *,
        top_k: int = 10,
        diversity: float = 0.5,
        tag_filter: list[str] | None = None,
        mode: str = "serendipity",
    ) -> dict[str, Any]:
        """Serendipity / dormant exploration. Higher ``diversity`` =>
        more random spread."""
        body: dict[str, Any] = {
            "query": query,
            "top_k": top_k,
            "diversity": diversity,
            "mode": mode,
        }
        if tag_filter is not None:
            body["tag_filter"] = tag_filter
        return self._post("/explore", body)

    # ----------------------------- bulk write -----------------------------

    def index(
        self,
        documents: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Batch-insert pre-chunked documents.

        Each item should look like ``{"content": "...", "metadata": {...}}``.
        ``metadata`` is free-form; common keys are ``source``, ``tags``
        (list[str]), ``file_path``, ``original_id`` (for Phase M
        self-force filtering — set this when chunks come from the same
        source file so intra-file mass inflation is suppressed).
        """
        if not documents:
            raise ValueError("index() requires at least one document")
        return self._post("/index", {"documents": documents})

    # ----------------------------- maintenance ----------------------------

    def forget(self, node_ids: list[str], *, hard: bool = False) -> dict[str, Any]:
        """Soft-archive (default) or hard-delete nodes."""
        return self._post("/forget", {"node_ids": node_ids, "hard": hard})

    def restore(self, node_ids: list[str]) -> dict[str, Any]:
        """Reverse a soft-forget."""
        return self._post("/restore", {"node_ids": node_ids})

    def revalidate(
        self,
        node_id: str,
        *,
        certainty: float | None = None,
        emotion: float | None = None,
    ) -> dict[str, Any]:
        """Refresh certainty decay-clock. Call when you re-confirm a fact."""
        body: dict[str, Any] = {"node_id": node_id}
        if certainty is not None:
            body["certainty"] = certainty
        if emotion is not None:
            body["emotion"] = emotion
        return self._post("/revalidate", body)

    def compact(
        self,
        *,
        expire_ttl: bool = True,
        rebuild_faiss: bool = False,
    ) -> dict[str, Any]:
        """Maintenance: expire TTL'd nodes, optionally rebuild FAISS."""
        return self._post("/compact", {
            "expire_ttl": expire_ttl,
            "rebuild_faiss": rebuild_faiss,
        })

    # ------------------------------ relations -----------------------------

    def relate(
        self,
        src_id: str,
        dst_id: str,
        edge_type: str,
        *,
        weight: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a directed edge. Reserved types: ``supersedes``,
        ``derived_from``, ``contradicts`` — but custom strings work too."""
        body: dict[str, Any] = {
            "src_id": src_id,
            "dst_id": dst_id,
            "edge_type": edge_type,
            "weight": weight,
        }
        if metadata is not None:
            body["metadata"] = metadata
        return self._post("/relations", body)

    def unrelate(
        self,
        src_id: str,
        dst_id: str,
        *,
        edge_type: str | None = None,
    ) -> dict[str, Any]:
        # DELETE /relations takes src_id / dst_id / edge_type as **query
        # parameters** (see gaottt/server/app.py:delete_relation), not a
        # JSON body. Sending a body yields 422.
        params: dict[str, Any] = {"src_id": src_id, "dst_id": dst_id}
        if edge_type is not None:
            params["edge_type"] = edge_type
        r = self._client.request("DELETE", "/relations", params=params)
        if r.status_code >= 400:
            try:
                payload = r.json()
            except Exception:
                payload = r.text
            raise GaOTTTError(r.status_code, payload)
        return r.json()

    def get_relations(
        self,
        node_id: str,
        *,
        edge_type: str | None = None,
        direction: str = "out",
    ) -> dict[str, Any]:
        """List relations for a node. direction ∈ {out, in, both}."""
        params: dict[str, Any] = {"direction": direction}
        if edge_type is not None:
            params["edge_type"] = edge_type
        return self._get(f"/relations/{node_id}", params=params)

    # ------------------------------ read ----------------------------------

    def get_node(self, node_id: str) -> dict[str, Any]:
        """Physical state only (mass / temperature / displacement_norm)."""
        return self._get(f"/node/{node_id}")

    def get_node_detail(self, node_id: str) -> dict[str, Any]:
        """Content + metadata + physical state."""
        return self._get(f"/node/{node_id}/detail")

    # ------------------------------ reflect -------------------------------

    def reflect(self, aspect: str, **kwargs: Any) -> dict[str, Any]:
        """Call any ``/reflect/<aspect>`` endpoint.

        Aspects: summary, hot_topics, connections, dormant, duplicates,
        relations, tasks_todo, tasks_doing, tasks_completed,
        tasks_abandoned, commitments, intentions, values, relationships,
        persona.

        Options (``limit``, ``threshold``, ``bucket``, ...) are passed as
        **query parameters** — the reflect endpoints declare them as
        function args on the FastAPI side, not as request-body fields.
        """
        # Drop None values so we don't send explicit "?key=None" strings.
        params = {k: v for k, v in kwargs.items() if v is not None}
        return self._post(f"/reflect/{aspect}", params=params)

    def summary(self) -> dict[str, Any]:
        """Shorthand for ``reflect("summary")``."""
        return self._post("/reflect/summary")

    def hot_topics(self, *, limit: int = 10) -> dict[str, Any]:
        return self._post("/reflect/hot_topics", params={"limit": limit})
