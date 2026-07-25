"""
exports.md §2.1 -- test pdf_maintenance_plan (Fase 2). Pola identik
test_pdf_inspection.py: fixture DB asli (bukan mock), job Dramatiq
dipanggil via .fn() (sinkron, tidak butuh worker terpisah), verifikasi
file BENAR ada di SeaweedFS via download_bytes() -- bukan cuma percaya
field file_ref.
"""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from apps.assets.models import Asset, AssetComponent
from apps.core.models import Organization, User
from apps.deterioration.models import DegradationForecast, DeteriorationModel
from apps.exports.jobs import generate_pdf_export_job
from apps.exports.models import ExportJob
from apps.exports.services_api import ExportJobService
from apps.exports.services_maintenance_pdf import MaintenancePlanPdfService
from apps.exports.storage import download_bytes
from apps.maintenance.models import MaintenanceIntervention, MaintenancePlan
from apps.maintenance.services_scheduling import MaintenanceOptimizationService


@pytest.fixture
def org():
    return Organization.objects.create(name="Dinas PU Test Fase 2 PDF")


@pytest.fixture
def manager(org):
    return User.objects.create(
        keycloak_sub="sub-pdf-maintenance-1", organization=org, username="reza",
        email="reza@example.id", role=User.Role.MANAGER,
    )


@pytest.fixture
def optimized_plan(org):
    """Fixture end-to-end: Asset -> Component -> DeteriorationModel ->
    DegradationForecast -> MaintenanceIntervention -> MaintenancePlan ->
    solve() sungguhan (BUKAN mock CP-SAT) -- menghasilkan MaintenanceSchedule
    row nyata untuk dirender ke PDF."""
    asset = Asset.objects.create(
        organization=org, code="BRG-PDF-1", name="Jembatan PDF Test",
        asset_type=Asset.AssetType.BRIDGE, latitude=Decimal("0"), longitude=Decimal("0"),
        construction_year=2000, design_life_years=50,
        importance_weight=Decimal("6.00"), status="active",
    )
    component = AssetComponent.objects.create(
        asset=asset, component_type="girder", criticality_weight=Decimal("1.000"),
    )
    model = DeteriorationModel.objects.create(
        component=component, model_type="discrete_markov", parameters={},
        fitted_at=datetime.now(timezone.utc), model_version=1,
        training_data_hash="test-hash-pdf-maintenance",
    )
    DegradationForecast.objects.create(
        model=model, forecast_year=datetime.now().year,
        state_probabilities={"CS1": 0.0, "CS2": 0.0, "CS3": 0.0, "CS4": 1.0, "CS5": 0.0},
        expected_state="CS4", confidence_width=None,
    )
    MaintenanceIntervention.objects.create(
        asset_type="bridge", intervention_type="major",
        name="Perbaikan Girder Major (PDF Test)", unit_cost=Decimal("40000000.00"),
        state_improvement={"CS4": "CS2"}, duration_days=20, min_interval_years=5,
    )
    plan = MaintenancePlan.objects.create(
        organization=org, name="Rencana PDF Test Fase 2",
        budget_total=Decimal("80000000.00"), planning_horizon_years=2, status="draft",
    )
    run = MaintenanceOptimizationService().solve(plan.id)
    assert run.status in ("optimal", "feasible"), (
        f"Fixture harus menghasilkan run optimal/feasible, dapat: {run.status}"
    )
    plan.refresh_from_db()
    return plan


@pytest.mark.django_db
class TestMaintenancePlanPdfService:
    def test_render_produces_valid_pdf_bytes(self, optimized_plan):
        pdf_bytes = MaintenancePlanPdfService().render(optimized_plan.id)
        assert pdf_bytes[:5] == b"%PDF-"
        assert len(pdf_bytes) > 1000  # bukan file kosong/rusak

    def test_render_raises_when_plan_has_no_optimization_run(self, org):
        plan_without_run = MaintenancePlan.objects.create(
            organization=org, name="Plan Tanpa Run",
            budget_total=Decimal("1000.00"), planning_horizon_years=1, status="draft",
        )
        with pytest.raises(ValueError, match="belum punya OptimizationRun"):
            MaintenancePlanPdfService().render(plan_without_run.id)


@pytest.mark.django_db
class TestPdfMaintenancePlanEndToEnd:
    """architecture.md §4: ExportRequested -> GeneratePdfExportJob.
    fn() dipanggil langsung, sama pola test_pdf_inspection.py."""

    def test_full_export_flow_uploads_to_seaweedfs(self, optimized_plan, manager):
        job = ExportJob.objects.create(
            export_type=ExportJob.ExportType.PDF_MAINTENANCE_PLAN,
            reference_id=optimized_plan.id,
            requested_by=manager,
        )

        generate_pdf_export_job.fn(str(job.id))

        job.refresh_from_db()
        assert job.status == ExportJob.Status.DONE
        assert job.file_ref == f"exports/pdf_maintenance_plan/{job.id}.pdf"
        assert job.failure_reason == ""

        # exports.md §1: verifikasi file BENAR ada di object storage.
        downloaded = download_bytes(job.file_ref)
        assert downloaded[:5] == b"%PDF-"

    def test_service_rejects_draft_plan(self, org, manager):
        """exports.md §1: pdf_maintenance_plan hanya untuk plan
        optimized/approved -- draft harus ditolak SEBELUM job dibuat."""
        draft_plan = MaintenancePlan.objects.create(
            organization=org, name="Plan Draft Belum Optimasi",
            budget_total=Decimal("1000.00"), planning_horizon_years=1, status="draft",
        )
        with pytest.raises(ValueError, match="hanya bisa di-generate untuk plan"):
            ExportJobService().request_pdf_maintenance_plan(draft_plan.id, requested_by=manager)
