"""
scheduling.md — test CP-SAT maintenance optimization service (Fase 2).

engineering-rules.md §7: setiap formula punya test dengan hand-computed
expected value (bukan cuma "jalan tanpa error"), plus minimal 1 skenario
deliberately infeasible.
"""
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal

import pytest

from apps.assets.models import Asset, AssetComponent
from apps.core.models import Organization
from apps.deterioration.models import DegradationForecast, DeteriorationModel
from apps.maintenance.models import (
    MaintenanceIntervention,
    MaintenancePlan,
    MaintenanceSchedule,
    OptimizationRun,
)
from apps.maintenance.services_scheduling import (
    ComponentInput,
    InterventionInput,
    MaintenanceCoefficientBuilder,
    MaintenanceOptimizationService,
    OptimizationInputs,
    build_and_solve,
)


# ---------------------------------------------------------------------------
# 1. build_and_solve() -- FUNGSI MURNI, hand-computed, tanpa DB.
# ---------------------------------------------------------------------------

class TestBuildAndSolveHandComputed:
    def test_single_component_single_intervention_optimal(self):
        """
        1 komponen forecast CS4 (probabilitas 1.0), 1 intervensi major
        CS4->CS2, budget cukup. Hand-computed:
          ΔD = P(CS4)=1.0 * (level(CS4)=4 - level(CS2)=2) = 2.0
          w_scaled = importance_weight(5.00) * objective_scale(10000) = 50000
          coeff = round(50000 * 2.0) = 100000
          objective_value = 100000 / objective_scale(10000) = 10.0
        Cost intervensi = 1000.00 * cost_scale(100) = 100000 sen <= budget
        200000 sen -- harus feasible dan x dipilih (satu-satunya cara
        mendapat objective positif).
        """
        component_id = "11111111-1111-1111-1111-111111111111"
        intervention_id = "22222222-2222-2222-2222-222222222222"

        inputs = OptimizationInputs(
            anchor_year=2027,
            horizon_years=1,
            components=[
                ComponentInput(
                    component_id=component_id,
                    asset_type="bridge",
                    importance_weight=Decimal("5.00"),
                    forecast_by_year={2027: {"CS4": 1.0}},
                    expected_state_by_year={2027: "CS4"},
                )
            ],
            interventions=[
                InterventionInput(
                    intervention_id=intervention_id,
                    asset_type="bridge",
                    intervention_type="major",
                    unit_cost=Decimal("1000.00"),
                    state_improvement={"CS4": "CS2"},
                    min_interval_years=5,
                )
            ],
            budget_cents_by_year={2027: 200000},
            cost_scale=100,
            objective_scale=10000,
            solver_time_limit_seconds=5,
        )

        result = build_and_solve(inputs)

        assert result.status == "optimal"
        assert result.objective_value == Decimal("10.0")
        assert len(result.schedule) == 1
        item = result.schedule[0]
        assert str(item.component_id) == component_id
        assert item.year == 2027
        assert str(item.intervention_id) == intervention_id
        assert item.cost == Decimal("1000.00")
        assert item.expected_state_after == "CS2"

    def test_budget_too_small_skips_intervention_but_stays_optimal(self):
        """
        Sama seperti di atas tapi budget SENGAJA di bawah cost intervensi
        (50000 sen < 100000 sen dibutuhkan) DAN komponen tidak forecast
        CS5 (jadi tidak ada mandatory floor §3.4 yang memaksa). Solver
        harus tetap OPTIMAL (trivial -- tidak menjadwalkan apa pun adalah
        solusi valid), objective_value = 0, schedule kosong -- BUKAN infeasible.
        """
        inputs = OptimizationInputs(
            anchor_year=2027,
            horizon_years=1,
            components=[
                ComponentInput(
                    component_id="11111111-1111-1111-1111-111111111111",
                    asset_type="bridge",
                    importance_weight=Decimal("5.00"),
                    forecast_by_year={2027: {"CS4": 1.0}},
                    expected_state_by_year={2027: "CS4"},
                )
            ],
            interventions=[
                InterventionInput(
                    intervention_id="22222222-2222-2222-2222-222222222222",
                    asset_type="bridge",
                    intervention_type="major",
                    unit_cost=Decimal("1000.00"),
                    state_improvement={"CS4": "CS2"},
                    min_interval_years=5,
                )
            ],
            budget_cents_by_year={2027: 50000},
            cost_scale=100,
            objective_scale=10000,
            solver_time_limit_seconds=5,
        )

        result = build_and_solve(inputs)

        assert result.status == "optimal"
        assert result.objective_value == Decimal("0")
        assert result.schedule == []


# ---------------------------------------------------------------------------
# 2. Skenario deliberately infeasible (engineering-rules.md §7, wajib ada).
# ---------------------------------------------------------------------------

