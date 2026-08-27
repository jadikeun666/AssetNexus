"""
visualization.md §6: anomaly hotspot marker untuk komponen bersensor --
AnomalyEvent unresolved dengan severity >= medium dirender sebagai
pulsing marker (THREE.Sprite) di posisi bounding-box center sub-mesh
komponen terkait.

Cross-app read query (digitaltwin -> sensors), pola sama persis
services_maintenance_markers.py (digitaltwin -> maintenance) --
BUKAN orkestrasi side-effect sinkron (engineering-rules.md §6).

Endpoint TERPISAH dari ViewerPayloadOut (alasan sama dengan
MaintenanceMarkerOut): anomali bisa muncul kapan saja secara real-time
(push via WebSocket, langkah e Fase 4) -- payload viewer utama
(forecast_by_component) sekali-fetch per-session tidak boleh
terpengaruh siklus refresh anomali.

Keputusan desain (analog "approved plan terbaru" di maintenance markers,
tapi TIDAK butuh pemilihan "run terbaru" -- AnomalyEvent bukan snapshot
per-run, cukup filter unresolved + severity):
- severity >= medium (bukan low) -- visualization.md §6 eksplisit
  menyebut "severity >= medium", low TIDAK muncul sebagai hotspot marker
  (masih bisa dilihat lewat GET /sensors/devices/{id}/anomalies/ biasa).
- Satu AnomalyEvent bisa merujuk banyak komponen? TIDAK -- device selalu
  1:1 ke satu component (SensorDevice.component, database.md §3), jadi
  rantai device->component sudah tunggal, tidak perlu agregasi/pilih
  "yang terbaru" seperti maintenance markers (yang portfolio-level).
  Kalau SATU component punya BANYAK unresolved AnomalyEvent (>1 device,
  atau >1 event dari device yang sama), SEMUA disertakan -- viewer
  frontend yang memutuskan render satu marker gabungan atau tumpuk
  (keputusan visual, bukan keputusan data layer).
"""
from __future__ import annotations

import uuid

from apps.sensors.models import AnomalyEvent


class AnomalyMarkerService:
    """Query read-only untuk anomaly hotspot marker viewer 3D. Tidak
    pernah menulis ke database, tidak pernah menyentuh Channels/Dramatiq
    (itu sepenuhnya domain apps.sensors, langkah e)."""

    def get_markers(self, organization_id: uuid.UUID, asset_id: uuid.UUID) -> list[dict]:
        severity_order = [
            AnomalyEvent.Severity.MEDIUM,
            AnomalyEvent.Severity.HIGH,
            AnomalyEvent.Severity.CRITICAL,
        ]
        events = (
            AnomalyEvent.objects.for_organization(organization_id)
            .filter(
                device__component__asset_id=asset_id,
                resolved=False,
                severity__in=severity_order,
                deleted_at__isnull=True,
            )
            .select_related("device__component")
            .order_by("-detected_at")
        )

        return [
            {
                "anomaly_id": event.id,
                "device_id": event.device_id,
                "component_id": event.device.component_id,
                "component_type": event.device.component.component_type,
                "detected_at": event.detected_at,
                "detection_method": event.detection_method,
                "severity": event.severity,
            }
            for event in events
        ]
