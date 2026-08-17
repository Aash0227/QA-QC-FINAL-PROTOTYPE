import { useState, memo } from "react";
import {
  ChevronDown, ChevronRight, Loader2, Check, AlertTriangle, Braces, Code,
} from "lucide-react";

import { cn } from "@/lib/utils";

import { AiText } from "./AiText";

import type { IslandStep } from "./types";

const STATUS_ICON: Record<IslandStep["status"], React.ReactNode> = {
  pending: <div className="h-1.5 w-1.5 rounded-full bg-current" />,
  active: <Loader2 className="h-3.5 w-3.5 animate-spin" />,
  success: <Check className="h-3.5 w-3.5" />,
  error: <AlertTriangle className="h-3.5 w-3.5" />,
  skipped: <div className="h-1.5 w-1.5 rounded-full bg-current" />,
};

const STATUS_RING: Record<IslandStep["status"], string> = {
  pending: "bg-secondary text-muted-foreground ring-border/50 dark:bg-secondary/50",
  active: "bg-blue-100 text-blue-600 ring-blue-500/30 dark:bg-blue-500/20 dark:text-blue-400",
  success: "bg-emerald-100 text-emerald-600 ring-emerald-500/20 dark:bg-emerald-500/20 dark:text-emerald-400",
  error: "bg-rose-100 text-rose-600 ring-rose-500/20 dark:bg-rose-500/20 dark:text-rose-400",
  skipped: "bg-secondary text-muted-foreground ring-border/50 dark:bg-secondary/50",
};

export const StepRow = memo(function StepRow({
  step,
  isLast,
}: {
  step: IslandStep;
  isLast: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const [showTech, setShowTech] = useState(false);

  const hasContent = !!step.message || !!step.aiText || step.aiPending || !!step.artifact;

  return (
    <div
      className={cn(
        "relative flex gap-4 animate-in fade-in slide-in-from-top-4 duration-500 fill-mode-both",
        step.status === "pending" && "opacity-60",
        step.status === "skipped" && "opacity-50",
      )}
    >
      {/* connecting line */}
      {!isLast && (
        <div className="absolute left-[11px] top-7 bottom-[-10px] w-px bg-border/60 z-0" />
      )}

      {/* status icon */}
      <div className="relative z-10 flex-none w-6 h-6 mt-0.5">
        <div
          className={cn(
            "flex items-center justify-center w-full h-full rounded-full ring-4 ring-card transition-colors duration-300",
            STATUS_RING[step.status],
          )}
          aria-label={`${step.status}: ${step.title}`}
        >
          {STATUS_ICON[step.status]}
        </div>
      </div>

      {/* content */}
      <div className="flex-1 pb-6">
        <div
          className={cn(
            "flex items-center justify-between group rounded-md -mx-2 px-2 py-1 transition-colors",
            hasContent && "cursor-pointer hover:bg-secondary/50",
          )}
          onClick={() => hasContent && setExpanded(!expanded)}
          onKeyDown={(e) => {
            if ((e.key === "Enter" || e.key === " ") && hasContent) setExpanded(!expanded);
          }}
          role="button"
          aria-expanded={expanded}
          tabIndex={0}
        >
          <span
            className={cn(
              "text-sm tracking-tight transition-colors duration-200",
              step.status === "active" && "text-foreground font-semibold",
              step.status === "error" && "text-rose-600 dark:text-rose-400 font-semibold",
              step.status !== "active" && step.status !== "error" && "text-foreground/80 group-hover:text-foreground font-medium",
            )}
          >
            {step.title}
          </span>

          <div className="flex items-center gap-3">
            {step.duration_s !== null && (
              <span className="text-xs font-mono text-muted-foreground tabular-nums">
                {step.duration_s}s
              </span>
            )}
            {hasContent && (
              <div className="text-muted-foreground/40 group-hover:text-muted-foreground transition-colors">
                {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
              </div>
            )}
          </div>
        </div>

        {/* expanded detail */}
        {hasContent && (
          <div
            className={cn(
              "grid transition-all duration-400 ease-in-out",
              expanded ? "grid-rows-[1fr] mt-2 opacity-100" : "grid-rows-[0fr] mt-0 opacity-0",
            )}
          >
            <div className="overflow-hidden">
              <div className="pt-1 pb-2 space-y-2">
                {step.message && (
                  <p className="text-xs text-foreground/70">{step.message}</p>
                )}

                {/* AI explanation */}
                {step.aiPending && (
                  <div className="flex items-center gap-2 text-xs text-muted-foreground animate-pulse">
                    <Loader2 className="h-3 w-3 animate-spin" /> AI explanation pending…
                  </div>
                )}
                {step.aiText && <AiText text={step.aiText} source={step.aiSource} />}

                {/* technical details panel */}
                {step.artifact && (
                  <div>
                    <button
                      className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
                      onClick={(e) => { e.stopPropagation(); setShowTech(!showTech); }}
                    >
                      <Braces className="h-3 w-3" />
                      Technical details
                      {showTech ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                    </button>
                    {showTech && (
                      <div className="mt-2 rounded-md border border-border bg-secondary/40 p-3 space-y-2 font-mono text-xs text-muted-foreground">
                        <div><span className="text-foreground/50">stage:</span> {step.id}</div>
                        <div><span className="text-foreground/50">artifact:</span> {step.artifact.key} → {step.artifact.filename}</div>
                        {step.started_at && (
                          <div><span className="text-foreground/50">started:</span> {step.started_at}</div>
                        )}
                        {step.completed_at && (
                          <div><span className="text-foreground/50">completed:</span> {step.completed_at}</div>
                        )}
                        {step.error && (
                          <div className="text-rose-400"><span className="text-foreground/50">error:</span> {step.error}</div>
                        )}
                        <div className="mt-2 flex items-center gap-2 pt-2 border-t border-border/50">
                          <Code className="h-3 w-3" />
                          <span>artifact viewer: available when backend supports GET /api/artifacts/{'{key}'}</span>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
});