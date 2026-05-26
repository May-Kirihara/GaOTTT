"""Observation Apparatus Refinement Stage 1 — reason-line generator.

Pure function that turns a :class:`ScoreBreakdown` into a short
human-readable string summarizing which factors dominated the score.
This is *observation layer only* — it never touches force, mass, or
displacement. The Phase M single-rule (source/class-blind physics) is
preserved by construction: ``explain_score`` reads breakdown fields and
returns a string. It does not feed back into ranking.
"""

from __future__ import annotations

from gaottt.core.types import ScoreBreakdown

_DOMINANCE_HINT = "possible dominance artifact"


def explain_score(
    breakdown: ScoreBreakdown,
    *,
    mass_dominance_threshold: float = 2.0,
    bm25_strong_threshold: float = 0.5,
) -> str | None:
    """Return a 60-100 char reason line, or ``None`` when nothing to say.

    Decision order (first match wins for the *prefix*, secondary factors
    are appended after ``+``):

    1. ``dormant_percentile`` is not None → "dormant surface (percentile=N)"
    2. ``lensing_gap > 0`` → "lensing pick (gap=+0.XX)"
    3. ``forced_inclusion`` → "forced via tag/persona_context"
    4. ``node_mass >= mass_dominance_threshold`` and ``virtual_cosine < 0.5``
       → "high mass persona proximity (mass=X.XX)" + dominance-artifact hint
    5. ``bm25_score >= bm25_strong_threshold`` → "bm25 strong lexical match"
    6. Fallback: "semantic match (cos=X.XX)" when ``virtual_cosine`` is
       the dominant additive term

    Returns ``None`` only when no signal is meaningful (all zero / cold).
    """
    parts: list[str] = []
    hints: list[str] = []

    # 1. dormant surface — wins outright (counter-importance sampling channel)
    if breakdown.dormant_percentile is not None:
        return (
            f"dormant surface (percentile={breakdown.dormant_percentile:.0f}, "
            f"mass={breakdown.node_mass:.2f}) — counter-importance sampling"
        )

    # 2. lensing pick — wins outright (field-connected but semantically distant)
    if breakdown.lensing_gap > 0:
        return (
            f"lensing pick (gap=+{breakdown.lensing_gap:.2f}) — "
            "semantically distant but field-connected"
        )

    # 3. forced inclusion — informational prefix, may stack with other signals below
    if breakdown.forced_inclusion:
        parts.append("forced via tag/persona_context")

    # 4. high mass + weak cosine = Heavy Persona Dominance candidate
    mass_dominates = (
        breakdown.node_mass >= mass_dominance_threshold
        and breakdown.virtual_cosine < 0.5
    )
    if mass_dominates:
        parts.append(f"high mass persona proximity (mass={breakdown.node_mass:.2f})")
        hints.append(_DOMINANCE_HINT)

    # 5. BM25 strong match — works alongside other signals
    if breakdown.bm25_score >= bm25_strong_threshold:
        parts.append(f"bm25 strong lexical match ({breakdown.bm25_score:.2f})")
    elif breakdown.bm25_contributed and breakdown.bm25_score > 0:
        parts.append(f"bm25 lexical assist ({breakdown.bm25_score:.2f})")

    # 6. fallback: semantic match if nothing fired and virtual_cosine carries the score
    if not parts and breakdown.virtual_cosine >= 0.3:
        parts.append(f"semantic match (cos={breakdown.virtual_cosine:.2f})")

    if not parts:
        return None

    text = " + ".join(parts)
    if hints:
        text = f"{text} — {', '.join(hints)}"
    return text
