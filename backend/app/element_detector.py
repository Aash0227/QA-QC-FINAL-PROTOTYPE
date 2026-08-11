"""Generic multi-category element mark detector for any structural PDF.

Generalizes the *pattern* of s201_detector.py (which stays frozen and
Madera-specific) to every mark category whose vocabulary was learned from the
sheet's own schedule tables (see schedule_tables.py). Two-pass over the whole
document:

  pass 1: per page — sheet number + schedule tables -> GLOBAL mark vocabulary
  pass 2: per page — plan-area mark tokens matching the learned vocabulary

Honesty rules carried over from the holdown pipeline:
  - marks found on the plan but absent from every schedule -> schedule_listed=false
  - count-prefix "(2)SW-1" expands to 2 instances that share the label center,
    flagged expanded_synthetic=true (no leader-following in this pass)
  - the locked Madera 54-baseline is NOT a gate here; the generalized QA is
    count_consistency[] (schedule vs plan presence per mark).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz

from . import progress
from .schedule_tables import (
    CATEGORY_MARK_RE,
    discover_tables,
    learned_vocabulary,
)

SCHEMA_VERSION = "element-intelligence/1.0"

# S-201 / S240 / SD14 (Madera style), letter-suffixed splits like S-201-A /
# S-202-B (data-center style), plus dotted styles S1.0 / SD1.3 / A-3.1.
SHEET_NUMBER_RE = re.compile(r"^[A-Z]{1,3}-?\d{1,3}(?:\.\d{1,2})?(?:-?[A-Z])?$")
COUNT_PREFIX_RE = re.compile(r"^\((\d{1,2})\)$")
EMBEDDED_COUNT_RE = re.compile(r"^\((\d{1,2})\)(?P<rest>\S+)$")
DETAIL_REF_RE = re.compile(r"^\d{1,2}/[A-Z]{1,2}-?\d{3}$|^[A-Z]{1,2}-?\d{3}$")

TITLE_STRIP_FRACTION = 0.12   # rightmost strip assumed title block
TABLE_PAD_PT = 6.0
NEIGHBOR_RADIUS_PT = 18.0


def detect_sheet_number(words: list[tuple], page_width: float) -> str | None:
    """Sheet number from the title block: candidates in the rightmost strip,
    preferring the tallest (largest font), then the lowest on the page."""
    strip_x = page_width * (1.0 - TITLE_STRIP_FRACTION)
    candidates = [
        w for w in words
        if SHEET_NUMBER_RE.match(str(w[4]).strip().upper()) and (w[0] + w[2]) / 2.0 >= strip_x
    ]
    if not candidates:
        return None
    best = max(candidates, key=lambda w: (w[3] - w[1], w[3]))
    return str(best[4]).strip().upper()


def _inside_any(x: float, y: float, bboxes: list[list[float]], pad: float = 0.0) -> bool:
    return any(
        b[0] - pad <= x <= b[2] + pad and b[1] - pad <= y <= b[3] + pad
        for b in bboxes
    )


def _category_for(
    token: str,
    vocab: dict[str, dict[str, Any]],
    overrides: dict[str, Any] | None = None,
) -> tuple[str | None, bool, str, str | None]:
    """(category, schedule_listed, mark, taught_by) for a token.

    Order: human-taught excludes drop the token, then aliases (teach.py) win,
    then learned vocabulary, then taught mark patterns, then built-in regexes."""
    if overrides:
        if token in overrides.get("excludes", {}):
            return None, False, token, None
        alias = overrides.get("aliases", {}).get(token)
        if alias:
            category, mark = alias["category"], alias["mark"]
            listed = mark in vocab.get(category, {})
            return category, listed, mark, alias.get("taught_by")
    for category, marks in vocab.items():
        if category in ("wall_type", "unknown"):
            continue  # wall types are SPEC_ONLY rows; bare digits on a plan
            # are dimension/grid text, never wall-type callouts
        if token in marks:
            return category, True, token, None
    if overrides:
        for category, patterns in overrides.get("mark_patterns", {}).items():
            for p in patterns:
                if re.match(p, token, re.IGNORECASE):
                    return category, token in vocab.get(category, {}), token, "taught_pattern"
    for category, pattern in CATEGORY_MARK_RE.items():
        if category == "wall_type":
            continue  # bare digits on a plan are NOT wall-type callouts
        if pattern.match(token):
            return category, False, token, None
    return None, False, token, None


def detect_marks(
    words: list[tuple],
    vocab: dict[str, dict[str, Any]],
    table_bboxes: list[list[float]],
    page_width: float,
    page_height: float,
    sheet_number: str,
    overrides: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Plan-area mark instances. Excludes schedule-table regions and the title
    strip; expands count prefixes; filters detail references (e.g. 5/S-501)."""
    strip_x = page_width * (1.0 - TITLE_STRIP_FRACTION)
    marks: list[dict[str, Any]] = []
    seq: dict[str, int] = {}

    for i, w in enumerate(words):
        raw = str(w[4]).strip()
        token = raw.upper()
        total = 1

        embedded = EMBEDDED_COUNT_RE.match(token)
        if embedded:
            total = int(embedded.group(1))
            token = embedded.group("rest")

        category, listed, mapped_mark, taught_by = _category_for(token, vocab, overrides)
        if category is None:
            continue

        xc = (w[0] + w[2]) / 2.0
        yc = (w[1] + w[3]) / 2.0
        if xc >= strip_x or _inside_any(xc, yc, table_bboxes, pad=TABLE_PAD_PT):
            continue
        if xc < 0 or yc < 0 or xc > page_width or yc > page_height:
            continue

        # Neighbor scan: separate "(2)" prefix token / detail-reference filter.
        is_detail_ref = False
        for other in words[max(0, i - 6): i + 7]:
            if other is w:
                continue
            ox = (other[0] + other[2]) / 2.0
            oy = (other[1] + other[3]) / 2.0
            if abs(oy - yc) > 6.0 or abs(ox - xc) > NEIGHBOR_RADIUS_PT * 3:
                continue
            otext = str(other[4]).strip().upper()
            if DETAIL_REF_RE.match(otext) and abs(ox - xc) <= NEIGHBOR_RADIUS_PT * 2:
                is_detail_ref = True
                break
            prefix = COUNT_PREFIX_RE.match(otext)
            if prefix and 0 < xc - ox <= NEIGHBOR_RADIUS_PT * 2 and total == 1:
                total = int(prefix.group(1))
        if is_detail_ref:
            continue

        key = f"{sheet_number.lower()}_{category}_{mapped_mark.lower()}"
        for m_index in range(1, total + 1):
            seq[key] = seq.get(key, 0) + 1
            marks.append(
                {
                    "id": f"{key}_{seq[key]:03d}",
                    "category": category,
                    "mark": mapped_mark,
                    "taught_by": taught_by,
                    "raw_text": raw,
                    "bbox_pdf": [w[0], w[1], w[2], w[3]],
                    "center_pdf": [round(xc, 2), round(yc, 2)],
                    "schedule_listed": listed,
                    "multiplicity_index": m_index,
                    "total_multiplicity": total,
                    "expanded_synthetic": total > 1,
                }
            )
    return marks


