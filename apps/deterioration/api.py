"""
architecture.md §3: router tipis — satu call service per endpoint.

Endpoint pertama app deterioration yang diekspos lewat REST (sebelumnya
murni event-driven via jobs.py). Scope sesi ini HANYA chart condition
trend line (visualization.md §5) — bukan endpoint umum CRUD untuk
DeteriorationModel/DegradationForecast.
"""
from uuid import UUID

from ninja import Router

from apps.assets.api import _current_org_stub

from .schemas import ComponentForecastChartOut
from .services_chart import ComponentForecastChartService

router = Router(tags=["deterioration"])
chart_service = ComponentForecastChartService()


@router.get("/components/{component_id}/forecast-chart/", response=ComponentForecastChartOut)
def get_component_forecast_chart(request, component_id: UUID):
    org_id = _current_org_stub(request)
    return chart_service.get_chart_data(org_id, component_id)
