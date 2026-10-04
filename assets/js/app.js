/* ============================================================
   GENGA K PORTFOLIO - home page
   Content, colours and the section palette live in data.js,
   which must load before this file. Three layers, in order:
     1. DEFAULTS      = assets/js/data.js
     2. content.json  = published overrides (what visitors see)
     3. localStorage  = your unsaved admin draft (only you see it)
   Open the admin panel with  #admin  or  Ctrl+Shift+E
   ============================================================ */


/* ============================================================
   CONTENT LAYERS
   ============================================================ */
const DRAFT_KEY = "gk.draft";
const $  = (s,r=document) => r.querySelector(s);
const $$ = (s,r=document) => Array.from(r.querySelectorAll(s));

let SITE = structuredClone(DEFAULTS);
let hasDraft = false;

function merge(base, over){
  if(!over) return base;
  const out = { ...base };
  for(const k of Object.keys(over)){
    const v = over[k];
    if(v === undefined || v === null) continue;
    if(Array.isArray(v)) out[k] = v;
    else if(typeof v === "object") out[k] = merge(base[k] || {}, v);
    else out[k] = v;
  }
  return out;
}

function readDraft(){
  try{ const raw = localStorage.getItem(DRAFT_KEY); return raw ? JSON.parse(raw) : null; }
  catch{ return null; }
}

async function loadContent(){
  try{
    const r = await fetch("content.json", { cache:"no-store" });
    if(r.ok) SITE = merge(SITE, await r.json());
  }catch{ /* no published overrides, defaults are fine */ }

  const draft = readDraft();
  if(draft){ SITE = merge(SITE, draft); hasDraft = true; }
}

/* ============================================================
   RENDER
   ============================================================ */
document.documentElement.classList.add("js");

function renderHero(){
  const p = SITE.profile;
  $("#brandName").textContent = p.name;
  $("#brandKicker").textContent = p.kicker;
  $("#brandMark").textContent = p.name.split(/\s+/).map(w => w[0]).join("").slice(0,2).toUpperCase();

  $("#avail").innerHTML = `<b aria-hidden="true"></b>${p.availableText}`;
  $("#avail").hidden = !p.available;

  $("#headline").innerHTML = p.headline.map(l =>
    `<span class="line"><span>${l}</span></span>`).join("");
  // the last word of the last line carries the gradient
  const lastLine = $("#headline .line:last-child span");
  if(lastLine){
    lastLine.innerHTML = lastLine.textContent.replace(/([\w-]+)(\W*)$/, (_,w,d) => `<em>${w}</em>${d}`);
  }

  $("#lede").innerHTML = p.lede;
  if(p.resume) $("#resumeBtn").href = p.resume;
  $("#portraitTag").innerHTML =
    `<span>${p.location}</span>` +
    (p.available ? `<span class="live"><b aria-hidden="true"></b>Available</span>` : "");

  $("#telemetry").innerHTML = SITE.telemetry.map(t =>
    `<div class="tm" role="listitem"><span class="v">${t.v}</span><span class="k">${t.k}</span></div>`).join("");

  const img = $("#photo"), fb = $("#photoFallback");
  fb.querySelector("span").textContent = $("#brandMark").textContent;
  img.onload  = () => { img.hidden = false; fb.style.display = "none"; };
  img.onerror = () => { img.hidden = true; fb.style.display = ""; };
  if(p.photo) img.src = p.photo;
}

function renderTimeline(){
  const roles = SITE.roles;
  const now = new Date();
  const T0 = 2022 + 8/12;
  const T1 = now.getFullYear() + (now.getMonth()+2)/12;
  const span = T1 - T0;
  const at = ([y,m]) => ((y + (m-1)/12) - T0) / span * 100;

  const years = [];
  for(let y = 2023; y <= now.getFullYear(); y++) years.push(y);

  $("#timeline").innerHTML = `
    <div class="tl-axis">
      <span></span>
      <span class="tl-years">${years.map(y => `<span style="left:${at([y,1])}%">${y}</span>`).join("")}</span>
    </div>
    <div class="tl-rows">${roles.map((r,i) => {
      const x = at(r.start), x2 = r.end ? at(r.end) : 100;
      return `<button class="tl-row" data-role="${i}" style="--c:${r.c}">
        <span class="tl-label"><b>${r.co}</b><span>${r.title.split(" · ")[0]}</span></span>
        <span class="tl-track">
          <span class="tl-grid">${years.map(y => `<i style="left:${at([y,1])}%"></i>`).join("")}</span>
          <span class="tl-bar${r.end?"":" now"}" style="left:${x}%;width:${Math.max(x2-x,8)}%;animation-delay:${.15+i*.09}s">${r.when}</span>
        </span>
      </button>`;
    }).join("")}</div>`;
}

