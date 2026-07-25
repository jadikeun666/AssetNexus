"""
architecture.md §4 — recalculate_deterioration_job. Memverifikasi routing
penuh: DTMC untuk di bawah MIN_INSPECTIONS_FOR_CTMC, CTMC+Fuzzy untuk di
atas/sama dengan ambang (TODO Fase 0 yang diisi Fase 1). Dramatiq actor
dipanggil via .fn(...) -- pola standar untuk memanggil fungsi asli secara
sinkron tanpa broker Redis sungguhan.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from apps.assets.models import Asset, AssetComponent
from apps.core.models import Organization, User
from apps.deterioration.jobs import recalculate_deterioration_job
from apps.deterioration.models import DeteriorationModel, DegradationForecast
from apps.inspections.models import InspectionRecord
from config.assetnexus import DETERIORATION


@pytest.fixture
def org():
    return Organization.objects.create(name="Dinas PU Test Jobs")


@pytest.fixture
def inspector(org):
    return User.objects.create(
        keycloak_sub="sub-jobs-1", organization=org, username="sari",
        email="sari-jobs@example.id", role=User.Role.INSPECTOR,
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
    config/assetnexus.py produksi."""
    monkeypatch.setitem(DETERIORATION, "BOOTSTRAP_RESAMPLES", 5)


@pytest.mark.django_db
class TestRecalculateDeteriorationJobRouting:
    def test_job_uses_dtmc_when_below_ctmc_threshold(self, org, inspector):
        # MIN_INSPECTIONS_FOR_CTMC=4 -- 2 inspeksi berarti di BAWAH ambang.
        asset = _make_bridge(org, "JOB-A")
        component = _make_girder(asset)
        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        _inspect(component, inspector, InspectionRecord.ConditionState.CS1, t0)
        _inspect(component, inspector, InspectionRecord.ConditionState.CS2, t0 + timedelta(days=365))

        recalculate_deterioration_job.fn(str(component.id))

        models = DeteriorationModel.objects.filter(component=component)
        assert models.count() == 1
        assert models.first().model_type == DeteriorationModel.ModelType.DISCRETE_MARKOV

        forecasts = DegradationForecast.objects.filter(model=models.first())
        assert forecasts.exists()
        assert all(f.confidence_width is None for f in forecasts)  # DTMC tidak isi confidence_width

    def test_job_uses_ctmc_and_fuzzy_when_at_ctmc_threshold(self, org, inspector, small_bootstrap):
        # Tepat di MIN_INSPECTIONS_FOR_CTMC=4 -- harus masuk jalur CTMC+Fuzzy.
        asset_a = _make_bridge(org, "JOB-B")
        asset_b = _make_bridge(org, "JOB-C")
        comp_a = _make_girder(asset_a)
        comp_b = _make_girder(asset_b)  # data pooled tambahan, cluster sama

        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS1, t0)
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS1, t0 + timedelta(days=365))
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS2, t0 + timedelta(days=730))
        _inspect(comp_a, inspector, InspectionRecord.ConditionState.CS2, t0 + timedelta(days=1095))
        _inspect(comp_b, inspector, InspectionRecord.ConditionState.CS2, t0)
        _inspect(comp_b, inspector, InspectionRecord.ConditionState.CS3, t0 + timedelta(days=365))

        recalculate_deterioration_job.fn(str(comp_a.id))

        models = DeteriorationModel.objects.filter(component=comp_a).order_by("model_version")
        model_types = [m.model_type for m in models]
        assert DeteriorationModel.ModelType.CTMC_LATENT in model_types
        assert DeteriorationModel.ModelType.FUZZY_MARKOV in model_types
        assert DeteriorationModel.ModelType.DISCRETE_MARKOV not in model_types

        fuzzy_model = models.get(model_type=DeteriorationModel.ModelType.FUZZY_MARKOV)
        ctmc_model = models.get(model_type=DeteriorationModel.ModelType.CTMC_LATENT)

        forecasts = DegradationForecast.objects.filter(model=ctmc_model)
        assert forecasts.exists()
        assert all(f.confidence_width is not None for f in forecasts)  # CTMC+Fuzzy isi confidence_width

    def test_job_returns_early_when_no_condition_state_inspections(self, org, inspector):
        # Hanya inspeksi method=sensor (condition_state NULL) -- job harus
        # kembali tanpa membuat model apa pun, bukan error.
        asset = _make_bridge(org, "JOB-D")
        component = _make_girder(asset)
        InspectionRecord.objects.create(
            component=component, inspector=inspector, inspected_at=datetime.now(timezone.utc),
            method=InspectionRecord.Method.SENSOR, condition_state=None,
        )

        recalculate_deterioration_job.fn(str(component.id))

        assert DeteriorationModel.objects.filter(component=component).count() == 0
