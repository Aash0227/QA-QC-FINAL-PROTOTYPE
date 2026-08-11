"""Benchmark Autopilot (AUTOPILOT_PLAN.md P3) — single module.

Two coupled concerns live here so every benchmark-related call site (PDF
extraction, grid-based proposal, 11-state wizard state machine, calibration
handoff, verification) is in one file:

1. **PDF benchmark extraction** (BM-1/BM-2).
   Pass 1 (primary): PDF *annotations* — the team stamps the crosshair asset
   in Bluebeam Revu with Subject ``BM-1``/``BM-2``. Annotations live above the
   drawing content, carry an exact rect, and can never be confused with
   drafting. FreeText is EXCLUDED: the team's existing review comments are
   FreeText and must never be misread as benchmarks.
   Pass 2 (fallback, flattened sets): a drawn crosshair symbol — a closed
   near-circular loop (radius 6-30pt) with two perpendicular straight lines
   through its center extending beyond the circle. A mark is assigned ONLY
   when a ``BM-x`` text span sits adjacent; bare symbols are reported as
   ``candidates_unassigned``, never guessed.

2. **Workflow state machine** — persistent, audit-logged workflow that
   coordinates the zero-click 2-benchmark registration between the webapp
   (human approvals) and a Claude agent driving Revit via Nonica MCP. The
   machine itself NEVER computes or saves a transform — calibration only ever
   happens through the gated ``POST /api/registration/benchmarks``
   (``registration.compute_calibration_from_benchmarks`` +
   ``registration_usable``). This part only records what happened, in order,
   with an audit trail modeled on ``review.py``'s resolution blocks.

States:
  idle -> proposing -> awaiting_pdf_approval -> stamping -> awaiting_revit
       -> placing_markers -> awaiting_revit_approval -> awaiting_export
       -> calibrating -> done | failed
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from typing import Any

from . import config

# =====================================================================
# 1. PDF benchmark extraction
# =====================================================================
BM_MARK_RE = re.compile(r"\bBM[-_ ]?(\d)\b", re.IGNORECASE)
ANNOT_TYPES = ("Stamp", "Square", "Circle")   # FreeText deliberately absent
VECTOR_R_MIN, VECTOR_R_MAX = 6.0, 30.0
VECTOR_TEXT_NEAR_PT = 60.0

EXTRACT_SCHEMA_VERSION = "pdf-benchmarks/1.0"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def extract_pdf_benchmarks(
    pdf_path: Any,
    page_index: int | None = None,
    marks: tuple[str, ...] = ("BM-1", "BM-2"),
) -> dict[str, Any]:
    """Find benchmark points on one page. Duplicate mark = hard error dict."""
    import fitz

    want = {m.upper() for m in marks}
    found: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    candidates_unassigned: list[dict[str, Any]] = []

    with fitz.open(str(pdf_path)) as doc:
        pages = [page_index] if page_index is not None else range(doc.page_count)
        hit_page = None
        for pi in pages:
            page = doc[pi]
            page_found = _annotation_pass(page, want)
            if not page_found or len(page_found) < len(want):
                vec_found, vec_unassigned = _vector_pass(page, want - set(page_found))
                for m, rec in vec_found.items():
                    page_found.setdefault(m, rec)
                if vec_unassigned and page_found:
                    candidates_unassigned.extend(
                        dict(c, page_index=pi) for c in vec_unassigned)
            if not page_found:
                continue
            dupes = [m for m in page_found if m in found]
            if dupes:
                return {
                    "schema_version": EXTRACT_SCHEMA_VERSION,
                    "created_at": _now_iso(),
                    "error": (f"Benchmark mark(s) {dupes} found on multiple pages "
                              f"({found[dupes[0]]['page_index']} and {pi}) — stamp "
                              "each mark exactly once."),
                    "benchmarks": [], "warnings": warnings,
                }
            for m, rec in page_found.items():
                rec["page_index"] = pi
                found[m] = rec
            hit_page = pi
            if want <= set(found):
                break
        page_size = None
        if hit_page is not None:
            r = doc[hit_page].rect
            page_size = {"width": r.width, "height": r.height}

    missing = sorted(want - set(found))
    if missing:
        warnings.append(
            f"Mark(s) not found: {', '.join(missing)}. Stamp them in Bluebeam "
            "(Subject BM-1/BM-2) or draw the crosshair symbol with a BM-x label.")
    pages_used = {rec["page_index"] for rec in found.values()}
    if len(pages_used) > 1:
        warnings.append(
            f"Benchmarks found on DIFFERENT pages {sorted(pages_used)} — both "
            "must be on the same plan sheet.")

    return {
        "schema_version": EXTRACT_SCHEMA_VERSION,
        "created_at": _now_iso(),
        "page_index": (sorted(pages_used)[0] if len(pages_used) == 1 else None),
        "page_size": page_size,
        "benchmarks": [
            {"mark": m, **rec} for m, rec in sorted(found.items())
        ],
        "candidates_unassigned": candidates_unassigned,
        "warnings": warnings,
    }


def _annotation_pass(page, want: set[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    annot = page.first_annot
    while annot:
        try:
            kind = annot.type[1] if isinstance(annot.type, (tuple, list)) else str(annot.type)
            if kind in ANNOT_TYPES:
                info = annot.info or {}
                text = " ".join(str(info.get(k, "")) for k in ("subject", "title", "content"))
                m = BM_MARK_RE.search(text)
                if m:
                    mark = f"BM-{m.group(1)}"
                    if mark in want or not want:
                        r = annot.rect
                        rec = {
                            "point_pt": {"x": (r.x0 + r.x1) / 2, "y": (r.y0 + r.y1) / 2},
                            "method": "annotation_stamp",
                            "confidence": 0.98,
                            "annot_type": kind,
                        }
                        if mark in out:
                            raise ValueError(
                                f"Duplicate benchmark stamp '{mark}' on one page.")
                        out[mark] = rec
        except ValueError:
            raise
        except Exception:
            pass
        annot = annot.next
    return out


def _vector_pass(page, want: set[str]):
    """Crosshair symbol fallback: near-circular closed loop + 2 long lines
    through its center. Mark requires an adjacent BM-x text span."""
    if not want:
        return {}, []
    circles: list[tuple[float, float, float]] = []
    lines: list[tuple[tuple[float, float], tuple[float, float]]] = []
    try:
        drawings = page.get_drawings()
    except Exception:
        return {}, []
    for d in drawings:
        for item in d.get("items", []):
            if item[0] == "l":
                p0, p1 = item[1], item[2]
                lines.append(((p0.x, p0.y), (p1.x, p1.y)))
        rect = d.get("rect")
        if rect is None:
            continue
        w, h = rect.width, rect.height
        if w <= 0 or h <= 0:
            continue
        if (VECTOR_R_MIN * 2 <= w <= VECTOR_R_MAX * 2
                and abs(w - h) <= 0.25 * max(w, h)
                and any(item[0] == "c" for item in d.get("items", []))):
            circles.append(((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2,
                            max(w, h) / 2))

    words = None
    found: dict[str, dict[str, Any]] = {}
    unassigned: list[dict[str, Any]] = []
    for cx, cy, r in circles:
        through: list[float] = []
        for (x0, y0), (x1, y1) in lines:
            dx, dy = x1 - x0, y1 - y0
            ll = math.hypot(dx, dy)
            if ll < 2 * r * 1.3:
                continue
            dist = abs(dy * (cx - x0) - dx * (cy - y0)) / ll
            if dist <= r * 0.25:
                through.append(math.atan2(dy, dx) % math.pi)
        ok = False
        for i in range(len(through)):
            for j in range(i + 1, len(through)):
                ang = abs(through[i] - through[j])
                ang = min(ang, math.pi - ang)
                if abs(ang - math.pi / 2) <= math.radians(10):
                    ok = True
        if not ok:
            continue
        if words is None:
            words = page.get_text("words")
        mark = None
        best_d = VECTOR_TEXT_NEAR_PT
        for w in words:
            m = BM_MARK_RE.search(w[4])
            if not m:
                continue
            wx, wy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
            dist = math.hypot(wx - cx, wy - cy)
            if dist < best_d:
                best_d = dist
                mark = f"BM-{m.group(1)}"
        rec = {"point_pt": {"x": cx, "y": cy}, "method": "vector_symbol",
               "confidence": 0.85, "radius_pt": round(r, 2)}
        if mark and mark.upper() in want and mark not in found:
            found[mark] = rec
        else:
            unassigned.append(rec)
    return found, unassigned


# =====================================================================
# 2. Workflow state machine + autopilot helpers
# =====================================================================
SCHEMA_VERSION = "benchmark-workflow/1.0"

STATES = (
    "idle", "proposing", "awaiting_pdf_approval", "stamping",
    "awaiting_revit", "placing_markers", "awaiting_revit_approval",
    "awaiting_export", "calibrating", "done", "failed",
)

# Every legal edge. "failed" is reachable from any active state; a finished
# or failed run can only restart by proposing again.
TRANSITIONS: dict[str, set[str]] = {
    "idle": {"proposing"},
    "proposing": {"awaiting_pdf_approval", "failed"},
    "awaiting_pdf_approval": {"stamping", "failed"},
    "stamping": {"awaiting_revit", "failed"},
    "awaiting_revit": {"placing_markers", "failed"},
    "placing_markers": {"awaiting_revit_approval", "failed"},
    "awaiting_revit_approval": {"awaiting_export", "failed"},
    "awaiting_export": {"calibrating", "failed"},
    "calibrating": {"done", "failed"},
    "done": {"proposing"},
    "failed": {"proposing"},
}

# Human approval gates: state -> state entered on approve. Reject -> failed.
APPROVAL_GATES: dict[str, str] = {
    "awaiting_pdf_approval": "stamping",
    "awaiting_revit_approval": "awaiting_export",
}

# Agent progress reports: step name -> (required current state, next state).
ADVANCE_STEPS: dict[str, tuple[str, str]] = {
    "stamped": ("stamping", "awaiting_revit"),
    "revit_connected": ("awaiting_revit", "placing_markers"),
    "markers_placed": ("placing_markers", "awaiting_revit_approval"),
    "export_received": ("awaiting_export", "calibrating"),
    "calibrated": ("calibrating", "done"),
}


def default_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "state": "idle",
        "updated_at": None,
        "proposal": None,
        "history": [],
    }


def load() -> dict[str, Any]:
    path = config.artifact_path("benchmark_workflow")
    if not path.exists():
        return default_state()
    return json.loads(path.read_text(encoding="utf-8"))


def save(wf: dict[str, Any]) -> None:
    config.artifact_path("benchmark_workflow").write_text(
        json.dumps(wf, indent=2), encoding="utf-8"
    )


def transition(
    wf: dict[str, Any],
    to_state: str,
    actor: str,
    note: str = "",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validated state change. Mutates + returns wf; raises ValueError on an
    illegal edge so endpoints can 409 without ever writing a bad state."""
    frm = wf.get("state", "idle")
    if to_state not in STATES:
        raise ValueError(f"Unknown state '{to_state}'.")
    if to_state not in TRANSITIONS.get(frm, set()):
        raise ValueError(f"Illegal transition {frm} -> {to_state}.")
    now = datetime.now(timezone.utc).isoformat()
    wf["state"] = to_state
    wf["updated_at"] = now
    wf["history"].append(
        {
            "ts": now,
            "actor": actor,
            "from": frm,
            "to": to_state,
            "note": note,
            "payload": payload or {},
        }
    )
    if to_state == "awaiting_revit_approval" and (payload or {}).get("readback"):
        # Marker placement is driven from a Revit router that this module never
        # calls; the transition it reports is the one seam every placement path
        # shares, so the placement summary is minted here. Only a real
        # server-obtained read-back triggers it, and a failure stays silent.
        try:
            from . import phase_summary

            phase_summary.record(
                "revit_placement",
                phase_summary.revit_placement(wf.get("proposal"), payload),
            )
        except Exception:
            pass
    return wf


