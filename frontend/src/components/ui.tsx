import type { Severity } from "../types";

export function Badge({
  children, kind = "mute",
}: { children: React.ReactNode; kind?: string }) {
  return <span className={`badge ${kind}`}>{children}</span>;
}

export function BusBadge({ bus }: { bus: string | null }) {
  if (!bus) return null;
  const k = bus.toUpperCase() === "USB" ? "usb" : bus.toUpperCase() === "NVME" ? "nvme" : "mute";
  return <Badge kind={k}>{bus}</Badge>;
}

export const severityIcon: Record<Severity, string> = {
  critical: "⛔",
  warning: "⚠️",
  info: "ℹ️",
  ok: "✅",
};

export function SummaryBanner({ severity, title, detail }: { severity: Severity; title: string; detail?: string }) {
  return (
    <div className={`summary ${severity}`}>
      <div className="icon">{severityIcon[severity]}</div>
      <div className="txt">
        <h2>{title}</h2>
        {detail && <p>{detail}</p>}
      </div>
    </div>
  );
}
