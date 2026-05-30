"""
Structured error taxonomy — machine-parseable, never prose. Every error carries
a stable `code` a consumer can branch on, an HTTP status for the REST surface,
and echoes the `request_id`. Shape:

    { "error": { "code": "INSUFFICIENT_OBSERVATIONS", "message": "...",
                 "request_id": "req_..." , "details": {...}? } }

Codes (build spec §7): INPUT_TOO_LARGE, INSUFFICIENT_OBSERVATIONS, SCHEMA_INVALID,
AUTH_INVALID, AUTH_MISSING, QUOTA_EXCEEDED, JOB_NOT_FOUND, JOB_FAILED.
"""

from __future__ import annotations

from typing import Any, Optional


class ApiError(Exception):
    """Base for every typed gateway error. Subclasses set code + http_status."""

    code: str = "INTERNAL"
    http_status: int = 500

    def __init__(self, message: str, *, details: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self, request_id: str) -> dict[str, Any]:
        body: dict[str, Any] = {"code": self.code, "message": self.message, "request_id": request_id}
        if self.details:
            body["details"] = self.details
        return {"error": body}


class InputTooLarge(ApiError):
    code = "INPUT_TOO_LARGE"
    http_status = 413


class InsufficientObservations(ApiError):
    code = "INSUFFICIENT_OBSERVATIONS"
    http_status = 422


class SchemaInvalid(ApiError):
    code = "SCHEMA_INVALID"
    http_status = 422


class AuthMissing(ApiError):
    code = "AUTH_MISSING"
    http_status = 401


class AuthInvalid(ApiError):
    code = "AUTH_INVALID"
    http_status = 401


class QuotaExceeded(ApiError):
    code = "QUOTA_EXCEEDED"
    http_status = 429


class JobNotFound(ApiError):
    code = "JOB_NOT_FOUND"
    http_status = 404


class JobFailed(ApiError):
    code = "JOB_FAILED"
    http_status = 500
