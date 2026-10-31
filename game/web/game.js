// Marele: browser client. Draws the three rooms from the server's
// state, plays Marycel's steps as animations, and sends Elena's signals.
// The server (game/server.py) owns every fact; this file only shows them.
"use strict";

const ROOM_W = 960, VIEW_W = 640, VIEW_H = 224, FOOT_Y = 198;
const WALK_SPEED = 80;           // room pixels per second
const CONSENT_WAIT_MS = 45000;   // a room waits this long for Elena's answer after Marycel asks
const ROUND_GAP_MS = 900;         // a breath between rounds, so Elena can watch and act
const VOICE_WAIT_MS = 8000;       // the next round waits for her line to finish, up to this long
const OUTFIT = "star-sweater";

const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const S = {
  rooms: {}, order: [], active: null, signals: [], files: [], fragments: [],
  started: false, paused: false, over: false, hover: null,
  rt: {}, images: {}, sheets: {}, cell: null, origin: null, anims: null, generation: 0,
};

// ------------------------------------------------------------------ server

async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok || data.error) throw new Error(data.error || res.statusText);
  return data;
}

// ------------------------------------------------------------------ images

function image(src) {
  if (!S.images[src]) {
    const img = new Image();
    img.src = src;
    S.images[src] = img;
  }
  return S.images[src];
}
const prop = (name) => image(`/assets/pixel/props/${name}.png`);
const ready = (img) => img.complete && img.naturalWidth > 0;

async function loadSprites() {
  const man = await (await fetch("/assets/sprites/marycel/manifest.json")).json();
  const native = man.outfits[OUTFIT].scales.native;
  S.cell = native.cell; S.origin = native.origin; S.anims = native.animations;
  for (const [name, a] of Object.entries(S.anims)) {
    S.sheets[name] = image(`/assets/sprites/marycel/${OUTFIT}/native/${a.sheet}`);
  }
}

// ------------------------------------------------------------------ state

function setRooms(rooms) {
  for (const r of rooms) {
    const fresh = !S.rooms[r.id];
    S.rooms[r.id] = r;
    if (fresh) {
      S.order.push(r.id);
      S.rt[r.id] = { x: r.marycel.x, facing: r.marycel.facing, anim: "idle", t0: performance.now(),
                     visible: r.marycel.location !== "away", walk: null, askedAt: null, alert: false,
                     seen: new Set(), unread: 0, typed: null };
      image(`/assets/pixel/rooms/${r.id}.png`);
    }
    checkUnlocks(r.id, fresh);
  }
}

function resetRooms(state) {
  S.rooms = {}; S.order = []; S.rt = {}; S.ever = new Set();
  $("notice").textContent = "";
  setRooms(state.rooms);
  S.active = S.order[0];
  S.signals = state.signals; S.files = state.files; S.fragments = state.fragments;
  buildPreviews();
  buildSignals();
  renderPanel();
}

// ------------------------------------------------------------------ drawing

function animFrame(rt, now) {
  const a = S.anims[rt.anim] || S.anims.idle;
  let t = now - rt.t0;
  const total = a.durations_ms.reduce((x, y) => x + y, 0);
  if (a.loop) t %= total; else t = Math.min(t, total - 1);
  for (let i = 0; i < a.frame_count; i++) {
    if (t < a.durations_ms[i]) return [rt.anim in S.anims ? rt.anim : "idle", i];
    t -= a.durations_ms[i];
  }
  return [rt.anim, a.frame_count - 1];
}

function drawMarycel(ctx, rt, now) {
  if (!rt.visible || !S.anims) return;
  const [name, i] = animFrame(rt, now);
  const sheet = S.sheets[name];
  if (!ready(sheet)) return;
  const [cw, ch] = S.cell, [ox, oy] = S.origin;
  const x = Math.round(rt.x);
  ctx.save();
  if (rt.facing === "left") {
    ctx.translate(x + ox, FOOT_Y - oy);
    ctx.scale(-1, 1);
  } else {
    ctx.translate(x - ox, FOOT_Y - oy);
  }
  ctx.drawImage(sheet, i * cw, 0, cw, ch, 0, 0, cw, ch);
  ctx.restore();
}

function drawRoom(ctx, id, camX, now, hover) {
  const room = S.rooms[id], rt = S.rt[id];
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, VIEW_W, VIEW_H);
  ctx.translate(-camX, 0);
  const bg = image(`/assets/pixel/rooms/${id}.png`);
  if (ready(bg)) ctx.drawImage(bg, 0, 0);
  for (const o of room.objects) {
    if (!o.sprite) continue;
    const img = prop(o.sprite);
    if (!ready(img)) continue;
    const [x0, y0] = o.bounds;
    ctx.drawImage(img, x0, y0);
    for (const ov of o.overlays) {
      const oi = prop(ov.sprite);
      if (ready(oi)) ctx.drawImage(oi, x0 + ov.dx, y0 + ov.dy);
    }
    if (hover && hover.id === o.id && o.outline) {
      const ol = prop(o.sprite + "_outline");
      if (ready(ol)) ctx.drawImage(ol, x0 - 1, y0 - 1);
    }
  }
  for (const it of room.items) {
    if (!it.pos) continue;
    const img = prop(it.sprite);
    if (ready(img)) ctx.drawImage(img, it.pos[0], it.pos[1]);
    if (hover && hover.id === it.id) {
      const ol = prop(it.sprite + "_outline");
      if (ready(ol)) ctx.drawImage(ol, it.pos[0] - 1, it.pos[1] - 1);
    }
  }
  if (hover && !hover.outline && hover.bounds) {
    const [x0, y0, x1, y1] = hover.bounds;
    ctx.strokeStyle = "#d2e0fa";
    ctx.lineWidth = 1;
    ctx.strokeRect(x0 + 0.5, y0 + 0.5, x1 - x0, y1 - y0);
  }
  drawMarycel(ctx, rt, now);
}

// The camera keeps the computer, where Elena is, in the middle, and pans only as far as it
// must to keep Marycel in the picture.
const CAM_MARGIN = 72;
function camFor(id) {
  const x = Math.round(S.rt[id].x), pc = S.rooms[id].objects.find((o) => o.id === "computer");
  const want = pc ? (pc.bounds[0] + pc.bounds[2]) / 2 - VIEW_W / 2 : x - VIEW_W / 2;
  const cam = Math.min(Math.max(want, x - VIEW_W + CAM_MARGIN), x - CAM_MARGIN);
  return Math.round(Math.min(Math.max(cam, 0), ROOM_W - VIEW_W));
}

