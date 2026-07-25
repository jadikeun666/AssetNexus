"""
architecture.md par.3: router hanya panggil method di sini -- tidak
orchestrate langsung. Dispatch job (par.4) ada di sini, bukan di router.
"""
import uuid

from django.shortcuts import get_object_or_404

from .jobs import run_optimization_job
from .models import MaintenancePlan, MaintenanceSchedule, OptimizationRun


class MaintenancePlanService:
    def create(self, organization_id: uuid.UUID, created_by, data: dict) -> MaintenancePlan:
        return MaintenancePlan.objects.create(
            organization_id=organization_id, created_by=created_by, **data
        )

    def get(self, organization_id: uuid.UUID, plan_id: uuid.UUID) -> MaintenancePlan:
        return get_object_or_404(
            MaintenancePlan.objects.for_organization(organization_id), id=plan_id
        )

    def list_for_organization(self, organization_id: uuid.UUID):
        return MaintenancePlan.objects.for_organization(organization_id)


class MaintenanceOptimizationRunService:
    def trigger(self, organization_id: uuid.UUID, plan_id: uuid.UUID) -> MaintenancePlan:
        """Dispatch async (dramatiq .send()) -- TIDAK menjalankan solve()
        sinkron di request thread (bisa sampai SOLVER_TIME_LIMIT_SECONDS=60
        detik, jauh melebihi timeout HTTP wajar)."""
        plan = get_object_or_404(
            MaintenancePlan.objects.for_organization(organization_id), id=plan_id
        )
        run_optimization_job.send(str(plan.id))
        return plan

    def get_latest_run(self, organization_id: uuid.UUID, plan_id: uuid.UUID) -> OptimizationRun:
        """BUKAN get_object_or_404(qs, plan=plan) -- itu memanggil .get()
        yang crash MultipleObjectsReturned begitu plan sudah pernah
        di-re-optimize lebih dari sekali (engineering-rules.md par.1: setiap
        re-optimize bikin OptimizationRun BARU, tidak pernah menimpa yang
        lama). .first() setelah order_by adalah cara yang benar utk "yang
        terbaru"."""
        from django.http import Http404

        plan = get_object_or_404(
            MaintenancePlan.objects.for_organization(organization_id), id=plan_id
        )
        run = OptimizationRun.objects.filter(plan=plan).order_by("-created_at").first()
        if run is None:
            raise Http404("Belum ada OptimizationRun untuk plan ini.")
        return run

    def get_run(self, organization_id: uuid.UUID, run_id: uuid.UUID) -> OptimizationRun:
        return get_object_or_404(
            OptimizationRun.objects.for_organization(organization_id), id=run_id
        )

    def list_schedule_for_run(self, organization_id: uuid.UUID, run_id: uuid.UUID):
        run = self.get_run(organization_id, run_id)
        return MaintenanceSchedule.objects.filter(run=run).select_related(
            "component", "intervention"
        )
