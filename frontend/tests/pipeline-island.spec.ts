/**
 * Pipeline Island Playwright e2e — verifies the React component renders,
 * SSE-driven step updates work, AI call fires after stage.done, and the
 * technical details panel opens.
 *
 * Run:  npm run test -- tests/pipeline-island.spec.ts
 * The backend (:8077) must be running with a project that has pipeline data
 * (dogwood-lane is fine). SSE events are consumed from the live stream;
 * this spec does NOT mock them (real backend integration).
 */
import { test, expect } from "@playwright/test";

const BASE = "http://127.0.0.1:8077";
const URL = `${BASE}/pipeline.html`;

test.describe("Pipeline Island", () => {
  test("renders with 7 stages from the live backend", async ({ page }) => {
    await page.goto(URL, { waitUntil: "networkidle" });

    // Header
    await expect(page.locator("img[alt='Livio']")).toBeVisible({ timeout: 10000 });
    await expect(page.locator("text=Pipeline")).toBeVisible();

    // 7 stage rows (Reading drawings … Building the review queue)
    const stages = [
      "Reading drawings", "Reading model", "Locating the plan",
      "Preparing drawing data", "Aligning coordinates", "Comparing",
      "Building the review queue",
    ];
    for (const title of stages) {
      await expect(page.getByRole("button", { name: title })).toBeVisible({ timeout: 5000 });
    }

    // Debug panel exists
    await expect(page.getByText(/raw SSE events/)).toBeVisible();
  });

  test("Run pipeline triggers SSE events and shows live indicator", async ({ page }) => {
    await page.goto(URL, { waitUntil: "networkidle" });

    // Click Run
    await page.getByRole("button", { name: "Run" }).click();

    // The header should show "Pipeline running…" briefly (or "complete" if instant-skip)
    await expect(page.getByText(/live/)).toBeVisible({ timeout: 10000 });
  });

  test("Force re-run updates the run ID", async ({ page }) => {
    await page.goto(URL, { waitUntil: "networkidle" });

    const before = await page.getByText(/T\d{6}/).first().textContent();

    await page.getByRole("button", { name: "Force" }).click();
    await page.waitForTimeout(3000);

    const after = await page.getByText(/T\d{6}/).first().textContent();
    // The run_id should change after a force re-run
    expect(after).not.toBe(before);
  });

  test("AI explanation appears after a stage completes", async ({ page }) => {
    await page.goto(URL, { waitUntil: "networkidle" });

    // Force re-run so stages freshly complete
    await page.getByRole("button", { name: "Force" }).click();

    // Wait for at least one "AI:" explanation to appear
    const ai = page.getByText(/AI:/).first();
    await ai.waitFor({ timeout: 30000 });

    // Click the first stage row to expand
    await page.getByRole("button", { name: "Reading drawings" }).click();

    // The expanded panel should contain the AI text
    await expect(ai).toBeVisible();
  });

  test("Technical details panel opens and shows expected keys", async ({ page }) => {
    await page.goto(URL, { waitUntil: "networkidle" });

    // Click the first "Technical details" toggle
    await page.getByText("Technical details").first().click();

    // Should show stage name + artifact + timestamps
    await expect(page.getByText(/stage:/)).toBeVisible({ timeout: 3000 });
    await expect(page.getByText(/artifact:/)).toBeVisible();
    await expect(page.getByText(/started:/)).toBeVisible();
    await expect(page.getByText(/completed:/)).toBeVisible();
  });

  test("Grid pause toggle works", async ({ page }) => {
    await page.goto(URL, { waitUntil: "networkidle" });

    const btn = page.getByRole("button", { name: /Grid|Pause grid/ });
    await expect(btn).toBeVisible();

    await btn.click();
    await expect(btn).toContainText(/Grid paused|Play/);
  });

  test("Debug: raw SSE events panel shows events after a run", async ({ page }) => {
    await page.goto(URL, { waitUntil: "networkidle" });

    await page.getByRole("button", { name: "Run" }).click();
    await page.waitForTimeout(4000);

    const debug = page.getByText(/raw SSE events/);
    await expect(debug).toBeVisible();
    const text = await debug.textContent();
    // Should show more than 0 events after a run
    expect(text).not.toBe("Debug: raw SSE events (0)");
  });
});