"""Per-phase plain-English summaries for the live pipeline log.

Every sentence here is built from numbers that already exist in an artifact —
no LLM, no estimation, no project-specific constants. Feed a dict, get a
string; the same input always yields the same sentence, so a summary can be
diffed across runs like any other artifact.

``record()`` is the only impure function: it pushes ``🤖 <summary>`` onto the
existing progress bus (``progress.emit`` -> SSE -> pipeline modal log) and
stores the latest text per phase in ``phase_summaries.json``. It never raises —
a summary is commentary, and commentary must not break a pipeline.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "phase-summaries/1.0"

# Phase -> the progress-bus step key whose card/log renders it. The keys are the
# ones the pipeline modal and the wizard already subscribe to; nothing new to
# wire on the frontend.
PHASE_STEPS: dict[str, str] = {
    "upload": "upload",
    # One entry per pipeline stage in stage_graph.STAGES, so every stage the
    # user watches can narrate itself. Step keys match the progress-bus keys
    # the pipeline modal already subscribes to.
    "extract": "extract",
    "revit_convert": "revit_convert",
    "pdf_intelligence": "pdf_intelligence",
    "pdf_convert": "pdf_convert",
    "compare": "compare",
    "auto_benchmark": "benchmark",
    "revit_placement": "benchmark_workflow",
    "registration": "ransac",
    "match": "match",
}

# review.analyze() walks every peer device per call, so a 400-mismatch sheet
# would be O(n^2). 30 samples is plenty to tell "most shift the same way" from
# "they scatter"; the summary reports the sample size honestly.
SYSTEMATIC_SAMPLE_CAP = 30


def _n(value: Any, default: float = 0) -> float:
    return value if isinstance(value, (int, float)) else default


# ---------------------------------------------------------------------------
# Pure summary builders
# ---------------------------------------------------------------------------
def upload(
    manifest: dict[str, Any] | None,
    element_intelligence: dict[str, Any] | None = None,
    page_intelligence: dict[str, Any] | None = None,
) -> str:
    """What arrived: pages, indexed sheets, schedule tables, the plan sheet."""
    manifest = manifest or {}
    parts: list[str] = []
    pages = manifest.get("page_count")
    name = manifest.get("pdf_original_name")
    if pages:
        parts.append(f"{int(pages)}-page set" + (f" ({name})" if name else ""))
    elif name:
        parts.append(str(name))
    if element_intelligence:
        sheets = element_intelligence.get("sheets") or []
        summary = element_intelligence.get("summary") or {}
        n_sheets = int(_n(summary.get("sheet_count"), len(sheets)))
        tables = sum(len(s.get("tables") or []) for s in sheets)
        marks = sum(int(_n(v)) for v in (summary.get("marks_by_category") or {}).values())
        parts.append(f"{n_sheets} sheets indexed")
        parts.append(f"{tables} schedule tables found")
        if marks:
            parts.append(f"{marks} element marks")
    if page_intelligence and page_intelligence.get("sheet_number"):
        page_index = page_intelligence.get("page_index")
        where = f" (page {int(page_index) + 1})" if isinstance(page_index, int) else ""
        parts.append(
            f"structural plan sheet {page_intelligence['sheet_number']}{where} detected")
    if not parts:
        return "Upload: files stored; nothing indexed yet — run Extract to read the sheets."
    tail = "" if (element_intelligence or page_intelligence) else \
        " Nothing indexed yet — run Extract to read the sheets."
    return "Upload: " + ", ".join(parts) + "." + tail


def auto_benchmark(proposal: dict[str, Any] | None, stamped: bool) -> str:
    """The two grid intersections the picker chose, and whether they got stamped."""
    bms = (proposal or {}).get("benchmarks") or []
    if len(bms) < 2:
        return ("Auto-benchmark: fewer than 2 labeled grid intersections are shared by "
                "the PDF sheet and the Revit export — falling back to manual picking "
                "or RANSAC.")
    labels = " & ".join(
        f"{b.get('mark')} at {b.get('grid_label') or b.get('grid_id')}" for b in bms[:2])
    sep_ft = (proposal or {}).get("separation_revit_ft")
    spread = f" {sep_ft} ft apart" if sep_ft is not None else ""
    considered = (proposal or {}).get("candidates_considered")
    pool = f" out of {considered} labeled intersections" if considered else ""
    stamp = ("PDF stamped with BM-1/BM-2 and read back."
             if stamped else "PDF NOT stamped — stamp verification did not pass; "
             "the proposal still stands for review.")
    return (f"Auto-benchmark: {labels} — max diagonal spread{spread}{pool}. {stamp} "
            "Awaiting your approval.")


def revit_placement(
    proposal: dict[str, Any] | None, payload: dict[str, Any] | None
) -> str:
    """Where the bridge actually put each marker, and how far that is from intent."""
    bms = (proposal or {}).get("benchmarks") or []
    readback = (payload or {}).get("readback") or {}
    if not bms or not readback:
        return "Revit placement: markers placed; no read-back coordinates reported."
    bits: list[str] = []
    worst = 0.0
    for b in bms:
        mark = b.get("mark")
        got = readback.get(mark)
        want = b.get("revit_point_ft") or {}
        if not got or want.get("x") is None:
            bits.append(f"{mark} not read back")
            continue
        delta = ((_n(got.get("x")) - _n(want.get("x"))) ** 2
                 + (_n(got.get("y")) - _n(want.get("y"))) ** 2) ** 0.5
        worst = max(worst, delta)
        bits.append(f"{mark} at ({_n(got.get('x')):.3f}, {_n(got.get('y')):.3f}) ft "
                    f"(Δ {delta:.4f} ft)")
    return (f"Revit placement: {'; '.join(bits)}. "
            f"Worst read-back deviation {worst:.4f} ft from the approved point.")


def registration(calibration: dict[str, Any] | None) -> str:
    """The transform that was actually saved, in the terms that gate a MATCH."""
    cal = calibration or {}
    transform = cal.get("transform") or {}
    quality = cal.get("quality") or {}
    scale = transform.get("scale")
    rot = transform.get("rotation_degrees")
    rms = quality.get("solve_rms_residual_pt", quality.get("rms_residual_pt"))
    allowed = quality.get("match_allowed")
    verdict = ("MATCH verdicts allowed" if allowed
               else "MATCH withheld — " + (quality.get("confidence_reason")
                                           or "quality gate not met"))
    return (
        f"Registration: {scale if scale is not None else '?'} pt/ft, "
        f"{rot if rot is not None else '?'}° rotation, source "
        f"{cal.get('calibration_source') or 'unknown'}, confidence "
        f"{quality.get('confidence') or 'unknown'}, RMS "
        f"{rms if rms is not None else '?'} pt. {verdict}."
    )


def match(
    element_list: dict[str, Any] | None,
    systematic: int = 0,
    sampled: int = 0,
) -> str:
    """Totals by status plus how much of the mismatch pile is one shared shift."""
    counts = (element_list or {}).get("counts") or {}
    by_status = counts.get("by_status") or {}
    total = counts.get("total", sum(int(_n(v)) for v in by_status.values()))
    breakdown = ", ".join(
        f"{int(_n(v))} {k}" for k, v in sorted(by_status.items(), key=lambda kv: -_n(kv[1]))
    ) or "no elements"
    out = f"Match: {int(_n(total))} elements — {breakdown}."
    if sampled:
        if systematic:
            out += (f" {systematic}/{sampled} sampled mismatches shift the same "
                    "direction — likely drafting offset, not modeling error.")
        else:
            out += (f" None of {sampled} sampled mismatches share a direction — "
                    "these look like individual deviations, not a sheet-wide offset.")
    return out


def extract(element_intelligence: dict[str, Any] | None) -> str:
    """What the drawings actually yielded: sheets, callouts, schedule marks."""
    ei = element_intelligence or {}
    sheets = ei.get("sheets") or []
    marks = [m for s in sheets for m in (s.get("marks") or [])]
    by_cat: dict[str, int] = {}
    for m in marks:
        by_cat[m.get("category") or "unclassified"] = by_cat.get(
            m.get("category") or "unclassified", 0) + 1
    breakdown = ", ".join(f"{v} {k.replace('_', ' ')}"
                          for k, v in sorted(by_cat.items(), key=lambda kv: -kv[1]))
    vocab = ei.get("vocabulary") or {}
    known = sum(len(v) for v in vocab.values() if isinstance(v, list))
    return (
        f"Reading drawings: {len(marks)} callouts across {len(sheets)} sheet(s)"
        + (f" — {breakdown}" if breakdown else "")
        + f". Learned {known} mark(s) from the schedule tables."
    )


def revit_convert(ai_revit: dict[str, Any] | None) -> str:
    """What came out of the model export, and whether marks could be resolved."""
    ai = ai_revit or {}
    assemblies = ai.get("canonical_holdown_assemblies") or []
    resolved = sum(1 for a in assemblies if a.get("pdf_mark_candidate"))
    unresolved = len(assemblies) - resolved
    out = (f"Reading model: {len(assemblies)} hold-down assemblies, "
           f"{resolved} resolved to a schedule mark")
    if unresolved:
        out += (f", {unresolved} unresolved — those cannot be matched until a "
                "type mapping is taught")
    return out + "."


def pdf_intelligence(page_intelligence: dict[str, Any] | None) -> str:
    """Which sheet became the plan, and how much was detected on it."""
    pi = page_intelligence or {}
    if pi.get("error"):
        return (f"Locating the plan: FAILED — {pi['error']}. Downstream "
                "comparison will have nothing to work from.")
    detections = pi.get("detections") or pi.get("holdowns") or []
    sheet = pi.get("sheet_number") or pi.get("source_sheet") or "the densest sheet"
    return (f"Locating the plan: chose {sheet} and located "
            f"{len(detections)} element(s) on it.")


def pdf_convert(ai_pdf: dict[str, Any] | None) -> str:
    """The normalized drawing-side rows the comparison will consume."""
    ap = ai_pdf or {}
    holdowns = ap.get("holdowns") or []
    inferred = sum(1 for h in holdowns if h.get("z_is_inferred"))
    marks = {h.get("normalized_mark") for h in holdowns if h.get("normalized_mark")}
    out = (f"Preparing drawing data: {len(holdowns)} element(s) normalized "
           f"across {len(marks)} mark(s)")
    if inferred:
        out += f", {inferred} with an inferred elevation"
    return out + "."


def compare(report: dict[str, Any] | None) -> str:
    """The registration-gated comparison, in the terms that gate a MATCH."""
    rep = report or {}
    counts = (rep.get("summary") or {}).get("verdict_counts") or {}
    reg = rep.get("registration") or {}
    breakdown = ", ".join(f"{int(_n(v))} {k}" for k, v in
                          sorted(counts.items(), key=lambda kv: -_n(kv[1])) if _n(v))
    blockers = [b for b in (rep.get("blockers") or [])
                if b.get("severity") == "blocking"]
    out = f"Comparing: {breakdown or 'no pairings'}."
    if not reg.get("match_allowed"):
        out += (" MATCH was withheld — registration is not verified for this "
                "sheet, so every pairing is reported as needing review.")
    if blockers:
        out += f" {len(blockers)} blocking issue(s): " + ", ".join(
            b.get("code", "?") for b in blockers) + "."
    return out


def count_systematic(
    element_list: dict[str, Any] | None,
    registry: dict[str, Any] | None,
    cap: int = SYSTEMATIC_SAMPLE_CAP,
) -> tuple[int, int]:
    """(systematic, sampled) over LOCATION_MISMATCH rows via review.analyze().

    Category-agnostic on purpose: whatever categories a client's schedule
    happens to contain, a shared shift is a shared shift. Capped so a huge
    sheet cannot turn a summary into a compute job.
    """
    from . import review

    rows = [r for r in (element_list or {}).get("elements") or []
            if r.get("status") == "LOCATION_MISMATCH"][:cap]
    systematic = sampled = 0
    for row in rows:
        try:
            result = review.analyze(row["id"], element_list or {}, registry or {})
        except Exception:
            continue
        if not result.get("analysis_available"):
            continue
        sampled += 1
        systematic += bool(result.get("systematic"))
    return systematic, sampled


# ---------------------------------------------------------------------------
# Emit + store (the only impure part)
# ---------------------------------------------------------------------------
def load() -> dict[str, Any]:
    from . import config

    path = config.artifact_path("phase_summaries")
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "phases": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": SCHEMA_VERSION, "phases": {}}


def record(phase: str, text: str) -> None:
    """Push ``🤖 <text>`` onto the live log and persist it. Never raises."""
    from . import config, progress

    try:
        progress.emit(PHASE_STEPS.get(phase, phase), "info", f"🤖 {text}",
                      {"phase_summary": phase})
        data = load()
        data["schema_version"] = SCHEMA_VERSION
        data.setdefault("phases", {})[phase] = {
            "text": text,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        path = config.artifact_path("phase_summaries")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass  # commentary must never break a pipeline


if __name__ == "__main__":
    assert "3 sheets indexed" in upload(
        {"page_count": 4}, {"sheets": [{"tables": []}] * 3, "summary": {}})
    assert "max diagonal" in auto_benchmark(
        {"benchmarks": [{"mark": "BM-1", "grid_label": "Grid A/1"},
                        {"mark": "BM-2", "grid_label": "Grid F/9"}],
         "separation_revit_ft": 82.1}, True)
    assert "MATCH withheld" in registration({"quality": {"match_allowed": False}})
    assert "same direction" in match(
        {"counts": {"total": 2, "by_status": {"MATCH": 1}}}, systematic=3, sampled=4)
    print("phase_summary self-check OK")
