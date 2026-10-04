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
  leave: $("#leaveBtn"),
};

let pc, ws, session, analyser, levelData;
let mouth = 0;              // smoothed 0..1 drive for the jaw
let forcedMouth = null;     // set by the pose harness only; null in normal use
let pipeState = "idle";

/* ---------------------------------------------------------------- level bars */
const BARS = 18;
const bars = [];
for (let i = 0; i < BARS; i++) {
  const b = document.createElement("i");
  els.level.appendChild(b);
  bars.push(b);
}

/* ---------------------------------------------------------------- 3D avatar
   A procedural human bust. Everything is built from primitives at load time:
   no GLB to download, no loader, no licence to track, and it still reads as a
   person because what sells "alive" is motion, not polygons. Breathing,
   blinks at irregular intervals, eyes that drift and come back, a jaw hinged
   where a jaw actually hinges.

   One rule holds the whole thing together: the head's proportions are baked
   into its geometry rather than applied as a mesh scale. A scale on the skull
   does not reach its sibling meshes, so every eye, lip and nostril placed
   beside it would land somewhere off the face. With the scale baked, head
   space is real space and surfZ() can put a feature exactly on the skin. */
const canvas = $("#scene");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 100);
camera.position.set(0, 0.10, 5.0);

const COL = { blue: 0x7ab8ff, violet: 0xb49bf5, teal: 0x5fd9c4, pink: 0xf49bb8 };
const SKIN = 0xd99f78, SKIN_DEEP = 0xb87a56, HAIR = 0x221b22, LIP = 0xa8615c;

// Head half-axes. Every feature position below is in these units.
const AX = 0.74, AY = 0.92, AZ = 0.80;
const surfZ = (x, y) =>
  AZ * Math.sqrt(Math.max(0, 1 - (x / AX) ** 2 - (y / AY) ** 2));

/* Three-point portrait lighting: warm key, cool fill, violet rim. A face lit
   flat from the front reads as a mask. */
scene.add(new THREE.HemisphereLight(0x93a9cc, 0x3a2b33, 1.0));
const key = new THREE.DirectionalLight(0xfff1e2, 2.4);
key.position.set(2.4, 2.8, 4.4);
scene.add(key);
const fill = new THREE.DirectionalLight(COL.blue, 0.75);
fill.position.set(-3.4, 0.2, 2.6);
scene.add(fill);
const rim = new THREE.DirectionalLight(COL.violet, 2.0);
rim.position.set(-2.0, 2.2, -3.2);
scene.add(rim);

const avatar = new THREE.Group();
avatar.position.y = -0.85;
scene.add(avatar);

const skin = new THREE.MeshStandardMaterial({ color: SKIN, roughness: 0.64, metalness: 0.02 });
const skinDeep = new THREE.MeshStandardMaterial({ color: SKIN_DEEP, roughness: 0.68, metalness: 0.02 });
const hairMat = new THREE.MeshStandardMaterial({ color: HAIR, roughness: 0.82, metalness: 0.04 });
const lipMat = new THREE.MeshStandardMaterial({ color: LIP, roughness: 0.42, metalness: 0.02 });

/* ---- head ---------------------------------------------------------------
   A sphere is a ball. Four displacements make it a head: a jaw that narrows
   towards the chin, a brow ridge, cheekbones, and a back that is flatter than
   a sphere. The jaw taper is kept gentle and pushed low with a high exponent,
   because taking it up into the cheeks turns the face into a cone. */
function shapeSkull(geo, scaleY = 1) {
  const p = geo.attributes.position;
  const v = new THREE.Vector3();
  for (let i = 0; i < p.count; i++) {
    v.fromBufferAttribute(p, i);
    const y = v.y;
    const front = Math.max(0, v.z);

    const jaw = y < 0 ? Math.pow(-y, 2.4) : 0;
    const narrow = 1 - jaw * 0.30;
    v.x *= narrow;
    v.z *= narrow;

    const brow = Math.exp(-(((y - 0.20) / 0.10) ** 2)) * front * 0.06;
    const cheek = Math.exp(-(((y + 0.06) / 0.18) ** 2))
                * Math.exp(-(((Math.abs(v.x) - 0.55) / 0.22) ** 2)) * 0.05;
    v.z = (v.z + brow + cheek) * (v.z < 0 ? 0.93 : 1);
    p.setXYZ(i, v.x, v.y * scaleY, v.z);
  }
  geo.computeVertexNormals();
}

const head = new THREE.Group();
head.position.y = 1.15;
avatar.add(head);