// Walking is timed, not stepped per frame, so a hidden tab (no animation
// frames) doesn't stall the rooms.
function updateWalk(rt, now) {
  const w = rt.walk;
  if (!w) return;
  const k = Math.min((now - w.t0) / w.dur, 1);
  rt.x = w.from + (w.to - w.from) * k;
}

// ------------------------------------------------------------------ title screen

// The painted background (assets/screens/home.jpg, 1672x940) has Marycel at the
// computer but no text; the monitor's title and the candle light are drawn over
// it here. Positions are in the painting's pixels.
const HOME = {
  bg: "/assets/screens/home.jpg",
  glass: [661, 228, 1034, 482],                // the monitor's glass, from tools/build_screens.py
  candles: [[573, 160], [536, 186], [1207, 392], [1302, 288], [1361, 262], [1421, 302], [1403, 484]],
  title: "MARELE", typeMs: 220, t0: null,
  keep: [847, 500],                            // the point every crop stays centred on
  buttons: [836, 696, 276],                    // where the buttons sit: x, y, width
};

// The painting fills the title screen: a wider window loses a little ceiling and floor,
// a narrower one loses the far walls, and the monitor and buttons always stay in view.
function homeCrop(bg) {
  const r = $("intro").querySelector(".scene").getBoundingClientRect();
  const W = bg.width, H = bg.height, a = r.width / r.height;
  const clamp = (v, hi) => Math.round(Math.min(Math.max(v, 0), hi));
  if (!r.height || window.innerWidth <= 720) return [0, 0, W, H];
  if (a >= W / H) {
    const h = Math.round(W / a);
    return [0, clamp(HOME.keep[1] - h / 2, H - h), W, h];
  }
  const w = Math.round(H * a);
  return [clamp(HOME.keep[0] - w / 2, W - w), 0, w, H];
}

function drawHome(now) {
  const ctx = $("home").getContext("2d");
  const bg = image(HOME.bg);
  if (!ready(bg)) return;
  const [sx, sy, sw, sh] = homeCrop(bg), canvas = $("home");
  if (canvas.width !== sw || canvas.height !== sh) {
    canvas.width = sw; canvas.height = sh;
    const [bx, by, bw] = HOME.buttons, scene = canvas.parentElement.style;
    scene.setProperty("--hx", `${(bx - sx) / sw * 100}%`);
    scene.setProperty("--hy", `${(by - sy) / sh * 100}%`);
    scene.setProperty("--hw", `${bw / sw * 100}%`);
  }
  ctx.save();
  ctx.translate(-sx, -sy);
  if (HOME.t0 === null) HOME.t0 = now;
  const t = now - HOME.t0;
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(bg, 0, 0);
  // candle light breathes
  ctx.globalCompositeOperation = "lighter";
  HOME.candles.forEach(([x, y], i) => {
    const a = 0.1 + 0.06 * Math.sin(now / 170 + i * 2.1) + 0.04 * Math.sin(now / 53 + i * 5.3);
    const g = ctx.createRadialGradient(x, y, 0, x, y, 46);
    g.addColorStop(0, `rgba(255, 196, 110, ${a})`);
    g.addColorStop(1, "rgba(255, 196, 110, 0)");
    ctx.fillStyle = g;
    ctx.fillRect(x - 46, y - 46, 92, 92);
  });
  ctx.globalCompositeOperation = "source-over";
  // the monitor types the title, then the cursor blinks
  const [gx0, gy0, gx1, gy1] = HOME.glass, cx = (gx0 + gx1) / 2, base = gy0 + 130;
  const shown = Math.min(HOME.title.length, Math.floor(t / HOME.typeMs));
  const typing = shown < HOME.title.length;
  ctx.save();
  ctx.fillStyle = "#c8ffd6"; ctx.shadowColor = "#40c470"; ctx.shadowBlur = 18;
  ctx.font = '700 76px "Pixelify Sans"';
  const x0 = cx - ctx.measureText(HOME.title).width / 2;
  const text = HOME.title.slice(0, shown);
  ctx.fillText(text, x0, base);
  if (typing || Math.floor(t / 530) % 2 === 0) ctx.fillRect(x0 + ctx.measureText(text).width + 6, base - 56, 26, 58);
  if (!typing) {
    ctx.font = '400 22px "Pixelify Sans"'; ctx.textAlign = "center"; ctx.shadowBlur = 8;
    ctx.fillText("A ghost who can only speak", cx, base + 54);
    ctx.fillText("through the family computer.", cx, base + 82);
  }
  ctx.shadowBlur = 0; ctx.fillStyle = "rgba(0, 0, 0, .14)";
  for (let y = gy0; y < gy1; y += 4) ctx.fillRect(gx0, y, gx1 - gx0, 2);
  ctx.restore();
  ctx.restore();
}

function frame(now) {
  if (!$("intro").hidden) drawHome(now);
  for (const id of S.order) updateWalk(S.rt[id], now);
  if (S.active) {
    const view = $("view").getContext("2d");
    view.imageSmoothingEnabled = false;
    drawRoom(view, S.active, camFor(S.active), now, S.hover);
  }
  for (const id of S.order) {
    const c = document.querySelector(`canvas[data-room="${id}"]`);
    if (!c) continue;
    const ctx = c.getContext("2d");
    ctx.imageSmoothingEnabled = false;
    drawRoom(ctx, id, camFor(id), now, null);
  }
  requestAnimationFrame(frame);
}

// ------------------------------------------------------------------ Marycel's turns

function walkTo(id, x) {
  const rt = S.rt[id];
  if (Math.abs(rt.x - x) < 1) return Promise.resolve();
  rt.facing = x < rt.x ? "left" : "right";
  rt.anim = "walk"; rt.t0 = performance.now();
  const dur = Math.abs(x - rt.x) / WALK_SPEED * 1000;
  rt.walk = { from: rt.x, to: x, t0: performance.now(), dur };
  return sleep(dur).then(() => { rt.x = x; rt.walk = null; });
}

function doorX(room) {
  const d = room.objects.find((o) => o.kind === "door");
  return d ? d.stand_x : ROOM_W - 40;
}

