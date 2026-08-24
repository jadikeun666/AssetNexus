"""architecture.md §5: routing WebSocket app sensors."""
from django.urls import re_path

from .consumers import AssetAlertsConsumer

websocket_urlpatterns = [
    re_path(
        r"ws/assets/(?P<asset_id>[0-9a-f-]+)/alerts$",
        AssetAlertsConsumer.as_asgi(),
    ),
]
