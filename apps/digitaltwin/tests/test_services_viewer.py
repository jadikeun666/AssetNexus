"""
visualization.md §4.1: payload viewer {component_id: {year: condition_score}}.

Pakai jalur DTMC (2 inspeksi, di bawah MIN_INSPECTIONS_FOR_CTMC) untuk
kecepatan test -- fitting CTMC/fuzzy sudah teruji penuh di
apps/deterioration/tests/, di sini fokus menguji reshape payload dan
integrasi DigitalTwinModel, bukan menguji ulang fitting.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from django.http import Http404

from apps.assets.models import Asset, AssetComponent
from apps.core.models import Organization, User
from apps.deterioration.jobs import recalculate_deterioration_job
from apps.digitaltwin.models import DigitalTwinModel
from apps.digitaltwin.services_viewer import DigitalTwinViewerPayloadService
from apps.digitaltwin.tests.test_services_validation import _build_single_triangle_glb
from apps.inspections.models import InspectionRecord


@pytest.fixture
def org():
    return Organization.objects.create(name="Dinas PU Test Viewer")


@pytest.fixture
def other_org():
    return Organization.objects.create(name="Dinas PU Lain Test Viewer")


@pytest.fixture
def inspector(org):
    return User.objects.create(
        keycloak_sub="sub-viewer-1", organization=org, username="sari",
        email="sari-viewer@example.id", role=User.Role.INSPECTOR,
    )


@pytest.fixture
def asset(org):
    return Asset.objects.create(
        organization=org, code="BRG-VIEW-1", name="Jembatan Viewer Test",
        asset_type=Asset.AssetType.BRIDGE, latitude=Decimal("0"), longitude=Decimal("0"),
        importance_weight=Decimal("5.00"),
    )


@pytest.fixture
def component(asset):
    return AssetComponent.objects.create(
        asset=asset, component_type="girder", criticality_weight=Decimal("0.250"),
    )


@pytest.mark.django_db
class TestDigitalTwinViewerPayloadService:
    def test_payload_includes_forecast_and_digital_twin_model(self, org, asset, component, inspector):
        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        InspectionRecord.objects.create(
            component=component, inspector=inspector, inspected_at=t0,
            method=InspectionRecord.Method.VISUAL,
            condition_state=InspectionRecord.ConditionState.CS1,
        )
        InspectionRecord.objects.create(
            component=component, inspector=inspector,
            inspected_at=t0 + timedelta(days=365),
            method=InspectionRecord.Method.VISUAL,
            condition_state=InspectionRecord.ConditionState.CS2,
        )
        recalculate_deterioration_job.fn(str(component.id))

        DigitalTwinModel.objects.create(
            asset=asset, model_format=DigitalTwinModel.ModelFormat.GLTF,
            source=DigitalTwinModel.Source.MANUAL,
            file_ref="digitaltwin/fake/v1.glb", version=1,
        )

        payload = DigitalTwinViewerPayloadService().get_viewer_payload(org.id, asset.id)

        assert payload["asset_id"] == asset.id
        assert payload["digital_twin_model"]["version"] == 1
        assert str(component.id) in payload["forecast_by_component"]
        year_scores = payload["forecast_by_component"][str(component.id)]
        assert len(year_scores) > 0
        for score in year_scores.values():
            assert 0.0 <= score <= 100.0

    def test_payload_picks_highest_version_digital_twin_model(self, org, asset):
        DigitalTwinModel.objects.create(
            asset=asset, model_format=DigitalTwinModel.ModelFormat.GLTF,
            source=DigitalTwinModel.Source.MANUAL, file_ref="digitaltwin/fake/v1.glb", version=1,
        )
        DigitalTwinModel.objects.create(
            asset=asset, model_format=DigitalTwinModel.ModelFormat.GLTF,
            source=DigitalTwinModel.Source.MANUAL, file_ref="digitaltwin/fake/v2.glb", version=2,
        )

        payload = DigitalTwinViewerPayloadService().get_viewer_payload(org.id, asset.id)

        assert payload["digital_twin_model"]["version"] == 2

    def test_payload_none_when_no_digital_twin_model_uploaded_yet(self, org, asset):
        payload = DigitalTwinViewerPayloadService().get_viewer_payload(org.id, asset.id)

        assert payload["digital_twin_model"] is None
        assert payload["forecast_by_component"] == {}

    def test_raises_404_for_asset_in_other_organization(self, org, other_org, asset):
        with pytest.raises(Http404):
            DigitalTwinViewerPayloadService().get_viewer_payload(other_org.id, asset.id)
