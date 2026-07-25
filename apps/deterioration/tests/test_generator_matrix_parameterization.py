"""
formulas.md §2.2 — GeneratorMatrixParameterization. engineering-rules.md §7:
expected value dihitung tangan, bukan cuma "tidak error".
"""
import math

import jax.numpy as jnp
import numpy as np
import pytest

from apps.deterioration.services_ctmc import (
    N_RAW_PARAMS_PER_REGIME,
    N_RAW_PARAMS_REGIME_GENERATOR,
    N_REGIMES,
    N_STATES,
    GeneratorMatrixParameterization,
    RegimeGeneratorParameterization,
)

LOG2 = math.log(2.0)  # softplus(0) = log(1 + e^0) = log(2)


class TestGeneratorMatrixParameterization:
    def test_zero_raw_params_produces_hand_computed_generator(self):
        raw_params = jnp.zeros(N_RAW_PARAMS_PER_REGIME)
        Q = GeneratorMatrixParameterization().unconstrained_to_generator(raw_params)
        Q_np = np.asarray(Q)

        expected = np.array([
            [-4 * LOG2,      LOG2,      LOG2,      LOG2,  LOG2],
            [0.0,        -3 * LOG2,      LOG2,      LOG2,  LOG2],
            [0.0,             0.0,  -2 * LOG2,      LOG2,  LOG2],
            [0.0,             0.0,       0.0,      -LOG2,  LOG2],
            [0.0,             0.0,       0.0,        0.0,   0.0],
        ])
        np.testing.assert_allclose(Q_np, expected, atol=1e-6)

    def test_every_row_sums_to_zero(self):
        # formulas.md §2.2: "Q_r[i][i] = -Σ_{j≠i} Q_r[i][j] (rows sum to zero)"
        # -- properti ini harus berlaku untuk RAW_PARAMS APA PUN, tidak cuma nol.
        raw_params = jnp.array([0.3, -1.2, 2.5, 0.0, -0.7, 1.1, -2.0, 0.4, 0.9, -0.1])
        Q = GeneratorMatrixParameterization().unconstrained_to_generator(raw_params)
        row_sums = np.asarray(Q).sum(axis=1)
        np.testing.assert_allclose(row_sums, np.zeros(N_STATES), atol=1e-6)

    def test_off_diagonal_below_diagonal_is_always_zero(self):
        # formulas.md §1.1/§2.1: monotone deterioration-only -- tidak ada
        # rate untuk j < i, apa pun raw_params-nya.
        raw_params = jnp.array([5.0, -3.0, 10.0, -8.0, 2.0, -1.0, 4.0, -6.0, 1.5, -2.5])
        Q = GeneratorMatrixParameterization().unconstrained_to_generator(raw_params)
        Q_np = np.asarray(Q)
        for i in range(N_STATES):
            for j in range(N_STATES):
                if j < i:
                    assert Q_np[i, j] == 0.0

    def test_off_diagonal_above_diagonal_always_nonnegative_even_for_very_negative_raw_params(self):
        # Ini inti properti reparameterisasi: softplus(z) >= 0 untuk SEMUA z,
        # termasuk z sangat negatif -- optimizer bebas melangkah ke mana saja
        # tanpa pernah menghasilkan Q_r yang melanggar §2.2.
        raw_params = jnp.full((N_RAW_PARAMS_PER_REGIME,), -1000.0)
        Q = GeneratorMatrixParameterization().unconstrained_to_generator(raw_params)
        Q_np = np.asarray(Q)
        for i, j in [(0, 1), (0, 4), (1, 2), (2, 3), (3, 4)]:
            assert Q_np[i, j] >= 0.0

    def test_cs5_row_is_absorbing_regardless_of_raw_params(self):
        # formulas.md §2.1: CS5 absorbing di dalam satu regime -- baris CS5
        # (index 4) harus nol total, apa pun raw_params.
        raw_params = jnp.array([1.0, 2.0, 3.0, 4.0, -1.0, -2.0, -3.0, 5.0, -5.0, 0.5])
        Q = GeneratorMatrixParameterization().unconstrained_to_generator(raw_params)
        Q_np = np.asarray(Q)
        np.testing.assert_allclose(Q_np[4, :], np.zeros(N_STATES), atol=1e-6)

    def test_wrong_shape_raw_params_raises(self):
        with pytest.raises(AssertionError):
            GeneratorMatrixParameterization().unconstrained_to_generator(jnp.zeros(3))

    def test_init_is_deterministic_given_same_seed(self):
        # engineering-rules.md §3: seed sama -> hasil bit-identical.
        service = GeneratorMatrixParameterization()
        init_1 = service.generator_to_unconstrained_init(seed=42)
        init_2 = service.generator_to_unconstrained_init(seed=42)
        np.testing.assert_array_equal(np.asarray(init_1), np.asarray(init_2))

    def test_init_differs_across_different_seeds(self):
        service = GeneratorMatrixParameterization()
        init_1 = service.generator_to_unconstrained_init(seed=42)
        init_2 = service.generator_to_unconstrained_init(seed=99)
        assert not np.allclose(np.asarray(init_1), np.asarray(init_2))

    def test_init_has_correct_shape(self):
        service = GeneratorMatrixParameterization()
        init = service.generator_to_unconstrained_init(seed=42)
        assert init.shape == (N_RAW_PARAMS_PER_REGIME,)


