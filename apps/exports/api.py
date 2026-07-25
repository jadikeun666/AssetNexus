from uuid import UUID

from ninja import Router

from apps.assets.api import _current_org_stub

from .schemas import ExportJobOut, ExportJobRequestIn, PdfMaintenancePlanRequestIn
from .services_api import ExportJobService

router = Router(tags=["exports"])
service = ExportJobService()


@router.post("/pdf-inspection/", response=ExportJobOut)
def request_pdf_inspection(request, payload: ExportJobRequestIn):
    _current_org_stub(request)  # guard org context tervalidasi, meski belum dipakai filter di sini
    return service.request_pdf_inspection(payload.component_id, requested_by=None)


@router.post("/pdf-maintenance-plan/", response=ExportJobOut)
def request_pdf_maintenance_plan(request, payload: PdfMaintenancePlanRequestIn):
    _current_org_stub(request)
    return service.request_pdf_maintenance_plan(payload.plan_id, requested_by=None)


@router.get("/{job_id}/", response=ExportJobOut)
def get_export_status(request, job_id: UUID):
    _current_org_stub(request)
    return service.get_status(job_id)
