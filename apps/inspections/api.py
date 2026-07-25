from uuid import UUID

from ninja import Router

from apps.assets.api import _current_org_stub

from .schemas import InspectionRecordIn, InspectionRecordOut
from .services import InspectionService

router = Router(tags=["inspections"])
inspection_service = InspectionService()


@router.get("/component/{component_id}/", response=list[InspectionRecordOut])
def list_inspections(request, component_id: UUID):
    org_id = _current_org_stub(request)
    return inspection_service.list_for_component(org_id, component_id)


@router.post("/", response=InspectionRecordOut)
def create_inspection(request, payload: InspectionRecordIn):
    org_id = _current_org_stub(request)
    return inspection_service.create(org_id, payload.dict())
