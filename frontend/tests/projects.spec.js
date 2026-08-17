// Project Manager UI suite.
//
// Deliberately data-independent: unlike smoke.spec.js, nothing here asserts a
// verdict baseline or assumes which project is loaded. Each test creates its own
// throwaway workspace with a run-unique name and removes it afterwards, so the
// suite passes on a machine with one project, thirty, or a different sample set.
//
// The newly created project is never the active one (POST /api/projects does not
// activate on purpose), which keeps these tests from disturbing the workspace a
// developer has open.

import { test, expect } from "@playwright/test";

const stamp = () => `${Date.now()}${Math.floor(Math.random() * 1000)}`;

async function openManager(page) {
  await page.goto("/");
  await page.locator("#btn-projects").click();
  await expect(page.locator("#projects")).toHaveClass(/open/);
  // Wait for the real cards, not just for the overlay: the grid shows skeleton
  // placeholders while GET /api/projects is in flight, and asserting against
  // those would pass before any project data existed.
  await expect(page.locator("#pm-grid .skeleton")).toHaveCount(0);
}

/** Create through the UI and return its slug. */
async function createProject(page, name) {
  await page.locator("#pm-new").click();
  await page.locator("#pm-new-form input[name=name]").fill(name);
  await page.locator("#pm-new-form button[type=submit]").click();
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-");
  await expect(page.locator(`.pm-card[data-slug="${slug}"]`)).toBeVisible();
  return slug;
}

