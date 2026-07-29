"""
scheduling.md -- CP-SAT maintenance optimization service (Fase 2).

Pemisahan disengaja jadi 3 lapis, supaya bagian matematis (build_and_solve)
bisa ditest dengan fixture kecil TANPA database (engineering-rules.md par.7:
"hand-computed expected value for at least one non-trivial input"):

1. MaintenanceCoefficientBuilder -- baca DB, rakit OptimizationInputs
   (constant coefficients, formulas.md par.5.1: DeltaD_b,t dihitung SEBELUM
   solver jalan, bukan di dalam constraint).
2. build_and_solve() -- FUNGSI MURNI, terima OptimizationInputs, bangun
   model CP-SAT (decision variables + constraint 3.1-3.4 + objective 4),
   solve, kembalikan SolveResult. Tidak menyentuh Django ORM sama sekali.
3. MaintenanceOptimizationService -- orkestrasi: panggil (1), panggil (2),
   tulis hasil ke OptimizationRun + MaintenanceSchedule (database.md par.5),
   plus tulis solver log ke SeaweedFS (engineering-rules.md par.3).

Keputusan desain disepakati eksplisit sesi ini (tidak ada di dokumen fixed
apa adanya, didokumentasikan di sini supaya tidak "ditemukan lagi" nanti):

- scheduling.md par.3.4 vs par.3.5: constraint mandatory floor DIBACA
  terhadap TRAJECTORY FORECAST ASLI (DegradationForecast.expected_state,
  dihitung tanpa asumsi intervensi apa pun) -- BUKAN re-baseline berantai
  state pasca-intervensi di dalam solver. Ini konsisten dengan par.3.5
  sendiri yang eksplisit bilang koefisien objective precomputed sebagai
  KONSTANTA linear ("keeps the CP-SAT model tractable... deliberate
  simplification").
- t=1 (tahun pertama horizon) = tahun kalender saat OptimizationRun ini
  dieksekusi (timezone.localdate().year), BUKAN plan.created_at --
  konsisten dengan engineering-rules.md par.1 (re-optimize selalu bikin
  OptimizationRun baru, snapshot waktu itu).
- budget_profile custom (JSONField, amandemen aditif database.md par.5):
  tahun yang TIDAK ada key-nya dianggap anggaran 0 (paling aman -- solver
  tidak pernah mengalokasikan dana di tahun yang sengaja tidak
  dianggarkan Manager), BUKAN fallback ke flat share.
- MaintenanceIntervention.state_improvement (JSONField) diasumsikan SELALU
  persis 1 entry {from_state: to_state} -- konvensi yang sudah dipakai di
  contoh formulas.md par.5.1 ({"CS4":"CS2"}). Divalidasi eksplisit
  (_single_state_improvement), bukan diam-diam mengasumsikan struktur.

Minimal infeasible subset (scheduling.md par.5, TIDAK LAGI TODO --
diimplementasi penuh sesi ini): HANYA constraint mandatory floor (par.3.4)
yang dijaga CP-SAT assumption boolean per komponen
(enable_mandatory_floor[component_id]). Constraint par.3.1 (budget) dan
par.3.3 (interval minimum) SENGAJA TIDAK dijaga assumption -- keduanya
selalu aktif penuh -- karena par.3.4 adalah SATU-SATUNYA constraint yang
secara eksplisit diminta didiagnosis per scheduling.md par.5: "which
mandatory interventions cannot fit the budget". Kalau infeasible
disebabkan murni interaksi par.3.2/par.3.3 (bukan par.3.4), assumption
list akan kosong -- ditangani dengan pesan fallback yang jujur, bukan
mengklaim tahu penyebabnya.

solver_log_ref (scheduling.md par.5, TIDAK LAGI TODO): CpSolver.ResponseStats()
plus (kalau infeasible) daftar component_id yang mandatory floor-nya
terbukti perlu (dari SufficientAssumptionsForInfeasibility()) ditulis
sebagai teks ke SeaweedFS via apps.core.storage.upload_bytes(), key
disimpan ke OptimizationRun.solver_log_ref -- SATU-SATUNYA titik commit
audit lengkap untuk sebuah run, ditulis untuk SETIAP status (bukan cuma
saat gagal), konsisten dengan engineering-rules.md par.3.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone
from ortools.sat.python import cp_model

from config.assetnexus import OPTIMIZATION

from apps.assets.models import AssetComponent
from apps.deterioration.models import DeteriorationModel
from apps.core.storage import upload_bytes

from .models import MaintenanceIntervention, MaintenancePlan, MaintenanceSchedule, OptimizationRun

STATES = ["CS1", "CS2", "CS3", "CS4", "CS5"]
STATE_LEVEL = {state: idx + 1 for idx, state in enumerate(STATES)}  # CS1=1 ... CS5=5


def _single_state_improvement(state_improvement: dict, intervention_id) -> tuple[str, str]:
    """formulas.md par.5.1 convention: state_improvement selalu persis 1 entry
    {from_state: to_state}. Divalidasi eksplisit -- gagal jelas (pesan
    menyebut intervention_id) daripada crash cryptic dari tuple-unpack."""
    if len(state_improvement) != 1:
        raise ValueError(
            f"MaintenanceIntervention {intervention_id}: state_improvement harus "
            f"persis 1 entry {{from_state: to_state}} (formulas.md par.5.1 convention), "
            f"dapat {len(state_improvement)} entry: {state_improvement!r}"
        )
    return next(iter(state_improvement.items()))


@dataclass
class ComponentInput:
    component_id: uuid.UUID
    asset_type: str
    importance_weight: Decimal
    forecast_by_year: dict  # {year: {"CS1": 0.1, ...}}
    expected_state_by_year: dict  # {year: "CS1".."CS5"}


@dataclass
class InterventionInput:
    intervention_id: uuid.UUID
    asset_type: str
    intervention_type: str  # minor / major / replacement
    unit_cost: Decimal
    state_improvement: dict
    min_interval_years: int | None


@dataclass
class OptimizationInputs:
    anchor_year: int
    horizon_years: int
    components: list = field(default_factory=list)
    interventions: list = field(default_factory=list)
    budget_cents_by_year: dict = field(default_factory=dict)
    cost_scale: int = 100
    objective_scale: int = 10000
    solver_time_limit_seconds: int = 60


@dataclass
class ScheduledIntervention:
    component_id: uuid.UUID
    year: int
    intervention_id: uuid.UUID
    cost: Decimal
    expected_state_after: str


@dataclass
class SolveResult:
    status: str  # optimal / feasible / infeasible / failed
    objective_value: Decimal | None
    runtime_seconds: Decimal
    schedule: list
    response_stats: str
    # Kosong kalau status bukan infeasible, ATAU infeasible tapi bukan
    # disebabkan mandatory floor spesifik manapun (lihat rationale di
    # module docstring -- fallback jujur, bukan klaim palsu).
    infeasible_mandatory_floor_component_ids: list


def _delta_d(intervention: InterventionInput, forecast_probs: dict) -> float:
    """formulas.md par.5.1: DeltaD_b,t,i = P(komponen berada di from_state
    pada tahun t) * (level state yang dipulihkan)."""
    from_state, to_state = _single_state_improvement(
        intervention.state_improvement, intervention.intervention_id
    )
    prob = forecast_probs.get(from_state, 0.0)
    levels_recovered = STATE_LEVEL[from_state] - STATE_LEVEL[to_state]
    return prob * levels_recovered


def build_and_solve(inputs: OptimizationInputs) -> SolveResult:
    """FUNGSI MURNI -- tidak menyentuh Django ORM. Terima OptimizationInputs,
    bangun model CP-SAT persis sesuai scheduling.md par.2-4, solve,
    kembalikan SolveResult. Dirancang begini supaya bisa ditest dengan
    fixture kecil yang bisa dihitung tangan (engineering-rules.md par.7)."""

    model = cp_model.CpModel()
    x = {}

    # Assumption boolean per komponen -- HANYA menjaga constraint mandatory
    # floor (par.3.4). Dipakai untuk minimal infeasible subset (scheduling.md par.5).
    enable_mandatory_floor: dict[uuid.UUID, cp_model.IntVar] = {}

    applicable_by_asset_type: dict[str, list] = {}
    for iv in inputs.interventions:
        applicable_by_asset_type.setdefault(iv.asset_type, []).append(iv)

    for comp in inputs.components:
        applicable = applicable_by_asset_type.get(comp.asset_type, [])
        years = sorted(comp.forecast_by_year.keys())

        for year in years:
            for iv in applicable:
                x[(comp.component_id, year, iv.intervention_id)] = model.NewBoolVar(
                    f"x_{comp.component_id}_{year}_{iv.intervention_id}"
                )

        # scheduling.md par.3.2: satu intervensi per komponen per tahun.
        for year in years:
            terms = [x[(comp.component_id, year, iv.intervention_id)] for iv in applicable]
            if terms:
                model.Add(sum(terms) <= 1)

        # scheduling.md par.3.3: interval minimum antar intervensi major/replacement.
        for iv in applicable:
            if iv.intervention_type in ("major", "replacement") and iv.min_interval_years:
                for start in years:
                    window = [y for y in years if start <= y < start + iv.min_interval_years]
                    if len(window) > 1:
                        model.Add(
                            sum(x[(comp.component_id, y, iv.intervention_id)] for y in window) <= 1
                        )

        # scheduling.md par.3.4: mandatory intervention floor -- terhadap
        # TRAJECTORY FORECAST ASLI (lihat rationale di module docstring).
        # DIJAGA assumption boolean untuk minimal infeasible subset (par.5).
        cs5_years = sorted(
            y for y, state in comp.expected_state_by_year.items() if state == "CS5"
        )
        if cs5_years:
            t_first = cs5_years[0]  # constraint utk tahun CS5 berikutnya adalah
            # subset dari constraint ini (window t'<=t_first lebih ketat),
            # jadi cukup ditambahkan sekali -- tidak redundant per-tahun.
            eligible_years = [y for y in years if y <= t_first]
            major_interventions = [
                iv for iv in applicable if iv.intervention_type in ("major", "replacement")
            ]
            terms = [
                x[(comp.component_id, y, iv.intervention_id)]
                for y in eligible_years
                for iv in major_interventions
            ]

            enable_var = model.NewBoolVar(f"mandatory_floor_{comp.component_id}")
            enable_mandatory_floor[comp.component_id] = enable_var

            if terms:
                model.Add(sum(terms) >= 1).OnlyEnforceIf(enable_var)
            else:
                # Tidak ada intervensi major/replacement yang berlaku untuk
                # asset_type ini di katalog -- komponen forecast CS5 TIDAK
                # BISA dipenuhi secara aman. Harus infeasible (via assumption),
                # bukan silent skip.
                model.Add(0 >= 1).OnlyEnforceIf(enable_var)

    # scheduling.md par.3.1: budget per tahun, lintas semua komponen+intervensi.
    # SENGAJA TIDAK dijaga assumption -- selalu aktif penuh (lihat module docstring).
    all_years = sorted({year for comp in inputs.components for year in comp.forecast_by_year})
    cost_cents = {
        iv.intervention_id: int(
            (iv.unit_cost * inputs.cost_scale).to_integral_value(rounding=ROUND_HALF_UP)
        )
        for iv in inputs.interventions
    }
    for year in all_years:
        budget = inputs.budget_cents_by_year.get(year, 0)
        terms = []
        for comp in inputs.components:
            if year not in comp.forecast_by_year:
                continue
            for iv in applicable_by_asset_type.get(comp.asset_type, []):
                terms.append(
                    cost_cents[iv.intervention_id] * x[(comp.component_id, year, iv.intervention_id)]
                )
        if terms:
            model.Add(sum(terms) <= budget)

    # formulas.md par.5.1: maximize sum(w_b * DeltaD_b,t * x_b,t), diskalakan ke integer.
    objective_terms = []
    for comp in inputs.components:
        w_scaled = int(
            (comp.importance_weight * inputs.objective_scale).to_integral_value(
                rounding=ROUND_HALF_UP
            )
        )
        for year, probs in comp.forecast_by_year.items():
            for iv in applicable_by_asset_type.get(comp.asset_type, []):
                delta_d = _delta_d(iv, probs)
                coeff = int(round(w_scaled * delta_d))
                if coeff != 0:
                    objective_terms.append(coeff * x[(comp.component_id, year, iv.intervention_id)])
    if objective_terms:
        model.Maximize(sum(objective_terms))
    # Kalau objective_terms kosong (tidak ada komponen/intervensi applicable
    # sama sekali), CP-SAT tetap valid diselesaikan tanpa objective -- solver
    # melaporkan OPTIMAL trivial (tidak ada apa pun untuk dijadwalkan).

    if enable_mandatory_floor:
        model.AddAssumptions(list(enable_mandatory_floor.values()))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = inputs.solver_time_limit_seconds
    status_code = solver.Solve(model)

    status_map = {
        cp_model.OPTIMAL: "optimal",
        cp_model.FEASIBLE: "feasible",
        cp_model.INFEASIBLE: "infeasible",
    }
    status = status_map.get(status_code, "failed")

    schedule = []
    objective_value = None
    infeasible_component_ids: list = []

    if status in ("optimal", "feasible"):
        objective_value = Decimal(solver.ObjectiveValue()) / inputs.objective_scale
        for comp in inputs.components:
            applicable = applicable_by_asset_type.get(comp.asset_type, [])
            for year in comp.forecast_by_year:
                for iv in applicable:
                    var = x.get((comp.component_id, year, iv.intervention_id))
                    if var is not None and solver.Value(var) == 1:
                        _, to_state = _single_state_improvement(
                            iv.state_improvement, iv.intervention_id
                        )
                        schedule.append(
                            ScheduledIntervention(
                                component_id=comp.component_id,
                                year=year,
                                intervention_id=iv.intervention_id,
                                cost=iv.unit_cost,
                                expected_state_after=to_state,
                            )
                        )
    elif status == "infeasible" and enable_mandatory_floor:
        # scheduling.md par.5: minimal infeasible subset -- index assumption
        # yang TERBUKTI perlu untuk membuktikan infeasible, di-map balik ke
        # component_id. Kalau kosong, infeasible disebabkan constraint lain
        # (par.3.2/par.3.3 murni) -- bukan mandatory floor mana pun.
        sufficient_indices = set(solver.SufficientAssumptionsForInfeasibility())
        infeasible_component_ids = [
            component_id
            for component_id, var in enable_mandatory_floor.items()
            if var.Index() in sufficient_indices
        ]

    return SolveResult(
        status=status,
        objective_value=objective_value,
        runtime_seconds=Decimal(str(round(solver.WallTime(), 2))),
        schedule=schedule,
        response_stats=solver.ResponseStats(),
        infeasible_mandatory_floor_component_ids=infeasible_component_ids,
    )


class MaintenanceCoefficientBuilder:
    """Kumpulkan constant data dari database untuk satu MaintenancePlan
    (scheduling.md par.2/par.4: koefisien dihitung SEBELUM solver jalan)."""

    def build(self, plan: MaintenancePlan) -> OptimizationInputs:
        anchor_year = timezone.localdate().year
        horizon = plan.planning_horizon_years
        years_range = list(range(anchor_year, anchor_year + horizon))

        components_qs = (
            AssetComponent.objects.for_organization(plan.organization_id)
            .filter(deleted_at__isnull=True)
            .select_related("asset")
        )

        component_inputs = []
        for component in components_qs:
            active_model = self._get_active_model(component)
            if active_model is None:
                continue  # belum ada DeteriorationModel -- di luar cakupan
                # optimasi ini, bukan error keras (prd.md par.9 graceful degradation).

            forecasts = {
                f.forecast_year: f
                for f in active_model.forecasts.filter(forecast_year__in=years_range)
            }
            if not forecasts:
                continue

            component_inputs.append(
                ComponentInput(
                    component_id=component.id,
                    asset_type=component.asset.asset_type,
                    importance_weight=component.asset.importance_weight,
                    forecast_by_year={
                        year: f.state_probabilities for year, f in forecasts.items()
                    },
                    expected_state_by_year={
                        year: f.expected_state for year, f in forecasts.items()
                    },
                )
            )

        intervention_inputs = [
            InterventionInput(
                intervention_id=iv.id,
                asset_type=iv.asset_type,
                intervention_type=iv.intervention_type,
                unit_cost=iv.unit_cost,
                state_improvement=iv.state_improvement,
                min_interval_years=iv.min_interval_years,
            )
            for iv in MaintenanceIntervention.objects.all()
        ]

        budget_cents_by_year = {}
        flat_budget = plan.budget_total / horizon
        for year in years_range:
            if plan.budget_profile:
                # Tahun yang tidak ada key-nya di budget_profile custom
                # dianggap anggaran 0 (paling aman) -- lihat rationale di
                # module docstring.
                amount = Decimal(str(plan.budget_profile.get(str(year), "0")))
            else:
                amount = flat_budget
            budget_cents_by_year[year] = int(
                (amount * OPTIMIZATION["COST_SCALE_TO_CENTS"]).to_integral_value(
                    rounding=ROUND_HALF_UP
                )
            )

        return OptimizationInputs(
            anchor_year=anchor_year,
            horizon_years=horizon,
            components=component_inputs,
            interventions=intervention_inputs,
            budget_cents_by_year=budget_cents_by_year,
            cost_scale=OPTIMIZATION["COST_SCALE_TO_CENTS"],
            objective_scale=OPTIMIZATION["OBJECTIVE_COEFFICIENT_SCALE"],
            solver_time_limit_seconds=OPTIMIZATION["SOLVER_TIME_LIMIT_SECONDS"],
        )

    def _get_active_model(self, component: AssetComponent):
        """Pola identik apps/deterioration/services_chart.py: exclude
        fuzzy_markov (tidak pernah punya DegradationForecast sendiri),
        model_version tertinggi dari sisa kandidat sudah pasti tepat."""
        return (
            DeteriorationModel.objects.filter(component=component)
            .exclude(model_type=DeteriorationModel.ModelType.FUZZY_MARKOV)
            .order_by("-model_version")
            .first()
        )


def _build_solver_log_text(run_id: uuid.UUID, result: SolveResult) -> str:
    """engineering-rules.md par.3: log audit lengkap untuk SETIAP run (bukan
    cuma saat gagal). Format teks polos -- cukup untuk dibaca manusia lewat
    UI/download_bytes(), tidak perlu parsing terstruktur di v1."""
    lines = [
        f"OptimizationRun: {run_id}",
        f"Status: {result.status}",
        f"Objective value: {result.objective_value}",
        f"Runtime (detik, WallTime): {result.runtime_seconds}",
        "",
        "--- CpSolver.ResponseStats() ---",
        result.response_stats,
    ]
    if result.status == "infeasible":
        lines.append("")
        lines.append("--- Minimal infeasible subset (scheduling.md par.5) ---")
        if result.infeasible_mandatory_floor_component_ids:
            lines.append(
                "Constraint mandatory floor (par.3.4) TERBUKTI PERLU untuk komponen berikut "
                "(forecast mencapai CS5, tidak bisa dipenuhi budget/katalog saat ini):"
            )
            for component_id in result.infeasible_mandatory_floor_component_ids:
                lines.append(f"  - component_id: {component_id}")
        else:
            lines.append(
                "Tidak ada mandatory floor (par.3.4) spesifik yang teridentifikasi sebagai "
                "penyebab -- infeasible kemungkinan disebabkan interaksi constraint lain "
                "(par.3.2 satu-intervensi-per-tahun atau par.3.3 interval minimum). Diagnosis "
                "lebih rinci untuk kasus ini belum diimplementasikan."
            )
    return "\n".join(lines)


class MaintenanceOptimizationService:
    """Orkestrasi penuh: DB -> CP-SAT -> DB -> SeaweedFS (log). Dipanggil
    dari Dramatiq actor (RunOptimizationJob, architecture.md par.4), bukan
    langsung dari router (engineering-rules.md par.6)."""

    def __init__(self) -> None:
        self._builder = MaintenanceCoefficientBuilder()

    def solve(self, plan_id: uuid.UUID) -> OptimizationRun:
        plan = MaintenancePlan.objects.get(id=plan_id)
        plan.status = MaintenancePlan.Status.OPTIMIZING
        plan.save(update_fields=["status"])

        inputs = self._builder.build(plan)
        result = build_and_solve(inputs)

        run = OptimizationRun.objects.create(
            plan=plan,
            solver="cp_sat",
            status=result.status,
            objective_value=result.objective_value,
            runtime_seconds=result.runtime_seconds,
            solved_at=timezone.now(),
        )

        log_text = _build_solver_log_text(run.id, result)
        log_key = upload_bytes(
            key=f"optimization-logs/{run.id}.txt",
            data=log_text.encode("utf-8"),
            content_type="text/plain",
        )
        run.solver_log_ref = log_key
        run.save(update_fields=["solver_log_ref"])

        if result.status in ("optimal", "feasible"):
            schedule_rows = [
                MaintenanceSchedule(
                    run=run,
                    component_id=item.component_id,
                    intervention_id=item.intervention_id,
                    scheduled_year=item.year,
                    cost=item.cost,
                    expected_state_after=item.expected_state_after,
                )
                for item in result.schedule
            ]
            MaintenanceSchedule.objects.bulk_create(schedule_rows)
            plan.status = MaintenancePlan.Status.OPTIMIZED
        else:
            # infeasible/failed -- TIDAK menulis MaintenanceSchedule
            # (scheduling.md par.5 langkah 4).
            plan.status = MaintenancePlan.Status.DRAFT  # kembali ke draft
            # (bukan tetap "optimizing") -- supaya Manager tahu run ini
            # perlu tindakan (revisi budget/scope), bukan status menggantung.

        plan.save(update_fields=["status"])
        return run
