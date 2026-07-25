from django.db import models

from .db_functions import RandomUUID


class BaseModel(models.Model):
    """
    Kolom bersama sesuai database.md §1: UUID PK dibangkitkan native oleh
    PostgreSQL, timestamp TIMESTAMPTZ (via USE_TZ=True), dan created_by
    di setiap tabel.
    """

    id = models.UUIDField(primary_key=True, db_default=RandomUUID(), editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "core.User",
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
        help_text="Nullable hanya untuk row bootstrap/sistem; row buatan user wajib mengisi ini.",
    )

    class Meta:
        abstract = True


class SoftDeleteModel(models.Model):
    """
    database.md §1: soft delete di semua tabel KECUALI InspectionRecord
    dan SensorReading, yang tidak pernah dihapus sama sekali.
    """

    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    def soft_delete(self, *, using=None):
        from django.utils import timezone
        self.deleted_at = timezone.now()
        self.save(using=using, update_fields=["deleted_at"])


class Organization(BaseModel, SoftDeleteModel):
    name = models.CharField(max_length=255)
    region = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        db_table = "core_organization"

    def __str__(self):
        return self.name


class User(BaseModel):
    """
    STUB untuk Fase 0. Sinkronisasi penuh dari Keycloak masih belum
    dikerjakan. Model ini cuma jadi target FK untuk sekarang.
    """

    class Role(models.TextChoices):
        INSPECTOR = "inspector", "Inspector"
        ANALYST = "analyst", "Analyst"
        MANAGER = "manager", "Manager"
        AUDITOR = "auditor", "Auditor"
        ADMIN = "admin", "Admin"

    keycloak_sub = models.CharField(max_length=255, unique=True)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="users")
    username = models.CharField(max_length=150)
    email = models.EmailField()
    role = models.CharField(max_length=20, choices=Role.choices)

    class Meta:
        db_table = "core_user"

    def __str__(self):
        return self.username
