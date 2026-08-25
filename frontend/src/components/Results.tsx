import { useState } from "react";
import type { Benchmark, Diagnostics, Verdict } from "../types";
import { humanSize, mbps, num, pct } from "../format";
import { Badge, BusBadge, SummaryBanner, severityIcon } from "./ui";
import { SustainedChart } from "./SustainedChart";

type Tab = "speed" | "marketing" | "diagnostics" | "smart" | "diagnosis";

const STATUS_LABEL: Record<string, string> = {
  met: "Met", partial: "Partial", unmet: "Not met", "n/a": "No claim",
};

export function Results({
  benchmark, diagnostics, verdict, blurb, setBlurb,
}: {
  benchmark: Benchmark;
  diagnostics: Diagnostics;
  verdict: Verdict;
  blurb: string;
  setBlurb: (s: string) => void;
}) {
  const [tab, setTab] = useState<Tab>("diagnosis");
  const topSeverity = verdict.findings[0]?.severity ?? "info";

  return (
    <div className="panel" style={{ marginTop: 16 }}>
      <SummaryBanner
        severity={topSeverity}
        title={verdict.summary}
        detail={verdict.link_tier ? `Link: ${verdict.link_tier}${verdict.link_ceiling_mbps ? ` · ceiling ≈ ${Math.round(verdict.link_ceiling_mbps)} MB/s` : ""} · benchmark method: ${benchmark.method}` : undefined}
      />

      <div className="tabs">
        <button className={tab === "diagnosis" ? "active" : ""} onClick={() => setTab("diagnosis")}>Diagnosis</button>
        <button className={tab === "speed" ? "active" : ""} onClick={() => setTab("speed")}>Speed</button>
        <button className={tab === "marketing" ? "active" : ""} onClick={() => setTab("marketing")}>Marketing claims</button>
        <button className={tab === "diagnostics" ? "active" : ""} onClick={() => setTab("diagnostics")}>Drive & connection</button>
        <button className={tab === "smart" ? "active" : ""} onClick={() => setTab("smart")}>S.M.A.R.T</button>
        <div className="spacer" />
        <ExportButton benchmark={benchmark} diagnostics={diagnostics} verdict={verdict} />
      </div>

      {tab === "diagnosis" && <DiagnosisTab benchmark={benchmark} verdict={verdict} />}
      {tab === "speed" && <SpeedTab benchmark={benchmark} />}
      {tab === "marketing" && <MarketingTab verdict={verdict} blurb={blurb} setBlurb={setBlurb} />}
      {tab === "diagnostics" && <DiagnosticsTab diagnostics={diagnostics} />}
      {tab === "smart" && <SmartTab diagnostics={diagnostics} />}
    </div>
  );
}

function DiagnosisTab({ benchmark, verdict }: { benchmark: Benchmark; verdict: Verdict }) {
  const sustained = benchmark.sustained;
  const claimSust = verdict.claim_rows.find((r) => r.metric === "Sustained write")?.claimed_mbps ?? null;
  return (
    <div>
      {verdict.findings.length === 0 && <div className="empty">No findings.</div>}
      {verdict.findings.map((f, i) => (
        <div key={i} className={`finding ${f.severity}`}>
          <div className="fhead">
            <span className="fi">{severityIcon[f.severity]}</span>
            <span className="ftitle">{f.title}</span>
            <Badge kind={f.severity === "ok" ? "ok" : f.severity === "critical" ? "crit" : f.severity === "warning" ? "warn" : "mute"}>
              {f.confidence} confidence
            </Badge>
          </div>
          <div className="fdetail">{f.detail}</div>
          {f.recommendations.length > 0 && (
            <ul>{f.recommendations.map((r, j) => <li key={j}>{r}</li>)}</ul>
          )}
        </div>
      ))}
      {sustained && sustained.points.length > 0 && (
        <div className="panel" style={{ marginTop: 8, background: "var(--panel-2)" }}>
          <div className="panel-title">Sustained write — SLC cache behavior</div>
          <SustainedChart points={sustained.points} claimMbps={claimSust} ceilingMbps={verdict.link_ceiling_mbps} />
        </div>
      )}
    </div>
  );
}

