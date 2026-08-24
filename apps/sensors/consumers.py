"""
architecture.md §5: WebSocket consumer #1 dari 2 yang diizinkan --
/ws/assets/{asset_id}/alerts, push SensorAnomalyDetected real-time.

Belum ada AuthMiddlewareStack (Keycloak realm belum ada, konsisten
stub _current_org_stub di seluruh REST API -- lihat apps/assets/api.py).
Klien harus tahu asset_id yang valid (didapat dari REST API lain yang
sudah org-scoped) -- WebSocket ini sendiri TIDAK memvalidasi org-scoping,
keterbatasan yang sama seperti REST API sampai realm Keycloak digarap.
"""
import json

from channels.generic.websocket import AsyncWebsocketConsumer


class AssetAlertsConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.asset_id = self.scope["url_route"]["kwargs"]["asset_id"]
        self.group_name = f"asset_{self.asset_id}_alerts"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def anomaly_alert(self, event):
        """
        Handler untuk pesan group_send bertipe 'anomaly_alert' (dikirim
        dari apps/sensors/jobs.py push_anomaly_alert_job) -- nama method
        HARUS cocok dengan field 'type' pada group_send (Channels
        otomatis memetakan 'anomaly_alert' -> method anomaly_alert()).
        """
        await self.send(text_data=json.dumps(event["payload"]))
