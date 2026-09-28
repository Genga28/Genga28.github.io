/* Aria - room client.
   WebRTC to the local Python peer, a WebSocket for captions and state, and a
   Three.js head whose jaw is driven by the actual amplitude of the audio
   coming back over the wire. */

import * as THREE from "three";

const $ = (s) => document.querySelector(s);
const body = document.body;

const els = {
  gate: $("#gate"), join: $("#joinBtn"), badges: $("#badges"),
  state: $("#stateText"), capUser: $("#capUser"), capAgent: $("#capAgent"),
  audio: $("#agentAudio"), cam: $("#cam"), pip: $("#pip"), level: $("#level"),
};

let pc, ws, session, analyser, levelData;
let mouth = 0;              // smoothed 0..1 drive for the jaw
let pipeState = "idle";

/* ---------------------------------------------------------------- level bars */
const BARS = 18;
const bars = [];
for (let i = 0; i < BARS; i++) {
  const b = document.createElement("i");
  els.level.appendChild(b);
  bars.push(b);
}

/* ---------------------------------------------------------------- 3D avatar */
const canvas = $("#scene");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
camera.position.set(0, 0.05, 4.1);

const COL = { blue: 0x7ab8ff, violet: 0xb49bf5, teal: 0x5fd9c4, pink: 0xf49bb8 };

scene.add(new THREE.AmbientLight(0x4a5a78, 1.1));
const key = new THREE.DirectionalLight(COL.blue, 2.6); key.position.set(3, 3, 5); scene.add(key);
const rim = new THREE.DirectionalLight(COL.violet, 2.2); rim.position.set(-4, 1, -3); scene.add(rim);
const warm = new THREE.PointLight(COL.pink, 14, 12); warm.position.set(0, -2, 3); scene.add(warm);

const head = new THREE.Group();
scene.add(head);

// Skull: an icosahedron scaled into a face-ish oval reads better than a sphere.
const skin = new THREE.MeshStandardMaterial({
  color: 0x131c2b, roughness: 0.34, metalness: 0.62,
  emissive: 0x0b1a2e, emissiveIntensity: 0.55,
});
const skull = new THREE.Mesh(new THREE.IcosahedronGeometry(1, 6), skin);
skull.scale.set(0.86, 1.06, 0.84);
head.add(skull);

// Wireframe shell, so the head reads as synthetic rather than a grey blob.
const shell = new THREE.Mesh(
  new THREE.IcosahedronGeometry(1.015, 3),
  new THREE.MeshBasicMaterial({ color: COL.blue, wireframe: true, transparent: true, opacity: 0.16 })
);
shell.scale.copy(skull.scale);
head.add(shell);

const eyeGeo = new THREE.SphereGeometry(0.1, 32, 32);
const eyeMat = new THREE.MeshStandardMaterial({
  color: 0xffffff, emissive: COL.blue, emissiveIntensity: 2.6, roughness: 0.15,
});
const eyes = [-1, 1].map((s) => {
  const e = new THREE.Mesh(eyeGeo, eyeMat);
  e.position.set(0.27 * s, 0.14, 0.74);
  head.add(e);
  return e;
});

// Jaw: a torus arc that opens. Cheap, and it tracks amplitude convincingly.
const mouthMat = new THREE.MeshStandardMaterial({
  color: 0x0a0f18, emissive: COL.teal, emissiveIntensity: 1.5, roughness: 0.3,
});
const mouthMesh = new THREE.Mesh(new THREE.CapsuleGeometry(0.055, 0.34, 6, 16), mouthMat);
mouthMesh.rotation.z = Math.PI / 2;
mouthMesh.position.set(0, -0.34, 0.74);
head.add(mouthMesh);

// Halo + particles
const halo = new THREE.Mesh(
  new THREE.TorusGeometry(1.52, 0.006, 8, 160),
  new THREE.MeshBasicMaterial({ color: COL.violet, transparent: true, opacity: 0.5 })
);
halo.rotation.x = Math.PI / 2.3;
scene.add(halo);

