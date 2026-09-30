"""
engine-error-code-table Section 3: the engine now declares its own error code
on stdout as a `PHZ_ERROR {json}` line, and the classifiers read it ahead of
the English-substring layer (design D4).

Fixtures are lines the rebuilt engine actually printed (Task 2.6), not strings
rebuilt from the classifier code.
"""

from agent.models import JobStatus
from agent.slicing_classifier import classify_slice_result
from agent.support_classifier import classify_support_result

# Printed by the engine for pad_wall_slope=50, pad_wall_thickness=2,
# pad_brim_size=1.6 (Task 2.6).
PHZ_PAD_CONFIG_INVALID = (
    'PHZ_ERROR {"code":"PAD_CONFIG_INVALID","fields":["pad_wall_slope",'
    '"pad_wall_thickness","pad_brim_size"],"values":{"min_pad_wall_slope":51.4,'
    '"pad_wall_slope":50}}'
)

# The same failure as a later engine might word it: none of the English
# needles the string layer looks for survive the rewording.
REWORDED_PAD_STDERR = "The pad rim is too narrow for this wall angle.\n"


class TestCodeWithoutTheEnglishText:
    """b: the code alone is enough — the new layer does not lean on the text."""

    def test_support_flow_reads_the_code_when_the_message_was_reworded(self):
        result = classify_support_result(
            stdout=PHZ_PAD_CONFIG_INVALID + "\n",
            stderr=REWORDED_PAD_STDERR,
            support_stl_exists=False,
        )
        assert result.status == JobStatus.FAILED
        assert result.error_code == "PAD_CONFIG_INVALID"

    def test_slice_flow_reads_the_code_when_the_message_was_reworded(self):
        # exit 0 with no .sl1 is how a validate() failure exits today (the
        # `return 1` in a bool function, fixed in Section 4).
        result = classify_slice_result(
            exit_code=0,
            stdout=PHZ_PAD_CONFIG_INVALID + "\n",
            stderr=REWORDED_PAD_STDERR,
            input_filename="model.stl",
            output_file_exists=False,
        )
        assert result is not None
        assert result.error_code == "PAD_CONFIG_INVALID"

    def test_slice_flow_reads_a_code_raised_as_a_slicing_exception(self):
        # Printed by the engine for a 0.1 mm sliver lifted to 5 mm with 0.3 mm
        # layers (Task 2.6); the exception path exits 1.
        result = classify_slice_result(
            exit_code=1,
            stdout='PHZ_ERROR {"code":"MODEL_MESH_UNSLICEABLE"}\n',
            stderr="This object is too thin for the chosen layer height.\n",
            input_filename="model.stl",
            output_file_exists=False,
        )
        assert result is not None
        assert result.error_code == "MODEL_MESH_UNSLICEABLE"

    def test_support_flow_reads_the_model_mismatch_code(self):
        # Printed by the engine when imported points belong to another model
        # (Task 2.6).
        result = classify_support_result(
            stdout='PHZ_ERROR {"code":"SUPPORT_POINTS_MODEL_MISMATCH"}\n',
            stderr="These support points were made for a different model.\n",
            support_stl_exists=False,
        )
        assert result.status == JobStatus.FAILED
        assert result.error_code == "SUPPORT_POINTS_MODEL_MISMATCH"

    def test_slice_flow_reads_the_model_mismatch_code(self):
        result = classify_slice_result(
            exit_code=1,
            stdout='PHZ_ERROR {"code":"SUPPORT_POINTS_MODEL_MISMATCH"}\n',
            stderr="These support points were made for a different model.\n",
            input_filename="model.stl",
            output_file_exists=False,
        )
        assert result is not None
        assert result.error_code == "SUPPORT_POINTS_MODEL_MISMATCH"

    # Not captured live (Task 2.6 could not make the print empty); this is
    # the line ProcessActions.cpp emits for it — a code with no fields.
    PHZ_OUT_OF_BOUNDS = 'PHZ_ERROR {"code":"MODEL_OUT_OF_BOUNDS"}\n'

    def test_support_flow_reads_the_out_of_bounds_code(self):
        result = classify_support_result(
            stdout=self.PHZ_OUT_OF_BOUNDS + "Nothing fits on the plate.\n",
            stderr="",
            support_stl_exists=False,
        )
        assert result.status == JobStatus.FAILED
        assert result.error_code == "MODEL_OUT_OF_BOUNDS"

    def test_slice_flow_reads_the_out_of_bounds_code(self):
        result = classify_slice_result(
            exit_code=0,
            stdout=self.PHZ_OUT_OF_BOUNDS + "Nothing fits on the plate.\n",
            stderr="",
            input_filename="model.stl",
            output_file_exists=False,
        )
        assert result is not None
        assert result.error_code == "MODEL_OUT_OF_BOUNDS"

    def test_slice_flow_reads_the_empty_model_code(self):
        # Not captured live either (an empty STL is rejected earlier, at
        # parse time); LoadPrintData.cpp emits this for a file with no objects.
        result = classify_slice_result(
            exit_code=0,
            stdout='PHZ_ERROR {"code":"INVALID_MODEL"}\n',
            stderr="The input file holds no objects.\n",
            input_filename="model.stl",
            output_file_exists=False,
        )
        assert result is not None
        assert result.error_code == "INVALID_MODEL"


