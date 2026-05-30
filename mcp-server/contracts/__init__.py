"""Inbound data contracts + structured error taxonomy for the gateway."""

from contracts.errors import (
    ApiError,
    AuthInvalid,
    AuthMissing,
    InputTooLarge,
    InsufficientObservations,
    JobFailed,
    JobNotFound,
    QuotaExceeded,
    SchemaInvalid,
)
from contracts.inbound import (
    MAX_BODY_BYTES,
    TOOL_INPUTS,
    guard_body_size,
    guard_float_count,
    parse_input,
)

__all__ = [
    "ApiError",
    "InputTooLarge",
    "InsufficientObservations",
    "SchemaInvalid",
    "AuthMissing",
    "AuthInvalid",
    "QuotaExceeded",
    "JobNotFound",
    "JobFailed",
    "parse_input",
    "guard_body_size",
    "guard_float_count",
    "TOOL_INPUTS",
    "MAX_BODY_BYTES",
]
