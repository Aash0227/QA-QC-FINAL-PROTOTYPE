import { chromium } from "playwright";
const OUT = process.env.SP;
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
const bad = [];
p.on("response", r => { if (r.status() >= 400) bad.push(r.status()+" "+r.url()); });
await p.goto("http://localhost:5173/index.html", { waitUntil: "domcontentloaded" });
await p.waitForTimeout(3500);
console.log("4xx/5xx:", JSON.stringify(bad));
console.log("logo natural size:", await p.evaluate(()=>{const i=document.querySelector(".brand-logo");return i.naturalWidth+"x"+i.naturalHeight;}));

// which cats are open on load
console.log("cat open state:", await p.evaluate(()=>[...document.querySelectorAll("#list-rows .cat-hdr")].map(e=>e.dataset.cat+":"+e.className)));
// open holdown properly then a mark
await p.evaluate(()=>{const h=[...document.querySelectorAll("#list-rows .cat-hdr")].find(e=>e.dataset.cat==="holdown"); if(!h.classList.contains("open")) h.click();});
await p.waitForTimeout(300);
console.log("mark headers:", (await p.locator("#list-rows .mark-hdr").count()));
await p.locator("#list-rows .mark-hdr").first().click(); await p.waitForTimeout(300);
console.log("rows now:", await p.locator("#list-rows .row").count());
console.log("row pills:", [...new Set(await p.locator("#list-rows .pill").allTextContents())]);
console.log("row has verdict badge?", await p.locator("#list-rows .verdict-badge").count());
await p.screenshot({path:OUT+"/20-list-rows.png"});

// select a row -> inspector
await p.locator("#list-rows .row").first().click(); await p.waitForTimeout(800);
console.log("inspector open?", await p.isVisible("#inspector"), "| inspector verdict badges:", await p.locator("#insp-body .verdict-badge").count());
console.log("inspector text head:", (await p.textContent("#insp-body")).replace(/\s+/g," ").slice(0,220));
await p.screenshot({path:OUT+"/21-inspector.png"});

// keyboard: real Tab to a verdict button
await p.click("#btn-table"); await p.waitForTimeout(500);
await p.evaluate(()=>document.querySelector(".verdict-bar__item").previousElementSibling?.focus?.());
await p.locator("#search").focus();
let hits=0, found=false;
for (let i=0;i<60;i++){ await p.keyboard.press("Tab"); const c = await p.evaluate(()=>document.activeElement?.className||""); if (c.includes("verdict-bar__item")){found=true;break;} hits++; }
console.log("tabs to reach first verdict button:", found?hits:"NEVER REACHED in 60 tabs");
if(found) console.log("FOCUS-VISIBLE style:", JSON.stringify(await p.evaluate(()=>{const e=document.activeElement,c=getComputedStyle(e);return{outlineStyle:c.outlineStyle,outlineWidth:c.outlineWidth,outlineColor:c.outlineColor,boxShadow:c.boxShadow,matchesFV:e.matches(":focus-visible")};})));
await p.screenshot({path:OUT+"/22-tabfocus.png"});
// cat-hdr keyboard reachable?
console.log("cat-hdr tabindex/role:", await p.evaluate(()=>{const e=document.querySelector("#list-rows .cat-hdr");return "tabindex="+e.tabIndex+" role="+e.getAttribute("role");}));
console.log("list-rows role children:", await p.evaluate(()=>{const l=document.getElementById("list-rows");return [...l.children].slice(0,4).map(c=>c.className+"|role="+(c.getAttribute("role")||"none"));}));
// track segment affordance
console.log("track seg cursor/clickable:", await p.evaluate(()=>{const s=document.querySelector(".verdict-bar__seg");return getComputedStyle(s).cursor+" | onclick="+!!s.onclick+" | tabindex="+s.tabIndex;}));

// stale filter across loadAll (Match) -- just check that store keeps it; use extract? too slow. Instead assert code path by triggering loadAll via btn-match is slow; skip.

// EMPTY STATE: results table with impossible search
await p.fill("#search","zzzzzzz"); await p.waitForTimeout(600);
console.log("EMPTY table cell:", (await p.textContent("#results-tbody")).trim(), "| left:", (await p.textContent("#list-rows")).trim());
await p.screenshot({path:OUT+"/23-empty.png"});
await p.fill("#search",""); await p.waitForTimeout(500);

// ---- PIPELINE PAGE ----
const pageErrs=[]; p.on("pageerror",e=>pageErrs.push(e.message));
await p.goto("http://localhost:5173/pipeline.html",{waitUntil:"domcontentloaded"});
await p.waitForTimeout(3000);
const btns = await p.evaluate(()=>[...document.querySelectorAll("button,a")].map(e=>({t:(e.innerText||e.title||"").replace(/\s+/g," ").trim().slice(0,40), dis:e.disabled===true, tag:e.tagName, href:e.getAttribute("href")||""})));
console.log("PIPELINE CONTROLS:", JSON.stringify(btns,null,0));
console.log("pipeline body text:", (await p.textContent("body")).replace(/\s+/g," ").slice(0,600));
await p.screenshot({path:OUT+"/30-pipeline.png",fullPage:true});
await p.setViewportSize({width:375,height:812}); await p.waitForTimeout(500);
console.log("pipeline 375 scrollW:", await p.evaluate(()=>document.documentElement.scrollWidth));
await p.screenshot({path:OUT+"/31-pipeline-375.png"});
console.log("pipeline errors:", JSON.stringify(pageErrs.slice(0,5)));
await b.close();
