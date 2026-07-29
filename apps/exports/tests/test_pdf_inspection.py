from datetime import datetime, timezone
from decimal import Decimal

import pytest

from apps.assets.models import Asset, AssetComponent
from apps.core.models import Organization, User
from apps.exports.jobs import generate_pdf_export_job
from apps.exports.models import ExportJob
from apps.exports.services import InspectionPdfService
from apps.exports.services_api import ExportJobService
from apps.core.storage import download_bytes
from apps.inspections.models import InspectionRecord


@pytest.fixture
def org():
    return Organization.objects.create(name="Dinas PU Test")


@pytest.fixture
def inspector(org):
    return User.objects.create(
        keycloak_sub="sub-export-1", organization=org, username="sari",
        email="sari@example.id", role=User.Role.INSPECTOR,
    )


@pytest.fixture
def component(org):
    asset = Asset.objects.create(
        organization=org, code="BRG-EXP-1", name="Jembatan Export Test",
        asset_type=Asset.AssetType.BRIDGE, latitude=Decimal("0"), longitude=Decimal("0"),
        importance_weight=Decimal("5.00"),
    )
    return AssetComponent.objects.create(asset=asset, component_type="girder", criticality_weight=Decimal("0.250"))


@pytest.mark.django_db
class TestInspectionPdfService:
    def test_render_produces_valid_pdf_bytes(self, component, inspector):
        InspectionRecord.objects.create(
            component=component, inspector=inspector,
            inspected_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
            method=InspectionRecord.Method.VISUAL,
            condition_state=InspectionRecord.ConditionState.CS2,
            notes="Kondisi baik, sedikit korosi permukaan.",
        )
        pdf_bytes = InspectionPdfService().render(component)

        # PDF valid selalu diawali magic bytes %PDF-
        assert pdf_bytes[:5] == b"%PDF-"
        assert len(pdf_bytes) > 500  # bukan file kosong/rusak

    def test_render_includes_forecast_summary_when_model_exists(self, component, inspector):
        from apps.deterioration.services import DiscreteMarkovFittingService, ForecastService

        t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
        InspectionRecord.objects.create(
            component=component, inspector=inspector, inspected_at=t0,
            method=InspectionRecord.Method.VISUAL, condition_state=InspectionRecord.ConditionState.CS1,
        )
        InspectionRecord.objects.create(
            component=component, inspector=inspector,
            inspected_at=t0.replace(year=2024),
            method=InspectionRecord.Method.VISUAL, condition_state=InspectionRecord.ConditionState.CS2,
        )
        model = DiscreteMarkovFittingService().fit(
            organization_id=component.asset.organization_id,
            asset_type="bridge", component_type="girder", component=component,
        )
        ForecastService().generate(model, current_state="CS2", horizon_years=3)

        context = InspectionPdfService()._build_context(component)
        assert context["forecast_summary"] is not None
        assert len(context["forecast_summary"]["forecasts"]) == 3

    def test_render_omits_forecast_summary_when_no_model_exists(self, component, inspector):
        InspectionRecord.objects.create(
            component=component, inspector=inspector,
            inspected_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
            method=InspectionRecord.Method.VISUAL, condition_state=InspectionRecord.ConditionState.CS2,
        )
        context = InspectionPdfService()._build_context(component)
        assert context["forecast_summary"] is None


@pytest.mark.django_db
class TestExportJobEndToEnd:
    """
    architecture.md §4: ExportRequested -> GeneratePdfExportJob.
    fn() dipanggil langsung (bukan .send()) supaya test tidak butuh
    worker Dramatiq terpisah berjalan -- pola standar test Dramatiq.
    """

    def test_full_export_flow_uploads_to_seaweedfs(self, component, inspector):
        InspectionRecord.objects.create(
            component=component, inspector=inspector,
            inspected_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
            method=InspectionRecord.Method.VISUAL, condition_state=InspectionRecord.ConditionState.CS3,
        )

        job = ExportJob.objects.create(
            export_type=ExportJob.ExportType.PDF_INSPECTION,
            reference_id=component.id,
            requested_by=inspector,
        )

        generate_pdf_export_job.fn(str(job.id))

        job.refresh_from_db()
        assert job.status == ExportJob.Status.DONE
        assert job.file_ref == f"exports/pdf_inspection/{job.id}.pdf"
        assert job.failure_reason == ""

        # exports.md §1: "write to SeaweedFS" -- verifikasi file BENAR ada
        # di object storage, bukan cuma percaya field file_ref di DB.
        downloaded = download_bytes(job.file_ref)
        assert downloaded[:5] == b"%PDF-"

    def test_export_job_fails_gracefully_for_nonexistent_component(self, org, inspector):
        import uuid

        job = ExportJob.objects.create(
            export_type=ExportJob.ExportType.PDF_INSPECTION,
            reference_id=uuid.uuid4(),  # komponen tidak ada
            requested_by=inspector,
        )

        with pytest.raises(Exception):
            generate_pdf_export_job.fn(str(job.id))

        job.refresh_from_db()
        # exports.md §5: "never a silent failure"
        assert job.status == ExportJob.Status.FAILED
        assert job.failure_reason != ""

    def test_service_creates_job_and_dispatches(self, component, inspector, monkeypatch):
        """
        Test ExportJobService tanpa benar-benar mengirim ke broker Redis --
        broker.send() di-monkeypatch supaya test ini murni cek
        orchestration-nya (create job + panggil dispatch), bukan
        integrasi Redis penuh (itu sudah dicover test end-to-end di atas
        via .fn()).
        """
        sent_ids = []

        def fake_send(*args, **kwargs):
            sent_ids.append(args[0] if args else None)

        monkeypatch.setattr(
            "apps.exports.services_api.generate_pdf_export_job.send", fake_send
        )

        job = ExportJobService().request_pdf_inspection(component.id, requested_by=inspector)

        assert job.status == ExportJob.Status.QUEUED
        assert job.reference_id == component.id
        assert len(sent_ids) == 1
        assert sent_ids[0] == str(job.id)
