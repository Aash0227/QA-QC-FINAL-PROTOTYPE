import { useEffect, useState } from "react";

/**
 * Progressive AI text reveal — the explanation types out character by
 * character so the UI feels like the AI is responding live.
 *
 * ponytail: pure JS interval, no lib. Honors prefers-reduced-motion (reveals
 * instantly). Never blocks anything — it's a display-only effect.
 */
export function useTypewriter(text: string, speed = 12): string {
  const [shown, setShown] = useState("");
  const reduced =
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

  useEffect(() => {
    if (reduced) {
      setShown(text);
      return;
    }
    setShown("");
    if (!text) return;
    let i = 0;
    const timer = setInterval(() => {
      i += 1;
      setShown(text.slice(0, i));
      if (i >= text.length) clearInterval(timer);
    }, speed);
    return () => clearInterval(timer);
  }, [text, speed, reduced]);

  return shown;
}
