"""
Service query untuk chart condition trend line (visualization.md §5).

MURNI membaca data yang sudah dihasilkan fitting service (services.py,
services_ctmc.py, services_fuzzy.py) — tidak mengubah logic komputasi
apa pun di file-file itu (batasan eksplisit sesi ini).

Sumber "model aktif" per komponen: DeteriorationModel dengan model_version
tertinggi, TAPI exclude model_type='fuzzy_markov' dari kandidat -- fuzzy_markov
tidak pernah punya DegradationForecast sendiri (forecast dibuat terikat ke
ctmc_latent oleh CTMCForecastService.generate(), lalu confidence_width-nya
di-annotate in-place oleh FuzzyBoundsService.annotate_forecast_confidence_width(),
lihat jobs.py:50-64). Kalau fuzzy_markov ikut jadi kandidat, model_version
tertinggi akan salah pilih row yang forecast-nya kosong -- ini sempat jadi
bug di draf pertama service ini sebelum diverifikasi lewat test_jobs.py.
Setelah exclude fuzzy_markov, sisa kandidat tinggal discrete_markov ATAU
ctmc_latent -- keduanya tidak pernah hidup berdampingan untuk komponen yang
sama (routing jobs.py menjamin ini), jadi model_version tertinggi dari
sisa kandidat sudah pasti model yang tepat untuk chart.

Scoping organisasi (engineering-rules.md §8): AssetComponent.objects sudah
dikonfigurasi OrganizationScopedManager(organization_lookup=
"asset__organization_id") — pola sama dengan AssetService.get(), pakai
for_organization() + get_object_or_404, bukan .objects.get() polos (celah
lintas-organisasi kalau tidak discope).

Band confidence disimetriskan dari confidence_width tunggal (keputusan
disepakati eksplisit dengan product owner sesi ini — lihat schemas.py
untuk rasionalisasi lengkap kenapa bukan asimetris/centroid_upper-lower
asli).
"""
from __future__ import annotations

import uuid

from django.shortcuts import get_object_or_404

from apps.assets.models import AssetComponent

from .models import DeteriorationModel
from .services_fuzzy import CentroidDefuzzificationService


class ComponentForecastChartService:
    """Query read-only untuk payload chart condition trend line
    (visualization.md §5). Tidak pernah menulis ke database."""

    def __init__(self) -> None:
        self._centroid_service = CentroidDefuzzificationService()

    def get_chart_data(self, organization_id: uuid.UUID, component_id: uuid.UUID) -> dict:
        component = get_object_or_404(
            AssetComponent.objects.for_organization(organization_id),
            id=component_id,
            deleted_at__isnull=True,
        )

        model = (
            DeteriorationModel.objects.filter(component=component)
            # fuzzy_markov TIDAK PERNAH punya DegradationForecast sendiri --
            # forecast dibuat terikat ke ctmc_latent oleh CTMCForecastService,
            # lalu confidence_width-nya di-annotate in-place (jobs.py:57-64,
            # services_fuzzy.py:annotate_forecast_confidence_width). Kalau
            # fuzzy_markov ikut dipertimbangkan di sini, model_version
            # tertinggi akan salah pilih row yang forecast-nya kosong.
            .exclude(model_type=DeteriorationModel.ModelType.FUZZY_MARKOV)
            .order_by("-model_version")
            .first()
        )

        if model is None:
            # Edge case: komponen ada tapi belum pernah difit sama sekali
            # (belum cukup InspectionRecord untuk memicu RecalculateDeteriorationJob).
            # Tidak error keras -- tampilkan chart kosong, bukan 404/500,
            # supaya frontend bisa render "belum ada forecast" secara graceful.
            return {
                "component_id": component.id,
                "component_type": component.component_type,
                "model_type": "",
                "model_version": 0,
                "points": [],
            }

        forecasts = model.forecasts.order_by("forecast_year")

        points = []
        for forecast in forecasts:
            condition_score = self._centroid_service.centroid(forecast.state_probabilities)

            confidence_lower = None
            confidence_upper = None
            if forecast.confidence_width is not None:
                # DTMC (discrete_markov) tidak pernah mengisi confidence_width
                # -- tetap None di sini, bukan 0.0 (0.0 berarti "band pasti
                # sempit", bukan "band tidak diketahui").
                half_width = float(forecast.confidence_width) / 2.0
                confidence_lower = condition_score - half_width
                confidence_upper = condition_score + half_width

            points.append(
                {
                    "forecast_year": forecast.forecast_year,
                    "condition_score": condition_score,
                    "confidence_lower": confidence_lower,
                    "confidence_upper": confidence_upper,
                }
            )

        return {
            "component_id": component.id,
            "component_type": component.component_type,
            "model_type": model.model_type,
            "model_version": model.model_version,
            "points": points,
        }