function renderRoles(){
  $("#roles").innerHTML = SITE.roles.map((r,i) => `
    <article class="xp-row" id="role-${i}" style="--c:${r.c}">
      <div class="xp-main">
        <h3 class="xp-co">${r.co}<span>${r.title}</span><small>${r.when} · ${r.where}</small></h3>
        <p>${r.line || ""}</p>
      </div>
      ${r.metric ? `<span class="xp-metric">${r.metric}</span>` : ""}
    </article>`).join("");
}

const FUSION_HTML = `
<div class="fusion">
  <div>
    <h4>Live signal fusion</h4>
    <p class="hint">Drag any signal. The blend is weighted, then boosted when one channel runs hot.</p>
    <div class="sigs">
      <div class="sig" style="--sig-c:${COLORS.blue}">
        <label for="s-content">Content <i>weight 0.30</i></label><span class="val" id="v-content">24</span>
        <input id="s-content" type="range" min="0" max="100" value="24" aria-label="Content signal">
      </div>
      <div class="sig" style="--sig-c:${COLORS.amber}">
        <label for="s-ai">AI-likeliness <i>weight 0.25</i></label><span class="val" id="v-ai">31</span>
        <input id="s-ai" type="range" min="0" max="100" value="31" aria-label="AI-likeliness signal">
      </div>
      <div class="sig" style="--sig-c:${COLORS.violet}">
        <label for="s-audio">Audio <i>weight 0.20</i></label><span class="val" id="v-audio">18</span>
        <input id="s-audio" type="range" min="0" max="100" value="18" aria-label="Audio signal">
      </div>
      <div class="sig" style="--sig-c:${COLORS.teal}">
        <label for="s-video">Video <i>weight 0.25</i></label><span class="val" id="v-video">42</span>
        <input id="s-video" type="range" min="0" max="100" value="42" aria-label="Video signal">
      </div>
    </div>
  </div>
  <div class="gauge">
    <div class="gauge-score">
      <span class="gauge-num" id="score">31</span>
      <span class="gauge-of">/ 100</span>
      <span class="band-pill" id="band">Review</span>
    </div>
    <div class="meter">
      <div class="meter-bands" aria-hidden="true">
        <i style="width:30%;background:#6FD895"></i><i style="width:30%;background:#EFC15E"></i>
        <i style="width:25%;background:#F0A05C"></i><i style="width:15%;background:#EE7F7F"></i>
      </div>
      <div class="meter-fill" id="fill"></div>
    </div>
    <div class="meter-scale"><span>0 Clear</span><span>30 Review</span><span>60 Elevated</span><span>85 Critical</span></div>
    <div class="episodes" id="episodes"></div>
    <p class="gauge-note">Illustrative model. Production weights and calibration are proprietary.</p>
  </div>
</div>`;

function renderCases(){
  const feature = SITE.cases.find(c => c.fusion);
  const rest = SITE.cases.filter(c => !c.fusion);
  $("#cases").innerHTML =
    (feature ? `
    <article class="proj-feature reveal" style="--c:${feature.c}">
      <div class="pf-head">
        <span class="pc-kind"><b>${feature.org}</b> · ${feature.kind}</span>
        <h3>${feature.title}</h3>
        <p>${feature.lede}</p>
      </div>
      ${FUSION_HTML}
    </article>` : "") + `
    <div class="pgrid">${rest.map((c,i) => `
      <article class="pcard reveal" style="--c:${c.c};--i:${i % 3}">
        <span class="pc-kind"><b>${c.org}</b> · ${c.kind}</span>
        <h3>${c.title}</h3>
        ${c.win ? `<p class="pc-win">${c.win}</p>` : ""}
        <p>${c.lede}</p>
        <div class="chips">${(c.tech||[]).map(t => `<span class="chip">${t}</span>`).join("")}</div>
        ${c.link ? `<a class="pc-link" href="${c.link}" target="_blank" rel="noopener" aria-label="Source for ${c.title}">↗</a>` : ""}
      </article>`).join("")}
    </div>`;
}

