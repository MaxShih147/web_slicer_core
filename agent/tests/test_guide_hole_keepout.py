"""The drill-hole keep-out: finding the wall, and dropping the heads on it.

Built on a synthetic guide rather than a patient model - a slab with a bore
through it, where the right answer is known rather than measured. The real
guides are what the numbers in guide_hole_keepout's own docstring came from, and
they are patient data that cannot live in a repository.
"""

import math

import numpy as np
import pytest

from agent.guide_hole_keepout import (
    drop_points_on_holes,
    keepout_from_mesh,
    wall_faces,
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


class TestFindingTheWall:
    def test_takes_the_wall_and_leaves_the_flat_faces(self):
        verts, faces = slab_with_bore(segments=48)
        idx = wall_faces(verts, faces, envelope())
        # Two triangles per segment of wall, and not one of the four flat ones.
        assert len(idx) == 96
        assert set(idx) == set(range(96))

    def test_finds_nothing_in_a_solid_slab(self):
        # No inward-facing wall anywhere: there is no hole, so there is nothing
        # to keep off. Guessing one would carve supports out of a sound model.
        verts, faces = slab_with_bore()
        assert len(wall_faces(verts, faces[96:], envelope())) == 0

    def test_finds_nothing_without_an_envelope_to_look_in(self):
        verts, faces = slab_with_bore()
        assert len(wall_faces(verts, faces, [])) == 0

    def test_finds_nothing_for_an_envelope_with_no_axis(self):
        verts, faces = slab_with_bore()
        broken = [{"center": [0, 0, 0], "axis": [0, 0, 0], "radius": 6.0, "length": 40.0}]
        assert len(wall_faces(verts, faces, broken)) == 0

    def test_finds_a_tilted_wall_along_its_own_axis(self):
        verts, faces = slab_with_bore()
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
        assert len(wall_faces(tilted, faces, env)) == 96

    def test_a_wall_of_a_few_stray_facets_is_not_a_hole(self):
        # Eight faces is noise the envelope happened to catch, not a bore.
        verts, faces = slab_with_bore(segments=4)
        assert len(wall_faces(verts, faces, envelope())) == 0


class TestWhatCountsAsOnAHole:
    @pytest.fixture
    def keepout(self):
        verts, faces = slab_with_bore(bore_radius=2.0, half_height=5.0)
        return keepout_from_mesh(verts, faces, envelope(), margin=0.5)

    def test_there_is_no_keep_out_without_a_hole(self):
        verts, faces = slab_with_bore()
        assert keepout_from_mesh(verts, faces[96:], envelope(), margin=0.5) is None

    def test_reports_what_it_was_built_from(self, keepout):
        assert keepout.face_count == 96
        assert keepout.margin == pytest.approx(0.5)

    def test_a_point_on_the_wall_is_on_a_hole(self, keepout):
        assert keepout.are_on_a_hole([[2.0, 0.0, 0.0]])[0]

    def test_a_point_on_the_rim_circle_is_on_a_hole(self, keepout):
        # The rim is where the wall meets the outside - the patch's own
        # boundary, so it needs no separate description.
        assert keepout.are_on_a_hole([[2.0, 0.0, 5.0]])[0]

    def test_a_point_within_the_margin_of_the_wall_is_on_a_hole(self, keepout):
        assert keepout.are_on_a_hole([[2.4, 0.0, 0.0]])[0]
        assert not keepout.are_on_a_hole([[2.6, 0.0, 0.0]])[0]

    def test_a_point_just_past_the_rim_is_on_a_hole(self, keepout):
        # Just outside the opening, which is where the head the report came
        # from was sitting - 0.2mm off a wall.
        assert keepout.are_on_a_hole([[2.0, 0.0, 5.4]])[0]
        assert not keepout.are_on_a_hole([[2.0, 0.0, 5.6]])[0]

    def test_a_point_out_in_the_slab_is_not(self, keepout):
        assert not keepout.are_on_a_hole([[10.0, 0.0, 0.0]])[0]

    def test_a_point_well_above_the_slab_is_not(self, keepout):
        assert not keepout.are_on_a_hole([[0.0, 0.0, 20.0]])[0]

    def test_takes_a_whole_list_at_once(self, keepout):
        mask = keepout.are_on_a_hole([[2.0, 0, 0], [10.0, 0, 0], [2.0, 0, 5.0]])
        assert list(mask) == [True, False, True]

    def test_has_nothing_to_say_about_an_empty_list(self, keepout):
        assert len(keepout.are_on_a_hole([])) == 0


class TestDroppingPoints:
    @pytest.fixture
    def keepout(self):
        verts, faces = slab_with_bore(bore_radius=2.0, half_height=5.0)
        return keepout_from_mesh(verts, faces, envelope(), margin=0.5)

    def document(self, *positions):
        return {
            "model_fingerprint": {"face_count": 104, "vertex_checksum": "abc"},
            "points": [{"pos": list(p), "type": "island"} for p in positions],
        }

    def test_drops_the_heads_on_the_hole_and_keeps_the_rest(self, keepout):
        doc = self.document((2, 0, 0), (10, 0, 0), (2, 0, 5), (-10, 4, 2))
        out, dropped = drop_points_on_holes(doc, keepout)

        assert dropped == 2
        assert [p["pos"] for p in out["points"]] == [[10, 0, 0], [-10, 4, 2]]

    def test_keeps_the_fingerprint_so_the_engine_still_takes_the_list(self, keepout):
        # The engine refuses a point list that does not belong to the model it
        # was given. A filtered list still belongs to it.
        doc = self.document((2, 0, 0), (10, 0, 0))
        out, _ = drop_points_on_holes(doc, keepout)
        assert out["model_fingerprint"] == doc["model_fingerprint"]

    def test_leaves_the_document_alone_when_nothing_is_on_a_hole(self, keepout):
        doc = self.document((10, 0, 0), (-10, 4, 2))
        out, dropped = drop_points_on_holes(doc, keepout)

        assert dropped == 0
        assert out is doc

    def test_leaves_the_document_alone_when_there_is_no_keep_out(self):
        doc = self.document((2, 0, 0))
        out, dropped = drop_points_on_holes(doc, None)

        assert dropped == 0
        assert out is doc

    def test_has_nothing_to_do_for_an_empty_list(self, keepout):
        out, dropped = drop_points_on_holes({"points": []}, keepout)
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

    def test_the_keep_out_is_off_unless_it_is_asked_for(self):
        # One-click processing asks for it, for a surgical guide. A caller
        # growing supports on their own gets what they asked for and nothing
        # taken away, so the default cannot be "on".
        from agent.api_v2 import _convert_v2_config_to_sla

        config = _convert_v2_config_to_sla({"layer_height": 0.05})
        assert config.support_avoid_guide_holes is False
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
