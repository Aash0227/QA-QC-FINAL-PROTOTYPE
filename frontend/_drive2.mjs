import { chromium } from "playwright";
const OUT = process.env.SP;
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
const errs = []; p.on("pageerror", e => errs.push("PAGEERROR " + e.message));
p.on("console", m => { if (m.type()==="error") errs.push(m.text()); });
await p.goto("http://localhost:5173/index.html", { waitUntil: "domcontentloaded" });
await p.waitForTimeout(3500);

// expand list fully so .row exists
await p.locator("#list-rows .cat-hdr").first().click(); await p.waitForTimeout(200);
const cats = await p.locator("#list-rows .cat-hdr").allTextContents();
console.log("CATS:", cats.map(s=>s.replace(/\s+/g," ").trim()));
for (const mh of await p.locator("#list-rows .mark-hdr").all()) await mh.click();
await p.waitForTimeout(400);
console.log("list rows expanded:", await p.locator("#list-rows .row").count());
console.log("LEFT LIST pills (distinct):", [...new Set(await p.locator("#list-rows .pill").allTextContents())]);
await p.screenshot({ path: OUT+"/10-list-expanded.png" });

await p.click("#btn-table"); await p.waitForTimeout(500);
// verdict sort proof
const order0 = await p.locator("#results-tbody .verdict-badge").allTextContents();
await p.click('#results-table th[data-k="verdict"]'); await p.waitForTimeout(400);
const o1 = await p.locator("#results-tbody .verdict-badge").allTextContents();
await p.click('#results-table th[data-k="verdict"]'); await p.waitForTimeout(400);
const o2 = await p.locator("#results-tbody .verdict-badge").allTextContents();
const isSorted = a => { const u=[]; for(const x of a) if(u[u.length-1]!==x) u.push(x); return new Set(u).size===u.length; };
console.log("verdict asc grouped?", isSorted(o1), " desc grouped?", isSorted(o2), " asc==desc?", JSON.stringify(o1)===JSON.stringify(o2));
console.log("first 6 asc:", o1.slice(0,6).join(","), "| first 6 desc:", o2.slice(0,6).join(","));
console.log("th attrs:", await p.evaluate(()=>{const t=document.querySelector('#results-table th[data-k=verdict]');return t.className+" dir="+t.dataset.dir;}));
// compare: does a real column sort work?
await p.click('#results-table th[data-k="mark"]'); await p.waitForTimeout(300);
console.log("mark asc first 5:", (await p.locator("#results-tbody tr td:nth-child(1)").allTextContents()).slice(0,5).join(","));

// verdict filter effect on left list
await p.locator(".verdict-bar__item", { hasText: "Needs review" }).click(); await p.waitForTimeout(500);
console.log("FILTER NeedsReview -> table rows:", await p.locator("#results-tbody tr").count(),
            "| left list rows:", await p.locator("#list-rows .row").count(),
            "| left cat headers:", (await p.locator("#list-rows .cat-hdr").allTextContents()).map(s=>s.replace(/\s+/g," ").trim()));
console.log("LEFT pills under NeedsReview filter:", [...new Set(await p.locator("#list-rows .pill").allTextContents())]);
await p.screenshot({ path: OUT+"/11-needsreview-filter.png" });

// now the trap: close table panel while filter active
console.log("table panel class before close:", await p.getAttribute("#table-panel","class"));
await p.evaluate(()=>document.querySelector("#btn-table-close").click());
await p.waitForTimeout(400);
console.log("TRAP after close: panel class:", await p.getAttribute("#table-panel","class"),
  "| verdictbar visible:", await p.locator(".verdict-bar").isVisible(),
  "| left rows still filtered:", await p.locator("#list-rows .row").count(),
  "| store.verdictFilter:", await p.evaluate(()=>window.__s?.verdictFilter ?? "n/a"));
console.log("left list innerText:", (await p.textContent("#list-rows")).replace(/\s+/g," ").slice(0,200));
console.log("hdr-stats while filtered:", await p.textContent("#hdr-stats"));
await p.screenshot({ path: OUT+"/12-trap-closed.png" });

// does Escape or anything clear it?
await p.keyboard.press("Escape"); await p.waitForTimeout(300);
console.log("after Escape left rows:", await p.locator("#list-rows .row").count());
// does re-running match (loadAll) reset verdictFilter? simulate by re-open panel & check selected state persists
await p.click("#btn-table"); await p.waitForTimeout(400);
console.log("selected item still pressed after reopen:", await p.locator(".verdict-bar__item[aria-pressed=true]").count());

// focus ring
await p.locator(".verdict-bar__item").first().focus();
console.log("FOCUS:", JSON.stringify(await p.evaluate(()=>{const e=document.activeElement,c=getComputedStyle(e);return{cls:e.className,outline:c.outline,outlineOffset:c.outlineOffset,boxShadow:c.boxShadow};})));
// tab reachability of segments in the track
console.log("track role/aria:", await p.evaluate(()=>{const t=document.querySelector(".verdict-bar__track");return t.getAttribute("role")+" | "+t.getAttribute("aria-label");}));

// overflow
console.log("OVERFLOW:", JSON.stringify(await p.evaluate(()=>{
 const w=document.querySelector("#table-wrap"),t=document.querySelector("#results-table");
 const tds=[...document.querySelectorAll("#results-tbody tr td:nth-child(8)")];
 const heights=tds.map(td=>Math.round(td.getBoundingClientRect().height));
 return {wrapClientW:w.clientWidth,tableScrollW:t.scrollWidth,hOverflow:t.scrollWidth>w.clientWidth,
  overflowX:getComputedStyle(w).overflowX, maxRowH:Math.max(...heights), minRowH:Math.min(...heights),
  ws:tds[0]&&getComputedStyle(tds[0]).whiteSpace, tableLayout:getComputedStyle(t).tableLayout};})));
console.log("BACKDROPS:", JSON.stringify(await p.evaluate(()=>[...document.querySelectorAll("*")].filter(e=>getComputedStyle(e).backdropFilter!=="none").map(e=>(e.id||e.className)+" => "+getComputedStyle(e).backdropFilter))));

for (const w of [1100, 900, 700, 375]) {
  await p.setViewportSize({width:w,height:850}); await p.waitForTimeout(500);
  console.log(`W=${w}`, JSON.stringify(await p.evaluate(()=>({docScrollW:document.documentElement.scrollWidth, inner:innerWidth,
   hdrOverflow:document.querySelector("header").scrollWidth>document.querySelector("header").clientWidth,
   leftW:Math.round(document.querySelector("#left").getBoundingClientRect().width),
   legendH:Math.round(document.querySelector(".verdict-bar__legend")?.getBoundingClientRect().height||0)}))));
  await p.screenshot({path:OUT+`/w-${w}.png`});
}
console.log("ERRORS:", JSON.stringify(errs.slice(0,10)));
await b.close();
