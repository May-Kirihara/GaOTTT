"""MCP human-readable formatters.

Each ``format_<operation>`` function takes the Pydantic result from the
corresponding service and returns the exact string the MCP tool used to
produce inline. Keeping these byte-identical matters: LLM clients have
learned to parse these shapes, and existing MCP integration tests assert
on specific substrings.

REST does not use this module.
"""
from __future__ import annotations

import json

from gaottt.core.types import (
    AbandonResponse,
    AmbientMemory,
    AmbientRecallResponse,
    AutoRememberResponse,
    CommitResponse,
    CompactResponse,
    CompleteResponse,
    DeclareCommitmentResponse,
    DeclareIntentionResponse,
    DeclareValueResponse,
    DependResponse,
    ExploreResponse,
    ForgetResponse,
    IngestResponse,
    MergeResponse,
    PersonaSnapshotResponse,
    PrefetchResponse,
    PrefetchStatusResponse,
    RecallResponse,
    ReflectCommitmentsResponse,
    ReflectConnectionsResponse,
    ReflectDormantResponse,
    ReflectDuplicatesResponse,
    ReflectHotTopicsResponse,
    ReflectIntentionsResponse,
    ReflectRelationsOverviewResponse,
    ReflectRelationshipsResponse,
    ReflectSummaryResponse,
    ReflectTasksAbandonedResponse,
    ReflectTasksCompletedResponse,
    ReflectTasksDoingResponse,
    ReflectTasksTodoResponse,
    ReflectValuesResponse,
    RelateResponse,
    RelationsResponse,
    RememberResponse,
    RestoreResponse,
    RevalidateResponse,
    StartResponse,
    UnrelateResponse,
)


def format_remember(result: RememberResponse) -> str:
    if result.duplicate or result.id is None:
        return "Already exists in memory (duplicate content)."
    suffix = f" (expires {result.expires_at})" if result.expires_at else ""
    return f"Remembered. ID: {result.id}{suffix}"


def format_forget(result: ForgetResponse) -> str:
    verb = "Hard-deleted" if result.hard else "Archived"
    return f"{verb} {result.affected} of {result.requested} requested memories."


def format_restore(result: RestoreResponse) -> str:
    return f"Restored {result.affected} of {result.requested} requested memories."


def format_revalidate(result: RevalidateResponse) -> str:
    if not result.found:
        return f"Node {result.id} not found or archived."
    short = (result.id or "")[:8]
    return (
        f"Revalidated {short}.. "
        f"certainty={result.certainty:.2f}, emotion={result.emotion_weight:+.2f}"
    )


_COMPACT_LIMIT = 300


def _format_breakdown(b) -> str:
    """Phase O Stage 1 — one-line additive breakdown of final_score.

    Always appended to recall output when score_breakdown is present, so a
    TTT-aware caller can see why a result scored what it scored.

    Observation Apparatus Refinement Stage 1 — if ``b.reason`` is populated
    (a human-readable summary from ``explain_score``), append it as a second
    indented line so existing breakdown-substring assertions keep working
    while callers get the 1-line explanation.
    """
    if b is None:
        return ""
    flags = []
    if b.bm25_contributed:
        flags.append("bm25")
    if b.forced_inclusion:
        flags.append("forced")
    flag_str = f" [{', '.join(flags)}]" if flags else ""
    line = (
        f"  breakdown: cos={b.raw_cosine:.3f} vcos={b.virtual_cosine:.3f}·"
        f"decay={b.decay_factor:.3f} +wave={b.wave_score:.3f} "
        f"+mass={b.mass_boost:.3f} +emo={b.emotion_term:.3f} "
        f"+cert={b.certainty_term:.3f} ×sat={b.saturation:.3f} "
        f"persona_prox={b.persona_proximity:.3f}{flag_str}"
    )
    reason = getattr(b, "reason", None)
    if reason:
        line = f"{line}\n  reason: {reason}"
    return line


