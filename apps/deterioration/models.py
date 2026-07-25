from django.db import models

from apps.assets.models import AssetComponent
from apps.core.managers import OrganizationScopedManager
from apps.core.models import BaseModel


class ConditionStateChoices(models.TextChoices):
    """Diulang di sini (bukan di-import dari InspectionRecord) karena
    asset-registry.md §3 menegaskan ini vocabulary bersama seluruh sistem,
    bukan milik satu app — mirror string-nya harus tetap identik."""
    CS1 = "CS1", "Sangat Baik"
    CS2 = "CS2", "Baik"
    CS3 = "CS3", "Sedang"
    CS4 = "CS4", "Buruk"
    CS5 = "CS5", "Gagal / Kritis"


class DeteriorationModel(BaseModel):
    """database.md §4. Immutable secara praktik: sebuah fit baru selalu
    menaikkan model_version, tidak pernah menimpa versi lama
    (engineering-rules.md §3 — auditability lintas waktu)."""

    class ModelType(models.TextChoices):
        DISCRETE_MARKOV = "discrete_markov", "Discrete-Time Markov Chain"
        CTMC_LATENT = "ctmc_latent", "CTMC with Latent Regime"       # Fase 1
        FUZZY_MARKOV = "fuzzy_markov", "Fuzzy Markov Bounds"          # Fase 1
        PINN = "pinn", "Physics-Informed Neural Network"             # Fase 4

    component = models.ForeignKey(
        AssetComponent, on_delete=models.CASCADE, related_name="deterioration_models"
    )
    model_type = models.CharField(max_length=32, choices=ModelType.choices)
    parameters = models.JSONField(
        help_text="Serialized generator matrix / fuzzy bounds / PINN weights reference."
    )
    fitted_at = models.DateTimeField()
    model_version = models.IntegerField(
        help_text="Monotonically incrementing per component (engineering-rules.md §3)."
    )
    training_data_hash = models.CharField(
        max_length=64,
        help_text="SHA-256 of the ordered inspection records used to fit this model.",
    )

    objects = OrganizationScopedManager(organization_lookup="component__asset__organization_id")

    class Meta:
        db_table = "deterioration_model"
        constraints = [
            models.UniqueConstraint(
                fields=["component", "model_version"], name="deterioration_model_version_unique_per_component"
            ),
        ]
        indexes = [
            models.Index(fields=["component", "model_type", "-model_version"]),
        ]

    def __str__(self):
        return f"{self.component} — {self.model_type} v{self.model_version}"


class TransitionMatrix(BaseModel):
    """database.md §4. Satu row per pasangan (from_state, to_state) yang
    valid (asset-registry.md §3: j >= i saja, deterioration-only)."""

    model = models.ForeignKey(DeteriorationModel, on_delete=models.CASCADE, related_name="transition_rows")
    from_state = models.CharField(max_length=3, choices=ConditionStateChoices.choices)
    to_state = models.CharField(max_length=3, choices=ConditionStateChoices.choices)
    rate_or_probability = models.DecimalField(max_digits=10, decimal_places=6)
    fuzzy_lower = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    fuzzy_upper = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)

    class Meta:
        db_table = "deterioration_transition_matrix"
        constraints = [
            models.UniqueConstraint(
                fields=["model", "from_state", "to_state"], name="transition_matrix_unique_cell_per_model"
            ),
        ]

    def __str__(self):
        return f"{self.model_id}: {self.from_state} -> {self.to_state} = {self.rate_or_probability}"


class DegradationForecast(BaseModel):
    """database.md §4. Satu row per tahun kalender per model."""

    model = models.ForeignKey(DeteriorationModel, on_delete=models.CASCADE, related_name="forecasts")
    forecast_year = models.IntegerField()
    state_probabilities = models.JSONField(help_text='e.g. {"CS1":0.02,"CS2":0.10,...} — sums to 1.0')
    expected_state = models.CharField(max_length=3, choices=ConditionStateChoices.choices)
    confidence_width = models.DecimalField(
        max_digits=6, decimal_places=3, null=True, blank=True,
        help_text=(
            "Derived from fuzzy bounds (formulas.md §3.2). "
            "max_digits=6 (bukan 4) -- amandemen database.md §4: nilai ini "
            "selisih dua centroid() di skala condition_score 0-100, bisa "
            "melebihi 10 pada uncertainty tinggi; NUMERIC(4,3) overflow "
            "ditemukan saat membangun visualization.md §5 chart."
        ),
    )

    class Meta:
        db_table = "deterioration_forecast"
        constraints = [
            models.UniqueConstraint(
                fields=["model", "forecast_year"], name="forecast_unique_year_per_model"
            ),
        ]
        indexes = [
            models.Index(fields=["model", "forecast_year"]),  # database.md §7: hot lookup path
        ]

    def __str__(self):
        return f"{self.model_id} @ {self.forecast_year}: {self.expected_state}"
