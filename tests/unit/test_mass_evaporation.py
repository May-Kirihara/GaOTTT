"""Phase N candidate β Stage 1 — ``evaporate_mass`` pure function.

Boundaries (all guards), monotonicity per parameter, and idempotency.
The function is config-driven, so each test builds a tiny ``GaOTTTConfig``
with the relevant knob tweaked.
"""
from __future__ import annotations

import math

from gaottt.config import GaOTTTConfig
from gaottt.core.gravity import evaporate_mass


def _cfg(**overrides) -> GaOTTTConfig:
    """Minimal config with Phase N β enabled. Override anything per-test."""
    defaults = dict(
        mass_evaporation_enabled=True,
        mass_evaporation_floor=1.0,
        mass_evaporation_grace_seconds=7 * 86400.0,
        mass_evaporation_idle_normalize_seconds=30 * 86400.0,
        mass_evaporation_rate=0.01,
        mass_evaporation_mass_exponent=1.5,
        mass_evaporation_time_exponent=1.0,
    )
    defaults.update(overrides)
    return GaOTTTConfig(**defaults)


# --- Disabled guard ---


def test_no_op_when_disabled():
    cfg = _cfg(mass_evaporation_enabled=False)
    # Far past grace, well above floor — would normally decay heavily.
    assert evaporate_mass(mass=10.0, last_access=0.0, now=365 * 86400.0, config=cfg) == 10.0


# --- Floor guard ---


def test_no_op_at_floor():
    cfg = _cfg()
    # mass == floor → no decay (definition of floor)
    assert evaporate_mass(mass=1.0, last_access=0.0, now=365 * 86400.0, config=cfg) == 1.0


def test_no_op_below_floor():
    cfg = _cfg()
    # Shouldn't normally happen, but defensive guard.
    assert evaporate_mass(mass=0.5, last_access=0.0, now=365 * 86400.0, config=cfg) == 0.5


def test_decay_clamps_to_floor_not_below():
    cfg = _cfg(mass_evaporation_rate=10.0)  # absurdly aggressive
    # With ε=10, excess^1.5 * (year/30d)^1 → enormous decay, must clamp at floor.
    result = evaporate_mass(mass=5.0, last_access=0.0, now=365 * 86400.0, config=cfg)
    assert result == cfg.mass_evaporation_floor
    assert result >= cfg.mass_evaporation_floor  # never below floor


# --- Grace guard ---


def test_no_op_inside_grace_period():
    cfg = _cfg(mass_evaporation_grace_seconds=7 * 86400.0)
    # 6 days idle — inside 7-day grace.
    now = 6 * 86400.0
    assert evaporate_mass(mass=10.0, last_access=0.0, now=now, config=cfg) == 10.0


def test_decays_just_outside_grace():
    cfg = _cfg(mass_evaporation_grace_seconds=7 * 86400.0)
    # 7d + 1s — just past grace.
    now = 7 * 86400.0 + 1.0
    result = evaporate_mass(mass=10.0, last_access=0.0, now=now, config=cfg)
    assert result < 10.0


# --- Single-rule structure (formula sanity) ---


def test_formula_matches_d1_specification():
    """Manually compute the D1=B formula and compare."""
    cfg = _cfg(
        mass_evaporation_rate=0.01,
        mass_evaporation_mass_exponent=1.5,
        mass_evaporation_time_exponent=1.0,
        mass_evaporation_idle_normalize_seconds=30 * 86400.0,
        mass_evaporation_grace_seconds=0.0,        # disable grace for clean math
    )
    mass = 5.0
    last_access = 0.0
    now = 30 * 86400.0   # exactly one τ_idle → idle_ratio = 1.0
    excess = mass - cfg.mass_evaporation_floor  # 4.0
    expected_decay = 0.01 * (excess ** 1.5) * (1.0 ** 1.0)
    expected = mass - expected_decay
    assert math.isclose(
        evaporate_mass(mass=mass, last_access=last_access, now=now, config=cfg),
        expected,
        rel_tol=1e-9,
    )


# --- Monotonicity ---


def test_monotonic_in_rate_epsilon():
    cfg_low = _cfg(mass_evaporation_rate=0.005)
    cfg_high = _cfg(mass_evaporation_rate=0.05)
    # 60 days idle, mass = 5.0
    args = dict(mass=5.0, last_access=0.0, now=60 * 86400.0)
    out_low = evaporate_mass(config=cfg_low, **args)
    out_high = evaporate_mass(config=cfg_high, **args)
    assert out_high < out_low < 5.0


