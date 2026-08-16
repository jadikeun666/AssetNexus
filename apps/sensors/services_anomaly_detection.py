"""
formulas.md §4 (konteks umum SensorDevice), database.md §3 (AnomalyEvent
detection_method='threshold'), engineering-rules.md §2 (AnomalyEvent
informasional/alerting saja, tidak pernah aksi otomatis).

Metode: three-sigma rule (Shewhart control chart, ISO 7870) -- deviasi
statistik dari baseline historis device yang sama, BUKAN ambang fisik
absolut per device_type. Dipilih setelah riset literatur SHM (bridge
vibration monitoring) mengonfirmasi pendekatan deviasi-dari-baseline
adalah standar, bukan ambang mutlak universal yang tidak punya dasar
kuat untuk ditebak per jenis sensor (config/assetnexus.py SENSORS).

Baseline (mean/std) dihitung ON-DEMAND dari Parquet historis via DuckDB
query -- TIDAK disimpan sebagai running state terpisah di PostgreSQL,
konsisten database.md §0: Parquet satu-satunya sumber kebenaran time-
series, PostgreSQL tidak menyimpan salinan/agregat time-series di luar
pola summary seperti DegradationForecast.
"""
from uuid import UUID

import duckdb
from django.conf import settings
from django.utils import timezone

from config.assetnexus import SENSORS

from .models import AnomalyEvent, SensorDevice


def _get_duckdb_connection() -> duckdb.DuckDBPyConnection:
    """Duplikasi kecil dari services_ingestion._get_duckdb_connection --
    dipertahankan terpisah (bukan diimpor silang) karena keduanya modul
    dengan tanggung jawab berbeda (tulis vs baca-agregasi); menyatukan
    jadi util bersama adalah refactor terpisah, bukan bagian langkah ini."""
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


def _severity_for_zscore(abs_zscore: float) -> str | None:
    bands = SENSORS["ANOMALY_SEVERITY_ZSCORE_BANDS"]
    if abs_zscore >= bands["critical"]:
        return AnomalyEvent.Severity.CRITICAL
    if abs_zscore >= bands["high"]:
        return AnomalyEvent.Severity.HIGH
    if abs_zscore >= bands["medium"]:
        return AnomalyEvent.Severity.MEDIUM
    return None  # di bawah threshold dasar -- bukan anomali


class ThresholdAnomalyDetectionService:
    def detect_and_record(
        self, *, device: SensorDevice, new_readings: list[dict]
    ) -> list[AnomalyEvent]:
        """
        Hitung baseline (mean/std) dari SELURUH riwayat Parquet device ini,
        lalu evaluasi tiap reading di new_readings terhadap baseline itu.
        new_readings SENDIRI ikut masuk hitungan baseline (sudah tertulis
        ke Parquet oleh SensorReadingIngestService sebelum method ini
        dipanggil) -- ini konsisten dengan cara three-sigma rule bekerja
        di SPC: baseline mencakup semua data historis termasuk titik yang
        sedang dievaluasi, bukan baseline "sebelum" titik itu secara
        artifisial dikecualikan.

        Mengembalikan list AnomalyEvent yang BARU dibuat (bisa kosong).
        """
        bucket = settings.SEAWEEDFS["BUCKET"]
        con = _get_duckdb_connection()
        try:
            count_row = con.execute(
                f"SELECT COUNT(*) FROM read_parquet("
                f"'s3://{bucket}/sensors/{device.id}/*/*.parquet')"
            ).fetchone()
        except duckdb.IOException:
            # Belum ada file Parquet sama sekali untuk device ini --
            # secara teori tidak mungkin terjadi saat method ini dipanggil
            # (ingestion selalu tulis dulu), tapi dijaga eksplisit.
            return []

        total_readings = count_row[0] if count_row else 0
        min_window = SENSORS["ANOMALY_BASELINE_WINDOW_READINGS"]
        if total_readings < min_window:
            return []  # baseline belum cukup matang -- TIDAK dievaluasi

        stats_row = con.execute(
            f"SELECT AVG(value), STDDEV_SAMP(value) FROM read_parquet("
            f"'s3://{bucket}/sensors/{device.id}/*/*.parquet')"
        ).fetchone()
        mean, stddev = stats_row

        if stddev is None or stddev == 0:
            # Semua reading historis identik -- deviasi apa pun dari nilai
            # itu adalah anomali pasti, tapi z-score tidak terdefinisi
            # (pembagian oleh nol). Kasus tepi jarang tapi harus ditangani
            # eksplisit, bukan membiarkan ZeroDivisionError.
            created = []
            for r in new_readings:
                if r["value"] != mean:
                    created.append(
                        AnomalyEvent.objects.create(
                            device=device,
                            detected_at=timezone.now(),
                            detection_method=AnomalyEvent.DetectionMethod.THRESHOLD,
                            severity=AnomalyEvent.Severity.HIGH,
                        )
                    )
            return created

        created = []
        for r in new_readings:
            zscore = (r["value"] - mean) / stddev
            severity = _severity_for_zscore(abs(zscore))
            if severity is not None:
                created.append(
                    AnomalyEvent.objects.create(
                        device=device,
                        detected_at=timezone.now(),
                        detection_method=AnomalyEvent.DetectionMethod.THRESHOLD,
                        severity=severity,
                    )
                )
        return created
