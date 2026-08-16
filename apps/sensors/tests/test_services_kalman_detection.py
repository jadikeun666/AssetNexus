from datetime import datetime, timezone
from decimal import Decimal

import pytest
from django.conf import settings

from apps.assets.models import Asset, AssetComponent
from apps.core.models import Organization
from apps.sensors.models import AnomalyEvent, SensorDevice
from apps.sensors.services_ingestion import SensorReadingIngestService
from apps.sensors.services_kalman_detection import KalmanAnomalyDetectionService
from config.assetnexus import KALMAN


def _make_component(org_name="Kalman Test"):
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


def _make_device(component):
    return SensorDevice.objects.create(
        component=component,
        device_type=SensorDevice.DeviceType.ACCELEROMETER,
        install_date=datetime(2026, 1, 1).date(),
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
class TestKalmanAnomalyDetectionService:
    def test_initializes_state_from_baseline_and_saves_to_device(
        self, _cleanup_seaweedfs_keys
    ):
        component = _make_component(org_name="Init Test")
        device = _make_device(component)
        assert device.kalman_state is None

        ingest = SensorReadingIngestService()
        detect = KalmanAnomalyDetectionService()

        readings = [
            {
                "timestamp": datetime(2026, 8, 16, 10, i % 59, tzinfo=timezone.utc),
                "value": 1.0, "unit": "mm/s2", "quality_flag": "ok",
            }
            for i in range(5)
        ]
        key = ingest.write_batch(device_id=device.id, readings=readings)
        _cleanup_seaweedfs_keys.append(key)

        detect.detect_and_record(device=device, new_readings=readings)
        device.refresh_from_db()

        assert device.kalman_state is not None
        assert device.kalman_state["n_updates"] == 5
        assert "estimate" in device.kalman_state
        assert "variance" in device.kalman_state

    def test_stable_readings_no_anomaly(self, _cleanup_seaweedfs_keys):
        component = _make_component(org_name="Stable Test")
        device = _make_device(component)
        ingest = SensorReadingIngestService()
        detect = KalmanAnomalyDetectionService()

        min_active = KALMAN["MIN_READINGS_BEFORE_ACTIVE"]
        readings = [
            {
                "timestamp": datetime(2026, 8, 16, 10, i % 59, tzinfo=timezone.utc),
                "value": 1.0 + (0.01 if i % 2 == 0 else -0.01),
                "unit": "mm/s2", "quality_flag": "ok",
            }
            for i in range(min_active + 10)
        ]
        key = ingest.write_batch(device_id=device.id, readings=readings)
        _cleanup_seaweedfs_keys.append(key)

        events = detect.detect_and_record(device=device, new_readings=readings)
        assert events == []
        assert AnomalyEvent.objects.filter(device=device).count() == 0

    def test_sudden_jump_detected_even_within_historical_range(
        self, _cleanup_seaweedfs_keys
    ):
        # Perbedaan kunci dari threshold: nilai "5.0" bisa saja TIDAK
        # terdeteksi threshold kalau riwayat punya sebaran luas, tapi
        # Kalman mendeteksinya sebagai penyimpangan TREN mendadak dari
        # estimate yang sudah konvergen ke ~1.0.
        component = _make_component(org_name="Jump Test")
        device = _make_device(component)
        ingest = SensorReadingIngestService()
        detect = KalmanAnomalyDetectionService()

        min_active = KALMAN["MIN_READINGS_BEFORE_ACTIVE"]
        stable_readings = [
            {
                "timestamp": datetime(2026, 8, 16, 10, i % 59, tzinfo=timezone.utc),
                "value": 1.0 + (0.01 if i % 2 == 0 else -0.01),
                "unit": "mm/s2", "quality_flag": "ok",
            }
            for i in range(min_active + 20)
        ]
        key1 = ingest.write_batch(device_id=device.id, readings=stable_readings)
        _cleanup_seaweedfs_keys.append(key1)
        detect.detect_and_record(device=device, new_readings=stable_readings)
        device.refresh_from_db()

        jump_reading = [{
            "timestamp": datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc),
            "value": 5.0,  # lonjakan mendadak
            "unit": "mm/s2", "quality_flag": "ok",
        }]
        key2 = ingest.write_batch(device_id=device.id, readings=jump_reading)
        _cleanup_seaweedfs_keys.append(key2)

        events = detect.detect_and_record(device=device, new_readings=jump_reading)
        assert len(events) == 1
        assert events[0].detection_method == AnomalyEvent.DetectionMethod.KALMAN_RESIDUAL

    def test_below_min_readings_before_active_no_detection(
        self, _cleanup_seaweedfs_keys
    ):
        component = _make_component(org_name="Below Min Test")
        device = _make_device(component)
        ingest = SensorReadingIngestService()
        detect = KalmanAnomalyDetectionService()

        readings = [
            {
                "timestamp": datetime(2026, 8, 16, 10, i, tzinfo=timezone.utc),
                "value": 1.0, "unit": "mm/s2", "quality_flag": "ok",
            }
            for i in range(5)
        ]
        readings.append({
            "timestamp": datetime(2026, 8, 16, 11, 0, tzinfo=timezone.utc),
            "value": 999.0,  # ekstrem, tapi n_updates masih < MIN_READINGS_BEFORE_ACTIVE
            "unit": "mm/s2", "quality_flag": "ok",
        })
        key = ingest.write_batch(device_id=device.id, readings=readings)
        _cleanup_seaweedfs_keys.append(key)

        events = detect.detect_and_record(device=device, new_readings=readings)
        assert events == []