class TestGeneratorMatrixParameterizationInverse:
    """Round-trip test untuk generator_to_unconstrained -- inverse dari
    unconstrained_to_generator, dipakai warm-start BootstrapResampler
    (formulas.md §3.1). Diverifikasi lewat round-trip raw -> Q -> raw',
    HARUS raw ~= raw' (bukan menghitung log(expm1(...)) manual, karena
    itu SENDIRI adalah definisi inverse eksak dari softplus)."""

    def test_round_trip_recovers_original_raw_params(self):
        service = GeneratorMatrixParameterization()
        raw_params_original = jnp.array([1.0, -0.5, 2.0, 0.3, -1.2, 0.8, 1.5, -0.7, 0.2, 1.1])

        Q = service.unconstrained_to_generator(raw_params_original)
        raw_params_recovered = service.generator_to_unconstrained(Q)

        np.testing.assert_allclose(
            np.asarray(raw_params_recovered), np.asarray(raw_params_original), atol=1e-4
        )

    def test_round_trip_with_zero_raw_params(self):
        # Kasus khusus dari test_zero_raw_params_produces_hand_computed_generator:
        # raw_params=0 -> rate=log(2) untuk semua off-diagonal j>i.
        service = GeneratorMatrixParameterization()
        raw_params_original = jnp.zeros(N_RAW_PARAMS_PER_REGIME)

        Q = service.unconstrained_to_generator(raw_params_original)
        raw_params_recovered = service.generator_to_unconstrained(Q)

        np.testing.assert_allclose(
            np.asarray(raw_params_recovered), np.asarray(raw_params_original), atol=1e-4
        )

    def test_forward_then_inverse_then_forward_again_produces_same_generator(self):
        # Uji tambahan: Q -> raw -> Q' harus identik (bukan cuma raw -> Q -> raw').
        service = GeneratorMatrixParameterization()
        raw_params = jnp.array([0.5, -0.3, 1.0, 0.2, -0.8, 0.6, 1.2, -0.4, 0.1, 0.9])

        Q_original = service.unconstrained_to_generator(raw_params)
        raw_recovered = service.generator_to_unconstrained(Q_original)
        Q_recovered = service.unconstrained_to_generator(raw_recovered)

        np.testing.assert_allclose(np.asarray(Q_recovered), np.asarray(Q_original), atol=1e-4)


class TestRegimeGeneratorParameterizationInverse:
    """Round-trip test untuk RegimeGeneratorParameterization -- prinsip SAMA
    dengan GeneratorMatrixParameterization, ukuran beda (N_REGIMES)."""

    def test_round_trip_recovers_original_raw_params(self):
        service = RegimeGeneratorParameterization()
        raw_params_original = jnp.array([0.7, -0.2, 1.3])  # N_RAW_PARAMS_REGIME_GENERATOR=3

        Q = service.unconstrained_to_generator(raw_params_original)
        raw_params_recovered = service.generator_to_unconstrained(Q)

        np.testing.assert_allclose(
            np.asarray(raw_params_recovered), np.asarray(raw_params_original), atol=1e-4
        )

    def test_round_trip_with_zero_raw_params(self):
        service = RegimeGeneratorParameterization()
        raw_params_original = jnp.zeros(N_RAW_PARAMS_REGIME_GENERATOR)

        Q = service.unconstrained_to_generator(raw_params_original)
        raw_params_recovered = service.generator_to_unconstrained(Q)

        np.testing.assert_allclose(
            np.asarray(raw_params_recovered), np.asarray(raw_params_original), atol=1e-4
        )