async function perform(id, res) {
  const rt = S.rt[id], gen = S.generation;
  const before = S.rooms[id];
  const after = res.room;
  if (!res.refused) {
    if (before.marycel.location === "away" && after.marycel.location !== "away") {
      rt.x = doorX(before); rt.visible = true;
    }
    const to = after.marycel.location === "away" ? doorX(before) : after.marycel.x;
    const dist = Math.abs(to - rt.x);
    if (id === S.active && dist > 8) sfx("steps", Math.max(1, Math.round(dist / WALK_SPEED / 0.36)));
    await walkTo(id, to);
    if (gen !== S.generation) return;
    if (after.marycel.location === "away") rt.visible = false;
    rt.facing = after.marycel.facing;
  }
  S.rooms[id] = after;
  checkUnlocks(id);
  if (id !== S.active) rt.unread++;
  if (!res.refused && (res.step || {}).action === "type_message") rt.typed = { text: res.step.text || "", steps: after.steps };
  rt.anim = res.refused ? "idle" : res.anim;
  rt.t0 = performance.now();
  showLine(id, res);
  if (id === S.active) {
    const act = (res.step || {}).action;
    if (res.refused) sfx("refused");
    else if (ACTION_SFX[act]) sfx(ACTION_SFX[act]);
    if ((res.noticed || []).some((n) => n.includes("quiet voice"))) sfx("echo");
    Voice.say([res.line, !res.refused && act === "say_aloud" ? (res.step || {}).text : null]);
    updateMusic();
  }
  renderPanel();
  const a = S.anims[rt.anim];
  const animTotal = a && !a.loop ? a.durations_ms.reduce((x, y) => x + y, 0) : 0;
  await sleep(Math.min(Math.max(res.ms || 600, animTotal, 900), 4000));
  if (gen !== S.generation) return;
  rt.anim = after.marycel.seated === "yes" ? "sit_type" : "idle";
  if (rt.anim === "sit_type") rt.x = after.marycel.x;
  rt.t0 = performance.now();
  if (after.world.transfer_consent === "asked" && !rt.askedAt) { rt.askedAt = performance.now(); rt.answer = null; }
  if (after.world.transfer_consent !== "asked") rt.askedAt = null;
}

function showLine(id, res) {
  if (id !== S.active) { flagPreview(id, res); return; }
  const sub = $("subtitle");
  sub.innerHTML = "";
  const who = document.createElement("span");
  who.className = "who";
  who.textContent = "Marycel: ";
  sub.append(who, res.line || "...");
  const st = res.step || {};
  if (!res.refused && st.text) {
    const said = document.createElement("span");
    said.className = "who";
    const how = st.action === "say_aloud" ? "says aloud" : st.action === "write_note" ? "writes" : "types";
    said.textContent = `  She ${how}: "${st.text}"`;
    sub.append(document.createElement("br"), said);
  }
  if (res.refused) {
    const r = document.createElement("span");
    r.className = "refused";
    r.textContent = "  (that didn't work)";
    sub.append(r);
  }
}

// The three Marycels take turns in rounds: each takes one step, and nobody starts the next
// until all of them have finished theirs (and the room on screen has finished speaking).
async function runRounds(gen) {
  while (gen === S.generation) {
    if (!S.started || S.paused || S.over) { await sleep(300); continue; }
    const ready = S.order.filter((id) => !S.rooms[id].ended && !waitingForElena(id));
    if (!ready.length) { await sleep(300); continue; }
    const ok = await Promise.all(ready.map((id) => stepRoom(id, gen)));
    if (gen !== S.generation) return;
    if (ok.includes(false)) { await sleep(3000); continue; }
    const until = performance.now() + VOICE_WAIT_MS;
    while (Voice.current && performance.now() < until && gen === S.generation) await sleep(150);
    await sleep(ROUND_GAP_MS);
  }
}

// After she asks about the transfer, her room sits out the rounds until Elena answers or time runs out.
function waitingForElena(id) {
  const room = S.rooms[id], rt = S.rt[id];
  return room.world.transfer_consent === "asked" && rt.askedAt && performance.now() - rt.askedAt < CONSENT_WAIT_MS;
}

async function stepRoom(id, gen) {
  let res;
  try {
    res = await api("/api/step", { room: id });
    setStatus("");
  } catch (e) {
    setStatus(e.message, true);
    return false;
  }
  if (gen !== S.generation) return true;
  if (res.ended) { S.rooms[id].ended = true; roomEnded(id); return true; }
  await perform(id, res);
  if (res.room.ended) roomEnded(id);
  return true;
}

function roomEnded(id) {
  if (!S.order.every((x) => S.rooms[x].ended)) {
    notice(`${S.rooms[id].label}: her night is over. The other rooms go on.`);
  }
  checkOver();
}

// Notices stack, newest first and at most three, and each fades after 8 seconds,
// so two that arrive together are both read.
function notice(text) {
  const el = $("notice"), line = document.createElement("span");
  line.textContent = text;
  el.prepend(line);
  while (el.children.length > 3) el.lastElementChild.remove();
  setTimeout(() => line.remove(), 8000);
}

function checkOver() {
  if (S.order.every((id) => S.rooms[id].ended)) showEnding();
}

// ------------------------------------------------------------------ previews and room switching

function buildPreviews() {
  const box = $("previews");
  box.innerHTML = "";
  for (const id of S.order) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "preview";
    b.dataset.room = id;
    b.innerHTML = `<canvas data-room="${id}" width="640" height="224"></canvas>` +
      `<span class="cap"><b></b><span class="cap-foot"><span class="st"></span><span class="reach"></span></span></span>`;
    b.addEventListener("click", () => setActive(id));
    box.append(b);
  }
  updatePreviews();
}

function setActive(id) {
  S.active = id;
  S.hover = null;
  S.rt[id].alert = false;
  S.rt[id].unread = 0;
  Voice.say([]);
  $("tip").hidden = true;
  $("subtitle").textContent = "";
  updatePreviews();
  renderPanel();
  updateMusic();
}

function flagPreview(id, res) {
  S.rt[id].alert = !!(res.room && res.room.question);
  updatePreviews();
}

function updatePreviews() {
  for (const b of document.querySelectorAll(".preview")) {
    const id = b.dataset.room, room = S.rooms[id];
    b.classList.toggle("active", id === S.active);
    b.setAttribute("aria-pressed", String(id === S.active));
    b.classList.toggle("alert", !!(room.question || S.rt[id].alert));
    b.querySelector(".cap b").textContent = room.label;
    const rt = S.rt[id], reply = !room.ended && (!!room.question || typedWaiting().includes(id));
    const st = b.querySelector(".st");
    st.textContent = room.ended ? "night over" : reply ? "Reply needed" : rt.unread ? `${rt.unread} unread` : "";
    st.className = `st${reply ? " urgent" : rt.unread && !room.ended ? " unread" : ""}`;
    b.querySelector(".reach").textContent = room.ended ? "" : reachWords(room);
    b.setAttribute("aria-label", [`Switch to ${room.label}`, st.textContent, b.querySelector(".reach").textContent].filter(Boolean).join(", "));
  }
}

