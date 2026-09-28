/* ============================================================
   GENGA K — PORTFOLIO
   Content lives in DEFAULTS below. Three layers, in order:
     1. DEFAULTS         — this file
     2. content.json     — published overrides (what visitors see)
     3. localStorage     — your unsaved admin draft (only you see it)
   Open the admin panel with  #admin  or  Ctrl+Shift+E
   ============================================================ */

const COLORS = {
  blue:"#7AB8FF", teal:"#5FD9C4", violet:"#B49BF5",
  cyan:"#5FC9F0", amber:"#F5BE8B", pink:"#F49BB8", green:"#8FE39A"
};

const SECTION_COLOR = {
  "#top":COLORS.blue, "#work":COLORS.teal, "#systems":COLORS.violet,
  "#stack":COLORS.cyan, "#writing":COLORS.amber, "#about":COLORS.pink, "#contact":COLORS.green
};

const DEFAULTS = {
  profile: {
    name:"Genga K",
    kicker:"Applied AI Engineer",
    location:"Bengaluru, India",
    photo:"assets/img/genga.jpg",
    resume:"GENGA_K_RESUME.pdf",
    available:true,
    availableText:"Open to AI / ML engineering roles",
    headline:["I build AI","systems that hold","up in production."],
    lede:"Applied AI engineer at <strong>Jobtwine</strong>. RAG pipelines, agentic workflows, real-time voice and vision — plus the concurrency and transformer internals underneath."
  },

  telemetry:[
    { v:"10–<i>50</i>", k:"Concurrent live sessions" },
    { v:"~<i>5K</i>",   k:"Documents / day in prod" },
    { v:"<i>50K</i>",   k:"Retrieval chunks grounded" },
    { v:"<i>4</i>",     k:"Signals fused per score" }
  ],

  /* Roles stay high-level on purpose — the detail lives in Systems,
     and each role links across rather than repeating it. */
  roles:[
    {
      co:"Jobtwine", title:"AI Engineer", when:"Jul 2025 — Present", where:"Bengaluru",
      start:[2025,7], end:null, c:COLORS.blue,
      bullets:[
        "Own the AI stack end to end — retrieval design, async backends, guardrails and observability across proctoring, interviewing and voice.",
        "Built the async FastAPI backend: a <b>10-worker SQS queue</b>, multiprocessing and polling-based concurrency holding <span class='num'>10–50</span> live sessions against <span class='num'>1000+</span> queued requests.",
        "Shipped the LLM interview tooling — JD-to-playbook generator, semantic resume shortlister, and post-interview analytics with generated debriefs."
      ],
      systems:["proctoring","rag","voice"],
      tech:["Python","RoBERTa","MediaPipe","OpenCV","Dlib","Wav2Lip","ASR","TTS","LangGraph","SQS","RAG","Pinecone","LangChain","FastAPI","MCP","Agentic AI","LLM-as-judge"]
    },
    {
      co:"Space Marvel AI", title:"AI Consultant · Freelance", when:"Jan — Jul 2025", where:"Remote",
      start:[2025,1], end:[2025,7], c:COLORS.violet,
      bullets:[
        "Led a <b>three-person team</b> across three AI systems — owned architecture, set the agent orchestration pattern, ran design reviews.",
        "Built an outbound tele-caller bot on ASR → LLM → TTS at <span class='num'>200 calls/day</span>, with interruption handling and outcome classification.",
        "Built a voice-driven desktop agent that reads browser and window state to automate multi-step workflows via tool calling."
      ],
      systems:["shelf"],
      tech:["Python","LLM agents","VLM","OpenCV","ASR/TTS","Tool calling","FastAPI"]
    },
    {
      co:"Yubi", title:"Data Scientist Intern", when:"Dec 2024 — Jun 2025", where:"Chennai",
      start:[2024,12], end:[2025,6], c:COLORS.teal,
      bullets:[
        "Shipped OCR + LLM classification APIs into loan-application processing — <span class='num'>~5,000 docs/day</span> across <span class='num'>50,000+</span> batch runs.",
        "Engineered validation modules detecting file tampering and verifying signature originality, flagging low-trust documents before underwriting.",
        "Devised an ASR/TTS audio bot extracting behavioural signals around loan-repayment intent."
      ],
      systems:["ocr"],
      tech:["Python","GPT-4o","llama.cpp","Fine-tuning","OCR","FastAPI","AWS SageMaker","Transformers","AWS Transcribe","Whisper"]
    },
    {
      co:"EXL Health", title:"Data Engineer Intern · R&D", when:"Jun — Nov 2023", where:"Chennai",
      start:[2023,6], end:[2023,11], c:COLORS.amber,
      bullets:[
        "Programmed RPA applications driving graphical and web interfaces, removing manual steps from repeated workflows.",
        "Ran data wrangling on scraped data with text mining and NLP — a <span class='num'>95%</span> cut in task completion time.",
        "Built a custom ETL tool to extract, clean and load web data — <span class='num'>60%</span> faster processing."
      ],
      tech:["Python","Lackey","PyAutoGUI","Tesseract OCR","Selenium","HiveQL","RPA","NLP"]
    },
    {
      co:"Elamigo", title:"Data Science Intern", when:"Dec 2022 — Feb 2023", where:"Bengaluru",
      start:[2022,12], end:[2023,2], c:COLORS.pink,
      bullets:[
        "Scraped and structured data across <span class='num'>~40</span> industry sectors into a queryable database, then ran EDA surfacing <span class='num'>15+</span> partnership insights."
      ],
      tech:["MySQL","BeautifulSoup","Selenium","Power BI"]
    }
  ],

  cases:[
    {
      id:"proctoring", feature:true, badge:"Flagship", c:COLORS.blue,
      org:"Jobtwine", year:"2025", kind:"Real-time scoring",
      title:"Multi-signal AI proctoring engine",
      lede:"Four noisy detectors watching a live interview, fused into one number a hiring panel can defend.",
      problem:"Fire on one detector and you get false accusations. Require all four and you get silence.",
      approach:"Weighted blend across the four signals, plus an exponential boost so one extreme reading can escalate — but never convict alone.",
      result:"A reviewable score, not a verdict. Every number traces back to timestamped episodes.",
      flow:["Live session","Content","AI-likeliness","Audio","Video","Fusion","0–100"], hot:[5,6],
      tech:["Python","RoBERTa","MediaPipe","OpenCV","Dlib","Wav2Lip","ASR","Multiprocessing"],
      fusion:true
    },
    {
      id:"rag", c:COLORS.violet, org:"Jobtwine", year:"2025", kind:"Retrieval",
      title:"Real-time RAG for a live interviewer",
      lede:"Grounding an interviewer LLM in rubrics and JDs, fast enough that the candidate never hears it happen.",
      problem:"An ungrounded interviewer invents requirements and drifts off the rubric mid-session.",
      approach:"Index 10–50K rubric and JD chunks in Pinecone, retrieve against live conversation state, inject only what the turn needs.",
      result:"Context-absence failures eliminated. Every question traces to a retrieved chunk.",
      flow:["Turn state","Query","Pinecone","Rerank","Grounded prompt","LLM"], hot:[2,5],
      tech:["RAG","Pinecone","LangChain","LangGraph","FastAPI","Python"]
    },
    {
      id:"voice", c:COLORS.teal, org:"Jobtwine", year:"2025", kind:"Real-time voice",
      title:"WebRTC voice agent with barge-in",
      lede:"Streaming and turn-based modes, with interruption handling that survives being talked over.",
      problem:"Turn-based agents feel like walkie-talkies. Streaming agents talk over people.",
      approach:"Dual-mode WebRTC transport, barge-in detection on the inbound stream, clean TTS cancellation, memory threaded through agent state.",
      result:"Conversations that hold their thread across a full interview instead of resetting each turn.",
      flow:["WebRTC","VAD · barge-in","ASR","Agent + memory","TTS"], hot:[1,3],
      tech:["WebRTC","ASR","TTS","LangGraph","Agentic AI","Python"]
    },
    {
      id:"ocr", c:COLORS.amber, org:"Yubi", year:"2024–25", kind:"Document AI",
      title:"Hybrid layout-preserving OCR",
      lede:"Rules and an LLM working the same page, rebuilding multi-column financial PDFs at pixel level.",
      problem:"Off-the-shelf OCR flattens layout — a number lands on the wrong label, and a loan gets written on it.",
      approach:"Replicate pixel coordinates and spacing to preserve structure; deterministic rules where the format is known, LLM where it isn't.",
      result:"Beat PaddleOCR, Tesseract and Textract across 30+ document types at ~5,000 docs/day.",
      flow:["PDF","Layout parse","Rules","LLM fallback","Coord replay","Key-values"], hot:[2,3],
      tech:["OCR","GPT-4o","llama.cpp","Transformers","AWS SageMaker","FastAPI"]
    },
    {
      id:"shelf", c:COLORS.pink, org:"Space Marvel AI", year:"2025", kind:"CV + VLM",
      title:"Retail shelf auditing",
      lede:"Segmentation finds where the products are; a VLM reads what they are and how many.",
      problem:"Manual audits are stale on arrival, and pure detection needs retraining for every new SKU.",
      approach:"Two stages — CV segmentation localizes clusters, then a VLM identifies SKU names and counts inside each.",
      result:"Automated restock alerts with no per-SKU model to maintain. New products need a prompt, not a retrain.",
      flow:["Shelf image","Segmentation","Crops","VLM","Restock alert"], hot:[1,3],
      tech:["VLM","OpenCV","Python","LLM agents","FastAPI"]
    },
    {
      id:"profiling", c:COLORS.cyan, org:"Independent", year:"2025", kind:"Inference economics",
      title:"Why a 3B outserved a 4B by 5×",
      lede:"A roofline and KV-concurrency model that predicted serving throughput better than parameter count.",
      problem:"Model choice was being made on benchmark scores, which say nothing about concurrent users per GPU.",
      approach:"Roofline model for decode latency plus a KV-cache concurrency model, validated with torch.profiler and vLLM under AWQ and FP8.",
      result:"3B served 5× the throughput of a 4B at equal latency — KV footprint, not parameters, was binding.",
      flow:["Roofline","KV concurrency","vLLM","torch.profiler","AWQ / FP8","CUDA graphs"], hot:[0,1],
      tech:["vLLM","torch.profiler","Transformer internals","AWQ","FP8","CUDA graphs","PyTorch"]
    },
    {
      id:"specialisation", c:COLORS.green, org:"Independent", year:"2025", kind:"Fine-tuning + eval",
      title:"Small-model specialisation",
      lede:"A QLoRA fine-tune is easy. Proving it improved — and gating CI on that proof — is the work.",
      problem:"Without statistical testing you can't tell an improvement from noise, let alone block a regression.",
      approach:"QLoRA with PEFT and TRL, wrapped in three eval tiers: deterministic checks, LLM-as-judge validated by Cohen's kappa, and McNemar's test for paired significance.",
      result:"A CI gate that fails on a significant regression rather than on a moved average.",
      flow:["Base","QLoRA","Rules","LLM judge","McNemar","CI gate"], hot:[4,5],
      tech:["QLoRA","PEFT","TRL","LLM-as-judge","Cohen's kappa","McNemar","PyTorch"]
    },
    {
      id:"outbreak", c:COLORS.blue, org:"Academic", year:"2024", kind:"Full stack + DL",
      title:"Disease outbreak portal",
      lede:"A CNN reading chest X-rays and an NLP classifier filtering misinformation, in one live dashboard.",
      problem:"During an outbreak, diagnostic signal and public misinformation travel the same channels.",
      approach:"CNN for X-ray disease detection paired with an NLP fake-news classifier, surfaced in a parallax MERN dashboard.",
      result:"97% accuracy on X-ray detection, 92% on fake-news classification.",
      flow:["X-ray","CNN","News feed","NLP filter","Dashboard"], hot:[1,3],
      tech:["CNN","NLP","MERN","Deep learning","Python"],
      link:"https://github.com/Genga28/Disease_Outbreak_Portal-Covid-19-"
    }
  ],

  stack:[
    { h:"AI & LLM systems", c:COLORS.blue,   items:["RAG","Agentic AI","LangGraph","LangChain","MCP","Multi-agent","LLM-as-judge","Prompt engineering","Fine-tuning","QLoRA","PEFT","TRL","GPT-4o","llama.cpp","vLLM"] },
    { h:"Transformer internals", c:COLORS.violet, items:["Attention & KV cache","Decode vs prefill","Roofline analysis","Quantisation — AWQ / FP8","CUDA graphs","torch.profiler","Transformers","RoBERTa","Tokenisation"] },
    { h:"Concurrency & backends", c:COLORS.teal, items:["Async I/O","Polling & queue workers","Multiprocessing","Concurrency design","AWS SQS","FastAPI","Flask","Django","Docker","Kubernetes"] },
    { h:"Speech & vision", c:COLORS.cyan,   items:["ASR","TTS","Whisper","AWS Transcribe","Azure Cognitive","WebRTC","OpenCV","MediaPipe","Dlib","Wav2Lip","OCR","Tesseract","PaddleOCR"] },
    { h:"Data & storage", c:COLORS.amber,   items:["Pinecone","MySQL","MongoDB","Oracle","HiveQL","Power BI","Predictive analytics","Time series"] },
    { h:"Languages & foundations", c:COLORS.pink, items:["Python","R","Java","C++","JavaScript","React","DSA","Operating systems","DBMS","Selenium","PyAutoGUI","RPA"] }
  ],

  videos:{ proctoring:"", rag:"", voice:"", ocr:"", shelf:"", profiling:"", specialisation:"", outbreak:"" },

  posts:[
    {
      tag:"Inference", date:"2025", read:"6 min", cover:"",
      title:"Why a 3B model outserved a 4B by 5×",
      dek:"Parameter count told us nothing about concurrent users per GPU. The KV cache told us everything.",
      body:`<p>Model selection usually happens on a leaderboard — pick the smallest model that clears your quality bar, assume cost scales with parameter count. When I profiled this properly, a 3B served roughly <strong>five times</strong> the throughput of a 4B at equal latency, and the gap had almost nothing to do with the extra billion parameters.</p>
<h3>Decode is memory-bound</h3>
<p>During autoregressive decode you read the entire weight matrix to produce a single token. Arithmetic intensity is terrible. Roofline analysis puts decode firmly on the memory-bandwidth side of the ridge point, so latency tracks <em>bytes moved per token</em>, not FLOPs. That's exactly why <code>AWQ</code> and <code>FP8</code> buy latency — fewer bytes moved, same operation count.</p>
<h3>The real constraint is KV footprint</h3>
<p class="pull">Concurrency is a memory budget problem. Whatever VRAM the weights don't occupy is what you spend on KV cache — and that residue sets your batch size.</p>
<p>The two models differed in hidden size and head configuration in a way that made per-token KV noticeably heavier on the 4B. Once weights were resident, leftover VRAM divided by per-sequence KV gave a much smaller concurrent batch. Fewer sequences in flight means worse batching efficiency, which on a memory-bound workload compounds.</p>
<h3>What I'd check first, next time</h3>
<ul>
<li>Per-token KV bytes at your real context length, not at 512 tokens.</li>
<li>Residual VRAM after weights at your chosen quantisation.</li>
<li>Whether <code>CUDA graphs</code> are actually capturing — ungraphed decode leaves launch overhead on the table at small batch.</li>
<li>Measured throughput under <code>vLLM</code> at target latency, verified with <code>torch.profiler</code>.</li>
</ul>
<p>None of this is exotic. It's just that the number everyone quotes is the one that doesn't predict what you're paying for.</p>`
    },
    {
      tag:"Evaluation", date:"2025", read:"5 min", cover:"",
      title:"Fusing four noisy signals into a defensible score",
      dek:"Any single proctoring detector is wrong often enough to be unusable. The problem is what you do with four.",
      body:`<p>Building a detector is the easy half. The hard half is what happens when four detectors disagree and a person has to act on it.</p>
<h3>Why OR and AND both fail</h3>
<p>Fire on any single detector and you get false accusations — gaze drifts because someone is thinking, not cheating. Require all four to agree and you get silence, because real incidents rarely light up every channel at once. Neither rule is defensible to the person on the receiving end.</p>
<h3>Weighted blend, plus a boost</h3>
<p>A weighted sum handles the ordinary case. But a pure linear blend under-reacts to a single extreme reading — a content signal at 98 gets averaged into irrelevance by three quiet channels.</p>
<p class="pull">So the blend carries an exponential boost keyed on the strongest signal. One channel screaming can escalate the score, without any single channel being able to convict.</p>
<h3>Bands, not verdicts</h3>
<p>Output is calibrated to 0–100 and cut into risk bands, and every score carries the <strong>timestamped episodes</strong> that produced it. A reviewer gets an argument they can audit, not a verdict they must trust. When someone disputes a result, the conversation is about specific moments in a recording — not about whether the model is trustworthy in the abstract.</p>
<ul>
<li>Calibration is a product decision. Band boundaries are where policy lives.</li>
<li>Any score a human will argue with must ship with its evidence attached.</li>
<li>Fusion weights need to be few and named, so non-engineers can review them.</li>
</ul>`
    },
    {
      tag:"Fine-tuning", date:"2025", read:"5 min", cover:"",
      title:"A three-tier eval harness for a small model",
      dek:"QLoRA gave me a number that looked better. Statistics told me whether to believe it.",
      body:`<p>Fine-tuning a small model with <code>QLoRA</code> takes an afternoon. Knowing whether the result is genuinely better — reliably enough to gate CI on — took considerably longer.</p>
<h3>Tier 1 — deterministic</h3>
<p>Format validity, schema conformance, refusal behaviour. Anything with a correct answer. Cheap, runs on every commit, and catches the failures that would otherwise waste judge tokens.</p>
<h3>Tier 2 — judge, with agreement measured</h3>
<p>A judge model scores what resists unit testing. The discipline here isn't the prompt — it's measuring <strong>Cohen's kappa</strong> between judge and human raters on a held-out slice. A judge you haven't validated is a random number generator with good manners.</p>
<h3>Tier 3 — paired significance</h3>
<p class="pull">A moved average is not a result. <strong>McNemar's test</strong> on paired base-versus-tuned outcomes tells you whether the difference survives your actual sample size.</p>
<p>This is the tier that turns evaluation into a gate. CI fails on a statistically significant regression, not on noise — which means the team trusts it enough to leave it on.</p>
<ul>
<li>Each tier costs an order of magnitude more than the last, so cheap checks filter first.</li>
<li>The tiers fail for different reasons, making a red build diagnosable.</li>
<li>Only the top tier claims quality; the lower two claim correctness.</li>
</ul>`
    }
  ],

  links:[
    { k:"Email",    v:"kgenga2002@gmail.com",      href:"mailto:kgenga2002@gmail.com", go:"Write" },
    { k:"Phone",    v:"+91 82488 70532",           href:"tel:+918248870532",           go:"Call" },
    { k:"LinkedIn", v:"linkedin.com/in/gengak",    href:"https://www.linkedin.com/in/gengak", go:"Open ↗" },
    { k:"GitHub",   v:"github.com/Genga28",        href:"https://github.com/Genga28",  go:"Open ↗" },
    { k:"LeetCode", v:"leetcode.com/u/kgenga2811", href:"https://leetcode.com/u/kgenga2811/", go:"Open ↗" },
    { k:"Based in", v:"Bengaluru, India",          href:"",                            go:"IST · UTC+5:30" }
  ]
};

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
  }catch{ /* no published overrides — defaults are fine */ }

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
  $("#roles").innerHTML = SITE.roles.map((r,i) => {
    const jump = (r.systems||[]).length
      ? `<div class="jump"><span>Systems built here:</span>${r.systems.map(id => {
          const c = SITE.cases.find(x => x.id === id);
          return c ? `<a href="#case-${id}">${c.title} →</a>` : "";
        }).join("")}</div>`
      : "";
    return `
    <article class="role${i===0?" open":""}" id="role-${i}" style="--c:${r.c}">
      <button class="role-head" aria-expanded="${i===0}">
        <span class="role-id"><span class="role-co">${r.co}</span><span class="role-title">${r.title}</span></span>
        <span class="role-when">${r.when}<small>${r.where}</small></span>
        <span class="role-toggle" aria-hidden="true"></span>
      </button>
      <div class="role-body"><div><div class="role-inner">
        <ul class="bullets">${r.bullets.map(b => `<li>${b}</li>`).join("")}</ul>
        ${jump}
        <div class="chips">${r.tech.map(t => `<span class="chip">${t}</span>`).join("")}</div>
      </div></div></div>
    </article>`;
  }).join("");
}