def _format_training_delta(td) -> str:
    """Phase O Stage 2 — TTT update visibility trailer.

    Reports state changes induced by this recall — backward-pass equivalent of
    the forward-pass breakdown. Emits a compact ``## 訓練差分`` section so the
    caller sees what their recall *changed* in the gravity field.
    """
    if td is None:
        return ""
    if td.cache_hit:
        # No simulation ran — be explicit so the caller doesn't mis-attribute
        # zero deltas to "nothing moved" (it's "nothing was tried").
        return (
            "\n\n## 訓練差分\n"
            "(cache hit — no simulation ran; mass / displacement unchanged)"
        )
    # Top movers — sort by absolute change, then trim to a small fixed budget.
    def _top(d: dict[str, float], n: int = 3) -> list[tuple[str, float]]:
        return sorted(d.items(), key=lambda t: abs(t[1]), reverse=True)[:n]

    lines = ["\n\n## 訓練差分"]
    mass_top = _top(td.mass_changes)
    disp_top = _top(td.displacement_changes)
    coverage = "top-k only" if td.topk_only else "full reached set"
    lines.append(
        f"wave_reached={td.wave_reached_count} "
        f"depth={td.wave_max_depth} "
        f"persona_hop={td.persona_hop_reached} "
        f"({coverage})"
    )
    # Multi-Source Query — added as its own line (CLAUDE.md formatter rule:
    # never modify an existing line). Shown only when the prompt actually
    # split into multiple intent centers.
    if getattr(td, "intent_centers", 1) > 1:
        lines.append(f"intent-centers={td.intent_centers} (multi-source seeding)")
    if mass_top:
        parts = [f"{nid[:8]}.. {d:+.4f}" for nid, d in mass_top]
        lines.append("Δmass top: " + ", ".join(parts))
    if disp_top:
        parts = [f"{nid[:8]}.. {d:+.4f}" for nid, d in disp_top]
        lines.append("Δ|disp| top: " + ", ".join(parts))
    if not mass_top and not disp_top:
        lines.append("(no state changes captured)")
    return "\n".join(lines)


def _format_routing_hint(h) -> str:
    """Phase O Stage 3 — auto-routed reflect summary trailer.

    Emits a ``## 関連 reflect サマリ (auto-routed)`` section when the surface
    form of the query matched a structured aspect and the reflect summary
    was attached. Keeps existing recall substrings untouched (CLAUDE.md
    "MCP formatter の出力文字列を変えない").
    """
    if h is None or not h.auto_routed or h.reflect_summary is None:
        return ""
    aspect_label = h.aspect or "?"
    return (
        f"\n\n## 関連 reflect サマリ (auto-routed)\n"
        f"_aspect_: `{aspect_label}` "
        f"(query 形式から自動判定 — 関連した state snapshot を併走実行)\n\n"
        f"{h.reflect_summary}"
    )


def format_recall(result: RecallResponse, output_mode: str = "full") -> str:
    """Format recall results for MCP output.

    output_mode:
      "full"    — full content (default, backward-compatible)
      "compact" — content truncated at 300 chars with length indicator
      "ids"     — header line only, no content
    """
    if not result.items:
        # Even with no memories, surface the auto-routed reflect summary so
        # the caller still gets the structured answer the surface form asked
        # for (Phase O Stage 3 — the whole point of routing is to substitute
        # when free-form recall would have come back empty).
        routing_trailer = _format_routing_hint(result.routing_hint)
        return "No memories found." + routing_trailer
    lines = []
    for i, item in enumerate(result.items):
        tag_str = f" [{', '.join(item.tags)}]" if item.tags else ""
        header = (
            f"[{i+1}] id={item.id} "
            f"(score={item.final_score:.4f}, virtual_score={item.raw_score:.4f}, "
            f"source={item.source}{tag_str}, "
            f"displacement={item.displacement_norm:.4f})"
        )
        breakdown_line = _format_breakdown(item.score_breakdown)
        if output_mode == "ids":
            block = header
            if breakdown_line:
                block += f"\n{breakdown_line}"
            lines.append(block)
        elif output_mode == "compact":
            content = item.content
            if len(content) > _COMPACT_LIMIT:
                content = content[:_COMPACT_LIMIT] + f"…({len(item.content)} chars)"
            block = header
            if breakdown_line:
                block += f"\n{breakdown_line}"
            block += f"\n{content}"
            lines.append(block)
        else:
            block = header
            if breakdown_line:
                block += f"\n{breakdown_line}"
            block += f"\n{item.content}"
            lines.append(block)
    body = "\n\n---\n\n".join(lines)
    trailer = _format_training_delta(result.training_delta)
    routing_trailer = _format_routing_hint(result.routing_hint)
    return body + trailer + routing_trailer


