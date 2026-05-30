"""Data-provided seam: request-scoped data context + no-fetch guard over the
intact backend. See docs/INVENTORY.md (seam scope) and MASTER_PLAN §4 inv #2."""

from seam.data_context import (
    FetchForbidden,
    get_provided,
    get_provided_data,
    is_provided_mode,
    provided_session,
)
from seam.install import install_seam, uninstall_seam

__all__ = [
    "provided_session",
    "is_provided_mode",
    "get_provided",
    "get_provided_data",
    "FetchForbidden",
    "install_seam",
    "uninstall_seam",
]