const FUSION_HTML = `
<div class="fusion">
  <div>
    <h4>Live — signal fusion</h4>
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
    <p class="gauge-note">Illustrative model — production weights and calibration are proprietary.</p>
  </div>
</div>`;

function demoHTML(c){
  const src = (SITE.videos || {})[c.id];
  if(!src) return "";
  const player = /^https?:\/\//.test(src)
    ? `<iframe src="${src}" title="${c.title} demo" allow="accelerometer; autoplay; clipboard-write; encrypted-media; picture-in-picture" allowfullscreen loading="lazy"></iframe>`
    : `<video src="${src}" controls playsinline preload="metadata"></video>`;
  return `<div class="demo"><div class="demo-frame">${player}</div><p class="demo-cap">Demo — ${c.title}</p></div>`;
}

function renderCases(){
  $("#cases").innerHTML = SITE.cases.map((c,i) => `
    <article class="case${c.feature?" feature":""} reveal" id="case-${c.id}" style="--c:${c.c};--i:${Math.min(i,4)}" data-spot>
      <div class="case-stripe"></div>
      <div class="case-top">
        <div>
          <div class="case-kick"><span class="org">${c.org}</span><span class="dot"></span><span>${c.year}</span><span class="dot"></span><span>${c.kind}</span></div>
          <h3 class="case-title">${c.title}</h3>
          <p class="case-lede">${c.lede}</p>
        </div>
        ${c.badge ? `<span class="case-badge">${c.badge}</span>` : ""}
      </div>
      <div class="case-grid">
        <div class="cg"><h4>Problem</h4><p>${c.problem}</p></div>
        <div class="cg"><h4>Approach</h4><p>${c.approach}</p></div>
        <div class="cg win"><h4>Result</h4><p>${c.result}</p></div>
      </div>
      <div class="flow">${c.flow.map((s,j) => {
        const hot = (c.hot||[]).includes(j) ? " hot" : "";
        const arr = j < c.flow.length-1 ? '<span class="flow-arr" aria-hidden="true"></span>' : "";
        return `<span class="flow-step${hot}">${s}</span>${arr}`;
      }).join("")}</div>
      ${c.fusion ? FUSION_HTML : ""}
      ${demoHTML(c)}
      <div class="case-foot">
        <div class="chips">${c.tech.map(t => `<span class="chip">${t}</span>`).join("")}</div>
        ${c.link ? `<a class="btn btn-sm" href="${c.link}" target="_blank" rel="noopener">Source <span class="arr" aria-hidden="true">↗</span></a>` : ""}
      </div>
    </article>`).join("");
}