function renderStack(){
  $("#stackGrid").innerHTML = SITE.stack.map(g => `
    <div class="skill-row" style="--c:${g.c}">
      <h3>${g.h}</h3>
      <div class="chips">${g.items.map(t => `<span class="chip">${t}</span>`).join("")}</div>
    </div>`).join("");
}

function renderPosts(){
  const cyc = [COLORS.amber, COLORS.violet, COLORS.teal, COLORS.pink, COLORS.cyan, COLORS.blue];
  $("#posts").innerHTML = SITE.posts.length
    ? SITE.posts.map((p,i) => `
      <button class="post" data-post="${i}" style="--c:${cyc[i % cyc.length]};--i:${i}">
        ${p.cover ? `<span class="post-cover"><img src="${p.cover}" alt=""></span>` : ""}
        <span class="post-meta"><span class="tag">${p.tag||"Note"}</span>·<span>${p.date||""}</span>·<span>${p.read||""}</span></span>
        <h3>${p.title}</h3>
        <p>${p.dek||""}</p>
        <span class="more">Read <span class="arr" aria-hidden="true">→</span></span>
      </button>`).join("")
    : `<p class="sec-sub">No notes published yet.</p>`;
}

function renderLinks(){
  $("#links").innerHTML = SITE.links.map(l => {
    const inner = `<span class="k">${l.k}</span><span class="v">${l.v}</span><span class="go">${l.go}</span>`;
    return l.href
      ? `<a class="link-row" href="${l.href}"${/^https/.test(l.href) ? ' target="_blank" rel="noopener"' : ""}>${inner}</a>`
      : `<div class="link-row">${inner}</div>`;
  }).join("");
}

function renderRail(){
  $("#rail").innerHTML = Object.entries(SECTION_COLOR).map(([href,c]) => {
    const label = { "#top":"Intro", "#work":"Experience" }[href] || href.slice(1);
    return `<a href="${href}" style="--c:${c}"><span class="dot"></span><span class="lbl">${label[0].toUpperCase()+label.slice(1)}</span></a>`;
  }).join("");
  for(const [href,c] of Object.entries(SECTION_COLOR)){
    const el = document.querySelector(href);
    if(el) el.style.setProperty("--sec", c);
  }
}

function renderAll(){
  renderHero(); renderDemos(); renderTimeline(); renderRoles(); renderCases();
  renderStack(); renderPosts(); renderLinks(); renderRail();
  $("#yr").textContent = new Date().getFullYear();
  bindDynamic();
  observeReveals();
}

/* ============================================================
   INTERACTION
   ============================================================ */
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const nav = $("#nav"), menuBtn = $("#menuBtn"), progress = $("#progress");

let lenis = null;
if(window.Lenis && !reduced){
  lenis = new Lenis({ duration:1.05, smoothWheel:true, touchMultiplier:1.6 });
  const raf = t => { lenis.raf(t); requestAnimationFrame(raf); };
  requestAnimationFrame(raf);
}
function goTo(target){
  const el = typeof target === "string" ? document.querySelector(target) : target;
  if(!el) return;
  if(lenis) lenis.scrollTo(el, { offset:-96 });
  else el.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block:"start" });
}

document.addEventListener("click", e => {
  const a = e.target.closest('a[href^="#"]');
  if(!a || a.closest(".admin")) return;
  const id = a.getAttribute("href");
  if(id.length < 2) return;
  e.preventDefault();
  nav.classList.remove("open");
  menuBtn.setAttribute("aria-expanded","false");
  goTo(id);
});

menuBtn.addEventListener("click", () => {
  const open = nav.classList.toggle("open");
  menuBtn.setAttribute("aria-expanded", String(open));
});

const spy = Object.keys(SECTION_COLOR);
let ticking = false;
function onScroll(){
  const y = window.scrollY;
  nav.classList.toggle("stuck", y > 20);
  const max = document.documentElement.scrollHeight - innerHeight;
  progress.style.width = (max > 0 ? (y/max)*100 : 0) + "%";
  let current = spy[0];
  for(const id of spy){
    const el = document.querySelector(id);
    if(el && el.getBoundingClientRect().top <= innerHeight*0.34) current = id;
  }
  $$("#navLinks a, #rail a").forEach(a => a.classList.toggle("active", a.getAttribute("href") === current));
  ticking = false;
}
addEventListener("scroll", () => { if(!ticking){ ticking = true; requestAnimationFrame(onScroll); } }, { passive:true });

