// Fixture data for the gated demo mode used to generate documentation
// screenshots. The benchmark/diagnostics/verdict were produced by the REAL
// backend analysis engine (see tooling), so the graded verdict matches actual
// app output. Demo mode only activates with a ?demo= query param.
import demoData from "./demo.json";
import type { Benchmark, Diagnostics, Drive, Status, Verdict } from "./types";

export interface DemoLive {
  phaseLabel: string;
  metrics: Record<string, { pct: number; mbps: number; iops?: number; done: boolean }>;
  sustainedPoints: { elapsed: number; written_bytes: number; mbps: number }[];
}

export interface DemoData {
  status: Status;
  drives: Drive[];
  blurb: string;
  benchmark: Benchmark;
  diagnostics: Diagnostics;
  verdict: Verdict;
  live: DemoLive;
}

export const DEMO = demoData as unknown as DemoData;

// ?demo=setup   -> pre-run state (drive picker + config + connection preview)
// ?demo=live    -> a frozen mid-benchmark frame (live metric bars)
// ?demo=results -> completed results (Diagnosis tab; other tabs via clicks)
export type DemoState = "setup" | "live" | "results";

export function demoStateFromLocation(): DemoState | null {
  const v = new URLSearchParams(window.location.search).get("demo");
  if (v === "setup" || v === "live" || v === "results") return v;
  if (v === "1" || v === "true") return "results";
  return null;
}
