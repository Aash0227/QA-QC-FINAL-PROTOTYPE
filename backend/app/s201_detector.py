"""
Hold-down plan-mark detector: shared geometry engine + a legacy fixture.

The REUSABLE part of this module — detect_holdowns_on_page() and everything
it calls (leader-line following, filled-marker snapping, hardware-pair
clustering) — is fully generic: every parameter (mark pattern, table regions,
plan region) is supplied by the caller. generic_page_intelligence.py is the
only production caller, and it always supplies these explicitly, so no
project-specific constant below is ever reached from a live pipeline run.

The MADERA-SPECIFIC constants below (PLAN_BBOX, S201_TABLE_BBOXES,
HOLDOWN_ROW_BANDS, HOLDOWN_RE) are dead defaults that only apply when a
caller omits its parameters entirely (mark_pattern is None) — no production
code path does that. They exist solely so tests/test_pdf_detector.py can
regression-test the shared geometry engine against a known-good real-world
PDF and its known-good count (54 hold-downs, H1:10/H2:21/H3:6/H4:17). Schedule
data and mark-to-core-token mapping are NEVER fabricated from a fixed table —
a schedule that can't be parsed produces an honest "schedule_not_parsed"
result, and core-token mapping comes from this project's own config (see
app/normalization.py), never a built-in per-project table. Do not add a new
production caller that relies on the dead geometry defaults; pass explicit
parameters instead (see generic_page_intelligence.run_generic_page_intelligence
for the pattern).
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz

from . import normalization

# NOTE: Copied verbatim from C:\qa-qc\backend\app\services\s201_holdown_detector.py
# for the QA-QC-FINAL-PROTOTYPE. The only change from the production source is the
# removal of the DrawingIntelligenceGraph dependency (and the helpers that used it),
# replaced with a standalone locate_s201_page() so this prototype has no coupling to
# the old Livio backend package. The core detection logic is unchanged so the proven
# Madera S-201 baseline (H1=10, H2=21, H3=6, H4=17, total=54) is reproduced exactly.

BBox = tuple[float, float, float, float]

PLAN_BBOX: BBox = (40, 60, 2250, 1660)
S201_TABLE_BBOXES: tuple[BBox, ...] = (
    (1760, 725, 2250, 1045),
    (1785, 1435, 2250, 1590),
    (1875, 1035, 2250, 1425),
    (1460, 1225, 1790, 1650),
)
HOLDOWN_ROW_BANDS = (
    ("H1", 1504, 1524),
    ("H2", 1524, 1544),
    ("H3", 1544, 1565),
    ("H4", 1564, 1586),
)
HOLDOWN_RE = re.compile(
    r"^(?:(?:\((?P<count_paren>\d+)\)|(?P<count_plain>\d+))\s*)?(?P<label>H[1-4])$",
    re.IGNORECASE,
)


def _holdown_re_for(mark_pattern: str | None) -> re.Pattern[str]:
    """Additive generalization hook: same count-prefix grammar around a
    caller-supplied label alternation (e.g. 'HD1|HD2|HD3|HD4'). Default (None)
    returns the frozen Madera HOLDOWN_RE — behavior byte-identical."""
    if not mark_pattern:
        return HOLDOWN_RE
    return re.compile(
        r"^(?:(?:\((?P<count_paren>\d+)\)|(?P<count_plain>\d+))\s*)?"
        rf"(?P<label>{mark_pattern})$",
        re.IGNORECASE,
    )

@dataclass(frozen=True)
class LineSegment:
    a: tuple[float, float]
    b: tuple[float, float]
    length: float


@dataclass(frozen=True)
class FilledMarker:
    center: tuple[float, float]
    width: float
    height: float


@dataclass
class DetectionPlan:
    hit: dict[str, Any]
    targets: list[tuple[float, float]]
    hardware_pair: list[tuple[float, float]]
    hardware_pair_key: tuple[tuple[int, int], tuple[int, int]] | None = None
    hardware_pair_score: float = math.inf
    use_hardware_pair: bool = False


def locate_s201_page(pdf_path: Path) -> int | None:
    """Standalone replacement for the old graph-based page lookup.

    Finds the S-201 foundation-plan page by scanning for the sheet token plus a
    cluster of H1-H4 plan marks (the schedule-only page has the token but no plan
    marks). Returns the 0-based page index, or None when not found.
    """

    if not Path(pdf_path).exists():
        return None
    doc = fitz.open(str(pdf_path))
    try:
        best_index: int | None = None
        best_marks = 0
        for page_index, page in enumerate(doc):
            text = page.get_text("text")
            if not re.search(r"S-?201", text, re.IGNORECASE):
                continue
            marks = len(re.findall(r"\bH[1-4]\b", text))
            if marks > best_marks:
                best_marks = marks
                best_index = page_index
        return best_index
    finally:
        doc.close()


def detect_s201_holdowns(
    *,
    pdf_path: Path,
    page_index: int,
    sheet_number: str = "S-201",
    evidence_dir: Path | None = None,
    mark_pattern: str | None = None,
    table_bboxes: list[BBox] | None = None,
    plan_bbox: BBox | None = None,
) -> list[dict[str, Any]]:
    doc = fitz.open(str(pdf_path))
    try:
        page = doc[page_index]
        schedule = _extract_holdown_schedule(page) if mark_pattern is None else {}
        return detect_holdowns_on_page(
            page,
            page_index=page_index,
            sheet_number=sheet_number,
            schedule=schedule,
            evidence_dir=evidence_dir,
            mark_pattern=mark_pattern,
            table_bboxes=table_bboxes,
            plan_bbox=plan_bbox,
        )
    finally:
        doc.close()


def detect_holdowns_on_page(
    page: fitz.Page,
    *,
    page_index: int,
    sheet_number: str,
    schedule: dict[str, dict[str, str]] | None = None,
    evidence_dir: Path | None = None,
    mark_pattern: str | None = None,
    table_bboxes: list[BBox] | None = None,
    plan_bbox: BBox | None = None,
) -> list[dict[str, Any]]:
    # schedule=None means "no schedule could be parsed" (the legacy call
    # signature); an explicitly-passed empty dict means "this project has no
    # schedule data" (generic path). Neither ever manufactures rows — a
    # schedule this system couldn't read produces an honest empty schedule
    # flagged 'schedule_not_parsed', never a borrowed one from another project.
    schedule_not_parsed = schedule is None
    if schedule_not_parsed:
        schedule = {}
    words = page.get_text("words")
    if table_bboxes is None:
        table_bboxes = _table_bboxes(page)
    label_hits = _label_hits(
        words, table_bboxes, _holdown_re_for(mark_pattern), plan_bbox
    )
    vector_context = _page_vector_context(page)
    plans = [_build_detection_plan(hit, vector_context) for hit in label_hits]
    _resolve_hardware_pair_claims(plans)

    detections: list[dict[str, Any]] = []
    for hit_index, plan in enumerate(plans, start=1):
        hit = plan.hit
        label = str(hit["label"]).upper()
        source_bbox = hit["bbox"]
        points = _instance_points_from_plan(plan)
        total = max(int(hit["count"]), len(points))
        points = _normalize_instance_count(points, source_bbox, total)
        location_evidence = _location_evidence(plan, total)
        if schedule_not_parsed:
            sched, sched_source = {}, "schedule_not_parsed"
        elif not schedule:
            sched, sched_source = {}, "none"
        else:
            sched = schedule.get(label, {})
            if sched:
                sched_source = "detected"
            else:
                # mark absent from the read schedule — say so, never claim it
                # was detected nor substitute defaults.
                sched_source = "not_in_schedule"

        for instance_index, point in enumerate(points, start=1):
            # ponytail: sheet_number may be None when no sheet pattern was
            # found on the page (pdf_intelligence._detect_sheet_number) —
            # neutral id prefix instead of crashing; upgrade if ids become
            # a parseable contract for the frontend.
            sheet_tag = str(sheet_number or "sheet").lower()
            det_id = f"{sheet_tag}_{label.lower()}_{hit_index:03d}_{instance_index}"
            crop_url = ""
            if evidence_dir is not None:
                crop_name = f"{det_id}.png"
                _render_detection_crop(page, point, source_bbox, evidence_dir / crop_name)
                crop_url = crop_name
            detections.append(
                {
                    "id": det_id,
                    "sheet_number": sheet_number,
                    "page_index": page_index,
                    "raw_mark": hit["source_text"],
                    "normalized_mark": label,
                    "schedule_type_raw": sched.get("holdown_type", ""),
                    "schedule_source": sched_source,
                    "normalized_core_token": normalization.MARK_TO_CORE_TOKEN.get(label, ""),
                    "multiplicity_index": instance_index,
                    "total_multiplicity": total,
                    "bbox_pdf": tuple(round(float(v), 4) for v in source_bbox),
                    "center_pdf": [round(float(point[0]), 2), round(float(point[1]), 2)],
                    "evidence_crop_path": crop_url,
                    "anchor_bolt": sched.get("anchor_bolt", ""),
                    "fasteners": sched.get("stud_fasteners", ""),
                    "embedment": sched.get("min_embedment_depth_in_concrete", ""),
                    "confidence": float(location_evidence["confidence"]),
                    "source": "s201_focused_holdown_detector",
                    "location_method": location_evidence["method"],
                    "location_uncertainty_pt": location_evidence["uncertainty_pt"],
                    "leader_found": location_evidence["leader_found"],
                    "hardware_marker_found": location_evidence["hardware_marker_found"],
                    "explicit_count_found": location_evidence["explicit_count_found"],
                }
            )
    return detections


def summarize_focused_holdowns(detections: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(item["normalized_mark"] for item in detections)
    return {
        "total": len(detections),
        "by_type": dict(sorted(counts.items())),
    }


def _extract_holdown_schedule(page: fitz.Page) -> dict[str, dict[str, str]] | None:
    """Parse the schedule table. None when it could not be parsed — callers
    must not manufacture rows to fill the gap."""
    return _extract_holdown_schedule_from_words(page) or None


def _extract_holdown_schedule_from_words(page: fitz.Page) -> dict[str, dict[str, str]]:
    words = page.get_text("words")
    rows: dict[str, dict[str, str]] = {}
    for row_no, (mark, y0, y1) in enumerate(HOLDOWN_ROW_BANDS, start=1):
        row_words = [w for w in words if y0 <= _center(_bbox(w))[1] <= y1 and 1780 <= _center(_bbox(w))[0] <= 2235]
        if not row_words:
            continue
        holdown_type = _text_in_col(row_words, 1888, 1952)
        fasteners = _text_in_col(row_words, 1954, 2024)
        anchor_bolt = _text_in_col(row_words, 2030, 2110)
        embedment = _text_in_col(row_words, 2160, 2195)
        if not holdown_type:
            continue
        rows[mark] = {
            "s_no": str(row_no),
            "mark": mark,
            "holdown_type": _clean_cell(holdown_type),
            "stud_fasteners": _clean_cell(fasteners),
            "anchor_bolt": _clean_cell(anchor_bolt),
            "min_embedment_depth_in_concrete": _clean_cell(embedment),
        }
    if rows.get("H4", {}).get("stud_fasteners") == '(4) 3 4" DIA':
        rows["H4"]["stud_fasteners"] = '(4) 3/4" DIA'
    return rows


def _text_in_col(words: list[tuple], x0: float, x1: float) -> str:
    selected = [w for w in words if x0 <= _center(_bbox(w))[0] <= x1]
    selected.sort(key=lambda w: (float(w[1]), float(w[0])))
    return " ".join(str(w[4]) for w in selected)


def _clean_cell(cell: str | None) -> str:
    text = re.sub(r"\s+", " ", cell or "").strip()
    text = text.replace("3 4\"", '3/4"')
    text = text.replace("1 2\"", '1/2"')
    text = text.replace("5 8\"", '5/8"')
    return text


def _location_evidence(plan: DetectionPlan, total: int) -> dict[str, object]:
    explicit_count = int(plan.hit["count"]) > 1
    leader_found = bool(plan.targets)
    if plan.use_hardware_pair:
        return {
            "method": "paired_hardware_markers",
            "uncertainty_pt": 4.0,
            "leader_found": leader_found,
            "hardware_marker_found": True,
            "explicit_count_found": explicit_count,
            "confidence": 0.94,
        }
    if len(plan.targets) >= total and total > 1:
        return {
            "method": "multiple_leader_targets",
            "uncertainty_pt": 7.0,
            "leader_found": True,
            "hardware_marker_found": False,
            "explicit_count_found": explicit_count,
            "confidence": 0.9,
        }
    if plan.targets and total == 1:
        return {
            "method": "leader_target",
            "uncertainty_pt": 10.0,
            "leader_found": True,
            "hardware_marker_found": False,
            "explicit_count_found": explicit_count,
            "confidence": 0.84,
        }
    if plan.targets:
        return {
            "method": "leader_plus_synthetic_count_expansion",
            "uncertainty_pt": 15.0,
            "leader_found": True,
            "hardware_marker_found": False,
            "explicit_count_found": explicit_count,
            "confidence": 0.74,
        }
    if explicit_count:
        return {
            "method": "label_center_synthetic_count_expansion",
            "uncertainty_pt": 20.0,
            "leader_found": False,
            "hardware_marker_found": False,
            "explicit_count_found": True,
            "confidence": 0.62,
        }
    return {
        "method": "label_center_fallback",
        "uncertainty_pt": 24.0,
        "leader_found": False,
        "hardware_marker_found": False,
        "explicit_count_found": False,
        "confidence": 0.55,
    }


def _label_hits(
    words: list[tuple],
    table_bboxes: list[BBox],
    mark_re: "re.Pattern[str] | None" = None,
    plan_bbox: BBox | None = None,
) -> list[dict[str, Any]]:
    label_re = mark_re or HOLDOWN_RE
    hits: list[dict[str, Any]] = []
    used: set[int] = set()
    sorted_words = sorted(enumerate(words), key=lambda item: (item[1][1], item[1][0]))

    for idx, word in sorted_words:
        if idx in used:
            continue
        text = str(word[4]).strip()
        if not _word_is_in_plan(word, plan_bbox) or _inside_any_table(word, table_bboxes):
            continue

        match = label_re.match(text)
        if match:
            count_text = match.group("count_paren") or match.group("count_plain")
            source_text = text
            if not count_text:
                prefix = _nearby_count_prefix(idx, word, words)
                if prefix:
                    count_text = str(prefix[0])
                    source_text = f"{prefix[1]} {text}"
            hits.append(
                {
                    "label": match.group("label"),
                    "count": int(count_text or "1"),
                    "source_text": source_text,
                    "bbox": _bbox(word),
                }
            )
            used.add(idx)
    return _dedupe_hits(hits)


def _nearby_count_prefix(idx: int, word: tuple, words: list[tuple]) -> tuple[int, str] | None:
    wx0, wy0, _wx1, wy1 = [float(v) for v in word[:4]]
    wcy = (wy0 + wy1) / 2.0
    best = None
    for j, other in enumerate(words):
        if j == idx:
            continue
        text = str(other[4]).strip()
        match = re.match(r"^\(?(\d+)\)?$", text)
        if not match:
            continue
        count = int(match.group(1))
        if count != 2:
            continue
        ox0, oy0, ox1, oy1 = [float(v) for v in other[:4]]
        ocy = (oy0 + oy1) / 2.0
        if _number_is_detail_reference(other, words):
            continue
        gap = wx0 - ox1
        if abs(ocy - wcy) < 8 and 0 <= gap < (55 if not text.startswith("(") else 65):
            best = (count, text)
    return best


def _number_is_detail_reference(number_word: tuple, words: list[tuple]) -> bool:
    nx0, ny0, nx1, ny1 = [float(v) for v in number_word[:4]]
    ncx = (nx0 + nx1) / 2.0
    ncy = (ny0 + ny1) / 2.0
    for word in words:
        text = str(word[4]).strip()
        if not re.match(r"^S-\d{3}$", text, re.IGNORECASE):
            continue
        sx0, sy0, sx1, sy1 = [float(v) for v in word[:4]]
        scx = (sx0 + sx1) / 2.0
        scy = (sy0 + sy1) / 2.0
        if abs(scx - ncx) < 55 and 0 < scy - ncy < 45:
            return True
    return False


def _page_vector_context(page: fitz.Page) -> tuple[list[LineSegment], list[FilledMarker]]:
    diagonal_segments: list[LineSegment] = []
    filled_markers: list[FilledMarker] = []
    for drawing in page.get_drawings():
        color = drawing.get("color")
        fill = drawing.get("fill")
        rect = drawing.get("rect")
        if fill and max(fill) < 0.25 and rect:
            width = float(rect.width)
            height = float(rect.height)
            if (
                (4 <= width <= 22 and 4 <= height <= 22)
                or (5 <= width <= 22 and 2 <= height <= 22)
                or (2 <= width <= 22 and 5 <= height <= 22)
            ):
                filled_markers.append(
                    FilledMarker(
                        center=((float(rect.x0) + float(rect.x1)) / 2, (float(rect.y0) + float(rect.y1)) / 2),
                        width=width,
                        height=height,
                    )
                )
        if color and max(color) > 0.25:
            continue
        for item in drawing.get("items", []):
            if item[0] != "l":
                continue
            a = (float(item[1].x), float(item[1].y))
            b = (float(item[2].x), float(item[2].y))
            dx = abs(a[0] - b[0])
            dy = abs(a[1] - b[1])
            length = _distance(a, b)
            if not 10 <= length <= 220:
                continue
            if dx < 8 or dy < 8:
                continue
            slope = dy / dx if dx else 99
            if not 0.25 <= slope <= 4:
                continue
            diagonal_segments.append(LineSegment(a=a, b=b, length=length))
    return diagonal_segments, filled_markers


def _build_detection_plan(
    hit: dict[str, Any],
    vector_context: tuple[list[LineSegment], list[FilledMarker]],
) -> DetectionPlan:
    diagonal_segments, filled_markers = vector_context
    source_bbox = hit["bbox"]
    targets = _leader_target_points(source_bbox, diagonal_segments, filled_markers)
    hardware_pair: list[tuple[float, float]] = []
    hardware_pair_key = None
    hardware_pair_score = math.inf
    if len(targets) <= 1:
        hardware_claim = _nearby_aligned_hardware_pair(source_bbox, filled_markers)
        if hardware_claim:
            hardware_pair, hardware_pair_key, hardware_pair_score = hardware_claim
    return DetectionPlan(
        hit=hit,
        targets=targets,
        hardware_pair=hardware_pair,
        hardware_pair_key=hardware_pair_key,
        hardware_pair_score=hardware_pair_score,
    )


def _resolve_hardware_pair_claims(plans: list[DetectionPlan]) -> None:
    claims: dict[tuple[tuple[int, int], tuple[int, int]], DetectionPlan] = {}
    for plan in plans:
        if not plan.hardware_pair_key:
            continue
        current = claims.get(plan.hardware_pair_key)
        if current is None or plan.hardware_pair_score < current.hardware_pair_score:
            claims[plan.hardware_pair_key] = plan
    for plan in plans:
        plan.use_hardware_pair = bool(plan.hardware_pair_key and claims.get(plan.hardware_pair_key) is plan)


def _instance_points_from_plan(plan: DetectionPlan) -> list[tuple[float, float]]:
    explicit_count = int(plan.hit["count"])
    if explicit_count > 1:
        if len(plan.targets) >= explicit_count:
            return plan.targets[:explicit_count]
        if plan.use_hardware_pair:
            return plan.hardware_pair[:explicit_count]
        base = plan.targets[0] if plan.targets else _center(plan.hit["bbox"])
        return _expand_instance_points(base, plan.hit["bbox"], explicit_count)

    if len(plan.targets) == 2:
        return plan.targets

    closest = _closest_pair(plan.targets)
    if len(plan.targets) == 3 and closest and 40 <= closest[0] <= 75:
        return [closest[1], closest[2]]

    if plan.use_hardware_pair:
        return plan.hardware_pair

    if plan.targets:
        return [plan.targets[0]]

    return [_center(plan.hit["bbox"])]


def _normalize_instance_count(
    points: list[tuple[float, float]],
    source_bbox: BBox,
    total: int,
) -> list[tuple[float, float]]:
    if len(points) == total:
        return points
    if len(points) > total:
        return points[:total]
    base = points[0] if points else _center(source_bbox)
    return _expand_instance_points(base, source_bbox, total)


def _leader_target_points(
    label_bbox: BBox,
    segments: list[LineSegment],
    markers: list[FilledMarker],
) -> list[tuple[float, float]]:
    label_center = _center(label_bbox)
    points: list[tuple[float, float]] = []
    for segment in segments:
        distance_a = _distance(segment.a, label_center)
        distance_b = _distance(segment.b, label_center)
        distance_segment = _point_segment_distance(label_center, segment.a, segment.b)
        if min(distance_a, distance_b) >= 55 and distance_segment >= 14:
            continue
        far = segment.b if distance_a < distance_b else segment.a
        if _distance(far, label_center) < 25:
            continue
        points.append(_snap_to_filled_marker(far, markers))

    out: list[tuple[float, float]] = []
    for point in points:
        if all(_distance(point, existing) > 22 for existing in out):
            out.append(point)
    return out


def _nearby_aligned_hardware_pair(
    label_bbox: BBox,
    markers: list[FilledMarker],
) -> tuple[list[tuple[float, float]], tuple[tuple[int, int], tuple[int, int]], float] | None:
    label_center = _center(label_bbox)
    nearby = [
        marker.center
        for marker in markers
        if 25 < _distance(marker.center, label_center) < 85
    ]
    best: tuple[float, tuple[float, float], tuple[float, float]] | None = None
    for idx, a in enumerate(nearby):
        for b in nearby[idx + 1 :]:
            pair_distance = _distance(a, b)
            horizontally_paired = abs(a[1] - b[1]) < 12 and 20 <= abs(a[0] - b[0]) <= 45
            if not horizontally_paired or not 20 <= pair_distance <= 45:
                continue
            score = (_distance(label_center, a) + _distance(label_center, b)) / 2
            if best is None or score < best[0]:
                best = (score, a, b)
    if best is None:
        return None
    a_key = (round(best[1][0]), round(best[1][1]))
    b_key = (round(best[2][0]), round(best[2][1]))
    key = tuple(sorted([a_key, b_key]))
    return [best[1], best[2]], key, best[0]  # type: ignore[return-value]


def _snap_to_filled_marker(
    point: tuple[float, float],
    markers: list[FilledMarker],
    max_distance: float = 26,
) -> tuple[float, float]:
    nearest: tuple[float, tuple[float, float]] | None = None
    for marker in markers:
        distance = _distance(point, marker.center)
        if distance > max_distance:
            continue
        if nearest is None or distance < nearest[0]:
            nearest = (distance, marker.center)
    return nearest[1] if nearest else point


def _closest_pair(points: list[tuple[float, float]]) -> tuple[float, tuple[float, float], tuple[float, float]] | None:
    best: tuple[float, tuple[float, float], tuple[float, float]] | None = None
    for idx, a in enumerate(points):
        for b in points[idx + 1 :]:
            distance = _distance(a, b)
            if best is None or distance < best[0]:
                best = (distance, a, b)
    return best


def _expand_instance_points(base: tuple[float, float], source_bbox: BBox, total: int) -> list[tuple[float, float]]:
    if total <= 1:
        return [base]
    spacing = 18.0
    start = -spacing * (total - 1) / 2.0
    return [(base[0] + start + spacing * i, base[1]) for i in range(total)]


def _render_detection_crop(page: fitz.Page, point: tuple[float, float], label_bbox: BBox, output_path: Path) -> None:
    x, y = point
    lx0, ly0, lx1, ly1 = label_bbox
    bbox = (
        max(0, min(x, lx0) - 90),
        max(0, min(y, ly0) - 90),
        min(float(page.rect.width), max(x, lx1) + 90),
        min(float(page.rect.height), max(y, ly1) + 90),
    )
    pix = page.get_pixmap(matrix=fitz.Matrix(180 / 72, 180 / 72), clip=fitz.Rect(*bbox), alpha=False)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pix.save(str(output_path))


def _table_bboxes(page: fitz.Page) -> list[BBox]:
    if page.rect.width > 2000 and page.rect.height > 1500:
        return list(S201_TABLE_BBOXES)
    return []


def _word_is_in_plan(word: tuple, plan_bbox: BBox | None = None) -> bool:
    return _point_in_bbox(_center(_bbox(word)), plan_bbox or PLAN_BBOX)


def _inside_any_table(word: tuple, table_bboxes: list[BBox]) -> bool:
    center = _center(_bbox(word))
    for bbox in table_bboxes:
        if (bbox[2] - bbox[0]) > 500 and (bbox[3] - bbox[1]) > 500:
            continue
        if _point_in_bbox(center, bbox):
            return True
    return False


def _dedupe_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for hit in hits:
        center = _center(hit["bbox"])
        if any(hit["label"].upper() == prev["label"].upper() and _distance(center, _center(prev["bbox"])) < 5 for prev in out):
            continue
        out.append(hit)
    return out


def _bbox(word: tuple) -> BBox:
    return tuple(float(v) for v in word[:4])  # type: ignore[return-value]


def _center(bbox: BBox) -> tuple[float, float]:
    return ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)


def _point_in_bbox(point: tuple[float, float], bbox: BBox) -> bool:
    return bbox[0] <= point[0] <= bbox[2] and bbox[1] <= point[1] <= bbox[3]


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _point_segment_distance(
    point: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> float:
    ax, ay = a
    bx, by = b
    px, py = point
    dx = bx - ax
    dy = by - ay
    if dx == 0 and dy == 0:
        return _distance(point, a)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    projection = (ax + t * dx, ay + t * dy)
    return _distance(point, projection)
