"""
visualization.md §4.2: MaintenanceMarkerService. Skenario dibangun manual
(bukan lewat CP-SAT solver sungguhan, engineering-rules.md §7 hanya
mewajibkan "no mocking JAX numerics" -- ini bukan JAX, murni query
read-only) untuk kecepatan test.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from apps.assets.models import Asset, AssetComponent
from apps.core.models import Organization
from apps.digitaltwin.services_maintenance_markers import MaintenanceMarkerService
from apps.maintenance.models import (
    MaintenanceIntervention,
    MaintenancePlan,
    MaintenanceSchedule,
    OptimizationRun,
)


@pytest.fixture
def org():
    return Organization.objects.create(name="Dinas PU Test Marker")


@pytest.fixture
def other_org():
    return Organization.objects.create(name="Dinas PU Lain Test Marker")


@pytest.fixture
def asset(org):
    return Asset.objects.create(
        organization=org, code="BRG-MARKER-1", name="Jembatan Marker Test",
        asset_type=Asset.AssetType.BRIDGE, latitude=Decimal("0"), longitude=Decimal("0"),
        importance_weight=Decimal("5.00"),
    )


@pytest.fixture
def component(asset):
    return AssetComponent.objects.create(
        asset=asset, component_type="girder", criticality_weight=Decimal("0.250"),
    )


@pytest.fixture
def intervention():
    return MaintenanceIntervention.objects.create(
        asset_type="bridge", intervention_type=MaintenanceIntervention.InterventionType.MAJOR,
        name="Rebar patch repair", unit_cost=Decimal("50000000.00"),
        state_improvement={"CS4": "CS2"}, duration_days=14,
    )


def _make_approved_run(org, plan_name, solved_at):
    plan = MaintenancePlan.objects.create(
        organization=org, name=plan_name, budget_total=Decimal("1000000000.00"),
        planning_horizon_years=10, status=MaintenancePlan.Status.APPROVED,
    )
    return OptimizationRun.objects.create(
        plan=plan, status=OptimizationRun.Status.OPTIMAL,
        solved_at=solved_at,
    )


@pytest.mark.django_db
class TestMaintenanceMarkerService:
    def test_returns_empty_when_no_approved_plan(self, org, asset):
        markers = MaintenanceMarkerService().get_markers(org.id, asset.id)
        assert markers == []

    def test_ignores_draft_plan_schedule(self, org, asset, component, intervention):
        draft_plan = MaintenancePlan.objects.create(
            organization=org, name="Draft Plan", budget_total=Decimal("1000000000.00"),
            planning_horizon_years=10, status=MaintenancePlan.Status.DRAFT,
        )
        run = OptimizationRun.objects.create(
            plan=draft_plan, status=OptimizationRun.Status.OPTIMAL,
            solved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        MaintenanceSchedule.objects.create(
            run=run, component=component, intervention=intervention,
            scheduled_year=2030, cost=Decimal("50000000.00"),
            expected_state_after="CS2",
        )

        markers = MaintenanceMarkerService().get_markers(org.id, asset.id)
        assert markers == []

    def test_returns_markers_from_approved_plan(self, org, asset, component, intervention):
        run = _make_approved_run(org, "Approved Plan", datetime(2026, 1, 1, tzinfo=timezone.utc))
        MaintenanceSchedule.objects.create(
            run=run, component=component, intervention=intervention,
            scheduled_year=2030, cost=Decimal("50000000.00"),
            expected_state_after="CS2",
        )

        markers = MaintenanceMarkerService().get_markers(org.id, asset.id)

        assert len(markers) == 1
        assert markers[0]["component_id"] == component.id
        assert markers[0]["component_type"] == "girder"
        assert markers[0]["scheduled_year"] == 2030
        assert markers[0]["intervention_name"] == "Rebar patch repair"
        assert markers[0]["expected_state_after"] == "CS2"

    def test_picks_only_latest_approved_run_not_mixed(self, org, asset, component, intervention):
        """2 approved plan -- HANYA baris dari run TERBARU (solved_at
        paling akhir) yang dikembalikan, tidak dicampur."""
        older_run = _make_approved_run(
            org, "Approved Plan Lama", datetime(2025, 1, 1, tzinfo=timezone.utc)
        )
        MaintenanceSchedule.objects.create(
            run=older_run, component=component, intervention=intervention,
            scheduled_year=2028, cost=Decimal("50000000.00"),
            expected_state_after="CS2",
        )

        newer_run = _make_approved_run(
            org, "Approved Plan Baru", datetime(2026, 6, 1, tzinfo=timezone.utc)
        )
        MaintenanceSchedule.objects.create(
            run=newer_run, component=component, intervention=intervention,
            scheduled_year=2032, cost=Decimal("60000000.00"),
            expected_state_after="CS1",
        )

        markers = MaintenanceMarkerService().get_markers(org.id, asset.id)

        assert len(markers) == 1
        assert markers[0]["scheduled_year"] == 2032
        assert markers[0]["expected_state_after"] == "CS1"

    def test_org_isolation(self, org, other_org, asset, component, intervention):
        run = _make_approved_run(org, "Approved Plan", datetime(2026, 1, 1, tzinfo=timezone.utc))
        MaintenanceSchedule.objects.create(
            run=run, component=component, intervention=intervention,
            scheduled_year=2030, cost=Decimal("50000000.00"),
            expected_state_after="CS2",
        )

        markers = MaintenanceMarkerService().get_markers(other_org.id, asset.id)
        assert markers == []
