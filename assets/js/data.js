/* ============================================================
   All site content lives here. Both pages read it.
   Copy rule: a recruiter scans for eight seconds. One line per
   idea, plain words, the number first. No paragraphs.
   ============================================================ */

const COLORS = {
  blue:"#7AB8FF", teal:"#5FD9C4", violet:"#B49BF5",
  cyan:"#5FC9F0", amber:"#F5BE8B", pink:"#F49BB8", green:"#8FE39A"
};

/* ------------------------------------------------------------------
   Turn whatever you paste into something a player can actually load.

   A Google Drive "share" link opens a Drive page, not a video, so it
   will not play in an <iframe> until /view is swapped for /preview.
   Same story for a YouTube watch URL, a Vimeo page and a Loom share.
   Paste the normal link from the address bar; this sorts it out.

   Returns { kind: "file" | "frame", url }.
   ------------------------------------------------------------------ */
function embedUrl(src){
  src = (src || "").trim();
  if(!src) return null;
  if(!/^https?:\/\//i.test(src)) return { kind:"file", url:src };

  let m;

  // Google Drive: /file/d/ID/..., ?id=ID, /open?id=ID
  if(/drive\.google\.com/i.test(src)){
    m = src.match(/\/file\/d\/([A-Za-z0-9_-]{10,})/) || src.match(/[?&]id=([A-Za-z0-9_-]{10,})/);
    if(m) return { kind:"frame", url:`https://drive.google.com/file/d/${m[1]}/preview` };
  }

  // YouTube: watch?v=ID, youtu.be/ID, /shorts/ID, already /embed/
  if(/youtube\.com|youtu\.be/i.test(src)){
    m = src.match(/[?&]v=([A-Za-z0-9_-]{6,})/)
      || src.match(/youtu\.be\/([A-Za-z0-9_-]{6,})/)
      || src.match(/\/(?:embed|shorts)\/([A-Za-z0-9_-]{6,})/);
    if(m) return { kind:"frame", url:`https://www.youtube.com/embed/${m[1]}?rel=0&autoplay=1` };
  }

  // Vimeo
  if(/vimeo\.com/i.test(src)){
    m = src.match(/vimeo\.com\/(?:video\/)?(\d{6,})/);
    if(m) return { kind:"frame", url:`https://player.vimeo.com/video/${m[1]}?autoplay=1` };
  }

  // Loom
  if(/loom\.com/i.test(src)){
    m = src.match(/loom\.com\/(?:share|embed)\/([A-Za-z0-9]{10,})/);
    if(m) return { kind:"frame", url:`https://www.loom.com/embed/${m[1]}` };
  }

  // A direct .mp4/.webm on a CDN can be played natively; anything else, frame it.
  if(/\.(mp4|webm|ogg|mov)(\?|$)/i.test(src)) return { kind:"file", url:src };
  return { kind:"frame", url:src };
}

/* Drive share link -> its thumbnail image, used as the video poster. */
function thumbUrl(src){
  const m = (src || "").match(/drive\.google\.com\/.*?(?:\/file\/d\/|[?&]id=)([A-Za-z0-9_-]{10,})/);
  return m ? `https://drive.google.com/thumbnail?id=${m[1]}&sz=w1280` : "";
}

const SECTION_COLOR = {
  "#top":COLORS.blue, "#demos":COLORS.violet, "#work":COLORS.teal,
  "#projects":COLORS.amber, "#stack":COLORS.cyan, "#writing":COLORS.pink, "#contact":COLORS.green
};

const DEFAULTS = {
  profile: {
    name:"Genga K",
    kicker:"Applied AI Engineer",
    location:"Bengaluru, India",
    photo:"assets/img/genga.jpg",
    resume:"assets/pdfs/GENGA_K_RESUME.pdf",
    available:true,
    availableText:"Open to AI / ML engineering roles",
    headline:["I build AI","that works in","production."],
    lede:"Voice agents, document AI and computer vision. Built end to end, running live."
  },

  telemetry:[
    { v:"<i>3</i>+",   k:"Years building AI" },
    { v:"~<i>5K</i>",  k:"Documents a day, automated" },
    { v:"<i>50</i>",   k:"Live sessions at once" },
    { v:"<i>10</i>",   k:"Systems shipped" }
  ],

  /* One line and one number per role. The timeline graph reads start/end. */
  roles:[
    {
      co:"Jobtwine", title:"AI Engineer", when:"Jul 2025 – Present", where:"Bengaluru",
      start:[2025,7], end:null, c:COLORS.blue,
      line:"Own the AI stack behind live interviews: RAG, voice, proctoring and the async backend.",
      metric:"10–50 live sessions"
    },
    {
      co:"Space Marvel AI", title:"AI Consultant · Freelance", when:"Jan – Jul 2025", where:"Remote",
      start:[2025,1], end:[2025,7], c:COLORS.violet,
      line:"Led a three-person team: tele-caller bot, voice desktop agent, shelf auditing.",
      metric:"200 calls / day"
    },
    {
      co:"Yubi", title:"Data Scientist Intern", when:"Dec 2024 – Jun 2025", where:"Chennai",
      start:[2024,12], end:[2025,6], c:COLORS.teal,
      line:"OCR, LLM classification and tamper checks in live loan processing.",
      metric:"~5,000 docs / day"
    },
    {
      co:"EXL Health", title:"Data Engineer Intern · R&D", when:"Jun – Nov 2023", where:"Chennai",
      start:[2023,6], end:[2023,11], c:COLORS.amber,
      line:"RPA bots for apps with no API, plus NLP on scraped data.",
      metric:"95% less task time"
    },
    {
      co:"Elamigo", title:"Data Science Intern", when:"Dec 2022 – Feb 2023", where:"Bengaluru",
      start:[2022,12], end:[2023,2], c:COLORS.pink,
      line:"Scraped ~40 sectors into a queryable database for partnership research.",
      metric:"15+ insights"
    }
  ],

  /* Projects without a demo video. The first one carries the interactive model. */
  cases:[
    {
      id:"proctoring", feature:true, c:COLORS.blue, org:"Jobtwine", kind:"Real-time scoring",
      title:"Proctoring score fusion",
      lede:"Four detectors, one 0–100 score a hiring panel can defend. Drag the sliders.",
      fusion:true
    },
    {
      id:"rag", c:COLORS.violet, org:"Jobtwine", kind:"Retrieval",
      title:"Real-time RAG interviewer",
      win:"50K chunks, no drift",
      lede:"Grounds a live interviewer in role rubrics without adding audible lag.",
      tech:["Pinecone","LangGraph","FastAPI"]
    },
    {
      id:"shelf", c:COLORS.pink, org:"Space Marvel AI", kind:"CV + VLM",
      title:"Retail shelf auditing",
      win:"No retraining per product",
      lede:"Segmentation finds products, a vision model names and counts them.",
      tech:["VLM","OpenCV","FastAPI"]
    },
    {
      id:"profiling", c:COLORS.cyan, org:"Independent", kind:"Inference",
      title:"A 3B model beat a 4B by 5×",
      win:"5× throughput, same latency",
      lede:"KV-cache memory, not parameter count, decides users per GPU.",
      tech:["vLLM","torch.profiler","AWQ / FP8"],
      link:"https://github.com/Genga28/Genga28.github.io/blob/main/demos/independent/P2_LLM_Inference_Profiling.ipynb"
    },
    {
      id:"specialisation", c:COLORS.green, org:"Independent", kind:"Fine-tuning",
      title:"QLoRA with a real eval gate",
      win:"CI fails only on real regressions",
      lede:"Rules, a validated LLM judge and a McNemar test decide if a fine-tune helped.",
      tech:["QLoRA","LLM-as-judge","McNemar"],
      link:"https://github.com/Genga28/Genga28.github.io/blob/main/demos/independent/P3_QLoRA_Eval_Harness.ipynb"
    },
    {
      id:"outbreak", c:COLORS.amber, org:"Academic", kind:"Deep learning",
      title:"Disease outbreak portal",
      win:"97% X-ray · 92% fake news",
      lede:"A CNN reads chest X-rays; an NLP model filters misinformation.",
      tech:["CNN","NLP","MERN"],
      link:"https://github.com/Genga28/Disease_Outbreak_Portal-Covid-19-"
    }
  ],

  /* Demo videos. Video links live in `videos` below, keyed by id. */
  demos:[
    {
      id:"voice", c:COLORS.teal, tag:"Voice AI",
      poster:"assets/img/demos/voice.jpg",
      title:"Voice agent you can interrupt",
      line:"Talk over it and it stops. Live captions and a lip-synced avatar.",
      tech:["WebRTC","Whisper","Piper"],
      flow:["Mic","Whisper","LLM","Piper","Avatar"],
      src:"https://github.com/Genga28/Genga28.github.io/tree/main/demos/03_voice_agent"
    },
    {
      id:"ocr", c:COLORS.amber, tag:"Document AI",
      poster:"assets/img/demos/ocr.jpg",
      title:"Layout-preserving OCR",
      line:"Keeps the columns, so numbers stay next to their labels.",
      tech:["PaddleOCR","FastAPI"],
      flow:["Scan","Detect","Grid","Columns","Text"],
      src:"https://github.com/Genga28/Genga28.github.io/tree/main/demos/05_ocr_layout"
    },
    {
      id:"proctoring", c:COLORS.blue, tag:"Computer vision",
      poster:"assets/img/demos/proctoring.jpg",
      title:"Gaze & presence tracker",
      line:"Tracks eyes, head pose and extra faces from a webcam, then fuses them into one live 0–100 risk score.",
      tech:["MediaPipe","OpenCV","Python"],
      flow:["Webcam","Face mesh","Gaze + pose","Fusion","Score"],
      src:"https://github.com/Genga28/Genga28.github.io/tree/main/demos/04_proctoring"
    },
    {
      id:"rpa", c:COLORS.violet, tag:"Desktop RPA",
      poster:"assets/img/demos/rpa.jpg",
      title:"GUI bot that sees the screen",
      line:"Finds buttons by sight, downloads an invoice, reads it, fills Excel. No API.",
      tech:["PyAutoGUI","OpenCV","Tesseract"],
      flow:["Portal","Find","Click","Read","Excel"],
      src:"https://github.com/Genga28/Genga28.github.io/tree/main/demos/01_rpa_desktop"
    },
    {
      id:"webauto", c:COLORS.pink, tag:"Web automation",
      poster:"assets/img/demos/webauto.jpg",
      title:"Selenium data collector",
      line:"Drives real Chrome, extracts structured data, writes a clean workbook.",
      tech:["Selenium","requests","openpyxl"],
      flow:["Browser","Search","Extract","Enrich","Excel"],
      src:"https://github.com/Genga28/Genga28.github.io/tree/main/demos/02_web_automation"
    }
  ],

  videos:{
    proctoring:"https://drive.google.com/file/d/1y5sJhYn5ZrbgMbcxv0sq0CMsNrjqP_9x/view?usp=drive_link",
    voice:     "https://drive.google.com/file/d/1zA10CWWJ10OAhgmpfRF1IhD6LrRCu_mw/view?usp=drive_link",
    ocr:       "https://drive.google.com/file/d/1n_ZOj3oXsXF4WSovQq5t0t1WMOmzxjev/view?usp=drive_link",
    rpa:       "https://drive.google.com/file/d/1R54XW0ECbx0IVNYdmfMM1Kb3PpGXJQf3/view?usp=drive_link",
    webauto:   "https://drive.google.com/file/d/1haDsEnIEzwGJpjhdah5rOJ_aZQvk1dxt/view?usp=drive_link"
  },

  stack:[
    { h:"AI & LLMs",        c:COLORS.blue,   items:["RAG","Agentic AI","LangGraph","LangChain","MCP","QLoRA","vLLM","LLM-as-judge","GPT-4o","llama.cpp"] },
    { h:"Speech & vision",  c:COLORS.teal,   items:["Whisper","ASR / TTS","WebRTC","OpenCV","MediaPipe","PaddleOCR","Tesseract","Wav2Lip"] },
    { h:"Backend & infra",  c:COLORS.violet, items:["Python","FastAPI","Async I/O","AWS SQS","SageMaker","Docker","Kubernetes"] },
    { h:"Data & automation",c:COLORS.amber,  items:["Pinecone","MySQL","MongoDB","Selenium","PyAutoGUI","Power BI"] }
  ],

  posts:[
    {
      tag:"Inference", date:"2025", read:"6 min", cover:"",
      title:"Why a 3B model beat a 4B by 5×",
      dek:"Parameter count said nothing about how many users one GPU could hold. The memory did.",
      body:`<p>Model selection usually happens on a leaderboard: pick the smallest model that clears your quality bar, assume cost scales with parameter count. When I profiled this properly, a 3B served roughly <strong>five times</strong> the throughput of a 4B at equal latency, and the gap had almost nothing to do with the extra billion parameters.</p>
<h3>Decode is memory-bound</h3>
<p>During autoregressive decode you read the entire weight matrix to produce a single token. Arithmetic intensity is terrible. Roofline analysis puts decode firmly on the memory-bandwidth side of the ridge point, so latency tracks <em>bytes moved per token</em>, not FLOPs. That's exactly why <code>AWQ</code> and <code>FP8</code> buy latency: fewer bytes moved, same operation count.</p>
<h3>The real constraint is KV footprint</h3>
<p class="pull">Concurrency is a memory budget problem. Whatever VRAM the weights don't occupy is what you spend on KV cache, and that residue sets your batch size.</p>
<p>The two models differed in hidden size and head configuration in a way that made per-token KV noticeably heavier on the 4B. Once weights were resident, leftover VRAM divided by per-sequence KV gave a much smaller concurrent batch. Fewer sequences in flight means worse batching efficiency, which on a memory-bound workload compounds.</p>
<h3>What I'd check first, next time</h3>
<ul>
<li>Per-token KV bytes at your real context length, not at 512 tokens.</li>
<li>Residual VRAM after weights at your chosen quantisation.</li>
<li>Whether <code>CUDA graphs</code> are actually capturing, since ungraphed decode leaves launch overhead on the table at small batch.</li>
<li>Measured throughput at target latency, verified with <code>torch.profiler</code>.</li>
</ul>
<p>None of this is exotic. It's just that the number everyone quotes is the one that doesn't predict what you're paying for.</p>`
    },
    {
      tag:"Evaluation", date:"2025", read:"5 min", cover:"",
      title:"Turning four unreliable signals into one you can defend",
      dek:"Any single cheating detector is wrong often enough to be useless. The problem is what you do with four.",
      body:`<p>Building a detector is the easy half. The hard half is what happens when four detectors disagree and a person has to act on it.</p>
<h3>Why OR and AND both fail</h3>
<p>Fire on any single detector and you get false accusations: gaze drifts because someone is thinking, not cheating. Require all four to agree and you get silence, because real incidents rarely light up every channel at once. Neither rule is defensible to the person on the receiving end.</p>
<h3>Weighted blend, plus a boost</h3>
<p>A weighted sum handles the ordinary case. But a pure linear blend under-reacts to a single extreme reading. A content signal at 98 gets averaged into irrelevance by three quiet channels.</p>
<p class="pull">So the blend carries an exponential boost keyed on the strongest signal. One channel screaming can escalate the score, without any single channel being able to convict.</p>
<h3>Bands, not verdicts</h3>
<p>Output is calibrated to 0–100 and cut into risk bands, and every score carries the <strong>timestamped episodes</strong> that produced it. A reviewer gets an argument they can audit, not a verdict they must trust. When someone disputes a result, the conversation is about specific moments in a recording, not about whether the model is trustworthy in the abstract.</p>
<ul>
<li>Calibration is a product decision. Band boundaries are where policy lives.</li>
<li>Any score a human will argue with must ship with its evidence attached.</li>
<li>Fusion weights need to be few and named, so non-engineers can review them.</li>
</ul>`
    },
    {
      tag:"Fine-tuning", date:"2025", read:"5 min", cover:"",
      title:"How to know a fine-tune actually worked",
      dek:"QLoRA gave me a number that looked better. Statistics told me whether to believe it.",
      body:`<p>Fine-tuning a small model with <code>QLoRA</code> takes an afternoon. Knowing whether the result is genuinely better, reliably enough to gate a build on, took considerably longer.</p>
<h3>Tier 1: deterministic</h3>
<p>Format validity, schema conformance, refusal behaviour. Anything with a correct answer. Cheap, runs on every commit, and catches the failures that would otherwise waste judge tokens.</p>
<h3>Tier 2: judge, with agreement measured</h3>
<p>A judge model scores what resists unit testing. The discipline here isn't the prompt. It's measuring <strong>Cohen's kappa</strong> between judge and human raters on a held-out slice. A judge you haven't validated is a random number generator with good manners.</p>
<h3>Tier 3: paired significance</h3>
<p class="pull">A moved average is not a result. <strong>McNemar's test</strong> on paired base-versus-tuned outcomes tells you whether the difference survives your actual sample size.</p>
<p>This is the tier that turns evaluation into a gate. The build fails on a statistically significant regression, not on noise, which means the team trusts it enough to leave it on.</p>
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
