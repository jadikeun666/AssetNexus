"""
exports.md §2: server-side render via WeasyPrint dari template Django,
BUKAN screenshot browser. exports.md §2.2: struktur fixed pdf_inspection.
"""
from datetime import datetime, timezone

from django.template.loader import render_to_string
from weasyprint import HTML

from apps.assets.models import AssetComponent
from apps.deterioration.models import DeteriorationModel
from apps.inspections.models import InspectionRecord

from apps.core.storage import upload_bytes


class InspectionPdfService:
    def _build_context(self, component: AssetComponent) -> dict:
        records = list(
            InspectionRecord.objects.filter(component=component).order_by("inspected_at")
        )
        record_rows = [
            {
                "inspected_at": r.inspected_at.strftime("%Y-%m-%d"),
                "inspector_name": r.inspector.username,
                "method_label": r.get_method_display(),
                "condition_state": r.condition_state,
                "notes": r.notes,
            }
            for r in records
        ]

        # exports.md §2.2 point 4: "If a DeteriorationModel exists for the
        # component" -- ambil versi terbaru saja, bukan seluruh riwayat model.
        latest_model = (
            DeteriorationModel.objects.filter(component=component)
            .order_by("-model_version")
            .prefetch_related("forecasts")
            .first()
        )
        forecast_summary = None
        if latest_model:
            forecasts = latest_model.forecasts.order_by("forecast_year")[:10]
            forecast_summary = {
                "model_type": latest_model.get_model_type_display(),
                "model_version": latest_model.model_version,
                "forecasts": [
                    {"year": f.forecast_year, "expected_state": f.expected_state} for f in forecasts
                ],
            }

        return {
            "asset": component.asset,
            "component": component,
            "date_range_start": records[0].inspected_at.strftime("%Y-%m-%d") if records else "—",
            "date_range_end": records[-1].inspected_at.strftime("%Y-%m-%d") if records else "—",
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "inspection_records": record_rows,
            "forecast_summary": forecast_summary,
        }

    def render(self, component: AssetComponent) -> bytes:
        context = self._build_context(component)
        html_string = render_to_string("exports/pdf_inspection.html", context)
        return HTML(string=html_string).write_pdf()

    def render_and_store(self, component: AssetComponent, export_job_id) -> str:
        pdf_bytes = self.render(component)
        key = f"exports/pdf_inspection/{export_job_id}.pdf"
        return upload_bytes(key, pdf_bytes, content_type="application/pdf")
