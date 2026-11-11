"""agent-large-model-perf, spec stl-upload-validation (design D2).

_validate_stl_bytes checks the header and size only, with rules that follow
how slicer-engine's admesh reads the file: binary must match its header's
triangle count exactly (admesh counts triangles from the file size), and
ASCII is accepted only when admesh would also read it as ASCII.
"""

import struct
import time

import numpy as np
import pytest
import trimesh

from agent import api_v2
from agent.errors import APIError


def _binary(faces: int, header: bytes = b"", data_faces=None, tail: bytes = b"") -> bytes:
    data_faces = faces if data_faces is None else data_faces
    head = header.ljust(80, b"\x00")[:80]
    rng = np.random.default_rng(0)
    # Negative floats guarantee bytes > 127 in admesh's 84..211 sniff window.
    body = rng.uniform(-50, -1, size=(data_faces, 12)).astype("<f4").tobytes()
    records = b"".join(body[i * 48:(i + 1) * 48] + b"\x00\x00" for i in range(data_faces))
    return head + struct.pack("<I", faces) + records + tail


ASCII = (
    b"solid part\n"
    b" facet normal 0 0 1\n  outer loop\n"
    b"   vertex 0 0 0\n   vertex 1 0 0\n   vertex 0 1 0\n"
    b"  endloop\n endfacet\n"
    b"endsolid part\n"
)


def _rejected(content: bytes) -> str:
    with pytest.raises(APIError) as excinfo:
        api_v2._validate_stl_bytes(content, "upload.stl")
    assert excinfo.value.code == "INVALID_MODEL"
    assert "upload.stl" in excinfo.value.message
    return excinfo.value.message


class TestBinary:
    def test_exact_size_is_accepted(self):
        api_v2._validate_stl_bytes(_binary(4))

    def test_trimesh_exported_stl_is_accepted(self):
        """Same layout as the frontend's STLExporter output: always exact."""
        data = trimesh.exchange.stl.export_stl(trimesh.creation.icosphere(subdivisions=2))
        api_v2._validate_stl_bytes(data)

    @pytest.mark.parametrize("extra", [37, 50, 100])
    def test_trailing_bytes_are_rejected(self, extra):
        """admesh would read 50-byte multiples as extra garbage triangles."""
        message = _rejected(_binary(4, tail=b"\x00" * extra))
        assert "does not match its header" in message

    def test_truncated_is_rejected(self):
        _rejected(_binary(10, data_faces=7))

    def test_zero_faces_is_rejected(self):
        _rejected(_binary(0, data_faces=3))

    def test_header_starting_with_solid_is_still_binary(self):
        api_v2._validate_stl_bytes(_binary(4, header=b"solid exported by some CAD tool"))

    def test_solid_header_with_facet_and_padding_is_not_taken_for_ascii(self):
        content = _binary(4, header=b"solid facet", tail=b"\x00" * 50)
        assert b"facet" in content
        _rejected(content)

    def test_huge_declared_count_is_rejected_without_allocating(self):
        _rejected(_binary(0x7FFFFFFF, data_faces=3))


class TestAscii:
    def test_plain_ascii_is_accepted(self):
        api_v2._validate_stl_bytes(ASCII)

    def test_bom_and_leading_whitespace_are_allowed(self):
        api_v2._validate_stl_bytes(b"\xef\xbb\xbf" + ASCII)
        api_v2._validate_stl_bytes(b"  \r\n" + ASCII)

    def test_more_than_five_leading_bytes_are_rejected(self):
        _rejected(b"      " + ASCII)

    def test_uppercase_solid_is_accepted(self):
        api_v2._validate_stl_bytes(ASCII.replace(b"solid part", b"SOLID part", 1))

    def test_no_facet_is_rejected(self):
        message = _rejected(b"solid x\nendsolid x\n")
        assert "no triangles" in message

    def test_high_bytes_in_admesh_window_are_rejected(self):
        """admesh would read this as binary, so it must pass the binary rule."""
        content = ASCII[:84].ljust(84, b" ") + b"\xff" + ASCII[84:]
        _rejected(content)


class TestNotStl:
    @pytest.mark.parametrize(
        "content",
        [b"", b"not a real stl", b"not-real-bytes", b"\x00" * 83, b"PK\x03\x04" + b"\x00" * 200],
    )
    def test_rejected(self, content):
        _rejected(content)


def test_validation_does_not_parse_the_mesh(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("trimesh.load must not be called")

    monkeypatch.setattr(trimesh, "load", forbidden)
    api_v2._validate_stl_bytes(_binary(4))
    api_v2._validate_stl_bytes(ASCII)


def test_5m_face_binary_validates_quickly():
    faces = 5_158_000  # TriangleStress_5M's count; about 258 MB
    content = bytearray(84 + faces * 50)
    content[80:84] = struct.pack("<I", faces)
    content[84:212] = b"\xff" * 128
    content = bytes(content)
    start = time.perf_counter()
    api_v2._validate_stl_bytes(content)
    assert time.perf_counter() - start < 0.05


@pytest.mark.parametrize("content", ["not-real-bytes", ["x"], None, 123])
def test_non_bytes_content_is_rejected(content):
    """add_models_to_slice_job() stores raw JSON values as stl_data."""
    _rejected(content)
