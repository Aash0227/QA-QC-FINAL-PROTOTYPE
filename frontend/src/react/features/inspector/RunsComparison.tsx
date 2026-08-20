import { useEffect, useState } from "react";

import { api } from "../../../api";
import { COL, RUN_STATUSES, toast } from "../../../util";

const COLORS = COL as Record<string, string>;
const STATUSES = RUN_STATUSES as string[];

interface RunSnapshot {
  label?: string;
  row_count?: number;
  saved_at?: string;
  by_category: Record<string, Record<string, number>>;
  totals: Record<string, number>;
}
interface DeviceChange {
  key: string;
  old_status: string;
  new_status: string;
  old_distance_ft?: number;
  new_distance_ft?: number;
}
interface RunsCompare {
  project: string;
  baseline: RunSnapshot;
  current: RunSnapshot;
  device_changes: DeviceChange[] | null;
  device_note?: string;
}

const SHORT: Record<string, string> = {
  LOCATION_MISMATCH: "LOC_MIS",
  NOT_IN_SCHEDULE: "NO_SCHED",
  NOT_EVALUATED: "NOT_EVAL",
  NO_REVIT_DATA: "NO_DATA",
};

function runDelta(a?: number, b?: number) {
  const d = (b || 0) - (a || 0);
  if (!d) return null;
  return (
    <small style={{ color: d > 0 ? "#4ade80" : "#f87171" }}>
      {" "}
      ({d > 0 ? "+" : ""}
      {d})
    </small>
  );
}

/** React port of panels/inspector.js's initRuns(). Mounted into #runs-body. */
export function RunsComparison() {
  const [data, setData] = useState<RunsCompare | "loading" | "none">("loading");

  const load = () => {
    setData("loading");
    api<RunsCompare>("/api/runs/compare")
      .then(setData)
      .catch(() => setData("none"));
  };

  useEffect(() => {
    // Load only when the Runs drawer is actually opened, not on mount. This
    // panel is closed on every normal dashboard load, and "no baseline saved
    // yet" is a legitimate 404 — fetching it eagerly turned an expected state
    // into a console error on every single page load, which is exactly the
    // kind of noise that hides a real error later.
    window.addEventListener("runs-init", load);
    return () => window.removeEventListener("runs-init", load);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const btn = document.getElementById("runs-save-baseline");
    const onSave = async () => {
      const label = prompt("Label for this baseline:", "current run");
      if (!label) return;
      await api(`/api/runs/baseline?label=${encodeURIComponent(label)}`, { method: "POST" });
      toast(`Baseline "${label}" saved.`);
      load();
    };
    btn?.addEventListener("click", onSave);
    return () => btn?.removeEventListener("click", onSave);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const label = document.getElementById("runs-label");
    if (!label) return;
    label.textContent = data === "loading" ? "–" : data === "none" ? "no baseline" : data.project;
  }, [data]);

  if (data === "loading") return <span style={{ color: "var(--dim)" }}>Loading…</span>;
  if (data === "none")
    return (
      <span style={{ color: "var(--dim)" }}>
        No baseline saved for this project yet. Run the pipeline, then press "Save as baseline" —
        the next run will compare against it.
      </span>
    );

  const { baseline, current, device_changes, device_note } = data;
  const cats = [...new Set([...Object.keys(baseline.by_category), ...Object.keys(current.by_category)])].sort();

  const Row = ({ label, a, b, bold }: { label: string; a: Record<string, number>; b: Record<string, number>; bold?: boolean }) => (
    <tr style={bold ? { fontWeight: 700 } : undefined}>
      <td>{label}</td>
      {STATUSES.map((s) => {
        const av = a[s] || 0;
        const bv = b[s] || 0;
        return (
          <td style={{ textAlign: "right" }} key={s}>
            {av} → {bv}
            {s === "MATCH" ? runDelta(av, bv) : null}
          </td>
        );
      })}
    </tr>
  );

  return (
    <>
      <p style={{ fontSize: 12, color: "var(--dim)" }}>
        <b>{baseline.label}</b> ({baseline.row_count} rows, saved {String(baseline.saved_at || "").slice(0, 10)}) →{" "}
        <b>current run</b> ({current.row_count} rows). Every cell is honest — statuses are never rewritten, only
        re-measured.
      </p>
      <table style={{ width: "100%", fontSize: 11, borderCollapse: "collapse" }} className="runs-table">
        <tbody>
          <tr style={{ color: "var(--dim)" }}>
            <th style={{ textAlign: "left" }}>category</th>
            {STATUSES.map((s) => (
              <th style={{ textAlign: "right", padding: "2px 4px" }} key={s}>
                {SHORT[s] || s}
              </th>
            ))}
          </tr>
          {cats.map((c) => (
            <Row key={c} label={c} a={baseline.by_category[c] || {}} b={current.by_category[c] || {}} />
          ))}
          <Row label="TOTAL" a={baseline.totals} b={current.totals} bold />
        </tbody>
      </table>
      {device_changes === null ? (
        <p style={{ fontSize: 11, color: "var(--dim)", marginTop: 10 }}>
          Per-device diff unavailable — {device_note || ""}.
        </p>
      ) : device_changes.length ? (
        <>
          <h4 style={{ margin: "14px 0 4px" }}>What changed</h4>
          <table style={{ width: "100%", fontSize: 11, borderCollapse: "collapse" }} className="runs-table">
            <tbody>
              {device_changes.map((c, i) => (
                <tr key={i}>
                  <td>{c.key}</td>
                  <td style={{ color: COLORS[c.old_status] || "#94a3b8" }}>{c.old_status.replaceAll("_", " ")}</td>
                  <td>→</td>
                  <td style={{ color: COLORS[c.new_status] || "#94a3b8" }}>{c.new_status.replaceAll("_", " ")}</td>
                  <td style={{ textAlign: "right" }}>
                    {c.old_distance_ft ?? "—"} → {c.new_distance_ft ?? "—"} ft
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      ) : (
        <p style={{ fontSize: 11, color: "var(--dim)", marginTop: 10 }}>No device changed status.</p>
      )}
      <style>{`.runs-table td{padding:3px 4px;border-top:1px solid #1c2740}`}</style>
    </>
  );
}