# ---------------------------------------------------------------------------
# Proposal geometry (pure — endpoint feeds it PDF + Revit control points)
# ---------------------------------------------------------------------------
def bubble_row_positions(
    words: list[tuple],
    page_w: float,
    page_h: float,
    grid_labels: set[str],
    band_fraction: float = 0.14,
    tol_pt: float = 8.0,
) -> tuple[dict[str, float], dict[str, float]]:
    """Crowded-sheet grid-bubble detector: the TRUE grid bubbles
    all sit on one thin row (vertical grids: same y in the top/bottom band)
    or one thin column (horizontal grids: same x in the left/right band),
    exactly one bubble per label. Find the cluster holding the most distinct
    labels uniquely (>=2); anything else stays honestly undetected."""
    band_x, band_y = page_w * band_fraction, page_h * band_fraction
    tb: list[tuple[str, float, float]] = []
    lr: list[tuple[str, float, float]] = []
    for w in words:
        text = str(w[4]).strip().upper()
        if text not in grid_labels:
            continue
        xc, yc = (w[0] + w[2]) / 2.0, (w[1] + w[3]) / 2.0
        if yc < band_y or yc > page_h - band_y:
            tb.append((text, xc, yc))
        if xc < band_x or xc > page_w - band_x:
            lr.append((text, xc, yc))

    def best_cluster(
        cands: list[tuple[str, float, float]], axis: int
    ) -> dict[str, float]:
        best: dict[str, float] = {}
        for _, *anchor in cands:
            center = anchor[axis - 1]
            members = [c for c in cands if abs(c[axis] - center) <= tol_pt]
            labels: dict[str, list[float]] = {}
            for lab, x, y in members:
                labels.setdefault(lab, []).append((x, y)[2 - axis])
            unique = {lab: v[0] for lab, v in labels.items() if len(v) == 1}
            if len(unique) >= 2 and len(unique) > len(best):
                best = unique
        return best

    vertical = best_cluster(tb, axis=2)
    horizontal = best_cluster(lr, axis=1)
    return vertical, horizontal