function reachWords(room) {
  if (room.marycel.location === "away") return "out of the room";
  const r = room.reach || {};
  return r.screen && r.sound ? "sees the screen, hears sound" : r.screen ? "sees the screen" :
    r.sound ? "hears sound" : "can't see the screen or hear sound";
}

// ------------------------------------------------------------------ hover labels

const STATE_WORDS = { yes: "", no: "not ", on: "on", off: "off" };

function describe(o) {
  const st = o.state || {};
  const bits = Object.entries(st).map(([k, v]) => {
    const key = k.replace(/_/g, " ");
    if (v === "yes") return key;
    if (v === "no") return `not ${key}`;
    return `${key} ${String(v).replace(/_/g, " ")}`;
  });
  return bits.length ? `${o.label} - ${bits.join(", ")}` : o.label;
}

function hitTest(id, x, y) {
  const room = S.rooms[id];
  for (const it of [...room.items].reverse()) {
    if (!it.pos) continue;
    const img = prop(it.sprite);
    if (ready(img) && x >= it.pos[0] && x < it.pos[0] + img.width && y >= it.pos[1] && y < it.pos[1] + img.height) {
      return { id: it.id, label: it.label, outline: true, text: it.label };
    }
  }
  for (const o of [...room.objects].reverse()) {
    if (!o.outline && o.kind !== "door" && o.kind !== "window") continue;
    const [x0, y0, x1, y1] = o.bounds;
    if (x >= x0 && x <= x1 && y >= y0 && y <= y1) return { ...o, text: describe(o) };
  }
  return null;
}

function onHover(e) {
  if (!S.active) return;
  const rect = $("view").getBoundingClientRect();
  const k = rect.width / VIEW_W;
  const x = (e.clientX - rect.left) / k + camFor(S.active);
  const y = (e.clientY - rect.top) / k;
  S.hover = hitTest(S.active, x, y);
  const tip = $("tip");
  if (!S.hover) { tip.hidden = true; return; }
  tip.hidden = false;
  tip.textContent = S.hover.text;
  tip.style.left = (e.clientX - rect.left) + "px";
  tip.style.top = (e.clientY - rect.top - 8) + "px";
}

// ------------------------------------------------------------------ Elena's signals

// Three cards, one for each way Elena can reach Marycel. A signal shows only while it would
// go through in at least one room (the server's signals_now, the same check a send makes),
// and the first time one works in a room a notice says so.
const CHOICE_WORDS = { agreed: "Yes", declined: "No", warned: "Danger", more_tests: "More tests" };
const UNLOCK_WORDS = {
  long_note: "screen repaired, longer messages work now.",
  highlight_file: "she opened the files, you can point to one.",
  play_fragment: "she played the recording, you can play pieces of it.",
  print_message: "the printer works, you can print a note.",
  request_pause: "the recovery is running, you can ask her to halt it.",
};
const UNLOCK_CARD = { long_note: "screen", highlight_file: "screen", request_pause: "screen",
                      play_fragment: "sound", print_message: "printer" };
const TYPED_STEPS = 3;  // her typed question waits this many of her steps for an answer
const ICONS = {
  screen: "M1 2h14v10H1zM3 4v6h10V4zM6 12h4v2h2v1H4v-1h2z",
  sound: "M2 6h3l3-3h2v10H8L5 10H2zM12 5h1v1h1v4h-1v1h-1v-1h1V6h-1z",
  printer: "M4 1h8v4H4zM1 5h14v7h-3v3H4v-3H1zM5 10v4h6v-4z",
};

function choiceLabel(sid, c) {
  if (sid === "highlight_file") {
    const f = S.files.find((x) => x.id === c);
    return f ? f.name : c.replace(/_/g, " ").toUpperCase();
  }
  if (sid === "transfer_response") return CHOICE_WORDS[c] || c;
  return c.replace(/_/g, " ");
}

const sigById = (sid) => S.signals.find((s) => s.id === sid);
const canSend = (sid) => S.order.some((id) => !S.rooms[id].ended && (S.rooms[id].signals_now || {})[sid]);

// rooms whose Marycel typed on the screen and is still waiting for a reply
function typedWaiting() {
  return S.order.filter((id) => {
    const t = S.rt[id].typed, r = S.rooms[id];
    return t && !r.ended && r.steps - t.steps < TYPED_STEPS;
  });
}

function icon(name) {
  return `<span class="sig-icon" aria-hidden="true"><svg viewBox="0 0 16 16"><path fill-rule="evenodd" d="${ICONS[name]}"/></svg></span>`;
}

