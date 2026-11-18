from datetime import datetime, timedelta, timezone

import pytest
from django.conf import settings

from apps.sensors.services_ingestion import SensorReadingIngestService
from apps.sensors.services_readings import (
    InvalidTraceWindowError,
    SensorReadingQueryService,
)
from apps.sensors.tests.test_services_anomaly_detection import (
    _make_component,
    _make_device,
)
from config.assetnexus import SENSORS

T0 = datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _cleanup_seaweedfs_keys():
    from apps.core.storage import get_s3_client
    written = []
    yield written
    if written:
        client = get_s3_client()
        for key in written:
            client.delete_object(Bucket=settings.SEAWEEDFS["BUCKET"], Key=key)


def _write_minutes(device, written, count):
    readings = [
        {
            "timestamp": T0 + timedelta(minutes=i),
            "value": float(i), "unit": "mm/s2", "quality_flag": "ok",
        }
        for i in range(count)
    ]
    written.append(SensorReadingIngestService().write_batch(
        device_id=device.id, readings=readings))


@pytest.mark.django_db
class TestSensorReadingQueryService:
    def test_window_is_inclusive_ordered_and_roundtrips_values(self, _cleanup_seaweedfs_keys):
        device = _make_device(_make_component(org_name="Trace Window"))
        _write_minutes(device, _cleanup_seaweedfs_keys, 10)

        result = SensorReadingQueryService().read_window(
            device_id=device.id,
            start=T0 + timedelta(minutes=3), end=T0 + timedelta(minutes=6),
        )
        assert result["truncated"] is False
        assert [r["value"] for r in result["readings"]] == [3.0, 4.0, 5.0, 6.0]
        assert [r["timestamp"] for r in result["readings"]] == [
            T0 + timedelta(minutes=m) for m in (3, 4, 5, 6)
        ]
        assert result["readings"][0]["unit"] == "mm/s2"

    def test_device_without_parquet_returns_empty(self):
        device = _make_device(_make_component(org_name="Trace Empty"))
        result = SensorReadingQueryService().read_window(
            device_id=device.id, start=T0, end=T0 + timedelta(hours=1),
        )
        assert result["readings"] == []
        assert result["truncated"] is False

    def test_truncates_to_earliest_points_and_flags_it(
        self, _cleanup_seaweedfs_keys, monkeypatch
    ):
        device = _make_device(_make_component(org_name="Trace Truncate"))
        _write_minutes(device, _cleanup_seaweedfs_keys, 10)
        monkeypatch.setitem(SENSORS, "MAX_TRACE_POINTS", 3)

        result = SensorReadingQueryService().read_window(
            device_id=device.id, start=T0, end=T0 + timedelta(hours=1),
        )
        assert result["truncated"] is True
        assert [r["value"] for r in result["readings"]] == [0.0, 1.0, 2.0]

    @pytest.mark.parametrize("start,end", [
        (T0, T0),                                   # end tidak setelah start
        (T0 + timedelta(hours=1), T0),              # terbalik
        (T0, T0 + timedelta(hours=25)),             # lebih lebar dari 24 jam
        (T0.replace(tzinfo=None), T0 + timedelta(hours=1)),  # naive
    ])
    def test_invalid_window_rejected(self, start, end):
        with pytest.raises(InvalidTraceWindowError):
            SensorReadingQueryService().read_window(
                device_id="00000000-0000-0000-0000-000000000000",
                start=start, end=end,
            )
