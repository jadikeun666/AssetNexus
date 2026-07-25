from django.apps import AppConfig


class InspectionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.inspections"
    label = "inspections"

    def ready(self):
        from . import signals  # noqa: F401
