"""
visualization.md §5 -- test Gantt chart + budget allocation chart data
service (Fase 2). Pola sama test_services_scheduling.py: fixture DB
asli, solve() CP-SAT sungguhan (bukan mock), hand-computed expected
value untuk budget flat allocation.
"""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from apps.assets.models import Asset, AssetComponent
from apps.core.models import Organization
from apps.deterioration.models import DegradationForecast, DeteriorationModel
from apps.maintenance.models import MaintenanceIntervention, MaintenancePlan
from apps.maintenance.services_chart import MaintenanceBudgetChartService, MaintenanceGanttChartService
from apps.maintenance.services_scheduling import MaintenanceOptimizationService


@pytest.fixture
def org():
    return Organization.objects.create(name="Dinas PU Test Chart")


@pytest.fixture
def optimized_plan(org):
    asset = Asset.objects.create(
        organization=org, code="BRG-CHART-1", name="Jembatan Chart Test",
        asset_type=Asset.AssetType.BRIDGE, latitude=Decimal("0"), longitude=Decimal("0"),
        construction_year=2000, design_life_years=50,
        importance_weight=Decimal("5.00"), status="active",
    )
    component = AssetComponent.objects.create(
        asset=asset, component_type="pier", criticality_weight=Decimal("1.000"),
    )
    model = DeteriorationModel.objects.create(
        component=component, model_type="discrete_markov", parameters={},
        fitted_at=datetime.now(timezone.utc), model_version=1,
        training_data_hash="test-hash-chart",
    )
    DegradationForecast.objects.create(
        model=model, forecast_year=datetime.now().year,
        state_probabilities={"CS1": 0.0, "CS2": 0.0, "CS3": 0.0, "CS4": 1.0, "CS5": 0.0},
        expected_state="CS4", confidence_width=None,
    )
    MaintenanceIntervention.objects.create(
        asset_type="bridge", intervention_type="major",
        name="Perbaikan Pier Major (Chart Test)", unit_cost=Decimal("30000000.00"),
        state_improvement={"CS4": "CS2"}, duration_days=60, min_interval_years=5,
    )
    # Horizon 4 tahun, budget flat -- hand-computed: 120.000.000 / 4 = 30.000.000
    plan = MaintenancePlan.objects.create(
        organization=org, name="Rencana Chart Test",
        budget_total=Decimal("120000000.00"), planning_horizon_years=4, status="draft",
    )
    run = MaintenanceOptimizationService().solve(plan.id)
    assert run.status in ("optimal", "feasible")
    plan.refresh_from_db()
    return plan, run, component, asset


@pytest.mark.django_db
class TestMaintenanceGanttChartService:
    def test_gantt_data_matches_schedule_rows(self, optimized_plan):
        plan, run, component, asset = optimized_plan
        data = MaintenanceGanttChartService().get_gantt_data(plan.organization_id, run.id)

        assert data["run_id"] == run.id
        assert data["plan_id"] == plan.id
        assert len(data["rows"]) == 1

        row = data["rows"][0]
        assert row["component_id"] == component.id
        assert row["component_label"] == f"{asset.name} — {component.component_type}"
        assert row["intervention_name"] == "Perbaikan Pier Major (Chart Test)"
        # duration_days=60 -> 60/365 dibulatkan 2 desimal
        assert row["duration_years"] == round(60 / 365.0, 2)
        assert row["cost"] == Decimal("30000000.00")
        assert row["expected_state_after"] == "CS2"


@pytest.mark.django_db
class TestMaintenanceBudgetChartService:
    def test_budget_data_flat_allocation_hand_computed(self, optimized_plan):
        plan, run, component, asset = optimized_plan
        data = MaintenanceBudgetChartService().get_budget_data(plan.organization_id, run.id)

        assert data["run_id"] == run.id
        assert len(data["years"]) == 4  # planning_horizon_years=4

        # Hand-computed: budget_total NULL profile -> flat 120.000.000/4 = 30.000.000
        expected_flat_budget = Decimal("120000000.00") / 4
        for year_entry in data["years"]:
            assert year_entry["budget"] == expected_flat_budget

        # Tahun anchor (run.solved_at.year) harus punya allocated_cost = cost
        # dari schedule row (30.000.000), tahun lain 0.
        anchor_year = run.solved_at.year
        anchor_entry = next(y for y in data["years"] if y["year"] == anchor_year)
        assert anchor_entry["allocated_cost"] == Decimal("30000000.00")

        other_entries = [y for y in data["years"] if y["year"] != anchor_year]
        assert len(other_entries) == 3
        for entry in other_entries:
            assert entry["allocated_cost"] == Decimal("0.00")

    def test_budget_data_uses_custom_budget_profile(self, optimized_plan):
        """scheduling.md §3.1: budget_profile custom per-tahun -- tahun
        tanpa key dianggap 0 (paling aman), BUKAN fallback flat."""
        plan, run, component, asset = optimized_plan
        anchor_year = run.solved_at.year

        plan.budget_profile = {str(anchor_year): "50000000.00"}
        plan.save(update_fields=["budget_profile"])

        data = MaintenanceBudgetChartService().get_budget_data(plan.organization_id, run.id)

        anchor_entry = next(y for y in data["years"] if y["year"] == anchor_year)
        assert anchor_entry["budget"] == Decimal("50000000.00")

        # Tahun lain TIDAK ada di budget_profile -> harus 0, bukan flat share.
        other_entries = [y for y in data["years"] if y["year"] != anchor_year]
        for entry in other_entries:
            assert entry["budget"] == Decimal("0")
