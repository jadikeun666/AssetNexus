"""
Ninja schemas untuk app digitaltwin. Payload viewer (visualization.md
§4.1) dan response upload (visualization.md §1) -- bukan endpoint umum
CRUD DigitalTwinModel.
"""
import uuid
from typing import Optional

from ninja import Schema


class DigitalTwinModelOut(Schema):
    id: uuid.UUID
    file_ref: str
    version: int


class DigitalTwinUploadOut(Schema):
    id: uuid.UUID
    asset_id: uuid.UUID
    file_ref: str
    version: int


class ViewerPayloadOut(Schema):
    asset_id: uuid.UUID
    digital_twin_model: Optional[DigitalTwinModelOut] = None
    # forecast_by_component: {component_id (str): {forecast_year (str): condition_score}}
    # -- key dict di JSON WAJIB string (JSON tidak punya integer key), jadi
    # UUID dan tahun keduanya di-stringify di services_viewer.py sebelum
    # sampai sini (visualization.md §4.1).
    forecast_by_component: dict[str, dict[str, float]]
