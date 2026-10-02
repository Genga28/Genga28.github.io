/* ============================================================
   ADMIN: edit the site from the browser
   ------------------------------------------------------------
   Open with  #admin  in the URL, or Ctrl+Shift+E.

   HOW PUBLISHING WORKS (read this once):
   This is a static site, so there is no server to save to. Edits
   go to localStorage, which only YOU see, in THIS browser. To
   publish them to everyone you download content.json and commit
   it next to index.html. The site loads that file on every visit.

   The passcode below only hides the panel from casual clicking.
   It is client-side, so anyone can read it in the source. It is
   convenience, not security. Never put anything private here.
   ============================================================ */

const ADMIN_PASS = "genga";

let adminUnlocked = false;
let editingPost = -1;

/* ---------------- draft bar ---------------- */
function showDraftBar(){
  if($("#draftBar")) return;
  const bar = document.createElement("div");
  bar.className = "draft-bar";
  bar.id = "draftBar";
  bar.innerHTML = `
    <span><b>Local draft active.</b> Only you can see these edits. Publish them with Download content.json.</span>
    <button class="btn btn-sm" data-admin-open>Open editor</button>
    <button class="btn btn-sm" data-draft-discard>Discard draft</button>`;
  document.body.appendChild(bar);
}
function hideDraftBar(){ $("#draftBar")?.remove(); }

/* ---------------- panel shell ---------------- */
function buildAdmin(){
  if($("#admin")) return;
  const el = document.createElement("div");
  el.className = "admin";
  el.id = "admin";
  el.hidden = true;
  el.innerHTML = `
    <div class="admin-bg" data-admin-close></div>
    <section class="admin-panel" role="dialog" aria-modal="true" aria-label="Site editor">
      <div class="admin-head">
        <div class="row">
          <h2>Site editor</h2>
          <button class="btn btn-sm" data-admin-close>Close</button>
        </div>
        <p id="adminSub">Edits save to this browser. Download content.json to publish.</p>
        <div class="admin-tabs" id="adminTabs" hidden>
          <button data-tab="profile" class="on">Profile</button>
          <button data-tab="posts">Writing</button>
          <button data-tab="videos">Demo videos</button>
          <button data-tab="publish">Publish</button>
        </div>
      </div>
      <div class="admin-body" id="adminBody"></div>
      <div class="admin-foot" id="adminFoot" hidden>
        <button class="btn btn-sm btn-primary" data-save>Save draft</button>
        <button class="btn btn-sm" data-download>Download content.json</button>
        <button class="btn btn-sm" data-copy-json>Copy JSON</button>
      </div>
    </section>`;
  document.body.appendChild(el);
}

function openAdmin(){
  buildAdmin();
  const el = $("#admin");
  el.hidden = false;
  requestAnimationFrame(() => el.classList.add("on"));
  if(lenis) lenis.stop();
  renderAdmin();
}
function closeAdmin(){
  const el = $("#admin");
  if(!el) return;
  el.classList.remove("on");
  if(lenis) lenis.start();
  setTimeout(() => { el.hidden = true; }, 600);
  if(location.hash === "#admin") history.replaceState(null,"",location.pathname + location.search);
}

/* ---------------- rendering ---------------- */
let adminTab = "profile";