const skullGeo = new THREE.SphereGeometry(1, 72, 56);
shapeSkull(skullGeo);
skullGeo.scale(AX, AY, AZ);        // baked, so head space is real space
head.add(new THREE.Mesh(skullGeo, skin));

/* ---- hair ---------------------------------------------------------------
   A cap cut at a constant angle gives a hairline that is level all the way
   round, which leaves the back of the skull bare. So: a cap for the top and
   fringe, and a second fuller shape for the back and sides. */
// A cap cut at a constant angle gives a level brim all the way round, which
// reads as a beanie. Dropping the edge towards the back and the sides, and
// keeping it high over the brows, gives something closer to a hairline.
const HAIRLINE = 0.42;             // at the forehead; brows sit at 0.27
const capGeo = new THREE.SphereGeometry(1, 64, 44, 0, Math.PI * 2, 0, Math.PI * 0.62);
shapeSkull(capGeo);
{
  const p = capGeo.attributes.position;
  const v = new THREE.Vector3();
  for (let i = 0; i < p.count; i++) {
    v.fromBufferAttribute(p, i);
    const front = (v.z + 1) / 2;                      // 0 at the back, 1 at the front
    const floor = HAIRLINE * front + -0.55 * (1 - front);
    if (v.y < floor) {
      const k = Math.max(0.12, Math.hypot(v.x, v.z));  // keep the shell on the skull
      v.multiplyScalar(1);
      v.y = floor;
      const r = Math.hypot(v.x, v.z) || 1e-6;
      const want = Math.sqrt(Math.max(0.02, 1 - floor * floor));
      v.x *= want / r;
      v.z *= want / r;
      void k;
    }
    p.setXYZ(i, v.x, v.y, v.z);
  }
  capGeo.computeVertexNormals();
}
capGeo.scale(AX * 1.05, AY * 1.035, AZ * 1.05);
head.add(new THREE.Mesh(capGeo, hairMat));

// Rear half only. phi runs around Y with +Z at a quarter turn, so pi to two
// pi is exactly the back; a full shell here is a sack over the face.
const backGeo = new THREE.SphereGeometry(1, 48, 36, Math.PI, Math.PI, 0, Math.PI * 0.78);
shapeSkull(backGeo);
backGeo.scale(AX * 1.05, AY * 1.03, AZ * 1.05);
const backHair = new THREE.Mesh(backGeo, hairMat);
backHair.position.z = -0.03;
head.add(backHair);

// Sideburns, so the cap does not stop in mid air at the temples.
[-1, 1].forEach((sd) => {
  const side = new THREE.Mesh(new THREE.SphereGeometry(0.15, 20, 16), hairMat);
  side.scale.set(0.42, 1.5, 1.1);
  side.position.set(AX * 0.9 * sd, 0.16, -0.1);
  head.add(side);
});

/* ---- ears -------------------------------------------------------------- */
[-1, 1].forEach((s) => {
  const ear = new THREE.Mesh(new THREE.SphereGeometry(0.1, 20, 16), skinDeep);
  ear.scale.set(0.34, 1.05, 0.7);
  ear.position.set(AX * 0.96 * s, -0.04, -0.04);
  head.add(ear);
});

/* ---- nose -------------------------------------------------------------- */
const bridge = new THREE.Mesh(new THREE.CapsuleGeometry(0.062, 0.17, 6, 14), skin);
bridge.scale.set(1.15, 1, 1.0);
bridge.position.set(0, -0.085, surfZ(0, -0.085) - 0.055);
bridge.rotation.x = 0.3;
head.add(bridge);
const tip = new THREE.Mesh(new THREE.SphereGeometry(0.072, 20, 16), skin);
tip.scale.set(1.25, 0.88, 1.0);
tip.position.set(0, -0.175, surfZ(0, -0.175) + 0.022);
head.add(tip);
[-1, 1].forEach((s) => {
  const nostril = new THREE.Mesh(new THREE.SphereGeometry(0.04, 14, 12), skinDeep);
  nostril.scale.set(1, 0.8, 1);
  nostril.position.set(0.058 * s, -0.198, surfZ(0, -0.198) + 0.004);
  head.add(nostril);
});

/* ---- eyes ---------------------------------------------------------------
   Eyeball, iris, pupil and two lids as separate meshes, so the eyes can
   actually look somewhere and actually close. A painted-on eye can do
   neither, and both are things people read instantly. */
