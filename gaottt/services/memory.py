"""Memory service — remember / recall / explore / forget / restore / revalidate.

Each function takes an engine and returns a Pydantic response model from
``gaottt.core.types``. The MCP server formats these into human-readable text
via ``gaottt.services.formatters``; the REST server returns them as JSON.
"""
from __future__ import annotations

import time
from typing import Any

from gaottt.core.engine import GaOTTTEngine
from gaottt.core.extractor import extract_candidates
from gaottt.core.types import (
    AutoRememberCandidate,
    AutoRememberResponse,
    ExploreResponse,
    ForgetResponse,
    MemoryItem,
    RecallResponse,
    RememberResponse,
    RestoreResponse,
    RevalidateResponse,
)


async def save_memory(
    engine: GaOTTTEngine,
    content: str,
    source: str,
    tags: list[str] | None = None,
    context: str | None = None,
    ttl_seconds: float | None = None,
    emotion: float = 0.0,
    certainty: float = 1.0,
    extra_metadata: dict[str, Any] | None = None,
) -> tuple[str | None, dict[str, Any]]:
    """Build a document dict, index it, and return (id_or_None, metadata).

    Shared by ``remember`` and Phase D commit/declare_* services.
    id is None when the content was a duplicate.
    """
    metadata: dict[str, Any] = {"source": source}
    if tags:
        metadata["tags"] = tags
    if context:
        metadata["context"] = context
    metadata["remembered_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    if extra_metadata:
        metadata.update(extra_metadata)

    expires_at: float | None = None
    if ttl_seconds is not None:
        expires_at = time.time() + ttl_seconds
    elif source == "hypothesis":
        expires_at = time.time() + engine.config.default_hypothesis_ttl_seconds
    elif source == "task":
        expires_at = time.time() + engine.config.default_task_ttl_seconds
    elif source == "commitment":
        expires_at = time.time() + engine.config.default_commitment_ttl_seconds

    doc: dict[str, Any] = {
        "content": content,
        "metadata": metadata,
        "emotion": emotion,
        "certainty": certainty,
    }
    if expires_at is not None:
        doc["expires_at"] = expires_at
        metadata["expires_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.localtime(expires_at)
        )

    ids = await engine.index_documents([doc])
    return (ids[0] if ids else None, metadata)


async def remember(
    engine: GaOTTTEngine,
    content: str,
    source: str = "agent",
    tags: list[str] | None = None,
    context: str | None = None,
    ttl_seconds: float | None = None,
    emotion: float = 0.0,
    certainty: float = 1.0,
) -> RememberResponse:
    new_id, metadata = await save_memory(
        engine, content=content, source=source, tags=tags, context=context,
        ttl_seconds=ttl_seconds, emotion=emotion, certainty=certainty,
    )
    if new_id is None:
        return RememberResponse(id=None, duplicate=True)
    return RememberResponse(
        id=new_id,
        duplicate=False,
        expires_at=metadata.get("expires_at"),
    )


def _to_memory_item(engine: GaOTTTEngine, r) -> MemoryItem:
    meta = r.metadata or {}
    source = meta.get("source", "unknown")
    tags = meta.get("tags") or []
    return MemoryItem(
        id=r.id,
        content=r.content,
        metadata=r.metadata,
        raw_score=r.raw_score,
        final_score=r.final_score,
        source=source,
        tags=list(tags),
        displacement_norm=engine.get_displacement_norm(r.id),
    )


async def recall(
    engine: GaOTTTEngine,
    query: str,
    top_k: int = 5,
    source_filter: list[str] | None = None,
    wave_depth: int | None = None,
    wave_k: int | None = None,
    force_refresh: bool = False,
    persona_context: list[str] | None = None,
    tag_filter: list[str] | None = None,
) -> RecallResponse:
    # Phase H Stage 2: source_filter is applied at the wave seed step inside
    # propagate_gravity_wave (engine.query → _query_internal). The post-filter
    # below remains as a defensive belt-and-suspenders pass.
    # Phase J Stage 2: persona_context / tag_filter are forwarded through
    # engine.query and applied as additive seed injection in the wave (they
    # bypass source_filter's restrictive semantic — the caller explicitly
    # asked for these tags or persona ids).
    raw = await engine.query(
        text=query,
        top_k=top_k * 10 if source_filter else top_k,
        wave_depth=wave_depth,
        wave_k=wave_k,
        use_cache=not force_refresh,
        source_filter=source_filter,
        persona_context=persona_context,
        tag_filter=tag_filter,
    )
    if source_filter:
        sf = set(source_filter)
        injected_set = set()
        if tag_filter or persona_context:
            # Re-derive what the wave would have injected, so we can
            # protect those from the defensive post-filter below.
            if tag_filter:
                injected_set |= engine.cache.find_ids_by_tag_filter(tag_filter)
            if persona_context:
                injected_set |= set(persona_context)
        filtered = []
        for r in raw:
            meta = r.metadata or {}
            if meta.get("source") in sf or r.id in injected_set:
                filtered.append(r)
        raw = filtered[:top_k]
    items = [_to_memory_item(engine, r) for r in raw]
    return RecallResponse(items=items, count=len(items))


async def explore(
    engine: GaOTTTEngine,
    query: str,
    diversity: float = 0.5,
    top_k: int = 10,
    persona_context: list[str] | None = None,
    tag_filter: list[str] | None = None,
) -> ExploreResponse:
    config = engine.config
    original_gamma = config.gamma
    config.gamma = config.gamma * (1.0 + diversity * 20.0)
    explore_depth = config.wave_max_depth + int(diversity * 2)
    explore_k = config.wave_initial_k + int(diversity * 4)

    try:
        raw = await engine.query(
            text=query, top_k=top_k,
            wave_depth=explore_depth, wave_k=explore_k,
            persona_context=persona_context,
            tag_filter=tag_filter,
        )
    finally:
        config.gamma = original_gamma

    items = [_to_memory_item(engine, r) for r in raw]
    return ExploreResponse(items=items, count=len(items), diversity=diversity)


async def forget(
    engine: GaOTTTEngine,
    node_ids: list[str],
    hard: bool = False,
) -> ForgetResponse:
    affected = await engine.forget(node_ids, hard=hard)
    return ForgetResponse(affected=affected, requested=len(node_ids), hard=hard)


async def restore(
    engine: GaOTTTEngine,
    node_ids: list[str],
) -> RestoreResponse:
    affected = await engine.restore(node_ids)
    return RestoreResponse(affected=affected, requested=len(node_ids))


async def revalidate(
    engine: GaOTTTEngine,
    node_id: str,
    certainty: float | None = None,
    emotion: float | None = None,
) -> RevalidateResponse:
    state = await engine.revalidate(node_id, certainty=certainty, emotion=emotion)
    if state is None:
        return RevalidateResponse(found=False, id=node_id)
    return RevalidateResponse(
        found=True,
        id=node_id,
        certainty=state.certainty,
        emotion_weight=state.emotion_weight,
    )


async def auto_remember(
    engine: GaOTTTEngine,
    transcript: str,
    max_candidates: int = 5,
    include_reasons: bool = True,
) -> AutoRememberResponse:
    cfg = engine.config
    raw_candidates = extract_candidates(
        transcript,
        max_candidates=max_candidates,
        min_chars=cfg.auto_remember_min_chars,
        max_chars=cfg.auto_remember_max_chars,
    )
    candidates = [
        AutoRememberCandidate(
            content=c.content,
            score=c.score,
            suggested_source=c.suggested_source,
            suggested_tags=list(c.suggested_tags),
            reasons=list(c.reasons) if include_reasons else [],
        )
        for c in raw_candidates
    ]
    return AutoRememberResponse(candidates=candidates, count=len(candidates))