def resolve_pdf_grid_points(
    words: list[tuple],
    revit_points: list[dict[str, Any]],
    tol_pt: float = 6.0,
) -> list[dict[str, Any]]:
    """Axis-agnostic PDF grid-intersection resolver."""
    rev_ids = {p["id"] for p in revit_points}
    labels = {part for gid in rev_ids for part in gid.split("_")[1:]}
    cands: list[tuple[float, float, str]] = []
    for w in words:
        text = str(w[4]).strip().upper()
        if text in labels:
            cands.append(((w[0] + w[2]) / 2.0, (w[1] + w[3]) / 2.0, text))

    def richest(mode: str) -> dict[str, float]:
        share = (lambda c: c[0]) if mode == "col" else (lambda c: c[1])
        store = (lambda c: c[1]) if mode == "col" else (lambda c: c[0])
        best: dict[str, float] = {}
        for anchor in cands:
            center = share(anchor)
            grouped: dict[str, list[float]] = {}
            for c in cands:
                if abs(share(c) - center) <= tol_pt:
                    grouped.setdefault(c[2], []).append(store(c))
            uniq = {lab: v[0] for lab, v in grouped.items() if len(v) == 1}
            if len(uniq) > len(best):
                best = uniq
        return best

    col_y = richest("col")
    row_x = richest("row")
    points: list[dict[str, Any]] = []
    for cl, y in col_y.items():
        for rl, x in row_x.items():
            letters = [p for p in (cl, rl) if p[0].isalpha()]
            numbers = [p for p in (cl, rl) if not p[0].isalpha()]
            if len(letters) != 1 or len(numbers) != 1:
                continue
            gid = f"grid_{letters[0]}_{numbers[0]}"
            if gid in rev_ids:
                points.append(
                    {"id": gid, "label": f"Grid {letters[0]}/{numbers[0]}",
                     "point": {"x": round(x, 2), "y": round(y, 2)}}
                )
    return points


