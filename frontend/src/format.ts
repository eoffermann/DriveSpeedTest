export const GiB = 1024 ** 3;

export function bytesToGiB(n: number): string {
  return (n / GiB).toFixed(n >= GiB ? 1 : 2);
}

export function humanSize(n: number): string {
  if (n >= 1024 ** 4) return (n / 1024 ** 4).toFixed(2) + " TiB";
  if (n >= GiB) return (n / GiB).toFixed(1) + " GiB";
  if (n >= 1024 ** 2) return (n / 1024 ** 2).toFixed(0) + " MiB";
  return (n / 1024).toFixed(0) + " KiB";
}

export function mbps(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: 0 }) + " MB/s";
}

export function num(n: number | null | undefined, digits = 0): string {
  if (n == null) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}

export function pct(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toFixed(0) + "%";
}