class TestBuildAndSolveInfeasible:
    def test_cs5_forecast_with_no_major_intervention_available_is_infeasible(self):
        """
        scheduling.md §3.4: komponen forecast CS5 WAJIB dapat intervensi
        major/replacement. Kalau katalog TIDAK punya satu pun intervensi
        major/replacement untuk asset_type ini (cuma 'minor' tersedia),
        constraint mandatory floor tidak mungkin terpenuhi -- harus
        INFEASIBLE, bukan silam menjadwalkan yang minor atau kosong.
        """
        inputs = OptimizationInputs(
            anchor_year=2027,
            horizon_years=1,
            components=[
                ComponentInput(
                    component_id="11111111-1111-1111-1111-111111111111",
                    asset_type="bridge",
                    importance_weight=Decimal("5.00"),
                    forecast_by_year={2027: {"CS5": 1.0}},
                    expected_state_by_year={2027: "CS5"},
                )
            ],
            interventions=[
                InterventionInput(
                    intervention_id="33333333-3333-3333-3333-333333333333",
                    asset_type="bridge",
                    intervention_type="minor",  # BUKAN major/replacement
                    unit_cost=Decimal("100.00"),
                    state_improvement={"CS5": "CS4"},
                    min_interval_years=None,
                )
            ],
            budget_cents_by_year={2027: 1000000},
            cost_scale=100,
            objective_scale=10000,
            solver_time_limit_seconds=5,
        )

        result = build_and_solve(inputs)

        assert result.status == "infeasible"
        assert result.objective_value is None
        assert result.schedule == []

    def test_cs5_forecast_with_zero_budget_is_infeasible(self):
        """
        Variasi kedua: intervensi major TERSEDIA di katalog, tapi budget
        tahun itu 0 (mis. Manager menaruh budget_profile custom yang tidak
        mengalokasikan apa pun tahun itu -- Flag 1). Constraint §3.4 (wajib
        >=1 intervensi major) berbenturan dengan §3.1 (budget 0) -- harus
        INFEASIBLE, memverifikasi kedua constraint benar2 ditegakkan
        bersamaan, bukan salah satu diam2 dilonggarkan.
        """
        inputs = OptimizationInputs(
            anchor_year=2027,
            horizon_years=1,
            components=[
                ComponentInput(
                    component_id="11111111-1111-1111-1111-111111111111",
                    asset_type="bridge",
                    importance_weight=Decimal("5.00"),
                    forecast_by_year={2027: {"CS5": 1.0}},
                    expected_state_by_year={2027: "CS5"},
                )
            ],
            interventions=[
                InterventionInput(
                    intervention_id="22222222-2222-2222-2222-222222222222",
                    asset_type="bridge",
                    intervention_type="major",
                    unit_cost=Decimal("1000.00"),
                    state_improvement={"CS5": "CS3"},
                    min_interval_years=5,
                )
            ],
            budget_cents_by_year={2027: 0},
            cost_scale=100,
            objective_scale=10000,
            solver_time_limit_seconds=5,
        )

        result = build_and_solve(inputs)

        assert result.status == "infeasible"
        assert result.schedule == []


# ---------------------------------------------------------------------------
# 3. MaintenanceCoefficientBuilder -- verifikasi Flag 1 (budget_profile
#    tahun hilang -> 0) langsung dari DB.
# ---------------------------------------------------------------------------

@pytest.fixture
def org():
    return Organization.objects.create(name="Dinas PU Test Scheduling")


def _make_bridge(org, code, importance_weight="5.00"):
    return Asset.objects.create(
        organization=org, code=code, name=f"Bridge {code}", asset_type=Asset.AssetType.BRIDGE,
        latitude=Decimal("0"), longitude=Decimal("0"),
        importance_weight=Decimal(importance_weight),
    )


def _make_girder(asset):
    return AssetComponent.objects.create(
        asset=asset, component_type="girder", criticality_weight=Decimal("0.250"),
    )


def _make_model_with_forecast(component, forecast_years_states):
    """forecast_years_states: {year: (expected_state, {state: prob})}"""
    model = DeteriorationModel.objects.create(
        component=component,
        model_type=DeteriorationModel.ModelType.DISCRETE_MARKOV,
        parameters={},
        fitted_at=datetime(2027, 1, 1, tzinfo=dt_timezone.utc),
        model_version=1,
        training_data_hash="test-hash",
    )
    for year, (expected_state, probs) in forecast_years_states.items():
        DegradationForecast.objects.create(
            model=model, forecast_year=year,
            state_probabilities=probs, expected_state=expected_state,
        )
    return model


