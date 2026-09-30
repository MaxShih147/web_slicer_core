"""Structured API error codes matching err_code_spec.md."""

import inspect
import secrets
import sys

from fastapi.responses import JSONResponse


class APIError(Exception):
    def __init__(self, code: str, message: str, http_status: int, retryable: bool = False):
        self.code = code
        self.message = message
        self.http_status = http_status
        self.retryable = retryable
        self.trace_id = secrets.token_hex(6)  # 12-char hex
        super().__init__(message)

    def to_response(self, headers: dict = None) -> JSONResponse:
        return JSONResponse(
            status_code=self.http_status,
            content={
                "success": False,
                "code": self.code,
                "message": self.message,
                "data": {
                    "retryable": self.retryable,
                    "traceId": self.trace_id,
                },
            },
            headers=headers or {},
        )


# ─── factory functions ────────────────────────────────────────────────────────

def internal_error(message: str) -> APIError:
    return APIError("INTERNAL_ERROR", message, 500, retryable=True)


def validation_error(message: str) -> APIError:
    return APIError("VALIDATION_ERROR", message, 400, retryable=False)


def missing_body(message: str = "Required field or file is missing") -> APIError:
    return APIError("MISSING_BODY", message, 400, retryable=False)


def config_validation_error(message: str) -> APIError:
    return APIError("CONFIG_VALIDATION_ERROR", message, 422, retryable=False)


def job_not_found(job_id: str = None) -> APIError:
    msg = f"Job '{job_id}' not found" if job_id else "Job not found"
    return APIError("JOB_NOT_FOUND", msg, 404, retryable=False)


def job_already_executed(job_id: str = None) -> APIError:
    msg = (
        f"Job '{job_id}' has already been executed and cannot be modified"
        if job_id
        else "Job has already been executed"
    )
    return APIError("JOB_ALREADY_EXECUTED", msg, 409, retryable=False)


def job_still_processing() -> APIError:
    return APIError(
        "JOB_STILL_PROCESSING",
        "Job is still processing; result not yet available",
        200,
        retryable=True,
    )


def job_failed(error: str = None) -> APIError:
    msg = f"Job failed: {error}" if error else "Job execution failed"
    return APIError("JOB_FAILED", msg, 409, retryable=False)


def model_not_found(detail: str = None) -> APIError:
    return APIError(
        "MODEL_NOT_FOUND",
        detail or "No model found for this job",
        404,
        retryable=False,
    )


def invalid_model(detail: str = None) -> APIError:
    return APIError(
        "INVALID_MODEL",
        detail or "STL content is corrupted or format is invalid",
        422,
        retryable=False,
    )


def file_not_found(detail: str = None) -> APIError:
    return APIError(
        "FILE_NOT_FOUND",
        detail or "Output file not found",
        404,
        retryable=False,
    )


def boolean_failed(detail: str = None) -> APIError:
    return APIError(
        "BOOLEAN_FAILED",
        detail or "Boolean geometry operation failed",
        422,
        retryable=False,
    )


def boolean_invalid_mesh() -> APIError:
    return APIError(
        "BOOLEAN_INVALID_MESH",
        "The model mesh contains geometry errors and could not be processed.",
        422,
        retryable=False,
    )


def no_drain_holes() -> APIError:
    return APIError(
        "NO_DRAIN_HOLES",
        "No wall edges found in current geometry for drain hole placement",
        422,
        retryable=False,
    )


def no_hex_grid_cells() -> APIError:
    return APIError(
        "NO_HEX_GRID_CELLS",
        "Hex grid algorithm produced no cells; parameters may exceed hollow mesh bounds",
        422,
        retryable=False,
    )


def hollow_generation_failed(detail: str = None) -> APIError:
    return APIError(
        "HOLLOW_GENERATION_FAILED",
        detail or "Hollow interior mesh could not be generated",
        422,
        retryable=False,
    )


# ─── support generation error codes ───────────────────────────────────────────
# 對應 generate-supports 的 SLAPrint::validate() 失敗與結果分類（見
# openspec/changes/add-support-generation-error-codes）。沿用 geometry 失敗家族
# 的 422 / retryable=False 慣例；SUPPORT_NOT_NEEDED 屬中性 supportOutcome，非
# 錯誤，不在此註冊。

def support_head_too_wide(detail: str = None) -> APIError:
    return APIError(
        "SUPPORT_HEAD_TOO_WIDE",
        detail or "Support pinhead diameter is invalid for the given geometry",
        422,
        retryable=False,
    )


def support_head_penetration_invalid(detail: str = None) -> APIError:
    return APIError(
        "SUPPORT_HEAD_PENETRATION_INVALID",
        detail or "Support head penetration value is invalid",
        422,
        retryable=False,
    )


def support_elevation_too_low(detail: str = None) -> APIError:
    return APIError(
        "SUPPORT_ELEVATION_TOO_LOW",
        detail or "Object elevation is too low for support generation",
        422,
        retryable=False,
    )


