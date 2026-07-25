import dramatiq

from apps.assets.models import AssetComponent

from .models import ExportJob
from .services import InspectionPdfService


@dramatiq.actor(max_retries=1)  # exports.md §5: "retry once automatically"
def generate_pdf_export_job(export_job_id: str):
    """architecture.md §4: ExportRequested -> GeneratePdfExportJob.
    Never runs synchronously in the request/response cycle (exports.md §5)."""
    job = ExportJob.objects.get(id=export_job_id)
    job.status = ExportJob.Status.PROCESSING
    job.save(update_fields=["status"])

    try:
        if job.export_type != ExportJob.ExportType.PDF_INSPECTION:
            raise NotImplementedError(
                f"{job.export_type} belum diimplementasi — hanya pdf_inspection di Fase 0."
            )
        component = AssetComponent.objects.get(id=job.reference_id)
        file_ref = InspectionPdfService().render_and_store(component, job.id)

        job.status = ExportJob.Status.DONE
        job.file_ref = file_ref
        job.save(update_fields=["status", "file_ref"])
    except Exception as exc:
        # exports.md §5: "never a silent failure"
        job.status = ExportJob.Status.FAILED
        job.failure_reason = str(exc)
        job.save(update_fields=["status", "failure_reason"])
        raise