let io = null;
function observeReveals(){
  if(io) io.disconnect();
  io = new IntersectionObserver(es => {
    es.forEach(en => { if(en.isIntersecting){ en.target.classList.add("in"); io.unobserve(en.target); } });
  }, { rootMargin:"0px 0px -8% 0px", threshold:0.04 });
  $$(".reveal").forEach(el => io.observe(el));
}

function bindDynamic(){
  $("#timeline").onclick = e => {
    const row = e.target.closest("[data-role]");
    if(!row) return;
    const role = $("#role-" + row.dataset.role);
    if(!role) return;
    goTo(role);
    role.classList.add("flash");
    setTimeout(() => role.classList.remove("flash"), 1400);
  };

  $("#posts").onclick = e => {
    const b = e.target.closest("[data-post]");
    if(b) openPost(+b.dataset.post);
  };

  initFusion();
  onScroll();
}

/* ---------------- fusion ---------------- */
function initFusion(){
  const W = { content:.30, ai:.25, audio:.20, video:.25 };
  const C = { content:COLORS.blue, ai:COLORS.amber, audio:COLORS.violet, video:COLORS.teal };
  const L = { content:"Content anomaly", ai:"AI-likeliness spike", audio:"Audio irregularity", video:"Gaze / face episode" };
  const BANDS = [{to:30,n:"Clear",c:"#6FD895"},{to:60,n:"Review",c:"#EFC15E"},{to:85,n:"Elevated",c:"#F0A05C"},{to:101,n:"Critical",c:"#EE7F7F"}];

  const inputs = {};
  ["content","ai","audio","video"].forEach(k => inputs[k] = $("#s-"+k));
  if(!inputs.content) return;
  const scoreEl = $("#score"), bandEl = $("#band"), fillEl = $("#fill"), epEl = $("#episodes");

  function render(){
    const s = {};
    for(const k in inputs) s[k] = +inputs[k].value;

    let base = 0;
    for(const k in W) base += W[k] * s[k];
    const peak  = Math.max(...Object.values(s));
    const boost = peak > 70 ? Math.pow((peak-70)/30, 1.5) * 18 : 0;
    const score = Math.max(0, Math.min(100, Math.round(base + boost)));
    const band  = BANDS.find(b => score < b.to);

    for(const k in inputs){
      $("#v-"+k).textContent = inputs[k].value;
      inputs[k].style.setProperty("--p", inputs[k].value + "%");
    }
    scoreEl.textContent = score;
    scoreEl.style.color = band.c;
    bandEl.textContent  = band.n;
    bandEl.style.color  = band.c;
    fillEl.style.width  = score + "%";
    fillEl.style.color  = band.c;

    const flagged = Object.keys(s).filter(k => s[k] >= 55).sort((a,b) => s[b]-s[a]);
    epEl.innerHTML = flagged.length
      ? flagged.map((k,i) => `<div class="ep"><b style="background:${C[k]}"></b>${L[k]}<span class="t">${String(4+i*7).padStart(2,"0")}:${String((i*23)%60).padStart(2,"0")}</span></div>`).join("")
      : `<div class="ep"><b style="background:#6FD895"></b>No episodes flagged<span class="t">all clear</span></div>`;
  }
  Object.values(inputs).forEach(el => el.oninput = render);
  render();
}

/* ---------------- reader ---------------- */
let lastFocus = null;
function openPost(i){
  const p = SITE.posts[i];
  if(!p) return;
  const reader = $("#reader");
  $("#readerMeta").innerHTML = `<span class="tag">${p.tag||"Note"}</span>·<span>${p.date||""}</span>·<span>${p.read||""}</span>`;
  $("#readerTitle").textContent = p.title;
  $("#readerBody").innerHTML = (p.cover ? `<div class="reader-cover"><img src="${p.cover}" alt=""></div>` : "") + p.body;
  reader.hidden = false;
  requestAnimationFrame(() => reader.classList.add("on"));
  if(lenis) lenis.stop();
  lastFocus = document.activeElement;
  $(".reader-close").focus();
}
function closePost(){
  const reader = $("#reader");
  reader.classList.remove("on");
  if(lenis) lenis.start();
  setTimeout(() => { reader.hidden = true; $("#readerBody").innerHTML = ""; }, 620);
  if(lastFocus) lastFocus.focus();
}
$("#reader").addEventListener("click", e => { if(e.target.closest("[data-close]")) closePost(); });
addEventListener("keydown", e => { if(e.key === "Escape" && !$("#reader").hidden) closePost(); });

