from uuid import UUID

from ninja import Router
from ninja.errors import HttpError

from .schemas import AssetComponentIn, AssetComponentOut, AssetIn, AssetOut
from .services import AssetComponentService, AssetService

router = Router(tags=["assets"])

asset_service = AssetService()
component_service = AssetComponentService()


def _current_org_stub(request) -> UUID:
    """
    SEMENTARA untuk Fase 0. Implementasi asli membaca klaim organisasi
    dari token OIDC Keycloak yang sudah tervalidasi (engineering-rules.md
    §8). Ganti saat "Keycloak realm setup" selesai.
    """
    org_header = request.headers.get("X-Organization-Id")
    if not org_header:
        raise HttpError(401, "Missing X-Organization-Id (auth stub — lihat _current_org_stub)")
    return UUID(org_header)


@router.get("/", response=list[AssetOut])
def list_assets(request):
    org_id = _current_org_stub(request)
    return asset_service.list_for_organization(org_id)


@router.get("/{asset_id}", response=AssetOut)
def get_asset(request, asset_id: UUID):
    org_id = _current_org_stub(request)
    return asset_service.get(org_id, asset_id)


@router.post("/", response=AssetOut)
def create_asset(request, payload: AssetIn):
    org_id = _current_org_stub(request)
    return asset_service.create(org_id, created_by=None, data=payload.dict())


@router.post("/components/", response=AssetComponentOut)
def create_component(request, payload: AssetComponentIn):
    org_id = _current_org_stub(request)
    return component_service.create(org_id, created_by=None, data=payload.dict())


@router.get("/{asset_id}/components/", response=list[AssetComponentOut])
def list_components(request, asset_id: UUID):
    org_id = _current_org_stub(request)
    return component_service.list_for_asset(org_id, asset_id)
