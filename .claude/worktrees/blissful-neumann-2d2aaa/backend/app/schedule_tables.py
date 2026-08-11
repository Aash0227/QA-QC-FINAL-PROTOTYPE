"""Generic schedule-table discovery and parsing for structural sheets.

Generalizes what s201_detector.py hardcodes for Madera (S201_TABLE_BBOXES,
HOLDOWN_ROW_BANDS): instead of fixed bboxes and y-bands, tables are DISCOVERED
by their header text ("POST SCHEDULE", "SHEAR WALL SCHEDULE", ...) and their
column layout is inferred from the sub-header row. The mark vocabulary (which
H/SW/P/C marks are valid for this drawing set) is LEARNED from the MARK column
of each parsed table — nothing is hardcoded to Madera.

Works on plain PyMuPDF word tuples (x0, y0, x1, y1, text, block, line, word_no)
so every function below the page wrappers is pure and unit-testable without a
real PDF.
"""

from __future__ import annotations

import re
from typing import Any

# Known schedule categories. The generic \bSCHEDULE\b fallback keeps unknown
# table types visible (category="unknown") instead of silently dropped.
CATEGORY_HEADERS: dict[str, str] = {
    "holdown": r"HOLD[- ]?(?:DOWN|OWN)\s+SCHEDULE",
    "shear_wall": r"SHEAR\s+WALL\s+SCHEDULE",
    "post": r"POST\s+SCHEDULE",
    # "STEEL COLUMN SCHEDULE" (Madera) or plain "COLUMN SCHEDULE" (LGS sets).
    "steel_column": r"(?:STEEL\s+)?COLUMN\s+SCHEDULE",
    "wall_type": r"WALL\s+SPEC(?:IFICATION)?",
}
GENERIC_HEADER_RE = re.compile(r"\bSCHEDULE\b")

CATEGORY_MARK_RE: dict[str, re.Pattern[str]] = {
    # Common mark families across clients: H1 (Madera), HD1 (LGS sets),
    # HDU/HTT (Simpson), TD (tie-down).
    "holdown": re.compile(r"^(?:H|HD|HDU|HTT|TD)-?\d{1,2}$"),
    "shear_wall": re.compile(r"^SW-?\d{1,2}$"),
    "post": re.compile(r"^P-?\d{1,2}$"),
    "steel_column": re.compile(r"^C-?\d{1,2}$"),
    "wall_type": re.compile(r"^\d{1,2}$"),
}

# Fallback for schedules whose marks don't fit any known family: a short
# letters+digits token in the MARK/SYMBOL column (e.g. "HD15S"). Deliberately
# tight — spec fragments like "600S162-43MIL" or "S/HDU6" must not match.
GENERIC_MARK_RE = re.compile(r"^[A-Z]{1,4}-?\d{1,3}[A-Z]?$")

SUBHEADER_TOKEN_RE = re.compile(r"^(MARK|SYMBOL|TYPE|S\.?NO\.?|SR\.?NO\.?|SW\.?|#)$")
NOTE_RE = re.compile(r"^NOTES?\b")

LINE_Y_TOL_PT = 3.0
COLUMN_GAP_PT = 14.0
ROW_GAP_STOP_FACTOR = 2.5
SUBHEADER_SEARCH_PT = 60.0
TABLE_X_PAD_PT = 10.0


def lines_from_words(
    words: list[tuple], y_tol: float = LINE_Y_TOL_PT
) -> list[dict[str, Any]]:
    """Cluster word tuples into text lines by y-center. Returns lines sorted by
    y, each {y, x0, x1, y0, y1, words:[(x0,y0,x1,y1,text)], text}."""
    entries = sorted(
        ((w[0], w[1], w[2], w[3], str(w[4])) for w in words),
        key=lambda w: ((w[1] + w[3]) / 2.0, w[0]),
    )
    lines: list[dict[str, Any]] = []
    for w in entries:
        yc = (w[1] + w[3]) / 2.0
        if lines and abs(yc - lines[-1]["y"]) <= y_tol:
            line = lines[-1]
            line["words"].append(w)
            n = len(line["words"])
            line["y"] = line["y"] + (yc - line["y"]) / n
        else:
            lines.append({"y": yc, "words": [w]})
    for line in lines:
        ws = sorted(line["words"], key=lambda w: w[0])
        line["words"] = ws
        line["x0"] = min(w[0] for w in ws)
        line["x1"] = max(w[2] for w in ws)
        line["y0"] = min(w[1] for w in ws)
        line["y1"] = max(w[3] for w in ws)
        line["text"] = " ".join(w[4] for w in ws)
    return lines


