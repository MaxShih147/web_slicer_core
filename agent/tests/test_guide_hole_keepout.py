"""The drill-hole keep-out: measuring a bore, and dropping what falls in it.

Built on a synthetic guide rather than a patient model - a slab with a bore
through it, where the right answer is known rather than measured. The real
guides are what the numbers in guide_hole_keepout's own docstring came from, and
they are patient data that cannot live in a repository.
"""

import math

import numpy as np
import pytest

from agent.guide_hole_keepout import (
    bores_from_mesh,
    drop_points_in_bores,
    is_in_a_bore,
)


def slab_with_bore(bore_radius=2.0, half_height=5.0, segments=48, half_width=20.0):
    """A square slab with a vertical bore through it, as triangles.

    Only the bore wall and the slab's two flat faces are built: the outer sides
    are not what any of this looks at, and leaving them off keeps the fixture
    readable. The wall's normals point INWARD, at the axis, which is what marks
    it as a bore rather than an outside surface.
    """
    verts = []
    faces = []

    # The bore wall: a ring of quads, each split into two triangles, wound so
    # the normals face the axis.
    for i in range(segments):
        a = 2 * math.pi * i / segments
        b = 2 * math.pi * (i + 1) / segments
        p0 = [bore_radius * math.cos(a), bore_radius * math.sin(a), -half_height]
        p1 = [bore_radius * math.cos(b), bore_radius * math.sin(b), -half_height]
        p2 = [bore_radius * math.cos(b), bore_radius * math.sin(b), half_height]
        p3 = [bore_radius * math.cos(a), bore_radius * math.sin(a), half_height]
        base = len(verts)
        verts += [p0, p1, p2, p3]
        faces += [[base + 0, base + 2, base + 1], [base + 0, base + 3, base + 2]]

    # The two flat faces, well outside the bore, as something for the measuring
    # to correctly ignore.
    for z, flip in ((half_height, False), (-half_height, True)):
        base = len(verts)
        verts += [
            [-half_width, -half_width, z], [half_width, -half_width, z],
            [half_width, half_width, z], [-half_width, half_width, z],
        ]
        tri = [[base + 0, base + 1, base + 2], [base + 0, base + 2, base + 3]]
        faces += [t[::-1] for t in tri] if flip else tri

    return np.asarray(verts, dtype=np.float32), np.asarray(faces, dtype=np.uint32)


def envelope(radius=6.0, length=40.0):
    """What auto_orient_surg_guide hands over: a loose search envelope.

    Its radius is the end face's OUTER radius and its length a fixed
    max(10r, 40) both ways, so it is deliberately much bigger than the bore -
    the point of the measuring is to find the bore inside it.
    """
    return [{"center": [0.0, 0.0, 0.0], "axis": [0.0, 0.0, 1.0],
             "radius": radius, "length": length}]


