"""Back-compat shim.

All PDF-benchmark extraction routines have moved into ``benchmark_workflow``
so the benchmark codebase lives in a single module. This file re-exports
the legacy public surface so any older call site that still does
``from app.benchmarks import ...`` or ``import app.benchmarks`` keeps working.

New code should import directly from ``app.benchmark_workflow``.
"""
from __future__ import annotations

from .benchmark_workflow import (
    ANNOT_TYPES,
    BM_MARK_RE,
    EXTRACT_SCHEMA_VERSION,
    VECTOR_R_MAX,
    VECTOR_R_MIN,
    VECTOR_TEXT_NEAR_PT,
    _annotation_pass,
    _now_iso,
    _vector_pass,
    extract_pdf_benchmarks,
)

__all__ = [
    "ANNOT_TYPES",
    "BM_MARK_RE",
    "EXTRACT_SCHEMA_VERSION",
    "VECTOR_R_MAX",
    "VECTOR_R_MIN",
    "VECTOR_TEXT_NEAR_PT",
    "_annotation_pass",
    "_now_iso",
    "_vector_pass",
    "extract_pdf_benchmarks",
]
