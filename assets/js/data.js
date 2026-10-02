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
    resume:"assets/pdfs/GENGA_K_RESUME.pdf",
    available:true,
    availableText:"Open to AI / ML engineering roles",
    headline:["I build AI","systems that hold","up in production."],
    lede:"Voice agents, document automation and real-time video analysis. Built end to end, running live."
  },

  telemetry:[
    { v:"<i>3</i>+",   k:"Years building AI" },
    { v:"~<i>5K</i>",  k:"Documents a day, automated" },
    { v:"<i>50</i>",   k:"Live sessions at once" },
    { v:"<i>10</i>",   k:"Systems shipped" }
  ],

  roles:[
    {
      co:"Jobtwine", title:"AI Engineer", when:"Jul 2025 – Present", where:"Bengaluru",
      start:[2025,7], end:null, c:COLORS.blue,
      bullets:[
        "Own the AI stack end to end: retrieval, async backends, guardrails, observability.",
        "Async FastAPI backend with a <b>10-worker SQS queue</b> and polling concurrency, holding <span class='num'>10–50</span> live sessions.",
        "Built the interview tooling: JD-to-playbook generator, resume shortlister, generated debriefs."
      ],
      systems:["proctoring","rag","voice"],
      tech:["Python","RoBERTa","MediaPipe","OpenCV","Wav2Lip","ASR","TTS","LangGraph","SQS","RAG","Pinecone","LangChain","FastAPI","MCP","Agentic AI"]
    },
    {
      co:"Space Marvel AI", title:"AI Consultant · Freelance", when:"Jan – Jul 2025", where:"Remote",
      start:[2025,1], end:[2025,7], c:COLORS.violet,
      bullets:[
        "Led a <b>three-person team</b> across three AI products. Owned architecture and design reviews.",
        "Outbound tele-caller bot on ASR to LLM to TTS, at <span class='num'>200 calls/day</span>.",
        "Voice-driven desktop agent that automates multi-step workflows by tool calling."
      ],
      systems:["shelf"],
      tech:["Python","LLM agents","VLM","OpenCV","ASR/TTS","Tool calling","FastAPI"]
    },
    {
      co:"Yubi", title:"Data Scientist Intern", when:"Dec 2024 – Jun 2025", where:"Chennai",
      start:[2024,12], end:[2025,6], c:COLORS.teal,
      bullets:[
        "OCR and LLM classification APIs in loan processing at <span class='num'>~5,000 docs/day</span>.",
        "Tamper and signature validation, flagging low-trust documents before underwriting.",
        "ASR/TTS bot reading behavioural signals around repayment intent."
      ],
      systems:["ocr"],
      tech:["Python","GPT-4o","llama.cpp","Fine-tuning","OCR","FastAPI","AWS SageMaker","Transformers","Whisper"]
    },
    {
      co:"EXL Health", title:"Data Engineer Intern · R&D", when:"Jun – Nov 2023", where:"Chennai",
      start:[2023,6], end:[2023,11], c:COLORS.amber,
      bullets:[
        "RPA bots driving desktop and web interfaces with no API available.",
        "Text mining and NLP on scraped data, cutting task time by <span class='num'>95%</span>.",
        "Custom ETL tool, <span class='num'>60%</span> faster processing."
      ],
      systems:["rpa","webauto"],
      tech:["Python","Lackey","PyAutoGUI","Tesseract OCR","Selenium","HiveQL","RPA","NLP"]
    },
    {
      co:"Elamigo", title:"Data Science Intern", when:"Dec 2022 – Feb 2023", where:"Bengaluru",
      start:[2022,12], end:[2023,2], c:COLORS.pink,
      bullets:[
        "Scraped <span class='num'>~40</span> industry sectors into a queryable database, surfacing <span class='num'>15+</span> partnership insights."
      ],
      tech:["MySQL","BeautifulSoup","Selenium","Power BI"]
    }
  ],

  /* Each card leads with the outcome. Detail sits behind the toggle. */
  cases:[
    {
      id:"proctoring", feature:true, badge:"Flagship", c:COLORS.blue,
      org:"Jobtwine", year:"2025", kind:"Real-time scoring",
      title:"Multi-signal AI proctoring",
      lede:"Four detectors watching a live interview, fused into one score a hiring panel can defend.",
      win:"0–100, fully auditable",
      problem:"Fire on one detector and you get false accusations. Require all four and you get silence.",
      approach:"Weighted blend plus an exponential boost, so one extreme reading escalates without convicting alone.",
      result:"Every score traces back to the timestamped moments that caused it.",
      flow:["Live session","Content","AI-likeliness","Audio","Video","Fusion","0–100"], hot:[5,6],
      tech:["Python","RoBERTa","MediaPipe","OpenCV","Wav2Lip","ASR","Multiprocessing"],
      fusion:true
    },
    {
      id:"rag", c:COLORS.violet, org:"Jobtwine", year:"2025", kind:"Retrieval",
      title:"Real-time RAG interviewer",
      lede:"Grounds a live interviewer in role rubrics, fast enough that the candidate never hears it.",
      win:"50K chunks, no drift",
      problem:"An ungrounded interviewer invents requirements and wanders off the rubric mid-session.",
      approach:"Retrieve against live conversation state, inject only what the current turn needs.",
      result:"Every question traces to a retrieved chunk.",
      flow:["Turn state","Query","Pinecone","Rerank","Prompt","LLM"], hot:[2,5],
      tech:["RAG","Pinecone","LangChain","LangGraph","FastAPI","Python"]
    },
    {
      id:"voice", c:COLORS.teal, org:"Jobtwine", year:"2025", kind:"Real-time voice",
      title:"WebRTC voice agent",
      lede:"Streaming speech with barge-in. Talk over it and it actually stops.",
      win:"10–50 concurrent calls",
      problem:"Turn-based agents feel like walkie-talkies. Streaming ones talk over people.",
      approach:"Dual-mode transport, barge-in detection, clean cancellation, memory across turns.",
      result:"Conversations that hold their thread across a full interview.",
      flow:["WebRTC","Barge-in","ASR","Agent","TTS"], hot:[1,3],
      tech:["WebRTC","ASR","TTS","LangGraph","Agentic AI","Python"]
    },
    {
      id:"ocr", c:COLORS.amber, org:"Yubi", year:"2024–25", kind:"Document AI",
      title:"Layout-preserving OCR",
      lede:"Rebuilds multi-column financial PDFs at pixel level, so numbers keep their labels.",
      win:"Beat Textract on 30+ doc types",
      problem:"Standard OCR flattens layout, a figure lands on the wrong label, and a loan gets written on it.",
      approach:"Replicate pixel coordinates and spacing; rules where the format is known, LLM where it is not.",
      result:"Ran at ~5,000 documents a day in live loan processing.",
      flow:["PDF","Layout","Rules","LLM","Replay","Key-values"], hot:[2,3],
      tech:["PaddleOCR","GPT-4o","llama.cpp","Transformers","AWS SageMaker","FastAPI"]
    },
    {
      id:"shelf", c:COLORS.pink, org:"Space Marvel AI", year:"2025", kind:"CV + VLM",
      title:"Retail shelf auditing",
      lede:"Segmentation finds the products, a vision model reads what they are and how many.",
      win:"No retraining per product",
      problem:"Manual audits are stale on arrival, and detection models need retraining for every new product.",
      approach:"Segment the shelf into clusters, then let a VLM name and count what is inside each.",
      result:"Automated restock alerts with no per-product model to maintain.",
      flow:["Shelf photo","Segment","Crops","VLM","Restock alert"], hot:[1,3],
      tech:["VLM","OpenCV","Python","LLM agents","FastAPI"]
    },
    {
      id:"profiling", c:COLORS.cyan, org:"Independent", year:"2025", kind:"Inference economics",
      title:"A 3B model beat a 4B by 5×",
      lede:"Memory, not parameter count, decides how many users one GPU can serve.",
      win:"5× throughput, same latency",
      problem:"Model choice was made on benchmark scores, which say nothing about concurrent users.",
      approach:"Roofline decode model plus a KV-cache concurrency model, validated under vLLM.",
      result:"The smaller model served five times the traffic at equal latency.",
      flow:["Roofline","KV cache","vLLM","Profiler","AWQ / FP8","CUDA graphs"], hot:[0,1],
      tech:["vLLM","torch.profiler","Transformer internals","AWQ","FP8","PyTorch"],
      link:"https://github.com/Genga28/Genga28.github.io/blob/main/demos/independent/P2_LLM_Inference_Profiling.ipynb"
    },
    {
      id:"specialisation", c:COLORS.green, org:"Independent", year:"2025", kind:"Fine-tuning",
      title:"Small-model specialisation",
      lede:"Fine-tuning is the easy half. Proving it improved is the work.",
      win:"CI gate on real significance",
      problem:"Without statistical testing you cannot tell an improvement from noise.",
      approach:"QLoRA, then three eval tiers: rules, a validated LLM judge, and a paired significance test.",
      result:"A build that fails on a real regression instead of a moved average.",
      flow:["Base","QLoRA","Rules","Judge","McNemar","CI gate"], hot:[4,5],
      tech:["QLoRA","PEFT","TRL","LLM-as-judge","Cohen's kappa","McNemar"],
      link:"https://github.com/Genga28/Genga28.github.io/blob/main/demos/independent/P3_QLoRA_Eval_Harness.ipynb"
    },
    {
      id:"outbreak", c:COLORS.blue, org:"Academic", year:"2024", kind:"Deep learning",
      title:"Disease outbreak portal",
      lede:"A CNN reads chest X-rays while an NLP model filters the misinformation around them.",
      win:"97% and 92% accuracy",
      problem:"In an outbreak, diagnosis and misinformation travel through the same channels.",
      approach:"Two models behind one live dashboard.",
      result:"97% on X-ray detection, 92% on fake-news classification.",
      flow:["X-ray","CNN","News","NLP","Dashboard"], hot:[1,3],
      tech:["CNN","NLP","MERN","Deep learning","Python"],
      link:"https://github.com/Genga28/Disease_Outbreak_Portal-Covid-19-"
    },
    {
      id:"rpa", c:COLORS.amber, org:"Demo build", year:"2026", kind:"Desktop RPA",
      title:"Screen-driven automation",
      lede:"Reads the screen, moves the real cursor, lands the invoice in a spreadsheet.",
      win:"Works with no API at all",
      problem:"Legacy desktop software has no API. Automating it means working from pixels.",
      approach:"Colour-anchor targeting survives any zoom or screen scaling, then OCR and a written workbook.",
      result:"End to end with no vendor RPA licence.",
      flow:["Portal","Find control","Click","Download","OCR","Excel"], hot:[1,4],
      tech:["PyAutoGUI","OpenCV","Tesseract","openpyxl","Python"],
      link:"https://github.com/Genga28/Genga28.github.io/tree/main/demos/01_rpa_desktop"
    },
    {
      id:"webauto", c:COLORS.teal, org:"Demo build", year:"2026", kind:"Web automation",
      title:"Browser-driven collection",
      lede:"Drives a real browser, reads structured data out, and tabulates it.",
      win:"Runs twice without breaking",
      problem:"The obvious target blocks you within a few queries and takes the run down with it.",
      approach:"A source that permits it, enriched from a public API, written to a filtered workbook.",
      result:"A collector that survives being run again tomorrow.",
      flow:["Search","Article","Structure","Public API","Excel"], hot:[2,3],
      tech:["Selenium","requests","openpyxl","Python"],
      link:"https://github.com/Genga28/Genga28.github.io/tree/main/demos/02_web_automation"
    }
  ],

  /* The demos page. Each one runs locally; source is on GitHub. */
  demos:[
    {
      id:"proctoring", c:COLORS.blue, tag:"Computer vision",
      title:"Live proctoring that scores what it sees",
      line:"Tracks your eyes, your head and who else is in frame, then fuses all of it into one number in real time.",
      points:["Iris-level gaze tracking","Head pose from a 3D face model","Flags moments, not just a verdict"],
      tech:["MediaPipe","OpenCV","NumPy","Python"],
      flow:["Webcam","Face mesh","Gaze + pose","Fusion","0–100 score"],
      src:"https://github.com/Genga28/Genga28.github.io/tree/main/demos/04_proctoring"
    },
    {
      id:"voice", c:COLORS.teal, tag:"Voice AI",
      title:"A voice agent you can interrupt",
      line:"Real conversation in the browser with a 3D avatar, live captions, and speech that stops the moment you talk over it.",
      points:["Runs entirely on one machine","Speaks before it finishes thinking","Avatar lip-syncs to real audio"],
      tech:["WebRTC","Whisper","Piper","Claude","Three.js"],
      flow:["Mic","Whisper","Claude","Piper","Avatar"],
      src:"https://github.com/Genga28/Genga28.github.io/tree/main/demos/03_voice_agent"
    },
    {
      id:"ocr", c:COLORS.amber, tag:"Document AI",
      title:"OCR that keeps the page layout",
      line:"Most OCR flattens a document and quietly attaches numbers to the wrong labels. This one keeps the columns.",
      points:["Side-by-side with the flattened version","Finds the column structure itself","Exports clean text"],
      tech:["PaddleOCR","FastAPI","NumPy","Python"],
      flow:["Scan","Detect","Character grid","Columns","Text"],
      src:"https://github.com/Genga28/Genga28.github.io/tree/main/demos/05_ocr_layout"
    },
    {
      id:"rpa", c:COLORS.violet, tag:"Automation",
      title:"A bot that uses the screen like a person",
      line:"Opens the portal, finds the button by looking at it, clicks, downloads the invoice, reads it, fills the spreadsheet.",
      points:["No API, no integration","Survives zoom and screen scaling","Ends in a formatted workbook"],
      tech:["PyAutoGUI","OpenCV","Tesseract","openpyxl"],
      flow:["Portal","Find","Click","Read","Excel"],
      src:"https://github.com/Genga28/Genga28.github.io/tree/main/demos/01_rpa_desktop"
    },
    {
      id:"webauto", c:COLORS.pink, tag:"Automation",
      title:"Browser automation that doesn't get blocked",
      line:"Drives a real Chrome window through a reference source and turns what it finds into a clean table.",
      points:["Picks a source that permits it","Enriched from a public API","Filtered, formatted output"],
      tech:["Selenium","requests","openpyxl"],
      flow:["Browser","Search","Extract","Enrich","Excel"],
      src:"https://github.com/Genga28/Genga28.github.io/tree/main/demos/02_web_automation"
    }
  ],

  stack:[
    { h:"AI & LLM systems", c:COLORS.blue,   items:["RAG","Agentic AI","LangGraph","LangChain","MCP","Multi-agent","LLM-as-judge","Prompt engineering","Fine-tuning","QLoRA","PEFT","TRL","GPT-4o","llama.cpp","vLLM"] },
    { h:"Transformer internals", c:COLORS.violet, items:["Attention & KV cache","Decode vs prefill","Roofline analysis","Quantisation (AWQ, FP8)","CUDA graphs","torch.profiler","Transformers","RoBERTa"] },
    { h:"Concurrency & backends", c:COLORS.teal, items:["Async I/O","Polling & queue workers","Multiprocessing","AWS SQS","FastAPI","Flask","Django","Docker","Kubernetes"] },
    { h:"Speech & vision", c:COLORS.cyan,   items:["ASR","TTS","Whisper","AWS Transcribe","Azure Cognitive","WebRTC","OpenCV","MediaPipe","Dlib","Wav2Lip","OCR","PaddleOCR","Tesseract"] },
    { h:"Data & storage", c:COLORS.amber,   items:["Pinecone","MySQL","MongoDB","Oracle","HiveQL","Power BI","Predictive analytics","Time series"] },
    { h:"Languages & foundations", c:COLORS.pink, items:["Python","R","Java","C++","JavaScript","React","DSA","Operating systems","DBMS","Selenium","PyAutoGUI","RPA"] }
  ],

  videos:{ proctoring:"", rag:"", voice:"", ocr:"", shelf:"", profiling:"",
           specialisation:"", outbreak:"", rpa:"", webauto:"" },

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
