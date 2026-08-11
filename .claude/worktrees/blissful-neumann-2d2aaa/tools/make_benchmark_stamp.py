"""Generate the Bluebeam benchmark stamp assets (BM-1.pdf, BM-2.pdf).

Each stamp is a small PDF: a crosshair (circle + two perpendicular lines
through its exact center) with the mark text beside it. Import into Bluebeam
via Tool Chest > Stamp (see docs/BENCHMARK-SOP.md). The crosshair center IS
the benchmark point — the backend reads the placed stamp annotation's rect
center, so the artwork is kept symmetric about the page center.

Run:  python tools/make_benchmark_stamp.py   (writes tools/stamps/)
"""
from __future__ import annotations

import sys
from pathlib import Path

PAGE = 72.0          # 1in x 1in stamp page
R = 12.0             # crosshair circle radius (pt) — inside the 6-30pt
                     # window benchmarks.py accepts for the vector fallback
LINE_HALF = 30.0     # crosshair line half-length (must exceed 1.3*r)
RED = (0.85, 0.1, 0.1)

OUT_DIR = Path(__file__).resolve().parent / "stamps"


def make_stamp(mark: str) -> Path:
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=PAGE, height=PAGE)
    c = PAGE / 2.0
    # circle and lines as SEPARATE drawings: the backend's vector fallback
    # measures the circle radius from its own drawing bbox, which must not
    # be inflated by the long crosshair lines.
    circle = page.new_shape()
    circle.draw_circle(fitz.Point(c, c), R)
    circle.finish(color=RED, width=1.2)
    circle.commit()
    lines = page.new_shape()
    lines.draw_line(fitz.Point(c - LINE_HALF, c), fitz.Point(c + LINE_HALF, c))
    lines.draw_line(fitz.Point(c, c - LINE_HALF), fitz.Point(c, c + LINE_HALF))
    lines.finish(color=RED, width=1.2)
    lines.commit()
    page.insert_text(fitz.Point(c + R + 4, c - R - 2), mark,
                     fontsize=9, color=RED)
    doc.set_metadata({"title": mark, "subject": mark})
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{mark}.pdf"
    doc.save(str(out))
    doc.close()
    return out


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from app.benchmarks import extract_pdf_benchmarks

    for mark in ("BM-1", "BM-2"):
        out = make_stamp(mark)
        # self-check: the crosshair artwork itself must be recognizable by
        # the vector fallback pass (circle + perpendicular lines + BM-x text)
        res = extract_pdf_benchmarks(out, marks=(mark,))
        got = {b["mark"]: b for b in res["benchmarks"]}
        assert mark in got, (mark, res)
        assert got[mark]["method"] == "vector_symbol", got[mark]
        assert abs(got[mark]["point_pt"]["x"] - PAGE / 2) < 0.5
        assert abs(got[mark]["point_pt"]["y"] - PAGE / 2) < 0.5
        print(f"wrote {out}  (self-check OK: vector crosshair at center)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