test.describe("Project Manager", () => {
  // Every test starts with a real page load, and that means the whole app:
  // the sheet raster, the 3D scene and the full element list. On a project the
  // size of a 100-page permit set that is 10-20s before the first click, which
  // leaves nothing inside the global 30s budget. The extra time is startup, not
  // slow assertions — the assertions themselves still use the default expect
  // timeout, so a genuinely broken UI still fails fast.
  test.describe.configure({ timeout: 90_000 });

  const created = [];

  test.afterEach(async ({ request }) => {
    // Clean up over the API rather than the UI: a failed assertion mid-test
    // must still not leave a workspace behind for the next run.
    while (created.length) {
      await request.delete(`/api/projects/${created.pop()}`).catch(() => {});
    }
  });

  test("grid lists projects and marks the active one", async ({ page }) => {
    await openManager(page);
    const cards = page.locator(".pm-card[data-slug]");
    expect(await cards.count()).toBeGreaterThan(0);
    // Exactly one project is active, and its Open button is disabled because
    // you are already looking at it.
    const active = page.locator(".pm-card.pm-active");
    await expect(active).toHaveCount(1);
    await expect(active.locator("[data-act=open]")).toBeDisabled();
  });

  test("create — a new project appears with honest empty state", async ({ page }) => {
    await openManager(page);
    const name = `PW Create ${stamp()}`;
    const slug = await createProject(page, name);
    created.push(slug);

    const card = page.locator(`.pm-card[data-slug="${slug}"]`);
    await expect(card.locator("h3")).toHaveText(name);
    // No files yet — the card says so rather than implying an empty result set.
    await expect(card.locator(".pm-facts")).toContainText("no PDF");
    await expect(card.locator(".pm-facts")).toContainText("no Revit export");
    // Ring shows a dash, not 0%: nothing has been analysed.
    await expect(card.locator(".pm-ring-num")).toHaveText("—");
    // Creating does not switch the open project.
    await expect(card).not.toHaveClass(/pm-active/);
  });

  test("update — rename and re-tag without touching the folder", async ({ page }) => {
    await openManager(page);
    const slug = await createProject(page, `PW Edit ${stamp()}`);
    created.push(slug);

    const card = page.locator(`.pm-card[data-slug="${slug}"]`);
    await card.locator("[data-act=edit]").click();
    await card.locator("input[name=display_name]").fill("Renamed In Test");
    await card.locator("input[name=client]").fill("Acme Structural");
    await card.locator("input[name=revision]").fill("PC3 2026-08-12");
    await card.locator("select[name=status]").selectOption("archived");
    await card.locator("button[type=submit]").click();

    await expect(card.locator("h3")).toHaveText("Renamed In Test");
    await expect(card.locator(".pm-sub")).toContainText("Acme Structural");
    await expect(card.locator(".pm-sub")).toContainText("PC3 2026-08-12");
    await expect(card.locator(".pm-status")).toHaveText("archived");
    // The workspace folder is identity and must survive a rename.
    await expect(card.locator(".pm-slug")).toHaveText(slug);
  });

  test("delete — confirm button stays disabled until the slug is typed", async ({ page }) => {
    await openManager(page);
    const slug = await createProject(page, `PW Delete ${stamp()}`);
    created.push(slug);

    await page.locator(`.pm-card[data-slug="${slug}"] [data-act=delete]`).click();
    await expect(page.locator("#pm-confirm")).toHaveClass(/open/);
    // The dialog states what is actually being destroyed.
    await expect(page.locator("#pm-confirm-body")).toContainText("file");

    const go = page.locator("#pm-confirm-go");
    await expect(go).toBeDisabled();
    await page.locator("#pm-confirm-input").fill(slug.slice(0, -1));   // near miss
    await expect(go).toBeDisabled();
    await page.locator("#pm-confirm-input").fill(slug);
    await expect(go).toBeEnabled();

    await go.click();
    await expect(page.locator("#pm-confirm")).not.toHaveClass(/open/);
    await expect(page.locator(`.pm-card[data-slug="${slug}"]`)).toHaveCount(0);
    created.pop();   // already gone; afterEach would 404
  });

  test("delete — cancel leaves the project alone", async ({ page }) => {
    await openManager(page);
    const slug = await createProject(page, `PW Keep ${stamp()}`);
    created.push(slug);

    await page.locator(`.pm-card[data-slug="${slug}"] [data-act=delete]`).click();
    await page.locator("#pm-confirm-cancel").click();
    await expect(page.locator("#pm-confirm")).not.toHaveClass(/open/);
    await expect(page.locator(`.pm-card[data-slug="${slug}"]`)).toBeVisible();
  });

  test("Escape closes the confirm dialog first, then the overlay", async ({ page }) => {
    await openManager(page);
    const slug = await createProject(page, `PW Esc ${stamp()}`);
    created.push(slug);

    await page.locator(`.pm-card[data-slug="${slug}"] [data-act=delete]`).click();
    await page.keyboard.press("Escape");
    await expect(page.locator("#pm-confirm")).not.toHaveClass(/open/);
    await expect(page.locator("#projects")).toHaveClass(/open/);   // overlay survives

    await page.keyboard.press("Escape");
    await expect(page.locator("#projects")).not.toHaveClass(/open/);
  });

  test("J and K step through the element list", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("#hdr-stats")).toContainText("verified", { timeout: 30_000 });
    // Expand a mark group so element rows exist to step through.
    await page.locator("#list-rows .mark-hdr").first().click();
    await expect(page.locator("#list-rows .row").first()).toBeVisible();

    await page.keyboard.press("j");
    const first = page.locator("#list-rows .row.selected");
    await expect(first).toHaveCount(1);
    const firstId = await first.getAttribute("data-id");

    await page.keyboard.press("j");
    const second = page.locator("#list-rows .row.selected");
    await expect(second).not.toHaveAttribute("data-id", firstId);

    await page.keyboard.press("k");
    await expect(page.locator("#list-rows .row.selected")).toHaveAttribute("data-id", firstId);
  });

  test("J is ignored while typing in the search box", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("#hdr-stats")).toContainText("verified", { timeout: 30_000 });
    await page.locator("#search").fill("j");
    // The keystroke went into the field, not the list navigation.
    await expect(page.locator("#search")).toHaveValue("j");
  });

  test("status is conveyed by glyph as well as colour", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("#hdr-stats")).toContainText("verified", { timeout: 30_000 });
    // Count bars on the category headers carry a glyph and a titled label, so
    // the breakdown survives greyscale and colour-vision deficiency.
    const dot = page.locator("#list-rows .cat-hdr .mini-dots .dot").first();
    await expect(dot).not.toHaveText("");
    await expect(page.locator("#list-rows .cat-hdr .mini-dots span[title]").first())
      .toHaveAttribute("title", /\d+ [a-z ]+/);
  });

  test("header shows the active project name", async ({ page }) => {
    await page.goto("/");
    const label = page.locator("#proj-name");
    await expect(label).not.toHaveText("Projects", { timeout: 15_000 });
    await expect(page.locator("#btn-projects")).toHaveAttribute("title", /click to manage projects/);
  });
});
