"""Benchmark Autopilot workflow (AUTOPILOT_PLAN.md P3). The state machine only
records progress + approvals; the transform itself is ONLY ever minted by the
gated POST /api/registration/benchmarks."""

from __future__ import annotations

import json
from typing import Any

from fastapi import Body, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from .. import benchmark_workflow, config, control_points, phase_summary, progress
from .. import registration, review
from .common import load_artifact, make_router, project_pdf_path, save_artifact

router = make_router()


def _bmwf_page() -> tuple[str | None, int]:
    """Plan sheet for benchmark proposal: page-intelligence result wins,
    else the element-intelligence sheet with the most marks."""
    ppi_path = config.artifact_path("pdf_page_intelligence")
    if ppi_path.exists():
        ppi = json.loads(ppi_path.read_text(encoding="utf-8"))
        if ppi.get("page_index") is not None:
            return ppi.get("sheet_number"), int(ppi["page_index"])
    ei_path = config.artifact_path("element_intelligence")
    if ei_path.exists():
        sheets = json.loads(ei_path.read_text(encoding="utf-8")).get("sheets", [])
        best = max(sheets, key=lambda s: len(s.get("marks", [])), default=None)
        if best and best.get("page_index") is not None:
            return best.get("sheet_number"), int(best["page_index"])
    raise HTTPException(
        status_code=409,
        detail="No plan sheet known — run page-intelligence or element "
        "extraction first.",
    )


def _resolve_sheet_page(sheet_number: str) -> int:
    """page_index for a sheet number, from element_intelligence (BUG-14:
    sheet_number alone is enough — the page is already known there)."""
    ei_path = config.artifact_path("element_intelligence")
    if ei_path.exists():
        for s in json.loads(ei_path.read_text(encoding="utf-8")).get("sheets", []):
            if s.get("sheet_number") == sheet_number and s.get("page_index") is not None:
                return int(s["page_index"])
    raise HTTPException(
        status_code=422,
        detail=f"Sheet '{sheet_number}' not found in element intelligence; "
        "pass page_index explicitly or run extraction first.",
    )


def _maybe_auto_advance_export(raw_revit: dict[str, Any]) -> None:
    """If the workflow is waiting on a fresh export and this upload's Revit
    JSON already carries both proposal marks, auto-advance. No-op otherwise —
    never touches workflow state outside awaiting_export."""
    wf = benchmark_workflow.load()
    if wf.get("state") != "awaiting_export":
        return
    proposal = wf.get("proposal") or {}
    want = {bm["mark"] for bm in proposal.get("benchmarks", [])}
    have = {bm.get("mark") for bm in raw_revit.get("benchmarks") or []}
    if not want or not want <= have:
        return
    benchmark_workflow.transition(
        wf, "calibrating", "system",
        note="Auto-detected fresh export with both benchmarks present.",
        payload={"marks": sorted(want)},
    )
    benchmark_workflow.save(wf)
    progress.emit("benchmark_workflow", "info", "Auto-advanced awaiting_export -> calibrating")


@router.get("/api/benchmark-workflow")
def benchmark_workflow_get() -> JSONResponse:
    return JSONResponse(benchmark_workflow.load())