/* ---------------- toast + copy ---------------- */
const toast = $("#toast");
let toastTimer;
function say(msg){
  toast.textContent = msg;
  toast.classList.add("on");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("on"), 3000);
}
document.addEventListener("click", async e => {
  const b = e.target.closest("[data-copy]");
  if(!b) return;
  try{ await navigator.clipboard.writeText(b.dataset.copy); say("Copied: " + b.dataset.copy); }
  catch{ say("Copy blocked: " + b.dataset.copy); }
});

/* ---------------- hero ribbons ---------------- */
(function(){
  const cv = $("#signal");
  if(!cv) return;
  const ctx = cv.getContext("2d");
  const TRACES = [
    { c:COLORS.blue,   amp:22, f:0.0110, sp:0.42, y:0.40 },
    { c:COLORS.amber,  amp:16, f:0.0165, sp:0.58, y:0.55 },
    { c:COLORS.violet, amp:26, f:0.0082, sp:0.34, y:0.70 },
    { c:COLORS.teal,   amp:18, f:0.0205, sp:0.50, y:0.84 }
  ];
  let w=0, h=0, raf=null;

  function size(){
    const dpr = Math.min(devicePixelRatio || 1, 2);
    const r = cv.getBoundingClientRect();
    w = r.width; h = r.height;
    cv.width = Math.round(w*dpr); cv.height = Math.round(h*dpr);
    ctx.setTransform(dpr,0,0,dpr,0,0);
  }
  function wave(x,t,tr){
    return Math.sin(x*tr.f + t)*0.62 + Math.sin(x*tr.f*2.3 + t*1.7)*0.25 + Math.sin(x*tr.f*4.1 + t*0.6)*0.13;
  }
  function draw(time){
    ctx.clearRect(0,0,w,h);
    const t = time*0.001, mergeY = h*0.62, cx = w*0.62;
    ctx.lineCap = "round";
    TRACES.forEach((tr,i) => {
      ctx.beginPath();
      ctx.strokeStyle = tr.c;
      ctx.lineWidth = 2.6;
      ctx.globalAlpha = 0.24;
      for(let x = 0; x <= w; x += 5){
        const k = x < cx ? 0 : Math.min(1,(x-cx)/(w-cx||1));
        const e = k*k*(3-2*k);
        const baseY = h*tr.y + (mergeY - h*tr.y)*e;
        const amp = tr.amp*(1 - e*0.94);
        const y = baseY + wave(x, t*tr.sp + i, tr)*amp;
        x === 0 ? ctx.moveTo(x,y) : ctx.lineTo(x,y);
      }
      ctx.stroke();
    });
    ctx.globalAlpha = 0.36;
    ctx.strokeStyle = COLORS.blue;
    ctx.lineWidth = 2.8;
    ctx.beginPath();
    ctx.moveTo(w*0.93, mergeY);
    ctx.lineTo(w, mergeY);
    ctx.stroke();
    ctx.globalAlpha = 1;
  }
  function loop(time){ draw(time); raf = requestAnimationFrame(loop); }

  size();
  if(reduced) draw(0);
  else{
    raf = requestAnimationFrame(loop);
    document.addEventListener("visibilitychange", () => {
      if(document.hidden){ cancelAnimationFrame(raf); raf = null; }
      else if(!raf){ raf = requestAnimationFrame(loop); }
    });
  }
  addEventListener("resize", () => { size(); if(reduced) draw(0); }, { passive:true });
})();

/* ============================================================
   BOOT
   ============================================================ */
loadContent().then(() => {
  renderAll();
  loadCounts();
  if(hasDraft) showDraftBar();
  if(location.hash === "#admin") openAdmin();
  initAdmin();
});
