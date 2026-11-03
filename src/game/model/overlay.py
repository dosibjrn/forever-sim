"""Compatibility exports for the shared numeric field-overlay primitive.

The implementation is model-independent and lives in src.shared. Keep this
path as an identity-preserving import for existing GameIR consumers.
"""

from src.shared.field_overlays import (
    FieldOverlay,
    SUPPORTED_NUMERIC_OPERATIONS,
    apply_numeric_field_overlays,
)

__all__ = (
    "FieldOverlay",
    "SUPPORTED_NUMERIC_OPERATIONS",
    "apply_numeric_field_overlays",
)