RUN_GAP_PT = 30.0


def _line_runs(line: dict[str, Any], gap: float = RUN_GAP_PT) -> list[list[tuple]]:
    """Split a y-clustered line into contiguous x-runs. Plan text sitting at the
    same y as a table header would otherwise merge into it and sprawl the
    header bbox across the whole sheet."""
    runs: list[list[tuple]] = []
    for w in line["words"]:
        if runs and w[0] - runs[-1][-1][2] <= gap:
            runs[-1].append(w)
        else:
            runs.append([w])
    return runs


def find_schedule_headers(
    words: list[tuple], overrides: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Find schedule-table header runs. Returns
    [{category, header_text, header_bbox}] sorted by y.

    overrides["headers"] = {category: [regex,...]} — human-taught header
    patterns (teach.py) checked BEFORE the built-ins so a client's
    'TIE-DOWN SCHEDULE' can classify as holdown."""
    taught = (overrides or {}).get("headers", {})
    headers: list[dict[str, Any]] = []
    for line in lines_from_words(words):
        for run in _line_runs(line):
            text = " ".join(w[4] for w in run).upper()
            category = None
            for cat, patterns in taught.items():
                if any(re.search(p, text, re.IGNORECASE) for p in patterns):
                    category = cat
                    break
            if category is None:
                for cat, pattern in CATEGORY_HEADERS.items():
                    if re.search(pattern, text):
                        category = cat
                        break
            if category is None and GENERIC_HEADER_RE.search(text):
                category = "unknown"
            if category is None:
                continue
            headers.append(
                {
                    "category": category,
                    "header_text": " ".join(w[4] for w in run),
                    "header_bbox": [
                        min(w[0] for w in run),
                        min(w[1] for w in run),
                        max(w[2] for w in run),
                        max(w[3] for w in run),
                    ],
                }
            )
    headers.sort(key=lambda h: h["header_bbox"][1])
    return headers


SUBHEADER_X_MARGIN_PT = 320.0


def _find_subheader(
    lines: list[dict[str, Any]],
    header_bbox: list[float],
    category: str,
) -> dict[str, Any] | None:
    """Collect the sub-header BAND below the header: every line until the first
    data line (one whose tokens match the category mark regex). Schedules like
    the shear-wall table stack their column titles over 2+ staggered y-lines,
    so a single-line sub-header would only see a fragment. Words are x-filtered
    around the header so plan text at the same y can't become bogus columns."""
    hx0, _, hx1, hy1 = header_bbox
    pattern = CATEGORY_MARK_RE.get(category)
    x_lo = hx0 - SUBHEADER_X_MARGIN_PT
    x_hi = hx1 + SUBHEADER_X_MARGIN_PT
    band: list[tuple] = []
    data_y0: float | None = None
    for line in lines:
        if line["y0"] <= hy1:
            continue
        if line["y0"] - hy1 > SUBHEADER_SEARCH_PT and not band:
            break
        near = [w for w in line["words"] if x_lo <= (w[0] + w[2]) / 2.0 <= x_hi]
        if not near:
            continue
        if pattern is not None and any(pattern.match(w[4].strip().upper()) for w in near):
            data_y0 = line["y0"]
            break  # first data row reached — the band above it is the sub-header
        band.extend(near)
        if line["y0"] - hy1 > SUBHEADER_SEARCH_PT:
            break
    if data_y0 is not None:
        # Cells of the first data row can sit slightly ABOVE their mark token
        # (marks are vertically centered in tall row bands). Anything at or
        # below the mark line belongs to the body, not the column titles.
        band = [w for w in band if w[3] <= data_y0]
    if not band or not any(
        SUBHEADER_TOKEN_RE.match(w[4].upper().rstrip(".")) for w in band
    ):
        return None
    return {
        "words": band,
        "x0": min(w[0] for w in band),
        "x1": max(w[2] for w in band),
        "y0": min(w[1] for w in band),
        "y1": max(w[3] for w in band),
        "text": " ".join(w[4] for w in sorted(band, key=lambda w: (w[1], w[0]))),
    }


def detect_columns(subheader: dict[str, Any]) -> list[dict[str, Any]]:
    """Cluster sub-header words into columns by x-overlap/x-gap. Words may come
    from several stacked sub-header lines, so cluster on the x-axis only.
    Returns [{name, x0, x1}]."""
    groups: list[dict[str, Any]] = []
    for w in sorted(subheader["words"], key=lambda w: w[0]):
        if groups and w[0] <= groups[-1]["x1"] + COLUMN_GAP_PT:
            groups[-1]["words"].append(w)
            groups[-1]["x1"] = max(groups[-1]["x1"], w[2])
        else:
            groups.append({"words": [w], "x1": w[2]})
    cols = [
        {
            "name": " ".join(
                w[4] for w in sorted(g["words"], key=lambda w: (round(w[1]), w[0]))
            ),
            "x0": min(w[0] for w in g["words"]),
            "x1": max(w[2] for w in g["words"]),
        }
        for g in groups
    ]
    # Widen to midpoints so row cells between titles still land in a column.
    for i in range(len(cols) - 1):
        mid = (cols[i]["x1"] + cols[i + 1]["x0"]) / 2.0
        cols[i]["x1"] = mid
        cols[i + 1]["x0"] = mid
    if cols:
        cols[0]["x0"] -= TABLE_X_PAD_PT
        cols[-1]["x1"] += TABLE_X_PAD_PT
    return cols


def _mark_column_index(
    columns: list[dict[str, Any]], rows: list[list[str | None]], category: str
) -> int:
    """Column whose header says MARK (or a synonym — SYMBOL/#/ID), else the
    column whose cells best match the category mark regex, else 0."""
    for header_word in (r"\bMARK\b", r"\bSYMBOL\b", r"^#$", r"\bID\b"):
        for i, c in enumerate(columns):
            if re.search(header_word, c["name"].upper()):
                return i
    pattern = CATEGORY_MARK_RE.get(category)
    if pattern is not None:
        best_i, best_hits = 0, 0
        for i in range(len(columns)):
            hits = sum(1 for r in rows if r[i] and pattern.match(r[i].strip()))
            if hits > best_hits:
                best_i, best_hits = i, hits
        if best_hits > 0:
            return best_i
    return 0


def parse_rows(
    lines: list[dict[str, Any]],
    columns: list[dict[str, Any]],
    subheader: dict[str, Any],
    category: str,
    stop_y: float | None = None,
) -> tuple[list[dict[str, Any]], list[float]]:
    """Walk lines below the sub-header, assign words to columns, merge wrapped
    continuation lines into the previous row. Returns (rows, table_y_extent)."""
    x0 = columns[0]["x0"]
    x1 = columns[-1]["x1"]
    body: list[dict[str, Any]] = []
    prev_y: float | None = None
    gaps: list[float] = []
    for line in lines:
        if line["y0"] <= subheader["y1"]:
            continue
        if stop_y is not None and line["y0"] >= stop_y:
            break
        inside = [w for w in line["words"] if x0 <= (w[0] + w[2]) / 2.0 <= x1]
        if not inside:
            continue
        if NOTE_RE.match(inside[0][4].upper()):
            break
        if prev_y is not None and gaps:
            median_gap = sorted(gaps)[len(gaps) // 2]
            # 16pt floor: wrapped continuation lines sit ~0pt apart and must not
            # make a normal ~20-35pt row pitch look like the end of the table.
            if line["y0"] - prev_y > ROW_GAP_STOP_FACTOR * max(median_gap, 16.0):
                break
        if prev_y is not None:
            gaps.append(line["y0"] - prev_y)
        prev_y = line["y1"]
        body.append({"y0": line["y0"], "y1": line["y1"], "words": inside})

    if not body:
        return [], []

    # Assign each body line's words to columns.
    raw_rows: list[dict[str, Any]] = []
    for line in body:
        cells: list[str | None] = [None] * len(columns)
        for w in line["words"]:
            xc = (w[0] + w[2]) / 2.0
            for i, c in enumerate(columns):
                if c["x0"] <= xc <= c["x1"]:
                    cells[i] = f"{cells[i]} {w[4]}".strip() if cells[i] else w[4]
                    break
        raw_rows.append({"cells": cells, "y0": line["y0"], "y1": line["y1"]})

    mark_i = _mark_column_index(columns, [r["cells"] for r in raw_rows], category)
    pattern = CATEGORY_MARK_RE.get(category)

    rows: list[dict[str, Any]] = []
    for raw, line in zip(raw_rows, body):
        row_text = " ".join(w[4] for w in line["words"])
        # Row anchor: any word matching the category mark regex. Column-based
        # cells are best-effort display data (stacked sub-headers can merge
        # columns); the mark and row_text are the load-bearing fields.
        mark_cell: str | None = None
        if pattern is not None:
            # wall_type marks are bare digits, so scan tightly (a lone "50 KSI"
            # grade fragment must not anchor a row); real mark tokens (H1/SW-1/
            # P-1/C-1) are distinctive, so a wider window is safe and catches
            # rows merged with same-y annotation columns.
            if category == "wall_type":
                window = line["words"][:2] if len(line["words"]) >= 4 else []
            else:
                window = line["words"][:8]
            for w in window:
                token = w[4].strip().upper()
                if pattern.match(token):
                    mark_cell = token
                    break
            if mark_cell is None and category != "wall_type":
                # Family regex missed (client uses uncommon mark names): fall
                # back to the MARK/SYMBOL column cell if it's token-shaped.
                candidate = (raw["cells"][mark_i] or "").strip().upper()
                if GENERIC_MARK_RE.match(candidate):
                    mark_cell = candidate
        else:
            candidate = (raw["cells"][mark_i] or "").strip()
            mark_cell = candidate or None
        if mark_cell or not rows:
            cells = {
                columns[i]["name"]: raw["cells"][i]
                for i in range(len(columns))
                if raw["cells"][i]
            }
            cells["row_text"] = row_text
            rows.append(
                {
                    "mark": mark_cell,
                    "cells": cells,
                    "row_bbox": [x0, raw["y0"], x1, raw["y1"]],
                }
            )
        else:
            # Wrapped continuation line: append text into the previous row.
            prev = rows[-1]
            for i in range(len(columns)):
                if raw["cells"][i]:
                    name = columns[i]["name"]
                    prev["cells"][name] = (
                        f"{prev['cells'][name]} {raw['cells'][i]}".strip()
                        if prev["cells"].get(name)
                        else raw["cells"][i]
                    )
            prev["cells"]["row_text"] = f"{prev['cells']['row_text']} {row_text}".strip()
            prev["row_bbox"][3] = raw["y1"]
    # Drop rows that captured nothing (stray fragments).
    rows = [r for r in rows if r["cells"]]
    y_extent = [body[0]["y0"], max(r["row_bbox"][3] for r in rows)] if rows else []
    return rows, y_extent


def discover_tables(
    words: list[tuple], overrides: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Full pipeline on one page's words: headers -> sub-header columns -> rows.
    Returns [{category, header_text, bbox, columns, rows}]."""
    lines = lines_from_words(words)
    headers = find_schedule_headers(words, overrides)
    tables: list[dict[str, Any]] = []
    for i, header in enumerate(headers):
        subheader = _find_subheader(lines, header["header_bbox"], header["category"])
        if subheader is None:
            tables.append({**header, "bbox": header["header_bbox"], "columns": [], "rows": []})
            continue
        columns = detect_columns(subheader)
        if not columns:
            tables.append({**header, "bbox": header["header_bbox"], "columns": [], "rows": []})
            continue
        # Stop parsing at the next header below this one (any category).
        next_y = None
        for other in headers[i + 1:]:
            if other["header_bbox"][1] > header["header_bbox"][3]:
                next_y = other["header_bbox"][1]
                break
        rows, y_extent = parse_rows(lines, columns, subheader, header["category"], stop_y=next_y)
        y1 = y_extent[1] if y_extent else subheader["y1"]
        bbox = [
            min(columns[0]["x0"], header["header_bbox"][0]),
            header["header_bbox"][1],
            max(columns[-1]["x1"], header["header_bbox"][2]),
            y1,
        ]
        tables.append(
            {
                "category": header["category"],
                "header_text": header["header_text"],
                "bbox": bbox,
                "columns": columns,
                "rows": rows,
            }
        )
    return tables


def learned_vocabulary(tables: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Union of MARK-column tokens per category across tables:
    {category: {mark: spec_row_cells}}. This defines the valid marks for the
    sheet set — no hardcoded H1-H4/SW/P/C lists."""
    vocab: dict[str, dict[str, Any]] = {}
    for table in tables:
        category = table["category"]
        pattern = CATEGORY_MARK_RE.get(category)
        if pattern is None:
            continue  # "unknown" tables stay visible but teach no marks
        for row in table.get("rows", []):
            mark = (row.get("mark") or "").strip()
            if not mark:
                continue
            # Family regex, or the generic token shape for uncommon mark names
            # (rows were anchored via the MARK/SYMBOL column in parse_rows).
            if not pattern.match(mark) and not (
                category != "wall_type" and GENERIC_MARK_RE.match(mark)
            ):
                continue
            vocab.setdefault(category, {}).setdefault(mark, row.get("cells", {}))
    return vocab


def discover_tables_on_page(page: Any) -> list[dict[str, Any]]:
    """Page-level wrapper: fitz.Page -> discovered tables."""
    return discover_tables(page.get_text("words"))


if __name__ == "__main__":
    # Self-check with a synthetic POST SCHEDULE built from raw word tuples.
    def w(x0, y, text, width=40.0, h=8.0):
        return (x0, y, x0 + width, y + h, text, 0, 0, 0)

    words = [
        w(1800, 100, "POST"), w(1845, 100, "SCHEDULE"), w(1895, 100, "SPECIFICATION"),
        w(1760, 120, "MARK"), w(1830, 120, "SIZE", 30), w(1865, 120, "&", 8),
        w(1878, 120, "SPACING", 45), w(1960, 120, "GRADE"),
        w(1760, 140, "P-1"), w(1830, 140, "(2)"), w(1855, 140, "600S162-43MIL"),
        w(1960, 140, "50", 15), w(1978, 140, "KSI", 20),
        w(1760, 160, "P-2"), w(1830, 160, "(4)"), w(1855, 160, "600S162-43MIL"),
        w(1960, 160, "50", 15), w(1978, 160, "KSI", 20),
        # wrapped continuation of P-2's size cell:
        w(1830, 172, "(BOXED)"), w(1875, 172, "POST"),
        w(1760, 190, "NOTE:"), w(1805, 190, "ignore"),
    ]
    tables = discover_tables(words)
    assert len(tables) == 1, tables
    t = tables[0]
    assert t["category"] == "post"
    assert [r["mark"] for r in t["rows"]] == ["P-1", "P-2"], t["rows"]
    p2 = t["rows"][1]["cells"]
    size_col = next(k for k in p2 if "SIZE" in k)
    assert "(BOXED) POST" in p2[size_col], p2
    vocab = learned_vocabulary(tables)
    assert set(vocab["post"]) == {"P-1", "P-2"}
    assert t["bbox"][3] >= 172
    print("schedule_tables self-check OK:", {k: list(v) for k, v in vocab.items()})
