"""Human-review workspace: the collaboration loop between the QA reviewer
and the AI.

- Review queue: every LOCATION_MISMATCH / NEEDS_REVIEW element.
- Comments: the reviewer explains what they see; the comment is ALSO fed to
  teach.teach(), so a comment that encodes a convention ("HD3 means H3")
  becomes a persistent global memory rule applied to future projects.
- Dispositions: confirmed-issue / false-alarm / fixed-in-model. Stored
  alongside the element — the honest pipeline status is NEVER mutated; the
  punch list shows both.
- Side-by-side evidence: a PDF crop centred on the detected point with the
  Revit position ghost-marked, so the reviewer sees both claimed locations
  and the gap between them.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from . import config, teach

SCHEMA_VERSION = "review-comments/1.0"
REVIEW_STATUSES = ("LOCATION_MISMATCH", "NEEDS_REVIEW")
DISPOSITIONS = ("confirmed-issue", "false-alarm", "fixed-in-model")

CROP_HALF_PT = 90.0  # crop half-size around the PDF point


def _path():
    return config.artifact_path("review_comments")


def load() -> dict[str, Any]:
    p = _path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"schema_version": SCHEMA_VERSION, "comments": [], "dispositions": {}}


def _save(data: dict[str, Any]) -> None:
    _path().write_text(json.dumps(data, indent=2), encoding="utf-8")


def add_comment(element: dict[str, Any], comment: str, author: str | None) -> dict[str, Any]:
    """Store the comment AND run it through the teach engine so conventions
    become memory rules. Returns {comment_entry, teach_result}."""
    teach_result = teach.teach(comment, context={"element": {
        "id": element.get("id"), "category": element.get("category"),
        "mark": element.get("mark"), "status": element.get("status"),
        "sheet": element.get("sheet"),
    }})
    rule_entry = teach_result.get("entry")
    # Pure notes are remembered but honestly don't change extraction; real
    # rules (alias/pattern/header) will apply on the next Extract run.
    derived_rule_id = rule_entry["id"] if rule_entry else None
    data = load()
    entry = {
        "id": f"rc_{len(data['comments']) + 1:03d}",
        "element_id": element.get("id"),
        "comment": comment,
        "author": author or "reviewer",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ai_reply": teach_result.get("reply"),
        "derived_rule_id": derived_rule_id,
        "derived_rule_kind": (rule_entry or {}).get("rule", {}).get("kind"),
    }
    data["comments"].append(entry)
    _save(data)
    return {"comment": entry, "teach": teach_result}


def set_disposition(element_id: str, disposition: str) -> dict[str, Any]:
    if disposition not in DISPOSITIONS:
        raise ValueError(f"disposition must be one of {DISPOSITIONS}")
    data = load()
    data["dispositions"][element_id] = {
        "disposition": disposition,
        "set_at": datetime.now(timezone.utc).isoformat(),
    }
    _save(data)
    return data["dispositions"][element_id]


def build_queue(element_list: dict[str, Any]) -> dict[str, Any]:
    """All elements needing human review, joined with comments/dispositions."""
    data = load()
    by_element: dict[str, list[dict[str, Any]]] = {}
    for c in data["comments"]:
        by_element.setdefault(c["element_id"], []).append(c)
    items = []
    for e in element_list.get("elements", []):
        if e.get("status") not in REVIEW_STATUSES:
            continue
        disp = data["dispositions"].get(e["id"], {}).get("disposition")
        items.append({
            "element": e,
            "comments": by_element.get(e["id"], []),
            "disposition": disp,
            "reviewed": bool(disp),
        })
    reviewed = sum(1 for i in items if i["reviewed"])
    return {
        "total": len(items),
        "reviewed": reviewed,
        "items": items,
    }


def render_evidence_crop(
    pdf_path: Any,
    page_index: int,
    pdf_point: dict[str, float] | None,
    revit_point: dict[str, float] | None,
    dpi: int = 220,
) -> bytes:
    """PNG crop centred on the PDF point: solid ring = PDF detection, dashed
    ring = Revit position re-projected, line between them = the gap."""
    import fitz

    doc = fitz.open(str(pdf_path))
    try:
        page = doc[page_index]
        anchor = pdf_point or revit_point
        if anchor is None:
            raise ValueError("Element has no drawable point.")
        cx, cy = float(anchor["x"]), float(anchor["y"])
        clip = fitz.Rect(cx - CROP_HALF_PT, cy - CROP_HALF_PT,
                         cx + CROP_HALF_PT, cy + CROP_HALF_PT) & page.rect

        shape = page.new_shape()
        if pdf_point:
            shape.draw_circle(fitz.Point(pdf_point["x"], pdf_point["y"]), 7)
            shape.finish(color=(0.13, 0.77, 0.37), width=1.6)  # green: PDF
        if revit_point:
            shape.draw_circle(fitz.Point(revit_point["x"], revit_point["y"]), 7)
            shape.finish(color=(0.96, 0.42, 0.42), width=1.6, dashes="[3] 0")  # red: Revit
        if pdf_point and revit_point:
            shape.draw_line(fitz.Point(pdf_point["x"], pdf_point["y"]),
                            fitz.Point(revit_point["x"], revit_point["y"]))
            shape.finish(color=(0.98, 0.75, 0.14), width=1.2, dashes="[2] 0")
        shape.commit()

        pix = page.get_pixmap(clip=clip, dpi=dpi)
        return pix.tobytes("png")
    finally:
        doc.close()


# --------------------------------------------------------------------------
# Human Review v2 (docs/HUMAN_REVIEW_V2_PLAN.md): AI-first analysis of a
# LOCATION_MISMATCH device, evaluation of the reviewer's logic, and a
# human-accepted resolution that propagates to every artifact.

import math


def _device_for(element_id: str, element_list: dict[str, Any],
                registry: dict[str, Any]):
    row = next((e for e in element_list.get("elements", [])
                if e.get("id") == element_id), None)
    if not row or not row.get("device_id"):
        return row, None, None
    for cat, c in (registry or {}).get("categories", {}).items():
        for d in c.get("devices", []):
            if d["id"] == row["device_id"]:
                return row, d, cat
    return row, None, None


def _resolution_key(cat: str, device: dict[str, Any]) -> str:
    # device ids regenerate every match run; the pairing is the stable key
    return f"{cat}:{device.get('mark')}:{device.get('target_id')}"


def analyze(element_id: str, element_list: dict[str, Any],
            registry: dict[str, Any]) -> dict[str, Any]:
    """Deterministic mismatch analysis. Facts only — no LLM."""
    row, device, cat = _device_for(element_id, element_list, registry)
    if row is None:
        raise ValueError(f"Unknown element {element_id}")
    if device is None or not device.get("target_point"):
        return {"element_id": element_id, "analysis_available": False,
                "note": "No paired device with model-space geometry — "
                        "analysis applies to LOCATION_MISMATCH devices."}
    tx, ty = device["target_point"]
    vx, vy = device["x"] - tx, device["y"] - ty
    dist = device.get("distance_ft") or math.hypot(vx, vy)
    bearing = math.degrees(math.atan2(vx, vy)) % 360
    compass = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int((bearing + 22.5) // 45) % 8]

    # systematic-shift test across the category's mismatched devices
    peers = [d for d in registry["categories"][cat]["devices"]
             if d.get("status") == "LOCATION_MISMATCH"
             and d.get("target_point") and d["id"] != device["id"]]
    aligned = 0
    for p in peers:
        pvx, pvy = p["x"] - p["target_point"][0], p["y"] - p["target_point"][1]
        dot = vx * pvx + vy * pvy
        na, nb = math.hypot(vx, vy), math.hypot(pvx, pvy)
        if na and nb and dot / (na * nb) >= 0.8 and 0.5 <= nb / na <= 2.0:
            aligned += 1
    systematic = peers and aligned >= max(2, len(peers) // 2)

    finding = (
        f"The drawing callout sits {dist:.2f} ft {compass} of the model "
        f"device ({device.get('target_id')})."
    )
    if systematic:
        finding += (
            f" {aligned} of {len(peers)} other mismatched {cat} devices are "
            "shifted in the SAME direction and similar magnitude — this is "
            "the signature of a systematic drafting/registration offset on "
            "the sheet, NOT an individual modeling error. Accepting as a "
            "match is defensible.")
        suggestion = "lean-accept"
    elif dist <= 3.0:
        finding += (
            " The offset is small and isolated — commonly a callout leader "
            "anchored off the device, or the model placed on the other face "
            "of the wall. Verify against the crop before accepting.")
        suggestion = "verify-then-accept"
    else:
        finding += (
            " The offset is large and no other device moves this way — "
            "treat as a genuine modeling deviation unless the reviewer "
            "knows otherwise.")
        suggestion = "lean-reject"
    return {
        "element_id": element_id, "analysis_available": True,
        "device_id": device["id"], "category": cat,
        "distance_ft": round(dist, 2), "direction": compass,
        "offset_vector_ft": [round(vx, 2), round(vy, 2)],
        "systematic": bool(systematic),
        "aligned_peers": aligned, "peer_count": len(peers),
        "sheets": sorted(set(device.get("sheets", []))),
        "finding": finding, "suggestion": suggestion,
    }


def evaluate(element_id: str, comment: str, analysis: dict[str, Any]) -> dict[str, Any]:
    """Judge the reviewer's logic against the deterministic facts. LLM words
    the verdict; the facts come only from `analysis`."""
    from . import openrouter
    verdict = {"agrees": None, "reasoning": None,
               "deterministic_suggestion": analysis.get("suggestion")}
    if analysis.get("analysis_available"):
        result = openrouter.call_llm(
            system_prompt=(
                "You are a QA-QC assistant. You are given DETERMINISTIC "
                "measurements about a PDF-vs-Revit location mismatch and an "
                "experienced human reviewer's explanation. Judge ONLY "
                "whether the explanation is consistent with the "
                "measurements. Reply as JSON: "
                '{"agrees": true|false, "reasoning": "<2 sentences '
                "grounded in the numbers>\"}"),
            user_prompt=json.dumps({"measurements": analysis,
                                    "reviewer_comment": comment}),
            purpose="review.evaluate_comment",
        )
        if result.get("ok"):
            try:
                parsed = json.loads(result["content"])
                verdict["agrees"] = bool(parsed.get("agrees"))
                verdict["reasoning"] = parsed.get("reasoning")
            except (json.JSONDecodeError, TypeError):
                pass
    if verdict["reasoning"] is None:
        verdict["reasoning"] = (
            "LLM unavailable — deterministic facts: " + analysis.get(
                "finding", "no geometric analysis for this element."))
        verdict["agrees"] = analysis.get("suggestion") in (
            "lean-accept", "verify-then-accept")
    return verdict


def resolve(element_id: str, action: str, comment: str,
            element_list: dict[str, Any], registry: dict[str, Any],
            author: str | None = None) -> dict[str, Any]:
    """Apply the human decision. accept => every appearance of the device
    becomes MATCH with a permanent resolution block; reject => status stays,
    decision recorded. Returns {resolution, updated_element_ids}."""
    if action not in ("accept", "reject"):
        raise ValueError("action must be accept or reject")
    row, device, cat = _device_for(element_id, element_list, registry)
    if row is None:
        raise ValueError(f"Unknown element {element_id}")
    resolution = {
        "action": action,
        "via": "human_review",
        "original_status": row.get("status"),
        "distance_ft": row.get("distance_ft"),
        "comment": comment,
        "author": author or "reviewer",
        "resolved_at": datetime.now(timezone.utc).isoformat(),
    }
    updated: list[str] = []
    if device is not None:
        key = _resolution_key(cat, device)
        data = load()
        data.setdefault("resolutions", {})[key] = resolution
        _save(data)
        if action == "accept":
            device["status"] = "MATCH"
            device["resolution"] = resolution
            for rid in device.get("appearances", []):
                for e in element_list.get("elements", []):
                    if e["id"] == rid:
                        e["status"] = "MATCH"
                        e["resolution"] = resolution
                        e["reason"] = (
                            f"Accepted by human review: {comment} "
                            f"(was {resolution['original_status']}, "
                            f"{resolution['distance_ft']} ft offset).")
                        updated.append(rid)
        else:
            device["resolution"] = resolution
            for rid in device.get("appearances", []):
                for e in element_list.get("elements", []):
                    if e["id"] == rid:
                        e["resolution"] = resolution
                        updated.append(rid)
    # audit comment + teach memory (conventions become global rules)
    add_comment(row, comment, author)
    return {"resolution": resolution, "updated_element_ids": updated}


def apply_stored_resolutions(element_list: dict[str, Any],
                             registry: dict[str, Any]) -> int:
    """After a fresh match run, re-apply prior human accepts whose device
    pairing (category:mark:target) still exists and still mismatches."""
    data = load()
    stored = data.get("resolutions", {})
    if not stored:
        return 0
    applied = 0
    rows = {e["id"]: e for e in element_list.get("elements", [])}
    for cat, c in (registry or {}).get("categories", {}).items():
        for d in c.get("devices", []):
            res = stored.get(_resolution_key(cat, d))
            if not res or res.get("action") != "accept":
                continue
            if d.get("status") != "LOCATION_MISMATCH":
                continue
            d["status"] = "MATCH"
            d["resolution"] = res
            for rid in d.get("appearances", []):
                if rid in rows:
                    rows[rid]["status"] = "MATCH"
                    rows[rid]["resolution"] = res
                    rows[rid]["reason"] = (
                        f"Accepted by human review (persisted): "
                        f"{res.get('comment', '')}")
            applied += 1
    return applied


if __name__ == "__main__":
    q = build_queue({"elements": [
        {"id": "a", "status": "LOCATION_MISMATCH"},
        {"id": "b", "status": "MATCH"},
        {"id": "c", "status": "NEEDS_REVIEW"},
    ]})
    assert q["total"] == 2 and q["reviewed"] == 0, q
    try:
        set_disposition("a", "nope")
        raise AssertionError("invalid disposition accepted")
    except ValueError:
        pass
    # v2: analyze + resolve on a synthetic device registry — sandboxed so
    # the self-check never touches real artifacts or global teach memory
    import pathlib
    import tempfile
    _tmp = pathlib.Path(tempfile.mkdtemp()) / "rc.json"
    globals()["_path"] = lambda: _tmp
    teach.teach = lambda *a, **k: {"reply": "noted", "entry": None}
    el = {"elements": [
        {"id": "r1", "device_id": "holdown_dev_001", "category": "holdown",
         "status": "LOCATION_MISMATCH", "distance_ft": 2.5, "mark": "H2"},
        {"id": "r2", "device_id": "holdown_dev_001", "category": "holdown",
         "status": "LOCATION_MISMATCH", "distance_ft": 2.5, "mark": "H2"},
    ]}
    reg = {"categories": {"holdown": {"devices": [
        {"id": "holdown_dev_001", "mark": "H2", "x": 12.5, "y": 10.0,
         "status": "LOCATION_MISMATCH", "target_id": "rev_asm_009",
         "target_point": [10.0, 10.0], "distance_ft": 2.5,
         "appearances": ["r1", "r2"], "sheets": ["S-201", "S-202"]},
        {"id": "holdown_dev_002", "mark": "H1", "x": 32.4, "y": 20.0,
         "status": "LOCATION_MISMATCH", "target_id": "rev_asm_010",
         "target_point": [30.0, 20.0], "distance_ft": 2.4,
         "appearances": [], "sheets": ["S-201"]},
    ]}}}
    a = analyze("r1", el, reg)
    assert a["analysis_available"] and a["direction"] == "E", a
    r = resolve("r1", "accept", "leader anchored off stud face", el, reg)
    assert set(r["updated_element_ids"]) == {"r1", "r2"}
    assert el["elements"][0]["status"] == "MATCH"
    assert el["elements"][0]["resolution"]["original_status"] == "LOCATION_MISMATCH"
    # persistence re-apply on a FRESH run of the same pairing
    el2 = {"elements": [
        {"id": "n1", "device_id": "holdown_dev_001", "category": "holdown",
         "status": "LOCATION_MISMATCH", "mark": "H2"}]}
    reg2 = {"categories": {"holdown": {"devices": [
        {"id": "holdown_dev_001", "mark": "H2",
         "status": "LOCATION_MISMATCH", "target_id": "rev_asm_009",
         "appearances": ["n1"]}]}}}
    n = apply_stored_resolutions(el2, reg2)
    assert n == 1 and el2["elements"][0]["status"] == "MATCH", (n, el2)
    print("review self-check OK:", q["total"], "queue items + v2 resolution flow")
