import django.db.models.deletion
from django.db import migrations, models

import apps.core.db_functions


class Migration(migrations.Migration):

    initial = True
    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Asset",
            fields=[
                ("id", models.UUIDField(primary_key=True, serialize=False, editable=False,
                                         db_default=apps.core.db_functions.RandomUUID())),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("code", models.CharField(max_length=100, unique=True)),
                ("name", models.CharField(max_length=255)),
                ("asset_type", models.CharField(choices=[
                    ("bridge", "Jembatan"), ("building", "Gedung"),
                    ("culvert", "Gorong-gorong / Box Culvert"), ("tunnel", "Terowongan"),
                    ("dam", "Bendungan / Tanggul"), ("pipeline", "Pipa / Saluran Tertutup"),
                    ("retaining_wall", "Dinding Penahan Tanah"),
                ], max_length=32)),
                ("latitude", models.DecimalField(decimal_places=6, max_digits=9)),
                ("longitude", models.DecimalField(decimal_places=6, max_digits=9)),
                ("construction_year", models.IntegerField(blank=True, null=True)),
                ("design_life_years", models.IntegerField(blank=True, null=True)),
                ("importance_weight", models.DecimalField(
                    decimal_places=2, max_digits=4,
                    help_text="asset-registry.md §5: w_b, range [1,10], input kebijakan manual.")),
                ("status", models.CharField(choices=[
                    ("active", "Aktif"), ("monitoring", "Dalam Pemantauan"),
                    ("closed", "Ditutup"), ("decommissioned", "Dinonaktifkan"),
                ], default="active", max_length=20)),
                ("created_by", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                    related_name="+", to="core.user",
                    help_text="Nullable hanya untuk row bootstrap/sistem; row buatan user wajib mengisi ini.")),
                ("organization", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT, related_name="assets",
                    to="core.organization")),
            ],
            options={"db_table": "assets_asset"},
        ),
        migrations.CreateModel(
            name="AssetComponent",
            fields=[
                ("id", models.UUIDField(primary_key=True, serialize=False, editable=False,
                                         db_default=apps.core.db_functions.RandomUUID())),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("component_type", models.CharField(max_length=100)),
                ("criticality_weight", models.DecimalField(decimal_places=3, max_digits=4)),
                ("created_by", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                    related_name="+", to="core.user",
                    help_text="Nullable hanya untuk row bootstrap/sistem; row buatan user wajib mengisi ini.")),
                ("asset", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name="components",
                    to="assets.asset")),
                ("parent_component", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                    related_name="sub_components", to="assets.assetcomponent")),
            ],
            options={"db_table": "assets_component"},
        ),
        migrations.AddConstraint(
            model_name="asset",
            constraint=models.CheckConstraint(
                condition=models.Q(("importance_weight__gte", 1)) & models.Q(("importance_weight__lte", 10)),
                name="asset_importance_weight_range",
            ),
        ),
    ]
