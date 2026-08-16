from datetime import datetime
from uuid import UUID

from ninja import Schema


class SensorReadingIn(Schema):
    """database.md §3 SensorReading. quality_flag default 'ok' -- device
    yang tidak mengirim flag eksplisit diasumsikan bacaan normal."""

    timestamp: datetime
    value: float
    unit: str
    quality_flag: str = "ok"  # ok, suspect, missing


class SensorReadingBatchIn(Schema):
    readings: list[SensorReadingIn]


class IngestResultOut(Schema):
    device_id: UUID
    readings_written: int
    parquet_key: str
    anomalies_detected: int


class SensorDeviceIn(Schema):
    component_id: UUID
    device_type: str
    install_date: str  # ISO date, divalidasi/parsed di service


class SensorDeviceOut(Schema):
    id: UUID
    component_id: UUID
    device_type: str
    install_date: str
    status: str


class AnomalyEventOut(Schema):
    id: UUID
    device_id: UUID
    detected_at: datetime
    detection_method: str
    severity: str
    resolved: bool
