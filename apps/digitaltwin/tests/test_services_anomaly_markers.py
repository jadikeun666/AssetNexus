from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from apps.assets.models import Asset, AssetComponent
from apps.core.models import Organization
from apps.digitaltwin.services_anomaly_markers import AnomalyMarkerService
from apps.sensors.models import AnomalyEvent, SensorDevice


def _make_component(org_name="Anomaly Marker Test"):
    org = Organization.objects.create(name=org_name)
    asset = Asset.objects.create(
        organization=org, code=f"BRG-{org_name}", name="Jembatan Test",
        asset_type=Asset.AssetType.BRIDGE,
        latitude=Decimal("-6.9"), longitude=Decimal("107.6"),
        importance_weight=Decimal("5.00"),
    )
    component = AssetComponent.objects.create(
        asset=asset, component_type="girder", criticality_weight=Decimal("0.250"),
    )
    return org, asset, component


def _make_device(component):
    return SensorDevice.objects.create(
        component=component,
        device_type=SensorDevice.DeviceType.ACCELEROMETER,
        install_date=date(2026, 1, 1),
    )


@pytest.mark.django_db
class TestAnomalyMarkerService:
    def test_returns_unresolved_medium_and_above(self):
        org, asset, component = _make_component()
        device = _make_device(component)
        AnomalyEvent.objects.create(
            device=device, detected_at=datetime(2026, 8, 19, tzinfo=timezone.utc),
            detection_method=AnomalyEvent.DetectionMethod.THRESHOLD,
            severity=AnomalyEvent.Severity.MEDIUM, resolved=False,
        )
        markers = AnomalyMarkerService().get_markers(org.id, asset.id)
        assert len(markers) == 1
        assert markers[0]["severity"] == AnomalyEvent.Severity.MEDIUM
        assert markers[0]["component_type"] == "girder"

    def test_excludes_low_severity(self):
        org, asset, component = _make_component()
        device = _make_device(component)
        AnomalyEvent.objects.create(
            device=device, detected_at=datetime(2026, 8, 19, tzinfo=timezone.utc),
            detection_method=AnomalyEvent.DetectionMethod.THRESHOLD,
            severity=AnomalyEvent.Severity.LOW, resolved=False,
        )
        markers = AnomalyMarkerService().get_markers(org.id, asset.id)
        assert markers == []

    def test_excludes_resolved(self):
        org, asset, component = _make_component()
        device = _make_device(component)
        AnomalyEvent.objects.create(
            device=device, detected_at=datetime(2026, 8, 19, tzinfo=timezone.utc),
            detection_method=AnomalyEvent.DetectionMethod.KALMAN_RESIDUAL,
            severity=AnomalyEvent.Severity.CRITICAL, resolved=True,
        )
        markers = AnomalyMarkerService().get_markers(org.id, asset.id)
        assert markers == []

    def test_org_scoping_excludes_other_org(self):
        org_a, asset_a, component_a = _make_component(org_name="Org A")
        device_a = _make_device(component_a)
        AnomalyEvent.objects.create(
            device=device_a, detected_at=datetime(2026, 8, 19, tzinfo=timezone.utc),
            detection_method=AnomalyEvent.DetectionMethod.THRESHOLD,
            severity=AnomalyEvent.Severity.HIGH, resolved=False,
        )
        org_b, _, _ = _make_component(org_name="Org B")
        markers = AnomalyMarkerService().get_markers(org_b.id, asset_a.id)
        assert markers == []

    def test_multiple_events_same_component_all_included(self):
        org, asset, component = _make_component()
        device = _make_device(component)
        AnomalyEvent.objects.create(
            device=device, detected_at=datetime(2026, 8, 19, 10, tzinfo=timezone.utc),
            detection_method=AnomalyEvent.DetectionMethod.THRESHOLD,
            severity=AnomalyEvent.Severity.HIGH, resolved=False,
        )
        AnomalyEvent.objects.create(
            device=device, detected_at=datetime(2026, 8, 19, 11, tzinfo=timezone.utc),
            detection_method=AnomalyEvent.DetectionMethod.KALMAN_RESIDUAL,
            severity=AnomalyEvent.Severity.CRITICAL, resolved=False,
        )
        markers = AnomalyMarkerService().get_markers(org.id, asset.id)
        assert len(markers) == 2
