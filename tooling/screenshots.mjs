// Generate documentation screenshots of every part of the app with Playwright.
//
// It launches the real server (which serves the built frontend) and drives the
// gated demo mode (?demo=...) so every panel renders with realistic, deterministic
// data -- no physical drive or benchmark run required.
//
//   cd tooling && npm install && npx playwright install chromium && npm run screenshots
//
// Output: docs/screenshots/*.png
//
// Env overrides: DST_URL (use an already-running server), DST_PY (python path).

import { spawn } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import fs from "node:fs";
import { chromium } from "playwright";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(__dirname, "..");
// Use a dedicated port so a stray instance on the default 8760 can't hijack us.
const PORT = process.env.DST_PORT || "8791";
const BASE = process.env.DST_URL || `http://127.0.0.1:${PORT}`;
const PY = process.env.DST_PY ||
  path.join(repo, ".venv", "Scripts", process.platform === "win32" ? "python.exe" : "python");
const outDir = path.join(repo, "docs", "screenshots");
fs.mkdirSync(outDir, { recursive: true });

async function waitUp(timeoutMs = 25000) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    try {
      const r = await fetch(BASE + "/api/status");
      if (r.ok) return;
    } catch { /* not up yet */ }
    await sleep(400);
  }
  throw new Error(`server at ${BASE} did not become ready`);
}

let server = null;
if (!process.env.DST_URL) {
  console.log(`[screenshots] starting server on port ${PORT}: ${PY} run.py`);
  server = spawn(PY, ["run.py", "--no-browser", "--no-admin"],
    { cwd: repo, stdio: "inherit", env: { ...process.env, DST_PORT: String(PORT) } });
}

let browser;
try {
  await waitUp();
  browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 960 }, deviceScaleFactor: 2 });

  const shot = async (name) => {
    await sleep(450); // let transitions/chart settle
    await page.screenshot({ path: path.join(outDir, name), fullPage: true });
    console.log("[screenshots] captured", name);
  };
  const openTab = async (label) => {
    await page.locator(".tabs button", { hasText: label }).first().click();
    await sleep(350);
  };

  // 1) Setup: drive picker + config + connection preview
  await page.goto(`${BASE}/?demo=setup`, { waitUntil: "load" });
  await page.waitForSelector(".drive.selected");
  await shot("01-overview.png");

  // 2) Live benchmark: streaming metric bars
  await page.goto(`${BASE}/?demo=live`, { waitUntil: "load" });
  await page.waitForSelector(".metric-bars");
  await shot("02-live-benchmark.png");

  // 3) Results — Diagnosis tab (summary + ranked findings + sustained chart)
  await page.goto(`${BASE}/?demo=results`, { waitUntil: "load" });
  await page.waitForSelector(".summary");
  await page.waitForSelector(".chart-wrap svg");
  await shot("03-diagnosis.png");

  // 4-7) Remaining result tabs
  await openTab("Speed");
  await shot("04-speed.png");
  await openTab("Marketing claims");
  await shot("05-marketing.png");
  await openTab("Drive & connection");
  await shot("06-connection.png");
  await openTab("S.M.A.R.T");
  await shot("07-smart.png");

  console.log("[screenshots] done ->", outDir);
} finally {
  if (browser) await browser.close();
  if (server) server.kill();
}
