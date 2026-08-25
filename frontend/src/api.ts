import type { Drive, Diagnostics, Status, Verdict, RunEvent, Benchmark } from "./types";

// Same-origin relative URLs; the Vite dev server proxies /api and /ws to :8760.
async function getJSON<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path} -> ${r.status}`);
  return r.json();
}

export const api = {
  status: () => getJSON<Status>("/api/status"),
  drives: () => getJSON<{ drives: Drive[] }>("/api/drives").then((d) => d.drives),
  diagnostics: (letter: string) => getJSON<Diagnostics>(`/api/diagnostics/${letter}`),
  analyze: async (blurb: string, benchmark: Benchmark, diagnostics: Diagnostics): Promise<Verdict> => {
    const r = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ blurb, benchmark, diagnostics }),
    });
    if (!r.ok) throw new Error(`analyze -> ${r.status}`);
    return r.json();
  },
};

export interface RunRequest {
  letter: string;
  depth: string;
  blurb: string | null;
  sustained_size_mb?: number | null;
  seq_size_mb?: number | null;
  allow_system?: boolean;
}

// Opens the WebSocket, starts a run, and calls onEvent for every server message.
// Returns a cancel() that closes the socket.
export function runBenchmark(req: RunRequest, onEvent: (ev: RunEvent) => void): () => void {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/run`);
  ws.onopen = () => ws.send(JSON.stringify(req));
  ws.onmessage = (m) => {
    try {
      onEvent(JSON.parse(m.data) as RunEvent);
    } catch {
      /* ignore malformed frames */
    }
  };
  ws.onerror = () => onEvent({ type: "error", message: "WebSocket connection failed." });
  return () => ws.close();
}
