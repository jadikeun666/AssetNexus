"""
architecture.md §1: SeaweedFS (S3-compatible) via boto3. Ini satu-satunya
titik akses ke object storage di seluruh project — jangan panggil boto3
langsung dari service/job lain, selalu lewat wrapper ini.

Sengaja ditaruh di apps/core (bukan apps/exports) karena architecture.md
§2 mendefinisikan `core` sebagai app cross-cutting, dan sejak Fase 2
wrapper ini sudah dipakai lintas domain: apps/exports (PDF/Excel) dan
apps/maintenance (solver_log_ref, scheduling.md §5) — bukan cuma exports.
Dipindah dari apps/exports/storage.py ke apps/core/storage.py sebagai
amandemen disengaja sesi Fase 3 (viewer digital twin butuh upload glTF
ke SeaweedFS juga) — lihat claude.md untuk catatan revisi lengkap.
"""
import boto3
from django.conf import settings


def get_s3_client():
    cfg = settings.SEAWEEDFS
    return boto3.client(
        "s3",
        endpoint_url=cfg["S3_ENDPOINT"],
        aws_access_key_id=cfg["S3_ACCESS_KEY"],
        aws_secret_access_key=cfg["S3_SECRET_KEY"],
    )


def ensure_bucket_exists():
    """
    Idempotent by design: mengandalkan try/except pada create_bucket,
    bukan cek list_buckets() dulu -- SeaweedFS S3 gateway tidak selalu
    konsisten antara hasil list_buckets() dan status create_bucket()
    (BucketAlreadyOwnedByYou bisa muncul walau bucket sempat tidak
    terlihat di listing). Menangkap error spesifik ini adalah cara yang
    benar untuk operasi idempotent -- bukan celah race condition yang
    diabaikan.
    """
    import botocore.exceptions

    client = get_s3_client()
    bucket = settings.SEAWEEDFS["BUCKET"]
    try:
        client.create_bucket(Bucket=bucket)
    except client.exceptions.BucketAlreadyOwnedByYou:
        pass
    except botocore.exceptions.ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            raise


def upload_bytes(key: str, data: bytes, content_type: str) -> str:
    """Upload dan kembalikan object key (bukan URL — file_ref di
    database.md §6 didefinisikan sebagai SeaweedFS object key)."""
    ensure_bucket_exists()
    client = get_s3_client()
    client.put_object(
        Bucket=settings.SEAWEEDFS["BUCKET"], Key=key, Body=data, ContentType=content_type
    )
    return key


def download_bytes(key: str) -> bytes:
    client = get_s3_client()
    response = client.get_object(Bucket=settings.SEAWEEDFS["BUCKET"], Key=key)
    return response["Body"].read()