const COUNT = 900;
const pPos = new Float32Array(COUNT * 3);
const pSeed = new Float32Array(COUNT);
for (let i = 0; i < COUNT; i++) {
  const r = 1.9 + Math.random() * 2.4;
  const th = Math.random() * Math.PI * 2;
  const ph = Math.acos(2 * Math.random() - 1);
  pPos[i * 3] = r * Math.sin(ph) * Math.cos(th);
  pPos[i * 3 + 1] = r * Math.cos(ph) * 0.62;
  pPos[i * 3 + 2] = r * Math.sin(ph) * Math.sin(th);
  pSeed[i] = Math.random() * Math.PI * 2;
}
const pGeo = new THREE.BufferGeometry();
pGeo.setAttribute("position", new THREE.BufferAttribute(pPos, 3));
const dust = new THREE.Points(
  pGeo,
  new THREE.PointsMaterial({ color: COL.teal, size: 0.021, transparent: true, opacity: 0.55, depthWrite: false })
);
scene.add(dust);

function resize() {
  const r = canvas.getBoundingClientRect();
  if (!r.width || !r.height) return;
  renderer.setSize(r.width, r.height, false);
  camera.aspect = r.width / r.height;
  camera.updateProjectionMatrix();
}
addEventListener("resize", resize);
new ResizeObserver(resize).observe(canvas);
resize();

let blinkAt = 2;
const clock = new THREE.Clock();

function frame() {
  requestAnimationFrame(frame);
  const t = clock.getElapsedTime();
  const dt = Math.min(clock.getDelta(), 0.05);

  // amplitude of the agent's audio -> jaw
  let amp = 0;
  if (analyser) {
    analyser.getByteTimeDomainData(levelData);
    let sum = 0;
    for (let i = 0; i < levelData.length; i++) {
      const v = (levelData[i] - 128) / 128;
      sum += v * v;
    }
    amp = Math.min(1, Math.sqrt(sum / levelData.length) * 7.5);
  }
  mouth += (amp - mouth) * Math.min(1, dt * 18);

  mouthMesh.scale.y = 1 + mouth * 3.6;
  mouthMesh.scale.x = 1 - mouth * 0.28;
  mouthMat.emissiveIntensity = 1.2 + mouth * 3.4;

  for (let i = 0; i < BARS; i++) {
    const wob = 0.45 + 0.55 * Math.sin(t * 9 + i * 0.7);
    const h = 4 + mouth * 30 * wob;
    bars[i].style.height = h.toFixed(1) + "px";
    bars[i].style.opacity = (0.28 + mouth * 0.72).toFixed(2);
  }

  // idle motion so it never looks frozen
  head.rotation.y = Math.sin(t * 0.42) * 0.17;
  head.rotation.x = Math.sin(t * 0.31) * 0.07 + mouth * 0.05;
  head.position.y = Math.sin(t * 0.85) * 0.035;

  if (t > blinkAt) {
    const k = (t - blinkAt) / 0.14;
    const s = k < 1 ? Math.max(0.06, Math.abs(Math.cos(k * Math.PI))) : 1;
    eyes.forEach((e) => (e.scale.y = s));
    if (k >= 1) blinkAt = t + 2.2 + Math.random() * 3.4;
  }
  const pulse = pipeState === "thinking" ? 1.6 + Math.sin(t * 7) * 1.1 : 2.4 + mouth * 3.2;
  eyeMat.emissiveIntensity = pulse;
  eyeMat.color.set(pipeState === "thinking" ? COL.violet : 0xffffff);

  halo.rotation.z += dt * (pipeState === "thinking" ? 1.5 : 0.22);
  halo.scale.setScalar(1 + mouth * 0.09);
  halo.material.opacity = 0.32 + mouth * 0.5;

  const pa = pGeo.attributes.position;
  for (let i = 0; i < COUNT; i++) {
    const base = pPos[i * 3 + 1];
    pa.array[i * 3 + 1] = base + Math.sin(t * 0.7 + pSeed[i]) * (0.06 + mouth * 0.34);
  }
  pa.needsUpdate = true;
  dust.rotation.y += dt * 0.045;
  dust.material.opacity = 0.34 + mouth * 0.5;

  skin.emissiveIntensity = 0.42 + mouth * 0.9;
  shell.material.opacity = 0.12 + mouth * 0.3;

  renderer.render(scene, camera);
}
frame();