def support_points_required(detail: str = None) -> APIError:
    return APIError(
        "SUPPORT_POINTS_REQUIRED",
        detail or "Cannot proceed without support points",
        422,
        retryable=False,
    )


def support_pad_gap_conflict(detail: str = None) -> APIError:
    return APIError(
        "SUPPORT_PAD_GAP_CONFLICT",
        detail or "Support pillar endings conflict with the object/pad gap",
        422,
        retryable=False,
    )


def model_out_of_bounds(detail: str = None) -> APIError:
    return APIError(
        "MODEL_OUT_OF_BOUNDS",
        detail or "No object is fully inside the print volume",
        422,
        retryable=False,
    )


def support_generation_failed(detail: str = None) -> APIError:
    return APIError(
        "SUPPORT_GENERATION_FAILED",
        detail or "Support mesh generation failed",
        422,
        retryable=False,
    )


def support_points_model_mismatch(detail: str = None) -> APIError:
    """The imported support point list does not describe the model being sliced.

    Not retryable: the fingerprint comparison is deterministic, so replaying the
    same list against the same model always fails again. The only fix is to
    regenerate the points from the current model.
    """
    return APIError(
        "SUPPORT_POINTS_MODEL_MISMATCH",
        detail
        or "The supplied support points do not match this model; "
           "regenerate them from the current model",
        422,
        retryable=False,
    )


def support_point_sampling_failed(detail: str = None) -> APIError:
    return APIError(
        "SUPPORT_POINT_SAMPLING_FAILED",
        detail or "The SLA support point generator failed to sample this model; "
                  "try adjusting the model's orientation slightly",
        422,
        retryable=False,
    )


def support_mesh_export_failed(detail: str = None) -> APIError:
    """The support was generated, but its STL could not be written.

    500 and retryable, unlike the other support codes: a failed file write is
    the server's disk or permissions, not a setting the user can fix, so the
    same request may well succeed the next time.
    """
    return APIError(
        "SUPPORT_MESH_EXPORT_FAILED",
        detail or "The support mesh was generated but could not be written to disk",
        500,
        retryable=True,
    )


def shrinkage_compensation_invalid(detail: str = None) -> APIError:
    return APIError(
        "SHRINKAGE_COMPENSATION_INVALID",
        detail or "The object transform is not invertible (a zero scale or a zero "
                  "shrinkage compensation), so support points cannot be mapped back "
                  "to the input model",
        422,
        retryable=False,
    )


# ─── slicing error codes ───────────────────────────────────────────────────────
# Correspond to classified SLA slicing failures (see slicing_classifier.py).
# Follow the same 422 / retryable=False convention as the geometry-failure family.

def pad_config_invalid(detail: str = None) -> APIError:
    return APIError(
        "PAD_CONFIG_INVALID",
        detail or "Pad brim size is too small for the current configuration",
        422,
        retryable=False,
    )


def exposure_time_out_of_range(detail: str = None) -> APIError:
    return APIError(
        "EXPOSURE_TIME_OUT_OF_RANGE",
        detail or "Exposure time is outside the printer profile bounds",
        422,
        retryable=False,
    )


def model_mesh_unsliceable(detail: str = None) -> APIError:
    return APIError(
        "MODEL_MESH_UNSLICEABLE",
        detail or "Model mesh cannot be sliced; the geometry may be broken or non-manifold",
        422,
        retryable=False,
    )


def unprintable_object(detail: str = None) -> APIError:
    return APIError(
        "UNPRINTABLE_OBJECT",
        detail or "Model contains layers that cannot be printed; try adjusting support settings",
        422,
        retryable=False,
    )


def pad_generation_failed(detail: str = None) -> APIError:
    return APIError(
        "PAD_GENERATION_FAILED",
        detail or "Pad mesh could not be generated for this model with the current configuration",
        422,
        retryable=False,
    )


# ─── registry-derived lookup (unify-error-code-registry Task 4.1) ─────────────

def factory_registry() -> dict:
    """Map every error code to the factory above that produces it.

    Derived by calling each factory in this module and reading the `code` off
    its returned APIError — not a hand-maintained dict (agent/error_codes.py
    design D3: factory signatures aren't uniform enough to codegen, but a
    lookup table built from them at runtime needs no maintenance at all).

    Used by api_v2.py to build its code -> factory table, and by
    test_error_code_contract.py to verify it agrees with the registry.
    """
    registry = {}
    for _, fn in inspect.getmembers(sys.modules[__name__], inspect.isfunction):
        if fn.__module__ != __name__:
            continue
        sig = inspect.signature(fn)
        if sig.return_annotation is not APIError:
            continue  # excludes this function itself (-> dict), not an error factory
        kwargs = {
            name: "test-value"
            for name, param in sig.parameters.items()
            if param.default is inspect.Parameter.empty
        }
        code = fn(**kwargs).code
        if code in registry:
            raise ValueError(
                f"two factories produce code={code!r}: {registry[code].__name__} and "
                f"{fn.__name__} — each code must have exactly one factory"
            )
        registry[code] = fn
    return registry