def format_explore(result: ExploreResponse, mode: str = "serendipity") -> str:
    """Format an explore result. ``mode='dormant'`` swaps the header for a
    counter-importance framing (Phase O Stage 5) — final_score is meaningless
    there since the wave was bypassed, so it is omitted from the per-item
    line."""
    if mode == "dormant":
        if not result.items:
            return (
                "💭 No dormant memories to surface "
                "(none match age + mass + source-class conditions)."
            )
        lines = [f"💭 Dormant memories surfaced ({len(result.items)}):"]
        for i, item in enumerate(result.items):
            tag_str = f" [{', '.join(item.tags)}]" if item.tags else ""
            lines.append(
                f"[{i+1}] id={item.id} "
                f"(source={item.source}{tag_str}, "
                f"displacement={item.displacement_norm:.4f})\n"
                f"{item.content[:300]}"
            )
        return "\n\n---\n\n".join(lines)

    if not result.items:
        return "No memories found for exploration." + _format_routing_hint(
            result.routing_hint,
        )
    lines = [f"Exploration (diversity={result.diversity:.1f}):"]
    for i, item in enumerate(result.items):
        lines.append(
            f"[{i+1}] (score={item.final_score:.4f}, source={item.source})\n"
            f"{item.content[:200]}"
        )
    body = "\n\n---\n\n".join(lines)
    return (
        body
        + _format_training_delta(result.training_delta)
        + _format_routing_hint(result.routing_hint)
    )


# --- Ambient Recall Enrichment ---

def _ambient_meta(m: AmbientMemory) -> str:
    """Compact provenance tag — source · certainty · age (· lensing gap+resonance)."""
    parts = [m.source]
    if m.certainty is not None:
        parts.append(f"certainty {m.certainty:.2f}")
    if m.age_days is not None:
        parts.append(f"{m.age_days:.0f}d")
    if m.lensing_gap is not None:
        parts.append(f"gap +{m.lensing_gap:.2f}")
    # Lateral Association Stage 5 — resonance signal for lensing picks
    # ("trust" axis derived from cooccurrence with today's direct hits).
    # Always populated alongside ``lensing_gap`` so the agent can weigh
    # "field bent strongly" + "field has learned this association" jointly.
    if m.lensing_resonance is not None:
        parts.append(f"resonance {m.lensing_resonance:.2f}")
    return " · ".join(parts)


def _ambient_breakdown(b) -> str:
    """Refinement Stage 3 — terse ``[raw=.. virt=.. bm25=.. mass=.. ...]``
    suffix appended after each slot row when ``expose_breakdown`` is on.
    Skips zero / default fields so the line stays compact. ``b`` is a
    ``ScoreBreakdown`` (any null-falsy value yields the empty string)."""
    if b is None:
        return ""
    parts: list[str] = []
    if b.raw_cosine:
        parts.append(f"raw={b.raw_cosine:.3f}")
    if b.virtual_cosine:
        parts.append(f"virt={b.virtual_cosine:.3f}")
    if b.wave_score:
        parts.append(f"wave={b.wave_score:.3f}")
    if b.mass_boost:
        parts.append(f"mass={b.mass_boost:.2f}")
    if b.persona_proximity:
        parts.append(f"persona={b.persona_proximity:.2f}")
    if b.bm25_contributed:
        parts.append("bm25")
    if b.forced_inclusion:
        parts.append("forced")
    suffix = f"  [{' '.join(parts)}]" if parts else ""
    # Observation Apparatus Refinement Stage 1 — append the reason line as a
    # second indented sub-line so the ambient block reader sees *why* this
    # slot fired without parsing the numeric breakdown.
    reason = getattr(b, "reason", None)
    if reason:
        suffix = f"{suffix}\n      reason: {reason}"
    return suffix


