"""
formulas.md §2.3 — CTMCLatentFittingService. engineering-rules.md §7:
bagian yang bisa dihitung tangan (unpacking, log-likelihood tanpa transisi)
diverifikasi eksak. fit() end-to-end (optimasi gradient non-convex) TIDAK
punya rumus tertutup untuk nilai optimum -- diverifikasi lewat properti
struktural yang harus selalu benar terlepas dari hasil optimasi spesifik.
"""
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import jax.numpy as jnp
import numpy as np
import pytest

from apps.assets.models import Asset, AssetComponent
from apps.core.models import Organization, User
from apps.deterioration.models import DeteriorationModel, TransitionMatrix
import jax.numpy as jnp

from apps.deterioration.services_ctmc import (
    N_RAW_PARAMS_TOTAL,
    N_REGIMES,
    N_STATES,
    CTMCLatentFittingService,
    ComponentHistory,
)
from apps.inspections.models import InspectionRecord


@pytest.fixture
def org():
    return Organization.objects.create(name="Dinas PU Test CTMC Fitting")


@pytest.fixture
def inspector(org):
    return User.objects.create(
        keycloak_sub="sub-ctmc-fit-1", organization=org, username="sari",
        email="sari-ctmc-fit@example.id", role=User.Role.INSPECTOR,
    )


def _make_bridge(org, code):
    return Asset.objects.create(
        organization=org, code=code, name=f"Bridge {code}", asset_type=Asset.AssetType.BRIDGE,
        latitude=Decimal("0"), longitude=Decimal("0"), importance_weight=Decimal("5.00"),
    )


def _make_girder(asset):
    return AssetComponent.objects.create(
        asset=asset, component_type="girder", criticality_weight=Decimal("0.250"),
    )


def _inspect(component, inspector, state, when):
    return InspectionRecord.objects.create(
        component=component, inspector=inspector, inspected_at=when,
        method=InspectionRecord.Method.VISUAL, condition_state=state,
    )


class TestUnpackParams:
    def test_unpack_produces_correct_shapes(self):
        raw_params = jnp.zeros(N_RAW_PARAMS_TOTAL)
        cs_generators, regime_generator, regime_priors = CTMCLatentFittingService()._unpack_params(raw_params)

        assert len(cs_generators) == N_REGIMES
        for Q_r in cs_generators:
            assert Q_r.shape == (N_STATES, N_STATES)
        assert regime_generator.shape == (N_REGIMES, N_REGIMES)
        assert regime_priors.shape == (N_REGIMES,)

    def test_unpacked_regime_priors_sum_to_one_via_softmax(self):
        # Hand-computed softmax([0,0,0]) = [1/3, 1/3, 1/3] persis.
        raw_params = jnp.zeros(N_RAW_PARAMS_TOTAL)
        _, _, regime_priors = CTMCLatentFittingService()._unpack_params(raw_params)
        np.testing.assert_allclose(np.asarray(regime_priors), np.array([1 / 3, 1 / 3, 1 / 3]), atol=1e-6)
        assert float(jnp.sum(regime_priors)) == pytest.approx(1.0, abs=1e-6)

    def test_unpacked_cs_generators_and_regime_generator_rows_sum_to_zero(self):
        # Properti generator matrix (formulas.md §2.2) harus tetap berlaku
        # SETELAH unpacking dari raw_params gabungan, apa pun nilainya.
        raw_params = jnp.array(np.random.RandomState(0).normal(size=N_RAW_PARAMS_TOTAL))
        cs_generators, regime_generator, _ = CTMCLatentFittingService()._unpack_params(raw_params)

        for Q_r in cs_generators:
            row_sums = np.asarray(Q_r).sum(axis=1)
            np.testing.assert_allclose(row_sums, np.zeros(N_STATES), atol=1e-5)

        regime_row_sums = np.asarray(regime_generator).sum(axis=1)
        np.testing.assert_allclose(regime_row_sums, np.zeros(N_REGIMES), atol=1e-5)


