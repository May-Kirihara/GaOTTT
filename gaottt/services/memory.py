"""Memory service — remember / recall / explore / forget / restore / revalidate.

Each function takes an engine and returns a Pydantic response model from
``gaottt.core.types``. The MCP server formats these into human-readable text
via ``gaottt.services.formatters``; the REST server returns them as JSON.
"""
from __future__ import annotations

import random
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
    RoutingHint,
    TrainingDelta,
)
from gaottt.services import query_routing, reflection as reflection_service


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


def _to_memory_item(
    engine: GaOTTTEngine, r, *, excerpt_chars: int | None = None,
) -> MemoryItem:
    meta = r.metadata or {}
    source = meta.get("source", "unknown")
    tags = meta.get("tags") or []
    content = r.content
    # Phase O Stage 4 — list mode truncation. Applied here so the truncation
    # lives on the wire (both REST + MCP get the shorter payload), not just at
    # MCP-formatter time. Newlines collapsed to spaces so the result fits on
    # one terminal line.
    if excerpt_chars is not None and content:
        flat = content.replace("\n", " ").replace("\r", " ")
        content = flat[:excerpt_chars]
    return MemoryItem(
        id=r.id,
        content=content,
        metadata=r.metadata,
        raw_score=r.raw_score,
        final_score=r.final_score,
        source=source,
        tags=list(tags),
        displacement_norm=engine.get_displacement_norm(r.id),
        score_breakdown=getattr(r, "score_breakdown", None),  # Phase O Stage 1
    )


async def _build_routing_hint(
    engine: GaOTTTEngine,
    query: str,
    auto_route: bool,
    limit: int = 10,
) -> RoutingHint | None:
    """Phase O Stage 3 — classify ``query``; optionally run matching reflect.

    Returns ``None`` when both the per-call flag and the config switch are off
    (caller opted out completely — no hint to attach). Returns a populated
    ``RoutingHint`` otherwise so the caller can distinguish:
      - ``pattern_matched=False`` — router was on, no aspect matched (free-form)
      - ``auto_routed=True``      — aspect matched and reflect summary attached
      - ``auto_routed=False, pattern_matched=True`` — surfaced because the
        config switch was off after a per-call ``auto_route=True``
    """
    config_on = engine.config.auto_route_enabled
    if not auto_route and not config_on:
        return None
    aspect = query_routing.detect_aspect(query)
    pattern_matched = aspect is not None
    will_run = bool(pattern_matched and auto_route and config_on)
    summary: str | None = None
    if will_run:
        summary = await reflection_service.dispatch_aspect(
            engine, aspect, limit=limit,
        )
    return RoutingHint(
        aspect=aspect,
        pattern_matched=pattern_matched,
        auto_routed=will_run,
        reflect_summary=summary,
    )