const EYE_X = 0.272, EYE_Y = 0.075, EYE_R = 0.118;
const EYE_Z = surfZ(EYE_X, EYE_Y) - 0.098;   // set in, not stuck on
const scleraMat = new THREE.MeshStandardMaterial({ color: 0xf4efe9, roughness: 0.2 });
const irisMat = new THREE.MeshStandardMaterial({
  color: 0x5a3a20, roughness: 0.16, metalness: 0.08,
  emissive: 0x2a1a0c, emissiveIntensity: 0.35,
});
const lidMat = new THREE.MeshStandardMaterial({ color: SKIN, roughness: 0.62, side: THREE.DoubleSide });
const browMat = new THREE.MeshStandardMaterial({ color: HAIR, roughness: 0.85 });
const BROW_Y = 0.27;

const eyes = [-1, 1].map((s) => {
  const socket = new THREE.Group();
  socket.position.set(EYE_X * s, EYE_Y, EYE_Z);
  head.add(socket);

  const ball = new THREE.Mesh(new THREE.SphereGeometry(EYE_R, 28, 22), scleraMat);
  socket.add(ball);

  // the iris rides on the ball, so rotating the ball aims the gaze
  const iris = new THREE.Mesh(new THREE.CircleGeometry(0.05, 28), irisMat);
  iris.position.z = EYE_R * 0.975;
  ball.add(iris);
  iris.add(new THREE.Mesh(new THREE.CircleGeometry(0.022, 20),
    new THREE.MeshBasicMaterial({ color: 0x0a0708 })).translateZ(0.002));
  const glint = new THREE.Mesh(new THREE.CircleGeometry(0.013, 12),
    new THREE.MeshBasicMaterial({ color: 0xffffff }));
  glint.position.set(0.021, 0.023, 0.004);
  iris.add(glint);

  const upper = new THREE.Mesh(
    new THREE.SphereGeometry(EYE_R * 1.08, 24, 18, 0, Math.PI * 2, 0, Math.PI * 0.54), lidMat);
  upper.scale.x = 1.22;              // wider than the ball, to cover the corners
  socket.add(upper);
  const lower = new THREE.Mesh(
    new THREE.SphereGeometry(EYE_R * 1.07, 24, 18, 0, Math.PI * 2, Math.PI * 0.56, Math.PI * 0.44),
    lidMat);
  lower.scale.x = 1.22;
  socket.add(lower);

  const brow = new THREE.Mesh(new THREE.CapsuleGeometry(0.032, 0.2, 5, 12), browMat);
  brow.rotation.z = Math.PI / 2;
  brow.rotation.y = -0.18 * s;
  brow.position.set(EYE_X * s, BROW_Y, surfZ(EYE_X * s, BROW_Y) + 0.01);
  head.add(brow);

  return { socket, ball, upper, lower, brow, side: s };
});

/* ---- mouth --------------------------------------------------------------
   A dark cavity behind two lips. The lower lip and the cavity hang off a jaw
   group hinged back near the ears, which is where a jaw hinges, so the mouth
   swings open on an arc instead of the lower lip sliding down a wall. */
const MOUTH_Y = -0.40;
const MOUTH_Z = surfZ(0, MOUTH_Y);
// The hinge sits back near the ears, where a jaw actually hinges, so the
// mouth swings open on an arc instead of the lower lip sliding down a wall.
//
// Everything parented to it must be given in jaw-local coordinates. Writing
// a head-space z here instead puts the part a whole 0.28 deeper than
// intended, which is inside a solid skull: the lower lip and the cavity are
// then perfectly correct and perfectly invisible, and the mouth looks welded
// shut however far the jaw swings.
const JAW_Y = 0.0, JAW_Z = -0.28;
const jaw = new THREE.Group();
jaw.position.set(0, JAW_Y, JAW_Z);
head.add(jaw);
const inJaw = (x, y, z) => [x, y - JAW_Y, z - JAW_Z];

// Proud of the skin, not behind it. The skull is a solid surface, so a
// cavity tucked inside is simply invisible however wide the jaw swings. The
// lips close over this when the mouth is shut and part to reveal it.
// Parented to the head, not the jaw. On the jaw the whole opening swings
// down with the chin and leaves a band of cheek between it and the upper
// lip; anchored here, its top edge stays tucked under the upper lip and it
// only grows downwards, which is what a mouth does.
const CAVITY_TOP = MOUTH_Y + 0.012;
const cavity = new THREE.Mesh(new THREE.SphereGeometry(0.14, 24, 18),
  new THREE.MeshStandardMaterial({ color: 0x3a1118, roughness: 0.95 }));
