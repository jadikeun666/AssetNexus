from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from apps.assets.models import Asset, AssetComponent
from apps.core.models import Organization
from apps.sensors.models import AnomalyEvent, SensorDevice


def _make_component(org_name="Dinas PU Test"):
    org = Organization.objects.create(name=org_name)
    asset = Asset.objects.create(
        organization=org, code=f"BRG-{org_name}", name="Jembatan Test",
        asset_type=Asset.AssetType.BRIDGE,
        latitude=Decimal("-6.914744"), longitude=Decimal("107.609810"),
        importance_weight=Decimal("8.50"),
    )
    component = AssetComponent.objects.create(
        asset=asset, component_type="girder", criticality_weight=Decimal("0.250"),
    )
    return org, component


@pytest.mark.django_db
class TestSensorDevice:
    def test_device_gets_db_generated_uuid(self):
        _, component = _make_component()
        device = SensorDevice.objects.create(
            component=component,
            device_type=SensorDevice.DeviceType.ACCELEROMETER,
            install_date=date(2026, 1, 1),
        )
        assert device.id is not None
        assert device.status == SensorDevice.Status.ACTIVE  # default

    def test_organization_scoped_manager_follows_fk_chain(self):
        org_a, component_a = _make_component(org_name="Org A")
        _, component_b = _make_component(org_name="Org B")
        SensorDevice.objects.create(
            component=component_a, device_type=SensorDevice.DeviceType.STRAIN_GAUGE,
            install_date=date(2026, 1, 1),
        )
        SensorDevice.objects.create(
            component=component_b, device_type=SensorDevice.DeviceType.STRAIN_GAUGE,
            install_date=date(2026, 1, 1),
        )
        assert SensorDevice.objects.for_organization(org_a.id).count() == 1
        assert (
            SensorDevice.objects.for_organization(org_a.id).first().component_id
            == component_a.id
        )


@pytest.mark.django_db
class TestAnomalyEvent:
    def test_anomaly_event_creation(self):
        _, component = _make_component()
        device = SensorDevice.objects.create(
            component=component, device_type=SensorDevice.DeviceType.TILTMETER,
            install_date=date(2026, 1, 1),
        )
        event = AnomalyEvent.objects.create(
            device=device,
            detected_at=datetime(2026, 8, 16, 6, 0, tzinfo=timezone.utc),
            detection_method=AnomalyEvent.DetectionMethod.THRESHOLD,
            severity=AnomalyEvent.Severity.HIGH,
        )
        assert event.id is not None
        assert event.resolved is False  # default, engineering-rules.md §2: alerting only

    def test_organization_scoped_manager_follows_two_hop_fk_chain(self):
        org_a, component_a = _make_component(org_name="Org A")
        _, component_b = _make_component(org_name="Org B")
        device_a = SensorDevice.objects.create(
            component=component_a, device_type=SensorDevice.DeviceType.THERMOMETER,
            install_date=date(2026, 1, 1),
        )
        device_b = SensorDevice.objects.create(
            component=component_b, device_type=SensorDevice.DeviceType.THERMOMETER,
            install_date=date(2026, 1, 1),
        )
        AnomalyEvent.objects.create(
            device=device_a, detected_at=datetime(2026, 8, 16, 6, 0, tzinfo=timezone.utc),
            detection_method=AnomalyEvent.DetectionMethod.KALMAN_RESIDUAL,
            severity=AnomalyEvent.Severity.MEDIUM,
        )
        AnomalyEvent.objects.create(
            device=device_b, detected_at=datetime(2026, 8, 16, 6, 0, tzinfo=timezone.utc),
            detection_method=AnomalyEvent.DetectionMethod.KALMAN_RESIDUAL,
            severity=AnomalyEvent.Severity.MEDIUM,
        )
        assert AnomalyEvent.objects.for_organization(org_a.id).count() == 1

    def test_unresolved_filter_uses_partial_index_condition(self):
        # database.md §7: partial index WHERE resolved=false — pastikan
        # filter ORM biasa tetap mengembalikan hasil benar (index hanya
        # optimisasi, bukan constraint, jadi ini test korektnes query,
        # bukan test keberadaan index itu sendiri).
        _, component = _make_component()
        device = SensorDevice.objects.create(
            component=component, device_type=SensorDevice.DeviceType.ACCELEROMETER,
            install_date=date(2026, 1, 1),
        )
        AnomalyEvent.objects.create(
            device=device, detected_at=datetime(2026, 8, 16, 6, 0, tzinfo=timezone.utc),
            detection_method=AnomalyEvent.DetectionMethod.THRESHOLD,
            severity=AnomalyEvent.Severity.LOW, resolved=True,
        )
        AnomalyEvent.objects.create(
            device=device, detected_at=datetime(2026, 8, 16, 7, 0, tzinfo=timezone.utc),
            detection_method=AnomalyEvent.DetectionMethod.THRESHOLD,
            severity=AnomalyEvent.Severity.CRITICAL, resolved=False,
        )
        unresolved = AnomalyEvent.objects.filter(resolved=False)
        assert unresolved.count() == 1
        assert unresolved.first().severity == AnomalyEvent.Severity.CRITICAL