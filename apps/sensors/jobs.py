"""
architecture.md §4: SensorAnomalyDetected -> PushAnomalyAlertJob.
Dipicu oleh signals.py (post_save AnomalyEvent), dikirim async lewat
Dramatiq broker -- BUKAN dipanggil sinkron dari api.py (engineering-
rules.md §6, pola sama seperti recalculate_deterioration_job).
"""
import dramatiq
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .models import AnomalyEvent


@dramatiq.actor(max_retries=3)
def push_anomaly_alert_job(anomaly_event_id: str):
    """
    architecture.md §5: push ke grup Channels asset_{asset_id}_alerts --
    konsumen /ws/assets/{asset_id}/alerts yang subscribe grup itu akan
    menerima payload ini. asset_id diturunkan dari rantai FK
    device -> component -> asset (AnomalyEvent tidak punya FK langsung
    ke Asset, sama seperti pola OrganizationScopedManager di models.py).
    """
    event = AnomalyEvent.objects.select_related(
        "device__component__asset"
    ).get(id=anomaly_event_id)
    asset_id = event.device.component.asset_id

    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"asset_{asset_id}_alerts",
        {
            "type": "anomaly_alert",
            "payload": {
                "anomaly_id": str(event.id),
                "device_id": str(event.device_id),
                "component_id": str(event.device.component_id),
                "detected_at": event.detected_at.isoformat(),
                "detection_method": event.detection_method,
                "severity": event.severity,
            },
        },
    )
