from django.db import models

from apps.assets.models import AssetComponent
from apps.core.managers import OrganizationScopedManager
from apps.core.models import BaseModel


class InspectionRecord(BaseModel):
    """
    database.md §3 + engineering-rules.md §1: append-only, immutable.
    SENGAJA tidak dicampur dengan SoftDeleteModel — tidak ada deleted_at
    sama sekali di sini. Koreksi = row baru via supersedes, bukan edit.
    """

    class Method(models.TextChoices):
        VISUAL = "visual", "Visual"
        NDT = "ndt", "Non-destructive Testing"
        DRONE_PHOTOGRAMMETRY = "drone_photogrammetry", "Drone Photogrammetry"
        SENSOR = "sensor", "Sensor"

    class ConditionState(models.TextChoices):
        CS1 = "CS1", "Sangat Baik"
        CS2 = "CS2", "Baik"
        CS3 = "CS3", "Sedang"
        CS4 = "CS4", "Buruk"
        CS5 = "CS5", "Gagal / Kritis"

    component = models.ForeignKey(AssetComponent, on_delete=models.PROTECT, related_name="inspection_records")
    inspector = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="inspections_performed")
    inspected_at = models.DateTimeField()
    method = models.CharField(max_length=32, choices=Method.choices)
    condition_state = models.CharField(max_length=3, choices=ConditionState.choices, null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    photo_refs = models.JSONField(default=list, blank=True)
    supersedes = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="superseded_by"
    )

    objects = OrganizationScopedManager(organization_lookup="component__asset__organization_id")

    class Meta:
        db_table = "inspections_record"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(method="sensor", condition_state__isnull=True)
                    | (~models.Q(method="sensor") & models.Q(condition_state__isnull=False))
                ),
                name="inspection_condition_state_null_iff_sensor_method",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and InspectionRecord.objects.filter(pk=self.pk).exists():
            raise ValueError(
                "InspectionRecord bersifat immutable (engineering-rules.md §1) — "
                "buat row baru dengan supersedes=<record ini>, jangan edit row ini."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError(
            "InspectionRecord tidak pernah bisa dihapus, bahkan soft delete "
            "(database.md §1, engineering-rules.md §1)."
        )

    def __str__(self):
        return f"{self.component} @ {self.inspected_at:%Y-%m-%d} ({self.condition_state or self.method})"