def _propose(body: dict[str, Any]) -> dict[str, Any]:
    """The proposal run itself: grid extraction -> max-diagonal pair (or the
    caller's manual pick) -> evidence crops -> awaiting_pdf_approval. Shared by
    the endpoint and the zero-click auto-benchmark on upload, so there is
    exactly one picker in the codebase. Raises HTTPException on any failure."""
    import fitz

    actor = str(body.get("actor", "agent"))
    wf = benchmark_workflow.load()
    try:
        benchmark_workflow.transition(
            wf, "proposing", actor, note="Proposing benchmark pair from grid geometry."
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    progress.emit("benchmark_workflow", "start", "Proposing benchmark pair")

    def _fail(reason: str) -> HTTPException:
        benchmark_workflow.transition(wf, "failed", "backend", note=reason)
        benchmark_workflow.save(wf)
        progress.emit("benchmark_workflow", "error", reason)
        return HTTPException(status_code=409, detail=reason)

    raw_revit = load_artifact("raw_revit")
    rev_cp = control_points.extract_revit_control_points(raw_revit)
    if not rev_cp.get("points"):
        raise _fail("Revit export has no usable grid intersections.")
    sheet_number, page_index = _bmwf_page()
    # BUG-14: sheet_number alone is enough — resolve its page from extraction.
    if body.get("sheet_number"):
        sheet_number = str(body["sheet_number"])
        page_index = (int(body["page_index"]) if body.get("page_index") is not None
                      else _resolve_sheet_page(sheet_number))
    elif body.get("page_index") is not None:
        page_index = int(body["page_index"])
    pdf_path = project_pdf_path()
    with fitz.open(str(pdf_path)) as doc:
        words = doc[page_index].get_text("words")
    # BUG-01: axis-agnostic resolver — no letter=vertical assumption, works on
    # inverted-axis sheets (Dogwood) and mid-page grid bubbles.
    pdf_points = benchmark_workflow.resolve_pdf_grid_points(words, rev_cp["points"])
    # §3 "Pick manually": a user-picked [{grid_id, mark}] selection replaces the
    # auto max-diagonal pair. Bad input is a client error (422) that leaves the
    # workflow untouched — the proposing edge is only in memory, never saved.
    manual = body.get("points")
    if manual is not None:
        try:
            proposal = benchmark_workflow.propose_from_points(
                pdf_points, rev_cp["points"], manual, sheet_number, page_index
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    else:
        try:
            proposal = benchmark_workflow.propose_from_geometry(
                pdf_points, rev_cp["points"], sheet_number, page_index
            )
        except ValueError as exc:
            raise _fail(str(exc))

    # Evidence crops for the approval card (review.py's crop renderer).
    config.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    for bm in proposal["benchmarks"]:
        png = review.render_evidence_crop(
            pdf_path, page_index, pdf_point=bm["pdf_point_pt"], revit_point=None
        )
        (config.EVIDENCE_DIR / f"benchmark_{bm['mark']}.png").write_bytes(png)
        bm["evidence_url"] = f"/api/benchmark-workflow/evidence/{bm['mark']}.png"

    wf["proposal"] = proposal
    benchmark_workflow.transition(
        wf, "awaiting_pdf_approval", actor,
        note=(
            f"Proposed {proposal['benchmarks'][0]['grid_label']} + "
            f"{proposal['benchmarks'][1]['grid_label']} on {sheet_number} "
            f"({proposal['separation_revit_ft']} ft apart)."
        ),
        payload={
            "separation_pdf_pt": proposal["separation_pdf_pt"],
            "separation_revit_ft": proposal["separation_revit_ft"],
            "candidates_considered": proposal["candidates_considered"],
        },
    )
    benchmark_workflow.save(wf)
    progress.emit(
        "benchmark_workflow", "done",
        f"Proposal ready on {sheet_number} — awaiting PDF approval",
    )
    return wf


@router.post("/api/benchmark-workflow/propose")
def benchmark_workflow_propose(
    payload: dict[str, Any] | None = Body(default=None),
) -> JSONResponse:
    """Find labeled grid intersections on the plan sheet, pick the two with
    max diagonal separation, render evidence crops, await human approval.
    Works on brand-new unregistered projects — no transform dependency."""
    return JSONResponse(_propose(payload if isinstance(payload, dict) else {}))


def maybe_auto_benchmark() -> dict[str, Any] | None:
    """Zero-click benchmark proposal after an upload (production-plan: the user
    should never have to know the wizard exists to get a registration).

    Runs the SAME picker as the wizard on THIS PDF's own grid bubbles, stamps
    BM-1/BM-2 at the chosen points, and stops at the normal
    ``awaiting_pdf_approval`` gate — a human still approves before anything
    downstream trusts it. Only ever fires from a clean ``idle`` workflow, so a
    run already in flight (or already approved) is never disturbed.

    Anything missing — no Revit export, no indexed plan sheet, fewer than 2
    shared labeled intersections — is logged and skipped; the manual pick and
    RANSAC paths are untouched. Never raises: an upload must not fail because
    a convenience step could not run.
    """
    before = benchmark_workflow.load()
    if before.get("state") != "idle":
        return None
    try:
        wf = _propose({"actor": "auto"})
    except HTTPException as exc:
        # _propose may have recorded a 'failed' edge; this attempt was
        # automatic and unasked-for, so restore the workflow exactly as found.
        benchmark_workflow.save(before)
        progress.emit(
            "benchmark", "info",
            f"🤖 Auto-benchmark skipped: {exc.detail} "
            "Manual picking and RANSAC calibration are unaffected.",
        )
        return None
    except Exception as exc:  # noqa: BLE001 - upload must never fail for this
        benchmark_workflow.save(before)
        progress.emit("benchmark", "info", f"🤖 Auto-benchmark skipped: {exc}")
        return None
    stamped = False
    try:
        stamped = bool(_stamp_pdf_with_proposal(wf["proposal"])["ok"])
    except Exception as exc:  # noqa: BLE001 - proposal still stands unstamped
        progress.emit("benchmark", "info", f"🤖 Auto-benchmark stamp skipped: {exc}")
    phase_summary.record("auto_benchmark",
                         phase_summary.auto_benchmark(wf["proposal"], stamped))
    return wf


@router.get("/api/benchmark-workflow/grid-points")
def benchmark_workflow_grid_points() -> JSONResponse:
    """Detected grid intersections on the plan sheet, joinable to Revit — the
    exact set the wizard's "Pick manually" mode (§3) snaps clicks to. Returns
    PDF-point coordinates + page size so the overlay shares the sheet's space."""
    import fitz

    raw_revit = load_artifact("raw_revit")
    rev_cp = control_points.extract_revit_control_points(raw_revit)
    if not rev_cp.get("points"):
        raise HTTPException(
            status_code=409, detail="Revit export has no usable grid intersections."
        )
    sheet_number, page_index = _bmwf_page()
    pdf_path = project_pdf_path()
    with fitz.open(str(pdf_path)) as doc:
        page = doc[page_index]
        words = page.get_text("words")
        rect = page.rect
    points = benchmark_workflow.resolve_pdf_grid_points(words, rev_cp["points"])
    return JSONResponse({
        "sheet_number": sheet_number,
        "page_index": page_index,
        "page_size": [round(rect.width, 2), round(rect.height, 2)],
        "points": points,
    })


@router.post("/api/benchmark-workflow/approve")
def benchmark_workflow_approve(
    payload: dict[str, Any] | None = Body(default=None),
) -> JSONResponse:
    """Human decision at an approval gate. Audit-logged; reject -> failed."""
    body = payload if isinstance(payload, dict) else {}
    if "approved" not in body:
        raise HTTPException(status_code=422, detail="'approved' (bool) is required.")
    approved = bool(body["approved"])
    actor = str(body.get("actor", "human"))
    comment = str(body.get("comment", ""))
    wf = benchmark_workflow.load()
    gate = wf.get("state")
    if gate not in benchmark_workflow.APPROVAL_GATES:
        raise HTTPException(
            status_code=409,
            detail=f"State '{gate}' is not an approval gate.",
        )
    to_state = benchmark_workflow.APPROVAL_GATES[gate] if approved else "failed"
    benchmark_workflow.transition(
        wf, to_state, actor,
        note=comment or ("Approved." if approved else "Rejected."),
        payload={"approved": approved, "gate": gate},
    )
    benchmark_workflow.save(wf)
    progress.emit(
        "benchmark_workflow", "info",
        f"{gate}: {'approved' if approved else 'REJECTED'} by {actor}",
    )
    return JSONResponse(wf)


@router.post("/api/benchmark-workflow/advance")
def benchmark_workflow_advance(
    payload: dict[str, Any] | None = Body(default=None),
) -> JSONResponse:
    """Agent reports a step done (stamped coords, marker ids, export, …)."""
    body = payload if isinstance(payload, dict) else {}
    step = str(body.get("step", ""))
    data = body.get("data") or {}
    actor = str(body.get("actor", "agent"))
    wf = benchmark_workflow.load()
    if step == "failed":
        try:
            benchmark_workflow.transition(
                wf, "failed", actor, note=str(body.get("note", "Agent reported failure.")),
                payload=data,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        benchmark_workflow.save(wf)
        progress.emit("benchmark_workflow", "error", "Agent reported failure")
        return JSONResponse(wf)
    if step not in benchmark_workflow.ADVANCE_STEPS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown step '{step}'. "
            f"Valid: {sorted(benchmark_workflow.ADVANCE_STEPS)} or 'failed'.",
        )
    required, to_state = benchmark_workflow.ADVANCE_STEPS[step]
    if wf.get("state") != required:
        raise HTTPException(
            status_code=409,
            detail=f"Step '{step}' requires state '{required}', "
            f"current is '{wf.get('state')}'.",
        )
    if step == "stamped":
        # Guard rail: never trust the caller's word that stamping happened —
        # a Playwright test proved this state machine had no way to tell a
        # truthful report from a fabricated one. Re-read the PDF and check
        # against the human-approved proposal, same pattern as 'calibrated'.
        proposal = wf.get("proposal")
        if not proposal or not proposal.get("benchmarks"):
            raise HTTPException(
                status_code=409, detail="No approved proposal to verify against."
            )
        extracted = benchmark_workflow.extract_pdf_benchmarks(
            project_pdf_path(), page_index=proposal["page_index"]
        )
        verification = benchmark_workflow.verify_stamped_benchmarks(proposal, extracted)
        if not verification["ok"]:
            raise HTTPException(status_code=409, detail={
                "message": "Reported stamp does not verify against the proposal.",
                "verification": verification,
            })
        data = {**data, "verification": verification}
    if step == "calibrated":
        # Guard rail: 'done' only when a benchmark-verified calibration truly
        # exists on disk — saved by the gated /api/registration/benchmarks,
        # never by this state machine.
        cal = registration.load_calibration()
        if not registration.registration_usable(cal) or (
            cal.get("calibration_source") != "benchmark_verified"
        ):
            raise HTTPException(
                status_code=409,
                detail="No benchmark-verified calibration on disk — run "
                "POST /api/registration/benchmarks (it saves only when the "
                "quality gates pass).",
            )
        data = {**data, "calibration_source": cal.get("calibration_source"),
                "scale": cal.get("transform", {}).get("scale")}
    if step in ("revit_connected", "markers_placed", "export_received"):
        # BUG-07: these Revit-side steps are self-reported (the backend can't
        # yet verify them itself — that's the MCP bridge in the production
        # plan). Stamp the audit trail so the UI renders them amber, never as
        # verified-green, and a fabricated report is visibly unverified.
        data = {**data, "verified": False}
    benchmark_workflow.transition(
        wf, to_state, actor, note=str(body.get("note", f"Step '{step}' complete.")),
        payload=data,
    )
    benchmark_workflow.save(wf)
    progress.emit("benchmark_workflow", "info", f"{step} -> {to_state}")
    return JSONResponse(wf)


@router.post("/api/benchmark-workflow/reset")
def benchmark_workflow_reset(
    payload: dict[str, Any] | None = Body(default=None),
) -> JSONResponse:
    """BUG-08: audited reset/abort back to idle from any state, so recovering
    a stuck workflow no longer means hand-deleting benchmark_workflow.json."""
    from datetime import datetime, timezone

    body = payload if isinstance(payload, dict) else {}
    actor = str(body.get("actor", "human"))
    prior = benchmark_workflow.load()
    # An audited reset must not destroy the prior audit trail — archive it.
    if prior.get("history"):
        archive = config.artifact_path("benchmark_workflow").with_suffix(".prev.json")
        archive.write_text(json.dumps(prior, indent=2), encoding="utf-8")
    wf = benchmark_workflow.default_state()
    wf["updated_at"] = datetime.now(timezone.utc).isoformat()
    wf["history"].append({
        "ts": wf["updated_at"], "actor": actor,
        "from": prior.get("state", "idle"), "to": "idle",
        "note": str(body.get("note", "Workflow reset.")), "payload": {},
    })
    benchmark_workflow.save(wf)
    progress.emit("benchmark_workflow", "info",
                  f"Workflow reset ({prior.get('state')} -> idle) by {actor}")
    return JSONResponse(wf)


@router.get("/api/benchmark-workflow/evidence/{mark}.png")
def benchmark_workflow_evidence(mark: str):
    safe = "".join(c for c in mark.upper() if c.isalnum() or c == "-")
    path = config.EVIDENCE_DIR / f"benchmark_{safe}.png"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"No evidence crop for {safe}.")
    return FileResponse(path, media_type="image/png")


def _stamp_pdf_with_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
    """Backs up the PDF, writes BM-1/BM-2 circle annots at the proposal's
    ALREADY-APPROVED pdf_point_pt (never caller-supplied coords), verifies by
    reading them back. Returns the verification dict; never transitions state."""
    import shutil

    import fitz

    pdf_path = project_pdf_path()
    page_index = proposal["page_index"]
    bak = pdf_path.with_suffix(".pre_benchmarks.bak" + pdf_path.suffix)
    if not bak.exists():
        shutil.copy2(pdf_path, bak)
    # Rollback must restore THIS call's entry state — the .bak file can be
    # stale (created on an earlier run), and restoring it would wipe every
    # legitimate change made since. Snapshot the exact entry bytes instead.
    entry_bytes = pdf_path.read_bytes()

    with fitz.open(str(pdf_path)) as doc:
        page = doc[page_index]
        existing = {a.info.get("subject", "") for a in (page.annots() or [])}
        for bm in proposal["benchmarks"]:
            if bm["mark"] in existing:
                continue  # idempotent retry after a prior partial failure
            p, r = bm["pdf_point_pt"], 12.0
            annot = page.add_circle_annot(
                fitz.Rect(p["x"] - r, p["y"] - r, p["x"] + r, p["y"] + r)
            )
            annot.set_info(
                subject=bm["mark"], title="Livio QA-QC benchmark",
                content=f"{bm['mark']} registration benchmark",
            )
            annot.set_colors(stroke=(0.9, 0.2, 0.1))
            annot.set_border(width=1.2)
            annot.update()
        doc.saveIncr()

    extracted = benchmark_workflow.extract_pdf_benchmarks(pdf_path, page_index=page_index)
    verification = benchmark_workflow.verify_stamped_benchmarks(proposal, extracted)
    if not verification["ok"]:
        # BUG-06: a failed verification leaves the PDF exactly as it was at
        # the start of THIS call, so the PDF and the (unchanged) workflow
        # state never disagree — and a stale .bak can't rewind later edits.
        pdf_path.write_bytes(entry_bytes)
    return verification


@router.post("/api/benchmark-workflow/stamp")
def benchmark_workflow_stamp(
    payload: dict[str, Any] | None = Body(default=None),
) -> JSONResponse:
    """Stamp BM-1/BM-2 at the human-approved proposal points and verify the
    stamp landed before advancing. Coordinates NEVER come from the request
    body — only from wf['proposal'], to prevent stamp/approval drift."""
    body = payload if isinstance(payload, dict) else {}
    actor = str(body.get("actor", "agent"))
    wf = benchmark_workflow.load()
    if wf.get("state") != "stamping":
        raise HTTPException(
            status_code=409,
            detail=f"Stamp requires state 'stamping', current is '{wf.get('state')}'.",
        )
    proposal = wf.get("proposal")
    if not proposal or not proposal.get("benchmarks"):
        raise HTTPException(status_code=409, detail="No approved proposal to stamp.")

    verification = _stamp_pdf_with_proposal(proposal)
    if not verification["ok"]:
        progress.emit(
            "benchmark_workflow", "error",
            f"Stamp verification failed: {verification['reason']}",
        )
        raise HTTPException(status_code=409, detail={
            "message": "Stamp written but verification failed — state unchanged.",
            "verification": verification,
        })
    benchmark_workflow.transition(
        wf, "awaiting_revit", actor, note="Stamped and verified BM-1/BM-2.",
        payload={"verification": verification},
    )
    benchmark_workflow.save(wf)
    progress.emit("benchmark_workflow", "done", "PDF stamped and verified")
    return JSONResponse({**wf, "verification": verification})
