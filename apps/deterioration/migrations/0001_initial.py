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
            name="DeteriorationModel",
            fields=[
                ("id", models.UUIDField(primary_key=True, serialize=False, editable=False,
                                         db_default=apps.core.db_functions.RandomUUID())),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("model_type", models.CharField(choices=[
                    ("discrete_markov", "Discrete-Time Markov Chain"),
                    ("ctmc_latent", "CTMC with Latent Regime"),
                    ("fuzzy_markov", "Fuzzy Markov Bounds"),
                    ("pinn", "Physics-Informed Neural Network"),
                ], max_length=32)),
                ("parameters", models.JSONField(
                    help_text="Serialized generator matrix / fuzzy bounds / PINN weights reference.")),
                ("fitted_at", models.DateTimeField()),
                ("model_version", models.IntegerField(
                    help_text="Monotonically incrementing per component (engineering-rules.md §3).")),
                ("training_data_hash", models.CharField(
                    max_length=64,
                    help_text="SHA-256 of the ordered inspection records used to fit this model.")),
                ("created_by", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                    related_name="+", to="core.user",
                    help_text="Nullable hanya untuk row bootstrap/sistem; row buatan user wajib mengisi ini.")),
                ("component", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name="deterioration_models",
                    to="assets.assetcomponent")),
            ],
            options={"db_table": "deterioration_model"},
        ),
        migrations.CreateModel(
            name="TransitionMatrix",
            fields=[
                ("id", models.UUIDField(primary_key=True, serialize=False, editable=False,
                                         db_default=apps.core.db_functions.RandomUUID())),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("from_state", models.CharField(choices=[
                    ("CS1", "Sangat Baik"), ("CS2", "Baik"), ("CS3", "Sedang"),
                    ("CS4", "Buruk"), ("CS5", "Gagal / Kritis"),
                ], max_length=3)),
                ("to_state", models.CharField(choices=[
                    ("CS1", "Sangat Baik"), ("CS2", "Baik"), ("CS3", "Sedang"),
                    ("CS4", "Buruk"), ("CS5", "Gagal / Kritis"),
                ], max_length=3)),
                ("rate_or_probability", models.DecimalField(decimal_places=6, max_digits=10)),
                ("fuzzy_lower", models.DecimalField(blank=True, decimal_places=6, max_digits=10, null=True)),
                ("fuzzy_upper", models.DecimalField(blank=True, decimal_places=6, max_digits=10, null=True)),
                ("created_by", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                    related_name="+", to="core.user",
                    help_text="Nullable hanya untuk row bootstrap/sistem; row buatan user wajib mengisi ini.")),
                ("model", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name="transition_rows",
                    to="deterioration.deteriorationmodel")),
            ],
            options={"db_table": "deterioration_transition_matrix"},
        ),
        migrations.CreateModel(
            name="DegradationForecast",
            fields=[
                ("id", models.UUIDField(primary_key=True, serialize=False, editable=False,
                                         db_default=apps.core.db_functions.RandomUUID())),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("forecast_year", models.IntegerField()),
                ("state_probabilities", models.JSONField(
                    help_text='e.g. {"CS1":0.02,"CS2":0.10,...} — sums to 1.0')),
                ("expected_state", models.CharField(choices=[
                    ("CS1", "Sangat Baik"), ("CS2", "Baik"), ("CS3", "Sedang"),
                    ("CS4", "Buruk"), ("CS5", "Gagal / Kritis"),
                ], max_length=3)),
                ("confidence_width", models.DecimalField(
                    blank=True, decimal_places=3, max_digits=4, null=True,
                    help_text="Derived from fuzzy bounds (formulas.md §3.2) — NULL until Fase 1.")),
                ("created_by", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                    related_name="+", to="core.user",
                    help_text="Nullable hanya untuk row bootstrap/sistem; row buatan user wajib mengisi ini.")),
                ("model", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name="forecasts",
                    to="deterioration.deteriorationmodel")),
            ],
            options={"db_table": "deterioration_forecast"},
        ),
        migrations.AddIndex(
            model_name="deteriorationmodel",
            index=models.Index(fields=["component", "model_type", "-model_version"],
                                name="deteriorat_compone_9e5f9c_idx"),
        ),
        migrations.AddConstraint(
            model_name="deteriorationmodel",
            constraint=models.UniqueConstraint(
                fields=("component", "model_version"),
                name="deterioration_model_version_unique_per_component",
            ),
        ),
        migrations.AddConstraint(
            model_name="transitionmatrix",
            constraint=models.UniqueConstraint(
                fields=("model", "from_state", "to_state"),
                name="transition_matrix_unique_cell_per_model",
            ),
        ),
        migrations.AddIndex(
            model_name="degradationforecast",
            index=models.Index(fields=["model", "forecast_year"], name="deterior_model_i_a1b2c3_idx"),
        ),
        migrations.AddConstraint(
            model_name="degradationforecast",
            constraint=models.UniqueConstraint(
                fields=("model", "forecast_year"),
                name="forecast_unique_year_per_model",
            ),
        ),
    ]
