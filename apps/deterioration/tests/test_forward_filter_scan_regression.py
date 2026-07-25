"""
FASE A (bootstrap vmap+padding, formulas.md §3.1) — regression test:
forward_filter_scan (jax.lax.scan, dipakai BootstrapResampler Fase B/C)
HARUS menghasilkan angka IDENTIK dengan RegimeForwardFilter
.log_likelihood_and_posterior (loop Python, dipakai CTMCLatentFittingService
.fit() -- TIDAK disentuh). Ini gerbang wajib sebelum forward_filter_scan
dipakai di mana pun untuk fitting sungguhan.
"""
from datetime import datetime, timedelta, timezone

import jax.numpy as jnp
import numpy as np
import pytest

from apps.deterioration.services_ctmc import (
    ComponentHistory,
    N_STATES,
    RegimeForwardFilter,
    forward_filter_scan,
    history_to_arrays,
)


def _single_transition_generator(rate: float) -> jnp.ndarray:
    Q = np.zeros((N_STATES, N_STATES))
    Q[0, 1] = rate
    Q[0, 0] = -rate
    return jnp.asarray(Q)


class TestForwardFilterScanMatchesLoopVersion:
    def test_two_observation_history_matches_loop_version_exactly(self):
        Q_slow = _single_transition_generator(0.1)
        Q_fast = _single_transition_generator(0.5)
        regime_generator = jnp.zeros((2, 2))
        regime_priors = jnp.array([0.5, 0.5])

        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        history = ComponentHistory(
            component_id="dummy",
            observations=[("CS1", t0), ("CS2", t0 + timedelta(days=365.25))],
        )

        forward_filter = RegimeForwardFilter()
        ll_loop, posterior_loop = forward_filter.log_likelihood_and_posterior(
            history, [Q_slow, Q_fast], regime_generator, regime_priors,
        )

        Q_joint = forward_filter.build_joint_generator([Q_slow, Q_fast], regime_generator)
        cs_indices, delta_years = history_to_arrays(history)
        ll_scan, posterior_scan = forward_filter_scan(
            Q_joint, cs_indices, delta_years, regime_priors, n_regimes=2,
        )

        assert float(ll_scan) == pytest.approx(float(ll_loop), abs=1e-6)
        np.testing.assert_allclose(np.asarray(posterior_scan), np.asarray(posterior_loop), atol=1e-6)

    def test_multi_observation_history_matches_loop_version_exactly(self):
        # Histori lebih panjang (4 observasi, 3 interval) -- kasus lebih
        # dekat dengan data pooled sungguhan (MIN_INSPECTIONS_FOR_CTMC=4).
        Q_slow = _single_transition_generator(0.15)
        Q_normal = _single_transition_generator(0.3)
        Q_fast = _single_transition_generator(0.6)
        regime_generator = jnp.array([
            [-0.05, 0.03, 0.02],
            [0.0, -0.04, 0.04],
            [0.0, 0.0, 0.0],
        ])
        regime_priors = jnp.array([0.5, 0.3, 0.2])

        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        history = ComponentHistory(
            component_id="dummy",
            observations=[
                ("CS1", t0),
                ("CS1", t0 + timedelta(days=365)),
                ("CS2", t0 + timedelta(days=800)),
                ("CS2", t0 + timedelta(days=1200)),
            ],
        )

        forward_filter = RegimeForwardFilter()
        ll_loop, posterior_loop = forward_filter.log_likelihood_and_posterior(
            history, [Q_slow, Q_normal, Q_fast], regime_generator, regime_priors,
        )

        Q_joint = forward_filter.build_joint_generator([Q_slow, Q_normal, Q_fast], regime_generator)
        cs_indices, delta_years = history_to_arrays(history)
        ll_scan, posterior_scan = forward_filter_scan(
            Q_joint, cs_indices, delta_years, regime_priors, n_regimes=3,
        )

        assert float(ll_scan) == pytest.approx(float(ll_loop), abs=1e-6)
        np.testing.assert_allclose(np.asarray(posterior_scan), np.asarray(posterior_loop), atol=1e-6)

    def test_single_observation_history_matches_loop_version(self):
        # Kasus tanpa transisi teramati -- loop version sudah diverifikasi
        # menghasilkan log_likelihood=0 (test_ctmc_fitting.py). scan version
        # harus setara.
        Q_slow = _single_transition_generator(0.1)
        Q_fast = _single_transition_generator(0.5)
        regime_generator = jnp.zeros((2, 2))
        regime_priors = jnp.array([0.5, 0.5])

        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        history = ComponentHistory(component_id="dummy", observations=[("CS1", t0)])

        forward_filter = RegimeForwardFilter()
        ll_loop, posterior_loop = forward_filter.log_likelihood_and_posterior(
            history, [Q_slow, Q_fast], regime_generator, regime_priors,
        )

        Q_joint = forward_filter.build_joint_generator([Q_slow, Q_fast], regime_generator)
        cs_indices, delta_years = history_to_arrays(history)
        ll_scan, posterior_scan = forward_filter_scan(
            Q_joint, cs_indices, delta_years, regime_priors, n_regimes=2,
        )

        assert float(ll_scan) == pytest.approx(0.0, abs=1e-6)
        assert float(ll_scan) == pytest.approx(float(ll_loop), abs=1e-6)
        np.testing.assert_allclose(np.asarray(posterior_scan), np.asarray(posterior_loop), atol=1e-6)

    def test_scan_version_is_jittable(self):
        # Prasyarat Fase B/C: forward_filter_scan harus bisa di-jax.jit
        # tanpa error -- ini yang membedakannya dari versi loop Python biasa.
        import jax

        Q_slow = _single_transition_generator(0.1)
        Q_fast = _single_transition_generator(0.5)
        regime_generator = jnp.zeros((2, 2))
        regime_priors = jnp.array([0.5, 0.5])

        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        history = ComponentHistory(
            component_id="dummy",
            observations=[("CS1", t0), ("CS2", t0 + timedelta(days=365.25))],
        )

        forward_filter = RegimeForwardFilter()
        Q_joint = forward_filter.build_joint_generator([Q_slow, Q_fast], regime_generator)
        cs_indices, delta_years = history_to_arrays(history)

        jitted_fn = jax.jit(forward_filter_scan, static_argnames=["n_regimes"])
        ll_jit, posterior_jit = jitted_fn(Q_joint, cs_indices, delta_years, regime_priors, n_regimes=2)

        ll_eager, posterior_eager = forward_filter_scan(
            Q_joint, cs_indices, delta_years, regime_priors, n_regimes=2
        )
        assert float(ll_jit) == pytest.approx(float(ll_eager), abs=1e-6)
