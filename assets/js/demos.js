/* Demos page. Reads the same data.js the home page does, plus content.json
   so a video added through the editor shows up here too. */

const $  = (s,r=document) => r.querySelector(s);
const $$ = (s,r=document) => Array.from(r.querySelectorAll(s));
const DRAFT_KEY = "gk.draft";

let SITE = structuredClone(DEFAULTS);

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

async function loadContent(){
  try{
    const r = await fetch("content.json", { cache:"no-store" });
    if(r.ok) SITE = merge(SITE, await r.json());
  }catch{ /* defaults are fine */ }
  try{
    const raw = localStorage.getItem(DRAFT_KEY);
    if(raw) SITE = merge(SITE, JSON.parse(raw));
  }catch{ /* storage blocked */ }
}

document.documentElement.classList.add("js");

/* ---------------------------------------------------------------- render */
function card(d, i){
  const src = (SITE.videos || {})[d.id];
  const poster = src
    ? (/^https?:\/\//.test(src)
        ? `<div class="dc-play"><span class="play-big" aria-hidden="true"></span><span>Watch the demo</span></div>`
        : `<video src="${src}" muted playsinline preload="metadata"></video>
           <div class="dc-play"><span class="play-big" aria-hidden="true"></span><span>Watch the demo</span></div>`)
    : `<div class="dc-soon">
         <div class="dc-flow">${d.flow.map(s => `<span>${s}</span>`).join('<i aria-hidden="true"></i>')}</div>
         <span class="dc-soon-tag">Recording coming soon</span>
       </div>`;

  return `
  <article class="dcard reveal" style="--c:${d.c};--i:${i}" data-spot>
    <div class="dc-media${src ? " has-video" : ""}" ${src ? `data-demo="${d.id}" role="button" tabindex="0" aria-label="Play ${d.title}"` : ""}>
      ${poster}
    </div>
    <div class="dc-body">
      <span class="dc-tag">${d.tag}</span>
      <h2>${d.title}</h2>
      <p>${d.line}</p>
      <ul class="dc-points">${d.points.map(p => `<li>${p}</li>`).join("")}</ul>
      <div class="chips">${d.tech.map(t => `<span class="chip">${t}</span>`).join("")}</div>
      <div class="dc-actions">
        ${src ? `<button class="btn btn-sm demo-btn" data-demo="${d.id}"><span class="play" aria-hidden="true"></span>Watch demo</button>` : ""}
        <a class="btn btn-sm" href="${d.src}" target="_blank" rel="noopener">View the code <span class="arr" aria-hidden="true">↗</span></a>
      </div>
    </div>
  </article>`;
}

function render(){
  $("#demoGrid").innerHTML = SITE.demos.map(card).join("");
  $("#yr").textContent = new Date().getFullYear();

  const p = SITE.profile;
  $("#brandName").textContent = p.name;
  $("#brandKicker").textContent = p.kicker;
  $("#brandMark").textContent = p.name.split(/\s+/).map(w => w[0]).join("").slice(0,2).toUpperCase();

  observeReveals();
  bind();
}

/* ---------------------------------------------------------------- motion */
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
let lenis = null;
if(window.Lenis && !reduced){
  lenis = new Lenis({ duration:1.05, smoothWheel:true, touchMultiplier:1.6 });
  const raf = t => { lenis.raf(t); requestAnimationFrame(raf); };
  requestAnimationFrame(raf);
}

let io = null;
function observeReveals(){
  if(io) io.disconnect();
  io = new IntersectionObserver(es => {
    es.forEach(en => { if(en.isIntersecting){ en.target.classList.add("in"); io.unobserve(en.target); } });
  }, { rootMargin:"0px 0px -8% 0px", threshold:0.04 });
  $$(".reveal").forEach(el => io.observe(el));
}

const nav = $("#nav"), menuBtn = $("#menuBtn"), progress = $("#progress");
menuBtn.addEventListener("click", () => {
  const open = nav.classList.toggle("open");
  menuBtn.setAttribute("aria-expanded", String(open));
});

let ticking = false;
addEventListener("scroll", () => {
  if(ticking) return;
  ticking = true;
  requestAnimationFrame(() => {
    const y = window.scrollY;
    nav.classList.toggle("stuck", y > 20);
    const max = document.documentElement.scrollHeight - innerHeight;
    progress.style.width = (max > 0 ? (y/max)*100 : 0) + "%";
    ticking = false;
  });
}, { passive:true });

function bind(){
  if(matchMedia("(pointer:fine)").matches){
    $$("[data-spot]").forEach(el => {
      el.addEventListener("pointermove", ev => {
        const r = el.getBoundingClientRect();
        el.style.setProperty("--mx",(ev.clientX-r.left)+"px");
        el.style.setProperty("--my",(ev.clientY-r.top)+"px");
      });
    });
  }

  // Preview on hover: a muted loop is a much better poster than a still.
  $$(".dc-media.has-video video").forEach(v => {
    const card = v.closest(".dc-media");
    card.addEventListener("pointerenter", () => { v.currentTime = 0; v.play().catch(() => {}); });
    card.addEventListener("pointerleave", () => v.pause());
  });

  $("#demoGrid").addEventListener("click", e => {
    const b = e.target.closest("[data-demo]");
    if(b) openDemo(b.dataset.demo);
  });
  $("#demoGrid").addEventListener("keydown", e => {
    if(e.key !== "Enter" && e.key !== " ") return;
    const b = e.target.closest("[data-demo]");
    if(b){ e.preventDefault(); openDemo(b.dataset.demo); }
  });
}

/* ---------------------------------------------------------------- player */
function openDemo(id){
  const d = SITE.demos.find(x => x.id === id);
  const src = (SITE.videos || {})[id];
  if(!d || !src) return;

  const modal = $("#demo");
  modal.style.setProperty("--c", d.c);
  $("#demoTitle").textContent = d.title;
  $("#demoKick").textContent = d.tag;
  $("#demoStage").innerHTML = /^https?:\/\//.test(src)
    ? `<iframe src="${src}${src.includes("?") ? "&" : "?"}autoplay=1" title="${d.title}" allow="accelerometer; autoplay; clipboard-write; encrypted-media; picture-in-picture" allowfullscreen></iframe>`
    : `<video src="${src}" controls autoplay playsinline></video>`;

  modal.hidden = false;
  requestAnimationFrame(() => modal.classList.add("on"));
  if(lenis) lenis.stop();
  $(".demo-close").focus();
}

function closeDemo(){
  const modal = $("#demo");
  if(!modal || modal.hidden) return;
  modal.classList.remove("on");
  if(lenis) lenis.start();
  setTimeout(() => { modal.hidden = true; $("#demoStage").innerHTML = ""; }, 480);
}

$("#demo").addEventListener("click", e => { if(e.target.closest("[data-close]")) closeDemo(); });
addEventListener("keydown", e => { if(e.key === "Escape") closeDemo(); });

document.addEventListener("click", e => {
  const a = e.target.closest('a[href^="#"]');
  if(!a) return;
  const id = a.getAttribute("href");
  if(id.length < 2) return;
  e.preventDefault();
  const el = document.querySelector(id);
  if(!el) return;
  if(lenis) lenis.scrollTo(el, { offset:-96 });
  else el.scrollIntoView({ behavior: reduced ? "auto" : "smooth" });
});

loadContent().then(render);
