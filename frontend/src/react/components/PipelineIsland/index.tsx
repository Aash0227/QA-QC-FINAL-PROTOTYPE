import { projectScoped, tokenized } from "../../lib/api";
import { toast } from "../../../util";
import { useState } from "react";
import { ChevronDown, ChevronRight, BrainCircuit, Loader2, Bug } from "lucide-react";

import logo from "@/assets/livio-logo-white.png";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

import KineticGrid, { KineticGridToggle } from "./KineticGrid";
import { PipelineTimeline } from "./PipelineTimeline";
import { usePipeline } from "./usePipeline";
import type { PipelineEvent } from "@/types/pipeline";

export default function PipelineIsland() {
  const {
    steps, project, runId, connected, status,
    debugRawEvents, startRun,
  } = usePipeline();
  const [gridPaused, setGridPaused] = useState(false);
  const [expanded, setExpanded] = useState(true);
  const [showDebug, setShowDebug] = useState(false);

  return (
    <KineticGrid paused={gridPaused}>
      <div className="flex flex-col min-h-screen">
        {/* ── HEADER ──────────────────────────────────────────────── */}
        <header className="flex items-center justify-between border-b border-white/8 bg-background/50 backdrop-blur-md px-5 py-3 z-20">
          <div className="flex items-center gap-3">
            <a href="/" className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors" title="Back to dashboard">
              ◂ Dash
            </a>
            <div className="h-5 w-px bg-border/50" />
            <img src={logo} alt="Livio" className="h-7 w-auto" />
            <div className="h-5 w-px bg-border/50" />
            <span className="text-sm font-semibold text-foreground/90">Pipeline</span>
            {project && (
              <Badge variant="secondary" className="font-mono">{project}</Badge>
            )}
            {runId && (
              <span className="text-xs text-muted-foreground font-mono">{runId.slice(-8)}</span>
            )}
          </div>

          <div className="flex items-center gap-2">
            <KineticGridToggle paused={gridPaused} onToggle={() => setGridPaused(!gridPaused)} />
            <Separator orientation="vertical" className="h-5" />
            <Button size="sm" onClick={() => startRun()}>
              <BrainCircuit className="h-3.5 w-3.5" /> Run
            </Button>
            <Button size="sm" variant="secondary" onClick={() => startRun(true)}>
              Force
            </Button>
            {/* "Stop" was a disabled placeholder with no endpoint behind it.
                A control that cannot do anything is worse than no control, so
                it is removed rather than left to look broken. Re-add it when
                a cancel endpoint exists.
                "Report" now downloads the punch list that
                GET /api/export/punch-list.csv has been serving all along. */}
            <Button
              size="sm"
              variant="outline"
              onClick={async () => {
                // Fetch rather than navigate. window.location.href sent the
                // browser to the raw endpoint, so on a project with no results
                // the user got a 409 JSON blob rendered as a page instead of an
                // explanation. Fetch lets us keep them here and say what is
                // actually missing.
                try {
                  // projectScoped, not a bare fetch: a raw fetch carries
                  // neither the X-Project header nor ?project=, so the export
                  // resolved to the server's globally-active project rather
                  // than the one THIS tab is pinned to — a tab could hand the
                  // user a different project's punch list.
                  const res = await fetch(tokenized(projectScoped("/api/export/punch-list.csv")));
                  if (!res.ok) {
                    const detail = await res.json().catch(() => null);
                    toast(
                      res.status === 409 || res.status === 404
                        ? "No results to export yet — run the pipeline first."
                        : "Could not export the punch list: " +
                            ((detail && detail.detail) || res.statusText),
                      true,
                    );
                    return;
                  }
                  const blob = await res.blob();
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = "punch_list.csv";
                  a.click();
                  URL.revokeObjectURL(url);
                } catch (e) {
                  toast("Could not export the punch list: " + (e as Error).message, true);
                }
              }}
            >
              Report
            </Button>
          </div>
        </header>

        {/* ── BODY ─────────────────────────────────────────────── */}
        <main className="flex-1 flex justify-center px-4 py-8">
          <div className="w-full max-w-2xl">
            <Card className="border-border/60 shadow-sm">
              {/* ── TITLE BAR ──────────────────────────────────── */}
              <div
                onClick={() => setExpanded(!expanded)}
                className="flex items-center justify-between px-5 py-3.5 cursor-pointer select-none bg-secondary/30 border-b border-border/50"
              >
                <div className="flex items-center gap-3">
                  {status === "running" ? (
                    <Loader2 className="w-4 h-4 text-primary animate-spin" />
                  ) : (
                    <BrainCircuit className="w-4 h-4 text-primary" />
                  )}
                  <span className="text-[15px] font-semibold text-foreground/90 tracking-tight">
                    {/* "blocked" is a real terminal state: nothing broke, but
                        the run produced no results because inputs were
                        missing. It used to be reported as "complete", which is
                        how a project that could never produce an answer came to
                        look finished. */}
                    {status === "running"
                      ? "Pipeline running…"
                      : status === "completed"
                        ? "Pipeline complete"
                        : status === "blocked"
                          ? "Pipeline blocked — missing inputs"
                          : status === "failed"
                            ? "Pipeline failed"
                            : "Pipeline"}
                  </span>
                </div>
                <div className="flex items-center gap-3">
                  <span className={`flex items-center gap-1.5 text-xs ${connected ? "text-emerald-400" : "text-rose-400"}`}>
                    <span className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-emerald-400 animate-pulse" : "bg-rose-400"}`} />
                    {connected ? "live" : "polling"}
                  </span>
                  {expanded ? <ChevronDown className="w-4 h-4 text-muted-foreground" /> : <ChevronRight className="w-4 h-4 text-muted-foreground" />}
                </div>
              </div>

              {/* ── TIMELINE ──────────────────────────────────── */}
              <div
                className={`grid transition-all duration-500 ease-in-out bg-card ${
                  expanded ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"
                }`}
              >
                <div className="overflow-hidden">
                  <PipelineTimeline steps={steps} />
                </div>
              </div>
            </Card>

            {/* ── DEBUG PANEL ──────────────────────────────────── */}
            <div className="mt-4">
              <button
                className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
                onClick={() => setShowDebug(!showDebug)}
              >
                <Bug className="h-3 w-3" />
                Debug: raw SSE events ({debugRawEvents.length})
              </button>
              {showDebug && (
                <div className="mt-2 rounded-md border border-border bg-secondary/40 p-3 max-h-48 overflow-auto font-mono text-xs text-muted-foreground">
                  {debugRawEvents.length === 0 && <span>no events yet</span>}
                  {debugRawEvents.slice(-10).map((e: PipelineEvent) => (
                    <div key={e.seq} className="pb-1">
                      <span className="text-foreground/50">[{e.step}]</span> {e.kind}: {e.message}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </main>
      </div>
    </KineticGrid>
  );
}