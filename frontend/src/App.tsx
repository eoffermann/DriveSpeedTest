import { useEffect, useMemo, useRef, useState } from "react";
import { api, runBenchmark } from "./api";
import type { Benchmark, Diagnostics, Drive, RunEvent, Status, Verdict } from "./types";
import { humanSize, num } from "./format";
import { Badge, BusBadge } from "./components/ui";
import { Results } from "./components/Results";
import { DEMO, demoStateFromLocation } from "./demo";

const DEPTHS = [
  { key: "quick", label: "Quick", hint: "~1 GiB · no sustained" },
  { key: "full", label: "Full", hint: "2 GiB + 4 GiB sustained" },
  { key: "sustained", label: "Sustained", hint: "16 GiB — find the SLC cliff" },
];

interface MetricLive { pct: number; mbps: number; iops?: number; done: boolean; }
const METRICS = [
  { key: "seq_write", label: "Sequential write", rand: false },
  { key: "seq_read", label: "Sequential read", rand: false },
  { key: "rand_write", label: "Random 4K write", rand: true },
  { key: "rand_read", label: "Random 4K read", rand: true },
  { key: "sustained", label: "Sustained write", rand: false },
];

export default function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [drives, setDrives] = useState<Drive[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [preDiag, setPreDiag] = useState<Diagnostics | null>(null);
  const [depth, setDepth] = useState("full");
  const [blurb, setBlurb] = useState("");

  const [running, setRunning] = useState(false);
  const [phaseLabel, setPhaseLabel] = useState("");
  const [live, setLive] = useState<Record<string, MetricLive>>({});
  const [sustainedPoints, setSustainedPoints] = useState<{ elapsed: number; written_bytes: number; mbps: number }[]>([]);

  const [benchmark, setBenchmark] = useState<Benchmark | null>(null);
  const [diagnostics, setDiagnostics] = useState<Diagnostics | null>(null);
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [error, setError] = useState<string>("");
  const cancelRef = useRef<(() => void) | null>(null);

  // Initial load. In demo mode (?demo=...), populate from fixtures instead of the
  // API so documentation screenshots are deterministic and hardware-independent.
  useEffect(() => {
    const demo = demoStateFromLocation();
    if (demo) {
      setStatus(DEMO.status);
      setDrives(DEMO.drives);
      setSelected("E");
      setBlurb(DEMO.blurb);
      setPreDiag(DEMO.diagnostics);
      if (demo === "results") {
        setBenchmark(DEMO.benchmark);
        setDiagnostics(DEMO.diagnostics);
        setVerdict(DEMO.verdict);
      } else if (demo === "live") {
        setRunning(true);
        setPhaseLabel(DEMO.live.phaseLabel);
        setLive(DEMO.live.metrics);
        setSustainedPoints(DEMO.live.sustainedPoints);
      }
      return;
    }
    api.status().then((s) => { setStatus(s); if (!blurb) setBlurb(s.default_blurb); }).catch(() => {});
    api.drives().then((ds) => {
      setDrives(ds);
      const pick = ds.find((d) => d.bus_type?.toUpperCase() === "USB") ?? ds.find((d) => !d.is_system) ?? ds[0];
      if (pick) setSelected(pick.letter);
    }).catch((e) => setError(String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Pre-run diagnostics when the selected drive changes (shows link/SMART early).
  useEffect(() => {
    if (!selected || demoStateFromLocation()) return;
    setPreDiag(null);
    api.diagnostics(selected).then(setPreDiag).catch(() => {});
  }, [selected]);

  // Live re-grade when the marketing text is edited after a run.
  useEffect(() => {
    if (!benchmark || !diagnostics || running || demoStateFromLocation()) return;
    const t = setTimeout(() => {
      api.analyze(blurb, benchmark, diagnostics).then(setVerdict).catch(() => {});
    }, 450);
    return () => clearTimeout(t);
  }, [blurb, benchmark, diagnostics, running]);

  const selectedDrive = useMemo(() => drives.find((d) => d.letter === selected), [drives, selected]);

  function start() {
    if (!selected || running) return;
    setError(""); setBenchmark(null); setVerdict(null);
    setLive({}); setSustainedPoints([]); setPhaseLabel("Starting…");
    setRunning(true);

    cancelRef.current = runBenchmark(
      { letter: selected, depth, blurb, allow_system: selectedDrive?.is_system ?? false },
      (ev: RunEvent) => handleEvent(ev),
    );
  }

  function handleEvent(ev: RunEvent) {
    switch (ev.type) {
      case "phase":
        setPhaseLabel(ev.label);
        break;
      case "diagnostics":
        setDiagnostics(ev.data); setPreDiag(ev.data);
        break;
      case "progress":
        setLive((m) => ({ ...m, [ev.phase]: { pct: ev.pct, mbps: ev.mbps, done: m[ev.phase]?.done ?? false } }));
        break;
      case "sustained_point":
        setSustainedPoints((p) => [...p, { elapsed: ev.elapsed, written_bytes: ev.written_bytes, mbps: ev.mbps }]);
        setLive((m) => ({ ...m, sustained: { pct: m.sustained?.pct ?? 0.5, mbps: ev.mbps, done: false } }));
        break;
      case "result": {
        const iops = typeof ev.iops === "number" ? ev.iops : undefined;
        const mv = typeof ev.mbps === "number" ? ev.mbps : (typeof ev.avg_mbps === "number" ? ev.avg_mbps : 0);
        setLive((m) => ({ ...m, [ev.metric]: { pct: 1, mbps: mv, iops, done: true } }));
        break;
      }
      case "complete":
        setBenchmark(ev.benchmark); setDiagnostics(ev.diagnostics); setVerdict(ev.verdict);
        setRunning(false); setPhaseLabel("");
        break;
      case "error":
        setError(ev.message); setRunning(false); setPhaseLabel("");
        break;
    }
  }

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1><span className="accent">Drive</span>SpeedTest</h1>
          <div className="sub">Honest external-drive profiler — measures the real device, then tells you if it's the drive, the cable, or the port.</div>
        </div>
        <div className="status-chips">
          {status && <Badge kind={status.is_admin ? "ok" : "mute"}>{status.is_admin ? "Elevated" : "Not elevated"}</Badge>}
          {status && <Badge kind={status.smartctl_present ? "ok" : "mute"}>smartctl {status.smartctl_present ? "found" : "absent"}</Badge>}
          {status && <Badge kind="mute">v{status.version}</Badge>}
        </div>
      </header>

      <div className="grid setup">
        <div className="panel">
          <div className="panel-title">1 · Select a drive</div>
          <div className="drive-list">
            {drives.length === 0 && <div className="empty">No drives found.</div>}
            {drives.map((d) => (
              <div key={d.letter} className={`drive ${selected === d.letter ? "selected" : ""}`} onClick={() => setSelected(d.letter)}>
                <div className="letter">{d.letter}</div>
                <div className="meta">
                  <div className="name">{d.model ?? d.label ?? `${d.letter}: drive`}</div>
                  <div className="detail">
                    {d.label ? `${d.label} · ` : ""}{d.filesystem} {d.is_system && <Badge kind="warn">system</Badge>}
                  </div>
                </div>
                <div className="row" style={{ justifyContent: "flex-end" }}>
                  <BusBadge bus={d.bus_type} />
                </div>
                <div className="cap">{humanSize(d.free)} free<br />of {humanSize(d.total)}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="panel">
          <div className="panel-title">2 · Configure & run</div>
          <label className="field">Test depth</label>
          <div className="segment" role="tablist">
            {DEPTHS.map((d) => (
              <button key={d.key} className={depth === d.key ? "active" : ""} onClick={() => setDepth(d.key)}>{d.label}</button>
            ))}
          </div>
          <div className="small" style={{ marginTop: 6 }}>{DEPTHS.find((d) => d.key === depth)?.hint}</div>

          {preDiag && (
            <div style={{ marginTop: 14 }}>
              <div className="kv">
                {preDiag.usb && (selectedDrive?.bus_type ?? "").toUpperCase() === "USB" && (
                  <>
                    <div className="k">USB link</div>
                    <div className="v sans" style={{ fontSize: 12 }}>{preDiag.usb.negotiated}</div>
                  </>
                )}
                <div className="k">TRIM</div>
                <div className="v sans">{preDiag.trim_enabled == null ? "—" : preDiag.trim_enabled ? <Badge kind="ok">on</Badge> : <Badge kind="warn">off</Badge>}</div>
              </div>
              {preDiag.smart && !preDiag.smart.available && preDiag.smart.needs_admin && (
                <div className="banner" style={{ marginTop: 10 }}><span className="b-icon">🔒</span><span>Run as administrator to read SMART health for this drive.</span></div>
              )}
            </div>
          )}

          <div className="row" style={{ marginTop: 16 }}>
            <button className="btn" onClick={start} disabled={running || !selected}>
              {running ? "Running…" : "▶ Run benchmark"}
            </button>
            {selectedDrive?.is_system && <span className="small t-critical">System drive — writes here are risky.</span>}
          </div>
          {error && <div className="banner" style={{ marginTop: 12, borderColor: "#5c2626", background: "#221012", color: "var(--crit)" }}><span className="b-icon">⛔</span><span>{error}</span></div>}
        </div>
      </div>

      {(running || Object.keys(live).length > 0) && !benchmark && (
        <div className="panel" style={{ marginTop: 16 }}>
          <div className="live-phase"><span className="pulse" />{phaseLabel || "Working…"}</div>
          <div className="metric-bars">
            {METRICS.map((m) => {
              const s = live[m.key];
              const val = s ? (m.rand && s.iops ? `${num(s.iops)} IOPS` : `${num(s.mbps)} MB/s`) : "—";
              return (
                <div key={m.key} className={`mbar ${s?.done ? "done" : ""}`}>
                  <div className="lbl">{m.label}</div>
                  <div className="track"><div className="fill" style={{ width: `${s ? (s.done ? 100 : Math.round(s.pct * 100)) : 0}%` }} /></div>
                  <div className="val">{val}</div>
                </div>
              );
            })}
          </div>
          {sustainedPoints.length > 0 && <div className="small" style={{ marginTop: 10 }}>Sustained samples: {sustainedPoints.length} · latest {num(sustainedPoints[sustainedPoints.length - 1].mbps)} MB/s</div>}
        </div>
      )}

      {benchmark && diagnostics && verdict && (
        <Results benchmark={benchmark} diagnostics={diagnostics} verdict={verdict} blurb={blurb} setBlurb={setBlurb} />
      )}

      <footer className="small" style={{ marginTop: 30, textAlign: "center", color: "var(--text-mute)" }}>
        Writes incompressible data with the OS cache bypassed, so numbers reflect the real device. Temp files are cleaned up automatically.
      </footer>
    </div>
  );
}