class TestGeneratorMatrixParameterizationOverflowSafety:
    """Regression test untuk bug NaN yang ditemukan saat debugging
    FuzzyBoundsService: regime dengan posterior_weight=0 selama fitting
    bisa melenceng ke rate SANGAT BESAR (tidak dikontrol data), yang
    sebelum perbaikan menyebabkan expm1 overflow -> log(inf)=inf ->
    NaN saat dikalikan bobot posterior nol."""

    def test_large_rate_does_not_produce_inf_or_nan(self):
        service = GeneratorMatrixParameterization()
        # Rate mirip yang ditemukan saat debugging: ~1.47e5 dan ~6.64e5
        Q = jnp.zeros((N_STATES, N_STATES))
        Q = Q.at[0, 1].set(147330.0)
        Q = Q.at[0, 0].set(-147330.0)

        raw_params = service.generator_to_unconstrained(Q)

        assert not bool(jnp.any(jnp.isnan(raw_params)))
        assert not bool(jnp.any(jnp.isinf(raw_params)))

    def test_large_rate_round_trip_is_clipped_to_max_annual_rate(self):
        # REVISI setelah MAX_ANNUAL_RATE ditambahkan (config/assetnexus.py):
        # unconstrained_to_generator SEKARANG SENGAJA meng-clip rate ekstrem
        # ke ambang aman -- round-trip TIDAK LAGI diharapkan mendekati nilai
        # asli untuk rate di atas ambang (itu justru perilaku yang benar,
        # bukan bug). Verifikasi: hasil akhir DIBATASI ke MAX_ANNUAL_RATE,
        # bukan round-trip eksak/mendekati.
        from config.assetnexus import DETERIORATION

        service = GeneratorMatrixParameterization()
        Q_original = jnp.zeros((N_STATES, N_STATES))
        Q_original = Q_original.at[0, 1].set(50000.0)
        Q_original = Q_original.at[0, 0].set(-50000.0)

        raw_params = service.generator_to_unconstrained(Q_original)
        Q_recovered = service.unconstrained_to_generator(raw_params)

        max_rate = DETERIORATION["MAX_ANNUAL_RATE"]
        assert float(Q_recovered[0, 1]) == pytest.approx(max_rate, abs=1e-4)
        assert float(Q_recovered[0, 0]) == pytest.approx(-max_rate, abs=1e-4)

    def test_zero_multiplied_by_large_rate_never_produces_nan(self):
        # Reproduksi LANGSUNG skenario bug: posterior_weight=0.0 dikalikan
        # generator dengan rate besar -- HARUS 0.0, bukan NaN.
        service = GeneratorMatrixParameterization()
        Q = jnp.zeros((N_STATES, N_STATES))
        Q = Q.at[0, 1].set(664230.0)
        Q = Q.at[0, 0].set(-664230.0)

        raw_params = service.generator_to_unconstrained(Q)
        Q_reconstructed = service.unconstrained_to_generator(raw_params)

        posterior_weight = 0.0
        result = posterior_weight * np.asarray(Q_reconstructed)

        assert not np.any(np.isnan(result))
        np.testing.assert_allclose(result, np.zeros((N_STATES, N_STATES)), atol=1e-10)


class TestRegimeGeneratorParameterizationOverflowSafety:
    def test_large_rate_does_not_produce_inf_or_nan(self):
        service = RegimeGeneratorParameterization()
        Q = jnp.zeros((N_REGIMES, N_REGIMES))
        Q = Q.at[0, 1].set(200000.0)
        Q = Q.at[0, 0].set(-200000.0)

        raw_params = service.generator_to_unconstrained(Q)

        assert not bool(jnp.any(jnp.isnan(raw_params)))
        assert not bool(jnp.any(jnp.isinf(raw_params)))
