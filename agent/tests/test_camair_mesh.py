"""Tests for the CAMair mesh → STL conversion.

This is the seam where 3Shape's indexed vertex/facet list becomes something the
slicing pipeline can read, so a silent error here would surface much later as a
corrupt or subtly wrong model.
"""

import struct

import pytest

from agent import camair  # noqa: F401  — puts _generated on sys.path

import CAMairDataTypes_pb2  # isort: skip

from agent.camair.mesh import facet_marks_to_dict, mesh_to_stl_bytes

STL_HEADER_SIZE = 80
STL_TRIANGLE_SIZE = 50


def _tetrahedron():
    mesh = CAMairDataTypes_pb2.Mesh()
    for x, y, z in [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)]:
        mesh.vertices.add(x=x, y=y, z=z)
    for a, b, c in [(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)]:
        mesh.facets.add(v0Idx=a, v1Idx=b, v2Idx=c)
    return mesh


class TestMeshToStl:
    def test_layout_matches_the_binary_stl_spec(self):
        mesh = _tetrahedron()

        data = mesh_to_stl_bytes(mesh)

        assert len(data) == STL_HEADER_SIZE + 4 + STL_TRIANGLE_SIZE * 4
        (count,) = struct.unpack_from("<I", data, STL_HEADER_SIZE)
        assert count == len(mesh.facets)

    def test_vertices_survive_the_conversion(self):
        mesh = _tetrahedron()

        data = mesh_to_stl_bytes(mesh)

        # First triangle is facet (0, 2, 1) → vertices (0,0,0) (0,1,0) (1,0,0).
        values = struct.unpack_from("<12fH", data, STL_HEADER_SIZE + 4)
        assert values[3:6] == (0.0, 0.0, 0.0)
        assert values[6:9] == (0.0, 1.0, 0.0)
        assert values[9:12] == (1.0, 0.0, 0.0)

    def test_normal_is_derived_when_the_facet_carries_none(self):
        mesh = _tetrahedron()

        data = mesh_to_stl_bytes(mesh)

        nx, ny, nz = struct.unpack_from("<3f", data, STL_HEADER_SIZE + 4)
        # Facet (0,2,1) lies in z=0; its normal must be a unit vector along Z.
        assert pytest.approx((nx * nx + ny * ny + nz * nz), abs=1e-5) == 1.0
        assert pytest.approx(abs(nz), abs=1e-5) == 1.0

    def test_supplied_normal_is_preferred_over_the_cross_product(self):
        mesh = _tetrahedron()
        mesh.facets[0].normal.x = 1.0

        data = mesh_to_stl_bytes(mesh)

        assert struct.unpack_from("<3f", data, STL_HEADER_SIZE + 4) == (1.0, 0.0, 0.0)

    def test_out_of_range_facet_index_is_rejected_up_front(self):
        """Better a clear error here than a corrupt STL the slicer chokes on."""
        mesh = _tetrahedron()
        mesh.facets.add(v0Idx=0, v1Idx=1, v2Idx=99)

        with pytest.raises(ValueError, match="references vertex 99"):
            mesh_to_stl_bytes(mesh)

    def test_empty_mesh_is_rejected(self):
        with pytest.raises(ValueError, match="no geometry"):
            mesh_to_stl_bytes(CAMairDataTypes_pb2.Mesh())


class TestFacetMarks:
    def test_named_groups_are_carried_out_of_the_protobuf_map(self):
        """STL has no per-face metadata, so these have to travel separately."""
        mesh = _tetrahedron()
        mesh.facetMarks["MarginLineArea"].ids.extend([0, 2])
        mesh.facetMarks["OuterSurface"].ids.append(3)

        assert facet_marks_to_dict(mesh) == {
            "MarginLineArea": [0, 2],
            "OuterSurface": [3],
        }

    def test_absent_marks_give_an_empty_dict_not_none(self):
        assert facet_marks_to_dict(_tetrahedron()) == {}
