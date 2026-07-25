"""
FASE B (bootstrap vmap+padding, formulas.md §3.1) — regression test:
batched_joint_log_likelihood (jax.vmap atas forward_filter_scan_masked)
HARUS menghasilkan angka IDENTIK dengan CTMCLatentFittingService
._joint_log_likelihood (loop Python, sudah teruji -- TIDAK disentuh).
Ini gerbang wajib sebelum batching dipakai BootstrapResampler (Fase C).
"""
from datetime import datetime, timedelta, timezone

import jax.numpy as jnp
import numpy as np
import pytest

from apps.deterioration.services_ctmc import (
    ComponentHistory,
    N_REGIMES,
    N_STATES,
    CTMCLatentFittingService,
    RegimeForwardFilter,
    batched_joint_log_likelihood,
    forward_filter_scan,
    forward_filter_scan_masked,
    history_to_arrays,
    pad_histories_to_arrays,
)


def _single_transition_generator(rate: float) -> jnp.ndarray:
    Q = np.zeros((N_STATES, N_STATES))
    Q[0, 1] = rate
    Q[0, 0] = -rate
    return jnp.asarray(Q)


class TestPadHistoriesToArrays:
    def test_padding_preserves_original_observations(self):
        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        history_short = ComponentHistory(
            component_id="c1", observations=[("CS1", t0), ("CS2", t0 + timedelta(days=365))],
        )
        history_long = ComponentHistory(
            component_id="c2",
            observations=[
                ("CS2", t0), ("CS3", t0 + timedelta(days=365)),
                ("CS3", t0 + timedelta(days=730)), ("CS4", t0 + timedelta(days=1095)),
            ],
        )

        cs_indices, delta_years, transition_mask = pad_histories_to_arrays([history_short, history_long])

        assert cs_indices.shape == (2, 4)
        assert delta_years.shape == (2, 3)
        assert transition_mask.shape == (2, 3)

        # history_short: 2 observasi asli -> 1 transisi asli, 2 padding
        assert bool(transition_mask[0, 0]) is True
        assert bool(transition_mask[0, 1]) is False
        assert bool(transition_mask[0, 2]) is False

        # history_long: 4 observasi asli -> 3 transisi asli, tanpa padding
        assert bool(transition_mask[1, 0]) is True
        assert bool(transition_mask[1, 1]) is True
        assert bool(transition_mask[1, 2]) is True

    def test_masked_scan_matches_unmasked_scan_for_history_without_padding(self):
        # Untuk histori yang KEBETULAN tidak butuh padding (semua mask True),
        # forward_filter_scan_masked HARUS identik dengan forward_filter_scan
        # (Fase A, sudah diverifikasi identik dengan loop asli).
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

        cs_indices_unmasked, delta_years_unmasked = history_to_arrays(history)
        ll_unmasked, posterior_unmasked = forward_filter_scan(
            Q_joint, cs_indices_unmasked, delta_years_unmasked, regime_priors, n_regimes=2,
        )

        cs_indices_batch, delta_years_batch, mask_batch = pad_histories_to_arrays([history])
        ll_masked, posterior_masked = forward_filter_scan_masked(
            Q_joint, cs_indices_batch[0], delta_years_batch[0], mask_batch[0], regime_priors, n_regimes=2,
        )

        assert float(ll_masked) == pytest.approx(float(ll_unmasked), abs=1e-6)
        np.testing.assert_allclose(np.asarray(posterior_masked), np.asarray(posterior_unmasked), atol=1e-6)

    def test_masked_scan_with_actual_padding_matches_scan_on_unpadded_history(self):
        # Histori PENDEK dipadding karena ada histori lain lebih panjang di
        # batch yang sama -- hasil untuk histori pendek ini harus TETAP
        # identik dengan forward_filter_scan dijalankan LANGSUNG pada
        # histori pendek tanpa padding sama sekali.
        Q_slow = _single_transition_generator(0.1)
        Q_fast = _single_transition_generator(0.5)
        regime_generator = jnp.zeros((2, 2))
        regime_priors = jnp.array([0.5, 0.5])

        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        history_short = ComponentHistory(
            component_id="c1", observations=[("CS1", t0), ("CS2", t0 + timedelta(days=365))],
        )
        history_long = ComponentHistory(
            component_id="c2",
            observations=[
                ("CS2", t0), ("CS3", t0 + timedelta(days=365)),
                ("CS3", t0 + timedelta(days=730)), ("CS4", t0 + timedelta(days=1095)),
            ],
        )

        forward_filter = RegimeForwardFilter()
        Q_joint = forward_filter.build_joint_generator([Q_slow, Q_fast], regime_generator)

        # Referensi: forward_filter_scan LANGSUNG pada history_short saja (tanpa padding)
        cs_ref, dt_ref = history_to_arrays(history_short)
        ll_ref, posterior_ref = forward_filter_scan(Q_joint, cs_ref, dt_ref, regime_priors, n_regimes=2)

        # Batch: history_short dipadding mengikuti panjang history_long
        cs_batch, dt_batch, mask_batch = pad_histories_to_arrays([history_short, history_long])
        ll_padded, posterior_padded = forward_filter_scan_masked(
            Q_joint, cs_batch[0], dt_batch[0], mask_batch[0], regime_priors, n_regimes=2,
        )

        assert float(ll_padded) == pytest.approx(float(ll_ref), abs=1e-6)
        np.testing.assert_allclose(np.asarray(posterior_padded), np.asarray(posterior_ref), atol=1e-6)


