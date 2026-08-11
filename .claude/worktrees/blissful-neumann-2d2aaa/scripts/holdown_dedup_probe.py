"""Probe: are PDF_ONLY holdowns the same physical device drawn on another
sheet? Fit each sheet's similarity transform from its saved point pairs,
inverse-project every PDF holdown callout to model space, cluster across
sheets, and compare cluster count to Revit assembly count."""
import json
import math
import os
from collections import Counter

BASE = r"C:\QA-QC-FINAL-PROTOTYPE-bkp\artifacts\projects\madera"


def load(name):
    with open(os.path.join(BASE, name), encoding="utf-8") as f:
        return json.load(f)


def fit_similarity(pairs):
    """least-squares similarity revit(ft) -> pdf(pt), trying both chiralities
    (PDF y is typically flipped vs model y); returns inverse fn"""
    best = None
    for flip in (1.0, -1.0):
        inv, rms = _fit_one(pairs, flip)
        if best is None or rms < best[1]:
            best = (inv, rms)
    print("  fit rms: %.2f pt" % best[1])
    return best[0]


def _fit_one(pairs, flip):
    src = [(p["revit_point"]["x"], flip * p["revit_point"]["y"])
           for p in pairs]
    dst = [(p["pdf_point"]["x"], p["pdf_point"]["y"]) for p in pairs]
    n = len(src)
    mx = sum(x for x, _ in src) / n; my = sum(y for _, y in src) / n
    ux = sum(x for x, _ in dst) / n; uy = sum(y for _, y in dst) / n
    sxx = sxy = ss = 0.0
    for (x, y), (u, v) in zip(src, dst):
        dx, dy, du, dv = x - mx, y - my, u - ux, v - uy
        sxx += dx * du + dy * dv
        sxy += dx * dv - dy * du
        ss += dx * dx + dy * dy
    a = sxx / ss; b = sxy / ss   # u = a*x - b*y + tx ; v = b*x + a*y + ty
    tx = ux - a * mx + b * my; ty = uy - b * mx - a * my
    det = a * a + b * b

    def inv(u, v):
        u2, v2 = u - tx, v - ty
        return ((a * u2 + b * v2) / det, flip * (-b * u2 + a * v2) / det)

    rms = math.sqrt(sum(
        (a * x - b * y + tx - u) ** 2 + (b * x + a * y + ty - v) ** 2
        for (x, y), (u, v) in zip(src, dst)) / n)
    return inv, rms


cals = {"S-201": load("registration_calibration.json"),
        "S-202": load("registration_calibration_S-202.json"),
        "S-205": load("registration_calibration_S-205.json")}
inv = {s: fit_similarity(c["point_pairs"]) for s, c in cals.items()}

rows = [r for r in load("element_list.json")["elements"]
        if r.get("category") == "holdown" and r.get("sheet") in inv
        and r.get("pdf_point")]
pts = []
for r in rows:
    x, y = inv[r["sheet"]](r["pdf_point"]["x"], r["pdf_point"]["y"])
    pts.append({"row": r, "mx": x, "my": y})

# cluster across sheets: same mark within TOL ft = same physical device
TOL_FT = 3.0
clusters = []
for p in pts:
    for c in clusters:
        if (c["mark"] == p["row"]["mark"]
                and abs(c["x"] - p["mx"]) <= TOL_FT
                and abs(c["y"] - p["my"]) <= TOL_FT):
            c["members"].append(p)
            break
    else:
        clusters.append({"mark": p["row"]["mark"], "x": p["mx"], "y": p["my"],
                         "members": [p]})

print("PDF callout rows:", len(pts), "-> physical clusters:", len(clusters))
print("cluster sizes:", dict(Counter(len(c["members"]) for c in clusters)))
print("clusters by mark:", dict(Counter(c["mark"] for c in clusters)))

asm = load("AIConvert_revit.json")["canonical_holdown_assemblies"]
print("revit assemblies:", len(asm),
      dict(Counter(a["pdf_mark_candidate"] for a in asm)))

# how many multi-sheet clusters contain a MATCH on one sheet and a
# PDF_ONLY/LOCATION_MISMATCH on another (= double-counted "misses")
double_miss = 0
statuses_fixed = Counter()
for c in clusters:
    sts = {m["row"]["status"] for m in c["members"]}
    if "MATCH" in sts and len(c["members"]) > 1:
        for m in c["members"]:
            if m["row"]["status"] in ("PDF_ONLY", "LOCATION_MISMATCH"):
                double_miss += 1
                statuses_fixed[m["row"]["status"]] += 1
print("rows that are re-appearances of an already-MATCHED device:",
      double_miss, dict(statuses_fixed))

# physical-level verdict: cluster matched if ANY member matched
phys = Counter()
for c in clusters:
    sts = [m["row"]["status"] for m in c["members"]]
    if "MATCH" in sts:
        phys["MATCH"] += 1
    elif "LOCATION_MISMATCH" in sts:
        phys["LOCATION_MISMATCH"] += 1
    else:
        phys["PDF_ONLY"] += 1
print("physical-element verdicts:", dict(phys))

# mark-blind nearest-assembly distance for every physical PDF cluster (ft)
import bisect
dists = []
for c in clusters:
    best = None; bmark = None
    for a in asm:
        d = math.hypot(a["center_point"]["x"] - c["x"],
                       a["center_point"]["y"] - c["y"])
        if best is None or d < best:
            best, bmark = d, a["pdf_mark_candidate"]
    dists.append((c["mark"], bmark, best))
buckets = Counter()
for pm, rm, d in dists:
    if d <= 2.0:
        buckets["<=2ft " + ("same-mark" if pm == rm else "MARK-DIFF %s->%s" % (pm, rm))] += 1
    elif d <= 6.0:
        buckets["2-6ft"] += 1
    else:
        buckets[">6ft (no device nearby)"] += 1
print("mark-blind nearest-assembly buckets:", dict(buckets))
far = [x for x in dists if x[2] > 6.0]
print("no-device-nearby by PDF mark:", dict(Counter(x[0] for x in far)))
