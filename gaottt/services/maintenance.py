"""Maintenance service — merge / compact / prefetch / prefetch_status."""
from __future__ import annotations

from gaottt.core.engine import GaOTTTEngine
from gaottt.core.types import (
    CompactResponse,
    MergeOutcomeItem,
    MergeResponse,
    PrefetchResponse,
    PrefetchStatusResponse,
    ResetMassesResponse,
    WarmDisplacementResponse,
)


async def merge(
    engine: GaOTTTEngine,
    node_ids: list[str],
    keep: str | None = None,
) -> MergeResponse:
    outcomes = await engine.merge(node_ids, keep=keep)
    items = [
        MergeOutcomeItem(
            absorbed_id=o.absorbed_id,
            survivor_id=o.survivor_id,
            mass_before=o.mass_before,
            absorbed_mass=o.absorbed_mass,
            mass_after=o.mass_after,
        )
        for o in outcomes
    ]
    return MergeResponse(outcomes=items, count=len(items))


async def compact(
    engine: GaOTTTEngine,
    expire_ttl: bool = True,
    rebuild_faiss: bool = True,
    auto_merge: bool = False,
    merge_threshold: float = 0.95,
    merge_top_n: int = 500,
) -> CompactResponse:
    report = await engine.compact(
        expire_ttl=expire_ttl,
        rebuild_faiss=rebuild_faiss,
        auto_merge=auto_merge,
        merge_threshold=merge_threshold,
        merge_top_n=merge_top_n,
    )
    return CompactResponse(
        expired=report["expired"],
        merged_pairs=report["merged_pairs"],
        faiss_rebuilt=report["faiss_rebuilt"],
        vectors_before=report["vectors_before"],
        vectors_after=report["vectors_after"],
    )


def prefetch(
    engine: GaOTTTEngine,
    query: str,
    top_k: int = 5,
    wave_depth: int | None = None,
    wave_k: int | None = None,
    persona_context: list[str] | None = None,
    tag_filter: list[str] | None = None,
) -> PrefetchResponse:
    engine.prefetch(
        text=query, top_k=top_k, wave_depth=wave_depth, wave_k=wave_k,
        persona_context=persona_context, tag_filter=tag_filter,
    )
    return PrefetchResponse(
        scheduled=True,
        query=query,
        top_k=top_k,
        ttl_seconds=engine.config.prefetch_ttl_seconds,
    )


def prefetch_status(engine: GaOTTTEngine) -> PrefetchStatusResponse:
    status = engine.prefetch_status()
    return PrefetchStatusResponse(cache=status["cache"], pool=status["pool"])


async def reset_masses(
    engine: GaOTTTEngine,
    value: float = 1.0,
) -> ResetMassesResponse:
    """Phase M Stage 1 — maintainer-only mass reset.

    Intentionally absent from the MCP surface: bulk mass overwrite is
    destructive and there is no LLM-driven use case. REST exposes it
    under ``/admin/`` mirroring how ``/reset`` is gated.
    """
    affected = await engine.reset_masses(value)
    return ResetMassesResponse(nodes_reset=affected, value=value)


async def warm_displacement(
    engine: GaOTTTEngine,
    overwrite: bool = False,
) -> WarmDisplacementResponse:
    """Phase M follow-up — one-shot displacement seeding from velocity.

    Used to close the gap between M004 (writes velocity to every active
    node) and the dream loop's slow per-node coverage (~20h for a 24k
    corpus). Calls ``engine.warm_displacement`` which sets
    ``displacement = velocity`` for every active node that has velocity
    but no meaningful displacement.

    MCP-non-exposed — bulk write under ``/admin/`` mirroring
    ``/admin/reset_masses``. Safe to call repeatedly; default
    ``overwrite=False`` leaves naturally-accumulated displacement alone.
    """
    stats = await engine.warm_displacement(overwrite=overwrite)
    return WarmDisplacementResponse(**stats)