function renderStack(){
  $("#stackGrid").innerHTML = SITE.stack.map(g => `
    <div class="stack-col" style="--c:${g.c}">
      <h3>${g.h}<span>${g.items.length}</span></h3>
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
    const label = href === "#top" ? "Intro" : href.slice(1);
    return `<a href="${href}" style="--c:${c}"><span class="dot"></span><span class="lbl">${label[0].toUpperCase()+label.slice(1)}</span></a>`;
  }).join("");
  for(const [href,c] of Object.entries(SECTION_COLOR)){
    const el = document.querySelector(href);
    if(el) el.style.setProperty("--sec", c);
  }
}

function renderAll(){
  renderHero(); renderTimeline(); renderRoles(); renderCases();
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
  $("#roles").onclick = e => {
    const head = e.target.closest(".role-head");
    if(!head) return;
    const role = head.closest(".role");
    const open = role.classList.toggle("open");
    head.setAttribute("aria-expanded", String(open));
  };

  $("#timeline").onclick = e => {
    const row = e.target.closest("[data-role]");
    if(!row) return;
    const role = $("#role-" + row.dataset.role);
    if(!role) return;
    role.classList.add("open");
    role.querySelector(".role-head").setAttribute("aria-expanded","true");
    goTo(role);
  };

  $("#posts").onclick = e => {
    const b = e.target.closest("[data-post]");
    if(b) openPost(+b.dataset.post);
  };

  if(matchMedia("(pointer:fine)").matches){
    $$("[data-spot]").forEach(card => {
      card.addEventListener("pointermove", ev => {
        const r = card.getBoundingClientRect();
        card.style.setProperty("--mx",(ev.clientX-r.left)+"px");
        card.style.setProperty("--my",(ev.clientY-r.top)+"px");
      });
    });
  }

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
  try{ await navigator.clipboard.writeText(b.dataset.copy); say("Copied — " + b.dataset.copy); }
  catch{ say("Copy blocked — " + b.dataset.copy); }
});

$("#resumeBtn").addEventListener("click", async e => {
  const url = SITE.profile.resume;
  try{ const r = await fetch(url, { method:"HEAD" }); if(r.ok){ e.currentTarget.href = url; return; } }catch{}
  e.preventDefault();
  say("Résumé not uploaded yet — email kgenga2002@gmail.com");
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
  if(hasDraft) showDraftBar();
  if(location.hash === "#admin") openAdmin();
  initAdmin();
});