function SpeedTab({ benchmark: b }: { benchmark: Benchmark }) {
  return (
    <div>
      <div className="stat-cards">
        <div className="stat read"><div className="sl">Seq. read</div><div className="sv">{num(b.seq_read_mbps)}</div><div className="su">MB/s</div></div>
        <div className="stat write"><div className="sl">Seq. write</div><div className="sv">{num(b.seq_write_mbps)}</div><div className="su">MB/s</div></div>
        <div className="stat"><div className="sl">Rand 4K read</div><div className="sv">{num(b.rand_read?.iops)}</div><div className="su">IOPS · {num(b.rand_read?.latency_us, 0)} µs</div></div>
        <div className="stat"><div className="sl">Rand 4K write</div><div className="sv">{num(b.rand_write?.iops)}</div><div className="su">IOPS · {num(b.rand_write?.latency_us, 0)} µs</div></div>
      </div>
      <table>
        <thead><tr><th>Test</th><th className="num">Throughput</th><th className="num">IOPS</th><th className="num">Avg latency</th></tr></thead>
        <tbody>
          <tr><td>Sequential read</td><td className="num">{mbps(b.seq_read_mbps)}</td><td className="num">—</td><td className="num">—</td></tr>
          <tr><td>Sequential write</td><td className="num">{mbps(b.seq_write_mbps)}</td><td className="num">—</td><td className="num">—</td></tr>
          <tr><td>Random 4K read (QD1)</td><td className="num">{mbps(b.rand_read?.mbps)}</td><td className="num">{num(b.rand_read?.iops)}</td><td className="num">{num(b.rand_read?.latency_us)} µs</td></tr>
          <tr><td>Random 4K write (QD1)</td><td className="num">{mbps(b.rand_write?.mbps)}</td><td className="num">{num(b.rand_write?.iops)}</td><td className="num">{num(b.rand_write?.latency_us)} µs</td></tr>
          {b.sustained && <tr><td>Sustained write (avg)</td><td className="num">{mbps(b.sustained.avg_mbps)}</td><td className="num">—</td><td className="num">peak {num(b.sustained.peak_mbps)}</td></tr>}
        </tbody>
      </table>
      <p className="small" style={{ marginTop: 10 }}>
        Measured with cache-bypassing, incompressible I/O ({b.method}) — {humanSize(b.bytes_written)} written. These reflect the real device, not the OS cache.
      </p>
    </div>
  );
}

