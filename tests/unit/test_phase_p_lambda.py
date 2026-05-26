"""Phase P Stage 2 — Cosmological Λ (P-α) unit tests.

Pin the literal Hubble-flow form ``a_Λ(i) = +H · (pos_i - pos_j)``
summed over the neighbor scope. Verifies that Λ:
  - is bit-exact zero when the feature is off (regression guard),
  - produces distance-proportional repulsion when on,
  - shares the neighbor scope with the gravity loop (no separate filter),
  - is additive — it does not change the other four components.
"""

from __future__ import annotations

import numpy as np
import pytest

from gaottt.config import GaOTTTConfig
from gaottt.core.gravity import compute_acceleration


def _cfg(**overrides) -> GaOTTTConfig:
    """Minimal config that zeros every legacy acceleration term so the test
    isolates the Λ contribution. Each test re-enables the components it
    cares about."""
    base = dict(
        embedding_dim=8,
        gravity_G=0.0,                  # disable neighbor gravity
        orbital_anchor_strength=0.0,    # disable Hooke
        query_kick_enabled=False,
        mass_bh_enabled=False,
    )
    base.update(overrides)
    return GaOTTTConfig(**base)


def _make_neighbors(positions: list[np.ndarray]) -> list[tuple[np.ndarray, float]]:
    """Wrap raw positions into the (pos_j, mass_j) tuples ``compute_acceleration``
    expects. Λ doesn't read mass, but the type is shared with the gravity loop."""
    return [(p.astype(np.float32), 1.0) for p in positions]


# ----- core behavior --------------------------------------------------------

