"""Pure Azure Functions log parser (PRD FR-2)."""

from __future__ import annotations

from .core import from_log_text, parse_trace
from .masking import mask_records, mask_text

__all__ = ["from_log_text", "mask_records", "mask_text", "parse_trace"]