def format_ambient(result: AmbientRecallResponse) -> str:
    """Ambient Recall Enrichment — the ``<gaottt-ambient-recall>`` block.

    Returns the full block when there is something to inject. When the
    relevance gate suppressed injection (``count == 0``) it returns a short
    non-block sentinel — the UserPromptSubmit hook keys on the leading
    ``<gaottt-ambient-recall>`` tag to decide whether to emit.
    """
    if result.count == 0:
        return "(関連する記憶なし)"
    lines = [
        "<gaottt-ambient-recall>",
        "GaOTTT 長期記憶から自動取得した関連知識です"
        "（ユーザーの発話ではなく、参考のための前提知識）。",
    ]
    if result.direct:
        lines.append("")
        lines.append("▼ 直接ヒット")
        for i, m in enumerate(result.direct, 1):
            lines.append(
                f" {i}. [{_ambient_meta(m)}] {m.content}"
                f"{_ambient_breakdown(m.breakdown)}"
            )
            if m.because:
                lines.append(f"    ← because {m.because}")
    if result.lensing:
        lines.append("")
        # Lateral Association Stage 3 — top-K lensing. Heading shows the
        # count so the reader knows N lateral associations are in play
        # (the literal "〇〇といえば〜だったよな" mechanism firing N times).
        # Singular heading (N=1, the Stage 1/2 default) stays unchanged for
        # zero visible noise at K=1.
        count = len(result.lensing)
        if count == 1:
            lines.append("▼ 重力レンズ（テキスト的に遠いが、場が結びつけた）")
        else:
            lines.append(
                f"▼ 重力レンズ（{count} 件、テキスト的に遠いが、場が結びつけた）"
            )
        for m in result.lensing:
            lines.append(
                f" · [{_ambient_meta(m)}] {m.content}"
                f"{_ambient_breakdown(m.breakdown)}"
            )
            if m.because:
                lines.append(f"    ← because {m.because}")
    if result.tensions:
        lines.append("")
        lines.append("▼ ⚠ 矛盾")
        for t in result.tensions:
            lines.append(f" · {t.memory_excerpt}")
            lines.append(f"   ⇔ contradicts: {t.contradicts_excerpt}")
    if result.persona is not None:
        lines.append("")
        lines.append("▼ いま誰として")
        lines.append(
            f" · {result.persona.kind}: {result.persona.content}"
            f"{_ambient_breakdown(result.persona.breakdown)}"
        )
    # Lateral Association Stage 1 — id manifest for the UserPromptSubmit hook.
    # HTML comment so it stays out of the visible block in markdown rendering
    # while being trivially parseable from the raw text. The hook reads this
    # to build the ``recently_surfaced`` map it passes to the next ambient
    # call (Plans-Ambient-Recall-Lateral-Association.md Stage 1 sub-step 1).
    # Format: ``<!-- ambient-ids direct=id1,id2 lensing=id3 persona=id4 -->``.
    # Keys are omitted when their slot is empty so a missing key is "no pick".
    manifest_parts: list[str] = []
    if result.direct:
        manifest_parts.append(
            "direct=" + ",".join(m.id for m in result.direct)
        )
    if result.lensing:
        # Stage 3 — comma-separated for top-K lensing. The hook already
        # splits on commas within slot=... chunks, so no parser change.
        manifest_parts.append(
            "lensing=" + ",".join(m.id for m in result.lensing)
        )
    if result.persona is not None:
        manifest_parts.append(f"persona={result.persona.id}")
    if manifest_parts:
        lines.append(f"<!-- ambient-ids {' '.join(manifest_parts)} -->")
    lines.append("</gaottt-ambient-recall>")
    return "\n".join(lines)


