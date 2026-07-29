"""
architecture.md §3: router tipis -- satu call service per endpoint.
Endpoint pertama app digitaltwin (Fase 3, prd.md §8): upload glTF
(visualization.md §1) dan payload viewer (visualization.md §4.1).
"""
from uuid import UUID

from django.shortcuts import get_object_or_404
from ninja import File, Form, Router
from ninja.errors import HttpError
from ninja.files import UploadedFile

from apps.assets.api import _current_org_stub
from apps.assets.models import Asset
from apps.digitaltwin.services import DigitalTwinUploadService
from apps.digitaltwin.services_validation import InvalidGltfError, TriangleCountExceededError
from apps.digitaltwin.services_viewer import DigitalTwinViewerPayloadService

from .schemas import DigitalTwinUploadOut, ViewerPayloadOut

router = Router(tags=["digitaltwin"])

upload_service = DigitalTwinUploadService()
viewer_service = DigitalTwinViewerPayloadService()


@router.post("/assets/{asset_id}/upload/", response=DigitalTwinUploadOut)
def upload_digital_twin_model(
    request,
    asset_id: UUID,
    source: str = Form(...),
    file: UploadedFile = File(...),
):
    """
    visualization.md §1: Analyst/Admin upload .glb -> divalidasi
    (triangle count, visualization.md §7) -> SeaweedFS -> DigitalTwinModel.
    Reject eksplisit (400), bukan 500 diam-diam, untuk mesh invalid/
    kelebihan triangle -- visualization.md §7: "rejected at upload time
    with a clear error". created_by=None aman di sini (BEDA dari
    ExportJob.requested_by yang non-nullable, Fase 2) -- BaseModel.created_by
    sudah null=True/blank=True; None berarti "belum ada Keycloak realm",
    sama seperti stub org header.
    """
    org_id = _current_org_stub(request)
    asset = get_object_or_404(
        Asset.objects.for_organization(org_id), id=asset_id, deleted_at__isnull=True
    )

    data = file.read()

    try:
        model = upload_service.upload(
            asset=asset, data=data, source=source, created_by=None,
        )
    except TriangleCountExceededError as exc:
        raise HttpError(400, str(exc))
    except InvalidGltfError as exc:
        raise HttpError(400, str(exc))

    return {
        "id": model.id,
        "asset_id": model.asset_id,
        "file_ref": model.file_ref,
        "version": model.version,
    }


@router.get("/assets/{asset_id}/viewer-payload/", response=ViewerPayloadOut)
def get_viewer_payload(request, asset_id: UUID):
    """visualization.md §4.1: payload sekali-fetch per asset untuk
    timeline scrubber -- di-cache client-side, bukan query per-tahun."""
    org_id = _current_org_stub(request)
    return viewer_service.get_viewer_payload(org_id, asset_id)
