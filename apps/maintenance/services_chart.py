"""
Service query untuk Gantt chart + budget allocation chart
(visualization.md §5). MURNI membaca data yang sudah dihasilkan
MaintenanceOptimizationService (services_scheduling.py) -- TIDAK
mengubah logic solver apa pun (batasan eksplisit sesi ini).

visualization.md §5: "Maintenance Gantt chart ... generated directly
from the CP-SAT solver output ... not maintained as a separate
planning artifact" -- artinya kedua chart di sini murni query
MaintenanceSchedule/OptimizationRun, tidak ada tabel/state Gantt
terpisah.

Keputusan desain disepakati eksplisit sesi ini (didokumentasikan di
sini, bukan ditemukan lagi nanti):

- anchor_year untuk merekonstruksi years_range budget chart diambil dari
  OptimizationRun.solved_at.year, BUKAN menghitung ulang
  timezone.localdate().year saat chart di-generate/PDF di-export.
  Rationale: MaintenanceCoefficientBuilder.build() (services_scheduling.py)
  menghitung anchor_year = timezone.localdate().year PERSIS saat solve
  dijalankan, tapi nilai itu tidak pernah disimpan eksplisit ke kolom
  manapun. run.solved_at ditulis via timezone.now() pada baris yang sama
  di eksekusi job yang sama -- job berjalan dalam hitungan detik/menit,
  tidak mungkin melintasi pergantian tahun kalender, jadi
  run.solved_at.year secara praktis identik dengan anchor_year asli yang
  dipakai solver. Ini menghindari angka budget chart "menghitung ulang"
  horizon yang berbeda dari yang benar-benar dipakai solver kalau export
  dilakukan di tahun kalender berikutnya (prd.md §9: "no silently-imputed
  values", auditability).
- Gantt "durasi" bar: MaintenanceSchedule tidak punya rentang waktu
  sendiri (hanya scheduled_year, satu titik) -- durasi visual diturunkan
  dari MaintenanceIntervention.duration_days (dikonversi ke pecahan
  tahun, dibulatkan 2 desimal secukupnya untuk tampilan, BUKAN untuk
  komputasi lebih lanjut).
- Budget per tahun memakai logic IDENTIK dengan
  MaintenanceCoefficientBuilder.build() (flat = budget_total / horizon,
  ATAU budget_profile custom dengan tahun kosong = 0) -- TAPI dalam
  satuan Rupiah asli (Decimal), bukan sen/integer seperti representasi
  internal solver (yang itu murni kebutuhan CP-SAT, bukan buat tampilan).
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from django.db.models import Sum
from django.shortcuts import get_object_or_404

from .models import MaintenanceSchedule, OptimizationRun


class MaintenanceGanttChartService:
    """Query read-only untuk Gantt chart (visualization.md §5). Satu baris
    output per MaintenanceSchedule row -- tidak ada agregasi."""

    def get_gantt_data(self, organization_id: uuid.UUID, run_id: uuid.UUID) -> dict:
        run = get_object_or_404(
            OptimizationRun.objects.for_organization(organization_id),
            id=run_id,
        )

        schedule_rows = (
            MaintenanceSchedule.objects.filter(run=run)
            .select_related("component", "component__asset", "intervention")
            .order_by("component__asset__name", "component__component_type", "scheduled_year")
        )

        rows = []
        for row in schedule_rows:
            duration_years = round(row.intervention.duration_days / 365.0, 2)
            rows.append(
                {
                    "component_id": row.component_id,
                    "component_label": (
                        f"{row.component.asset.name} — {row.component.component_type}"
                    ),
                    "scheduled_year": row.scheduled_year,
                    "duration_years": duration_years,
                    "intervention_name": row.intervention.name,
                    "intervention_type": row.intervention.intervention_type,
                    "cost": row.cost,
                    "expected_state_after": row.expected_state_after,
                }
            )

        return {
            "run_id": run.id,
            "plan_id": run.plan_id,
            "plan_name": run.plan.name,
            "rows": rows,
        }


class MaintenanceBudgetChartService:
    """Query read-only untuk budget allocation chart (visualization.md §5).
    Logic budget per tahun IDENTIK dengan MaintenanceCoefficientBuilder
    (services_scheduling.py) -- lihat rationale anchor_year di docstring
    modul ini."""

    def get_budget_data(self, organization_id: uuid.UUID, run_id: uuid.UUID) -> dict:
        run = get_object_or_404(
            OptimizationRun.objects.for_organization(organization_id),
            id=run_id,
        )
        plan = run.plan
        horizon = plan.planning_horizon_years

        # Lihat rationale di docstring modul: anchor_year dari
        # run.solved_at, BUKAN timezone.localdate() saat chart digenerate.
        anchor_year = run.solved_at.year
        years_range = list(range(anchor_year, anchor_year + horizon))

        cost_by_year: dict[int, Decimal] = {
            row["scheduled_year"]: row["total"]
            for row in (
                MaintenanceSchedule.objects.filter(run=run)
                .values("scheduled_year")
                .annotate(total=Sum("cost"))
            )
        }

        flat_budget = plan.budget_total / horizon
        years = []
        for year in years_range:
            if plan.budget_profile:
                budget_for_year = Decimal(str(plan.budget_profile.get(str(year), "0")))
            else:
                budget_for_year = flat_budget

            years.append(
                {
                    "year": year,
                    "allocated_cost": cost_by_year.get(year, Decimal("0.00")),
                    "budget": budget_for_year,
                }
            )

        return {
            "run_id": run.id,
            "plan_id": run.plan_id,
            "plan_name": run.plan.name,
            "years": years,
        }