# --- Relations ---

def format_relate(result: RelateResponse) -> str:
    e = result.edge
    return (
        f"Related {e.src[:8]}.. --[{e.edge_type}]--> {e.dst[:8]}.. "
        f"(weight={e.weight:.2f})"
    )


def format_unrelate(result: UnrelateResponse) -> str:
    return (
        f"Removed {result.removed} directed edge(s) between "
        f"{result.src_id[:8]}.. and {result.dst_id[:8]}.."
    )


def format_relations(result: RelationsResponse) -> str:
    if not result.edges:
        return (
            f"No directed relations found for {result.node_id[:8]}.. "
            f"(direction={result.direction})."
        )
    lines = [
        f"Relations for {result.node_id[:8]}.. "
        f"(direction={result.direction}, {result.count} found):"
    ]
    for e in result.edges:
        meta = f" meta={e.metadata}" if e.metadata else ""
        lines.append(
            f"  {e.src[:8]}.. --[{e.edge_type}]--> {e.dst[:8]}.. "
            f"weight={e.weight:.2f}{meta}"
        )
    return "\n".join(lines)


# --- Maintenance ---

def format_merge(result: MergeResponse) -> str:
    if not result.outcomes:
        return "Nothing to merge (need ≥2 active nodes from the given IDs)."
    lines = [f"Merged {result.count} node(s) into a survivor:"]
    for o in result.outcomes:
        lines.append(
            f"  {o.absorbed_id[:8]}.. → {o.survivor_id[:8]}.. "
            f"(mass {o.mass_before:.3f} + {o.absorbed_mass:.3f} = {o.mass_after:.3f})"
        )
    return "\n".join(lines)


def format_compact(result: CompactResponse) -> str:
    return (
        f"Compaction complete:\n"
        f"  TTL-expired:    {result.expired}\n"
        f"  Auto-merged:    {result.merged_pairs} pairs\n"
        f"  FAISS rebuilt:  {result.faiss_rebuilt}\n"
        f"  FAISS vectors:  {result.vectors_before} → {result.vectors_after}"
    )


def format_prefetch(result: PrefetchResponse) -> str:
    return (
        f"Scheduled prefetch for '{result.query[:60]}...' (top_k={result.top_k}). "
        f"Subsequent recall within {result.ttl_seconds:.0f}s "
        f"will be served from cache."
    )


def format_prefetch_status(result: PrefetchStatusResponse) -> str:
    cache = result.cache
    pool = result.pool
    return (
        "Prefetch cache:\n"
        f"  size:      {cache['size']}/{cache['max_size']}  (active: {cache['active']})\n"
        f"  hit/miss:  {cache['hits']} / {cache['misses']}  "
        f"(hit_rate: {cache['hit_rate']:.2%})\n"
        f"  evictions: {cache['evictions']}\n"
        f"  ttl:       {cache['ttl_seconds']:.0f}s\n"
        "Prefetch pool:\n"
        f"  scheduled: {pool['scheduled']}\n"
        f"  completed: {pool['completed']}\n"
        f"  failed:    {pool['failed']}\n"
        f"  in_flight: {pool['in_flight']}/{pool['max_concurrent']}"
    )


# --- Ingest ---

def format_ingest(result: IngestResponse) -> str:
    if result.found == 0:
        return f"No documents found at {result.path}"
    return (
        f"Ingested {result.ingested} documents from {result.path} "
        f"(skipped {result.skipped} duplicates)"
    )


# --- Auto-remember ---

