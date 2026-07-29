"""
exports.md §2.1: layout FIXED pdf_maintenance_plan (6 bagian). Service ini
MURNI assembly konteks + orkestrasi render chart -- tidak menyentuh
services_scheduling.py atau deterioration/* sama sekali (batasan
eksplisit sesi ini), hanya membaca data yang sudah dihasilkan keduanya.

Opsi A (disepakati eksplisit product owner, exports.md §2.1 poin 5):
halaman per-asset menampilkan SATU chart condition trend PER KOMPONEN
yang punya baris MaintenanceSchedule di run ini -- bukan satu chart
gabungan per-aset. Rationale: asset-registry.md §2 menegaskan forecast
selalu di-scope ke AssetComponent, tidak ada formula di formulas.md
untuk mengagregasi trajectory forecast lintas-komponen jadi satu garis
per-aset -- mengarang agregasi semacam itu berarti matematika baru yang
tidak diotorisasi dokumen fixed manapun.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone as dt_timezone

from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from weasyprint import HTML

from apps.deterioration.services_chart import ComponentForecastChartService
from apps.maintenance.models import MaintenancePlan, MaintenanceSchedule, OptimizationRun
from apps.maintenance.services_chart import MaintenanceBudgetChartService, MaintenanceGanttChartService

from .chart_renderer_client import render_chart_svg
from apps.core.storage import upload_bytes


class MaintenancePlanPdfService:
    def __init__(self) -> None:
        self._gantt_service = MaintenanceGanttChartService()
        self._budget_service = MaintenanceBudgetChartService()
        self._forecast_service = ComponentForecastChartService()

    def _get_latest_run(self, plan: MaintenancePlan) -> OptimizationRun:
        """Pola identik apps/maintenance/services_api.py get_latest_run() --
        .order_by('-created_at').first(), BUKAN get_object_or_404(plan=plan)
        polos (rentan MultipleObjectsReturned setelah re-optimize)."""
        run = plan.optimization_runs.order_by("-created_at").first()
        if run is None:
            raise ValueError(
                f"MaintenancePlan {plan.id} belum punya OptimizationRun -- "
                f"tidak bisa generate pdf_maintenance_plan tanpa hasil solve."
            )
        return run

    def _build_cover_context(self, plan: MaintenancePlan, run: OptimizationRun) -> dict:
        # exports.md §2.1 poin 1
        return {
            "plan_name": plan.name,
            "organization_name": plan.organization.name,
            "budget_total": plan.budget_total,
            "horizon_years": plan.planning_horizon_years,
            "generated_at": datetime.now(dt_timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "run_id": run.id,
        }

    def _build_executive_summary_context(self, run: OptimizationRun, schedule_rows: list) -> dict:
        # exports.md §2.1 poin 2
        assets_covered = {row.component.asset_id for row in schedule_rows}
        return {
            "objective_value": run.objective_value,
            "assets_covered_count": len(assets_covered),
            "interventions_scheduled_count": len(schedule_rows),
            "solver_status": run.status,
            "is_infeasibility_note_needed": run.status == OptimizationRun.Status.FEASIBLE,
        }

    def _build_per_asset_context(self, schedule_rows: list) -> list:
        # exports.md §2.1 poin 5. Opsi A: satu chart per komponen (lihat
        # docstring modul), dikelompokkan per asset untuk layout halaman.
        by_asset: dict[uuid.UUID, dict] = {}
        for row in schedule_rows:
            asset = row.component.asset
            if asset.id not in by_asset:
                by_asset[asset.id] = {
                    "asset_name": asset.name,
                    "asset_code": asset.code,
                    "components": {},  # component_id -> {label, chart_svg, schedule_rows}
                }

            comp_id = row.component_id
            if comp_id not in by_asset[asset.id]["components"]:
                forecast_data = self._forecast_service.get_chart_data(
                    organization_id=asset.organization_id, component_id=comp_id
                )
                chart_svg = None
                if forecast_data["points"]:
                    # Komponen bisa saja belum punya forecast (edge case
                    # ComponentForecastChartService: points kosong) -- tidak
                    # render chart kosong, tabel jadwal tetap tampil.
                    chart_svg = render_chart_svg("condition_trend", forecast_data)

                by_asset[asset.id]["components"][comp_id] = {
                    "component_label": row.component.component_type,
                    "chart_svg": chart_svg,
                    "schedule_rows": [],
                }

            by_asset[asset.id]["components"][comp_id]["schedule_rows"].append(
                {
                    "scheduled_year": row.scheduled_year,
                    "intervention_name": row.intervention.name,
                    "cost": row.cost,
                    "expected_state_after": row.expected_state_after,
                }
            )

        # Ubah dict jadi list untuk template, components juga jadi list
        result = []
        for asset_data in by_asset.values():
            asset_data["components"] = list(asset_data["components"].values())
            result.append(asset_data)
        return result

    def _build_appendix_context(self, run: OptimizationRun, schedule_rows: list) -> dict:
        # exports.md §2.1 poin 6
        return {
            "solver": run.solver,
            "runtime_seconds": run.runtime_seconds,
            "status": run.status,
            "schedule_rows": [
                {
                    "component_label": (
                        f"{row.component.asset.name} — {row.component.component_type}"
                    ),
                    "intervention_name": row.intervention.name,
                    "scheduled_year": row.scheduled_year,
                    "cost": row.cost,
                    "expected_state_after": row.expected_state_after,
                }
                for row in schedule_rows
            ],
        }

    def render(self, plan_id: uuid.UUID) -> bytes:
        plan = get_object_or_404(MaintenancePlan, id=plan_id)
        run = self._get_latest_run(plan)

        schedule_rows = list(
            MaintenanceSchedule.objects.filter(run=run)
            .select_related("component", "component__asset", "intervention")
            .order_by("component__asset__name", "component__component_type", "scheduled_year")
        )

        # exports.md §2.1 poin 3: portfolio Gantt chart (semua asset dalam
        # satu chart, sesuai deskripsi "all assets, one row per component").
        gantt_data = self._gantt_service.get_gantt_data(plan.organization_id, run.id)
        gantt_svg = render_chart_svg("gantt", gantt_data) if gantt_data["rows"] else None

        # exports.md §2.1 poin 4: budget allocation chart.
        budget_data = self._budget_service.get_budget_data(plan.organization_id, run.id)
        budget_svg = render_chart_svg("budget", budget_data)

        context = {
            "cover": self._build_cover_context(plan, run),
            "executive_summary": self._build_executive_summary_context(run, schedule_rows),
            "gantt_svg": gantt_svg,
            "budget_svg": budget_svg,
            "per_asset": self._build_per_asset_context(schedule_rows),
            "appendix": self._build_appendix_context(run, schedule_rows),
        }

        html_string = render_to_string("exports/pdf_maintenance_plan.html", context)
        return HTML(string=html_string).write_pdf()

    def render_and_store(self, plan_id: uuid.UUID, export_job_id) -> str:
        pdf_bytes = self.render(plan_id)
        key = f"exports/pdf_maintenance_plan/{export_job_id}.pdf"
        return upload_bytes(key, pdf_bytes, content_type="application/pdf")