function buildSignals() {
  const box = $("signals");
  box.innerHTML = `
    <div id="typed" class="typed" role="status" hidden></div>
    <form class="sig-card" data-card="screen">
      <div class="card-head">${icon("screen")}<h3>Screen</h3></div>
      <p class="card-line" id="screen-line"></p>
      <div class="sig-row">
        <input id="screen-text" name="text" autocomplete="off" aria-label="Message for the screen">
        <button type="submit">Send</button>
      </div>
      <p class="card-sub" id="screen-count"></p>
      <div class="sig-row" data-show="highlight_file">
        <select id="file-choice" aria-label="File to point to"></select>
        <button type="button" data-send="highlight_file">Point to this file</button>
      </div>
      <div class="sig-row" data-show="request_pause">
        <button type="button" data-send="request_pause">Ask her to halt the recovery</button>
        <span class="card-sub">Flashes PAUSE on the screen. She decides.</span>
      </div>
    </form>
    <div class="sig-card" data-card="sound">
      <div class="card-head">${icon("sound")}<h3>Sound</h3></div>
      <p class="card-line">She hears it if she's in the room.</p>
      <div class="sig-row" data-show="tone"><button type="button" data-send="tone">Crackle the speakers</button></div>
      <div class="sig-row" data-show="play_fragment">
        <select id="fragment-choice" aria-label="Piece of the recording"></select>
        <button type="button" data-send="play_fragment">Play this piece</button>
      </div>
      <p class="card-sub" id="sound-off">The speakers are unplugged or muted.</p>
    </div>
    <form class="sig-card" data-card="printer">
      <div class="card-head">${icon("printer")}<h3>Printer</h3></div>
      <p class="card-line" id="printer-line"></p>
      <div class="sig-row" data-show="print_message">
        <input id="print-text" name="text" autocomplete="off" aria-label="Note to print">
        <button type="submit">Print</button>
      </div>
    </form>`;
  for (const [sel, sid] of [["file-choice", "highlight_file"], ["fragment-choice", "play_fragment"]]) {
    for (const c of sigById(sid).choices) $(sel).add(new Option(choiceLabel(sid, c), c));
  }
  $("print-text").maxLength = sigById("print_message").max_chars;
  const screenText = $("screen-text");
  screenText.addEventListener("input", () => {
    updateSignalLocks();
  });
  box.querySelector('[data-card="screen"]').addEventListener("submit", async (e) => {
    e.preventDefault();
    const v = screenText.value.trim(), short = sigById("screen_message").max_chars;
    if (!v) { notice("Type a few letters first."); screenText.focus(); return; }
    if (v.length > short && !canSend("long_note")) {
      notice(`The screen can only show ${short} letters right now.`);
      screenText.focus();
      return;
    }
    // one box: a long message is a note, a short one answers her if she typed, else a message
    const sid = v.length > short ? "long_note" : typedWaiting().length ? "answer_typed" : "screen_message";
    const reached = await sendSignal(sigById(sid), { name: "text", value: sid === "long_note" ? v : v.toUpperCase() });
    if (reached) {
      screenText.value = "";
      for (const id of reached) S.rt[id].typed = null;
      updateSignalLocks();
    }
  });
  box.querySelector('[data-card="printer"]').addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = $("print-text"), v = input.value.trim();
    if (!v) { notice("Type a few words first."); input.focus(); return; }
    if (await sendSignal(sigById("print_message"), { name: "text", value: v })) input.value = "";
  });
  const choice = { highlight_file: "file-choice", play_fragment: "fragment-choice" };
  for (const b of box.querySelectorAll("[data-send]")) {
    const sid = b.dataset.send;
    b.addEventListener("click", () => sendSignal(sigById(sid), choice[sid] ? { name: "choice", value: $(choice[sid]).value } : null));
  }
  updateSignalLocks();
}

// The first time a signal works in a room, say so and light up its card for a moment.
function checkUnlocks(id, quiet) {
  const rt = S.rt[id], now = S.rooms[id].signals_now || {};
  for (const [sid, ok] of Object.entries(now)) {
    if (!ok || rt.seen.has(sid)) continue;
    rt.seen.add(sid);
    S.ever.add(sid);
    if (quiet || !UNLOCK_WORDS[sid]) continue;
    notice(`${S.rooms[id].label}: ${UNLOCK_WORDS[sid]}`);
    const card = $("signals").querySelector(`[data-card="${UNLOCK_CARD[sid]}"]`);
    card.classList.add("fresh");
    setTimeout(() => card.classList.remove("fresh"), 6000);
  }
}

function updateSignalLocks() {
  const box = $("signals");
  if (!box.firstElementChild || !S.signals) return;
  const live = S.started && !S.over && !S.paused && !S.sending;
  box.classList.toggle("resting", S.paused);
  box.querySelectorAll("button, input, select").forEach((el) => { el.disabled = !live; });
  const open = S.order.filter((id) => !S.rooms[id].ended);
  for (const el of box.querySelectorAll("[data-show]")) {
    const sid = el.dataset.show, rooms = open.filter((id) => (S.rooms[id].signals_now || {})[sid]);
    el.hidden = !rooms.length;
    if (!el.classList.contains("sig-row")) continue;
    const where = el.querySelector(".where") || el.appendChild(Object.assign(document.createElement("span"), { className: "card-sub where" }));
    where.textContent = rooms.length && rooms.length < open.length ? `Works in: ${rooms.map((id) => S.rooms[id].label).join(", ")}` : "";
  }

  // Screen: one box, a few letters until diagnostics repair it
  const screenOk = canSend("screen_message"), long = canSend("long_note");
  const input = $("screen-text"), max = sigById(long ? "long_note" : "screen_message").max_chars;
  input.maxLength = max;
  input.placeholder = `type up to ${max} letters`;
  input.disabled = input.nextElementSibling.disabled = !live || !screenOk;
  $("screen-line").textContent = !screenOk ? "The computer is off." :
    long ? "Repaired: longer messages work now." : "The screen is damaged: a few letters only.";
  $("screen-count").textContent = `${input.value.length} / ${max}`;
  $("screen-count").classList.toggle("bad", input.value.length > max);
  input.classList.toggle("shout", !long);

  // Sound: in each room the crackle gives way to the recording once she has played it
  const tone = box.querySelector('[data-show="tone"]'), frag = box.querySelector('[data-show="play_fragment"]');
  tone.hidden = !open.some((id) => { const now = S.rooms[id].signals_now || {}; return now.tone && !S.rt[id].seen.has("play_fragment"); });
  $("sound-off").hidden = !tone.hidden || !frag.hidden;
  $("sound-off").textContent = S.ever.has("play_fragment") ? "The speakers can't play the recording right now." :
    "The speakers are unplugged or muted.";

  // Printer: a dim preview until it works
  const printOk = canSend("print_message");
  box.querySelector('[data-card="printer"]').classList.toggle("locked", !printOk);
  $("printer-line").textContent = printOk ? "She reads it when she picks up the printout." :
    S.ever.has("print_message") ? "Not ready right now." : "Not working yet.";

  // her typed question, with the room it came from
  const typed = $("typed"), waiting = typedWaiting();
  typed.hidden = !waiting.length;
  typed.textContent = waiting.map((id) => `${S.rooms[id].label}: Marycel typed "${S.rt[id].typed.text}".`).join(" ") +
    (waiting.length ? " Your next screen message answers her." : "");
}

const STATUS_WORDS = {
  noticed: ["ok", "she noticed"],
  sent: ["warn", "sent, not noticed yet"],
  no_route: ["warn", "no way to reach her"],
  unavailable: ["bad", "not possible here"],
  ended: ["dim", "night over"],
};

