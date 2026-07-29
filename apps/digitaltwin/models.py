from django.db import models

from apps.assets.models import Asset
from apps.core.managers import OrganizationScopedManager
from apps.core.models import BaseModel, SoftDeleteModel


class DigitalTwinModel(BaseModel, SoftDeleteModel):
    """
    database.md §6, visualization.md §1. Satu row = satu upload .glb per
    asset (bukan per komponen) — mesh gabungan berisi banyak sub-mesh/node
    yang namanya harus cocok 1:1 dengan AssetComponent.component_type
    milik asset yang sama (join key, tidak ada tabel spatial-mapping
    terpisah, visualization.md §1).

    `version` dipakai viewer untuk selalu memuat model TERBARU per asset
    secara default (pola sama dengan DeteriorationModel.model_version,
    engineering-rules.md §3) — keputusan disepakati eksplisit product
    owner, sesi Fase 3.
    """

    class ModelFormat(models.TextChoices):
        GLTF = "gltf", "glTF"

    class Source(models.TextChoices):
        DRONE_PHOTOGRAMMETRY = "drone_photogrammetry", "Fotogrametri Drone"
        MANUAL = "manual", "Manual"
        FEM_IMPORT = "fem_import", "Import FEM"

    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="digital_twin_models")
    model_format = models.CharField(
        max_length=10, choices=ModelFormat.choices, default=ModelFormat.GLTF
    )
    source = models.CharField(max_length=32, choices=Source.choices)
    file_ref = models.CharField(max_length=500, help_text="SeaweedFS object key.")
    version = models.IntegerField()

    objects = OrganizationScopedManager(organization_lookup="asset__organization_id")

    class Meta:
        db_table = "digitaltwin_digitaltwinmodel"
        constraints = [
            models.UniqueConstraint(
                fields=["asset", "version"], name="digitaltwinmodel_asset_version_unique"
            ),
        ]

    def __str__(self):
        return f"{self.asset.code} — v{self.version} ({self.model_format})"