class TestFlowRoutingIsKept:
    """c: a declared code is only taken where the flow already recognizes it.
    The engine reports EXPOSURE_TIME_OUT_OF_RANGE on every flow, but the
    support flow has always routed that failure to its fallback."""

    # Printed by the engine for exposure_time=500 against a 0-100 profile
    # (Task 2.6), with the stderr message that accompanies it.
    PHZ_EXPOSURE = (
        'PHZ_ERROR {"code":"EXPOSURE_TIME_OUT_OF_RANGE","fields":["exposure_time"],'
        '"values":{"min_exposure_time":0,"max_exposure_time":100,"exposure_time":500}}\n'
    )
    EXPOSURE_STDERR = "Exposition time is out of printer profile bounds.\n"

    def test_support_flow_still_routes_exposure_to_its_fallback(self):
        result = classify_support_result(
            stdout=self.PHZ_EXPOSURE, stderr=self.EXPOSURE_STDERR, support_stl_exists=False
        )
        assert result.error_code == "SUPPORT_GENERATION_FAILED"

    def test_slice_flow_still_gives_exposure_its_own_code(self):
        result = classify_slice_result(
            exit_code=0,
            stdout=self.PHZ_EXPOSURE,
            stderr=self.EXPOSURE_STDERR,
            input_filename="model.stl",
            output_file_exists=False,
        )
        assert result.error_code == "EXPOSURE_TIME_OUT_OF_RANGE"


class TestUnregisteredCode:
    """d: an engine newer than the agent may declare a code the registry has
    never heard of. It must not reach the frontend as-is (it would find no
    i18n key) — fall back, and keep the engine's line for whoever debugs it."""

    UNKNOWN = 'PHZ_ERROR {"code":"SOME_CODE_FROM_A_NEWER_ENGINE"}'

    def test_slice_flow_falls_back_and_keeps_the_engine_line(self):
        result = classify_slice_result(
            exit_code=0,
            stdout=self.UNKNOWN + "\n",
            stderr="",
            input_filename="model.stl",
            output_file_exists=False,
        )
        assert result.error_code is None  # generic JOB_FAILED
        assert self.UNKNOWN in result.error

    def test_support_flow_falls_back_and_keeps_the_engine_line(self):
        result = classify_support_result(
            stdout=self.UNKNOWN + "\n", stderr="", support_stl_exists=False
        )
        assert result.error_code == "SUPPORT_GENERATION_FAILED"
        assert self.UNKNOWN in result.detail


class TestGarbledEngineLine:
    """e: a PHZ_ERROR line that is not valid JSON is ignored, and the English
    message beside it still classifies the run."""

    GARBLED = 'PHZ_ERROR {"code":"PAD_CONFIG_INVALID",\n'
    PAD_STDERR = "Pad brim size is too small for the current configuration.\n"

    def test_support_flow_falls_back_to_the_string_layer(self):
        result = classify_support_result(
            stdout=self.GARBLED, stderr=self.PAD_STDERR, support_stl_exists=False
        )
        assert result.error_code == "PAD_CONFIG_INVALID"

    def test_slice_flow_falls_back_to_the_string_layer(self):
        result = classify_slice_result(
            exit_code=0,
            stdout=self.GARBLED,
            stderr=self.PAD_STDERR,
            input_filename="model.stl",
            output_file_exists=False,
        )
        assert result.error_code == "PAD_CONFIG_INVALID"
