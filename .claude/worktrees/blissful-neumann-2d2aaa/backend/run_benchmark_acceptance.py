"""Real-acceptance run for 2-benchmark registration on Madera.

Revit side already done live via Nonica MCP (verified by readback):
  element 3951194  Mark BM-1  at grid A x 1
  element 3951193  Mark BM-2  at grid C x 3
This script does the PDF side + injects the benchmarks into the raw
export artifact + runs extract & calibrate through the running API.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import fitz
import sys
import urllib.request

# BUG-17: SUPERSEDED. The current path is the gated API — propose → approve →
# POST /api/benchmark-workflow/stamp (writes at the human-approved proposal
# points and verifies) — driven by .claude/skills/benchmark-autopilot/SKILL.md.
# This historical script hardcodes coordinates + a personal PDF path and
# bypasses the approval gates. Kept only as a reference; refuses to run
# without --force so no one follows it by accident.
if __name__ == "__main__" and "--force" not in sys.argv:
    sys.exit(
        "run_benchmark_acceptance.py is superseded — use the /api/benchmark-"
        "workflow endpoints (see SKILL.md). Re-run with --force only if you "
        "specifically need the historical flow."
    )

ROOT = Path(__file__).resolve().parent.parent
PROJ = ROOT / "artifacts" / "projects" / "madera"
PDF = Path(r"C:\Users\aashd\Downloads\wetransfer_madera-model-and-permit-sets_2026-05-13_1004"
           r"\STAMPED_10510 Madera Dr-DWG-20260122-D1.pdf")
API = "http://127.0.0.1:8077"

# Exact grid intersections (from raw_revit_export.json grid lines; the
# placed markers were copied by these exact vectors, verified by readback).
A1 = (17.30397680562973, 62.17388041741090)
C3 = (75.97064298626886, 4.71554708407756)

MATRIX = json.loads((PROJ / "registration_calibration.json").read_text(
    encoding="utf-8"))["transform"]["matrix"]


def to_pdf(x: float, y: float) -> tuple[float, float]:
    a, b, c, d, tx, ty = MATRIX
    return a * x + b * y + tx, c * x + d * y + ty


def api(path: str, payload: dict | None = None) -> dict:
    req = urllib.request.Request(
        API + path,
        data=json.dumps(payload or {}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "detail": e.read().decode()[:500]}


def main() -> None:
    # ---- 1. find the S-201 page --------------------------------------
    ei = json.loads((PROJ / "pdf_page_intelligence.json").read_text(encoding="utf-8"))
    assert (ei.get("sheet_number") or "").strip().upper() == "S-201", ei.get("sheet_number")
    s201_page = ei["page_index"]
    print(f"S-201 page index: {s201_page}")

    # ---- 2. stamp the real PDF (backup first) ------------------------
    bak = PDF.with_suffix(".pre_benchmarks.bak.pdf")
    if not bak.exists():
        shutil.copy2(PDF, bak)
        print(f"backup: {bak.name}")

    doc = fitz.open(str(PDF))
    page = doc[s201_page]
    existing = [a.info.get("subject", "") for a in page.annots() or []]
    assert "BM-1" not in existing and "BM-2" not in existing, \
        f"page already has BM stamps: {existing}"
    for mark, (mx, my) in (("BM-1", A1), ("BM-2", C3)):
        px, py = to_pdf(mx, my)
        r = 12.0
        annot = page.add_circle_annot(fitz.Rect(px - r, py - r, px + r, py + r))
        annot.set_info(subject=mark, title="Livio QA-QC benchmark",
                       content=f"{mark} registration benchmark")
        annot.set_colors(stroke=(0.9, 0.2, 0.1))
        annot.set_border(width=1.2)
        annot.update()
        print(f"stamped {mark} at ({px:.3f}, {py:.3f}) pt")
    doc.saveIncr()
    doc.close()

    # ---- 3. inject benchmarks into raw_revit_export.json -------------
    raw_path = PROJ / "raw_revit_export.json"
    raw_bak = PROJ / "raw_revit_export.pre_benchmarks.bak.json"
    if not raw_bak.exists():
        shutil.copy2(raw_path, raw_bak)
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    raw["benchmarks"] = [
        {"id": "3951194", "mark": "BM-1", "family": "mwfBenchmark",
         "level": "Level 1",
         "point_ft": {"x": A1[0], "y": A1[1], "z": 1.50},
         "source": "nonica_live_mcp_2026-07-16"},
        {"id": "3951193", "mark": "BM-2", "family": "mwfBenchmark",
         "level": "Level 1",
         "point_ft": {"x": C3[0], "y": C3[1], "z": 1.50},
         "source": "nonica_live_mcp_2026-07-16"},
    ]
    raw_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    print("benchmarks injected into raw_revit_export.json")

    # ---- 4. run the pipeline steps through the API --------------------
    print("\nactivate:", json.dumps(api("/api/projects/activate",
                                        {"project": "madera"}))[:120])
    ext = api("/api/pdf/benchmarks")
    print("extract:", json.dumps(ext, indent=1)[:800])
    cal = api("/api/registration/benchmarks")
    print("calibrate:", json.dumps(cal, indent=1)[:2000])


if __name__ == "__main__":
    main()
