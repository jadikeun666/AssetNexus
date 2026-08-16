from django.db import models
from apps.assets.models import AssetComponent
from apps.core.managers import OrganizationScopedManager
from apps.core.models import BaseModel, SoftDeleteModel


class SensorDevice(BaseModel, SoftDeleteModel):
    """
    database.md §3, asset-registry.md §6. Satu row = satu perangkat sensor
    terpasang pada satu AssetComponent. Time-series aktual TIDAK disimpan
    di sini — SensorReading murni Parquet/SeaweedFS via DuckDB
    (database.md §0, §3), diakses lewat service layer terpisah, bukan
    model Django.
    """

    class DeviceType(models.TextChoices):
        ACCELEROMETER = "accelerometer", "Accelerometer"
        STRAIN_GAUGE = "strain_gauge", "Strain Gauge"
        TILTMETER = "tiltmeter", "Tiltmeter"
        THERMOMETER = "thermometer", "Thermometer"

    class Status(models.TextChoices):
        ACTIVE = "active", "Aktif"
        INACTIVE = "inactive", "Tidak Aktif"
        FAULTY = "faulty", "Rusak"

    component = models.ForeignKey(
        AssetComponent, on_delete=models.CASCADE, related_name="sensor_devices"
    )
    device_type = models.CharField(max_length=20, choices=DeviceType.choices)
    install_date = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)

    objects = OrganizationScopedManager(organization_lookup="component__asset__organization_id")

    class Meta:
        db_table = "sensors_sensordevice"

    def __str__(self):
        return f"{self.component.component_type} — {self.device_type} ({self.id})"


class AnomalyEvent(BaseModel, SoftDeleteModel):
    """
    database.md §3, architecture.md §4-5. Ringkasan PostgreSQL dari
    anomali terdeteksi di jalur ingestion (threshold/Kalman) atau residual
    PINN — TIDAK menyimpan raw time-series (itu tetap di Parquet). Bersifat
    informasional/alerting only, tidak pernah memicu aksi otomatis
    (engineering-rules.md §2).
    """

    class DetectionMethod(models.TextChoices):
        THRESHOLD = "threshold", "Threshold"
        KALMAN_RESIDUAL = "kalman_residual", "Kalman Residual"
        PINN_RESIDUAL = "pinn_residual", "PINN Residual"

    class Severity(models.TextChoices):
        LOW = "low", "Rendah"
        MEDIUM = "medium", "Sedang"
        HIGH = "high", "Tinggi"
        CRITICAL = "critical", "Kritis"

    device = models.ForeignKey(
        SensorDevice, on_delete=models.CASCADE, related_name="anomaly_events"
    )
    detected_at = models.DateTimeField()
    detection_method = models.CharField(max_length=20, choices=DetectionMethod.choices)
    severity = models.CharField(max_length=10, choices=Severity.choices)
    resolved = models.BooleanField(default=False)
    resolution_notes = models.TextField(blank=True, default="")

    objects = OrganizationScopedManager(
        organization_lookup="device__component__asset__organization_id"
    )

    class Meta:
        db_table = "sensors_anomalyevent"
        indexes = [
            models.Index(
                fields=["resolved"],
                condition=models.Q(resolved=False),
                name="anomalyevent_unresolved_idx",
            ),
        ]

    def __str__(self):
        return f"{self.device_id} — {self.severity} ({self.detected_at:%Y-%m-%d})"