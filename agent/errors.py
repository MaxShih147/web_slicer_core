"""Structured API error codes matching err_code_spec.md."""

import secrets

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
