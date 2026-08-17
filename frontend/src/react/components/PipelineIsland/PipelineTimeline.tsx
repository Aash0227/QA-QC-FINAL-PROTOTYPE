import { memo } from "react";
import { BrainCircuit } from "lucide-react";

import { StepRow } from "./StepRow";
import type { IslandStep } from "./types";

export const PipelineTimeline = memo(function PipelineTimeline({
  steps,
}: {
  steps: IslandStep[];
}) {
  if (steps.length === 0) {
    return (
      <div className="flex flex-col items-center gap-4 py-12 text-muted-foreground text-sm">
        <BrainCircuit className="h-8 w-8 opacity-30" />
        No pipeline steps yet — upload a drawing to begin
      </div>
    );
  }

  return (
    <div className="p-5 flex flex-col">
      {steps.map((step, idx) => (
        <StepRow key={step.id} step={step} isLast={idx === steps.length - 1} />
      ))}
    </div>
  );
});