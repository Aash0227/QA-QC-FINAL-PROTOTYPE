import { createContext, useContext, useEffect, useReducer } from "react";

import { api, ApiError } from "@/lib/api";
import { usePipelineEvents } from "@/lib/use-pipeline-events";

import type { PipelineEvent, RunState } from "@/types/pipeline";

/**
 * Shell-level run state: current run (GET /api/pipeline/run), live stage
 * events (SSE), and the AI status line. Small reducer — no external store.
 * The future Pipeline UI consumes this context instead of calling the API
 * directly; legacy panels keep using the vanilla store until migrated.
 */

export interface RunContextValue {
  run: RunState | null;
  runError: string | null;
  events: PipelineEvent[];
  connected: boolean;
  aiText: string | null;
  refresh: () => Promise<void>;
  startRun: (force?: boolean) => Promise<void>;
  requestAiStatus: (stage: string, title: string) => Promise<void>;
}

const RunContext = createContext<RunContextValue | null>(null);

interface State {
  run: RunState | null;
  runError: string | null;
  events: PipelineEvent[];
  connected: boolean;
  aiText: string | null;
}

type Action =
  | { type: "run"; run: RunState }
  | { type: "error"; message: string }
  | { type: "event"; event: PipelineEvent }
  | { type: "connected"; connected: boolean }
  | { type: "ai"; text: string }
  | { type: "reset" };

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "run":
      return { ...state, run: action.run, runError: null };
    case "error":
      return { ...state, runError: action.message };
    case "event":
      // ponytail: keep the last 200 events; a timeline needs more, the
      // Pipeline UI needs the last ~10.
      return { ...state, events: [...state.events.slice(-199), action.event] };
    case "connected":
      return { ...state, connected: action.connected };
    case "ai":
      return { ...state, aiText: action.text };
    case "reset":
      return { run: null, runError: null, events: [], connected: false, aiText: null };
    default:
      return state;
  }
}

export function RunProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(reducer, undefined, () => ({
    run: null,
    runError: null,
    events: [],
    connected: false,
    aiText: null,
  }));

  const { connected } = usePipelineEvents({
    onEvent: (event) => dispatch({ type: "event", event }),
  });

  useEffect(() => {
    dispatch({ type: "connected", connected });
  }, [connected]);

  const refresh = async () => {
    try {
      dispatch({ type: "run", run: await api.runState() });
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        dispatch({ type: "reset" });
      } else {
        dispatch({ type: "error", message: err instanceof Error ? err.message : String(err) });
      }
    }
  };

  const startRun = async (force = false) => {
    try {
      // 409 = a run is already in flight → that run's state is still the truth.
      dispatch({ type: "run", run: await api.runPipeline(force) });
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        await refresh();
      } else {
        dispatch({ type: "error", message: err instanceof Error ? err.message : String(err) });
      }
    }
  };

  const requestAiStatus = async (stage: string, title: string) => {
    const { text } = await api.aiStatus(stage, title);
    dispatch({ type: "ai", text });
  };

  return (
    <RunContext.Provider
      value={{
        run: state.run,
        runError: state.runError,
        events: state.events,
        connected: state.connected,
        aiText: state.aiText,
        refresh,
        startRun,
        requestAiStatus,
      }}
    >
      {children}
    </RunContext.Provider>
  );
}

export function useRun(): RunContextValue {
  const ctx = useContext(RunContext);
  if (!ctx) throw new Error("useRun must be used inside <RunProvider>");
  return ctx;
}
