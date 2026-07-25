import django.db.models.deletion
from django.db import migrations, models

import apps.core.db_functions


class Migration(migrations.Migration):

    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Organization",
            fields=[
                ("id", models.UUIDField(primary_key=True, serialize=False, editable=False,
                                         db_default=apps.core.db_functions.RandomUUID())),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("name", models.CharField(max_length=255)),
                ("region", models.CharField(blank=True, default="", max_length=255)),
            ],
            options={"db_table": "core_organization"},
        ),
        migrations.CreateModel(
            name="User",
            fields=[
                ("id", models.UUIDField(primary_key=True, serialize=False, editable=False,
                                         db_default=apps.core.db_functions.RandomUUID())),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("keycloak_sub", models.CharField(max_length=255, unique=True)),
                ("username", models.CharField(max_length=150)),
                ("email", models.EmailField(max_length=254)),
                ("role", models.CharField(choices=[
                    ("inspector", "Inspector"), ("analyst", "Analyst"),
                    ("manager", "Manager"), ("auditor", "Auditor"), ("admin", "Admin"),
                ], max_length=20)),
                ("organization", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT, related_name="users",
                    to="core.organization")),
                ("created_by", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                    related_name="+", to="core.user")),
            ],
            options={"db_table": "core_user"},
        ),
        migrations.AddField(
            model_name="organization",
            name="created_by",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="+", to="core.user"),
        ),
    ]
