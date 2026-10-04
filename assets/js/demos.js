/* Demos page. Cards, player and counter come from views.js; this file
   loads content, renders, and runs the page chrome. */

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

function render(){
  renderDemos();
  $("#yr").textContent = new Date().getFullYear();

  const p = SITE.profile;
  $("#brandName").textContent = p.name;
  $("#brandKicker").textContent = p.kicker;
  $("#brandMark").textContent = p.name.split(/\s+/).map(w => w[0]).join("").slice(0,2).toUpperCase();

  observeReveals();
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

loadContent().then(() => { render(); loadCounts(); });
