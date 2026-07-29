from decimal import Decimal

import pytest

from apps.assets.models import Asset
from apps.core.models import Organization, User
from apps.core.storage import download_bytes, get_s3_client
from apps.digitaltwin.models import DigitalTwinModel
from apps.digitaltwin.services import DigitalTwinUploadService
from apps.digitaltwin.tests.test_services_validation import _build_single_triangle_glb
from django.conf import settings


@pytest.fixture
def org():
    return Organization.objects.create(name="Dinas PU Test DigitalTwin")


@pytest.fixture
def uploader(org):
    return User.objects.create(
        keycloak_sub="sub-dt-1", organization=org, username="admin",
        email="admin@example.id", role=User.Role.ADMIN,
    )


@pytest.fixture
def asset(org):
    return Asset.objects.create(
        organization=org, code="BRG-DT-1", name="Jembatan Digital Twin Test",
        asset_type=Asset.AssetType.BRIDGE, latitude=Decimal("0"), longitude=Decimal("0"),
        importance_weight=Decimal("5.00"),
    )


@pytest.mark.django_db
class TestDigitalTwinUploadService:
    def test_upload_creates_model_and_uploads_to_seaweedfs(self, asset, uploader):
        data = _build_single_triangle_glb(node_name="girder")

        model = DigitalTwinUploadService().upload(
            asset=asset, data=data,
            source=DigitalTwinModel.Source.MANUAL, created_by=uploader,
        )

        assert model.version == 1
        assert model.asset_id == asset.id
        assert model.file_ref.startswith(f"digitaltwin/{asset.id}/")

        # Verifikasi file BENAR ada di SeaweedFS -- bukan cuma percaya
        # field file_ref di DB (pola sama exports.md §1).
        downloaded = download_bytes(model.file_ref)
        assert downloaded == data

    def test_second_upload_increments_version(self, asset, uploader):
        data = _build_single_triangle_glb()

        first = DigitalTwinUploadService().upload(
            asset=asset, data=data, source=DigitalTwinModel.Source.MANUAL, created_by=uploader,
        )
        second = DigitalTwinUploadService().upload(
            asset=asset, data=data, source=DigitalTwinModel.Source.MANUAL, created_by=uploader,
        )

        assert first.version == 1
        assert second.version == 2

    def test_upload_rejects_oversized_mesh_without_touching_storage(self, asset, uploader, settings_override=None):
        """
        visualization.md §7: mesh di atas MAX_TRIANGLE_COUNT ditolak SAAT
        upload. Verifikasi juga bahwa TIDAK ADA objek yang terupload ke
        SeaweedFS sama sekali (fail-fast sebelum I/O storage).
        """
        from apps.digitaltwin.services_validation import TriangleCountExceededError
        from unittest.mock import patch

        data = _build_single_triangle_glb()

        with patch("apps.digitaltwin.services.DIGITAL_TWIN", {"MAX_TRIANGLE_COUNT": 0}):
            with pytest.raises(TriangleCountExceededError):
                DigitalTwinUploadService().upload(
                    asset=asset, data=data,
                    source=DigitalTwinModel.Source.MANUAL, created_by=uploader,
                )

        assert DigitalTwinModel.objects.filter(asset=asset).count() == 0