@pytest.mark.django_db
class TestMaintenanceCoefficientBuilder:
    def test_budget_profile_missing_year_defaults_to_zero(self, org):
        import datetime as dt
        current_year = dt.date.today().year  # anchor_year builder SELALU
        # tahun berjalan sungguhan (timezone.localdate().year) -- fixture
        # HARUS memakai tahun ini, bukan angka fixed, supaya forecast_year
        # ada di dalam years_range yang benar-benar dipakai builder.

        asset = _make_bridge(org, "SCHED-A")
        component = _make_girder(asset)
        _make_model_with_forecast(component, {current_year: ("CS3", {"CS3": 1.0})})

        other_year = current_year + 1
        plan = MaintenancePlan.objects.create(
            organization=org, name="Plan Budget Profile Test",
            budget_total=Decimal("1000000.00"), planning_horizon_years=1,
            budget_profile={str(other_year): "500000.00"},  # current_year SENGAJA tidak disebut
        )

        builder = MaintenanceCoefficientBuilder()
        inputs = builder.build(plan)

        assert current_year in inputs.budget_cents_by_year
        assert inputs.budget_cents_by_year[current_year] == 0  # tidak ada di
        # budget_profile -- Flag 1: default 0, bukan fallback flat.

    def test_budget_profile_year_present_is_used_directly(self, org):
        import datetime as dt
        current_year = dt.date.today().year

        asset = _make_bridge(org, "SCHED-B")
        component = _make_girder(asset)
        _make_model_with_forecast(component, {current_year: ("CS3", {"CS3": 1.0})})

        plan = MaintenancePlan.objects.create(
            organization=org, name="Plan Budget Profile Test 2",
            budget_total=Decimal("1000000.00"), planning_horizon_years=1,
            budget_profile={str(current_year): "750000.00"},
        )

        builder = MaintenanceCoefficientBuilder()
        inputs = builder.build(plan)

        assert inputs.budget_cents_by_year[current_year] == 75000000  # 750000.00 * 100 sen


# ---------------------------------------------------------------------------
# 4. MaintenanceOptimizationService -- end-to-end lewat database sungguhan.
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestMaintenanceOptimizationServiceIntegration:
    def test_end_to_end_optimal_writes_run_and_schedule(self, org):
        asset = _make_bridge(org, "SCHED-C", importance_weight="8.00")
        component = _make_girder(asset)

        import datetime as dt
        current_year = dt.date.today().year
        _make_model_with_forecast(
            component, {current_year: ("CS4", {"CS4": 1.0})}
        )

        MaintenanceIntervention.objects.create(
            asset_type=Asset.AssetType.BRIDGE,
            intervention_type=MaintenanceIntervention.InterventionType.MAJOR,
            name="Perbaikan Girder Major",
            unit_cost=Decimal("5000000.00"),
            state_improvement={"CS4": "CS2"},
            duration_days=14,
            min_interval_years=5,
        )

        plan = MaintenancePlan.objects.create(
            organization=org, name="Plan E2E Optimal",
            budget_total=Decimal("10000000.00"), planning_horizon_years=1,
        )

        run = MaintenanceOptimizationService().solve(plan.id)

        assert run.status == "optimal"
        assert run.objective_value is not None
        assert run.objective_value > 0

        plan.refresh_from_db()
        assert plan.status == MaintenancePlan.Status.OPTIMIZED

        schedule_rows = MaintenanceSchedule.objects.filter(run=run)
        assert schedule_rows.count() == 1
        row = schedule_rows.first()
        assert row.component_id == component.id
        assert row.scheduled_year == current_year
        assert row.expected_state_after == "CS2"
        assert row.cost == Decimal("5000000.00")

    def test_end_to_end_infeasible_writes_no_schedule_and_reverts_plan_to_draft(self, org):
        asset = _make_bridge(org, "SCHED-D")
        component = _make_girder(asset)

        import datetime as dt
        current_year = dt.date.today().year
        _make_model_with_forecast(
            component, {current_year: ("CS5", {"CS5": 1.0})}
        )

        # SENGAJA tidak membuat MaintenanceIntervention major/replacement
        # apa pun -- katalog kosong untuk asset_type ini -> §3.4 mustahil
        # dipenuhi.
        plan = MaintenancePlan.objects.create(
            organization=org, name="Plan E2E Infeasible",
            budget_total=Decimal("10000000.00"), planning_horizon_years=1,
        )

        run = MaintenanceOptimizationService().solve(plan.id)

        assert run.status == "infeasible"
        assert run.objective_value is None

        plan.refresh_from_db()
        assert plan.status == MaintenancePlan.Status.DRAFT  # dikembalikan,
        # bukan menggantung di 'optimizing'.

        assert not MaintenanceSchedule.objects.filter(run=run).exists()