cavity.scale.set(0.86, 0.08, 0.22);
cavity.position.set(0, CAVITY_TOP, MOUTH_Z + 0.026);
head.add(cavity);

const upperLip = new THREE.Mesh(new THREE.CapsuleGeometry(0.031, 0.17, 6, 14), lipMat);
upperLip.rotation.z = Math.PI / 2;
upperLip.position.set(0, MOUTH_Y + 0.030, MOUTH_Z + 0.022);
head.add(upperLip);

const lowerLip = new THREE.Mesh(new THREE.CapsuleGeometry(0.036, 0.16, 6, 14), lipMat);
lowerLip.rotation.z = Math.PI / 2;
lowerLip.position.set(...inJaw(0, MOUTH_Y - 0.036, MOUTH_Z + 0.022));
jaw.add(lowerLip);

/* ---- neck and shoulders ------------------------------------------------- */
const neck = new THREE.Mesh(new THREE.CylinderGeometry(0.215, 0.27, 0.78, 28), skinDeep);
neck.position.y = 0.42;
avatar.add(neck);

const torso = new THREE.Group();
torso.position.y = -0.46;
avatar.add(torso);

const shirt = new THREE.MeshStandardMaterial({ color: 0x2a3450, roughness: 0.86 });
const shoulders = new THREE.Mesh(new THREE.CapsuleGeometry(0.31, 1.2, 10, 26), shirt);
shoulders.rotation.z = Math.PI / 2;
shoulders.position.y = 0.3;
torso.add(shoulders);

const chest = new THREE.Mesh(new THREE.SphereGeometry(0.62, 32, 24), shirt);
chest.scale.set(1.12, 0.8, 0.62);
chest.position.y = -0.1;
torso.add(chest);

const collar = new THREE.Mesh(new THREE.TorusGeometry(0.235, 0.05, 12, 32),
  new THREE.MeshStandardMaterial({ color: 0x35405f, roughness: 0.8 }));
collar.rotation.x = Math.PI / 2;
collar.position.y = 0.42;
torso.add(collar);

/* ---- a soft presence behind the shoulders, not a sci-fi halo ----------- */
const glow = new THREE.Mesh(new THREE.CircleGeometry(2.1, 48),
  new THREE.MeshBasicMaterial({ color: COL.violet, transparent: true, opacity: 0.08 }));
glow.position.set(0, 0.45, -1.9);
scene.add(glow);

const COUNT = 380;
const pPos = new Float32Array(COUNT * 3);
const pSeed = new Float32Array(COUNT);
for (let i = 0; i < COUNT; i++) {
  const r = 2.2 + Math.random() * 2.1;
  const th = Math.random() * Math.PI * 2;
  const ph = Math.acos(2 * Math.random() - 1);
  pPos[i * 3] = r * Math.sin(ph) * Math.cos(th);
  pPos[i * 3 + 1] = r * Math.cos(ph) * 0.6 + 0.3;
  pPos[i * 3 + 2] = r * Math.sin(ph) * Math.sin(th) - 1.0;
  pSeed[i] = Math.random() * Math.PI * 2;
}
const pGeo = new THREE.BufferGeometry();
pGeo.setAttribute("position", new THREE.BufferAttribute(pPos, 3));
const dust = new THREE.Points(pGeo, new THREE.PointsMaterial({
  color: COL.teal, size: 0.016, transparent: true, opacity: 0.3, depthWrite: false,
}));
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

/* ---- behaviour ----------------------------------------------------------
   Idle motion is the illusion. A still face reads as dead inside two seconds,
   and the fix is not more geometry: it is blinks at uneven intervals, eyes
   that drift away and come back, and a chest that moves. */
const clock = new THREE.Clock();
let blinkAt = 1.4, blinkPhase = -1;
let gazeAt = 2.0;
const gaze = { x: 0, y: 0, tx: 0, ty: 0 };
let browLift = 0, headYaw = 0, headPitch = 0, headRoll = 0;

// Three sines at unrelated rates: cheaper than real noise and it never
// settles into a loop the eye can learn.
const drift = (t, seed) =>
  Math.sin(t * 0.37 + seed) * 0.6 + Math.sin(t * 0.83 + seed * 2.1) * 0.3
  + Math.sin(t * 1.9 + seed * 3.7) * 0.1;