def pick_max_diagonal_pair(
    points: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], float] | None:
    best: tuple[dict[str, Any], dict[str, Any], float] | None = None
    for i, a in enumerate(points):
        for b in points[i + 1:]:
            d = math.hypot(
                b["point"]["x"] - a["point"]["x"],
                b["point"]["y"] - a["point"]["y"],
            )
            if best is None or d > best[2]:
                best = (a, b, d)
    return best


def _join_pdf_revit(
    pdf_points: list[dict[str, Any]], revit_points: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rev_by_id = {p["id"]: p for p in revit_points}
    return [
        {"id": p["id"], "label": p.get("label"), "point": p["point"],
         "revit_point": rev_by_id[p["id"]]["point"]}
        for p in pdf_points if p["id"] in rev_by_id
    ]


def _benchmark(mark: str, p: dict[str, Any]) -> dict[str, Any]:
    return {
        "mark": mark,
        "grid_id": p["id"],
        "grid_label": p.get("label"),
        "pdf_point_pt": {"x": p["point"]["x"], "y": p["point"]["y"]},
        "revit_point_ft": {"x": p["revit_point"]["x"], "y": p["revit_point"]["y"]},
    }


def _proposal(
    pair: list[dict[str, Any]],
    joined: list[dict[str, Any]],
    sep_pt: float,
    sheet_number: str | None,
    page_index: int | None,
) -> dict[str, Any]:
    sep_ft = math.hypot(
        pair[1]["revit_point"]["x"] - pair[0]["revit_point"]["x"],
        pair[1]["revit_point"]["y"] - pair[0]["revit_point"]["y"],
    )
    return {
        "sheet_number": sheet_number,
        "page_index": page_index,
        "benchmarks": [_benchmark(f"BM-{i + 1}", p) for i, p in enumerate(pair)],
        "separation_pdf_pt": round(sep_pt, 2),
        "separation_revit_ft": round(sep_ft, 2),
        "candidates_considered": len(joined),
    }


def propose_from_geometry(
    pdf_points: list[dict[str, Any]],
    revit_points: list[dict[str, Any]],
    sheet_number: str | None,
    page_index: int | None,
) -> dict[str, Any]:
    joined = _join_pdf_revit(pdf_points, revit_points)
    if len(joined) < 2:
        raise ValueError(
            f"Only {len(joined)} labeled grid intersections exist on both the "
            "PDF sheet and the Revit export — need 2+ to propose benchmarks."
        )
    a, b, sep_pt = pick_max_diagonal_pair(joined)  # type: ignore[misc]
    pair = sorted([a, b], key=lambda p: (p["revit_point"]["x"], p["revit_point"]["y"]))
    return _proposal(pair, joined, sep_pt, sheet_number, page_index)


def propose_from_points(
    pdf_points: list[dict[str, Any]],
    revit_points: list[dict[str, Any]],
    selected: list[dict[str, Any]],
    sheet_number: str | None,
    page_index: int | None,
) -> dict[str, Any]:
    """Manual variant of propose_from_geometry."""
    by_id = {p["id"]: p for p in _join_pdf_revit(pdf_points, revit_points)}
    if len(selected) != 2:
        raise ValueError(f"Pick exactly 2 grid intersections; got {len(selected)}.")
    chosen: dict[str, dict[str, Any]] = {}
    for s in selected:
        gid, mark = s.get("grid_id"), s.get("mark")
        if gid not in by_id:
            raise ValueError(
                f"Grid '{gid}' is not a labeled intersection present on both the "
                "PDF sheet and the Revit export."
            )
        chosen[mark] = by_id[gid]
    if set(chosen) != {"BM-1", "BM-2"}:
        raise ValueError(f"Marks must be exactly BM-1 and BM-2; got {sorted(chosen)}.")
    if chosen["BM-1"]["id"] == chosen["BM-2"]["id"]:
        raise ValueError("BM-1 and BM-2 must be two different intersections.")
    pair = [chosen["BM-1"], chosen["BM-2"]]
    sep_pt = math.hypot(
        pair[1]["point"]["x"] - pair[0]["point"]["x"],
        pair[1]["point"]["y"] - pair[0]["point"]["y"],
    )
    return _proposal(pair, list(by_id.values()), sep_pt, sheet_number, page_index)


STAMP_TOLERANCE_PT = 3.0


def verify_stamped_benchmarks(
    proposal: dict[str, Any],
    extracted: dict[str, Any],
    tolerance_pt: float = STAMP_TOLERANCE_PT,
) -> dict[str, Any]:
    """Compare extract_pdf_benchmarks() output against the approved proposal.
    Never trusts a caller's word that stamping happened — reads the PDF back
    and checks each mark landed within tolerance of the point that was
    actually approved in awaiting_pdf_approval."""
    found = {b["mark"]: b["point_pt"] for b in extracted.get("benchmarks", [])}
    checks: list[dict[str, Any]] = []
    ok = True
    for bm in proposal["benchmarks"]:
        mark, exp = bm["mark"], bm["pdf_point_pt"]
        got = found.get(mark)
        delta = math.hypot(got["x"] - exp["x"], got["y"] - exp["y"]) if got else None
        mark_ok = got is not None and delta <= tolerance_pt
        ok = ok and mark_ok
        checks.append(
            {
                "mark": mark,
                "expected": exp,
                "found": got,
                "delta_pt": round(delta, 3) if delta is not None else None,
                "ok": mark_ok,
            }
        )
    reason = None if ok else "Off-tolerance/missing: " + ", ".join(
        c["mark"] for c in checks if not c["ok"]
    )
    return {"ok": ok, "checks": checks, "reason": reason}


if __name__ == "__main__":
    # Self-check: state-machine legality + extraction smoke + verify.
    wf = default_state()
    transition(wf, "proposing", "agent")
    transition(wf, "awaiting_pdf_approval", "agent", payload={"n": 4})
    try:
        transition(wf, "done", "agent")
        raise AssertionError("illegal edge accepted")
    except ValueError:
        pass
    pts = [{"id": k, "point": {"x": x, "y": y}}
           for k, x, y in (("a", 0, 0), ("b", 10, 0), ("c", 0, 10), ("d", 7, 7))]
    a, b, d = pick_max_diagonal_pair(pts)
    assert {a["id"], b["id"]} == {"b", "c"} and abs(d - math.hypot(10, 10)) < 1e-9
    proposal = {"benchmarks": [
        {"mark": "BM-1", "pdf_point_pt": {"x": 100.0, "y": 200.0}},
        {"mark": "BM-2", "pdf_point_pt": {"x": 500.0, "y": 600.0}},
    ]}
    good = {"benchmarks": [
        {"mark": "BM-1", "point_pt": {"x": 101.0, "y": 200.5}},
        {"mark": "BM-2", "point_pt": {"x": 500.0, "y": 600.0}},
    ]}
    bad = {"benchmarks": [{"mark": "BM-1", "point_pt": {"x": 999.0, "y": 999.0}}]}
    assert verify_stamped_benchmarks(proposal, good)["ok"] is True
    v = verify_stamped_benchmarks(proposal, bad)
    assert v["ok"] is False and "BM-2" in v["reason"] and "BM-1" in v["reason"]
    print("benchmark_workflow self-check OK:", wf["state"], len(wf["history"]))