function MarketingTab({ verdict, blurb, setBlurb }: { verdict: Verdict; blurb: string; setBlurb: (s: string) => void }) {
  return (
    <div>
      <label className="field">Marketing text — edit and the grading updates live</label>
      <textarea value={blurb} onChange={(e) => setBlurb(e.target.value)} />
      <table style={{ marginTop: 14 }}>
        <thead><tr><th>Claim</th><th className="num">Advertised</th><th className="num">Measured</th><th className="num">% of claim</th><th>Verdict</th></tr></thead>
        <tbody>
          {verdict.claim_rows.map((r, i) => (
            <tr key={i}>
              <td>{r.metric}</td>
              <td className="num">{mbps(r.claimed_mbps)}</td>
              <td className="num">{mbps(r.measured_mbps)}</td>
              <td className="num">{pct(r.pct_of_claim)}</td>
              <td><span className={`t-${r.status}`} style={{ fontWeight: 600 }}>{STATUS_LABEL[r.status]}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="feature-list" style={{ marginTop: 14 }}>
        {verdict.feature_checks.map((f, i) => (
          <div key={i} className="feature">
            <span className="fi">{f.status === "ok" ? "✅" : f.status === "warning" ? "⚠️" : "❔"}</span>
            <div>
              <div className="fname">{f.feature} {f.claimed && <Badge kind="mute">advertised</Badge>}</div>
              {f.note && <div className="fnote">{f.note}</div>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function DiagnosticsTab({ diagnostics: d }: { diagnostics: Diagnostics }) {
  const drive = d.drive;
  const usb = d.usb;
  return (
    <div className="grid two">
      <div className="panel" style={{ background: "var(--panel-2)" }}>
        <div className="panel-title">Drive identity</div>
        <div className="kv">
          <div className="k">Model</div><div className="v sans">{drive?.model ?? "—"}</div>
          <div className="k">Bus</div><div className="v sans"><BusBadge bus={drive?.bus_type ?? null} /> {drive?.media_type}</div>
          <div className="k">Firmware</div><div className="v">{drive?.firmware ?? "—"}</div>
          <div className="k">Serial</div><div className="v">{drive?.serial ?? "—"}</div>
          <div className="k">Capacity</div><div className="v">{drive ? humanSize(drive.total) : "—"}</div>
          <div className="k">Free</div><div className="v">{drive ? humanSize(drive.free) : "—"}</div>
          <div className="k">Filesystem</div><div className="v">{d.filesystem ?? "—"}{d.allocation_unit ? ` · ${d.allocation_unit}B clusters` : ""}</div>
          <div className="k">Health</div><div className="v sans">{drive?.health === "Healthy" ? <Badge kind="ok"><span className="dot" />Healthy</Badge> : (drive?.health ?? "—")}</div>
          <div className="k">TRIM</div><div className="v sans">{d.trim_enabled == null ? "—" : d.trim_enabled ? <Badge kind="ok">Enabled</Badge> : <Badge kind="warn">Disabled</Badge>}</div>
        </div>
      </div>
      <div className="panel" style={{ background: "var(--panel-2)" }}>
        <div className="panel-title">USB connection</div>
        {usb && (drive?.bus_type ?? "").toUpperCase() === "USB" ? (
          <div className="kv">
            <div className="k">Negotiated link</div><div className="v sans">{usb.negotiated}{usb.inferred && <> <Badge kind="mute">inferred</Badge></>}</div>
            <div className="k">Link ceiling</div><div className="v">{usb.ceiling_mbps ? `≈ ${Math.round(usb.ceiling_mbps)} MB/s` : "—"}</div>
            <div className="k">SuperSpeed</div><div className="v sans">{usb.operating_superspeed ? <Badge kind="ok">Yes</Badge> : <Badge kind="warn">No — USB 2.0/low</Badge>}</div>
            <div className="k">Device VID:PID</div><div className="v">{usb.vid != null ? `${usb.vid.toString(16).padStart(4, "0")}:${(usb.pid ?? 0).toString(16).padStart(4, "0")}` : "—"}</div>
            <div className="k">Host controllers</div>
            <div className="v sans" style={{ fontSize: 12 }}>{usb.controllers.length ? usb.controllers.map((c, i) => <div key={i}>{c}</div>) : "—"}</div>
            {usb.note && <><div className="k">Note</div><div className="v sans" style={{ fontSize: 12, color: "var(--text-mute)" }}>{usb.note}</div></>}
          </div>
        ) : (
          <div className="empty">Not a USB drive — connection diagnostics apply to external USB drives.</div>
        )}
      </div>
    </div>
  );
}

function SmartTab({ diagnostics: d }: { diagnostics: Diagnostics }) {
  const s = d.smart;
  if (!s) return <div className="empty">No SMART data.</div>;
  if (!s.available) {
    return (
      <div>
        <div className="banner"><span className="b-icon">🔒</span><span>{s.message}</span></div>
        <p className="small" style={{ marginTop: 12 }}>
          Source attempted: <span className="mono">{s.source}</span>. {s.needs_admin ? "Re-launch DriveSpeedTest as administrator" : "Install smartmontools"} to read health attributes through the USB bridge.
        </p>
      </div>
    );
  }
  return (
    <div>
      <div className="stat-cards">
        <div className="stat"><div className="sl">Temperature</div><div className="sv">{s.temperature_c != null ? Math.round(s.temperature_c) : "—"}</div><div className="su">°C</div></div>
        <div className="stat"><div className="sl">Power-on</div><div className="sv">{num(s.power_on_hours)}</div><div className="su">hours</div></div>
        <div className="stat"><div className="sl">Endurance used</div><div className="sv">{s.percent_used != null ? num(s.percent_used) : "—"}</div><div className="su">%</div></div>
        <div className="stat"><div className="sl">Health</div><div className="sv" style={{ fontSize: 18 }}>{s.health ?? "—"}</div><div className="su">{s.source}</div></div>
      </div>
      <table>
        <thead><tr><th>Attribute</th><th className="num">Value</th></tr></thead>
        <tbody>
          {s.attributes.map((a, i) => (
            <tr key={i}><td>{a.name}</td><td className="num">{a.value ?? "—"}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ExportButton({ benchmark, diagnostics, verdict }: { benchmark: Benchmark; diagnostics: Diagnostics; verdict: Verdict }) {
  const download = (name: string, text: string, mime: string) => {
    const blob = new Blob([text], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = name; a.click();
    URL.revokeObjectURL(url);
  };
  const exportJSON = () => download(
    `drivespeedtest-${diagnostics.drive?.letter ?? "drive"}.json`,
    JSON.stringify({ benchmark, diagnostics, verdict }, null, 2),
    "application/json");
  const exportReport = () => {
    const d = diagnostics.drive;
    const lines = [
      `DriveSpeedTest report — ${d?.model ?? "drive"} (${d?.letter}:)`,
      `Bus: ${d?.bus_type} · ${d?.media_type} · firmware ${d?.firmware}`,
      diagnostics.usb ? `USB link: ${diagnostics.usb.negotiated} (ceiling ≈ ${diagnostics.usb.ceiling_mbps} MB/s)` : "",
      "",
      `VERDICT: ${verdict.summary}`,
      "",
      "Marketing claims:",
      ...verdict.claim_rows.map((r) => `  ${r.metric}: claimed ${r.claimed_mbps ?? "—"} / measured ${r.measured_mbps ?? "—"} MB/s (${r.status})`),
      "",
      "Findings:",
      ...verdict.findings.flatMap((f) => [
        `  [${f.severity}] ${f.title}`,
        `    ${f.detail}`,
        ...f.recommendations.map((r) => `      - ${r}`),
      ]),
    ];
    download(`drivespeedtest-${d?.letter ?? "drive"}.txt`, lines.join("\n"), "text/plain");
  };
  return (
    <div className="row">
      <button className="btn ghost" onClick={exportReport}>Export report</button>
      <button className="btn ghost" onClick={exportJSON}>JSON</button>
    </div>
  );
}
