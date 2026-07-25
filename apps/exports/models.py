from django.db import models

from apps.core.models import BaseModel


class ExportJob(BaseModel):
    """database.md §6. Setiap export adalah audit record — exports.md §4:
    "who exported what, when" queryable langsung dari sini."""

    class ExportType(models.TextChoices):
        PDF_INSPECTION = "pdf_inspection", "Laporan Inspeksi (PDF)"
        PDF_MAINTENANCE_PLAN = "pdf_maintenance_plan", "Rencana Pemeliharaan (PDF)"  # Fase 2
        EXCEL_SCHEDULE = "excel_schedule", "Jadwal Pemeliharaan (Excel)"              # Fase 2
        EXCEL_INVENTORY = "excel_inventory", "Inventaris Aset (Excel)"                # Fase 2

    class Status(models.TextChoices):
        QUEUED = "queued", "Antre"
        PROCESSING = "processing", "Diproses"
        DONE = "done", "Selesai"
        FAILED = "failed", "Gagal"

    export_type = models.CharField(max_length=32, choices=ExportType.choices)
    reference_id = models.UUIDField(help_text="Points to the Asset/Component/Plan being exported.")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    file_ref = models.CharField(max_length=500, null=True, blank=True, help_text="SeaweedFS object key, NULL until done.")
    requested_by = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="export_jobs")
    failure_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "exports_job"
        indexes = [
            models.Index(fields=["reference_id", "export_type"]),
        ]

    def __str__(self):
        return f"{self.export_type} @ {self.reference_id} ({self.status})"