class TestBatchedJointLogLikelihoodMatchesLoopVersion:
    def test_batched_total_matches_loop_version_on_pooled_dataset(self):
        # Verifikasi END-TO-END: batched_joint_log_likelihood (vmap) atas
        # beberapa histori beda panjang HARUS menghasilkan total identik
        # dengan CTMCLatentFittingService._joint_log_likelihood (loop asli).
        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        history_a = ComponentHistory(
            component_id="a",
            observations=[("CS1", t0), ("CS1", t0 + timedelta(days=365)), ("CS2", t0 + timedelta(days=730))],
        )
        history_b = ComponentHistory(
            component_id="b",
            observations=[("CS2", t0), ("CS3", t0 + timedelta(days=400))],
        )
        history_c = ComponentHistory(
            component_id="c",
            observations=[
                ("CS1", t0), ("CS2", t0 + timedelta(days=300)),
                ("CS3", t0 + timedelta(days=600)), ("CS4", t0 + timedelta(days=900)),
            ],
        )
        histories = [history_a, history_b, history_c]

        raw_params = jnp.array(np.random.RandomState(7).normal(size=0))  # placeholder, diisi bawah
        from apps.deterioration.services_ctmc import N_RAW_PARAMS_TOTAL
        raw_params = jnp.array(np.random.RandomState(7).normal(size=N_RAW_PARAMS_TOTAL))

        service = CTMCLatentFittingService()
        cs_generators, regime_generator, regime_priors = service._unpack_params(raw_params)

        expected_neg_ll = float(service._joint_log_likelihood(raw_params, histories))

        forward_filter = RegimeForwardFilter()
        Q_joint = forward_filter.build_joint_generator(cs_generators, regime_generator)
        cs_indices_batch, delta_years_batch, mask_batch = pad_histories_to_arrays(histories)

        actual_neg_ll = float(batched_joint_log_likelihood(
            Q_joint, cs_indices_batch, delta_years_batch, mask_batch, regime_priors, N_REGIMES,
        ))

        assert actual_neg_ll == pytest.approx(expected_neg_ll, abs=1e-4)

    def test_batched_version_is_jittable_and_vmappable(self):
        # Prasyarat Fase C: batched_joint_log_likelihood harus bisa di-jit.
        import jax
        from apps.deterioration.services_ctmc import N_RAW_PARAMS_TOTAL

        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        histories = [
            ComponentHistory(component_id="a", observations=[("CS1", t0), ("CS2", t0 + timedelta(days=365))]),
            ComponentHistory(component_id="b", observations=[("CS2", t0), ("CS3", t0 + timedelta(days=400))]),
        ]

        raw_params = jnp.array(np.random.RandomState(3).normal(size=N_RAW_PARAMS_TOTAL))
        service = CTMCLatentFittingService()
        cs_generators, regime_generator, regime_priors = service._unpack_params(raw_params)
        forward_filter = RegimeForwardFilter()
        Q_joint = forward_filter.build_joint_generator(cs_generators, regime_generator)
        cs_indices_batch, delta_years_batch, mask_batch = pad_histories_to_arrays(histories)

        jitted_fn = jax.jit(batched_joint_log_likelihood, static_argnames=["n_regimes"])
        result_jit = jitted_fn(Q_joint, cs_indices_batch, delta_years_batch, mask_batch, regime_priors, N_REGIMES)
        result_eager = batched_joint_log_likelihood(
            Q_joint, cs_indices_batch, delta_years_batch, mask_batch, regime_priors, N_REGIMES,
        )

        assert float(result_jit) == pytest.approx(float(result_eager), abs=1e-6)
