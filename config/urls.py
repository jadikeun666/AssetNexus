from django.urls import path
from ninja import NinjaAPI

from apps.assets.api import router as assets_router
from apps.inspections.api import router as inspections_router
from apps.exports.api import router as exports_router
from apps.deterioration.api import router as deterioration_router
from apps.maintenance.api import router as maintenance_router

api = NinjaAPI(title="AssetNexus API", version="0.1.0")
api.add_router("/assets/", assets_router)
api.add_router("/inspections/", inspections_router)
api.add_router("/exports/", exports_router)
api.add_router("/deterioration/", deterioration_router)
api.add_router("/maintenance/", maintenance_router)

urlpatterns = [
    path("api/", api.urls),
]
