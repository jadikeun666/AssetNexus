from django.db import models

from apps.core.managers import OrganizationScopedManager
from apps.core.models import BaseModel, Organization, SoftDeleteModel


class Asset(BaseModel, SoftDeleteModel):
    """
    database.md §2. asset_type adalah taksonomi FIXED — asset-registry.md §1.
    Menambah tipe baru = amandemen dokumen itu dulu, bukan menambah string
    bebas di sini.
    """

    class AssetType(models.TextChoices):
        BRIDGE = "bridge", "Jembatan"
        BUILDING = "building", "Gedung"
        CULVERT = "culvert", "Gorong-gorong / Box Culvert"
        TUNNEL = "tunnel", "Terowongan"
        DAM = "dam", "Bendungan / Tanggul"
        PIPELINE = "pipeline", "Pipa / Saluran Tertutup"
        RETAINING_WALL = "retaining_wall", "Dinding Penahan Tanah"

    class Status(models.TextChoices):
        ACTIVE = "active", "Aktif"
        MONITORING = "monitoring", "Dalam Pemantauan"
        CLOSED = "closed", "Ditutup"
        DECOMMISSIONED = "decommissioned", "Dinonaktifkan"

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="assets")
    code = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=255)
    asset_type = models.CharField(max_length=32, choices=AssetType.choices)
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    construction_year = models.IntegerField(null=True, blank=True)
    design_life_years = models.IntegerField(null=True, blank=True)
    importance_weight = models.DecimalField(
        max_digits=4, decimal_places=2,
        help_text="asset-registry.md §5: w_b, range [1,10], input kebijakan manual.",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)

    objects = OrganizationScopedManager()

    class Meta:
        db_table = "assets_asset"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(importance_weight__gte=1) & models.Q(importance_weight__lte=10),
                name="asset_importance_weight_range",
            ),
        ]

    def __str__(self):
        return f"{self.code} — {self.name}"


class AssetComponent(BaseModel, SoftDeleteModel):
    """
    database.md §2, asset-registry.md §2. Hierarki self-referential.
    component_type sengaja TEXT bebas (bukan enum) karena visualization.md
    §1 mensyaratkan nilainya cocok 1:1 dengan nama node mesh glTF.
    """

    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="components")
    parent_component = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="sub_components"
    )
    component_type = models.CharField(max_length=100)
    criticality_weight = models.DecimalField(max_digits=4, decimal_places=3)

    objects = OrganizationScopedManager(organization_lookup="asset__organization_id")

    class Meta:
        db_table = "assets_component"

    def __str__(self):
        return f"{self.asset.code} / {self.component_type}"
