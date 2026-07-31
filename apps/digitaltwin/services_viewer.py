"""
visualization.md §4.1: payload viewer {component_id: {year: condition_score}},
di-fetch SEKALI per asset dan di-cache client-side untuk scrubbing halus --
bukan query per-tahun.

Reuse ComponentForecastChartService (apps/deterioration/services_chart.py,
Fase 1) APA ADANYA -- tidak menduplikasi logic pemilihan "model aktif"
(exclude fuzzy_markov) atau konversi CS->condition_score (centroid()).
Ini cross-app read query, BUKAN orkestrasi side-effect sinkron yang
dilarang engineering-rules.md §6 -- architecture.md §3 eksplisit
mendaftarkan digitaltwin bergantung pada deterioration untuk "viewer
data API". Jaminan penting: angka condition_score di viewer 3D dan di
chart 2D (visualization.md §4.3) SELALU identik karena sumbernya satu
service yang sama, bukan dua implementasi paralel yang bisa drift.
"""
from __future__ import annotations

import uuid

from django.shortcuts import get_object_or_404

from apps.assets.models import Asset, AssetComponent
from apps.deterioration.services_chart import ComponentForecastChartService

from .models import DigitalTwinModel


class DigitalTwinViewerPayloadService:
    """Query read-only untuk payload viewer 3D. Tidak pernah menulis ke
    database."""

    def __init__(self) -> None:
        self._chart_service = ComponentForecastChartService()

    def get_viewer_payload(self, organization_id: uuid.UUID, asset_id: uuid.UUID) -> dict:
        asset = get_object_or_404(
            Asset.objects.for_organization(organization_id),
            id=asset_id,
            deleted_at__isnull=True,
        )

        # visualization.md §1, database.md §6: version tertinggi = model
        # aktif viewer, keputusan disepakati eksplisit product owner sesi
        # ini (pola sama DeteriorationModel.model_version).
        digital_twin_model = (
            DigitalTwinModel.objects.filter(asset=asset).order_by("-version").first()
        )

        components = AssetComponent.objects.filter(
            asset=asset, deleted_at__isnull=True
        )

        # visualization.md §1: component_type disertakan eksplisit (bukan
        # cuma component_id) -- join key ke node glTF adalah component_type,
        # frontend butuh tahu nama itu untuk mencocokkan node (schemas.py
        # ComponentForecastOut, keputusan disepakati eksplisit product
        # owner, langkah 4d).
        forecast_by_component = []
        for component in components:
            chart_data = self._chart_service.get_chart_data(
                organization_id=organization_id, component_id=component.id
            )
            year_scores = {
                str(point["forecast_year"]): point["condition_score"]
                for point in chart_data["points"]
            }
            forecast_by_component.append(
                {
                    "component_id": component.id,
                    "component_type": component.component_type,
                    "year_scores": year_scores,
                }
            )

        return {
            "asset_id": asset.id,
            "digital_twin_model": (
                {
                    "id": digital_twin_model.id,
                    "file_ref": digital_twin_model.file_ref,
                    "version": digital_twin_model.version,
                }
                if digital_twin_model is not None
                else None
            ),
            "forecast_by_component": forecast_by_component,
        }
