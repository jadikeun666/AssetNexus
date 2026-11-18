"""
visualization.md §6 (sensor trace untuk panel anomaly marker), database.md
§0: hanya app `sensors` dan `deterioration` yang boleh membaca Parquet --
karena itu pembacaan trace ada di sini, bukan di app `digitaltwin`.

Jendela waktu inklusif [start, end]. Hasil dibatasi MAX_TRACE_POINTS
(config/assetnexus.py SENSORS); kalau ada lebih banyak titik, yang
dikembalikan adalah titik TERAWAL dan `truncated=True` -- sengaja tidak
di-downsample diam-diam supaya pemanggil tahu datanya terpotong.
"""
from datetime import datetime
from uuid import UUID

import duckdb
from django.conf import settings

from config.assetnexus import SENSORS

from .services_ingestion import _get_duckdb_connection


class InvalidTraceWindowError(ValueError):
    """Jendela waktu trace tidak valid (naive, terbalik, atau terlalu lebar)."""


class SensorReadingQueryService:
    def read_window(self, *, device_id: UUID, start: datetime, end: datetime) -> dict:
        if start.tzinfo is None or end.tzinfo is None:
            raise InvalidTraceWindowError(
                "start dan end harus menyertakan zona waktu (mis. akhiran Z)."
            )
        if end <= start:
            raise InvalidTraceWindowError("end harus setelah start.")
        max_hours = SENSORS["MAX_TRACE_WINDOW_HOURS"]
        if (end - start).total_seconds() > max_hours * 3600:
            raise InvalidTraceWindowError(
                f"Jendela maksimum {max_hours} jam."
            )

        bucket = settings.SEAWEEDFS["BUCKET"]
        max_points = SENSORS["MAX_TRACE_POINTS"]
        con = _get_duckdb_connection()
        try:
            rows = con.execute(
                f"SELECT timestamp, value, unit, quality_flag FROM read_parquet("
                f"'s3://{bucket}/sensors/{device_id}/*/*.parquet') "
                f"WHERE timestamp >= ? AND timestamp <= ? "
                f"ORDER BY timestamp LIMIT ?",
                [start, end, max_points + 1],
            ).fetchall()
        except duckdb.IOException:
            rows = []  # belum ada file Parquet untuk device ini
        finally:
            con.close()

        truncated = len(rows) > max_points
        rows = rows[:max_points]
        return {
            "device_id": device_id,
            "start": start,
            "end": end,
            "truncated": truncated,
            "readings": [
                {"timestamp": r[0], "value": r[1], "unit": r[2], "quality_flag": r[3]}
                for r in rows
            ],
        }
