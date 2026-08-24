from django.db.models.signals import post_save
from django.dispatch import receiver

from .jobs import push_anomaly_alert_job
from .models import AnomalyEvent


@receiver(post_save, sender=AnomalyEvent)
def on_anomaly_detected(sender, instance, created, **kwargs):
    """
    architecture.md §4: SensorAnomalyDetected -> PushAnomalyAlertJob.
    Message-passing lewat Dramatiq broker (actor.send()), bukan
    pemanggilan langsung -- pola sama persis dengan
    apps/inspections/signals.py (InspectionRecorded).
    """
    if created:
        push_anomaly_alert_job.send(str(instance.id))