async function sendSignal(s, input) {
  if (S.sending || S.paused) return null;
  const params = {};
  if (input) {
    const v = input.value.trim();
    if (s.params.includes("text") && !v) {
      if (input.focus) input.focus();
      notice("Type a few letters first.");
      return null;
    }
    params[input.name] = v;
  }
  S.sending = true;
  document.querySelectorAll("#signals button, .banner button").forEach((b) => { b.disabled = true; });
  let ok = null;  // the rooms that took the signal
  try {
    const res = await api("/api/signal", { signal: s.id, params });
    if (s.id === "transfer_response") {
      for (const id of S.order) {
        if (S.rooms[id].question) S.rt[id].answer = { text: CHOICE_WORDS[params.choice], until: performance.now() + 8000 };
        S.rt[id].askedAt = null;
      }
    }
    setRooms(res.rooms);
    if (input && input.tagName === "INPUT") input.value = "";
    const fb = $("feedback");
    fb.innerHTML = "";
    for (const id of S.order) {
      const r = res.results[id];
      const [cls, word] = STATUS_WORDS[r.status] || ["dim", r.status];
      const line = document.createElement("span");
      line.className = `r ${cls}`;
      line.textContent = `${S.rooms[id].label}: ${word}${r.status === "unavailable" && r.why ? ` (${r.why})` : ""}`;
      fb.append(line);
    }
    const open = S.order.filter((id) => res.results[id].status !== "ended");
    const seen = open.filter((id) => res.results[id].status === "noticed").length;
    const waiting = open.some((id) => res.results[id].why !== "she isn't waiting for an answer right now");
    notice(s.id === "transfer_response" && open.length && !waiting ? "She isn't waiting for an answer right now." :
      `Sent. ${seen} of ${open.length} rooms noticed it right away.`);
    if (s.id === "tone" || s.id === "play_fragment") sfx("tone");
    else if (s.id === "print_message") sfx("printer");
    else sfx("screen");
    const reached = S.order.filter((id) => !["unavailable", "ended"].includes(res.results[id].status));
    ok = reached.length ? reached : null;
  } catch (e) {
    setStatus(e.message, true);
  } finally {
    S.sending = false;
    $("banner").dataset.key = "";
    renderPanel();
  }
  return ok;
}

// ------------------------------------------------------------------ panel and log

function renderPanel() {
  const id = S.active;
  if (!id) return;
  const room = S.rooms[id];
  $("room-title").textContent = room.label;
  const m = room.marycel;
  const held = m.holding ? `holding the ${m.holding.replace(/_/g, " ")}` : "hands free";
  const where = m.location === "away" ? "out of the room" : `${m.seated === "yes" ? "sitting at" : "at"} the ${m.at.replace(/_/g, " ")}`;
  $("room-facts").textContent = `Marycel is ${where}, ${held}. On the screen: ${room.screen ? `"${room.screen}"` : "no message"}.`;
  renderAsk(room, S.rt[id]);

  $("log-room").textContent = `(${room.label})`;
  const log = $("log");
  log.innerHTML = "";
  for (const e of [...room.log].reverse()) {
    const li = document.createElement("li");
    if (e.elena) {
      const p = e.params && (e.params.text || e.params.choice);
      li.innerHTML = `<span class="elena"></span>`;
      li.firstChild.textContent = `You: ${e.elena.replace(/_/g, " ")}${p ? ` "${p}"` : ""}`;
    } else {
      const st = e.step || {};
      const words = [st.action, st.target, st.item, st.choice, st.position].filter(Boolean).join(" ").replace(/_/g, " ");
      const said = st.text ? ` "${st.text}"` : "";
      li.innerHTML = `<span class="act"></span><span class="res"></span>`;
      li.children[0].textContent = `${e.n}. ${words}${said}`;
      li.children[1].textContent = e.result;
      if (e.refused) li.children[1].classList.add("bad");
    }
    for (const n of e.noticed || []) {
      const h = document.createElement("span");
      h.className = "heard";
      h.textContent = `She noticed: ${n}`;
      li.append(h);
    }
    log.append(li);
  }
  updatePreviews();
  updateSignalLocks();
}

// Marycel's transfer question, with the answers right under it; after an
// answer, the banner says so for a few seconds.
function renderAsk(room, rt) {
  const banner = $("banner");
  const answered = rt.answer && performance.now() < rt.answer.until ? rt.answer.text : "";
  const asking = room.question && !room.ended;
  banner.hidden = !asking && !answered;
  if (banner.hidden) { banner.dataset.key = ""; return; }
  const key = `${asking ? room.question : ""}|${answered}|${S.paused}`;
  if (banner.dataset.key === key) return;
  banner.dataset.key = key;
  banner.innerHTML = `<span class="q"></span><span class="answers"></span>`;
  const box = banner.querySelector(".answers");
  if (answered) {
    banner.querySelector(".q").textContent = `You answered: ${answered}.`;
    box.textContent = "She will see it on her next step.";
    setTimeout(() => { if (S.active) renderPanel(); }, rt.answer.until - performance.now() + 50);
    return;
  }
  banner.querySelector(".q").textContent = `${room.label}: Marycel asks you "${room.question}" She waits about ${CONSENT_WAIT_MS / 1000} seconds.`;
  const s = S.signals.find((x) => x.id === "transfer_response");
  for (const c of s.choices) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = CHOICE_WORDS[c] || c;
    b.disabled = S.sending || S.paused;
    b.addEventListener("click", async () => {
      await sendSignal(s, { name: "choice", value: c });
      if (!banner.hidden) banner.focus();
    });
    box.append(b);
  }
}

function setStatus(text, bad) {
  const el = $("status");
  el.textContent = text || (S.over ? "The night is over." : S.paused ? "Paused." : S.started ? "Marycel is working." : "");
  el.classList.toggle("error", !!bad);
}

// ------------------------------------------------------------------ sound and music
// Effects are synthesized (sound.js) and play only for the room on screen.
// Music: each room has its own theme; the eerie passage music takes over while
// the passage stirs in the room on screen; morning plays over the endings.
// Each cue is a playlist of ACE-Step takes (audio/music/playlists.json).

const ROOM_THEME = { "repair-shop": "ofrenda", "electronics-workshop": "workshop", "home-workshop": "home" };
const EERIE = new Set(["stirring", "active", "uncertain"]);
const MUSIC_VOLUME = 0.35, FADE_S = 4;
const ACTION_SFX = {
  insert_recording: "tape", play_tape: "tape", insert_disk: "disk", copy_playable_video: "disk", verify_copy: "disk",
  print_file: "printer", type_message: "typing", ask_before_transfer: "typing", start_transfer: "transfer",
  leave_room: "door", return: "door",
};

