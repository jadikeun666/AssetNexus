from datetime import datetime, timedelta, timezone
from decimal import Decimal

import numpy as np
import pytest

from apps.assets.models import Asset, AssetComponent
from apps.core.models import Organization, User
from apps.deterioration.models import DeteriorationModel, TransitionMatrix
from apps.deterioration.services import (
    DiscreteMarkovFittingService,
    ForecastService,
    normalize_interval,
    reproject_to_stochastic,
)
from apps.inspections.models import InspectionRecord


@pytest.fixture
def org():
    return Organization.objects.create(name="Dinas PU Test")


@pytest.fixture
def inspector(org):
    return User.objects.create(
        keycloak_sub="sub-fit-1", organization=org, username="sari",
        email="sari@example.id", role=User.Role.INSPECTOR,
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


@pytest.mark.django_db
class TestPooledMLEFitting:
    """
    Nilai expected dihitung manual — lihat perhitungan di deskripsi PR/commit.
    Component A: CS1 -> CS1 -> CS2 (interval 1 tahun tiap langkah)
    Component B: CS2 -> CS3 (interval 1 tahun)
    """

    def test_pooled_mle_matches_hand_computed_matrix(self, org, inspector):
        asset_a = _make_bridge(org, "BRG-A")
        asset_b = _make_bridge(org, "BRG-B")
        comp_a = _make_girder(asset_a)
        comp_b = _make_girder(asset_b)

        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS1, t0)
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS1, t0 + timedelta(days=365))
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS2, t0 + timedelta(days=730))

        _inspect(comp_b, inspector, InspectionRecord.ConditionState.CS2, t0)
        _inspect(comp_b, inspector, InspectionRecord.ConditionState.CS3, t0 + timedelta(days=365))

        service = DiscreteMarkovFittingService()
        model = service.fit(
            organization_id=org.id, asset_type="bridge", component_type="girder", component=comp_a,
        )

        p_annual = np.array(model.parameters["p_annual"])

        # Baris CS1: hand-computed 0.5 / 0.5
        assert p_annual[0, 0] == pytest.approx(0.5, abs=1e-6)
        assert p_annual[0, 1] == pytest.approx(0.5, abs=1e-6)
        # Baris CS2: hand-computed 1.0 ke CS3
        assert p_annual[1, 2] == pytest.approx(1.0, abs=1e-6)
        # Baris CS3, CS4 tanpa data -> fallback identitas
        assert p_annual[2, 2] == pytest.approx(1.0, abs=1e-6)
        assert p_annual[3, 3] == pytest.approx(1.0, abs=1e-6)
        # CS5 absorbing dipaksa terlepas dari data
        assert p_annual[4, 4] == pytest.approx(1.0, abs=1e-6)

    def test_model_version_increments_on_refit(self, org, inspector):
        asset_a = _make_bridge(org, "BRG-C")
        comp_a = _make_girder(asset_a)
        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS1, t0)
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS2, t0 + timedelta(days=365))

        service = DiscreteMarkovFittingService()
        model_v1 = service.fit(org.id, "bridge", "girder", comp_a)
        assert model_v1.model_version == 1

        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS3, t0 + timedelta(days=730))
        model_v2 = service.fit(org.id, "bridge", "girder", comp_a)
        assert model_v2.model_version == 2
        assert DeteriorationModel.objects.filter(component=comp_a).count() == 2  # v1 tetap ada

    def test_transition_matrix_only_stores_monotone_cells(self, org, inspector):
        # formulas.md §1.1: hanya j >= i yang valid, tidak ada row di DB untuk j < i
        asset_a = _make_bridge(org, "BRG-D")
        comp_a = _make_girder(asset_a)
        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS1, t0)
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS2, t0 + timedelta(days=365))

        model = DiscreteMarkovFittingService().fit(org.id, "bridge", "girder", comp_a)
        rows = TransitionMatrix.objects.filter(model=model)
        for row in rows:
            from_idx = ["CS1", "CS2", "CS3", "CS4", "CS5"].index(row.from_state)
            to_idx = ["CS1", "CS2", "CS3", "CS4", "CS5"].index(row.to_state)
            assert to_idx >= from_idx

    def test_training_data_hash_is_deterministic(self, org, inspector):
        # engineering-rules.md §3: fit ulang data identik -> hash identik
        asset_a = _make_bridge(org, "BRG-E")
        comp_a = _make_girder(asset_a)
        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS1, t0)
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS2, t0 + timedelta(days=365))

        service = DiscreteMarkovFittingService()
        model_v1 = service.fit(org.id, "bridge", "girder", comp_a)
        # Refit tanpa data baru -> hash training data harus identik
        model_v2 = service.fit(org.id, "bridge", "girder", comp_a)
        assert model_v1.training_data_hash == model_v2.training_data_hash

    def test_fit_raises_when_no_transition_pairs_observed(self, org, inspector):
        asset_a = _make_bridge(org, "BRG-F")
        comp_a = _make_girder(asset_a)
        # Hanya 1 inspeksi -> tidak ada pasangan transisi
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS1, datetime.now(timezone.utc))

        with pytest.raises(ValueError):
            DiscreteMarkovFittingService().fit(org.id, "bridge", "girder", comp_a)


