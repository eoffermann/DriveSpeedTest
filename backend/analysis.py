"""Turn measurements + diagnostics + a marketing blurb into a verdict.

Two jobs:
  1. Grade each marketing claim against what we actually measured.
  2. Point at the most likely bottleneck -- USB link, cable/handshake fallback,
     SLC-cache exhaustion, thermal, or the drive/system itself -- with concrete
     next steps, so the user knows whether to swap a cable, change ports, or stop
     blaming the drive.

The key idea that makes this trustworthy: the USB link imposes a hard throughput
ceiling. If that ceiling is below the advertised speed, no drive on earth reaches
the claim over that connection -- so we can attribute the shortfall to the
connection with confidence, independent of the drive's own quality.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import List, Optional

# Default text is the user's SSK blurb so the UI shows a worked example on load.
DEFAULT_BLURB = (
    "High-speed transfer: Read speeds up to 2100MB/s, write speed up to 1800MB/s, "
    "20 times faster than traditional hard drives. Quickly transfer high-resolution "
    "photos, videos and large files. S.M.A.R.T monitoring keeps track of solid state "
    "external hard drive health. TRIM technology ensures stable write speeds and "
    "extends drive lifespan. Adopting TLC NAND, it maintains stable write speeds "
    "above 1000MB/s without slowdown."
)

# USB link tiers -> realistic usable ceiling (decimal MB/s).
_GEN1 = 450.0     # 5 Gbps
_GEN2 = 1050.0    # 10 Gbps
_GEN2X2 = 2100.0  # 20 Gbps


@dataclass
class ClaimRow:
    metric: str
    claimed_mbps: Optional[float]
    measured_mbps: Optional[float]
    pct_of_claim: Optional[float]
    status: str          # met | partial | unmet | n/a


@dataclass
class FeatureCheck:
    feature: str
    claimed: bool
    observed: str        # yes | no | unknown
    status: str          # ok | warning | unknown
    note: str = ""


@dataclass
class Finding:
    title: str
    severity: str        # critical | warning | info | ok
    confidence: str      # high | medium | low
    detail: str
    recommendations: List[str] = field(default_factory=list)


@dataclass
class Verdict:
    summary: str = ""
    claim_rows: List[ClaimRow] = field(default_factory=list)
    feature_checks: List[FeatureCheck] = field(default_factory=list)
    findings: List[Finding] = field(default_factory=list)
    link_ceiling_mbps: Optional[float] = None
    link_tier: Optional[str] = None


# --- blurb parsing -----------------------------------------------------------
def parse_blurb(text: str) -> dict:
    t = text or ""
    def near(keyword: str) -> Optional[float]:
        # a number followed by MB/s within ~40 chars after the keyword
        m = re.search(keyword + r"[^.]{0,40}?(\d{2,5})\s*MB/?s", t, re.IGNORECASE)
        return float(m.group(1)) if m else None

    read = near(r"read")
    write = near(r"write")
    sustained = None
    m = re.search(r"(?:stable|sustained|maintain\w*)[^.]{0,60}?(?:above\s*)?(\d{3,4})\s*MB/?s",
                  t, re.IGNORECASE)
    if not m:
        m = re.search(r"above\s*(\d{3,4})\s*MB/?s", t, re.IGNORECASE)
    if m:
        sustained = float(m.group(1))
    return {
        "read": read,
        "write": write,
        "sustained": sustained,
        "tlc": bool(re.search(r"\bTLC\b", t, re.IGNORECASE)),
        "smart": bool(re.search(r"S\.?M\.?A\.?R\.?T", t, re.IGNORECASE)),
        "trim": bool(re.search(r"\bTRIM\b", t, re.IGNORECASE)),
    }


def _status(measured: Optional[float], claimed: Optional[float]) -> str:
    if claimed is None:
        return "n/a"
    if measured is None:
        return "n/a"
    pct = measured / claimed
    if pct >= 0.9:
        return "met"
    if pct >= 0.6:
        return "partial"
    return "unmet"


def _link_needed(mbps: float) -> str:
    if mbps > _GEN2:
        return "20 Gbps (USB 3.2 Gen2x2 / USB4)"
    if mbps > _GEN1:
        return "10 Gbps (USB 3.2 Gen2)"
    if mbps > 42:
        return "5 Gbps (USB 3.0)"
    return "USB 2.0"


def _effective_ceiling(usb: dict, measured_peak: float) -> (Optional[float], str):
    """Link ceiling, refined upward if the drive empirically beat the inferred tier."""
    if not usb or not usb.get("matched"):
        return None, usb.get("best_controller_tier", "Unknown") if usb else "Unknown"
    ceiling = usb.get("ceiling_mbps")
    tier = usb.get("negotiated", "Unknown")
    # Measurement is a hard floor on the true link speed: if we moved more than the
    # inferred ceiling, the link must actually be a faster tier -- promote it.
    if ceiling and measured_peak > ceiling * 1.05:
        if measured_peak > _GEN2:
            return _GEN2X2, "USB 3.2 Gen2x2 (20 Gbps, confirmed by throughput)"
        if measured_peak > _GEN1:
            return _GEN2, "USB 3.2 Gen2 (10 Gbps, confirmed by throughput)"
    return ceiling, tier


def _detect_cliff(points: List[dict]) -> Optional[dict]:
    """Find an SLC-cache cliff: a sustained drop well below the early peak."""
    if not points or len(points) < 4:
        return None
    speeds = [p["mbps"] for p in points]
    peak = max(speeds)
    tail = speeds[max(1, int(len(speeds) * 0.75)):]
    tail_avg = sum(tail) / len(tail)
    if peak > 0 and tail_avg < peak * 0.6:
        # first index where speed drops below 70% of peak and stays lowish
        cliff_at = None
        for i, s in enumerate(speeds):
            if s < peak * 0.7:
                cliff_at = points[i]
                break
        return {"peak": peak, "tail_avg": round(tail_avg, 1),
                "cliff_at_bytes": cliff_at["written_bytes"] if cliff_at else None}
    return {"peak": peak, "tail_avg": round(tail_avg, 1), "cliff_at_bytes": None}


# --- main --------------------------------------------------------------------
def analyze(blurb: str, bench: dict, diag: dict) -> Verdict:
    claims = parse_blurb(blurb)
    v = Verdict()
    bench = bench or {}
    diag = diag or {}
    usb = diag.get("usb") or {}
    drive = diag.get("drive") or {}
    smart = diag.get("smart") or {}
    is_usb = (drive.get("bus_type") or "").upper() == "USB"

    seq_read = bench.get("seq_read_mbps")
    seq_write = bench.get("seq_write_mbps")
    sustained = bench.get("sustained") or {}
    sust_points = sustained.get("points") or []
    measured_peak = max([x for x in [seq_read, seq_write, sustained.get("peak_mbps")] if x] or [0])

    ceiling, tier = _effective_ceiling(usb, measured_peak)
    v.link_ceiling_mbps = ceiling
    v.link_tier = tier

    # --- claim grading -------------------------------------------------------
    def row(metric, claimed, measured):
        pct = round(measured / claimed * 100, 1) if (claimed and measured) else None
        return ClaimRow(metric, claimed, round(measured, 1) if measured else None,
                        pct, _status(measured, claimed))

    v.claim_rows = [
        row("Sequential read", claims["read"], seq_read),
        row("Sequential write", claims["write"], seq_write),
        row("Sustained write", claims["sustained"],
            sustained.get("avg_mbps") if sust_points else None),
    ]

    # --- feature checks ------------------------------------------------------
    trim = diag.get("trim_enabled")
    v.feature_checks.append(FeatureCheck(
        "TRIM", claims["trim"],
        "yes" if trim else ("no" if trim is False else "unknown"),
        "ok" if trim else ("warning" if trim is False else "unknown"),
        "" if trim else "TRIM appears disabled system-wide; enable it to keep write speeds stable." if trim is False else "Could not read TRIM state."))
    smart_available = smart.get("available")
    v.feature_checks.append(FeatureCheck(
        "S.M.A.R.T monitoring", claims["smart"],
        "yes" if smart_available else "unknown",
        "ok" if smart_available else "unknown",
        "" if smart_available else (smart.get("message") or "SMART not readable for this drive.")))
    v.feature_checks.append(FeatureCheck(
        "TLC NAND", claims["tlc"], "unknown", "unknown",
        "NAND type isn't reported by the OS; the sustained-write curve is the real test of the 'no slowdown' promise."))

    # --- findings (ranked) ---------------------------------------------------
    findings: List[Finding] = []
    top_claim = max([c for c in [claims["read"], claims["write"]] if c] or [0])

    # 1) Fell back to a slower USB mode than the port supports.
    if is_usb and usb.get("matched") and not usb.get("operating_superspeed"):
        findings.append(Finding(
            "Drive negotiated a slow USB mode",
            "critical", "high",
            f"The drive linked at {usb.get('negotiated')}, but your host controllers "
            f"support {usb.get('best_controller_tier')}. A USB 2.0/low fallback usually "
            f"means a bad cable, a USB 2.0-only cable, a damaged connector, or a front-panel/hub port.",
            ["Swap in a cable rated for the drive's speed (USB 3.2 Gen2/Gen2x2).",
             "Plug directly into a rear-panel USB port, not a hub or front-panel header.",
             "Try a different port; reseat both ends of the cable."]))

    # 2) The link ceiling is below the advertised speed -> connection-limited.
    elif is_usb and ceiling and top_claim and ceiling < top_claim * 0.9:
        findings.append(Finding(
            "The USB connection caps you below the advertised speed",
            "warning", "high",
            f"Your link tops out around {ceiling:.0f} MB/s ({tier}). The advertised "
            f"{top_claim:.0f} MB/s needs a {_link_needed(top_claim)} connection. Even a "
            f"flawless drive cannot exceed the connection, so this shortfall is the "
            f"port/cable/host — not the flash.",
            [f"Use a {_link_needed(top_claim)} port and a matching certified cable.",
             "On desktops, that's usually a rear USB-C port wired to Gen2x2/USB4.",
             "Confirm the drive's own port is USB-C 20 Gbps, not a 10 Gbps type-A."]))

    # 3) Measured well below the link ceiling -> a second, drive/system-side limit.
    if ceiling and seq_read and seq_read < ceiling * 0.7 and (not is_usb or usb.get("operating_superspeed")):
        findings.append(Finding(
            "Throughput is below what the link allows",
            "warning", "medium",
            f"Sequential read {seq_read:.0f} MB/s is well under the ~{ceiling:.0f} MB/s the "
            f"link can carry, so something beyond the connection is limiting it: a nearly "
            f"full drive, thermal throttling, background activity, or firmware.",
            ["Ensure the drive has plenty of free space (SSDs slow when near full).",
             "Let the drive cool and retest; check SMART temperature.",
             "Close apps doing background I/O; update the drive's firmware."]))

    # 4) SLC-cache cliff on sustained writes.
    if sust_points:
        cliff = _detect_cliff(sust_points)
        if cliff and cliff.get("cliff_at_bytes"):
            gb = cliff["cliff_at_bytes"] / (1024 ** 3)
            detail = (f"Write speed held near {cliff['peak']:.0f} MB/s, then dropped to "
                      f"~{cliff['tail_avg']:.0f} MB/s after about {gb:.1f} GiB — the SLC "
                      f"write cache filling up and exposing the slower native TLC speed.")
            claimed_sust = claims["sustained"]
            sev = "warning"
            if claimed_sust and cliff["tail_avg"] < claimed_sust * 0.9:
                detail += (f" That is below the advertised 'stable {claimed_sust:.0f} MB/s "
                           f"without slowdown' — the claim does not hold for long writes.")
                sev = "critical"
            findings.append(Finding("Sustained write speed drops after the SLC cache fills",
                                    sev, "high", detail,
                                    ["Expect the lower rate for very large single transfers.",
                                     "For big sustained jobs, a drive with a larger/native cache helps."]))
        elif cliff:
            findings.append(Finding(
                "Sustained write stayed stable",
                "ok", "high",
                f"Across the sustained test, write speed held near {cliff['tail_avg']:.0f} MB/s "
                f"with no SLC-cache cliff in the range tested.",
                ["To probe deeper, run the sustained test with a larger size."]))

    # 5) SMART temperature.
    temp = smart.get("temperature_c") if smart.get("available") else None
    if temp and temp >= 70:
        findings.append(Finding(
            "Drive is running hot", "warning", "medium",
            f"SMART reports {temp:.0f} °C. External SSDs throttle when hot, which can cap "
            f"sustained speeds.",
            ["Improve airflow / add a heatsink; avoid enclosed spaces during long transfers."]))

    # 6) Everything met.
    if not findings and all(r.status in ("met", "n/a") for r in v.claim_rows):
        findings.append(Finding("Drive meets its advertised performance", "ok", "high",
                                "Measured speeds are within 10% of the marketing claims and no "
                                "connection or health issues were detected.", []))

    v.findings = findings

    # --- one-line summary ----------------------------------------------------
    crit = [f for f in findings if f.severity == "critical"]
    warn = [f for f in findings if f.severity == "warning"]
    if crit:
        v.summary = crit[0].title + "."
    elif warn:
        v.summary = warn[0].title + "."
    elif findings:
        v.summary = findings[0].title + "."
    else:
        v.summary = "Benchmark complete."
    return v


def to_dict(v: Verdict) -> dict:
    return asdict(v)
