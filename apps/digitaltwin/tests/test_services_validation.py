"""
engineering-rules.md §7: setiap formula/logic punya test dengan expected
value yang dihitung tangan -- bukan cuma "jalan tanpa error".

Fixture .glb dibuat langsung di test (via pygltflib), bukan file biner
statis di repo -- lebih transparan untuk direview (triangle count-nya
terlihat jelas dari kode fixture, bukan tersembunyi di file binary).
"""
import struct

import pytest
from pygltflib import (
    GLTF2,
    Accessor,
    Buffer,
    BufferView,
    Mesh,
    Node,
    Primitive,
    Scene,
)

from apps.digitaltwin.services_validation import (
    InvalidGltfError,
    TriangleCountExceededError,
    validate_gltf_bytes,
)


def _build_single_triangle_glb(node_name: str = "girder") -> bytes:
    """
    Fixture: satu mesh, satu primitive TRIANGLES, 3 vertex + 3 index.
    Hitungan tangan: 3 index / 3 = 1 triangle.
    """
    vertices = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
    indices = struct.pack("<3H", 0, 1, 2)
    padding = b"\x00\x00" if len(indices) % 4 != 0 else b""
    buffer_data = vertices + indices + padding

    gltf = GLTF2()
    gltf.scenes = [Scene(nodes=[0])]
    gltf.nodes = [Node(name=node_name, mesh=0)]
    gltf.meshes = [Mesh(primitives=[Primitive(attributes={"POSITION": 0}, indices=1, mode=4)])]
    gltf.buffers = [Buffer(byteLength=len(buffer_data))]
    gltf.bufferViews = [
        BufferView(buffer=0, byteOffset=0, byteLength=len(vertices), target=34962),
        BufferView(buffer=0, byteOffset=len(vertices), byteLength=len(indices), target=34963),
    ]
    gltf.accessors = [
        Accessor(bufferView=0, componentType=5126, count=3, type="VEC3", max=[1, 1, 0], min=[0, 0, 0]),
        Accessor(bufferView=1, componentType=5123, count=3, type="SCALAR"),
    ]
    gltf.set_binary_blob(buffer_data)
    return b"".join(gltf.save_to_bytes())


class TestValidateGltfBytes:
    def test_single_triangle_counted_correctly(self):
        """Hitungan tangan: 1 mesh, 1 primitive, 3 index -> 1 triangle."""
        data = _build_single_triangle_glb(node_name="girder")

        result = validate_gltf_bytes(data, max_triangle_count=150_000)

        assert result.triangle_count == 1
        assert result.node_names == ["girder"]

    def test_raises_when_triangle_count_exceeds_limit(self):
        """1 triangle > batas 0 -> harus raise, bukan lolos diam-diam."""
        data = _build_single_triangle_glb()

        with pytest.raises(TriangleCountExceededError) as exc_info:
            validate_gltf_bytes(data, max_triangle_count=0)

        assert exc_info.value.triangle_count == 1
        assert exc_info.value.max_allowed == 0

    def test_accepts_exactly_at_limit(self):
        """Boundary case: triangle_count == max_triangle_count harus LOLOS
        (bukan strict less-than) -- visualization.md §7 bilang "up to
        ~150k triangles", bukan "kurang dari"."""
        data = _build_single_triangle_glb()

        result = validate_gltf_bytes(data, max_triangle_count=1)

        assert result.triangle_count == 1

    def test_raises_invalid_gltf_error_for_garbage_bytes(self):
        with pytest.raises(InvalidGltfError):
            validate_gltf_bytes(b"this is not a glb file at all", max_triangle_count=150_000)

    def test_multiple_node_names_collected(self):
        """Node tanpa nama (None) tidak masuk daftar -- hanya yang bernama
        yang relevan sebagai join key ke AssetComponent.component_type
        (visualization.md §1)."""
        data = _build_single_triangle_glb(node_name="pier")

        result = validate_gltf_bytes(data, max_triangle_count=150_000)

        assert "pier" in result.node_names