def format_auto_remember(result: AutoRememberResponse) -> str:
    if not result.candidates:
        return "No save-worthy candidates extracted from the transcript."
    lines = [f"Extracted {len(result.candidates)} candidate(s):"]
    for i, c in enumerate(result.candidates, start=1):
        tags = f", tags={list(c.suggested_tags)}" if c.suggested_tags else ""
        header = f"[{i}] score={c.score} source={c.suggested_source}{tags}"
        block = f"{header}\n{c.content}"
        if c.reasons:
            block += f"\n  reasons: {', '.join(c.reasons)}"
        lines.append(block)
    lines.append(
        "\nReview and call `remember` for the ones you want to keep."
    )
    return "\n\n".join(lines)


# --- Reflection ---

def format_reflect_summary(r: ReflectSummaryResponse) -> str:
    return (
        f"Memory Summary:\n"
        f"  Total memories: {r.total_memories}\n"
        f"  Active (mass > 1): {r.active_memories}\n"
        f"  Displaced by gravity: {r.displaced_nodes}\n"
        f"  Co-occurrence edges: {r.total_edges}\n"
        f"  Sources: {json.dumps(r.sources, ensure_ascii=False)}"
    )


def format_reflect_hot_topics(r: ReflectHotTopicsResponse) -> str:
    lines = ["High-mass memories (frequently recalled):"]
    for n in r.items:
        lines.append(
            f"  id={n.id} mass={n.mass:.2f} temp={n.temperature:.6f} | "
            f"{n.content_preview}..."
        )
    return "\n".join(lines)


def format_reflect_connections(r: ReflectConnectionsResponse) -> str:
    lines = [f"Strongest connections ({len(r.items)} shown):"]
    for e in r.items:
        lines.append(
            f"  weight={e.weight:.1f}: {e.src}↔{e.dst} | "
            f"[{e.src_preview}...] <-> [{e.dst_preview}...]"
        )
    return "\n".join(lines)


def format_reflect_dormant(r: ReflectDormantResponse) -> str:
    lines = ["Dormant memories (longest since last access):"]
    for n in r.items:
        lines.append(
            f"  id={n.id} {n.age_days:.1f} days ago, mass={n.mass:.2f} | "
            f"{n.content_preview}..."
        )
    return "\n".join(lines)


def format_reflect_duplicates(r: ReflectDuplicatesResponse, limit: int) -> str:
    if not r.clusters:
        return f"No near-duplicate clusters found (threshold {r.threshold:.2f})."
    lines = [
        f"Near-duplicate clusters ({len(r.clusters)} found, top {limit}):"
    ]
    for i, c in enumerate(r.clusters, start=1):
        lines.append(
            f"\n[Cluster {i}] {len(c.ids)} nodes, "
            f"avg_pairwise_sim={c.avg_pairwise_similarity:.3f}"
        )
        for m in c.members:
            lines.append(
                f"  - {m.id[:8]}.. mass={m.mass:.2f} | {m.content_preview}"
            )
        lines.append(f"  → To merge: merge(node_ids={list(c.ids)})")
    return "\n".join(lines)


def format_reflect_relations_overview(r: ReflectRelationsOverviewResponse) -> str:
    if r.total == 0:
        return "No directed relations recorded yet."
    lines = [f"Directed relations ({r.total} total):"]
    for t, c in sorted(r.by_type.items(), key=lambda kv: -kv[1]):
        lines.append(f"  {t}: {c}")
    lines.append(f"\nMost recent {len(r.recent)}:")
    for e in r.recent:
        lines.append(
            f"  {e.src[:8]}.. --[{e.edge_type}]--> {e.dst[:8]}.. "
            f"(weight={e.weight:.2f})"
        )
    return "\n".join(lines)


def format_reflect_tasks_todo(r: ReflectTasksTodoResponse, limit: int) -> str:
    if r.total == 0:
        return "No active tasks. Use `commit(...)` to start one."
    lines = [f"Active tasks ({r.total} total, showing top {limit} by deadline):"]
    for t in r.items:
        dl_str = t.deadline or "permanent"
        days_note = f" ({t.days_left:+.1f}d)" if t.days_left is not None else ""
        lines.append(f"  id={t.id} deadline={dl_str}{days_note} | {t.content[:120]}")
    return "\n".join(lines)


