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
            name="ExportJob",
            fields=[
                ("id", models.UUIDField(primary_key=True, serialize=False, editable=False,
                                         db_default=apps.core.db_functions.RandomUUID())),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("export_type", models.CharField(choices=[
                    ("pdf_inspection", "Laporan Inspeksi (PDF)"),
                    ("pdf_maintenance_plan", "Rencana Pemeliharaan (PDF)"),
                    ("excel_schedule", "Jadwal Pemeliharaan (Excel)"),
                    ("excel_inventory", "Inventaris Aset (Excel)"),
                ], max_length=32)),
                ("reference_id", models.UUIDField(
                    help_text="Points to the Asset/Component/Plan being exported.")),
                ("status", models.CharField(choices=[
                    ("queued", "Antre"), ("processing", "Diproses"),
                    ("done", "Selesai"), ("failed", "Gagal"),
                ], default="queued", max_length=20)),
                ("file_ref", models.CharField(
                    blank=True, max_length=500, null=True,
                    help_text="SeaweedFS object key, NULL until done.")),
                ("failure_reason", models.TextField(blank=True, default="")),
                ("created_by", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                    related_name="+", to="core.user",
                    help_text="Nullable hanya untuk row bootstrap/sistem; row buatan user wajib mengisi ini.")),
                ("requested_by", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT, related_name="export_jobs",
                    to="core.user")),
            ],
            options={"db_table": "exports_job"},
        ),
        migrations.AddIndex(
            model_name="exportjob",
            index=models.Index(fields=["reference_id", "export_type"], name="exports_job_ref_type_idx"),
        ),
    ]
