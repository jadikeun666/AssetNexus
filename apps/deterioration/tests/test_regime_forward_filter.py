"""
formulas.md §2.1 — RegimeForwardFilter. engineering-rules.md §7: expected
value dihitung tangan (rumus tertutup CTMC 2-status, dihitung ulang di sini
via math.exp secara independen dari jax.scipy.linalg.expm yang dipakai kode).
"""
import math
from datetime import datetime, timedelta, timezone

import jax.numpy as jnp
import numpy as np
import pytest

from apps.deterioration.services_ctmc import ComponentHistory, N_STATES, RegimeForwardFilter


def _make_single_transition_generator(rate: float) -> jnp.ndarray:
    """Generator 5x5 dengan hanya CS1->CS2 aktif (rate q), sisanya nol."""
    Q = np.zeros((N_STATES, N_STATES))
    Q[0, 1] = rate
    Q[0, 0] = -rate
    return jnp.asarray(Q)


class TestBuildJointGenerator:
    def test_joint_generator_entries_match_hand_computation(self):
        # regime 0=slow (q_cs=0.1), regime 1=fast (q_cs=0.5)
        # regime_generator: slow->fast rate 0.2, fast absorbing (searah)
        Q_slow = _make_single_transition_generator(0.1)
        Q_fast = _make_single_transition_generator(0.5)
        regime_generator = jnp.array([[-0.2, 0.2], [0.0, 0.0]])

        Q_joint = RegimeForwardFilter().build_joint_generator([Q_slow, Q_fast], regime_generator)
        Q_joint_np = np.asarray(Q_joint)

        # combined_idx = r * N_STATES + cs
        idx_slow_cs1 = 0 * N_STATES + 0
        idx_slow_cs2 = 0 * N_STATES + 1
        idx_fast_cs1 = 1 * N_STATES + 0
        idx_fast_cs2 = 1 * N_STATES + 1

        # Dalam-regime slow: CS1->CS2 rate 0.1
        assert Q_joint_np[idx_slow_cs1, idx_slow_cs2] == pytest.approx(0.1, abs=1e-6)
        # Antar-regime: CS tetap CS1, regime slow->fast rate 0.2
        assert Q_joint_np[idx_slow_cs1, idx_fast_cs1] == pytest.approx(0.2, abs=1e-6)
        # Diagonal (slow, CS1) = -(0.1 + 0.2) = -0.3
        assert Q_joint_np[idx_slow_cs1, idx_slow_cs1] == pytest.approx(-0.3, abs=1e-6)

        # Dalam-regime fast: CS1->CS2 rate 0.5
        assert Q_joint_np[idx_fast_cs1, idx_fast_cs2] == pytest.approx(0.5, abs=1e-6)
        # Regime fast absorbing -> tidak ada rate fast->slow
        assert Q_joint_np[idx_fast_cs1, idx_slow_cs1] == pytest.approx(0.0, abs=1e-6)
        # Diagonal (fast, CS1) = -(0.5 + 0) = -0.5
        assert Q_joint_np[idx_fast_cs1, idx_fast_cs1] == pytest.approx(-0.5, abs=1e-6)

    def test_every_row_of_joint_generator_sums_to_zero(self):
        Q_slow = _make_single_transition_generator(0.1)
        Q_fast = _make_single_transition_generator(0.5)
        regime_generator = jnp.array([[-0.2, 0.2], [0.0, 0.0]])

        Q_joint = RegimeForwardFilter().build_joint_generator([Q_slow, Q_fast], regime_generator)
        row_sums = np.asarray(Q_joint).sum(axis=1)
        np.testing.assert_allclose(row_sums, np.zeros(2 * N_STATES), atol=1e-6)


@pytest.mark.django_db
class TestPosteriorRegimeProbabilities:
    def test_posterior_matches_hand_computed_bayes_update_no_regime_switching(self):
        """Skenario disederhanakan: regime_generator = 0 (regime TIDAK
        berpindah selama observasi) -- sehingga posterior regime punya
        rumus tertutup klasik: P(transisi CS1->CS2 dalam waktu t | rate q)
        = 1 - e^(-qt). Posterior propto prior * likelihood ini per regime."""
        q_slow, q_fast = 0.1, 0.5
        Q_slow = _make_single_transition_generator(q_slow)
        Q_fast = _make_single_transition_generator(q_fast)
        regime_generator = jnp.zeros((2, 2))  # tidak ada perpindahan regime
        regime_priors = jnp.array([0.5, 0.5])

        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        history = ComponentHistory(
            component_id="dummy",
            observations=[("CS1", t0), ("CS2", t0 + timedelta(days=365.25))],
        )

        posterior = RegimeForwardFilter().posterior_regime_probabilities(
            history, [Q_slow, Q_fast], regime_generator, regime_priors,
        )
        posterior_np = np.asarray(posterior)

        # Hand-computed rumus tertutup CTMC 2-status, independen dari expm kode:
        p_transition_slow = 1 - math.exp(-q_slow * 1.0)
        p_transition_fast = 1 - math.exp(-q_fast * 1.0)
        unnormalized = np.array([0.5 * p_transition_slow, 0.5 * p_transition_fast])
        expected_posterior = unnormalized / unnormalized.sum()

        np.testing.assert_allclose(posterior_np, expected_posterior, atol=1e-4)
        # Sanity check konseptual: transisi cepat teramati -> regime fast
        # jauh lebih mungkin dibanding slow.
        assert posterior_np[1] > posterior_np[0]

    def test_posterior_sums_to_one(self):
        q_slow, q_fast = 0.1, 0.5
        Q_slow = _make_single_transition_generator(q_slow)
        Q_fast = _make_single_transition_generator(q_fast)
        regime_generator = jnp.zeros((2, 2))
        regime_priors = jnp.array([0.5, 0.5])

        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        history = ComponentHistory(
            component_id="dummy",
            observations=[("CS1", t0), ("CS2", t0 + timedelta(days=365.25))],
        )
        posterior = RegimeForwardFilter().posterior_regime_probabilities(
            history, [Q_slow, Q_fast], regime_generator, regime_priors,
        )
        assert float(jnp.sum(posterior)) == pytest.approx(1.0, abs=1e-6)

    def test_single_observation_returns_prior_unchanged(self):
        # Tanpa transisi teramati (cuma 1 titik data), posterior harus jatuh
        # kembali ke prior -- tidak ada informasi baru untuk update Bayes.
        q_slow, q_fast = 0.1, 0.5
        Q_slow = _make_single_transition_generator(q_slow)
        Q_fast = _make_single_transition_generator(q_fast)
        regime_generator = jnp.zeros((2, 2))
        regime_priors = jnp.array([0.3, 0.7])

        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        history = ComponentHistory(component_id="dummy", observations=[("CS1", t0)])

        posterior = RegimeForwardFilter().posterior_regime_probabilities(
            history, [Q_slow, Q_fast], regime_generator, regime_priors,
        )
        np.testing.assert_allclose(np.asarray(posterior), np.asarray(regime_priors), atol=1e-6)