def format_reflect_tasks_doing(r: ReflectTasksDoingResponse) -> str:
    if not r.items:
        return "No tasks actively in progress (no `start()` in the last hour)."
    lines = [f"In-progress tasks ({len(r.items)}):"]
    for t in r.items:
        lines.append(
            f"  id={t.id} ({t.minutes_since_last_verify:.0f}m ago) | {t.content[:120]}"
        )
    return "\n".join(lines)


def format_reflect_tasks_completed(r: ReflectTasksCompletedResponse, limit: int) -> str:
    if r.total == 0:
        return "No completed tasks yet."
    lines = [f"Completed tasks ({r.total} total, showing top {limit}):"]
    for item in r.items:
        lines.append(f"  {item.timestamp}  task={item.task_id[:8]}.. | {item.task_preview}")
        lines.append(f"        outcome={item.other_id[:8]}.. | {item.other_preview}")
    return "\n".join(lines)


def format_reflect_tasks_abandoned(r: ReflectTasksAbandonedResponse, limit: int) -> str:
    if r.total == 0:
        return "No abandoned tasks (yet — that's OK)."
    lines = [f"Abandoned tasks (shadow chronology, {r.total} total, top {limit}):"]
    for item in r.items:
        lines.append(f"  {item.timestamp}  task={item.task_id[:8]}.. | {item.task_preview}")
        lines.append(f"        reason | {item.other_preview}")
    return "\n".join(lines)


def format_reflect_commitments(r: ReflectCommitmentsResponse, limit: int) -> str:
    if r.total == 0:
        return "No active commitments. Use `declare_commitment(...)`."
    lines = [f"Active commitments ({r.total} total, showing top {limit}):"]
    for t in r.items:
        dl_str = t.deadline or "permanent"
        days_note = f" ({t.days_left:+.1f}d)" if t.days_left is not None else ""
        warn = " ⚠️" if t.days_left is not None and t.days_left < 2 else ""
        lines.append(f"  id={t.id} deadline={dl_str}{days_note}{warn} | {t.content[:120]}")
    return "\n".join(lines)


def format_reflect_intentions(r: ReflectIntentionsResponse, limit: int) -> str:
    if r.total == 0:
        return "No intentions declared. Use `declare_intention(...)`."
    lines = [f"Intentions ({r.total} total, showing top {limit}):"]
    for item in r.items:
        lines.append(f"  id={item.id} | {item.content[:160]}")
    return "\n".join(lines)


def format_reflect_values(r: ReflectValuesResponse, limit: int) -> str:
    if r.total == 0:
        return "No values declared. Use `declare_value(...)`."
    lines = [f"Values ({r.total} total, showing top {limit}):"]
    for item in r.items:
        lines.append(f"  id={item.id} | {item.content[:160]}")
    return "\n".join(lines)


def format_reflect_relationships(r: ReflectRelationshipsResponse) -> str:
    if r.total_people == 0:
        return "No relationships recorded. Use `remember(source=\"relationship:<name>\", ...)`."
    lines = [f"Relationships ({r.total_people} people, {r.total_memories} memories):"]
    for entry in r.people:
        lines.append(f"\n## {entry.who}  ({len(entry.memories)} memories)")
        for mem in entry.memories[:3]:
            lines.append(f"  id={mem.id[:8]}.. | {mem.content[:120]}")
    return "\n".join(lines)


