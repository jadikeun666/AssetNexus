"""
architecture.md par.3: router tipis -- satu call service per endpoint.
scheduling.md par.5: trigger optimasi TIDAK sinkron (dispatch job via
.send(), bukan menjalankan solve() langsung di request thread).
"""
from uuid import UUID

from ninja import Router

from apps.assets.api import _current_org_stub

from .schemas import (
    BudgetChartOut,
    GanttChartOut,
    MaintenancePlanIn,
    MaintenancePlanOut,
    MaintenanceScheduleOut,
    OptimizationRunOut,
)
from .services_api import MaintenanceOptimizationRunService, MaintenancePlanService
from .services_chart import MaintenanceBudgetChartService, MaintenanceGanttChartService

router = Router(tags=["maintenance"])
plan_service = MaintenancePlanService()
run_service = MaintenanceOptimizationRunService()
gantt_chart_service = MaintenanceGanttChartService()
budget_chart_service = MaintenanceBudgetChartService()


@router.post("/plans/", response=MaintenancePlanOut)
def create_plan(request, payload: MaintenancePlanIn):
    org_id = _current_org_stub(request)
    return plan_service.create(org_id, created_by=None, data=payload.dict())


@router.get("/plans/", response=list[MaintenancePlanOut])
def list_plans(request):
    org_id = _current_org_stub(request)
    return plan_service.list_for_organization(org_id)


@router.get("/plans/{plan_id}/", response=MaintenancePlanOut)
def get_plan(request, plan_id: UUID):
    org_id = _current_org_stub(request)
    return plan_service.get(org_id, plan_id)


@router.post("/plans/{plan_id}/optimize/", response=MaintenancePlanOut)
def trigger_optimization(request, plan_id: UUID):
    org_id = _current_org_stub(request)
    return run_service.trigger(org_id, plan_id)


@router.get("/plans/{plan_id}/latest-run/", response=OptimizationRunOut)
def get_latest_run(request, plan_id: UUID):
    org_id = _current_org_stub(request)
    return run_service.get_latest_run(org_id, plan_id)


@router.get("/runs/{run_id}/schedule/", response=list[MaintenanceScheduleOut])
def get_run_schedule(request, run_id: UUID):
    org_id = _current_org_stub(request)
    return run_service.list_schedule_for_run(org_id, run_id)


# visualization.md §5 -- Gantt chart + budget allocation chart data.
# Read-only query service, pola sama apps/deterioration/api.py yang
# memanggil ComponentForecastChartService langsung tanpa lewat
# services_api.py (tidak ada orkestrasi/side-effect untuk endpoint ini).

@router.get("/runs/{run_id}/gantt-chart/", response=GanttChartOut)
def get_gantt_chart(request, run_id: UUID):
    org_id = _current_org_stub(request)
    return gantt_chart_service.get_gantt_data(org_id, run_id)


@router.get("/runs/{run_id}/budget-chart/", response=BudgetChartOut)
def get_budget_chart(request, run_id: UUID):
    org_id = _current_org_stub(request)
    return budget_chart_service.get_budget_data(org_id, run_id)
