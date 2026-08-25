// Mirrors the backend's dataclass/dict contract (see backend/*.py).

export interface Drive {
  letter: string;
  label: string | null;
  filesystem: string | null;
  total: number;
  free: number;
  disk_number: number | null;
  model: string | null;
  bus_type: string | null;
  media_type: string | null;
  firmware: string | null;
  health: string | null;
  serial: string | null;
  is_system: boolean;
}

export interface UsbLink {
  matched: boolean;
  negotiated: string;
  ceiling_mbps: number | null;
  operating_superspeed: boolean;
  superspeed_plus: boolean;
  inferred: boolean;
  vid: number | null;
  pid: number | null;
  bcd_usb: number | null;
  controllers: string[];
  best_controller_tier: string;
  note: string;
}

export interface SmartAttr { name: string; value: number | string | null; }

export interface Smart {
  available: boolean;
  source: string;
  needs_admin: boolean;
  temperature_c: number | null;
  power_on_hours: number | null;
  percent_used: number | null;
  reallocated_sectors: number | null;
  pending_sectors: number | null;
  read_errors: number | null;
  write_errors: number | null;
  health: string | null;
  attributes: SmartAttr[];
  message: string;
}

export interface Diagnostics {
  drive: Drive | null;
  usb: UsbLink | null;
  smart: Smart | null;
  trim_enabled: boolean | null;
  allocation_unit: number | null;
  filesystem: string | null;
  notes: string[];
}

export interface RandomResult { iops: number; mbps: number; latency_us: number; ops: number; }
export interface SustainedPoint { elapsed: number; written_bytes: number; mbps: number; }
export interface Sustained { points: SustainedPoint[]; peak_mbps: number; avg_mbps: number; }

export interface Benchmark {
  method: string;
  seq_write_mbps: number;
  seq_read_mbps: number;
  rand_write: RandomResult | null;
  rand_read: RandomResult | null;
  sustained: Sustained | null;
  bytes_written: number;
  config_label: string;
}

export interface ClaimRow {
  metric: string;
  claimed_mbps: number | null;
  measured_mbps: number | null;
  pct_of_claim: number | null;
  status: "met" | "partial" | "unmet" | "n/a";
}

export interface FeatureCheck {
  feature: string;
  claimed: boolean;
  observed: string;
  status: "ok" | "warning" | "unknown";
  note: string;
}

export type Severity = "critical" | "warning" | "info" | "ok";

export interface Finding {
  title: string;
  severity: Severity;
  confidence: "high" | "medium" | "low";
  detail: string;
  recommendations: string[];
}

export interface Verdict {
  summary: string;
  claim_rows: ClaimRow[];
  feature_checks: FeatureCheck[];
  findings: Finding[];
  link_ceiling_mbps: number | null;
  link_tier: string | null;
}

export interface Status {
  version: string;
  is_admin: boolean;
  smartctl_present: boolean;
  default_blurb: string;
  busy: boolean;
}

// WebSocket event union
export type RunEvent =
  | { type: "phase"; phase: string; label: string }
  | { type: "progress"; phase: string; pct: number; mbps: number }
  | { type: "sustained_point"; elapsed: number; written_bytes: number; mbps: number }
  | { type: "result"; metric: string; [k: string]: unknown }
  | { type: "diagnostics"; data: Diagnostics }
  | { type: "done" }
  | { type: "complete"; benchmark: Benchmark; diagnostics: Diagnostics; verdict: Verdict }
  | { type: "error"; message: string };
