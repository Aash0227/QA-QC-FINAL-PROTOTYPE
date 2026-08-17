import PipelineIsland from "@/components/PipelineIsland";
import { RunProvider } from "@/state/run-context";

export default function App() {
  return (
    <RunProvider>
      <PipelineIsland />
    </RunProvider>
  );
}