class TestJointLogLikelihoodClosedFormCases:
    def test_single_observation_history_contributes_zero_log_likelihood(self):
        # Tanpa transisi teramati (1 titik data saja), tidak ada informasi
        # untuk update -- log-likelihood kontribusinya persis 0 (log(1)),
        # terlepas dari raw_params apa pun. Ini rumus tertutup EKSAK,
        # bukan pendekatan.
        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        history = ComponentHistory(component_id="dummy", observations=[("CS1", t0)])

        raw_params = jnp.array(np.random.RandomState(1).normal(size=N_RAW_PARAMS_TOTAL))
        neg_log_likelihood = CTMCLatentFittingService()._joint_log_likelihood(raw_params, [history])

        assert float(neg_log_likelihood) == pytest.approx(0.0, abs=1e-6)

    def test_negative_log_likelihood_sums_across_multiple_histories(self):
        # Menguji logic AGREGASI (bukan menduplikasi hitung tangan forward-
        # filter, yang sudah divalidasi terpisah di
        # test_regime_forward_filter.py): total neg-log-likelihood atas N
        # histories harus persis penjumlahan neg-log-likelihood tiap
        # histori dihitung SENDIRI-SENDIRI dengan generator yang SAMA
        # (dari raw_params yang sama, di-unpack sekali).
        from apps.deterioration.services_ctmc import RegimeForwardFilter

        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        history_1 = ComponentHistory(
            component_id="c1",
            observations=[("CS1", t0), ("CS2", t0 + timedelta(days=365.25))],
        )
        history_2 = ComponentHistory(
            component_id="c2",
            observations=[("CS2", t0), ("CS3", t0 + timedelta(days=730.5))],
        )

        raw_params = jnp.array(np.random.RandomState(2).normal(size=N_RAW_PARAMS_TOTAL))
        service = CTMCLatentFittingService()
        cs_generators, regime_generator, regime_priors = service._unpack_params(raw_params)

        forward_filter = RegimeForwardFilter()
        ll_1, _ = forward_filter.log_likelihood_and_posterior(
            history_1, cs_generators, regime_generator, regime_priors
        )
        ll_2, _ = forward_filter.log_likelihood_and_posterior(
            history_2, cs_generators, regime_generator, regime_priors
        )
        expected_neg_total = -(float(ll_1) + float(ll_2))

        actual_neg_total = float(service._joint_log_likelihood(raw_params, [history_1, history_2]))
        assert actual_neg_total == pytest.approx(expected_neg_total, abs=1e-5)


