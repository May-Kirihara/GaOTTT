"""Phase M Stage 1 — unit tests for the new helpers.

Covers:
  * ``bh_factor`` — clamped at 0 below θ-2σ, smoothly rises through tanh.
  * ``is_self_force_by_id`` — original_id / cohort_id collision detection
    using a minimal cache stub.
"""
from __future__ import annotations

import math

from gaottt.core.gravity import bh_factor, is_self_force_by_id


# ---------------------------------------------------------------------------
# bh_factor
# ---------------------------------------------------------------------------

def test_bh_factor_zero_below_theta_minus_two_sigma():
    # θ=5, σ=1 → cutoff at 3.0
    assert bh_factor(2.0, theta=5.0, sigma=1.0) == 0.0
    assert bh_factor(2.999, theta=5.0, sigma=1.0) == 0.0


def test_bh_factor_transitions_smoothly_around_theta():
    theta, sigma = 5.0, 1.0
    f_at_theta = bh_factor(theta, theta=theta, sigma=sigma)
    # tanh(0) = 0, but our cutoff already let it through — must equal 0.
    assert f_at_theta == 0.0
    # +σ above θ → tanh(1) ≈ 0.7616
    assert math.isclose(
        bh_factor(theta + sigma, theta=theta, sigma=sigma),
        math.tanh(1.0),
        rel_tol=1e-6,
    )


def test_bh_factor_saturates_for_large_mass():
    theta, sigma = 5.0, 1.5
    # 3σ above θ → tanh(3) ≈ 0.9951
    assert bh_factor(theta + 3 * sigma, theta=theta, sigma=sigma) > 0.99
    # 5σ → essentially 1
    assert bh_factor(theta + 5 * sigma, theta=theta, sigma=sigma) > 0.9999


def test_bh_factor_sigma_zero_degenerates_to_hard_step():
    # σ=0 is a defensive degenerate case — pure step at θ.
    assert bh_factor(4.9, theta=5.0, sigma=0.0) == 0.0
    assert bh_factor(5.0, theta=5.0, sigma=0.0) == 0.0
    assert bh_factor(5.1, theta=5.0, sigma=0.0) == 1.0


# ---------------------------------------------------------------------------
# is_self_force_by_id
# ---------------------------------------------------------------------------

class _StubCache:
    """Minimal cache shape that ``is_self_force_by_id`` reaches into."""

    def __init__(self) -> None:
        self.originals: dict[str, str] = {}
        self.cohorts: dict[str, str] = {}

    def get_original(self, node_id: str) -> str | None:
        return self.originals.get(node_id)

    def get_cohort(self, node_id: str) -> str | None:
        return self.cohorts.get(node_id)


def test_same_id_is_always_self_force():
    cache = _StubCache()
    assert is_self_force_by_id(cache, "a", "a")


def test_same_original_id_is_self_force():
    cache = _StubCache()
    cache.originals = {"a": "doc-1", "b": "doc-1"}
    assert is_self_force_by_id(cache, "a", "b")


def test_different_original_id_is_external():
    cache = _StubCache()
    cache.originals = {"a": "doc-1", "b": "doc-2"}
    assert not is_self_force_by_id(cache, "a", "b")


def test_same_cohort_id_is_self_force():
    cache = _StubCache()
    cache.cohorts = {"a": "cohort-x", "b": "cohort-x"}
    assert is_self_force_by_id(cache, "a", "b")


def test_different_cohort_id_is_external():
    cache = _StubCache()
    cache.cohorts = {"a": "cohort-x", "b": "cohort-y"}
    assert not is_self_force_by_id(cache, "a", "b")


def test_both_missing_is_external():
    # No original_id and no cohort_id on either node → cannot prove they
    # share a context, so the force must count as external.
    cache = _StubCache()
    assert not is_self_force_by_id(cache, "a", "b")


def test_one_side_missing_is_external():
    cache = _StubCache()
    cache.originals = {"a": "doc-1"}  # b absent
    assert not is_self_force_by_id(cache, "a", "b")
    cache.cohorts = {"a": "cohort-x"}  # b still absent
    assert not is_self_force_by_id(cache, "a", "b")
