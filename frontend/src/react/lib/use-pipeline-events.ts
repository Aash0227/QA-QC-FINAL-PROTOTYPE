import { useEffect, useRef, useState } from "react";

import { projectScoped, tokenized } from "@/lib/api";

import type { PipelineEvent } from "@/types/pipeline";

export type PipelineEventKind = PipelineEvent["kind"];

export interface UsePipelineEventsOptions {
  /** Called per event, in arrival order. Keep handlers cheap. */
  onEvent?: (event: PipelineEvent) => void;
  /** SSE cannot carry a project header — the connection is ambient (active
   *  project), same as the legacy vanilla client. */
  enabled?: boolean;
}

export interface PipelineEventsState {
  connected: boolean;
  lastEvent: PipelineEvent | null;
  eventCount: number;
}

const EVENTS_URL = "./api/pipeline/events";

/** SSE URL with the auth token AND the project appended when present.
 *
 *  EventSource cannot set headers, so both travel as query params —
 *  routers/common resolves ?project= exactly as it resolves X-Project. Without
 *  the project the stream fell back to the globally-active project, which is
 *  how this page came to render another project's stage completions as its
 *  own. Same contract as the vanilla sse.js client. */
export function pipelineEventsUrl(): string {
  return tokenized(projectScoped(EVENTS_URL));
}

/**
 * Single EventSource for pipeline stage events. The EventSource itself
 * auto-reconnects (browser default); this hook just surfaces connection state
 * and tears the stream down on unmount. The future Pipeline UI will subscribe
 * once at the shell level and fan events out through context.
 */
export function usePipelineEvents({
  onEvent,
  enabled = true,
}: UsePipelineEventsOptions = {}): PipelineEventsState {
  const [connected, setConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState<PipelineEvent | null>(null);
  const [eventCount, setEventCount] = useState(0);
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;

  useEffect(() => {
    if (!enabled) return;

    const source = new EventSource(pipelineEventsUrl());
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);

    source.onmessage = (msg) => {
      let event: PipelineEvent;
      try {
        event = JSON.parse(msg.data) as PipelineEvent;
      } catch {
        return; // hello/keepalive frames with non-JSON data — ignore
      }
      setLastEvent(event);
      setEventCount((n) => n + 1);
      handlerRef.current?.(event);
    };

    return () => {
      source.close();
      setConnected(false);
    };
  }, [enabled]);

  return { connected, lastEvent, eventCount };
}

export type { UsePipelineEventsOptions as _Options };