@pytest.mark.django_db
class TestFitEndToEndStructuralProperties:
    """fit() menjalankan optimasi gradient non-convex -- TIDAK ada nilai
    optimum yang bisa dihitung tangan (beda dengan DTMC closed-form MLE).
    Diverifikasi lewat properti struktural yang harus selalu benar."""

    def _make_dataset(self, org, inspector, code_prefix):
        asset_a = _make_bridge(org, f"{code_prefix}-A")
        asset_b = _make_bridge(org, f"{code_prefix}-B")
        comp_a = _make_girder(asset_a)
        comp_b = _make_girder(asset_b)

        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        # comp_a: 4 observasi (mencapai MIN_INSPECTIONS_FOR_CTMC)
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS1, t0)
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS1, t0 + timedelta(days=365))
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS2, t0 + timedelta(days=730))
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS2, t0 + timedelta(days=1095))
        # comp_b: histori pooled tambahan (cluster sama)
        _inspect(comp_b, inspector, InspectionRecord.ConditionState.CS2, t0)
        _inspect(comp_b, inspector, InspectionRecord.ConditionState.CS3, t0 + timedelta(days=365))

        return comp_a, comp_b

    def test_fit_creates_ctmc_latent_model_with_valid_structure(self, org, inspector):
        comp_a, _ = self._make_dataset(org, inspector, "CTMCFIT1")

        model = CTMCLatentFittingService().fit(
            organization_id=org.id, asset_type="bridge", component_type="girder", component=comp_a,
        )

        assert model.model_type == DeteriorationModel.ModelType.CTMC_LATENT
        assert model.model_version == 1
        assert model.training_data_hash  # non-empty

        params = model.parameters
        assert set(params["generators"].keys()) == {"slow", "normal", "fast"}
        for regime_name, Q_r in params["generators"].items():
            assert len(Q_r) == N_STATES
            assert len(Q_r[0]) == N_STATES

        posterior = params["regime_posterior_this_component"]
        assert set(posterior.keys()) == {"slow", "normal", "fast"}
        assert sum(posterior.values()) == pytest.approx(1.0, abs=1e-3)
        for p in posterior.values():
            assert p >= 0.0

    def test_fit_transition_matrix_only_stores_monotone_off_diagonal_cells(self, org, inspector):
        comp_a, _ = self._make_dataset(org, inspector, "CTMCFIT2")

        model = CTMCLatentFittingService().fit(
            organization_id=org.id, asset_type="bridge", component_type="girder", component=comp_a,
        )
        rows = TransitionMatrix.objects.filter(model=model)
        state_order = ["CS1", "CS2", "CS3", "CS4", "CS5"]

        assert rows.count() == 10  # OFF_DIAGONAL_CELLS: 4+3+2+1+0
        for row in rows:
            from_idx = state_order.index(row.from_state)
            to_idx = state_order.index(row.to_state)
            assert to_idx > from_idx  # strict j>i, bukan j>=i seperti DTMC
            assert row.fuzzy_lower is None  # belum diisi -- itu tugas FuzzyBoundsService
            assert row.fuzzy_upper is None

    def test_fit_version_increments_on_refit_and_coexists_with_dtmc(self, org, inspector):
        # Regression test langsung untuk fix versioning global-per-component
        # yang sudah dilakukan di services.py -- CTMC dan DTMC untuk
        # component YANG SAMA tidak boleh bentrok model_version.
        from apps.deterioration.services import DiscreteMarkovFittingService

        comp_a, _ = self._make_dataset(org, inspector, "CTMCFIT3")

        dtmc_model = DiscreteMarkovFittingService().fit(org.id, "bridge", "girder", comp_a)
        assert dtmc_model.model_version == 1

        ctmc_model_v1 = CTMCLatentFittingService().fit(org.id, "bridge", "girder", comp_a)
        assert ctmc_model_v1.model_version == 2  # global per component, bukan 1 lagi

        ctmc_model_v2 = CTMCLatentFittingService().fit(org.id, "bridge", "girder", comp_a)
        assert ctmc_model_v2.model_version == 3

        assert DeteriorationModel.objects.filter(component=comp_a).count() == 3

    def test_fit_training_data_hash_is_deterministic_across_refits_without_new_data(self, org, inspector):
        comp_a, _ = self._make_dataset(org, inspector, "CTMCFIT4")

        model_v1 = CTMCLatentFittingService().fit(org.id, "bridge", "girder", comp_a)
        model_v2 = CTMCLatentFittingService().fit(org.id, "bridge", "girder", comp_a)

        assert model_v1.training_data_hash == model_v2.training_data_hash

    def test_fit_raises_when_no_inspections_in_cluster(self, org):
        with pytest.raises(ValueError):
            CTMCLatentFittingService().fit(org.id, "bridge", "girder", component=None)


class TestPackParamsInverseOfUnpackParams:
    """_pack_params (INVERSE _unpack_params) dipakai warm-start
    BootstrapResampler (formulas.md §3.1) dari ctmc_model.parameters
    tersimpan. Diverifikasi round-trip: unpack -> pack -> unpack lagi
    harus menghasilkan cs_generators/regime_generator/regime_priors yang
    SETARA (bukan raw_params identik -- regime_priors inverse tidak unik,
    lihat komentar _pack_params)."""

    def test_round_trip_unpack_pack_unpack_recovers_equivalent_params(self):
        raw_params_original = jnp.array(np.random.RandomState(11).normal(size=N_RAW_PARAMS_TOTAL))
        service = CTMCLatentFittingService()

        cs_generators_1, regime_generator_1, regime_priors_1 = service._unpack_params(raw_params_original)

        packed = service._pack_params(cs_generators_1, regime_generator_1, regime_priors_1)
        cs_generators_2, regime_generator_2, regime_priors_2 = service._unpack_params(packed)

        for r in range(N_REGIMES):
            np.testing.assert_allclose(
                np.asarray(cs_generators_2[r]), np.asarray(cs_generators_1[r]), atol=1e-4
            )
        np.testing.assert_allclose(
            np.asarray(regime_generator_2), np.asarray(regime_generator_1), atol=1e-4
        )
        np.testing.assert_allclose(
            np.asarray(regime_priors_2), np.asarray(regime_priors_1), atol=1e-4
        )

    def test_packed_params_have_correct_shape(self):
        raw_params_original = jnp.array(np.random.RandomState(12).normal(size=N_RAW_PARAMS_TOTAL))
        service = CTMCLatentFittingService()

        cs_generators, regime_generator, regime_priors = service._unpack_params(raw_params_original)
        packed = service._pack_params(cs_generators, regime_generator, regime_priors)

        assert packed.shape == (N_RAW_PARAMS_TOTAL,)
