"""
visualization.md §5 -- ComponentForecastChartService (services_chart.py).

Test end-to-end lewat recalculate_deterioration_job.fn() sungguhan (bukan
mock fitting), konsisten engineering-rules.md §7 ("No mocking of JAX
numerics") -- pola factory sama dengan test_jobs.py.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from django.http import Http404

from apps.assets.models import Asset, AssetComponent
from apps.core.models import Organization, User
from apps.deterioration.jobs import recalculate_deterioration_job
from apps.deterioration.models import DeteriorationModel
from apps.deterioration.services_chart import ComponentForecastChartService
from apps.inspections.models import InspectionRecord
from config.assetnexus import DETERIORATION


@pytest.fixture
def org():
    return Organization.objects.create(name="Dinas PU Test Chart")


@pytest.fixture
def other_org():
    return Organization.objects.create(name="Dinas PU Lain Test Chart")


@pytest.fixture
def inspector(org):
    return User.objects.create(
        keycloak_sub="sub-chart-1", organization=org, username="sari",
        email="sari-chart@example.id", role=User.Role.INSPECTOR,
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
    config/assetnexus.py produksi (pola sama dengan test_jobs.py)."""
    monkeypatch.setitem(DETERIORATION, "BOOTSTRAP_RESAMPLES", 5)


@pytest.mark.django_db
class TestComponentForecastChartService:
    def test_dtmc_component_has_no_confidence_band(self, org, inspector):
        # 2 inspeksi -- di bawah MIN_INSPECTIONS_FOR_CTMC=4, jalur DTMC.
        asset = _make_bridge(org, "CHART-A")
        component = _make_girder(asset)
        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        _inspect(component, inspector, InspectionRecord.ConditionState.CS1, t0)
        _inspect(component, inspector, InspectionRecord.ConditionState.CS2, t0 + timedelta(days=365))

        recalculate_deterioration_job.fn(str(component.id))

        result = ComponentForecastChartService().get_chart_data(org.id, component.id)

        assert result["component_id"] == component.id
        assert result["model_type"] == DeteriorationModel.ModelType.DISCRETE_MARKOV
        assert len(result["points"]) > 0
        for point in result["points"]:
            assert point["confidence_lower"] is None
            assert point["confidence_upper"] is None
            assert 0.0 <= point["condition_score"] <= 100.0

    def test_ctmc_fuzzy_component_has_symmetric_band(self, org, inspector, small_bootstrap):
        # >=4 inspeksi -- jalur CTMC+Fuzzy. comp_a berhenti di CS2 -- forecast-nya
        # dimulai dari current_state=CS2, jadi rate keberangkatan dari CS2
        # (CS2->CS3) yang menentukan lintasan forecast, BUKAN CS1->CS2. Perlu
        # beberapa komponen tambahan dengan transisi CS2->CS3 bervariasi durasi
        # supaya pooled fit + bootstrap punya sinyal cukup untuk estimasi rate
        # itu dengan spread non-degenerate (band nol-total di semua titik
        # ditemukan di awal draf test ini -- root cause: dataset pooled asli
        # nyaris tidak ada transisi CS2->CS3, root cause diverifikasi lewat
        # shell manual, BUKAN bug di services_chart.py/services_fuzzy.py).
        asset_a = _make_bridge(org, "CHART-B")
        comp_a = _make_girder(asset_a)
        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS1, t0)
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS1, t0 + timedelta(days=365))
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS2, t0 + timedelta(days=730))
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS2, t0 + timedelta(days=1095))

        for suffix, days in [("C", 400), ("D", 500), ("E", 600), ("F", 700), ("G", 800)]:
            helper_asset = _make_bridge(org, f"CHART-{suffix}")
            helper_comp = _make_girder(helper_asset)
            _inspect(helper_comp, inspector, InspectionRecord.ConditionState.CS2, t0)
            _inspect(helper_comp, inspector, InspectionRecord.ConditionState.CS3, t0 + timedelta(days=days))

        recalculate_deterioration_job.fn(str(comp_a.id))

        result = ComponentForecastChartService().get_chart_data(org.id, comp_a.id)

        assert result["model_type"] == DeteriorationModel.ModelType.CTMC_LATENT
        assert len(result["points"]) > 0
        for point in result["points"]:
            assert point["confidence_lower"] is not None
            assert point["confidence_upper"] is not None
            # Band harus simetris di sekitar condition_score (keputusan
            # disepakati eksplisit -- lihat services_chart.py docstring).
            lower_gap = point["condition_score"] - point["confidence_lower"]
            upper_gap = point["confidence_upper"] - point["condition_score"]
            assert lower_gap == pytest.approx(upper_gap, abs=1e-6)
            # <=, bukan < ketat -- forecast_year == tahun sekarang (t=0)
            # punya confidence_width=0 secara matematis valid: expm(Q*0)=I,
            # jadi pi_upper_t == pi_lower_t == pi_0, band nol-lebar untuk
            # kondisi SAAT INI (belum ada waktu berlalu untuk uncertainty
            # berkembang). Band positif diharapkan di tahun-tahun berikutnya.
            assert point["confidence_lower"] <= point["confidence_upper"]

        # Pastikan band tidak nol di SEMUA titik -- kalau iya, itu tanda
        # bug (misal confidence_width tidak benar-benar ke-propagate),
        # bukan sekadar t=0 edge case yang tadinya bikin test gagal.
        assert any(
            point["confidence_upper"] - point["confidence_lower"] > 1e-6
            for point in result["points"]
        )

    def test_no_deterioration_model_returns_empty_chart(self, org):
        # Komponen ada tapi belum pernah difit -- tidak error, chart kosong.
        asset = _make_bridge(org, "CHART-D")
        component = _make_girder(asset)

        result = ComponentForecastChartService().get_chart_data(org.id, component.id)

        assert result["component_id"] == component.id
        assert result["model_type"] == ""
        assert result["model_version"] == 0
        assert result["points"] == []

    def test_cross_organization_access_raises_404(self, org, other_org, inspector):
        # engineering-rules.md §8 -- komponen org lain tidak boleh terlihat.
        asset = _make_bridge(org, "CHART-E")
        component = _make_girder(asset)
        _inspect(component, inspector, InspectionRecord.ConditionState.CS1, datetime.now(timezone.utc))

        with pytest.raises(Http404):
            ComponentForecastChartService().get_chart_data(other_org.id, component.id)
