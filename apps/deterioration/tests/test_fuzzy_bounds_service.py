"""
formulas.md §3 — FuzzyBoundsService end-to-end. engineering-rules.md §7:
properti struktural diverifikasi (bootstrap+fit gradient non-convex, tidak
ada rumus tertutup untuk nilai akhir). BOOTSTRAP_RESAMPLES di-monkeypatch
ke angka kecil (5) untuk kecepatan test -- config/assetnexus.py produksi
(500) TIDAK disentuh.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from apps.assets.models import Asset, AssetComponent
from apps.core.models import Organization, User
from apps.deterioration.models import DeteriorationModel, TransitionMatrix
from apps.deterioration.services_ctmc import (
    CTMCDatasetCollector,
    CTMCForecastService,
    CTMCLatentFittingService,
)
from apps.deterioration.services_fuzzy import FuzzyBoundsService
from apps.inspections.models import InspectionRecord
from config.assetnexus import DETERIORATION


@pytest.fixture
def org():
    return Organization.objects.create(name="Dinas PU Test Fuzzy Bounds")


@pytest.fixture
def inspector(org):
    return User.objects.create(
        keycloak_sub="sub-fuzzy-1", organization=org, username="sari",
        email="sari-fuzzy@example.id", role=User.Role.INSPECTOR,
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


@pytest.fixture
def small_bootstrap(monkeypatch):
    """Kecilkan BOOTSTRAP_RESAMPLES untuk kecepatan test -- TIDAK mengubah
    config/assetnexus.py produksi (500 tetap dipakai job sungguhan)."""
    monkeypatch.setitem(DETERIORATION, "BOOTSTRAP_RESAMPLES", 5)


@pytest.mark.django_db
class TestFuzzyBoundsServiceEndToEnd:
    def _make_dataset_and_ctmc_model(self, org, inspector, code_prefix):
        asset_a = _make_bridge(org, f"{code_prefix}-A")
        asset_b = _make_bridge(org, f"{code_prefix}-B")
        comp_a = _make_girder(asset_a)
        comp_b = _make_girder(asset_b)

        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS1, t0)
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS1, t0 + timedelta(days=365))
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS2, t0 + timedelta(days=730))
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS2, t0 + timedelta(days=1095))
        _inspect(comp_b, inspector, InspectionRecord.ConditionState.CS2, t0)
        _inspect(comp_b, inspector, InspectionRecord.ConditionState.CS3, t0 + timedelta(days=365))

        ctmc_model = CTMCLatentFittingService().fit(
            organization_id=org.id, asset_type="bridge", component_type="girder", component=comp_a,
        )
        histories = CTMCDatasetCollector().collect(org.id, "bridge", "girder")
        return comp_a, ctmc_model, histories

    def test_fit_creates_fuzzy_markov_model_with_valid_structure(self, org, inspector, small_bootstrap):
        comp_a, ctmc_model, histories = self._make_dataset_and_ctmc_model(org, inspector, "FUZZYFIT1")

        fuzzy_model = FuzzyBoundsService().fit(ctmc_model, histories)

        assert fuzzy_model.model_type == DeteriorationModel.ModelType.FUZZY_MARKOV
        assert fuzzy_model.parameters["source_model_id"] == str(ctmc_model.id)
        assert fuzzy_model.parameters["n_resamples"] == 5
        assert fuzzy_model.training_data_hash == ctmc_model.training_data_hash

    def test_fit_version_is_global_per_component_across_all_model_types(self, org, inspector, small_bootstrap):
        # Regression test versioning: DTMC + CTMC + FUZZY untuk component
        # yang sama harus punya model_version berurutan TANPA bentrok.
        # _make_dataset_and_ctmc_model TIDAK membuat DTMC dulu, jadi
        # ctmc_model (dibuat pertama) harus model_version=1. DTMC ekstra
        # di bawah dibuat SETELAH ctmc_model -- jadi versi DTMC baru=2.
        # fuzzy_model dibuat terakhir -- versi=3.
        from apps.deterioration.services import DiscreteMarkovFittingService

        comp_a, ctmc_model, histories = self._make_dataset_and_ctmc_model(org, inspector, "FUZZYFIT2")
        assert ctmc_model.model_version == 1

        dtmc_model = DiscreteMarkovFittingService().fit(org.id, "bridge", "girder", comp_a)
        assert dtmc_model.model_version == 2

        fuzzy_model = FuzzyBoundsService().fit(ctmc_model, histories)
        assert fuzzy_model.model_version == 3
        assert DeteriorationModel.objects.filter(component=comp_a).count() == 3

    def test_fit_transition_matrix_has_valid_fuzzy_bounds_sanity(self, org, inspector, small_bootstrap):
        # formulas.md §6: p_ij^L <= p_ij <= p_ij^U HARUS berlaku untuk
        # SEMUA cell -- kalau fit() tidak raise, berarti sanity check lolos
        # untuk semua 10 cell (diverifikasi ULANG di sini secara eksplisit).
        comp_a, ctmc_model, histories = self._make_dataset_and_ctmc_model(org, inspector, "FUZZYFIT3")

        fuzzy_model = FuzzyBoundsService().fit(ctmc_model, histories)
        rows = TransitionMatrix.objects.filter(model=fuzzy_model)

        assert rows.count() == 10  # OFF_DIAGONAL_CELLS: 4+3+2+1+0
        for row in rows:
            assert row.fuzzy_lower is not None
            assert row.fuzzy_upper is not None
            assert float(row.fuzzy_lower) <= float(row.rate_or_probability) <= float(row.fuzzy_upper)

    def test_fit_raises_when_component_not_in_histories(self, org, inspector, small_bootstrap):
        comp_a, ctmc_model, histories = self._make_dataset_and_ctmc_model(org, inspector, "FUZZYFIT4")

        with pytest.raises(ValueError):
            FuzzyBoundsService().fit(ctmc_model, histories=[])

    def test_annotate_forecast_confidence_width_fills_in_previously_null_field(
        self, org, inspector, small_bootstrap
    ):
        comp_a, ctmc_model, histories = self._make_dataset_and_ctmc_model(org, inspector, "FUZZYFIT5")
        fuzzy_model = FuzzyBoundsService().fit(ctmc_model, histories)

        forecasts = CTMCForecastService().generate(ctmc_model, current_state="CS1", horizon_years=3)
        assert all(f.confidence_width is None for f in forecasts)  # sebelum diisi

        annotated = FuzzyBoundsService().annotate_forecast_confidence_width(
            forecasts[0], fuzzy_model, current_state="CS1",
        )

        assert annotated.confidence_width is not None
        assert float(annotated.confidence_width) >= 0.0

        # Verifikasi tersimpan di DB (update_fields=["confidence_width"])
        from apps.deterioration.models import DegradationForecast
        refetched = DegradationForecast.objects.get(id=forecasts[0].id)
        # confidence_width tersimpan sebagai DecimalField (database.md §4),
        # sementara annotated.confidence_width di memori masih float --
        # bandingkan sebagai float di kedua sisi, bukan == lintas tipe.
        assert float(refetched.confidence_width) == pytest.approx(float(annotated.confidence_width))

    def test_annotate_forecast_confidence_width_is_nonnegative_across_horizon(
        self, org, inspector, small_bootstrap
    ):
        # REVISI (diagnostik konkret menunjukkan asumsi awal keliru):
        # confidence_width TIDAK selalu membesar seiring horizon untuk CTMC
        # dengan absorbing/high-rate transitions -- begitu titik estimasi
        # sendiri terkonsentrasi ~100% di satu state (mis. rate CS1->CS2
        # cukup cepat relatif horizon), Q_bar_upper dan Q_bar_lower SAMA-SAMA
        # konvergen ke distribusi serupa pada horizon panjang, membuat
        # confidence_width -> 0 secara matematis SAH (bukan bug) -- properti
        # ini diverifikasi konkret via skrip diagnostik sebelum test ini
        # ditulis ulang. Yang tetap harus benar universal: confidence_width
        # selalu >= 0 di SETIAP titik horizon, apa pun bentuk distribusinya.
        comp_a, ctmc_model, histories = self._make_dataset_and_ctmc_model(org, inspector, "FUZZYFIT6")
        fuzzy_model = FuzzyBoundsService().fit(ctmc_model, histories)

        forecasts = CTMCForecastService().generate(ctmc_model, current_state="CS1", horizon_years=10)

        service = FuzzyBoundsService()
        for forecast in forecasts:
            service.annotate_forecast_confidence_width(forecast, fuzzy_model, current_state="CS1")
            assert float(forecast.confidence_width) >= 0.0
