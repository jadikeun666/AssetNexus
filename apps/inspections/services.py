from uuid import UUID

from django.shortcuts import get_object_or_404

from apps.assets.models import AssetComponent

from .models import InspectionRecord


class InspectionService:
    """architecture.md §3. Hanya create + list/get — TIDAK ADA method
    update (engineering-rules.md §1: InspectionRecord append-only)."""

    def list_for_component(self, organization_id: UUID, component_id: UUID):
        return InspectionRecord.objects.for_organization(organization_id).filter(
            component_id=component_id
        ).order_by("-inspected_at")

    def create(self, organization_id: UUID, data: dict) -> InspectionRecord:
        component = get_object_or_404(
            AssetComponent.objects.for_organization(organization_id), id=data["component_id"]
        )
        return InspectionRecord.objects.create(
            component=component,
            inspector_id=data["inspector_id"],
            inspected_at=data["inspected_at"],
            method=data["method"],
            condition_state=data.get("condition_state"),
            notes=data.get("notes", ""),
            photo_refs=data.get("photo_refs", []),
            supersedes_id=data.get("supersedes_id"),
        )
