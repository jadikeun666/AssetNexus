"""
visualization.md §7: validasi mesh glTF SEBELUM diterima -- mesh di atas
MAX_TRIANGLE_COUNT ditolak dengan error jelas saat upload, tidak dibiarkan
lolos dan mendegradasi performa viewer secara diam-diam.

Fungsi murni (tanpa I/O, tanpa Django ORM) -- testable dengan fixture .glb
kecil, mengikuti disiplin build_and_solve() di
apps/maintenance/services_scheduling.py (engineering-rules.md §7).
"""
from dataclasses import dataclass

from pygltflib import GLTF2


class InvalidGltfError(Exception):
    """Raised saat file bukan glTF/GLB valid, atau gagal di-parse."""


class TriangleCountExceededError(Exception):
    """Raised saat triangle count > DIGITAL_TWIN['MAX_TRIANGLE_COUNT']."""

    def __init__(self, triangle_count: int, max_allowed: int):
        self.triangle_count = triangle_count
        self.max_allowed = max_allowed
        super().__init__(
            f"Mesh punya {triangle_count} triangle, melebihi batas "
            f"{max_allowed} (visualization.md §7). Sederhanakan/decimate "
            f"mesh di tool eksternal sebelum upload -- AssetNexus tidak "
            f"melakukan mesh simplification sendiri."
        )


@dataclass(frozen=True)
class GltfValidationResult:
    triangle_count: int
    node_names: list[str]


def _count_triangles_for_primitive(gltf: GLTF2, primitive) -> int:
    """
    Menghitung triangle count satu primitive. Diasumsikan mode TRIANGLES
    (mode=4, default glTF kalau mode tidak di-set) -- mode lain (strip/fan)
    di luar scope karena photogrammetry/authoring tool standar (Blender,
    RealityCapture, dll) mengekspor TRIANGLES secara default.
    """
    mode = primitive.mode if primitive.mode is not None else 4  # 4 = TRIANGLES
    if mode != 4:
        raise InvalidGltfError(
            f"Primitive mode={mode} tidak didukung -- hanya mode TRIANGLES "
            f"(mode=4) yang divalidasi (visualization.md §7 mengasumsikan "
            f"export standar dari tool photogrammetry/authoring)."
        )

    if primitive.indices is not None:
        # Indexed geometry: jumlah index / 3 = jumlah triangle.
        accessor = gltf.accessors[primitive.indices]
        return accessor.count // 3

    # Non-indexed geometry: jumlah vertex posisi / 3.
    position_accessor_idx = primitive.attributes.POSITION
    accessor = gltf.accessors[position_accessor_idx]
    return accessor.count // 3


def validate_gltf_bytes(data: bytes, max_triangle_count: int) -> GltfValidationResult:
    """
    Parse .glb bytes, hitung total triangle count across semua mesh primitive,
    dan kumpulkan node names (untuk verifikasi join key nanti terhadap
    AssetComponent.component_type, visualization.md §1).

    Raises InvalidGltfError kalau parsing gagal, TriangleCountExceededError
    kalau triangle count melebihi max_triangle_count.
    """
    try:
        gltf = GLTF2.load_from_bytes(data)
    except Exception as exc:
        raise InvalidGltfError(f"Gagal parse file sebagai glTF/GLB: {exc}") from exc

    total_triangles = 0
    for mesh in gltf.meshes:
        for primitive in mesh.primitives:
            total_triangles += _count_triangles_for_primitive(gltf, primitive)

    if total_triangles > max_triangle_count:
        raise TriangleCountExceededError(total_triangles, max_triangle_count)

    node_names = [node.name for node in gltf.nodes if node.name]

    return GltfValidationResult(triangle_count=total_triangles, node_names=node_names)