let soundOn = true;
try { soundOn = localStorage.getItem("ghost-sound") !== "off"; } catch (_) { /* storage is optional */ }

function sfx(name, ...args) {
  if (!soundOn) return;
  try { Sound.play(name, ...args); } catch (_) { /* sound is optional */ }
}

const Music = {
  lists: null, cue: null, next: {}, current: null, timer: null,

  async load() {
    try { this.lists = await (await fetch("/game/web/audio/music/playlists.json")).json(); } catch (_) { this.lists = {}; }
  },

  // Crossfade to the next take of a cue (or keep going if it's already playing).
  play(cue) {
    if (!this.lists || !this.lists[cue] || (cue === this.cue && this.current)) return;
    this.cue = cue;
    this.start();
  },

  start() {
    const list = this.lists[this.cue];
    const i = (this.next[this.cue] || 0) % list.length;
    this.next[this.cue] = i + 1;
    const el = new Audio(`/game/web/audio/music/${list[i].file}`);
    el.volume = 0;
    const old = this.current;
    this.current = el;
    if (soundOn) el.play().catch(() => {});
    fade(el, soundOn ? MUSIC_VOLUME : 0);
    if (old) fade(old, 0, () => old.pause());
    // Move on to the next take shortly before this one ends.
    el.addEventListener("timeupdate", () => {
      if (el === this.current && el.duration && el.currentTime > el.duration - FADE_S) this.start();
    });
  },

  stop() {
    if (this.current) { const old = this.current; fade(old, 0, () => old.pause()); }
    this.current = null; this.cue = null;
  },

  mute(on) {
    if (!this.current) return;
    if (on) { this.current.play().catch(() => {}); fade(this.current, MUSIC_VOLUME); }
    else fade(this.current, 0);
  },
};

// Marycel's voice: lines recorded ahead (tools/record_voice.py). A line with no
// recording stays a subtitle only. Only the room on screen speaks.
const Voice = {
  manifest: {}, current: null,

  async load() {
    try { this.manifest = await (await fetch("/game/web/audio/voice/manifest.json")).json(); } catch (_) { this.manifest = {}; }
  },

  // Says each text that has a recording, one after another; stops anything she was still saying.
  say(texts) {
    const wasSpeaking = !!this.current;
    if (this.current) { this.current.pause(); this.current = null; }
    const files = texts.map((t) => this.manifest[(t || "").trim()]).filter(Boolean);
    if (!soundOn || !files.length) { if (wasSpeaking) duck(false); return; }
    const next = () => {
      const file = files.shift();
      if (!file) { this.current = null; duck(false); return; }
      const el = new Audio(`/game/web/audio/voice/${file}`);
      el.volume = 0.95;
      this.current = el;
      el.addEventListener("ended", () => { if (this.current === el) next(); });
      el.play().catch(() => {});
    };
    duck(true);
    next();
  },
};

// Music dips while she speaks.
function duck(on) {
  if (Music.current && soundOn) fade(Music.current, on ? MUSIC_VOLUME * 0.45 : MUSIC_VOLUME);
}

function fade(el, to, done) {
  const from = el.volume, t0 = performance.now();
  clearInterval(el._fade);
  el._fade = setInterval(() => {
    const k = Math.min((performance.now() - t0) / (FADE_S * 1000), 1);
    el.volume = Math.max(0, Math.min(1, from + (to - from) * k));
    if (k >= 1) { clearInterval(el._fade); if (done) done(); }
  }, 50);
}

function updateMusic() {
  if (!S.started) return;
  if (S.over) return Music.play("morning");
  const room = S.rooms[S.active];
  if (room) Music.play(EERIE.has(room.world.passage) ? "passage" : ROOM_THEME[room.id]);
}

// ------------------------------------------------------------------ ending

const ENDINGS = {
  bridge: ["The bridge", "Marycel moved Elena's own voice to the new drive, after Elena said yes."],
  wrong_voice: ["The wrong voice", "The voice she moved was not Elena's. Something else got out of the machine."],
  promise: ["The promise", "Elena said no, so Marycel left her where she is. The way out stays shut, and they can still talk."],
  recording_survives: ["The recording survives", "The family video is safe. Elena's voice is still inside the old computer."],
  unresolved: ["Unresolved", "The night ended before any voice was moved or the video was saved."],
  too_early: ["Over too soon", "The night ended before Marycel got far. Nothing was saved, and nothing was lost."],
};
const TOO_EARLY_STEPS = 3;  // an unresolved room with fewer steps than this barely started
const FACT_WORDS = {
  video: { none: "family video not copied", copying: "family video copy unfinished", preserved: "family video copied",
           failed: "family video copy failed" },
  passage: { dormant: "the way out stayed closed", stirring: "the way out was stirring", active: "the way out was open",
             contained: "the way out was shut again", transfer: "a voice crossed over", uncertain: "unclear if the way out is shut" },
};
const CONSENT_WORDS = { none: "she never asked you", asked: "her last question was still waiting for your answer",
                        no_answer: "she asked, and time ran out before you answered" };

async function showEnding() {
  if (S.over) return;
  S.over = true;
  setStatus();
  let rooms = S.order.map((id) => S.rooms[id]);
  try { rooms = (await api("/api/end", {})).rooms; } catch (_) { /* show what we have */ }
  setRooms(rooms);
  $("pause").disabled = true;
  $("end").disabled = true;
  const box = $("outcomes");
  box.innerHTML = "";
  for (const r of rooms) {
    const o = r.outcome || { key: "unresolved", video: r.world.video_copy, passage: r.world.passage,
                             stream: r.world.selected_stream, consent: r.world.transfer_consent, steps: r.steps };
    const [name, text] = ENDINGS[o.key === "unresolved" && o.steps < TOO_EARLY_STEPS ? "too_early" : o.key];
    const div = document.createElement("div");
    div.className = "outcome";
    const voice = (v) => `voice ${String(v || "?").replace("stream_", "").toUpperCase()}`;
    const streamWord = o.stream === "none" ? "no voice chosen" : `she chose ${voice(o.stream)}; Elena's was ${voice(o.elena_stream)}`;
    div.innerHTML = `<h3></h3><div class="name"></div><p></p><details><summary>What happened</summary><ul></ul></details>`;
    // the card shows where this room actually ended up
    const snap = document.createElement("canvas");
    snap.width = VIEW_W; snap.height = VIEW_H;
    snap.setAttribute("role", "img");
    snap.setAttribute("aria-label", `${r.label} in the morning`);
    const sctx = snap.getContext("2d");
    sctx.imageSmoothingEnabled = false;
    drawRoom(sctx, r.id, camFor(r.id), performance.now(), null);
    div.prepend(snap);
    div.querySelector("h3").textContent = r.label;
    div.querySelector(".name").textContent = name;
    div.querySelector("p").textContent = text;
    for (const f of [FACT_WORDS.video[o.video], FACT_WORDS.passage[o.passage], streamWord,
                     CHOICE_WORDS[o.consent] ? `your answer: ${CHOICE_WORDS[o.consent]}` : CONSENT_WORDS[o.consent] || o.consent.replace(/_/g, " "), `${o.steps} steps`]) {
      const li = document.createElement("li");
      li.textContent = f;
      div.querySelector("ul").append(li);
    }
    box.append(div);
  }
  $("ending").hidden = false;
  $("again").focus();
  updateMusic();
  const keys = rooms.map((r) => (r.outcome || {}).key);
  if (keys.includes("wrong_voice")) sfx("wrong_voice");
  else if (keys.includes("bridge")) sfx("bridge");
  updateSignalLocks();
}

