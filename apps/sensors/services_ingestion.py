"""
formulas.md §4 (konteks), database.md §0 & §3, architecture.md §0:
SensorReading BUKAN model Django -- ditulis sebagai file Parquet ke
SeaweedFS via DuckDB, satu file per batch ingest per device.

database.md §1: timestamp selalu UTC di storage -- dinormalisasi eksplisit
di sini, tidak bergantung pada timezone session DuckDB/mesin (terverifikasi
manual: tanpa normalisasi, DuckDB now()/local timestamp mengikuti tz lokal
mesin, BUKAN UTC).

Partisi path: sensors/{device_id}/{date}/{uuid}.parquet -- SATU file per
request ingest, bukan satu file tunggal per device per hari (Parquet tidak
mendukung append native; banyak file kecil per partisi tanggal adalah pola
standar, bisa di-compact belakangan jika diperlukan -- didokumentasikan
sebagai keputusan desain eksplisit, bukan penyimpangan diam-diam dari
"satu file per device per hari" di database.md §3).
"""
import uuid
from datetime import timezone as dt_timezone

import duckdb
from django.conf import settings


def _get_duckdb_connection() -> duckdb.DuckDBPyConnection:
    """
    Koneksi baru per operasi (bukan connection pool/singleton) --
    kredensial S3 di-SET per koneksi, biaya setup INSTALL/LOAD httpfs
    kecil dan idempotent, konsisten dengan pola get_s3_client() di
    core/storage.py yang juga membuat client baru tiap panggilan.
    """
    cfg = settings.SEAWEEDFS
    endpoint = cfg["S3_ENDPOINT"].replace("http://", "").replace("https://", "")
    use_ssl = cfg["S3_ENDPOINT"].startswith("https://")

    con = duckdb.connect()
    con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")
    con.execute(f"SET s3_endpoint='{endpoint}'")
    con.execute(f"SET s3_access_key_id='{cfg['S3_ACCESS_KEY']}'")
    con.execute(f"SET s3_secret_access_key='{cfg['S3_SECRET_KEY']}'")
    con.execute(f"SET s3_use_ssl={'true' if use_ssl else 'false'}")
    con.execute("SET s3_url_style='path'")
    return con


class SensorReadingIngestService:
    def write_batch(self, *, device_id: uuid.UUID, readings: list[dict]) -> str:
        """
        Tulis satu batch reading sebagai satu file Parquet baru. Mengembalikan
        object key (bukan URL, konsisten pola file_ref di seluruh project).

        readings: list of dict dengan key timestamp (datetime, WAJIB aware
        atau di-treat sebagai UTC jika naive), value (float), unit (str),
        quality_flag (str).
        """
        if not readings:
            raise ValueError("readings tidak boleh kosong")

        rows = []
        for r in readings:
            ts = r["timestamp"]
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=dt_timezone.utc)
            else:
                ts = ts.astimezone(dt_timezone.utc)
            rows.append(
                {
                    "device_id": str(device_id),
                    "timestamp": ts,
                    "value": float(r["value"]),
                    "unit": r["unit"],
                    "quality_flag": r["quality_flag"],
                }
            )

        first_date = rows[0]["timestamp"].date().isoformat()
        batch_id = uuid.uuid4()
        key = f"sensors/{device_id}/{first_date}/{batch_id}.parquet"

        con = _get_duckdb_connection()
        con.execute(
            "CREATE TABLE batch (device_id VARCHAR, timestamp TIMESTAMPTZ, "
            "value DOUBLE, unit VARCHAR, quality_flag VARCHAR)"
        )
        con.executemany(
            "INSERT INTO batch VALUES (?, ?, ?, ?, ?)",
            [
                (r["device_id"], r["timestamp"], r["value"], r["unit"], r["quality_flag"])
                for r in rows
            ],
        )
        con.execute(
            f"COPY batch TO 's3://{settings.SEAWEEDFS['BUCKET']}/{key}' (FORMAT PARQUET)"
        )
        con.close()

        return key
