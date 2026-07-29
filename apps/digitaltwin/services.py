"""
architecture.md §3: business/engineering logic di Service, bukan di Ninja
router. visualization.md §1: upload flow -- Analyst/Admin upload .glb ->
divalidasi (services_validation.py) -> SeaweedFS -> DigitalTwinModel.
"""
import logging
import uuid

from apps.assets.models import Asset
from apps.core.storage import get_s3_client, upload_bytes
from apps.digitaltwin.models import DigitalTwinModel
from apps.digitaltwin.services_validation import validate_gltf_bytes
from config.assetnexus import DIGITAL_TWIN
from django.conf import settings

logger = logging.getLogger(__name__)


class DigitalTwinUploadService:
    """
    Orkestrasi upload glTF: validasi (fail-fast SEBELUM upload ke storage,
    visualization.md §7) -> SeaweedFS -> row DigitalTwinModel baru.

    Upload SeaweedFS (I/O jaringan) SENGAJA di luar transaction.atomic()
    -- menahan koneksi/transaksi DB terbuka selama panggilan jaringan
    adalah anti-pattern (blocking connection pool, risiko lock timeout).
    SeaweedFS (S3-compatible) tidak ikut serta dalam transaksi Postgres
    (tidak ada two-phase commit lintas sistem) -- kalau create() row gagal
    SETELAH upload sukses (mis. race condition unique constraint asset+
    version dari 2 upload bersamaan), dijalankan aksi kompensasi (hapus
    objek yang baru diupload) supaya tidak ada file yatim tersisa di
    storage. Ini pola standar (compensating action / saga) untuk resource
    non-transactional -- dipilih daripada Dramatiq async (opsi B) karena
    DigitalTwinModel (database.md §6) tidak punya field status seperti
    ExportJob, dan menambahnya adalah amandemen skema yang lebih besar
    dari yang dibutuhkan untuk masalah ini.

    Key SeaweedFS dibangun dari id row (UUID, digenerate eksplisit di
    Python SEBELUM create()) -- bukan dari version -- supaya id sudah
    diketahui sebelum upload, dan konsisten dengan database.md §1 (PK
    UUID, bukan sekuensial/dapat ditebak).
    """

    def upload(
        self,
        *,
        asset: Asset,
        data: bytes,
        source: str,
        created_by=None,
    ) -> DigitalTwinModel:
        validation_result = validate_gltf_bytes(
            data, max_triangle_count=DIGITAL_TWIN["MAX_TRIANGLE_COUNT"]
        )

        last_version = (
            DigitalTwinModel.objects.filter(asset=asset)
            .order_by("-version")
            .values_list("version", flat=True)
            .first()
        ) or 0
        new_version = last_version + 1

        model_id = uuid.uuid4()
        key = f"digitaltwin/{asset.id}/{model_id}.glb"

        upload_bytes(key, data, content_type="model/gltf-binary")

        try:
            model = DigitalTwinModel.objects.create(
                id=model_id,
                asset=asset,
                model_format=DigitalTwinModel.ModelFormat.GLTF,
                source=source,
                file_ref=key,
                version=new_version,
                created_by=created_by,
            )
        except Exception:
            # Aksi kompensasi: row gagal dibuat (mis. race condition pada
            # UniqueConstraint asset+version) -- hapus objek yang sudah
            # terlanjur diupload supaya tidak ada file yatim di SeaweedFS.
            logger.warning(
                "DigitalTwinModel.create() gagal untuk key=%s, menjalankan "
                "kompensasi (hapus objek SeaweedFS)", key,
            )
            get_s3_client().delete_object(Bucket=settings.SEAWEEDFS["BUCKET"], Key=key)
            raise

        return model