@pytest.mark.django_db
class TestForecastGeneration:
    """
    formulas.md §1.5: π(t) = π(0) · P_annual^t.
    Hand-computed: dengan P sederhana P[CS1][CS1]=0.5, P[CS1][CS2]=0.5,
    mulai dari pi(0)=[1,0,0,0,0] (CS1):
      pi(1) = [0.5, 0.5, 0, 0, 0]
      pi(2) = pi(1) @ P = [0.25, 0.5+0.25=0.75?, ...] -- dihitung via numpy
      di test, bukan aljabar tangan penuh, karena P baris CS2 juga
      berkontribusi begitu probabilitas CS1 mengalir ke CS2.
    """

    def test_forecast_probabilities_sum_to_one_each_year(self, org, inspector):
        asset_a = _make_bridge(org, "BRG-G")
        comp_a = _make_girder(asset_a)
        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS1, t0)
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS2, t0 + timedelta(days=365))

        model = DiscreteMarkovFittingService().fit(org.id, "bridge", "girder", comp_a)
        forecasts = ForecastService().generate(model, current_state="CS1", horizon_years=5)

        assert len(forecasts) == 5
        for f in forecasts:
            total = sum(f.state_probabilities.values())
            assert total == pytest.approx(1.0, abs=1e-3)

    def test_forecast_year_1_matches_hand_computed_pi(self, org, inspector):
        asset_a = _make_bridge(org, "BRG-H")
        comp_a = _make_girder(asset_a)
        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS1, t0)
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS2, t0 + timedelta(days=365))

        model = DiscreteMarkovFittingService().fit(org.id, "bridge", "girder", comp_a)
        # Hanya 1 transisi teramati (CS1->CS2), jadi MLE baris CS1 = 100% ke
        # CS2, BUKAN 50/50 (itu skenario test lain dengan 2 komponen pooled).
        # pi(0) = [1,0,0,0,0] (CS1), pi(1) = pi(0) @ P = row CS1 of P = [0, 1.0, 0, 0, 0]
        forecasts = ForecastService().generate(model, current_state="CS1", horizon_years=1)
        assert forecasts[0].state_probabilities["CS1"] == pytest.approx(0.0, abs=1e-3)
        assert forecasts[0].state_probabilities["CS2"] == pytest.approx(1.0, abs=1e-3)
        assert forecasts[0].expected_state == "CS2"


class TestIntervalNormalizationAndReprojection:
    """Unit test murni numerik, tidak butuh database."""

    def test_identity_matrix_normalizes_to_itself(self):
        P = np.eye(5)
        result = normalize_interval(P, delta_t=2.0)
        np.testing.assert_allclose(result, P, atol=1e-6)

    def test_reproject_clips_negative_and_row_normalizes(self):
        P = np.array([[0.6, -0.1, 0.5], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
        result = reproject_to_stochastic(P)
        assert (result >= 0).all()
        row_sums = result.sum(axis=1)
        np.testing.assert_allclose(row_sums, np.ones(3), atol=1e-6)

    def test_delta_t_one_returns_matrix_unchanged(self):
        P = np.array([[0.7, 0.3], [0.0, 1.0]])
        result = normalize_interval(P, delta_t=1.0)
        np.testing.assert_allclose(result, P, atol=1e-9)

    def test_delta_t_within_tolerance_of_one_also_skips_eig(self):
        # 365/365.25 ≈ 0.9993 -- harus tetap dianggap "annual", menghindari
        # eigendecomposition yang numerically unstable untuk matriks
        # defective/near-defective.
        P = np.array([[0.7, 0.3], [0.0, 1.0]])
        result = normalize_interval(P, delta_t=365 / 365.25)
        np.testing.assert_allclose(result, P, atol=1e-9)
