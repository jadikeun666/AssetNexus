import uuid
from datetime import datetime, timezone

import pytest
from django.conf import settings

from apps.sensors.models import AnomalyEvent, SensorDevice
from apps.sensors.services_anomaly_detection import ThresholdAnomalyDetectionService
from apps.sensors.services_ingestion import SensorReadingIngestService
from config.assetnexus import SENSORS


def _make_device(component):
    return SensorDevice.objects.create(
        component=component,
        device_type=SensorDevice.DeviceType.ACCELEROMETER,
        install_date=datetime(2026, 1, 1).date(),
    )


def _make_component(org_name="Anomaly Test"):
    from decimal import Decimal
    from apps.assets.models import Asset, AssetComponent
    from apps.core.models import Organization

    org = Organization.objects.create(name=org_name)
    asset = Asset.objects.create(
        organization=org, code=f"BRG-{org_name}", name="Jembatan Test",
        asset_type=Asset.AssetType.BRIDGE,
        latitude=Decimal("-6.9"), longitude=Decimal("107.6"),
        importance_weight=Decimal("5.00"),
    )
    return AssetComponent.objects.create(
        asset=asset, component_type="girder", criticality_weight=Decimal("0.250"),
    )


@pytest.fixture(autouse=True)
def _cleanup_seaweedfs_keys():
    from apps.core.storage import get_s3_client
    written = []
    yield written
    if written:
        client = get_s3_client()
        for key in written:
            client.delete_object(Bucket=settings.SEAWEEDFS["BUCKET"], Key=key)


@pytest.mark.django_db
class TestThresholdAnomalyDetectionService:
    def test_baseline_not_yet_mature_skips_detection(self, _cleanup_seaweedfs_keys):
        component = _make_component(org_name="Baseline Immature")
        device = _make_device(component)
        ingest = SensorReadingIngestService()
        detect = ThresholdAnomalyDetectionService()

        readings = [
            {
                "timestamp": datetime(2026, 8, 16, 10, i, tzinfo=timezone.utc),
                "value": 1.0, "unit": "mm/s2", "quality_flag": "ok",
            }
            for i in range(5)  # jauh di bawah ANOMALY_BASELINE_WINDOW_READINGS
        ]
        key = ingest.write_batch(device_id=device.id, readings=readings)
        _cleanup_seaweedfs_keys.append(key)

        events = detect.detect_and_record(device=device, new_readings=readings)
        assert events == []
        assert AnomalyEvent.objects.filter(device=device).count() == 0

    def test_outlier_detected_with_correct_severity(self, _cleanup_seaweedfs_keys):
        component = _make_component(org_name="Outlier Test")
        device = _make_device(component)
        ingest = SensorReadingIngestService()
        detect = ThresholdAnomalyDetectionService()

        min_window = SENSORS["ANOMALY_BASELINE_WINDOW_READINGS"]
        # Baseline stabil: nilai 1.0 dengan sedikit noise deterministik,
        # lalu SATU outlier ekstrem di akhir batch yang sama.
        readings = [
            {
                "timestamp": datetime(2026, 8, 16, 10, i % 59, tzinfo=timezone.utc),
                "value": 1.0 + (0.01 if i % 2 == 0 else -0.01),
                "unit": "mm/s2", "quality_flag": "ok",
            }
            for i in range(min_window)
        ]
        readings.append({
            "timestamp": datetime(2026, 8, 16, 11, 0, tzinfo=timezone.utc),
            "value": 100.0,  # outlier ekstrem -- pasti >8 sigma
            "unit": "mm/s2", "quality_flag": "ok",
        })
        key = ingest.write_batch(device_id=device.id, readings=readings)
        _cleanup_seaweedfs_keys.append(key)

        events = detect.detect_and_record(device=device, new_readings=readings)
        assert len(events) == 1
        assert events[0].severity == AnomalyEvent.Severity.CRITICAL
        assert events[0].detection_method == AnomalyEvent.DetectionMethod.THRESHOLD
        assert AnomalyEvent.objects.filter(device=device).count() == 1

    def test_normal_readings_no_anomaly(self, _cleanup_seaweedfs_keys):
        component = _make_component(org_name="Normal Test")
        device = _make_device(component)
        ingest = SensorReadingIngestService()
        detect = ThresholdAnomalyDetectionService()

        min_window = SENSORS["ANOMALY_BASELINE_WINDOW_READINGS"]
        readings = [
            {
                "timestamp": datetime(2026, 8, 16, 10, i % 59, tzinfo=timezone.utc),
                "value": 1.0 + (0.01 if i % 2 == 0 else -0.01),
                "unit": "mm/s2", "quality_flag": "ok",
            }
            for i in range(min_window)
        ]
        key = ingest.write_batch(device_id=device.id, readings=readings)
        _cleanup_seaweedfs_keys.append(key)

        events = detect.detect_and_record(device=device, new_readings=readings)
        assert events == []
        assert AnomalyEvent.objects.filter(device=device).count() == 0
