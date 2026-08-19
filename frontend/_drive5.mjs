import { chromium } from "playwright";
const OUT=process.env.SP;
const b=await chromium.launch(); const p=await b.newPage({viewport:{width:1440,height:900}});
await p.goto("http://localhost:5173/index.html",{waitUntil:"domcontentloaded"}); await p.waitForTimeout(3500);
await p.click("#btn-table"); await p.waitForTimeout(600);
console.log("rows before search:", await p.locator("#results-tbody tr").count());
await p.click("#search"); await p.type("#search","zzzzzzz",{delay:60}); await p.waitForTimeout(1500);
console.log("input value:", await p.inputValue("#search"),
  "| rows after:", await p.locator("#results-tbody tr").count(),
  "| tbody text:", (await p.textContent("#results-tbody")).replace(/\s+/g," ").trim().slice(0,60),
  "| left:", (await p.textContent("#list-rows")).replace(/\s+/g," ").trim().slice(0,60));
await p.screenshot({path:OUT+"/40-search-empty.png"});
await p.fill("#search",""); await p.waitForTimeout(600);
await p.click("#search"); await p.type("#search","SW-2",{delay:60}); await p.waitForTimeout(1200);
console.log("rows for SW-2:", await p.locator("#results-tbody tr").count());
await p.fill("#search",""); await p.waitForTimeout(800);

// open adv menu then runs
await p.click("#adv-menu summary"); await p.waitForTimeout(300);
await p.click("#btn-runs"); await p.waitForTimeout(2000);
console.log("RUNS drawer:", (await p.textContent("#runs-body")).replace(/\s+/g," ").trim().slice(0,250));
await p.screenshot({path:OUT+"/41-runs-drawer.png"});
await p.evaluate(()=>document.querySelector("#btn-runs").click()); await p.waitForTimeout(400);

await p.click("#btn-review"); await p.waitForTimeout(2000);
console.log("REVIEW drawer:", (await p.textContent("#rev-body")).replace(/\s+/g," ").trim().slice(0,320));
console.log("review verdict badges:", await p.locator("#rev-body .verdict-badge").count());
console.log("rev-count badge:", await p.textContent("#rev-count"));
await p.screenshot({path:OUT+"/42-review-drawer.png"});
await p.evaluate(()=>document.querySelector("#btn-review").click()); await p.waitForTimeout(400);

await p.click("#btn-table"); await p.waitForTimeout(600);
console.log("badge styles:", JSON.stringify(await p.evaluate(()=>[...document.querySelectorAll("#results-tbody .verdict-badge")].slice(0,3).map(e=>({v:e.dataset.verdict,color:getComputedStyle(e).color,bg:getComputedStyle(e).backgroundColor})))));
console.log("tokens:", JSON.stringify(await p.evaluate(()=>{const s=getComputedStyle(document.documentElement);return ["--signal","--color-primary","--accent","--fg","--muted","--dim","--bg","--warn","--ok"].map(k=>k+"="+s.getPropertyValue(k).trim());})));
console.log("font sizes in table-panel:", JSON.stringify(await p.evaluate(()=>[...new Set([...document.querySelectorAll("#table-panel *")].map(e=>getComputedStyle(e).fontSize))].sort())));
console.log("left list now:", JSON.stringify(await p.evaluate(()=>{const r=document.querySelector("#list-rows .row");return r?r.innerText.replace(/\s+/g," "):"none";})));
await b.close();