// ------------------------------------------------------------------ start

async function newGame() {
  S.generation++;
  S.over = false; S.paused = false;
  const state = await api("/api/new", {});
  resetRooms(state);
  setStatus(`Model: ${state.model}`);
  runRounds(S.generation);
}

async function init() {
  setupDialogs();
  $("view").addEventListener("mousemove", onHover);
  $("view").addEventListener("mouseleave", () => { S.hover = null; $("tip").hidden = true; });
  $("pause").addEventListener("click", () => setPaused(!S.paused));
  // menu items close the menu once chosen
  $("help").addEventListener("click", () => $("menu").hidePopover());
  $("menu").addEventListener("toggle", (e) => {  // open just under the gear, inside the window
    if (e.newState !== "open") return;
    const m = $("menu"), g = $("menu-button").getBoundingClientRect();
    m.style.top = `${g.bottom + 6}px`;
    m.style.left = `${Math.max(8, Math.min(g.right - m.offsetWidth, innerWidth - m.offsetWidth - 8))}px`;
  });
  $("end").addEventListener("click", () => { $("menu").hidePopover(); showEnding(); });
  window.addEventListener("beforeunload", (e) => {
    if (S.started && !S.over) { e.preventDefault(); e.returnValue = ""; }
  });
  // another night starts back at the title screen
  $("again").addEventListener("click", async () => {
    $("ending").hidden = true;
    $("intro").hidden = false;
    S.started = false;
    S.ready = false;
    HOME.t0 = null;
    Music.stop();
    setStatus("");
    await prepareNight();
    $("start").focus();
  });
  $("start").addEventListener("click", () => {
    if (!S.ready) return prepareNight();
    $("story").showModal();
  });
  const soundButton = $("sound");
  const showSound = () => { soundButton.textContent = soundOn ? "Sound on" : "Sound off"; soundButton.setAttribute("aria-pressed", String(soundOn)); };
  showSound();
  soundButton.addEventListener("click", () => {
    soundOn = !soundOn;
    try { localStorage.setItem("ghost-sound", soundOn ? "on" : "off"); } catch (_) { /* storage is optional */ }
    showSound();
    Music.mute(soundOn);
    if (!soundOn) Voice.say([]);
  });
  requestAnimationFrame(frame);
  document.fonts.load('700 76px "Pixelify Sans"').catch(() => {});
  try {
    await Music.load();
    await Voice.load();
    await loadSprites();
  } catch (e) {
    $("intro-error").textContent = e.message;
    return;
  }
  await prepareNight();
  $("start").focus();
}

// A new night is made on the server while the title screen shows; "Try again" retries a failure.
async function prepareNight() {
  const start = $("start");
  start.disabled = true;
  start.textContent = "Loading...";
  $("intro-error").textContent = "";
  try {
    await newGame();
    S.ready = true;
    start.textContent = "Begin the night";
  } catch (e) {
    S.ready = false;
    $("intro-error").textContent = e.message;
    start.textContent = "Try again";
  }
  start.disabled = false;
}

function beginNight() {
  $("intro").hidden = true;
  S.started = true;
  showPause();
  $("pause").disabled = false;
  $("end").disabled = false;
  setStatus();
  updateSignalLocks();
  updateMusic();
  $("pause").focus();  // the title's buttons are gone; keyboard play starts in the top bar
}

// A pause also stops the clock on Marycel's question, so a paused player loses no answer time.
function setPaused(on) {
  if (on === S.paused) return;
  const now = performance.now();
  if (on) S.pausedAt = now;
  else for (const id of S.order) if (S.rt[id].askedAt) S.rt[id].askedAt += now - S.pausedAt;
  S.paused = on;
  showPause();
  setStatus();
}

function showPause() {
  const b = $("pause"), label = S.paused ? "Resume" : "Pause";
  b.classList.toggle("paused", S.paused);
  b.setAttribute("aria-label", label);
  b.title = label;
  $("signals").classList.toggle("resting", S.paused);
  updateSignalLocks();
  renderPanel();
}

// Opening How to play during a night pauses it; closing it picks up where it was.
function openHelp() {
  const d = $("how-dialog");
  if (d.open) return;
  d.dataset.resume = S.started && !S.over && !S.paused ? "1" : "";
  if (d.dataset.resume) setPaused(true);
  d.dataset.back = $("story").open ? "1" : "";  // opened from the story: go back to it after
  if (d.dataset.back) $("story").close();
  d.showModal();
}

function setupDialogs() {
  for (const d of document.querySelectorAll(".dialog")) {
    d.querySelector(".close").addEventListener("click", () => d.close());
    d.addEventListener("click", (e) => {  // a click on the dimmed backdrop, outside the window
      const b = d.getBoundingClientRect();
      if (e.target === d && (e.clientX < b.left || e.clientX > b.right || e.clientY < b.top || e.clientY > b.bottom)) d.close();
    });
  }
  $("how-dialog").addEventListener("close", () => {
    if ($("how-dialog").dataset.resume) setPaused(false);
    if ($("how-dialog").dataset.back && !S.started) $("story").showModal();
  });
  $("help").addEventListener("click", openHelp);
  $("how").addEventListener("click", openHelp);
  $("story-how").addEventListener("click", openHelp);
  $("story-go").addEventListener("click", () => { $("story").close(); beginNight(); });
}

init();
