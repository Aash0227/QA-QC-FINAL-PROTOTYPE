import { chromium } from "playwright";
const OUT=process.env.SP;
const b=await chromium.launch(); const p=await b.newPage({viewport:{width:1440,height:900}});
await p.goto("http://localhost:5173/index.html",{waitUntil:"domcontentloaded"}); await p.waitForTimeout(3500);
await p.click("#btn-table"); await p.waitForTimeout(600);
console.log("rows before search:", await p.locator("#results-tbody tr").count());
await p.click("#search"); await p.type("#search","zzzzzzz",{delay:60}); await p.waitForTimeout(1200);
console.log("store.filters.search value in DOM:", await p.inputValue("#search"));
console.log("rows after search zzz:", await p.locator("#results-tbody tr").count(),
  "| left:", (await p.textContent("#list-rows")).replace(/\s+/g," ").trim().slice(0,80));
await p.screenshot({path:OUT+"/40-search-empty.png"});
// real search
await p.fill("#search",""); await p.waitForTimeout(500);
await p.click("#search"); await p.type("#search","SW-2",{delay:60}); await p.waitForTimeout(1200);
console.log("rows for SW-2:", await p.locator("#results-tbody tr").count());
await p.fill("#search",""); await p.waitForTimeout(600);

// runs drawer
await p.click("#btn-runs"); await p.waitForTimeout(1500);
console.log("runs drawer visible:", await p.isVisible("#runs"), "| body:", (await p.textContent("#runs-body")).replace(/\s+/g," ").trim().slice(0,200));
await p.screenshot({path:OUT+"/41-runs-drawer.png"});
await p.click("#btn-runs"); await p.waitForTimeout(400);

// review drawer
await p.click("#btn-review"); await p.waitForTimeout(1500);
console.log("review drawer:", (await p.textContent("#rev-body")).replace(/\s+/g," ").trim().slice(0,300));
console.log("review verdict badges:", await p.locator("#rev-body .verdict-badge").count());
await p.screenshot({path:OUT+"/42-review-drawer.png"});
await p.click("#btn-review"); await p.waitForTimeout(400);

// contrast sample of verdict badge on ground
await p.click("#btn-table"); await p.waitForTimeout(500);
console.log("badge styles:", JSON.stringify(await p.evaluate(()=>[...document.querySelectorAll("#results-tbody .verdict-badge")].slice(0,3).map(e=>({v:e.dataset.verdict,color:getComputedStyle(e).color,bg:getComputedStyle(e).backgroundColor,fs:getComputedStyle(e).fontSize})))));
console.log("accents:", JSON.stringify(await p.evaluate(()=>{const s=getComputedStyle(document.documentElement);return ["--signal","--color-primary","--accent","--fg","--muted","--dim","--bg"].map(k=>k+"="+s.getPropertyValue(k).trim());})));
console.log("font sizes in table area:", JSON.stringify(await p.evaluate(()=>{const s=new Set();document.querySelectorAll("#table-panel *").forEach(e=>s.add(getComputedStyle(e).fontSize));return [...s];})));
await b.close();
