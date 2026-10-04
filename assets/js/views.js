/* ============================================================
   Shared by both pages, loaded after data.js:
     - the public view counter
     - demo video cards
     - the video player modal
   Each page sets SITE and (optionally) lenis before calling these.
   ============================================================ */

/* ---------------------------------------------------------------- counter
   GitHub Pages is static, so the counts live on Abacus, a free public
   counter API. Every visitor sees the same numbers. A visit or a play is
   counted once per browser tab session, so refreshing does not inflate it.
   If the service is unreachable the numbers just stay hidden. */
const COUNTER = { api:"https://abacus.jasoncameron.dev", ns:"genga28-portfolio" };
const COUNTS = {};

async function counterCall(op, key){
  try{
    const r = await fetch(`${COUNTER.api}/${op}/${COUNTER.ns}/${key}`);
    if(r.status === 404) return 0;           // never hit yet
    if(!r.ok) return null;
    const j = await r.json();
    return typeof j.value === "number" ? j.value : null;
  }catch{ return null; }
}

function firstThisSession(key){
  try{
    const k = "gk.counted." + key;
    if(sessionStorage.getItem(k)) return false;
    sessionStorage.setItem(k, "1");
  }catch{ /* storage blocked: count it anyway */ }
  return true;
}

function showCount(key, n){
  if(typeof n !== "number") return;
  COUNTS[key] = n;
  document.querySelectorAll(`[data-count="${key}"]`).forEach(el => {
    el.querySelector("b").textContent = n.toLocaleString("en-US");
    el.hidden = n < 1;
  });
}

function showDemoTotal(){
  const ids = (SITE.demos || []).map(d => "demo-" + d.id);
  if(!ids.every(k => typeof COUNTS[k] === "number")) return;
  showCount("demo-total", ids.reduce((s,k) => s + COUNTS[k], 0));
}

/* Count an event once per session, then show the new total. */
async function track(key){
  const n = await counterCall(firstThisSession(key) ? "hit" : "get", key);
  showCount(key, n);
  if(key.startsWith("demo-")) showDemoTotal();
  return n;
}

/* On load: count the visit, read every demo's total and the résumé opens. */
async function loadCounts(){
  const reads = (SITE.demos || []).map(d =>
    counterCall("get", "demo-" + d.id).then(n => showCount("demo-" + d.id, n)));
  reads.push(counterCall("get", "resume").then(n => showCount("resume", n)));
  reads.push(track("visits"));
  await Promise.all(reads);
  showDemoTotal();
}

/* ---------------------------------------------------------------- cards */
const EYE = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"/><circle cx="12" cy="12" r="3"/></svg>`;

function demoCard(d, i){
  const src = (SITE.videos || {})[d.id];
  // A committed poster is reliable; Drive's thumbnail endpoint is the fallback.
  const thumb = src ? (d.poster || thumbUrl(src)) : "";
  const views = `<span class="vc-views" data-count="demo-${d.id}" hidden>${EYE}<b>0</b> views</span>`;
  const media = src
    ? `<button class="vc-media" data-demo="${d.id}" aria-label="Play demo: ${d.title}">
         ${thumb ? `<img src="${thumb}" alt="" referrerpolicy="no-referrer" onerror="this.remove()">` : ""}
         <span class="vc-play"><span class="play-big" aria-hidden="true"></span></span>
         ${views}
       </button>`
    : `<div class="vc-media"><div class="vc-soon">
         <div class="vc-flow">${d.flow.map(s => `<span>${s}</span>`).join('<i aria-hidden="true"></i>')}</div>
         Recording coming soon
       </div></div>`;

  return `
  <article class="vcard reveal" style="--c:${d.c};--i:${Math.min(i,3)}">
    ${media}
    <div class="vc-body">
      <span class="vc-tag">${d.tag}</span>
      <h3>${d.title}</h3>
      <p>${d.line}</p>
      <div class="vc-foot">
        <div class="chips">${d.tech.map(t => `<span class="chip">${t}</span>`).join("")}</div>
        <a class="vc-code" href="${d.src}" target="_blank" rel="noopener">Code <span aria-hidden="true">↗</span></a>
      </div>
    </div>
  </article>`;
}

function renderDemos(){
  const grid = document.querySelector("#demoGrid");
  if(!grid) return;
  grid.innerHTML = SITE.demos.map(demoCard).join("");
  for(const k in COUNTS) showCount(k, COUNTS[k]);
}

/* ---------------------------------------------------------------- player */
function scrollLock(on){
  if(typeof lenis === "undefined" || !lenis) return;
  on ? lenis.stop() : lenis.start();
}

function openDemo(id){
  const d = SITE.demos.find(x => x.id === id);
  const src = (SITE.videos || {})[id];
  if(!d || !src) return;

  const modal = document.querySelector("#demo");
  modal.style.setProperty("--c", d.c);
  document.querySelector("#demoTitle").textContent = d.title;
  document.querySelector("#demoKick").textContent = d.tag;
  const e = embedUrl(src);
  document.querySelector("#demoStage").innerHTML = e.kind === "frame"
    ? `<iframe src="${e.url}" title="${d.title}" allow="accelerometer; autoplay; clipboard-write; encrypted-media; picture-in-picture" allowfullscreen></iframe>`
    : `<video src="${e.url}" controls autoplay playsinline></video>`;

  modal.hidden = false;
  requestAnimationFrame(() => modal.classList.add("on"));
  scrollLock(true);
  modal.querySelector(".demo-close").focus();
  track("demo-" + id);
}

function closeDemo(){
  const modal = document.querySelector("#demo");
  if(!modal || modal.hidden) return;
  modal.classList.remove("on");
  scrollLock(false);
  // Clearing the stage stops playback; wait for the transition first.
  setTimeout(() => { modal.hidden = true; document.querySelector("#demoStage").innerHTML = ""; }, 480);
}

document.addEventListener("click", e => {
  if(e.target.closest("#demo [data-close]")){ closeDemo(); return; }
  const b = e.target.closest("[data-demo]");
  if(b){ openDemo(b.dataset.demo); return; }
  if(e.target.closest("[data-resume]")) track("resume");
});
addEventListener("keydown", e => { if(e.key === "Escape") closeDemo(); });
