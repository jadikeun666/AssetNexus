import django.db.models.deletion
from django.db import migrations, models

import apps.core.db_functions


class Migration(migrations.Migration):

    initial = True
    dependencies = [
        ("core", "0001_initial"),
        ("assets", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="MaintenanceIntervention",
            fields=[
                ("id", models.UUIDField(primary_key=True, serialize=False, editable=False,
                                         db_default=apps.core.db_functions.RandomUUID())),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("asset_type", models.CharField(choices=[
                    ("bridge", "Jembatan"), ("building", "Gedung"),
                    ("culvert", "Gorong-gorong / Box Culvert"), ("tunnel", "Terowongan"),
                    ("dam", "Bendungan / Tanggul"), ("pipeline", "Pipa / Saluran Tertutup"),
                    ("retaining_wall", "Dinding Penahan Tanah"),
                ], max_length=32)),
                ("intervention_type", models.CharField(choices=[
                    ("minor", "Minor"), ("major", "Major"), ("replacement", "Replacement"),
                ], max_length=20)),
                ("name", models.CharField(max_length=255)),
                ("unit_cost", models.DecimalField(decimal_places=2, max_digits=14)),
                ("state_improvement", models.JSONField(
                    help_text='e.g. {"CS4":"CS2"} -- lompatan state yang diharapkan jika diterapkan.')),
                ("duration_days", models.IntegerField()),
                ("min_interval_years", models.IntegerField(
                    blank=True, null=True,
                    help_text=(
                        "Amandemen aditif ke database.md §5 -- scheduling.md §3.3 "
                        "menyebut 'min_interval(i)' sebagai fixed lookup value pada "
                        "katalog, tapi kolomnya belum ada di dokumen sumber. Hanya "
                        "relevan untuk intervention_type IN (major, replacement); "
                        "NULL untuk minor (tidak ada constraint jarak minimum)."
                    ))),
                ("created_by", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                    related_name="+", to="core.user",
                    help_text="Nullable hanya untuk row bootstrap/sistem; row buatan user wajib mengisi ini.")),
            ],
            options={"db_table": "maintenance_intervention"},
        ),
        migrations.CreateModel(
            name="MaintenancePlan",
            fields=[
                ("id", models.UUIDField(primary_key=True, serialize=False, editable=False,
                                         db_default=apps.core.db_functions.RandomUUID())),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=255)),
                ("budget_total", models.DecimalField(decimal_places=2, max_digits=16)),
                ("planning_horizon_years", models.IntegerField()),
                ("status", models.CharField(choices=[
                    ("draft", "Draft"), ("optimizing", "Sedang Dioptimasi"),
                    ("optimized", "Teroptimasi"), ("approved", "Disetujui"),
                    ("rejected", "Ditolak"),
                ], default="draft", max_length=20)),
                ("budget_profile", models.JSONField(
                    blank=True, null=True,
                    help_text=(
                        'Amandemen aditif ke database.md §5 -- scheduling.md §3.1 '
                        'secara eksplisit mensyaratkan budget_profile custom per-tahun '
                        '("both supported via a budget_profile input, defaulting to '
                        'flat"), tapi kolomnya belum ada di dokumen sumber. '
                        'e.g. {"2027": "500000000.00", "2028": "500000000.00"}. '
                        'NULL = flat (budget_total / planning_horizon_years), default.'
                    ))),
                ("created_by", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                    related_name="+", to="core.user",
                    help_text="Nullable hanya untuk row bootstrap/sistem; row buatan user wajib mengisi ini.")),
                ("organization", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT, related_name="maintenance_plans",
                    to="core.organization")),
            ],
            options={"db_table": "maintenance_plan"},
        ),
        migrations.CreateModel(
            name="OptimizationRun",
            fields=[
                ("id", models.UUIDField(primary_key=True, serialize=False, editable=False,
                                         db_default=apps.core.db_functions.RandomUUID())),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("solver", models.CharField(default="cp_sat", max_length=50)),
                ("objective_value", models.DecimalField(
                    blank=True, decimal_places=4, max_digits=18, null=True)),
                ("status", models.CharField(choices=[
                    ("queued", "Antrean"), ("running", "Berjalan"), ("feasible", "Feasible"),
                    ("optimal", "Optimal"), ("infeasible", "Infeasible"), ("failed", "Gagal"),
                ], default="queued", max_length=20)),
                ("runtime_seconds", models.DecimalField(
                    blank=True, decimal_places=2, max_digits=8, null=True)),
                ("solved_at", models.DateTimeField(blank=True, null=True)),
                ("solver_log_ref", models.CharField(
                    blank=True, max_length=500, null=True,
                    help_text="SeaweedFS object key untuk full solver log (engineering-rules.md §3 -- audit).")),
                ("created_by", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                    related_name="+", to="core.user",
                    help_text="Nullable hanya untuk row bootstrap/sistem; row buatan user wajib mengisi ini.")),
                ("plan", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name="optimization_runs",
                    to="maintenance.maintenanceplan")),
            ],
            options={"db_table": "maintenance_optimization_run"},
        ),
        migrations.CreateModel(
            name="MaintenanceSchedule",
            fields=[
                ("id", models.UUIDField(primary_key=True, serialize=False, editable=False,
                                         db_default=apps.core.db_functions.RandomUUID())),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("scheduled_year", models.IntegerField()),
                ("cost", models.DecimalField(decimal_places=2, max_digits=14)),
                ("expected_state_after", models.CharField(choices=[
                    ("CS1", "Sangat Baik"), ("CS2", "Baik"), ("CS3", "Sedang"),
                    ("CS4", "Buruk"), ("CS5", "Gagal / Kritis"),
                ], max_length=3)),
                ("created_by", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                    related_name="+", to="core.user",
                    help_text="Nullable hanya untuk row bootstrap/sistem; row buatan user wajib mengisi ini.")),
                ("run", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name="schedule_rows",
                    to="maintenance.optimizationrun")),
                ("component", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT, related_name="maintenance_schedules",
                    to="assets.assetcomponent")),
                ("intervention", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT, related_name="+",
                    to="maintenance.maintenanceintervention")),
            ],
            options={"db_table": "maintenance_schedule"},
        ),
        migrations.AddConstraint(
            model_name="maintenanceschedule",
            constraint=models.UniqueConstraint(
                fields=("run", "component", "scheduled_year"),
                name="schedule_one_intervention_per_component_per_year",
            ),
        ),
    ]
