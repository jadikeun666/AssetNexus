"""
formulas.md §3.1 — BootstrapResampler. engineering-rules.md §7: properti
struktural yang harus selalu benar diverifikasi (bootstrap tidak punya
rumus tertutup untuk NILAI hasil resample individual -- sama seperti
CTMCLatentFittingService.fit(), ini optimasi gradient non-convex). Skala
KECIL (5 resample) dipakai di sini untuk kecepatan test suite; skala
produksi (500, DETERIORATION["BOOTSTRAP_RESAMPLES"]) diuji terpisah di
luar pytest untuk mengukur waktu nyata sebelum dipakai job produksi.

REVISI (Opsi A): resample_and_refit sekarang return dict
{"cs_generators": {...}, "regime_generator": ..., "regime_priors": ...,
"posterior": {...} atau None} per resample -- bukan {regime_idx: Q_r}
langsung seperti sebelumnya.
"""
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from apps.deterioration.services_ctmc import N_REGIMES, N_STATES, ComponentHistory
from apps.deterioration.services_fuzzy import BootstrapResampler


def _make_histories():
    t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
    return [
        ComponentHistory(
            component_id="a",
            observations=[("CS1", t0), ("CS1", t0 + timedelta(days=365)), ("CS2", t0 + timedelta(days=730))],
        ),
        ComponentHistory(
            component_id="b",
            observations=[("CS2", t0), ("CS3", t0 + timedelta(days=400))],
        ),
        ComponentHistory(
            component_id="c",
            observations=[
                ("CS1", t0), ("CS2", t0 + timedelta(days=300)),
                ("CS3", t0 + timedelta(days=600)), ("CS4", t0 + timedelta(days=900)),
            ],
        ),
    ]


class TestBootstrapResamplerStructuralProperties:
    def test_resample_and_refit_returns_correct_number_of_results(self):
        histories = _make_histories()
        results = BootstrapResampler().resample_and_refit(histories, seed=42, n_resamples=5)
        assert len(results) == 5

    def test_each_result_has_expected_top_level_keys(self):
        histories = _make_histories()
        results = BootstrapResampler().resample_and_refit(histories, seed=42, n_resamples=5)

        for result in results:
            assert set(result.keys()) == {"cs_generators", "regime_generator", "regime_priors", "posterior"}

    def test_each_result_has_all_regime_keys_with_valid_generator_shape(self):
        histories = _make_histories()
        results = BootstrapResampler().resample_and_refit(histories, seed=42, n_resamples=5)

        for result in results:
            cs_generators = result["cs_generators"]
            assert set(cs_generators.keys()) == set(range(N_REGIMES))
            for regime_idx, Q_r in cs_generators.items():
                assert Q_r.shape == (N_STATES, N_STATES)

    def test_each_result_generator_rows_sum_to_zero(self):
        # formulas.md §2.2: properti generator matrix harus tetap berlaku
        # untuk SETIAP hasil bootstrap, bukan cuma fit utama.
        histories = _make_histories()
        results = BootstrapResampler().resample_and_refit(histories, seed=42, n_resamples=5)

        for result in results:
            for regime_idx, Q_r in result["cs_generators"].items():
                row_sums = np.asarray(Q_r).sum(axis=1)
                np.testing.assert_allclose(row_sums, np.zeros(N_STATES), atol=1e-4)

    def test_each_result_off_diagonal_below_diagonal_is_zero(self):
        # formulas.md §1.1/§2.1: monotone deterioration-only harus tetap
        # berlaku untuk SETIAP hasil bootstrap.
        histories = _make_histories()
        results = BootstrapResampler().resample_and_refit(histories, seed=42, n_resamples=5)

        for result in results:
            for regime_idx, Q_r in result["cs_generators"].items():
                Q_np = np.asarray(Q_r)
                for i in range(N_STATES):
                    for j in range(N_STATES):
                        if j < i:
                            assert Q_np[i, j] == pytest.approx(0.0, abs=1e-6)

    def test_each_result_regime_generator_has_valid_shape_and_rows_sum_to_zero(self):
        # Cakupan Opsi A: regime_generator sekarang ikut dikembalikan.
        histories = _make_histories()
        results = BootstrapResampler().resample_and_refit(histories, seed=42, n_resamples=5)

        for result in results:
            regime_generator = np.asarray(result["regime_generator"])
            assert regime_generator.shape == (N_REGIMES, N_REGIMES)
            row_sums = regime_generator.sum(axis=1)
            np.testing.assert_allclose(row_sums, np.zeros(N_REGIMES), atol=1e-4)

    def test_each_result_regime_priors_sum_to_one(self):
        histories = _make_histories()
        results = BootstrapResampler().resample_and_refit(histories, seed=42, n_resamples=5)

        for result in results:
            regime_priors = np.asarray(result["regime_priors"])
            assert regime_priors.shape == (N_REGIMES,)
            assert float(regime_priors.sum()) == pytest.approx(1.0, abs=1e-4)
            assert (regime_priors >= 0).all()

    def test_posterior_is_none_when_target_component_history_not_given(self):
        histories = _make_histories()
        results = BootstrapResampler().resample_and_refit(histories, seed=42, n_resamples=5)

        for result in results:
            assert result["posterior"] is None

    def test_posterior_is_computed_per_resample_when_target_given(self):
        # Cakupan Opsi A: posterior regime KHUSUS komponen target dihitung
        # ULANG untuk SETIAP resample (bukan konstanta tunggal).
        histories = _make_histories()
        target = histories[0]  # component "a"

        results = BootstrapResampler().resample_and_refit(
            histories, seed=42, n_resamples=5, target_component_history=target,
        )

        for result in results:
            posterior = result["posterior"]
            assert posterior is not None
            assert set(posterior.keys()) == set(range(N_REGIMES))
            assert sum(posterior.values()) == pytest.approx(1.0, abs=1e-3)
            for p in posterior.values():
                assert p >= 0.0

    def test_resample_is_deterministic_given_same_seed(self):
        # engineering-rules.md §3: seed sama -> hasil bit-identical.
        histories = _make_histories()
        results_1 = BootstrapResampler().resample_and_refit(histories, seed=42, n_resamples=5)
        results_2 = BootstrapResampler().resample_and_refit(histories, seed=42, n_resamples=5)

        for r1, r2 in zip(results_1, results_2):
            for regime_idx in r1["cs_generators"]:
                np.testing.assert_array_equal(
                    np.asarray(r1["cs_generators"][regime_idx]),
                    np.asarray(r2["cs_generators"][regime_idx]),
                )

    def test_resample_differs_across_different_seeds(self):
        histories = _make_histories()
        results_1 = BootstrapResampler().resample_and_refit(histories, seed=42, n_resamples=5)
        results_2 = BootstrapResampler().resample_and_refit(histories, seed=99, n_resamples=5)

        # Setidaknya SATU regime di SATU resample harus berbeda -- seed
        # berbeda -> resample indeks berbeda -> hasil fit berbeda.
        any_different = False
        for r1, r2 in zip(results_1, results_2):
            for regime_idx in r1["cs_generators"]:
                if not np.allclose(
                    np.asarray(r1["cs_generators"][regime_idx]),
                    np.asarray(r2["cs_generators"][regime_idx]),
                    atol=1e-6,
                ):
                    any_different = True
        assert any_different

    def test_raises_on_empty_histories(self):
        with pytest.raises(ValueError):
            BootstrapResampler().resample_and_refit([], seed=42, n_resamples=5)
