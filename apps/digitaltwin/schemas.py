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


class ComponentForecastOut(Schema):
    """
    visualization.md §1: join key ke node glTF adalah component_type
    (BUKAN component_id) -- component_type WAJIB disertakan di sini,
    bukan hanya component_id, supaya frontend bisa mencari node glTF
    bernama persis component_type dan mewarnainya berdasarkan forecast
    komponen yang cocok. Diubah dari dict murni {component_id: {year:
    score}} (draf pertama) ke list eksplisit ini karena dict tidak punya
    tempat menyimpan component_type tanpa query balik terpisah --
    keputusan disepakati eksplisit product owner, sesi langkah 4d.
    """
    component_id: uuid.UUID
    component_type: str
    # year_scores: {forecast_year (str): condition_score} -- key dict di
    # JSON wajib string (JSON tidak punya integer key).
    year_scores: dict[str, float]


class ViewerPayloadOut(Schema):
    asset_id: uuid.UUID
    digital_twin_model: Optional[DigitalTwinModelOut] = None
    forecast_by_component: list[ComponentForecastOut]


class MaintenanceMarkerOut(Schema):
    """
    visualization.md §4.2: wrench marker + snap-to-green data. Endpoint
    terpisah (bukan digabung ke ViewerPayloadOut) -- payload viewer utama
    di-cache sekali per asset (§4.1) dan tidak bergantung status
    approval MaintenancePlan, sedangkan marker BISA berubah kalau plan
    baru disetujui tanpa forecast deterioration berubah sama sekali;
    memisah endpoint menghindari over-fetching/cache invalidation yang
    tidak perlu untuk kasus umum "belum ada plan approved".
    """
    component_id: uuid.UUID
    component_type: str
    scheduled_year: int
    intervention_name: str
    expected_state_after: str
