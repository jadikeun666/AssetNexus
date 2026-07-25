"""
Ninja schemas untuk app deterioration.

Endpoint pertama app ini yang diekspos lewat REST (sebelumnya deterioration
murni dipanggil dari jobs.py, event-driven — architecture.md §4). Skema di
sini KHUSUS untuk kebutuhan chart condition trend line (visualization.md
§5, baris "Condition trend line"), bukan endpoint umum untuk seluruh
DeterioriationModel/DegradationForecast.

confidence_lower/confidence_upper Optional (bukan required) karena DTMC
(model_type='discrete_markov') tidak pernah mengisi confidence_width
(engineering-rules.md style — lihat services.py Fase 0) — komponen di
bawah MIN_INSPECTIONS_FOR_CTMC akan tampil dengan band None, ditangani di
frontend sebagai "belum ada band uncertainty", bukan band nol/fiktif.

Band disimetriskan dari confidence_width tunggal (keputusan disepakati
eksplisit dengan product owner sesi ini, BUKAN reinterpretasi diam-diam
formulas.md §3.2 — confidence_width sendiri tidak pernah mendefinisikan
pembagian asimetris, centroid_upper/centroid_lower asli dibuang saat
fitting di services_fuzzy.py dan tidak disimpan; menyimpannya akan butuh
amandemen skema database.md §4, ditunda sebagai item terpisah).
"""
import uuid
from typing import Optional

from ninja import Schema


class ForecastPointOut(Schema):
    forecast_year: int
    condition_score: float
    confidence_lower: Optional[float] = None
    confidence_upper: Optional[float] = None


class ComponentForecastChartOut(Schema):
    component_id: uuid.UUID
    component_type: str
    model_type: str
    model_version: int
    points: list[ForecastPointOut]