class TestMeasuringTheBore:
    def test_measures_the_bore_not_the_envelope_it_was_found_in(self):
        verts, faces = slab_with_bore(bore_radius=2.0, half_height=5.0)
        [bore] = bores_from_mesh(verts, faces, envelope(radius=6.0), margin=0.0)

        # The envelope said 6mm and ±40mm; the bore is 2mm and ±5mm.
        assert bore["bore_radius"] == pytest.approx(2.0, abs=0.05)
        assert bore["radius"] == pytest.approx(2.0, abs=0.05)
        assert bore["depth"] == pytest.approx(10.0, abs=0.2)

    def test_the_margin_reaches_past_both_openings(self):
        verts, faces = slab_with_bore(bore_radius=2.0, half_height=5.0)
        [bore] = bores_from_mesh(verts, faces, envelope(), margin=0.5)

        assert bore["radius"] == pytest.approx(2.5, abs=0.05)
        # Past the wall at each end, so the rim circles are covered rather than
        # grazed.
        assert bore["low"] == pytest.approx(-5.5, abs=0.2)
        assert bore["high"] == pytest.approx(5.5, abs=0.2)

    def test_takes_the_wall_and_leaves_the_flat_faces(self):
        verts, faces = slab_with_bore(segments=48)
        [bore] = bores_from_mesh(verts, faces, envelope(), margin=0.0)
        # Two triangles per segment of wall, and not one of the four flat ones.
        assert bore["wall_faces"] == 96

    def test_reports_nothing_for_a_solid_slab(self):
        # No inward-facing wall anywhere: there is no hole, so there is no
        # keep-out. Guessing one would carve supports out of a sound model.
        verts, faces = slab_with_bore()
        wall_faces = 96
        solid_faces = faces[wall_faces:]
        assert bores_from_mesh(verts, solid_faces, envelope(), margin=0.5) == []

    def test_reports_nothing_without_an_envelope_to_look_in(self):
        verts, faces = slab_with_bore()
        assert bores_from_mesh(verts, faces, [], margin=0.5) == []

    def test_reports_nothing_for_an_envelope_with_no_axis(self):
        verts, faces = slab_with_bore()
        broken = [{"center": [0, 0, 0], "axis": [0, 0, 0], "radius": 6.0, "length": 40.0}]
        assert bores_from_mesh(verts, faces, broken, margin=0.5) == []

    def test_a_tilted_bore_is_measured_along_its_own_axis(self):
        verts, faces = slab_with_bore(bore_radius=2.0, half_height=5.0)
        angle = math.radians(30)
        rot = np.array([
            [1, 0, 0],
            [0, math.cos(angle), -math.sin(angle)],
            [0, math.sin(angle), math.cos(angle)],
        ])
        tilted = (rot @ verts.T).T.astype(np.float32)
        env = [{"center": [0.0, 0.0, 0.0],
                "axis": [float(x) for x in rot @ np.array([0.0, 0.0, 1.0])],
                "radius": 6.0, "length": 40.0}]
        [bore] = bores_from_mesh(tilted, faces, env, margin=0.0)

        assert bore["bore_radius"] == pytest.approx(2.0, abs=0.05)
        assert bore["depth"] == pytest.approx(10.0, abs=0.2)


class TestWhatCountsAsInside:
    @pytest.fixture
    def bore(self):
        verts, faces = slab_with_bore(bore_radius=2.0, half_height=5.0)
        return bores_from_mesh(verts, faces, envelope(), margin=0.5)

    def test_a_point_down_the_middle_is_inside(self, bore):
        assert is_in_a_bore([0.0, 0.0, 0.0], bore) is True

    def test_a_point_on_the_wall_is_inside(self, bore):
        assert is_in_a_bore([2.0, 0.0, 0.0], bore) is True

    def test_a_point_on_the_rim_circle_is_inside(self, bore):
        # The rim is the circle where the wall meets the outer surface, and it
        # is one of the places a support may not touch.
        assert is_in_a_bore([2.0, 0.0, 5.0], bore) is True

    def test_a_point_just_past_the_opening_is_inside_by_the_margin(self, bore):
        assert is_in_a_bore([0.0, 0.0, 5.4], bore) is True
        assert is_in_a_bore([0.0, 0.0, 5.6], bore) is False

    def test_a_point_out_in_the_slab_is_not_inside(self, bore):
        assert is_in_a_bore([10.0, 0.0, 0.0], bore) is False

    def test_a_point_above_the_hole_is_not_inside(self, bore):
        assert is_in_a_bore([0.0, 0.0, 20.0], bore) is False

    def test_nothing_is_inside_when_there_are_no_bores(self):
        assert is_in_a_bore([0.0, 0.0, 0.0], []) is False


