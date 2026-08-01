"""
visualization.md §4.2: wrench marker di scrubber untuk intervensi
terjadwal dari approved MaintenancePlan, dan warna snap-to-green (150ms,
non-eased) saat playhead melewati tahun itu -- kontras deliberate dari
easing gradient model biasa.

Cross-app read query (digitaltwin -> maintenance), BUKAN orkestrasi
side-effect sinkron yang dilarang engineering-rules.md §6 -- pola sama
dengan services_viewer.py (digitaltwin -> deterioration), murni membaca
data yang sudah ada.

Keputusan desain (disepakati eksplisit product owner, langkah 4e-5):
- "approved plan terbaru" untuk sebuah asset = di antara SEMUA approved
  MaintenancePlan yang PORTOFOLIO-nya mencakup minimal 1 komponen milik
  asset ini (MaintenancePlan TIDAK punya FK ke Asset -- ini plan
  portfolio-level, database.md §5), ambil OptimizationRun dengan
  solved_at TERBARU. SEMUA baris MaintenanceSchedule untuk asset ini
  HARUS berasal dari run yang SAMA (bukan campuran beberapa run/plan
  berbeda) -- supaya wrench marker konsisten merepresentasikan satu plan
  yang disetujui, bukan gado-gado dari plan berbeda.
- Warna snap-to-green SELALU hijau solid literal #2E7D32, TIDAK dihitung
  dari expected_state_after -- dokumen eksplisit menyebut "snap-to-green"
  (bukan "snap-to-computed-color"), dan tujuannya adalah kontras visual
  jelas "model memprediksi" vs "intervensi mengubah", yang akan blur
  kalau warnanya bisa jadi amber untuk intervensi minor. expected_state_after
  tetap disertakan di payload untuk kebutuhan lain (mis. tooltip detail),
  bukan untuk menentukan warna flash itu sendiri.
"""
from __future__ import annotations

import uuid

from apps.maintenance.models import MaintenancePlan, MaintenanceSchedule


class MaintenanceMarkerService:
    """Query read-only untuk wrench marker viewer 3D. Tidak pernah
    menulis ke database."""

    def get_markers(self, organization_id: uuid.UUID, asset_id: uuid.UUID) -> list[dict]:
        base_qs = MaintenanceSchedule.objects.for_organization(organization_id).filter(
            component__asset_id=asset_id,
            run__plan__status=MaintenancePlan.Status.APPROVED,
        )

        latest_row = base_qs.order_by("-run__solved_at").first()
        if latest_row is None:
            return []

        # Semua baris dari run yang SAMA (satu plan approved yang konsisten),
        # bukan campuran run/plan berbeda -- lihat catatan modul di atas.
        rows = base_qs.filter(run_id=latest_row.run_id).select_related(
            "component", "intervention"
        )

        return [
            {
                "component_id": row.component_id,
                "component_type": row.component.component_type,
                "scheduled_year": row.scheduled_year,
                "intervention_name": row.intervention.name,
                "expected_state_after": row.expected_state_after,
            }
            for row in rows
        ]
