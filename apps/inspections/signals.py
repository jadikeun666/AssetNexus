from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.deterioration.jobs import recalculate_deterioration_job

from .models import InspectionRecord


@receiver(post_save, sender=InspectionRecord)
def on_inspection_recorded(sender, instance, created, **kwargs):
    """
    architecture.md §4: InspectionRecorded -> RecalculateDeteriorationJob.
    inspections app tidak memanggil service deterioration secara
    sinkron — ini message-passing lewat Dramatiq broker (actor.send()),
    bukan pemanggilan langsung lintas domain (engineering-rules.md §6).
    """
    if created and instance.condition_state:
        recalculate_deterioration_job.send(str(instance.component_id))