function step(t, dt) {
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
  if (forcedMouth !== null) amp = forcedMouth;
  mouth += (amp - mouth) * Math.min(1, dt * 18);

  const speaking = pipeState === "speaking";
  const thinking = pipeState === "thinking";

  /* ---- jaw and lips ---- */
  jaw.rotation.x = mouth * 0.23;
  upperLip.position.y = MOUTH_Y + 0.030 + mouth * 0.022;
  upperLip.scale.x = 1 + mouth * 0.06;
  lowerLip.scale.x = 1 + mouth * 0.1;
  // grow downwards from a fixed top edge: scale, then drop the centre by
  // half of what the scale just added
  const open = 0.08 + mouth * 0.62;
  cavity.scale.y = open;
  cavity.position.y = CAVITY_TOP - 0.14 * open;

  /* ---- level meter ---- */
  for (let i = 0; i < BARS; i++) {
    const wob = 0.45 + 0.55 * Math.sin(t * 9 + i * 0.7);
    bars[i].style.height = (4 + mouth * 30 * wob).toFixed(1) + "px";
    bars[i].style.opacity = (0.28 + mouth * 0.72).toFixed(2);
  }

  /* ---- head: slow drift, a lean while listening, a nod on the beat ---- */
  const wantYaw = drift(t, 1.3) * 0.13 + gaze.x * 0.16;
  const wantPitch = drift(t, 4.7) * 0.045 + gaze.y * 0.09
                  + (thinking ? 0.05 : 0) + (speaking ? mouth * 0.03 : 0);
  const wantRoll = drift(t, 8.1) * 0.04 + (pipeState === "listening" ? 0.04 : 0);
  headYaw += (wantYaw - headYaw) * Math.min(1, dt * 2.2);
  headPitch += (wantPitch - headPitch) * Math.min(1, dt * 2.6);
  headRoll += (wantRoll - headRoll) * Math.min(1, dt * 1.8);
  head.rotation.set(headPitch, headYaw, headRoll);
  neck.rotation.y = headYaw * 0.35;

  /* ---- breathing ---- */
  const breath = Math.sin(t * 0.72) * 0.5 + 0.5;
  torso.scale.set(1 + breath * 0.013, 1 + breath * 0.008, 1 + breath * 0.018);
  torso.position.y = -0.46 + breath * 0.012;

  /* ---- eyes: a saccade out to somewhere, then back to the lens ---- */
  if (t > gazeAt) {
    const away = thinking || Math.random() < 0.35;
    gaze.tx = away ? (Math.random() - 0.5) * 1.3 : 0;
    gaze.ty = away ? (thinking ? 0.5 : (Math.random() - 0.5) * 0.7) : 0;
    gazeAt = t + (away ? 0.7 + Math.random() * 1.4 : 1.4 + Math.random() * 2.6);
  }
  gaze.x += (gaze.tx - gaze.x) * Math.min(1, dt * 11);   // saccades are fast
  gaze.y += (gaze.ty - gaze.y) * Math.min(1, dt * 11);

  /* ---- blinks: uneven, and doubled now and then ---- */
  if (blinkPhase < 0 && t > blinkAt) blinkPhase = 0;
  let lid = 0;
  if (blinkPhase >= 0) {
    blinkPhase += dt / 0.13;
    lid = Math.sin(Math.min(blinkPhase, 1) * Math.PI);
    if (blinkPhase >= 1) {
      blinkPhase = -1;
      blinkAt = t + (Math.random() < 0.18 ? 0.2 : 1.8 + Math.random() * 4.0);
    }
  }
  const squint = thinking ? 0.16 : 0;
  browLift += (((speaking ? mouth * 0.5 : 0) + (thinking ? -0.4 : 0)) - browLift)
            * Math.min(1, dt * 4);

  eyes.forEach((e) => {
    // Keep the glance small. Past about a quarter radian the iris rolls far
    // enough round the ball that the lids stop covering the sclera beside
    // it, and a crescent of bare white reads as a squint, or worse.
    e.ball.rotation.y = gaze.x * 0.24;
    e.ball.rotation.x = -gaze.y * 0.2;
    // At rest the upper lid clears the top of the iris and the lower sits
    // under it; a blink sweeps the upper one right down over the ball.
    e.upper.rotation.x = -0.80 + (lid + squint) * 2.05;
    e.lower.rotation.x = 0.38 - (lid + squint * 0.4) * 0.45;
    e.brow.position.y = BROW_Y + browLift * 0.045;
    e.brow.rotation.x = -browLift * 0.25;
  });

  /* ---- ambience ---- */
  glow.material.opacity = 0.055 + mouth * 0.08 + (thinking ? 0.045 : 0);
  glow.material.color.set(speaking ? COL.blue : COL.violet);

  const pa = pGeo.attributes.position;
  for (let i = 0; i < COUNT; i++) {
    pa.array[i * 3 + 1] = pPos[i * 3 + 1] + Math.sin(t * 0.7 + pSeed[i]) * (0.05 + mouth * 0.2);
  }
  pa.needsUpdate = true;
  dust.rotation.y += dt * 0.035;
  dust.material.opacity = 0.2 + mouth * 0.28;
}

