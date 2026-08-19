import { chromium } from "playwright";
const OUT = process.env.SP;
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
const errs = [];
p.on("console", m => { if (m.type() === "error") errs.push(m.text()); });
p.on("pageerror", e => errs.push("PAGEERROR " + e.message));
await p.goto("http://localhost:5173/index.html", { waitUntil: "domcontentloaded" });
await p.waitForTimeout(3000);
console.log("HDR STATS:", await p.textContent("#hdr-stats"));
console.log("REV COUNT:", await p.textContent("#rev-count"));
console.log("table-panel hidden?", await p.getAttribute("#table-panel", "class"));
console.log("scope-banner visible?", await p.isVisible("#scope-banner"));
console.log("verdict-bar count on load:", await p.locator(".verdict-bar").count(), "visible:", await p.locator(".verdict-bar").isVisible().catch(()=>false));
await p.screenshot({ path: OUT + "/01-load-desktop.png", fullPage: false });

// open results table
await p.click("#btn-table");
await p.waitForTimeout(800);
console.log("after All results: verdictbar visible:", await p.locator(".verdict-bar").isVisible());
console.log("legend items:", await p.locator(".verdict-bar__item").allTextContents());
console.log("rows in table:", await p.locator("#results-tbody tr").count());
console.log("rows in list:", await p.locator("#list-rows .row").count());
await p.screenshot({ path: OUT + "/02-results-table.png" });

// click Mismatch segment
const seg = p.locator(".verdict-bar__item", { hasText: "Mismatch" });
await seg.click();
await p.waitForTimeout(500);
console.log("AFTER FILTER Mismatch -> table rows:", await p.locator("#results-tbody tr").count(),
  "list rows:", await p.locator("#list-rows .row").count());
console.log("aria-pressed:", await seg.getAttribute("aria-pressed"));
const badges = await p.locator("#results-tbody .verdict-badge").allTextContents();
console.log("distinct badges after filter:", [...new Set(badges)]);
const listPills = await p.locator("#list-rows .pill").allTextContents();
console.log("distinct LEFT LIST pills after Mismatch filter:", [...new Set(listPills)]);
await p.screenshot({ path: OUT + "/03-filter-mismatch.png" });

// toggle off
await seg.click(); await p.waitForTimeout(400);
console.log("after re-click table rows:", await p.locator("#results-tbody tr").count());

// Verdict column sort test
const before = await p.locator("#results-tbody tr td:nth-child(1)").allTextContents();
await p.click('#results-table th[data-k="verdict"]');
await p.waitForTimeout(400);
const after = await p.locator("#results-tbody tr td:nth-child(1)").allTextContents();
console.log("VERDICT SORT changed order?", JSON.stringify(before) !== JSON.stringify(after));
const vAfter = await p.locator("#results-tbody .verdict-badge").allTextContents();
console.log("verdict col order first 12:", vAfter.slice(0,12).join("|"));
console.log("th sorted class:", await p.getAttribute('#results-table th[data-k="verdict"]', "class"));
await p.screenshot({ path: OUT + "/04-verdict-sort.png" });

// stuck-empty trap: filter Needs review + a conflicting status, then close panel
await p.locator(".verdict-bar__item", { hasText: "Needs review" }).click();
await p.waitForTimeout(300);
console.log("NeedsReview list rows:", await p.locator("#list-rows .row").count());
await p.selectOption("#status-filter", "MATCH");
await p.waitForTimeout(400);
console.log("NeedsReview + status=MATCH -> list rows:", await p.locator("#list-rows .row").count(),
   "list text:", (await p.textContent("#list-rows")).slice(0,120));
await p.click("#btn-table-close");
await p.waitForTimeout(400);
console.log("TRAP: table panel closed. verdict bar visible?", await p.locator(".verdict-bar").isVisible());
console.log("TRAP: any visible control mentioning verdict?", await p.locator(".verdict-bar__item:visible").count());
await p.screenshot({ path: OUT + "/05-stuck-empty.png" });

// does reload reset? (it's a page reload so yes) -- test in-app reload via Match? too slow. Test store persistence across loadAll:
await p.click("#btn-table"); await p.waitForTimeout(300);
await p.selectOption("#status-filter", "");
await p.waitForTimeout(300);

// keyboard focus on verdict buttons
await p.locator(".verdict-bar__item").first().focus();
const fv = await p.evaluate(() => {
  const el = document.activeElement;
  const cs = getComputedStyle(el);
  return { cls: el.className, outline: cs.outlineStyle + " " + cs.outlineWidth + " " + cs.outlineColor, boxShadow: cs.boxShadow };
});
console.log("FOCUS STYLE:", JSON.stringify(fv));
await p.screenshot({ path: OUT + "/06-focus.png" });

// long reason overflow
const overflow = await p.evaluate(() => {
  const tds = [...document.querySelectorAll("#results-tbody tr td:nth-child(8)")];
  const w = document.querySelector("#table-wrap");
  const t = document.querySelector("#results-table");
  const longest = tds.map(td => td.textContent.length).sort((a,b)=>b-a)[0];
  return { wrapW: w.clientWidth, tableW: t.scrollWidth, wrapScrollW: w.scrollWidth, hOverflow: t.scrollWidth > w.clientWidth, longestReason: longest,
           tdWhiteSpace: tds[0] && getComputedStyle(tds[0]).whiteSpace, tdH: tds[0]?.getBoundingClientRect().height };
});
console.log("TABLE OVERFLOW:", JSON.stringify(overflow));

// nested backdrop filters
const blurs = await p.evaluate(() => [...document.querySelectorAll("*")]
  .filter(e => getComputedStyle(e).backdropFilter !== "none")
  .map(e => (e.id||e.className)+" :: "+getComputedStyle(e).backdropFilter).slice(0,20));
console.log("BACKDROP-FILTER ELEMENTS:", JSON.stringify(blurs, null, 1));

// narrow viewport
await p.setViewportSize({ width: 900, height: 800 }); await p.waitForTimeout(600);
await p.screenshot({ path: OUT + "/07-narrow-900.png" });
await p.setViewportSize({ width: 600, height: 800 }); await p.waitForTimeout(600);
await p.screenshot({ path: OUT + "/08-narrow-600.png" });
const nar = await p.evaluate(() => ({
  bodyScrollW: document.body.scrollWidth, inner: window.innerWidth,
  legendWraps: document.querySelector(".verdict-bar__legend")?.getBoundingClientRect().height,
  headerScrollW: document.querySelector("header")?.scrollWidth,
  headerClientW: document.querySelector("header")?.clientWidth,
}));
console.log("NARROW:", JSON.stringify(nar));
await p.setViewportSize({ width: 375, height: 812 }); await p.waitForTimeout(600);
await p.screenshot({ path: OUT + "/09-mobile-375.png" });
console.log("375 body scrollW:", await p.evaluate(()=>document.body.scrollWidth));

console.log("CONSOLE ERRORS:", JSON.stringify(errs.slice(0,15), null, 1));
await b.close();
