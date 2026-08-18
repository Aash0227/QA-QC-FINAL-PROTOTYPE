import { api } from "../../../api";
import { onStep, startFallbackPoll } from "../../../sse";
import { toast } from "../../../util";

import type { GridPointsResponse, RevitStatus, Workflow, WizardSseEvent } from "./types";

/** Tiny pub/sub for the wizard, same pattern as store.js -- needed because
 *  #bm-rail/#bm-cards/#bm-log are three separate DOM containers (three
 *  separate React roots), and they all need to react to the same workflow
 *  state/logs/pick-mode/revit-status. Not store.js itself: this state is
 *  wizard-local and none of it is read by other panels. */

export interface GridPick {
  grid_id: string;
  mark: string;
  label?: string;
}

interface WizardState {
  wf: Workflow | null;
  pickOn: boolean;
  gp: GridPointsResponse | null;
  picks: GridPick[];
  revitStatus: RevitStatus | null;
  logs: WizardSseEvent[];
}

export const wizardState: WizardState = {
  wf: null,
  pickOn: false,
  gp: null,
  picks: [],
  revitStatus: null,
  logs: [],
};

const subs: Array<() => void> = [];
export function subscribeWizard(fn: () => void): () => void {
  subs.push(fn);
  return () => {
    const i = subs.indexOf(fn);
    if (i >= 0) subs.splice(i, 1);
  };
}
function notify() {
  subs.forEach((fn) => fn());
}

export async function refresh() {
  try {
    wizardState.wf = await api<Workflow>("/api/benchmark-workflow");
  } catch {
    /* leave state as-is; next SSE event or poll retries */
  }
  notify();
}

export async function action(url: string, body: unknown) {
  try {
    wizardState.wf = await api<Workflow>(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (e) {
    toast("Autopilot: " + (e as Error).message, true);
    await refresh();
    return;
  }
  notify();
}

export async function startPick() {
  wizardState.pickOn = true;
  wizardState.picks = [];
  wizardState.gp = null;
  notify();
  try {
    wizardState.gp = await api<GridPointsResponse>("/api/benchmark-workflow/grid-points");
  } catch (e) {
    toast("Grid points: " + (e as Error).message, true);
    wizardState.pickOn = false;
  }
  notify();
}

export function setPicks(picks: GridPick[]) {
  wizardState.picks = picks;
  notify();
}
export function setPickOn(on: boolean) {
  wizardState.pickOn = on;
  notify();
}

const revitCheck = { checking: false, at: 0 };
export async function maybeCheckRevit() {
  if (revitCheck.checking || Date.now() - revitCheck.at < 12000) return;
  revitCheck.checking = true;
  try {
    wizardState.revitStatus = await api<RevitStatus>("/api/revit/status");
  } catch {
    wizardState.revitStatus = { connected: false, reason: "status check failed" };
  }
  revitCheck.checking = false;
  revitCheck.at = Date.now();
  notify();
}

let stopPoll: (() => void) | null = null;
let sseUnsub: (() => void) | null = null;

/** Called once (module-scope-equivalent) so the SSE subscription and the
 *  boot-time banner-relevant fetch are always active, matching the original
 *  onStep("benchmark_workflow", ...) module-scope subscription. Safe to call
 *  multiple times -- guarded. */
export function ensureLiveSubscription() {
  if (sseUnsub) return;
  sseUnsub = onStep("benchmark_workflow", (e: WizardSseEvent) => {
    wizardState.logs = [...wizardState.logs, e];
    notify();
    refresh();
  });
}

export function openWizard() {
  refresh();
  if (!stopPoll) stopPoll = startFallbackPoll(refresh, 8000);
}
export function closeWizard() {
  stopPoll?.();
  stopPoll = null;
}