def _delta_from_dict(d: dict | None) -> TrainingDelta | None:
    """Phase O Stage 2 — convert the engine-populated out-dict to TrainingDelta.

    Returns None when delta capture is disabled (empty / not populated dict).
    """
    if not d:
        return None
    return TrainingDelta(
        displacement_changes=d.get("displacement_changes", {}),
        mass_changes=d.get("mass_changes", {}),
        wave_reached_count=d.get("wave_reached_count", 0),
        wave_max_depth=d.get("wave_max_depth", 0),
        persona_hop_reached=d.get("persona_hop_reached", 0),
        supernova_triggered=d.get("supernova_triggered", False),
        cache_hit=d.get("cache_hit", False),
        topk_only=d.get("topk_only", True),
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
    auto_route: bool = True,
    mode: str = "detail",
) -> RecallResponse:
    # Phase H Stage 2: source_filter is applied at the wave seed step inside
    # propagate_gravity_wave (engine.query → _query_internal). The post-filter
    # below remains as a defensive belt-and-suspenders pass.
    # Phase J Stage 2: persona_context / tag_filter are forwarded through
    # engine.query and applied as additive seed injection in the wave (they
    # bypass source_filter's restrictive semantic — the caller explicitly
    # asked for these tags or persona ids).
    delta_out: dict | None = {} if engine.config.training_delta_enabled else None
    raw = await engine.query(
        text=query,
        top_k=top_k * 10 if source_filter else top_k,
        wave_depth=wave_depth,
        wave_k=wave_k,
        use_cache=not force_refresh,
        source_filter=source_filter,
        persona_context=persona_context,
        tag_filter=tag_filter,
        out_training_delta=delta_out,
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
    excerpt_chars = (
        engine.config.list_mode_excerpt_chars if mode == "list" else None
    )
    items = [
        _to_memory_item(engine, r, excerpt_chars=excerpt_chars) for r in raw
    ]
    routing_hint = await _build_routing_hint(engine, query, auto_route)
    return RecallResponse(
        items=items, count=len(items),
        training_delta=_delta_from_dict(delta_out),
        routing_hint=routing_hint,
    )


async def _dormant_surface(
    engine: GaOTTTEngine, top_k: int, diversity: float,
) -> ExploreResponse:
    """Phase O Stage 5 — random self-authored memo that the field has not
    pulled back in a long time.

    Bypasses the wave / FAISS entirely. The dormant condition is purely
    structural: age (last_access), mass (still below the mature gate), and
    source-class membership (the *kind* of memo I authored). No physics rule
    branches on the result — this is a different *operation* (counter-importance
    sampling), not a physics modifier.
    """
    cfg = engine.config
    cutoff = time.time() - cfg.dormant_age_threshold_seconds
    sources = set(cfg.dormant_source_classes)
    candidates: list[tuple[Any, dict[str, Any]]] = []
    for state in engine.cache.get_all_nodes():
        if state.is_archived:
            continue
        if state.last_access > cutoff:
            continue
        if state.mass > cfg.dormant_mass_threshold:
            continue
        doc = await engine.store.get_document(state.id)
        if doc is None:
            continue
        meta = doc.get("metadata") or {}
        if meta.get("source", "") not in sources:
            continue
        candidates.append((state, doc))
    if not candidates:
        return ExploreResponse(items=[], count=0, diversity=diversity)
    # Random sample without replacement — the whole point is to surface a
    # *different* dormant memo each call (the field's saturation is
    # broken by counter-importance picking).
    picks = random.sample(candidates, k=min(top_k, len(candidates)))
    items: list[MemoryItem] = []
    for state, doc in picks:
        meta = doc.get("metadata") or {}
        items.append(MemoryItem(
            id=state.id,
            content=doc.get("content", ""),
            metadata=meta,
            raw_score=0.0,
            final_score=0.0,
            source=meta.get("source", "unknown"),
            tags=list(meta.get("tags") or []),
            displacement_norm=engine.get_displacement_norm(state.id),
            score_breakdown=None,
        ))
    return ExploreResponse(items=items, count=len(items), diversity=diversity)


async def explore(
    engine: GaOTTTEngine,
    query: str,
    diversity: float = 0.5,
    top_k: int = 10,
    persona_context: list[str] | None = None,
    tag_filter: list[str] | None = None,
    auto_route: bool = True,
    mode: str = "serendipity",
) -> ExploreResponse:
    if mode == "dormant":
        # Phase O Stage 5 — counter-importance sampling. Skips wave / routing
        # / training_delta entirely: this is a different operation, not a
        # query (no semantic intent to detect, no gradient step to record).
        return await _dormant_surface(engine, top_k=top_k, diversity=diversity)

    config = engine.config
    original_gamma = config.gamma
    config.gamma = config.gamma * (1.0 + diversity * 20.0)
    explore_depth = config.wave_max_depth + int(diversity * 2)
    explore_k = config.wave_initial_k + int(diversity * 4)

    delta_out: dict | None = {} if engine.config.training_delta_enabled else None
    try:
        raw = await engine.query(
            text=query, top_k=top_k,
            wave_depth=explore_depth, wave_k=explore_k,
            persona_context=persona_context,
            tag_filter=tag_filter,
            out_training_delta=delta_out,
        )
    finally:
        config.gamma = original_gamma

    items = [_to_memory_item(engine, r) for r in raw]
    routing_hint = await _build_routing_hint(engine, query, auto_route)
    return ExploreResponse(
        items=items, count=len(items), diversity=diversity,
        training_delta=_delta_from_dict(delta_out),
        routing_hint=routing_hint,
    )


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
