"""
architecture.md §3: router tipis -- satu call service per endpoint.
Endpoint pertama app sensors (Fase 4, prd.md §8): registrasi device
(asset-registry.md §6) dan ingestion batch SensorReading (database.md §3).
"""
from uuid import UUID

from ninja import Router
from ninja.errors import HttpError

from apps.assets.api import _current_org_stub
from config.assetnexus import SENSORS

from .schemas import (
    AnomalyEventOut,
    IngestResultOut,
    SensorDeviceIn,
    SensorDeviceOut,
    SensorReadingBatchIn,
)
from .services import AnomalyEventService, SensorDeviceService
from .services_anomaly_detection import ThresholdAnomalyDetectionService
from .services_ingestion import SensorReadingIngestService
from .services_kalman_detection import KalmanAnomalyDetectionService

router = Router(tags=["sensors"])

device_service = SensorDeviceService()
anomaly_service = AnomalyEventService()
ingest_service = SensorReadingIngestService()
threshold_detection_service = ThresholdAnomalyDetectionService()
kalman_detection_service = KalmanAnomalyDetectionService()


@router.post("/devices/", response=SensorDeviceOut)
def create_device(request, payload: SensorDeviceIn):
    org_id = _current_org_stub(request)
    device = device_service.create(org_id, created_by=None, data=payload.dict())
    return {
        "id": device.id,
        "component_id": device.component_id,
        "device_type": device.device_type,
        "install_date": device.install_date.isoformat(),
        "status": device.status,
    }


@router.get("/devices/", response=list[SensorDeviceOut])
def list_devices(request):
    org_id = _current_org_stub(request)
    devices = device_service.list_for_organization(org_id)
    return [
        {
            "id": d.id,
            "component_id": d.component_id,
            "device_type": d.device_type,
            "install_date": d.install_date.isoformat(),
            "status": d.status,
        }
        for d in devices
    ]


@router.post("/devices/{device_id}/readings/", response=IngestResultOut)
def ingest_readings(request, device_id: UUID, payload: SensorReadingBatchIn):
    """
    database.md §3: tulis batch ke Parquet/SeaweedFS, lalu jalankan
    deteksi anomali threshold (langkah c) DAN Kalman-residual (langkah d)
    terhadap batch yang baru ditulis -- keduanya dijalankan berurutan
    dalam request yang sama (bukan Dramatiq terpisah), karena deteksi
    dini butuh latency rendah dan kedua service tergolong ringan
    (query agregasi DuckDB per batch, bukan komputasi berat seperti
    fit CTMC/PINN).
    """
    org_id = _current_org_stub(request)
    device = device_service.get(org_id, device_id)

    if len(payload.readings) > SENSORS["MAX_READINGS_PER_INGEST_REQUEST"]:
        raise HttpError(
            400,
            f"Maksimum {SENSORS['MAX_READINGS_PER_INGEST_REQUEST']} reading "
            f"per request, diterima {len(payload.readings)}.",
        )
    if len(payload.readings) == 0:
        raise HttpError(400, "readings tidak boleh kosong.")

    readings_data = [r.dict() for r in payload.readings]
    key = ingest_service.write_batch(device_id=device.id, readings=readings_data)

    # Langkah c + d: deteksi threshold (statistik statis) DAN Kalman
    # (deviasi dari tren terkini) dijalankan keduanya -- keduanya
    # menangkap pola anomali berbeda (formulas.md §4 konteks umum,
    # architecture.md §4 SensorAnomalyDetected). AnomalyEvent dari kedua
    # metode disimpan terpisah (detection_method berbeda), tidak
    # di-dedupe -- satu reading bisa sah terdeteksi oleh keduanya.
    threshold_events = threshold_detection_service.detect_and_record(
        device=device, new_readings=readings_data
    )
    kalman_events = kalman_detection_service.detect_and_record(
        device=device, new_readings=readings_data
    )
    total_anomalies = len(threshold_events) + len(kalman_events)

    return {
        "device_id": device.id,
        "readings_written": len(payload.readings),
        "parquet_key": key,
        "anomalies_detected": total_anomalies,
    }


@router.get("/devices/{device_id}/anomalies/", response=list[AnomalyEventOut])
def list_anomalies(request, device_id: UUID):
    org_id = _current_org_stub(request)
    device_service.get(org_id, device_id)
    events = anomaly_service.list_for_device(org_id, device_id)
    return [
        {
            "id": e.id,
            "device_id": e.device_id,
            "detected_at": e.detected_at,
            "detection_method": e.detection_method,
            "severity": e.severity,
            "resolved": e.resolved,
        }
        for e in events
    ]
