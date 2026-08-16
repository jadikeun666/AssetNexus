import uuid
from datetime import datetime, timezone

import duckdb
import pytest
from django.conf import settings

from apps.sensors.services_ingestion import SensorReadingIngestService


def _read_parquet_from_seaweedfs(key: str) -> list[tuple]:
    cfg = settings.SEAWEEDFS
    endpoint = cfg["S3_ENDPOINT"].replace("http://", "").replace("https://", "")
    con = duckdb.connect()
    con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")
    con.execute(f"SET s3_endpoint='{endpoint}'")
    con.execute(f"SET s3_access_key_id='{cfg['S3_ACCESS_KEY']}'")
    con.execute(f"SET s3_secret_access_key='{cfg['S3_SECRET_KEY']}'")
    con.execute("SET s3_use_ssl=false")
    con.execute("SET s3_url_style='path'")
    return con.execute(
        f"SELECT * FROM read_parquet('s3://{cfg['BUCKET']}/{key}')"
    ).fetchall()


@pytest.fixture(autouse=True)
def _cleanup_seaweedfs_test_objects():
    """Kumpulkan key yang ditulis tiap test, hapus setelah selesai --
    supaya SeaweedFS dev tidak terus terisi objek test."""
    from apps.core.storage import get_s3_client

    written_keys = []
    yield written_keys
    if written_keys:
        client = get_s3_client()
        for key in written_keys:
            client.delete_object(Bucket=settings.SEAWEEDFS["BUCKET"], Key=key)


class TestSensorReadingIngestService:
    def test_write_batch_returns_key_and_persists_to_seaweedfs(
        self, _cleanup_seaweedfs_test_objects
    ):
        device_id = uuid.uuid4()
        svc = SensorReadingIngestService()
        key = svc.write_batch(
            device_id=device_id,
            readings=[
                {
                    "timestamp": datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc),
                    "value": 1.23,
                    "unit": "mm/s2",
                    "quality_flag": "ok",
                },
                {
                    "timestamp": datetime(2026, 8, 16, 10, 1, tzinfo=timezone.utc),
                    "value": 4.56,
                    "unit": "mm/s2",
                    "quality_flag": "suspect",
                },
            ],
        )
        _cleanup_seaweedfs_test_objects.append(key)

        assert key.startswith(f"sensors/{device_id}/2026-08-16/")
        assert key.endswith(".parquet")

        rows = _read_parquet_from_seaweedfs(key)
        assert len(rows) == 2
        values = {row[2] for row in rows}
        assert values == {1.23, 4.56}
        # database.md §1: timestamp selalu UTC di storage
        for row in rows:
            assert row[1].tzinfo is not None
            assert row[1].utcoffset().total_seconds() == 0

    def test_write_batch_normalizes_naive_datetime_to_utc(
        self, _cleanup_seaweedfs_test_objects
    ):
        # database.md §1: naive datetime harus di-treat sebagai UTC,
        # bukan diam-diam pakai timezone lokal mesin (bug yang
        # ditemukan saat verifikasi manual sebelum test ini ditulis).
        device_id = uuid.uuid4()
        svc = SensorReadingIngestService()
        naive_ts = datetime(2026, 8, 16, 12, 0)  # tanpa tzinfo
        key = svc.write_batch(
            device_id=device_id,
            readings=[
                {"timestamp": naive_ts, "value": 9.9, "unit": "mm/s2", "quality_flag": "ok"}
            ],
        )
        _cleanup_seaweedfs_test_objects.append(key)

        rows = _read_parquet_from_seaweedfs(key)
        assert rows[0][1].utcoffset().total_seconds() == 0
        assert rows[0][1].hour == 12  # jam TIDAK bergeser, hanya diberi label UTC

    def test_write_batch_empty_readings_raises(self):
        svc = SensorReadingIngestService()
        with pytest.raises(ValueError):
            svc.write_batch(device_id=uuid.uuid4(), readings=[])
