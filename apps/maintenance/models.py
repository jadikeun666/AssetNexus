from django.db import models

from apps.assets.models import AssetComponent
from apps.core.managers import OrganizationScopedManager
from apps.core.models import BaseModel, Organization


class ConditionStateChoices(models.TextChoices):
    """Dimirror (bukan di-import dari deterioration.models), sama alasan
    dengan pola yang sudah ada di deterioration/models.py: asset-registry.md
    §3 adalah vocabulary bersama seluruh sistem, bukan milik satu app —
    mirror string-nya harus tetap identik."""
    CS1 = "CS1", "Sangat Baik"
    CS2 = "CS2", "Baik"
    CS3 = "CS3", "Sedang"
    CS4 = "CS4", "Buruk"
    CS5 = "CS5", "Gagal / Kritis"


class AssetTypeChoices(models.TextChoices):
    """Dimirror dari Asset.AssetType (apps/assets/models.py), alasan sama:
    asset-registry.md §1 adalah taksonomi FIXED lintas app."""
    BRIDGE = "bridge", "Jembatan"
    BUILDING = "building", "Gedung"
    CULVERT = "culvert", "Gorong-gorong / Box Culvert"
    TUNNEL = "tunnel", "Terowongan"
    DAM = "dam", "Bendungan / Tanggul"
    PIPELINE = "pipeline", "Pipa / Saluran Tertutup"
    RETAINING_WALL = "retaining_wall", "Dinding Penahan Tanah"


class MaintenanceIntervention(BaseModel):
    """database.md §5 (catalog). SENGAJA tanpa organization_id — katalog
    global lintas organisasi, disepakati eksplisit dengan product owner:
    database.md §5 mendefinisikan tabel ini tanpa kolom organization_id,
    dan engineering-rules.md §8 hanya mewajibkan scoping untuk model yang
    sudah punya organization_id (langsung atau via FK chain ke Asset) —
    tabel ini tidak FK ke Asset sama sekali (hanya asset_type generik),
    jadi aturan itu tidak berlaku di sini tanpa perlu ditafsirkan ulang."""

    class InterventionType(models.TextChoices):
        MINOR = "minor", "Minor"
        MAJOR = "major", "Major"
        REPLACEMENT = "replacement", "Replacement"

    asset_type = models.CharField(max_length=32, choices=AssetTypeChoices.choices)
    intervention_type = models.CharField(max_length=20, choices=InterventionType.choices)
    name = models.CharField(max_length=255)
    unit_cost = models.DecimalField(max_digits=14, decimal_places=2)
    state_improvement = models.JSONField(
        help_text='e.g. {"CS4":"CS2"} -- lompatan state yang diharapkan jika diterapkan.'
    )
    duration_days = models.IntegerField()
    min_interval_years = models.IntegerField(
        null=True,
        blank=True,
        help_text=(
            "Amandemen aditif ke database.md §5 -- scheduling.md §3.3 "
            "menyebut 'min_interval(i)' sebagai fixed lookup value pada "
            "katalog, tapi kolomnya belum ada di dokumen sumber. Hanya "
            "relevan untuk intervention_type IN (major, replacement); "
            "NULL untuk minor (tidak ada constraint jarak minimum)."
        ),
    )

    class Meta:
        db_table = "maintenance_intervention"

    def __str__(self):
        return f"{self.name} ({self.get_intervention_type_display()})"


class MaintenancePlan(BaseModel):
    """database.md §5."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        OPTIMIZING = "optimizing", "Sedang Dioptimasi"
        OPTIMIZED = "optimized", "Teroptimasi"
        APPROVED = "approved", "Disetujui"
        REJECTED = "rejected", "Ditolak"

    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="maintenance_plans"
    )
    name = models.CharField(max_length=255)
    budget_total = models.DecimalField(max_digits=16, decimal_places=2)
    planning_horizon_years = models.IntegerField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    budget_profile = models.JSONField(
        null=True,
        blank=True,
        help_text=(
            'Amandemen aditif ke database.md §5 -- scheduling.md §3.1 '
            'secara eksplisit mensyaratkan budget_profile custom per-tahun '
            '("both supported via a budget_profile input, defaulting to '
            'flat"), tapi kolomnya belum ada di dokumen sumber. '
            'e.g. {"2027": "500000000.00", "2028": "500000000.00"}. '
            'NULL = flat (budget_total / planning_horizon_years), default.'
        ),
    )

    objects = OrganizationScopedManager()

    class Meta:
        db_table = "maintenance_plan"

    def __str__(self):
        return f"{self.name} ({self.organization.name})"


class OptimizationRun(BaseModel):
    """database.md §5."""

    class Status(models.TextChoices):
        QUEUED = "queued", "Antrean"
        RUNNING = "running", "Berjalan"
        FEASIBLE = "feasible", "Feasible"
        OPTIMAL = "optimal", "Optimal"
        INFEASIBLE = "infeasible", "Infeasible"
        FAILED = "failed", "Gagal"

    plan = models.ForeignKey(MaintenancePlan, on_delete=models.CASCADE, related_name="optimization_runs")
    solver = models.CharField(max_length=50, default="cp_sat")
    objective_value = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    runtime_seconds = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    solved_at = models.DateTimeField(null=True, blank=True)
    solver_log_ref = models.CharField(
        max_length=500,
        null=True,
        blank=True,
        help_text="SeaweedFS object key untuk full solver log (engineering-rules.md §3 -- audit).",
    )

    objects = OrganizationScopedManager(organization_lookup="plan__organization_id")

    class Meta:
        db_table = "maintenance_optimization_run"

    def __str__(self):
        return f"Run {self.id} — {self.plan.name} ({self.status})"


class MaintenanceSchedule(BaseModel):
    """database.md §5. Baris solver output. Immutable setelah plan induknya
    berstatus approved (engineering-rules.md §1: re-optimize membuat
    OptimizationRun + baris baru, tidak pernah edit di tempat) --
    ditegakkan di service layer (Fase 2 langkah 4), bukan di level model.

    UniqueConstraint di bawah menegakkan scheduling.md §3.2: satu
    intervensi per komponen PER TAHUN, discoped per run (satu run boleh
    menjadwalkan intervensi berbeda ke komponen yang sama di tahun-tahun
    berbeda -- constraint-nya bukan "satu intervensi per komponen per run").
    """

    run = models.ForeignKey(OptimizationRun, on_delete=models.CASCADE, related_name="schedule_rows")
    component = models.ForeignKey(
        AssetComponent, on_delete=models.PROTECT, related_name="maintenance_schedules"
    )
    intervention = models.ForeignKey(MaintenanceIntervention, on_delete=models.PROTECT, related_name="+")
    scheduled_year = models.IntegerField()
    cost = models.DecimalField(max_digits=14, decimal_places=2)
    expected_state_after = models.CharField(max_length=3, choices=ConditionStateChoices.choices)

    objects = OrganizationScopedManager(organization_lookup="run__plan__organization_id")

    class Meta:
        db_table = "maintenance_schedule"
        constraints = [
            models.UniqueConstraint(
                fields=["run", "component", "scheduled_year"],
                name="schedule_one_intervention_per_component_per_year",
            ),
        ]

    def __str__(self):
        return f"{self.component} @ {self.scheduled_year}: {self.intervention.name}"
