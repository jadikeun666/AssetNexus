"""
architecture.md §3: logic bisnis di Service, bukan router. Manajemen
SensorDevice -- registrasi & listing, mengikuti pola AssetComponentService
(apps/assets/services.py) persis: org-scoping via for_organization(),
FK parent (component) divalidasi org-scoped SEBELUM create.
"""
from uuid import UUID

from django.shortcuts import get_object_or_404

from apps.assets.models import AssetComponent

from .models import AnomalyEvent, SensorDevice


class SensorDeviceService:
    def create(self, organization_id: UUID, created_by, data: dict) -> SensorDevice:
        component = get_object_or_404(
            AssetComponent.objects.for_organization(organization_id),
            id=data["component_id"],
            deleted_at__isnull=True,
        )
        return SensorDevice.objects.create(
            component=component,
            device_type=data["device_type"],
            install_date=data["install_date"],
            created_by=created_by,
        )

    def list_for_organization(self, organization_id: UUID):
        return SensorDevice.objects.for_organization(organization_id).filter(
            deleted_at__isnull=True
        )

    def get(self, organization_id: UUID, device_id: UUID) -> SensorDevice:
        return get_object_or_404(
            SensorDevice.objects.for_organization(organization_id),
            id=device_id,
            deleted_at__isnull=True,
        )


class AnomalyEventService:
    """
    engineering-rules.md §2: read-only dari API perspective -- AnomalyEvent
    dibuat lewat pipeline deteksi (langkah c/d, belum ditulis), bukan lewat
    endpoint create manual. Service ini baru menyediakan listing untuk
    sekarang.
    """

    def list_for_device(self, organization_id: UUID, device_id: UUID):
        return AnomalyEvent.objects.for_organization(organization_id).filter(
            device_id=device_id, deleted_at__isnull=True
        ).order_by("-detected_at")
