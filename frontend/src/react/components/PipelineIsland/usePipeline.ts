/** Dedicated hook for the PipelineIsland: composes the existing RunProvider
 *  context (useRun) and adds per-stage auto-AI + polling fallback.
 *  Drives the AgentPlanning-compatible timeline from live backend data.
 *
 *  ponytail: no duplicate SSE connection — the RunProvider owns one EventSource;
 *  this hook only subscribes to its events + round-trips. */

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import { useRun } from "@/state/run-context";
import type { PipelineEvent } from "@/types/pipeline";

import { type IslandStep, STAGE_ARTIFACT, toIslandStatus } from "./types";

const AI_TIMEOUT_MS = 6000;
const POLL_INTERVAL_MS = 8000;

export interface PipelineIslandState {
  steps: IslandStep[];
  project: string | null;
  runId: string | null;
  connected: boolean;
  status: "loading" | "upload" | "running" | "completed" | "error";
  debugRawEvents: PipelineEvent[];
  /** Action set */
  startRun: (force?: boolean) => Promise<void>;
}

export function usePipeline(): PipelineIslandState {
  const { run, events, connected, startRun, refresh } = useRun();
  const [steps, setSteps] = useState<IslandStep[]>([]);
  const [debugRawEvents, setDebugRawEvents] = useState<PipelineEvent[]>([]);
  const fetchingAi = useRef<Set<string>>(new Set());
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Initial load ──────────────────────────────────────────────────
  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Derive steps from run state ───────────────────────────────────
  useEffect(() => {
    if (!run) return;
    setSteps(
      run.stages.map((s) => ({
        id: s.key,
        title: s.title,
        status: toIslandStatus(s.status),
        duration_s: s.duration_s,
        started_at: s.started_at,
        completed_at: s.completed_at,
        message: s.reason ?? s.error ?? null,
        aiText: null,
        aiSource: null,
        aiPending: false,
        error: s.error,
        artifact: STAGE_ARTIFACT[s.key] ?? null,
      })),
    );
  }, [run]);

  // ── SSE events → per-step updates + auto-AI ───────────────────────
  const requestAiFor = useCallback(
    async (stageId: string, stageTitle: string) => {
      if (fetchingAi.current.has(stageId)) return;
      fetchingAi.current.add(stageId);
      setSteps((prev) =>
        prev.map((s) => (s.id === stageId ? { ...s, aiPending: true } : s)),
      );
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), AI_TIMEOUT_MS);
      try {
        const { text, source } = await api.aiStatus(stageId, stageTitle);
        setSteps((prev) =>
          prev.map((s) =>
            s.id === stageId ? { ...s, aiText: text, aiSource: source, aiPending: false } : s,
          ),
        );
      } catch (err) {
        const fallback = typeof err === "object" && (err as Error)?.name === "ApiError"
          ? "" // backend returned deterministic already
          : `${stageTitle} completed.`;
        setSteps((prev) =>
          prev.map((s) =>
            s.id === stageId
              ? { ...s, aiText: fallback, aiSource: "deterministic", aiPending: false }
              : s,
          ),
        );
      } finally {
        clearTimeout(timer);
        fetchingAi.current.delete(stageId);
      }
    },
    [],
  );

  useEffect(() => {
    if (events.length === 0) return;
    setDebugRawEvents((prev) => [...prev.slice(-99), events[events.length - 1]]);
    const latest = events[events.length - 1];
    setSteps((prev) => {
      const idx = prev.findIndex((s) => s.id === latest.step);
      if (idx === -1) return prev;
      const updated = prev.map((s, i) => {
        if (i !== idx) return s;
        const newStatus = toIslandStatus(
          latest.kind === "start" ? "running"
          : latest.kind === "done" ? "done"
          : latest.kind === "error" ? "failed"
          : latest.kind === "skip" ? "skipped"
          : "running", // fallback — preserve current kind from backend when known
        );
        return { ...s, status: newStatus, message: latest.message };
      });
      // Auto-AI after a step is done
      const changed = updated[idx];
      if (latest.kind === "done") {
        void requestAiFor(changed.id, changed.title);
      }
      return updated;
    });
  }, [events, requestAiFor]);

  // ── Poll fallback when SSE is disconnected ─────────────────────────
  useEffect(() => {
    if (!connected) {
      pollTimer.current = setInterval(() => void refresh(), POLL_INTERVAL_MS);
    } else {
      if (pollTimer.current) { clearInterval(pollTimer.current); pollTimer.current = null; }
    }
    return () => {
      if (pollTimer.current) clearInterval(pollTimer.current);
    };
  }, [connected, refresh]);

  return {
    steps,
    project: run?.project ?? null,
    runId: run?.run_id ?? null,
    connected,
    status: run ? (
      run.status === "running" ? "running"
      : run.status === "completed" ? "completed"
      : "error"
    ) : "loading",
    debugRawEvents,
    startRun,
  };
}