def format_persona_snapshot(r: PersonaSnapshotResponse) -> str:
    """Exact reproduction of the previous ``inherit_persona`` layout."""
    parts: list[str] = ["# Persona inheritance\n"]
    if r.values:
        parts.append(f"## Values ({len(r.values)})")
        for v in r.values[:8]:
            parts.append(f"- {v.content}  _(id={v.id[:8]}..)_")
    else:
        parts.append("## Values\n_No values declared yet. `declare_value(...)` to seed the bedrock._")

    if r.intentions:
        parts.append(f"\n## Intentions ({len(r.intentions)})")
        for i in r.intentions[:8]:
            parts.append(f"- {i.content}  _(id={i.id[:8]}..)_")
    else:
        parts.append("\n## Intentions\n_No long-term direction declared yet._")

    if r.commitments:
        parts.append(f"\n## Active Commitments ({len(r.commitments)})")
        for c in r.commitments[:8]:
            parts.append(f"- {c.content}  _(id={c.id[:8]}.., deadline {c.deadline})_")

    if r.styles:
        parts.append(f"\n## Style ({len(r.styles)})")
        for s in r.styles[:5]:
            parts.append(f"- {s.content}")

    if r.relationships:
        parts.append(f"\n## Relationships ({len(r.relationships)})")
        for rel in r.relationships[:8]:
            parts.append(f"- **{rel.who}**: {rel.content}")

    parts.append(
        "\n---\n_To add to this persona: `declare_value` / `declare_intention` "
        "/ `declare_commitment`, or `remember(source=\"style\", ...)` and "
        "`remember(source=\"relationship:<name>\", ...)`._"
    )
    return "\n".join(parts)


# --- Phase D ---

def format_commit(r: CommitResponse) -> str:
    if r.duplicate:
        return "Task already exists (duplicate content)."
    if r.edge_error is not None:
        return f"Task created (id={r.id}) but fulfills edge failed: {r.edge_error}"
    expires = r.expires_at or "permanent"
    parent_note = f", fulfills {r.parent_id[:8]}..." if r.parent_id else ""
    return f"Task committed. ID: {r.id} (deadline {expires}{parent_note})"


def format_start(r: StartResponse) -> str:
    if not r.found:
        return f"Task {r.id} not found or archived."
    em = r.emotion_weight if r.emotion_weight is not None else 0.0
    return f"Started {r.id[:8]}.. (TTL refreshed; emotion={em:+.2f})"


def format_complete(r: CompleteResponse) -> str:
    if r.duplicate:
        return "Outcome content already exists; could not record completion."
    if r.edge_error is not None:
        return f"Outcome saved (id={r.outcome_id}) but completed edge failed: {r.edge_error}"
    note = " (task already archived)" if r.task_already_archived else ""
    return f"Completed. outcome={r.outcome_id} → task={r.task_id[:8]}..{note}"


def format_abandon(r: AbandonResponse) -> str:
    if r.duplicate:
        return "Reason content already exists; could not record abandonment."
    if r.edge_error is not None:
        return f"Reason saved (id={r.reason_id}) but abandoned edge failed: {r.edge_error}"
    return f"Abandoned. reason={r.reason_id} → task={r.task_id[:8]}.."


def format_depend(r: DependResponse) -> str:
    if r.error is not None:
        return f"Dependency could not be created: {r.error}"
    return f"{r.task_id[:8]}.. --[{r.edge_type}]--> {r.depends_on_id[:8]}.."


def format_declare_value(r: DeclareValueResponse) -> str:
    if r.duplicate:
        return "Value already declared (duplicate content)."
    return f"Value declared. ID: {r.id} (permanent)"


def format_declare_intention(r: DeclareIntentionResponse) -> str:
    if r.duplicate:
        return "Intention already declared (duplicate content)."
    if r.edge_error is not None:
        return f"Intention created (id={r.id}) but derived_from edge failed: {r.edge_error}"
    note = f", derived_from {r.parent_value_id[:8]}.." if r.parent_value_id else ""
    return f"Intention declared. ID: {r.id} (permanent{note})"


def format_declare_commitment(r: DeclareCommitmentResponse) -> str:
    if r.duplicate:
        return "Commitment already declared (duplicate content)."
    if r.edge_error is not None:
        return f"Commitment created (id={r.id}) but fulfills edge failed: {r.edge_error}"
    expires = r.expires_at or "permanent"
    return (
        f"Commitment declared. ID: {r.id} (deadline {expires}, "
        f"fulfills {r.parent_intention_id[:8]}..)"
    )
