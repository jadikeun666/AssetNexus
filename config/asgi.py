"""
architecture.md §5: ProtocolTypeRouter -- HTTP tetap ke Django ASGI app
biasa, WebSocket ke URLRouter dari websocket_urlpatterns.

Broker Dramatiq TIDAK di-set manual di sini lagi -- apps/core/apps.py
CoreConfig.ready() menanganinya secara global untuk semua proses yang
memanggil django.setup() (lihat komentar lengkap di sana untuk bug yang
diperbaiki: broker default library ke localhost:6379, port yang
kebetulan dipakai project predictmaint paralel).
"""
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django  # noqa: E402
django.setup()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from django.core.asgi import get_asgi_application  # noqa: E402

django_asgi_app = get_asgi_application()

from apps.sensors.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": URLRouter(websocket_urlpatterns),
    }
)
