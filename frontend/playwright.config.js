// Playwright config for the QA-QC smoke suite (production-plan §9).
// Starts the FastAPI backend (which also serves the frontend StaticFiles) on
// port 8017 and drives it in headless Chromium. reuseExistingServer lets a
// backend you already have running locally be reused instead of double-booting.
// ponytail: one browser, one webServer — add more projects only if a real
// cross-browser bug shows up.
import { defineConfig, devices } from "@playwright/test";

const PORT = 8017;
const BASE = `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: "./tests",
  // Builds frontend/dist before the backend boots, so the suite always exercises
  // the working tree rather than a stale bundle. QAQC_SKIP_BUILD=1 opts out.
  globalSetup: "./tests/global-setup.js",
  // 30s was sized for the Madera sample. A full permit set (100+ pages, a 3D
  // scene and a few hundred elements) can take 15-20s just to reach first
  // interaction, which left real assertions racing the test budget and failing
  // as timeouts. The per-assertion expect timeout below is unchanged, so a
  // genuinely broken UI still fails in 10s — only startup gets the extra room.
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: BASE,
    trace: "on-first-retry",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: {
    // Backend vendors PIL/fitz for CPython 3.11 — bare `python` may resolve to
    // a different interpreter (e.g. a venv) that lacks fitz. Use the py launcher
    // (works on any machine with Python 3.11 installed via the installer).
    command: "py -3.11 -m uvicorn app.main:app --port 8017",
    cwd: "../backend",
    url: `${BASE}/api/health`,
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
