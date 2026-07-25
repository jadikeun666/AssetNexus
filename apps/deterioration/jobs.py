import dramatiq

from apps.assets.models import AssetComponent
from apps.inspections.models import InspectionRecord

from config.assetnexus import DETERIORATION

from .services import DiscreteMarkovFittingService, ForecastService
from .services_ctmc import CTMCDatasetCollector, CTMCForecastService, CTMCLatentFittingService
from .services_fuzzy import FuzzyBoundsService


@dramatiq.actor(max_retries=3)
def recalculate_deterioration_job(component_id: str):
    """
    architecture.md §4: InspectionRecorded -> RecalculateDeteriorationJob.

    Fase 1: cabang penuh sesuai TODO yang ditinggalkan eksplisit sejak
    Fase 0 -- inspection_count >= MIN_INSPECTIONS_FOR_CTMC memakai jalur
    CTMC latent-regime + fuzzy bounds (formulas.md §2-3); di bawah ambang
    itu tetap DTMC baseline (formulas.md §1, prd.md §9 "graceful
    degradation"). KEDUANYA tidak pernah dijalankan untuk komponen yang
    sama pada satu invocation job ini -- begitu ambang tercapai, DTMC
    tidak lagi dipakai untuk forecast component tsb (meski secara skema
    keduanya BISA koeksis tanpa bentrok versioning, lihat fix global-
    per-component di DiscreteMarkovFittingService.fit(), menjalankan DTMC
    yang tidak dipakai forecast utama adalah kerja sia-sia).
    """
    component = AssetComponent.objects.select_related("asset").get(id=component_id)

    inspection_count = InspectionRecord.objects.filter(
        component=component, condition_state__isnull=False
    ).count()

    latest_state = (
        InspectionRecord.objects.filter(component=component, condition_state__isnull=False)
        .order_by("-inspected_at")
        .values_list("condition_state", flat=True)
        .first()
    )
    if not latest_state:
        return  # Tidak ada inspeksi ber-condition_state -- tidak ada yang bisa di-fit/forecast.

    organization_id = component.asset.organization_id
    asset_type = component.asset.asset_type
    component_type = component.component_type

    if inspection_count >= DETERIORATION["MIN_INSPECTIONS_FOR_CTMC"]:
        # Jalur CTMC + fuzzy bounds (formulas.md §2-3).
        ctmc_model = CTMCLatentFittingService().fit(
            organization_id=organization_id,
            asset_type=asset_type,
            component_type=component_type,
            component=component,
        )
        histories = CTMCDatasetCollector().collect(organization_id, asset_type, component_type)
        fuzzy_model = FuzzyBoundsService().fit(ctmc_model, histories)

        forecasts = CTMCForecastService().generate(ctmc_model, current_state=latest_state)

        fuzzy_service = FuzzyBoundsService()
        for forecast in forecasts:
            fuzzy_service.annotate_forecast_confidence_width(
                forecast, fuzzy_model, current_state=latest_state
            )
    else:
        # Jalur DTMC baseline (formulas.md §1) -- di bawah ambang CTMC.
        model = DiscreteMarkovFittingService().fit(
            organization_id=organization_id,
            asset_type=asset_type,
            component_type=component_type,
            component=component,
        )
        ForecastService().generate(model, current_state=latest_state)