def _count_consistency(
    marks: list[dict[str, Any]], vocab: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Generalized honest QA: per (category, mark) — how many plan instances vs
    whether the schedule lists it. Schedule marks with zero plan hits are
    surfaced too."""
    plan_counts: dict[tuple[str, str], int] = {}
    for m in marks:
        plan_counts[(m["category"], m["mark"])] = plan_counts.get((m["category"], m["mark"]), 0) + 1
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for (category, mark), count in sorted(plan_counts.items()):
        listed = mark in vocab.get(category, {})
        rows.append(
            {"category": category, "mark": mark, "plan_count": count, "schedule_listed": listed}
        )
        seen.add((category, mark))
    for category, entries in vocab.items():
        for mark in entries:
            if (category, mark) not in seen:
                rows.append(
                    {"category": category, "mark": mark, "plan_count": 0, "schedule_listed": True}
                )
    rows.sort(key=lambda r: (r["category"], r["mark"]))
    return rows


def scan_pdf(pdf_path: Path, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Two-pass scan of every page: tables + global vocabulary, then plan marks.
    Only pages with a detected sheet number AND (marks or tables) are emitted.
    overrides = teach.build_overrides() output (human-taught rules)."""
    doc = fitz.open(pdf_path)
    try:
        pages: list[dict[str, Any]] = []
        for index in range(doc.page_count):
            page = doc[index]
            words = page.get_text("words")
            rect = page.rect
            pages.append(
                {
                    "page_index": index,
                    "page_size_pt": [round(rect.width, 2), round(rect.height, 2)],
                    "words": words,
                    "sheet_number": detect_sheet_number(words, rect.width),
                    "tables": discover_tables(words, overrides),
                }
            )

        excludes = (overrides or {}).get("excludes", {})
        global_vocab: dict[str, dict[str, Any]] = {}
        for p in pages:
            for category, entries in learned_vocabulary(p["tables"]).items():
                for mark, spec in entries.items():
                    if mark.upper() in excludes:
                        continue  # excluded marks leave the schedule vocabulary too
                    global_vocab.setdefault(category, {}).setdefault(mark, spec)

        sheets: list[dict[str, Any]] = []
        for p in pages:
            if not p["sheet_number"]:
                continue
            table_bboxes = [t["bbox"] for t in p["tables"]]
            marks = detect_marks(
                p["words"],
                global_vocab,
                table_bboxes,
                p["page_size_pt"][0],
                p["page_size_pt"][1],
                p["sheet_number"],
                overrides,
            )
            if not marks and not p["tables"]:
                continue
            progress.emit(
                "extract", "info",
                f"{p['sheet_number']}: {len(p['tables'])} tables, {len(marks)} marks",
                {"sheet": p["sheet_number"]},
            )
            sheets.append(
                {
                    "sheet_number": p["sheet_number"],
                    "page_index": p["page_index"],
                    "page_size_pt": p["page_size_pt"],
                    "tables": p["tables"],
                    "marks": marks,
                    "count_consistency": _count_consistency(marks, global_vocab),
                }
            )

        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_file": str(pdf_path),
            "page_count": doc.page_count,
            "vocabulary": {
                category: sorted(entries) for category, entries in global_vocab.items()
            },
            "summary": {
                "sheet_count": len(sheets),
                "marks_by_category": _marks_by_category(sheets),
            },
            "sheets": sheets,
        }
    finally:
        doc.close()