class TestDroppingPoints:
    @pytest.fixture
    def bore(self):
        verts, faces = slab_with_bore(bore_radius=2.0, half_height=5.0)
        return bores_from_mesh(verts, faces, envelope(), margin=0.5)

    def document(self, *positions):
        return {
            "model_fingerprint": {"face_count": 104, "vertex_checksum": "abc"},
            "points": [{"pos": list(p), "type": "island"} for p in positions],
        }

    def test_drops_the_points_in_the_hole_and_keeps_the_rest(self, bore):
        doc = self.document((0, 0, 0), (10, 0, 0), (2, 0, 5), (-10, 4, 2))
        out, dropped = drop_points_in_bores(doc, bore)

        assert dropped == 2
        assert [p["pos"] for p in out["points"]] == [[10, 0, 0], [-10, 4, 2]]

    def test_keeps_the_fingerprint_so_the_engine_still_takes_the_list(self, bore):
        # The engine refuses a point list that does not belong to the model it
        # was given. A filtered list still belongs to it.
        doc = self.document((0, 0, 0), (10, 0, 0))
        out, _ = drop_points_in_bores(doc, bore)
        assert out["model_fingerprint"] == doc["model_fingerprint"]

    def test_leaves_the_document_alone_when_nothing_falls_in(self, bore):
        doc = self.document((10, 0, 0), (-10, 4, 2))
        out, dropped = drop_points_in_bores(doc, bore)

        assert dropped == 0
        assert out is doc

    def test_leaves_the_document_alone_when_there_are_no_bores(self):
        doc = self.document((0, 0, 0))
        out, dropped = drop_points_in_bores(doc, [])

        assert dropped == 0
        assert out is doc

    def test_has_nothing_to_do_for_an_empty_list(self, bore):
        out, dropped = drop_points_in_bores({"points": []}, bore)
        assert dropped == 0
        assert out["points"] == []


class TestTheSettingReachesTheOperation:
    """The two settings have to survive the trip and stay out of the INI.

    Both halves have bitten before in other hands: a field the config intake
    drops never reaches the code that reads it, and a field that DOES reach the
    INI fails the whole run - the CLI refuses an option it does not know.
    """

    def test_the_config_intake_carries_both(self):
        from agent.api_v2 import _convert_v2_config_to_sla

        config = _convert_v2_config_to_sla({
            "layer_height": 0.05,
            "support_avoid_guide_holes": False,
            "support_guide_hole_margin": 0.9,
        })
        assert config.support_avoid_guide_holes is False
        assert config.support_guide_hole_margin == pytest.approx(0.9)

    def test_the_keep_out_is_on_unless_the_panel_says_otherwise(self):
        from agent.api_v2 import _convert_v2_config_to_sla

        config = _convert_v2_config_to_sla({"layer_height": 0.05})
        assert config.support_avoid_guide_holes is True
        assert config.support_guide_hole_margin == pytest.approx(0.5)

    def test_neither_is_written_into_the_engine_config(self, tmp_path):
        from agent.models import SLAConfig
        from agent.sla_operations import generate_config_ini

        ini = tmp_path / "config.ini"
        generate_config_ini(SLAConfig(), ini)
        text = ini.read_text()

        assert "support_avoid_guide_holes" not in text
        assert "support_guide_hole_margin" not in text
        # And the rest of the config is still there, so the exclusion is not
        # quietly dropping everything.
        assert "support_head_front_diameter" in text
        assert "printer_technology = SLA" in text


class TestNothingHappensWhenItShouldNot:
    """The setting off, or no holes found, must cost nothing at all.

    Run with asyncio.run rather than pytest-asyncio: one coroutine is not worth
    a test dependency this project does not already have.
    """

    def _run(self, tmp_path, **config_kwargs):
        import asyncio

        from agent.models import SLAConfig
        from agent.sla_operations import keep_supports_out_of_guide_holes

        (tmp_path / "input").mkdir(exist_ok=True)
        # A loop of its own, closed again: asyncio.run reaches for the thread's
        # current loop policy, which something else in this suite has already
        # had its way with.
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(keep_supports_out_of_guide_holes(
                tmp_path, SLAConfig(**config_kwargs), tmp_path / "input" / "model.stl"
            ))
        finally:
            loop.close()

    def test_the_setting_off_skips_everything(self, tmp_path):
        # Not even the mesh is read: the input file named below does not exist,
        # and the call still returns rather than raising. That is the proof that
        # a model which is not a guide pays nothing for this feature.
        assert self._run(tmp_path, support_avoid_guide_holes=False) == {"applied": False}