function frame() {
  requestAnimationFrame(frame);
  step(clock.getElapsedTime(), Math.min(clock.getDelta(), 0.05));
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
      if (m.who === "user") {
        els.capUser.classList.toggle("live", !m.final);
        showCaption(els.capUser, m.text, false);
      } else {
        showCaption(els.capAgent, m.text, m.final);
      }
    }
  };
  // A dropped peer should land where hanging up lands, not in a half state
  // with a dead room on screen and the microphone still live.
  ws.onclose = () => leave();
  // Captured, not read off the module variable: leave() nulls `pc`, and this
  // handler fires during that teardown.
  const peer = pc;
  peer.onconnectionstatechange = () => {
    if (["failed", "disconnected", "closed"].includes(peer.connectionState)) leave();
  };

  els.gate.classList.add("gone");
  els.leave.hidden = false;
  setState("listening");
}

/* Hanging up has to release the hardware, not just hide the UI. Closing the
   peer connection alone leaves the microphone and camera live, and the
   browser keeps showing the recording indicator on a call the user believes
   they have left. Every track gets stopped explicitly.

   The server needs no message: closing the peer fires connectionstatechange
   there, which drops the session and its history. */
let leaving = false;

function leave() {
  // Idempotent on purpose. Tearing down fires the very events that call this
  // again: closing the socket runs ws.onclose, closing the peer runs
  // onconnectionstatechange, and both land back here mid-teardown with the
  // references already nulled.
  if (leaving) return;
  leaving = true;

  for (const stop of [
    () => ws && ws.close(),
    () => pc && pc.getSenders().forEach((s) => s.track && s.track.stop()),
    () => pc && pc.getReceivers().forEach((r) => r.track && r.track.stop()),
    () => pc && pc.close(),
    () => {
      const cam = els.cam.srcObject;
      if (cam) cam.getTracks().forEach((t) => t.stop());
      els.cam.srcObject = null;
    },
    () => { els.audio.pause(); els.audio.srcObject = null; },
  ]) {
    try { stop(); } catch (err) { console.warn("leave:", err); }
  }

  pc = ws = session = null;
  analyser = null;              // the jaw falls shut on its own from here
  els.pip.classList.remove("on");
  els.leave.hidden = true;
  showCaption(els.capUser, "", false);
  showCaption(els.capAgent, "", false);
  els.capUser.classList.remove("live");
  setState("idle");

  els.gate.classList.remove("gone");
  els.join.disabled = false;
  els.join.textContent = "Join the room";
  leaving = false;
}

/* Posing hook for the offline check: lets the avatar be rendered at a known
   mouth opening and pipeline state without a microphone, a call or a key. */
window.__aria = {
  pose(m, state, seconds = 2) {
    forcedMouth = m;
    if (state) { pipeState = state; body.className = state; }
    // Advance the animation by hand. requestAnimationFrame does not fire in
    // a headless browser, so without this the capture shows whatever the
    // rest pose was and a shut mouth looks like a broken jaw.
    for (let i = 0; i < seconds * 60; i++) step(i / 60, 1 / 60);
  },
  // Render and read back in the same tick. The drawing buffer is not
  // preserved between frames, which is the right default for a page that
  // renders continuously, so a toDataURL from outside the render call comes
  // back empty. Composited onto the page's own ground, the canvas being
  // transparent.
  shot() {
    renderer.render(scene, camera);
    const flat = document.createElement("canvas");
    flat.width = canvas.width;
    flat.height = canvas.height;
    const g = flat.getContext("2d");
    g.fillStyle = "#0b0f18";
    g.fillRect(0, 0, flat.width, flat.height);
    g.drawImage(canvas, 0, 0);
    return flat.toDataURL("image/png").split(",")[1];
  },
};

els.join.addEventListener("click", join);
els.leave.addEventListener("click", leave);
addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !els.leave.hidden) leave();
});
addEventListener("beforeunload", () => { try { pc && pc.close(); ws && ws.close(); } catch {} });