def test_lambda_off_is_bit_exact_zero_contribution() -> None:
    """flag OFF → acc is exactly zero when all other terms are zeroed.

    With Λ disabled and every legacy term zeroed via config, the function
    must return a literal zero vector — no rounding, no noise, no
    accidental contribution.
    """
    cfg = _cfg(cosmological_lambda_enabled=False)
    pos_i = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)
    disp = np.zeros(8, dtype=np.float32)
    neighbors = _make_neighbors([
        np.array([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
        np.array([0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
    ])
    acc = compute_acceleration(pos_i, pos_i, disp, neighbors, cfg)
    assert np.array_equal(acc, np.zeros(8, dtype=np.float32))


def test_lambda_two_node_literal_form() -> None:
    """Λ alone, 2 nodes — literal form a_Λ = H · (pos_i - pos_j).

    With H=0.001 and pos_i=[1,0,...], pos_j=[0,1,0,...]:
    a_Λ = 0.001 · ([1,0,...] - [0,1,0,...]) = [0.001, -0.001, 0,...].
    """
    H = 0.001
    cfg = _cfg(cosmological_lambda_enabled=True, cosmological_lambda_h=H)
    pos_i = np.array([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)
    pos_j = np.array([0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)
    disp = np.zeros(8, dtype=np.float32)
    acc = compute_acceleration(pos_i, pos_i, disp, _make_neighbors([pos_j]), cfg)
    expected = H * (pos_i - pos_j)
    np.testing.assert_allclose(acc, expected, atol=1e-7)


def test_lambda_is_repulsive_away_from_neighbor() -> None:
    """Direction check: Λ pushes pos_i AWAY from pos_j (positive (pos_i-pos_j))."""
    cfg = _cfg(cosmological_lambda_enabled=True, cosmological_lambda_h=0.01)
    pos_i = np.array([2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)
    pos_j = np.array([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)
    disp = np.zeros(8, dtype=np.float32)
    acc = compute_acceleration(pos_i, pos_i, disp, _make_neighbors([pos_j]), cfg)
    # pos_i is on +x of pos_j → Λ should push pos_i further along +x
    assert acc[0] > 0.0


def test_lambda_proportional_to_distance() -> None:
    """||a_Λ|| ∝ ||pos_i - pos_j|| (the defining Hubble-flow property)."""
    H = 0.01
    cfg = _cfg(cosmological_lambda_enabled=True, cosmological_lambda_h=H)
    pos_i = np.array([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)
    pos_j_near = np.array([0.9, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)
    pos_j_far = np.array([-1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)
    disp = np.zeros(8, dtype=np.float32)
    a_near = compute_acceleration(pos_i, pos_i, disp, _make_neighbors([pos_j_near]), cfg)
    a_far = compute_acceleration(pos_i, pos_i, disp, _make_neighbors([pos_j_far]), cfg)
    n_near = float(np.linalg.norm(a_near))
    n_far = float(np.linalg.norm(a_far))
    assert n_far > 10 * n_near  # distance ratio = 2.0 / 0.1 = 20×


def test_lambda_sums_over_neighbors() -> None:
    """a_Λ on i is the SUM of contributions from each neighbor."""
    H = 0.01
    cfg = _cfg(cosmological_lambda_enabled=True, cosmological_lambda_h=H)
    pos_i = np.zeros(8, dtype=np.float32)
    pos_a = np.array([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)
    pos_b = np.array([0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)
    disp = np.zeros(8, dtype=np.float32)
    acc = compute_acceleration(pos_i, pos_i, disp, _make_neighbors([pos_a, pos_b]), cfg)
    expected = H * ((pos_i - pos_a) + (pos_i - pos_b))
    np.testing.assert_allclose(acc, expected, atol=1e-7)


def test_lambda_h_zero_is_no_op_even_when_enabled() -> None:
    """Flag enabled + H=0 ⇒ Λ does nothing (rollback knob within the feature)."""
    cfg = _cfg(cosmological_lambda_enabled=True, cosmological_lambda_h=0.0)
    pos_i = np.array([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)
    pos_j = np.array([-1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)
    disp = np.zeros(8, dtype=np.float32)
    acc = compute_acceleration(pos_i, pos_i, disp, _make_neighbors([pos_j]), cfg)
    assert np.array_equal(acc, np.zeros(8, dtype=np.float32))


def test_lambda_additive_to_other_terms() -> None:
    """Λ is ADDITIVE — when other terms are non-zero, they keep their value.

    Strategy: compute acceleration with gravity ON + Λ OFF, then with both
    ON. The difference should be exactly the Λ contribution.
    """
    H = 0.005
    pos_i = np.array([0.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)
    pos_j = np.array([-0.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)
    disp = np.zeros(8, dtype=np.float32)
    neighbors = _make_neighbors([pos_j])

    cfg_off = _cfg(
        gravity_G=0.01,
        cosmological_lambda_enabled=False,
    )
    cfg_on = _cfg(
        gravity_G=0.01,
        cosmological_lambda_enabled=True,
        cosmological_lambda_h=H,
    )
    acc_off = compute_acceleration(pos_i, pos_i, disp, neighbors, cfg_off)
    acc_on = compute_acceleration(pos_i, pos_i, disp, neighbors, cfg_on)

    delta = acc_on - acc_off
    expected_lambda = H * (pos_i - pos_j)
    np.testing.assert_allclose(delta, expected_lambda, atol=1e-7)


@pytest.mark.parametrize("h_val", [0.0001, 0.001, 0.01, 0.1])
def test_lambda_scales_linearly_with_h(h_val: float) -> None:
    """||a_Λ|| should be linear in H for fixed positions."""
    cfg = _cfg(cosmological_lambda_enabled=True, cosmological_lambda_h=h_val)
    pos_i = np.array([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)
    pos_j = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)
    disp = np.zeros(8, dtype=np.float32)
    acc = compute_acceleration(pos_i, pos_i, disp, _make_neighbors([pos_j]), cfg)
    expected_mag = h_val * 1.0  # ||pos_i - pos_j|| = 1
    np.testing.assert_allclose(float(np.linalg.norm(acc)), expected_mag, rtol=1e-5)
