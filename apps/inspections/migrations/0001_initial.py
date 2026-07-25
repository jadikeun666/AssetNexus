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
            name="InspectionRecord",
            fields=[
                ("id", models.UUIDField(primary_key=True, serialize=False, editable=False,
                                         db_default=apps.core.db_functions.RandomUUID())),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("inspected_at", models.DateTimeField()),
                ("method", models.CharField(choices=[
                    ("visual", "Visual"), ("ndt", "Non-destructive Testing"),
                    ("drone_photogrammetry", "Drone Photogrammetry"), ("sensor", "Sensor"),
                ], max_length=32)),
                ("condition_state", models.CharField(blank=True, choices=[
                    ("CS1", "Sangat Baik"), ("CS2", "Baik"), ("CS3", "Sedang"),
                    ("CS4", "Buruk"), ("CS5", "Gagal / Kritis"),
                ], max_length=3, null=True)),
                ("notes", models.TextField(blank=True, default="")),
                ("photo_refs", models.JSONField(blank=True, default=list)),
                ("component", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT, related_name="inspection_records",
                    to="assets.assetcomponent")),
                ("inspector", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT, related_name="inspections_performed",
                    to="core.user")),
                ("supersedes", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                    related_name="superseded_by", to="inspections.inspectionrecord")),
                ("created_by", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                    related_name="+", to="core.user",
                    help_text="Nullable hanya untuk row bootstrap/sistem; row buatan user wajib mengisi ini.")),
            ],
            options={"db_table": "inspections_record"},
        ),
        migrations.AddConstraint(
            model_name="inspectionrecord",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("method", "sensor"), ("condition_state__isnull", True))
                    | (~models.Q(("method", "sensor")) & models.Q(("condition_state__isnull", False)))
                ),
                name="inspection_condition_state_null_iff_sensor_method",
            ),
        ),
    ]
