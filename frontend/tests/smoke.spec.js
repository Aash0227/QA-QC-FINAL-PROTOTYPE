// QA-QC webapp smoke suite (production-plan §9).
// The flows exercised manually all session, scripted: app load, 3-pane select
// sync, table sort/filter, the benchmark wizard propose->approve (state left
// idle, Stamp never clicked — it writes the real PDF), the chat drawer (mocked
// /api/chat so no live LLM key is needed), and drawer independence.
//
// The Madera project ships loaded, so MATCH=107 is asserted directly against
// the running backend — the standing gate baked into the browser suite.

import { test, expect } from "@playwright/test";

const RESET = "/api/benchmark-workflow/reset";

async function gotoLoaded(page) {
  await page.goto("/");
  // Header stats populate from /api/elements once data lands.
  await expect(page.locator("#hdr-stats")).toContainText("verified", { timeout: 15_000 });
}

// The five demoted controls live inside a closed <details> now, and Playwright
// refuses to click a node that isn't visible — open the ⚙ popover first.
const openAdvanced = (page) => page.locator("#adv-menu > summary").click();

test.describe("QA-QC webapp smoke", () => {
  test("app load — header shows 106 verified", async ({ page }) => {
    await gotoLoaded(page);
    // MATCH baseline (Madera): 106 (was 107). The leader-anchor snap
    // (leader_anchor.py, 2026-07-24) moved holdown callouts onto their
    // device dots: 4 previously human-accepted mismatches became natural
    // MATCHes and one borderline row shifted — verified device-by-device
    // on 2026-07-27 (review accepts redundant, reject still honored).
    await expect(page.locator("#hdr-stats")).toContainText("106 verified");
  });

  test("3-pane select sync — list click drives pdf + inspector", async ({ page }) => {
    await gotoLoaded(page);
    // Rows live under a collapsed category > mark tree; expand the first mark
    // group (the default-open category always has one) to reveal element rows.
    await page.locator("#list-rows .mark-hdr").first().click();
    const row = page.locator("#list-rows .row").first();
    await expect(row).toBeVisible();
    await row.click();
    // list reacts: the clicked row is marked selected.
    await expect(row).toHaveClass(/selected/);
    // pdf pane reacts: the overlay switches to isolation mode on any selection.
    await expect(page.locator("#overlay")).toHaveClass(/iso/);
    // inspector reacts: the body is populated with the element block even
    // though the drawer itself stays closed over the 3D pane (so assert the
    // content is present, not on-screen visible).
    await expect(page.locator("#insp-body .status-pill")).toHaveCount(1);
    await expect(page.locator("#insp-body")).toContainText("Category");
  });

  test("results table — opens, sorts, and filters", async ({ page }) => {
    await gotoLoaded(page);
    await page.locator("#btn-table").click();
    await expect(page.locator("#table-panel")).not.toHaveClass(/hidden/);
    const rows = page.locator("#results-tbody tr[data-id]");
    const before = await rows.count();
    expect(before).toBeGreaterThan(1);

    // sort: clicking the Mark header marks it as the active sort column.
    const markTh = page.locator('#results-table thead th[data-k="mark"]');
    await markTh.click();
    await expect(markTh).toHaveClass(/sorted/);

    // filter: the list search box feeds the same store filter the table reads,
    // so a specific mark narrows the table rows.
    const firstMark = (await rows.first().locator("td").first().innerText()).trim();
    await page.locator("#search").fill(firstMark);
    await expect
      .poll(async () => rows.count())
      .toBeLessThanOrEqual(before);
    await expect(rows.first().locator("td").first()).toContainText(firstMark);
  });

  test("benchmark wizard — propose then approve (no stamp)", async ({ page, request }) => {
    await request.post(RESET, { data: { actor: "playwright" } });
    await gotoLoaded(page);
    await openAdvanced(page);
    await page.locator("#btn-autopilot").click();
    await expect(page.locator("#bmwizard")).toHaveClass(/open/);

    // idle -> propose
    await page.locator("#bm-propose").click();
    // awaiting_pdf_approval: the approval card + a proposal table appear.
    await expect(page.locator("#bm-approve")).toBeVisible({ timeout: 15_000 });
    // …and the same gate surfaces as a banner above the main content, so an
    // auto-benchmark from upload is approvable without opening this wizard.
    await expect(page.locator("#bm-banner")).toContainText("Approve to continue");

    // approve the PDF gate -> stamping. We stop here: the Stamp button writes
    // the real PDF, so it is deliberately never clicked.
    await page.locator("#bm-approve").click();
    await expect(page.locator("#bm-stamp")).toBeVisible({ timeout: 15_000 });
    await expect(page.locator("#bm-approve")).toHaveCount(0);

    // Server-side confirmation the gate advanced to stamping.
    const wf = await (await request.get("/api/benchmark-workflow")).json();
    expect(wf.state).toBe("stamping");

    // leave the workflow idle for the next run.
    await request.post(RESET, { data: { actor: "playwright" } });
  });

  test("chat drawer — mocked /api/chat renders a count card", async ({ page }) => {
    // Canned agent reply so the suite never depends on the live LLM key.
    await page.route("**/api/chat", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          reply: "There are 107 hold-downs matched.",
          blocks: [
            { type: "count_card", total: 107, label: "hold-downs",
              by_category: { holdown: 107 } },
          ],
          ui_actions: [],
        }),
      }),
    );
    await gotoLoaded(page);
    await page.locator("#btn-chat").click();
    await expect(page.locator("#chat")).toHaveClass(/open/);

    await page.locator("#chat-input").fill("how many holdowns?");
    await page.locator("#chat-send").click();

    await expect(page.locator("#chat-log")).toContainText("107 hold-downs matched");
    // the structured count_card block renders with its big number.
    await expect(page.locator("#chat-log .chat-card .chat-card-num")).toHaveText("107");
  });

  test("drawer independence — chat and wizard coexist", async ({ page, request }) => {
    await request.post(RESET, { data: { actor: "playwright" } });
    await page.route("**/api/chat", (route) =>
      route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ reply: "hi", blocks: [], ui_actions: [] }) }));
    await gotoLoaded(page);

    // open both regions.
    await page.locator("#btn-chat").click();
    await expect(page.locator("#chat")).toHaveClass(/open/);
    await openAdvanced(page);
    await page.locator("#btn-autopilot").click();
    await expect(page.locator("#bmwizard")).toHaveClass(/open/);
    // opening the wizard must not close the chat drawer (independent regions).
    await expect(page.locator("#chat")).toHaveClass(/open/);

    // closing the chat drawer leaves the wizard open.
    await page.locator('#chat [data-close="chat"]').click();
    await expect(page.locator("#chat")).not.toHaveClass(/open/);
    await expect(page.locator("#bmwizard")).toHaveClass(/open/);

    // closing the wizard works independently.
    await page.locator("#bm-close").click();
    await expect(page.locator("#bmwizard")).not.toHaveClass(/open/);
  });

  // Revit-live §1 — the three new surfaces render off mocked bridge responses,
  // so this passes with or without a live Revit connector attached.
  test("Revit ID lookup drawer renders the live lookup in plain English", async ({ page }) => {
    await page.route("**/api/revit/status", (route) =>
      route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ connected: true, reason: "", model_title: "Madera.rvt" }) }));
    await page.route("**/api/revit/selection", (route) =>
      route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ ok: true, element_ids: [884211] }) }));
    // one-call flow: "Use current Revit selection" now hits /selected-element
    await page.route("**/api/revit/selected-element**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({
          ok: true, source: "revit_mcp",
          found: true, connected: true, element_id: 884211, live_point: [12.5, 40.25],
          assembly: { id: "rev_asm_007", mark_candidate: "H2", center_point: [12.4, 40.2] },
          device: { id: "dev_h2_3", status: "LOCATION_MISMATCH", distance_ft: 3.4,
                    reason: "offset beyond gate", mark: "H2", sheets: ["S2.1"], appearances: 2 },
          analysis: { distance_ft: 3.4, direction: "north-east", systematic: true,
                      aligned_peers: 5, peer_count: 7, finding: "Shifted with its neighbours.",
                      suggestion: "lean-accept" },
          plain_english: "This hold-down sits 3.4 ft north-east of where the drawing shows it.",
        }) }));
    await page.route("**/api/revit/lookup/**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({
          found: true, connected: true, element_id: 884211, live_point: [12.5, 40.25],
          assembly: { id: "rev_asm_007", mark_candidate: "H2", center_point: [12.4, 40.2] },
          device: { id: "dev_h2_3", status: "LOCATION_MISMATCH", distance_ft: 3.4,
                    reason: "offset beyond gate", mark: "H2", sheets: ["S2.1"], appearances: 2 },
          analysis: { distance_ft: 3.4, direction: "north-east", systematic: true,
                      aligned_peers: 5, peer_count: 7, finding: "Shifted with its neighbours.",
                      suggestion: "lean-accept" },
          plain_english: "This hold-down sits 3.4 ft north-east of where the drawing shows it.",
        }) }));
    // The lookup drawer talks only to the bridge — no project data needed.
    await page.goto("/");

    await openAdvanced(page);
    await page.locator("#btn-revit-lookup").click();
    await expect(page.locator("#revitlookup")).toHaveClass(/open/);
    await expect(page.locator("#rl-status")).toContainText("Madera.rvt");

    // "use current Revit selection" fills the input and looks the id up.
    await page.locator("#rl-selection").click();
    await expect(page.locator("#rl-input")).toHaveValue("884211");
    const body = page.locator("#rl-body");
    await expect(body).toContainText("Element 884211");
    await expect(body.locator(".status-pill")).toContainText("LOCATION MISMATCH");
    await expect(body).toContainText("rev_asm_007");
    await expect(body).toContainText("Offset is 3.4 ft to the north-east");
    // the 2 ft gate is stated, not assumed.
    await expect(body).toContainText("MATCH gate is 2 ft");
    await expect(body).toContainText("5 of 7 other mismatches");
    // suggestion is translated to human words, never echoed raw.
    await expect(body).toContainText("Likely false alarm");
    await expect(body).not.toContainText("lean-accept");
  });
});
