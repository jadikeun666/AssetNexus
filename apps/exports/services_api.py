from uuid import UUID

from .jobs import generate_pdf_export_job
from .models import ExportJob


class ExportJobService:
    """architecture.md §3: router hanya panggil method ini, tidak
    orchestrate langsung (dispatch job ada di sini, bukan di router)."""

    def request_pdf_inspection(self, component_id: UUID, requested_by) -> ExportJob:
        job = ExportJob.objects.create(
            export_type=ExportJob.ExportType.PDF_INSPECTION,
            reference_id=component_id,
            requested_by=requested_by,
        )
        generate_pdf_export_job.send(str(job.id))
        return job

    def request_pdf_maintenance_plan(self, plan_id: UUID, requested_by) -> ExportJob:
        """exports.md §1: dipicu pada MaintenancePlan berstatus optimized/approved.
        Validasi status di sini (bukan di service render) supaya request jelas
        ditolak SEBELUM job async dibuat -- exports.md §5 tidak pernah silent
        failure, dan menolak lebih awal lebih baik daripada job gagal di worker."""
        from apps.maintenance.models import MaintenancePlan

        plan = MaintenancePlan.objects.get(id=plan_id)
        if plan.status not in (MaintenancePlan.Status.OPTIMIZED, MaintenancePlan.Status.APPROVED):
            raise ValueError(
                f"MaintenancePlan {plan_id} berstatus '{plan.status}' -- "
                f"pdf_maintenance_plan hanya bisa di-generate untuk plan "
                f"berstatus optimized/approved (exports.md §1)."
            )

        job = ExportJob.objects.create(
            export_type=ExportJob.ExportType.PDF_MAINTENANCE_PLAN,
            reference_id=plan_id,
            requested_by=requested_by,
        )
        generate_pdf_export_job.send(str(job.id))
        return job

    def get_status(self, job_id: UUID) -> ExportJob:
        from django.shortcuts import get_object_or_404
        return get_object_or_404(ExportJob, id=job_id)