def _marks_by_category(sheets: list[dict[str, Any]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for sheet in sheets:
        for m in sheet["marks"]:
            totals[m["category"]] = totals.get(m["category"], 0) + 1
    return dict(sorted(totals.items()))


if __name__ == "__main__":
    # Self-check on pure functions (no PDF needed).
    def w(x0, y, text, width=20.0, h=8.0):
        return (x0, y, x0 + width, y + h, text, 0, 0, 0)

    vocab = {"shear_wall": {"SW-1": {}}, "post": {"P-1": {}}}
    words = [
        w(400, 300, "SW-1"),                      # plan callout, listed
        w(600, 500, "(2)"), w(625, 500, "P-1"),   # count prefix -> 2 instances
        w(700, 700, "C-4"),                       # regex hit, NOT in schedule
        w(900, 900, "5/S-501"),                   # detail ref, not a mark
        w(2500, 400, "SW-1"),                     # title strip -> excluded
        w(120, 118, "P-1"),                       # inside table bbox -> excluded
    ]
    marks = detect_marks(words, vocab, [[100, 100, 200, 140]], 2592, 1728, "S-202")
    by_mark = {}
    for m in marks:
        by_mark.setdefault(m["mark"], []).append(m)
    assert len(by_mark["SW-1"]) == 1 and by_mark["SW-1"][0]["schedule_listed"]
    assert len(by_mark["P-1"]) == 2 and by_mark["P-1"][1]["expanded_synthetic"]
    assert len(by_mark["C-4"]) == 1 and not by_mark["C-4"][0]["schedule_listed"]
    assert "5/S-501" not in by_mark
    cc = _count_consistency(marks, {**vocab, "steel_column": {"C-1": {}}})
    zero = next(r for r in cc if r["mark"] == "C-1")
    assert zero["plan_count"] == 0 and zero["schedule_listed"]
    c4 = next(r for r in cc if r["mark"] == "C-4")
    assert not c4["schedule_listed"]
    sheet = detect_sheet_number([w(2540, 1700, "S-202", 30, 14), w(2540, 200, "S-501", 20, 8)], 2592)
    assert sheet == "S-202", sheet
    print("element_detector self-check OK:", sorted(by_mark))