function renderAdmin(){
  const body = $("#adminBody");
  $("#adminTabs").hidden = !adminUnlocked;
  $("#adminFoot").hidden = !adminUnlocked;

  if(!adminUnlocked){
    $("#adminSub").textContent = "Enter the passcode to edit.";
    body.innerHTML = `
      <div class="gate">
        <div class="fld">
          <label for="adminPass">Passcode</label>
          <input id="adminPass" type="text" autocomplete="off" placeholder="passcode">
        </div>
        <button class="btn btn-primary" data-unlock>Unlock editor</button>
        <p class="admin-note">This gate is client-side only. It hides the panel, it does not secure anything. Change <code>ADMIN_PASS</code> in <code>assets/js/admin.js</code>.</p>
      </div>`;
    $("#adminPass").onkeydown = e => { if(e.key === "Enter") tryUnlock(); };
    return;
  }

  $("#adminSub").textContent = "Edits save to this browser. Download content.json and commit it to publish.";
  $$("#adminTabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === adminTab));

  if(adminTab === "profile") renderProfileTab(body);
  if(adminTab === "posts")   renderPostsTab(body);
  if(adminTab === "videos")  renderVideosTab(body);
  if(adminTab === "publish") renderPublishTab(body);
}

function field(label, id, value, hint){
  return `<div class="fld">
    <label for="${id}">${label}</label>
    <input id="${id}" type="text" value="">
    ${hint ? `<small>${hint}</small>` : ""}
  </div>`;
}

function renderProfileTab(body){
  const p = SITE.profile;
  body.innerHTML = `
    <div class="fld">
      <label>Profile photo</label>
      <div class="drop" id="photoDrop">
        ${p.photo ? `<img src="${p.photo}" alt="">` : `<span class="ph">🙂</span>`}
        <div><b>Click or drop an image</b><span>Portrait crop works best. Keep it under 600 KB.</span></div>
      </div>
      <small>Stored inside content.json as a data URI, so it travels with the site. For a large photo, save it to <code>assets/img/genga.jpg</code> instead and put that path in the field below.</small>
    </div>
    ${field("Photo path (if not uploading)","f-photo",p.photo)}
    <div class="fld-row">
      ${field("Name","f-name",p.name)}
      ${field("Role","f-kicker",p.kicker)}
      ${field("Location","f-location",p.location)}
    </div>
    ${field("Availability text","f-availText",p.availableText,"Shown in the pill at the top. Clear it to hide the pill.")}
    <div class="fld">
      <label>Headline, one line each</label>
      <input id="f-h0" type="text"><input id="f-h1" type="text" style="margin-top:8px"><input id="f-h2" type="text" style="margin-top:8px">
      <small>The last word of the last line gets the gradient treatment.</small>
    </div>
    <div class="fld">
      <label for="f-lede">Intro paragraph</label>
      <textarea id="f-lede" style="min-height:110px"></textarea>
      <small>Basic HTML is allowed. Use <code>&lt;strong&gt;</code> for emphasis.</small>
    </div>
    ${field("Résumé file","f-resume",p.resume)}`;

  $("#f-photo").value    = p.photo || "";
  $("#f-name").value     = p.name || "";
  $("#f-kicker").value   = p.kicker || "";
  $("#f-location").value = p.location || "";
  $("#f-availText").value= p.availableText || "";
  $("#f-h0").value = p.headline[0] || "";
  $("#f-h1").value = p.headline[1] || "";
  $("#f-h2").value = p.headline[2] || "";
  $("#f-lede").value   = p.lede || "";
  $("#f-resume").value = p.resume || "";

  wireDrop($("#photoDrop"), dataUrl => {
    SITE.profile.photo = dataUrl;
    renderAdmin();
    renderHero();
  });

  body.oninput = () => {
    SITE.profile = {
      ...SITE.profile,
      photo: $("#f-photo").value.trim(),
      name: $("#f-name").value,
      kicker: $("#f-kicker").value,
      location: $("#f-location").value,
      availableText: $("#f-availText").value,
      available: !!$("#f-availText").value.trim(),
      headline: [$("#f-h0").value, $("#f-h1").value, $("#f-h2").value].filter(Boolean),
      lede: $("#f-lede").value,
      resume: $("#f-resume").value
    };
    renderHero();
  };
}

function renderPostsTab(body){
  if(editingPost > -1){ renderPostEditor(body); return; }
  body.innerHTML = `
    <div class="fld"><label>Published notes</label>
      <small>Newest first is how they appear. Add as many as you like.</small></div>
    <div class="plist" id="plist">${
      SITE.posts.map((p,i) => `
        <div class="pitem">
          <div class="t"><b>${p.title || "Untitled"}</b><span>${[p.tag,p.date,p.read].filter(Boolean).join(" · ")}</span></div>
          <button data-up="${i}" title="Move up">↑</button>
          <button data-edit="${i}">Edit</button>
          <button class="del" data-del="${i}">Delete</button>
        </div>`).join("") || `<p class="admin-note">No notes yet.</p>`
    }</div>
    <button class="btn btn-sm" data-newpost>+ New note</button>`;

  body.onclick = e => {
    const up = e.target.closest("[data-up]"), ed = e.target.closest("[data-edit]"),
          dl = e.target.closest("[data-del]"), nw = e.target.closest("[data-newpost]");
    if(up){
      const i = +up.dataset.up;
      if(i > 0){ const a = SITE.posts; [a[i-1],a[i]] = [a[i],a[i-1]]; renderAdmin(); renderPosts(); bindDynamic(); }
    }
    if(ed){ editingPost = +ed.dataset.edit; renderAdmin(); }
    if(dl){
      const i = +dl.dataset.del;
      if(confirm(`Delete "${SITE.posts[i].title}"?`)){ SITE.posts.splice(i,1); renderAdmin(); renderPosts(); bindDynamic(); }
    }
    if(nw){
      SITE.posts.unshift({ tag:"Note", date:String(new Date().getFullYear()), read:"3 min", cover:"", title:"New note", dek:"", body:"<p>Start writing…</p>" });
      editingPost = 0;
      renderAdmin(); renderPosts(); bindDynamic();
    }
  };
}

function renderPostEditor(body){
  const p = SITE.posts[editingPost];
  body.innerHTML = `
    <div class="fld"><label>Editing note</label><small>Changes show on the page as you type.</small></div>
    ${field("Title","p-title",p.title)}
    <div class="fld-row">
      ${field("Tag","p-tag",p.tag)}
      ${field("Date","p-date",p.date)}
      ${field("Read time","p-read",p.read)}
    </div>
    <div class="fld">
      <label for="p-dek">Summary</label>
      <textarea id="p-dek" style="min-height:80px"></textarea>
      <small>One sentence. This is the card preview.</small>
    </div>
    <div class="fld">
      <label>Cover image</label>
      <div class="drop" id="coverDrop">
        ${p.cover ? `<img src="${p.cover}" alt="">` : `<span class="ph">🖼</span>`}
        <div><b>Click or drop an image</b><span>Optional. Shows on the card and at the top of the note.</span></div>
      </div>
    </div>
    <div class="fld">
      <label for="p-body">Body</label>
      <textarea id="p-body" style="min-height:300px"></textarea>
      <small>HTML. Use <code>&lt;h3&gt;</code> for headings, <code>&lt;p class="pull"&gt;</code> for a pull quote, <code>&lt;code&gt;</code> for inline code, <code>&lt;ul&gt;&lt;li&gt;</code> for lists, <code>&lt;img src="…"&gt;</code> for images.</small>
    </div>
    <div style="display:flex;gap:10px">
      <button class="btn btn-sm" data-back>← Back to list</button>
    </div>`;

  $("#p-title").value = p.title || "";
  $("#p-tag").value   = p.tag || "";
  $("#p-date").value  = p.date || "";
  $("#p-read").value  = p.read || "";
  $("#p-dek").value   = p.dek || "";
  $("#p-body").value  = p.body || "";

  wireDrop($("#coverDrop"), dataUrl => {
    SITE.posts[editingPost].cover = dataUrl;
    renderAdmin(); renderPosts(); bindDynamic();
  });

  body.oninput = () => {
    Object.assign(SITE.posts[editingPost], {
      title:$("#p-title").value, tag:$("#p-tag").value, date:$("#p-date").value,
      read:$("#p-read").value, dek:$("#p-dek").value, body:$("#p-body").value
    });
    renderPosts(); bindDynamic();
  };
  body.onclick = e => { if(e.target.closest("[data-back]")){ editingPost = -1; renderAdmin(); } };
}

function renderVideosTab(body){
  body.innerHTML = `
    <div class="fld"><label>Demo videos</label>
      <small>Paste a normal share link and it is converted automatically: Google Drive,
      YouTube, Vimeo or Loom all work. A local path like <code>assets/video/proctor.mp4</code>
      works too. Leave blank for no player.<br>
      <b>Drive only:</b> set the file to <i>Anyone with the link</i> or viewers get a sign-in page.</small></div>
    ${SITE.cases.map(c => `
      <div class="fld">
        <label for="vid-${c.id}">${c.title}</label>
        <input id="vid-${c.id}" type="text" data-vid="${c.id}">
      </div>`).join("")}`;
  SITE.cases.forEach(c => { $("#vid-"+c.id).value = (SITE.videos||{})[c.id] || ""; });
  body.oninput = e => {
    const el = e.target.closest("[data-vid]");
    if(!el) return;
    SITE.videos = { ...SITE.videos, [el.dataset.vid]: el.value.trim() };
    renderCases(); bindDynamic(); observeReveals();
  };
}

function renderPublishTab(body){
  const json = exportJSON();
  const kb = (new Blob([json]).size / 1024).toFixed(0);
  body.innerHTML = `
    <div class="fld"><label>Publishing</label>
      <small>Everything you change here lives in this browser only. To make it visible to everyone:</small></div>
    <ol class="admin-note" style="border:0;padding-left:20px;font-size:15px;line-height:1.7;color:var(--txt-2)">
      <li>Press <b>Download content.json</b> below (or <b>Copy JSON</b> and paste it into a file).</li>
      <li>Put <code>content.json</code> next to <code>index.html</code>.</li>
      <li><code>git add content.json &amp;&amp; git commit -m "Update notes" &amp;&amp; git push</code></li>
    </ol>
    <div class="fld">
      <label>Current content.json (${kb} KB)</label>
      <textarea readonly style="min-height:220px" id="jsonOut"></textarea>
      <small>Images you uploaded are embedded here as data URIs, which is why this can get large.</small>
    </div>
    <button class="btn btn-sm" data-discard>Discard local draft and reload</button>`;
  $("#jsonOut").value = json;
  body.onclick = e => { if(e.target.closest("[data-discard]")) discardDraft(); };
}

/* ---------------- image upload ---------------- */
function wireDrop(el, cb){
  if(!el) return;
  const input = document.createElement("input");
  input.type = "file"; input.accept = "image/*"; input.hidden = true;
  el.appendChild(input);

  const read = file => {
    if(!file || !file.type.startsWith("image/")) return say("That file isn't an image.");
    if(file.size > 1.5 * 1024 * 1024) return say("Too big. Keep images under 1.5 MB.");
    const fr = new FileReader();
    fr.onload = () => cb(fr.result);
    fr.onerror = () => say("Could not read that file.");
    fr.readAsDataURL(file);
  };

  el.onclick = e => { if(e.target !== input) input.click(); };
  input.onchange = () => read(input.files[0]);
  el.ondragover = e => { e.preventDefault(); el.classList.add("over"); };
  el.ondragleave = () => el.classList.remove("over");
  el.ondrop = e => { e.preventDefault(); el.classList.remove("over"); read(e.dataTransfer.files[0]); };
}

/* ---------------- persistence ---------------- */
function exportJSON(){
  return JSON.stringify({
    profile: SITE.profile,
    posts:   SITE.posts,
    videos:  SITE.videos
  }, null, 2);
}

function saveDraft(){
  try{
    localStorage.setItem(DRAFT_KEY, exportJSON());
    hasDraft = true;
    showDraftBar();
    say("Draft saved to this browser.");
  }catch{
    say("Browser storage is full or blocked. Use Download instead.");
  }
}

function discardDraft(){
  try{ localStorage.removeItem(DRAFT_KEY); }catch{}
  hideDraftBar();
  location.reload();
}

function downloadJSON(){
  try{
    const blob = new Blob([exportJSON()], { type:"application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "content.json";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    say("content.json downloaded. Commit it to publish.");
  }catch{
    say("Download blocked here. Use Copy JSON instead.");
  }
}

function tryUnlock(){
  const v = $("#adminPass")?.value.trim();
  if(v === ADMIN_PASS){ adminUnlocked = true; renderAdmin(); }
  else say("Wrong passcode.");
}

/* ---------------- wiring ---------------- */
function initAdmin(){
  document.addEventListener("click", e => {
    if(e.target.closest("[data-admin-open]")) return openAdmin();
    if(e.target.closest("[data-admin-close]")) return closeAdmin();
    if(e.target.closest("[data-draft-discard]")) return discardDraft();
    if(e.target.closest("[data-unlock]")) return tryUnlock();
    if(e.target.closest("[data-save]")) return saveDraft();
    if(e.target.closest("[data-download]")) return downloadJSON();
    if(e.target.closest("[data-copy-json]")){
      navigator.clipboard.writeText(exportJSON())
        .then(() => say("content.json copied to clipboard."))
        .catch(() => say("Clipboard blocked. Select the text in the Publish tab."));
      return;
    }
    const tab = e.target.closest("#adminTabs [data-tab]");
    if(tab){ adminTab = tab.dataset.tab; editingPost = -1; renderAdmin(); }
  });

  addEventListener("keydown", e => {
    if(e.ctrlKey && e.shiftKey && (e.key === "E" || e.key === "e")){ e.preventDefault(); openAdmin(); }
    if(e.key === "Escape" && $("#admin") && !$("#admin").hidden) closeAdmin();
  });

  addEventListener("hashchange", () => { if(location.hash === "#admin") openAdmin(); });
}