/* ---------------------------------------------------------------- captions */
function setState(s, note) {
  pipeState = s;
  body.className = s;
  els.state.textContent =
    { listening: "listening", thinking: "thinking", speaking: "speaking", idle: "waiting to join" }[s] || s;
  if (note) els.state.textContent += " · " + note;
}

function showCaption(el, text, animateWords) {
  if (!text) { el.classList.remove("on"); return; }
  if (animateWords) {
    el.innerHTML = text
      .split(/\s+/)
      .map((w, i) => `<span class="w" style="animation-delay:${i * 26}ms">${w}</span>`)
      .join(" ");
  } else {
    el.textContent = text;
  }
  el.classList.add("on");
}

function badges(info) {
  els.badges.innerHTML = [
    ["brain", info.brain === "claude" ? "Claude Opus 5" : "scripted"],
    ["stt", "faster-whisper"],
    ["tts", info.tts || "-"],
    ["room", "aiortc · local"],
  ]
    .map(([k, v]) => `<span class="badge"><span class="d"></span>${k} <b>${v}</b></span>`)
    .join("");
}

/* ---------------------------------------------------------------- connect */
async function join() {
  els.join.disabled = true;
  els.join.textContent = "connecting…";

  let mic;
  try {
    mic = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
    });
  } catch (err) {
    els.join.disabled = false;
    els.join.textContent = "Microphone blocked — retry";
    console.error(err);
    return;
  }

  // Camera is cosmetic: it stays local and is never added to the peer connection.
  try {
    const cam = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } });
    els.cam.srcObject = cam;
    els.pip.classList.add("on");
  } catch { /* no camera, no problem */ }

  pc = new RTCPeerConnection({ iceServers: [] }); // same machine: host candidates only
  mic.getTracks().forEach((t) => pc.addTrack(t, mic));
  pc.addTransceiver("audio", { direction: "recvonly" });

  pc.ontrack = (ev) => {
    els.audio.srcObject = ev.streams[0];
    els.audio.play().catch(() => {});
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const src = ctx.createMediaStreamSource(ev.streams[0]);
    analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;
    levelData = new Uint8Array(analyser.fftSize);
    src.connect(analyser);           // analyser only, playback goes through <audio>
  };

  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  await new Promise((res) => {
    if (pc.iceGatheringState === "complete") return res();
    const check = () => pc.iceGatheringState === "complete" && (pc.removeEventListener("icegatheringstatechange", check), res());
    pc.addEventListener("icegatheringstatechange", check);
    setTimeout(res, 1200);
  });

  const r = await fetch("/offer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sdp: pc.localDescription.sdp, type: pc.localDescription.type }),
  });
  const answer = await r.json();
  session = answer.session;
  await pc.setRemoteDescription(answer);

  ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/${session}`);
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.type === "ready") badges(m);
    if (m.type === "state") setState(m.state, m.note);
    if (m.type === "caption") {
      if (m.who === "user") showCaption(els.capUser, m.text, false);
      else showCaption(els.capAgent, m.text, m.final);
    }
  };
  ws.onclose = () => setState("idle");

  els.gate.classList.add("gone");
  setState("listening");
}

els.join.addEventListener("click", join);
addEventListener("beforeunload", () => { try { pc && pc.close(); ws && ws.close(); } catch {} });