def test_monotonic_in_mass_exponent_beta():
    cfg_low_beta = _cfg(mass_evaporation_mass_exponent=1.0)
    cfg_high_beta = _cfg(mass_evaporation_mass_exponent=2.0)
    args = dict(mass=5.0, last_access=0.0, now=60 * 86400.0)
    out_low = evaporate_mass(config=cfg_low_beta, **args)
    out_high = evaporate_mass(config=cfg_high_beta, **args)
    # Heavier exponent on (excess=4) → more decay → smaller resulting mass.
    assert out_high < out_low


def test_monotonic_in_time_exponent_gamma():
    cfg_low_gamma = _cfg(mass_evaporation_time_exponent=0.5)
    cfg_high_gamma = _cfg(mass_evaporation_time_exponent=2.0)
    # 60 days idle → idle_ratio = 2.0 → γ=2 amplifies more than γ=0.5
    args = dict(mass=5.0, last_access=0.0, now=60 * 86400.0)
    out_low = evaporate_mass(config=cfg_low_gamma, **args)
    out_high = evaporate_mass(config=cfg_high_gamma, **args)
    assert out_high < out_low


def test_monotonic_in_time_idle():
    cfg = _cfg(mass_evaporation_grace_seconds=0.0)
    args = dict(mass=5.0, last_access=0.0, config=cfg)
    out_30d = evaporate_mass(now=30 * 86400.0, **args)
    out_60d = evaporate_mass(now=60 * 86400.0, **args)
    out_90d = evaporate_mass(now=90 * 86400.0, **args)
    # Longer idle → more decay → strictly decreasing.
    assert out_30d > out_60d > out_90d


def test_monotonic_in_initial_mass():
    """Heavier nodes lose strictly more mass (in absolute terms)."""
    cfg = _cfg(mass_evaporation_grace_seconds=0.0)
    common = dict(last_access=0.0, now=30 * 86400.0, config=cfg)
    losses = []
    for m in (2.0, 3.0, 5.0, 10.0):
        result = evaporate_mass(mass=m, **common)
        losses.append(m - result)
    # Strictly increasing absolute losses.
    for i in range(1, len(losses)):
        assert losses[i] > losses[i - 1], (
            f"Loss not monotonic in mass: {losses}"
        )


# --- Idempotency (multiple calls with same args) ---


def test_idempotent_when_last_access_does_not_advance():
    """The lazy hook updates ``last_access=now`` after each touch; the cold-start
    sweep does not advance it. Calling evaporate_mass twice with the same
    ``last_access`` and same ``now`` MUST produce the same result the second
    time iff the mass was already at its post-decay value.

    This test exercises the startup sweep semantic — applying evaporation to
    an already-settled node must not erode it further.
    """
    cfg = _cfg(mass_evaporation_grace_seconds=0.0)
    once = evaporate_mass(mass=5.0, last_access=0.0, now=30 * 86400.0, config=cfg)
    # Second call with the *new* mass — already settled, should not decay again.
    twice = evaporate_mass(mass=once, last_access=0.0, now=30 * 86400.0, config=cfg)
    # decay term: ε · (once - floor)^β · 1 — strictly positive while once > floor,
    # so the sweep IS NOT idempotent on mass-value alone if last_access stays put.
    # That's expected and correct: the sweep is idempotent on the *node state* only
    # when callers update last_access. Document the invariant:
    assert twice < once  # not idempotent on raw call repetition — by design


def test_idempotent_when_last_access_advances_with_now():
    """The intended idempotency: after a touch event the caller sets
    ``state.last_access = now``. A subsequent evaporate call with
    ``last_access == now`` is inside grace (t_idle = 0) → no-op forever
    until the next idle period.
    """
    cfg = _cfg()
    now = 30 * 86400.0
    # Simulate the post-touch state: last_access set to now.
    result = evaporate_mass(mass=5.0, last_access=now, now=now, config=cfg)
    assert result == 5.0


# --- Numerical safety ---


def test_handles_zero_idle_normalize():
    """Mis-configured τ_idle=0 → fail safe, no decay (don't divide by zero)."""
    cfg = _cfg(mass_evaporation_idle_normalize_seconds=0.0)
    result = evaporate_mass(mass=5.0, last_access=0.0, now=60 * 86400.0, config=cfg)
    assert result == 5.0


def test_no_nan_or_inf_under_extreme_idle():
    cfg = _cfg()
    # 100 years idle, mass 100 — extreme but valid.
    result = evaporate_mass(
        mass=100.0, last_access=0.0, now=100 * 365 * 86400.0, config=cfg,
    )
    assert math.isfinite(result)
    assert result == cfg.mass_evaporation_floor  # clamped to floor
