from uuid import UUID

from django.shortcuts import get_object_or_404

from .models import Asset, AssetComponent


class AssetService:
    """architecture.md §3: logic bisnis di sini, tidak pernah di router."""

    def list_for_organization(self, organization_id: UUID):
        return Asset.objects.for_organization(organization_id).filter(deleted_at__isnull=True)

    def get(self, organization_id: UUID, asset_id: UUID) -> Asset:
        return get_object_or_404(
            Asset.objects.for_organization(organization_id), id=asset_id, deleted_at__isnull=True
        )

    def create(self, organization_id: UUID, created_by, data: dict) -> Asset:
        return Asset.objects.create(organization_id=organization_id, created_by=created_by, **data)


class AssetComponentService:
    def create(self, organization_id: UUID, created_by, data: dict) -> AssetComponent:
        asset = get_object_or_404(
            Asset.objects.for_organization(organization_id), id=data["asset_id"]
        )
        return AssetComponent.objects.create(
            asset=asset,
            parent_component_id=data.get("parent_component_id"),
            component_type=data["component_type"],
            criticality_weight=data["criticality_weight"],
            created_by=created_by,
        )

    def list_for_asset(self, organization_id: UUID, asset_id: UUID):
        return AssetComponent.objects.for_organization(organization_id).filter(
            asset_id=asset_id, deleted_at__isnull=True
        )
