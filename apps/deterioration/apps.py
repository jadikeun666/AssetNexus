from django.apps import AppConfig


class DeteriorationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.deterioration"
    label = "deterioration"

    def ready(self):
        # engineering-rules.md §4: JAX defaults to float32, insufficient
        # precision for matrix exponentiation/fractional power of
        # transition-rate matrices — must be overridden explicitly at
        # application startup, never left to the default.
        import jax
        jax.config.update("jax_enable_x64", True)
