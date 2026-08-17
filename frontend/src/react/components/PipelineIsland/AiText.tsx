import { memo } from "react";

import { useTypewriter } from "@/lib/use-typewriter";

export const AiText = memo(function AiText({ text, source }: { text: string; source: string | null }) {
  const typed = useTypewriter(text, 10);
  return (
    <div className="rounded-md border border-primary/20 bg-primary/5 backdrop-blur-sm p-3 text-xs text-foreground/80 leading-relaxed">
      <span className="font-medium text-primary">AI: </span>
      {typed}
      <span className="inline-block w-1.5 h-3 bg-primary/40 animate-pulse ml-0.5 align-middle" />
      {source === "deterministic" && (
        <span className="ml-1 text-muted-foreground">(offline fallback)</span>
      )}
    </div>
  );
});