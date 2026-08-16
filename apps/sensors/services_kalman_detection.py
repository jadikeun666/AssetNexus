"""
formulas.md §4 (konteks), database.md §3 amandemen aditif (SensorDevice
.kalman_state, langkah d Fase 4). Kalman filter 1D local-level -- model
proses paling sederhana untuk sinyal fisik generik tanpa asumsi dinamika
spesifik per device_type (konsisten rasionalisasi services_anomaly_
detection.py: tidak menebak model fisik per jenis sensor).

Berbeda dari ThresholdAnomalyDetectionService (statistik STATIS terhadap
seluruh riwayat), Kalman mendeteksi penyimpangan dari TREN TERKINI --
lebih sensitif terhadap perubahan mendadak meski nilai masih dalam
rentang historis wajar secara absolut.
"""
from uuid import UUID

import duckdb
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from config.assetnexus import KALMAN

from .models import AnomalyEvent, SensorDevice
from .services_anomaly_detection import _get_duckdb_connection, _severity_for_zscore


def _initialize_state(device: SensorDevice) -> dict:
    """
    Estimasi R (measurement noise) dari variance baseline historis Parquet
    device -- BUKAN angka tebakan tetap. Q diturunkan dari R via rasio
    tetap (config/assetnexus.py KALMAN.PROCESS_TO_MEASUREMENT_NOISE_RATIO).
    """
    bucket = settings.SEAWEEDFS["BUCKET"]
    con = _get_duckdb_connection()
    row = con.execute(
        f"SELECT AVG(value), VAR_SAMP(value) FROM read_parquet("
        f"'s3://{bucket}/sensors/{device.id}/*/*.parquet')"
    ).fetchone()
    mean, variance = row

    if variance is None or variance == 0:
        # Riwayat kosong atau semua nilai identik -- fallback konservatif:
        # R kecil non-nol supaya filter tetap terdefinisi (pembagian oleh
        # nol dihindari), akan cepat terkoreksi begitu ada variasi nyata.
        variance = 1e-6

    r = float(variance)
    q = r * KALMAN["PROCESS_TO_MEASUREMENT_NOISE_RATIO"]
    return {
        "estimate": float(mean) if mean is not None else 0.0,
        "variance": r,
        "measurement_noise": r,
        "process_noise": q,
        "n_updates": 0,
    }


class KalmanAnomalyDetectionService:
    def detect_and_record(
        self, *, device: SensorDevice, new_readings: list[dict]
    ) -> list[AnomalyEvent]:
        """
        Predict-update Kalman untuk tiap reading di new_readings, urut
        sesuai timestamp. State disimpan balik ke device.kalman_state
        setelah selesai (satu UPDATE, bukan per-reading, untuk efisiensi).
        """
        state = device.kalman_state
        if state is None:
            state = _initialize_state(device)

        min_active = KALMAN["MIN_READINGS_BEFORE_ACTIVE"]
        threshold = KALMAN["RESIDUAL_ZSCORE_THRESHOLD"]

        created = []
        sorted_readings = sorted(new_readings, key=lambda r: r["timestamp"])

        for r in sorted_readings:
            predicted_variance = state["variance"] + state["process_noise"]
            innovation = r["value"] - state["estimate"]
            innovation_std = (predicted_variance + state["measurement_noise"]) ** 0.5

            gain = predicted_variance / (predicted_variance + state["measurement_noise"])
            state["estimate"] = state["estimate"] + gain * innovation
            state["variance"] = (1 - gain) * predicted_variance
            state["n_updates"] += 1

            if state["n_updates"] >= min_active and innovation_std > 0:
                zscore = abs(innovation) / innovation_std
                severity = _severity_for_zscore(zscore) if zscore >= threshold else None
                if severity is not None:
                    created.append(
                        AnomalyEvent.objects.create(
                            device=device,
                            detected_at=timezone.now(),
                            detection_method=AnomalyEvent.DetectionMethod.KALMAN_RESIDUAL,
                            severity=severity,
                        )
                    )

        with transaction.atomic():
            device.kalman_state = state
            device.save(update_fields=["kalman_state"])

        return created
