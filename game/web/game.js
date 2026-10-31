// Marele: browser client. Draws the three rooms from the server's
// state, plays Marycel's steps as animations, and sends Elena's signals.
// The server (game/server.py) owns every fact; this file only shows them.
"use strict";

const ROOM_W = 960, VIEW_W = 640, VIEW_H = 224, FOOT_Y = 198;
const WALK_SPEED = 80;           // room pixels per second
const CONSENT_WAIT_MS = 30000;   // a room waits this long for Elena's answer after Marycel asks
const ROUND_GAP_MS = 900;         // a breath between rounds, so Elena can watch and act
const VOICE_WAIT_MS = 8000;       // the next round waits for her line to finish, up to this long
const OUTFIT = "star-sweater";

const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const S = {
  rooms: {}, order: [], active: null, signals: [], files: [], fragments: [],
  started: false, paused: false, over: false, hover: null, scale: 2,
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
                     visible: r.marycel.location !== "away", walk: null, askedAt: null, alert: false };
      image(`/assets/pixel/rooms/${r.id}.png`);
    }
  }
}

function resetRooms(state) {
  S.rooms = {}; S.order = []; S.rt = {};
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

const camFor = (id) => Math.min(Math.max(Math.round(S.rt[id].x) - VIEW_W / 2, 0), ROOM_W - VIEW_W);

// Walking is timed, not stepped per frame, so a hidden tab (no animation
// frames) doesn't stall the rooms.
function updateWalk(rt, now) {
  const w = rt.walk;
  if (!w) return;
  const k = Math.min((now - w.t0) / w.dur, 1);
  rt.x = w.from + (w.to - w.from) * k;
}

function frame(now) {
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

function fitScale() {
  const room = window.innerWidth - (window.innerWidth > 1000 ? 440 : 40);
  S.scale = room >= 1280 ? 2 : 1;
  const v = $("view");
  v.style.width = VIEW_W * S.scale + "px";
  v.style.height = VIEW_H * S.scale + "px";
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
  const rt = S.rt[id];
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
    if (after.marycel.location === "away") rt.visible = false;
    rt.facing = after.marycel.facing;
  }
  S.rooms[id] = after;
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
  rt.anim = after.marycel.seated === "yes" ? "sit_type" : "idle";
  if (rt.anim === "sit_type") rt.x = after.marycel.x;
  rt.t0 = performance.now();
  if (after.world.transfer_consent === "asked" && !rt.askedAt) rt.askedAt = performance.now();
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
  if (res.ended) { S.rooms[id].ended = true; checkOver(); return true; }
  await perform(id, res);
  if (res.room.ended) checkOver();
  return true;
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
    b.innerHTML = `<canvas data-room="${id}" width="640" height="224"></canvas><span class="cap"><b></b><span></span></span>`;
    b.addEventListener("click", () => setActive(id));
    box.append(b);
  }
  updatePreviews();
}

function setActive(id) {
  S.active = id;
  S.hover = null;
  S.rt[id].alert = false;
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
    b.hidden = id === S.active;
    b.classList.toggle("alert", !!(room.question || S.rt[id].alert));
    b.querySelector(".cap b").textContent = room.label;
    b.querySelector(".cap span").textContent = room.ended ? "night over" : room.question ? "asking you" :
      room.marycel.location === "away" ? "away" : `step ${room.steps}`;
    b.setAttribute("aria-label", `Switch to ${room.label}`);
  }
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
  const x = (e.clientX - rect.left) / S.scale + camFor(S.active);
  const y = (e.clientY - rect.top) / S.scale;
  S.hover = hitTest(S.active, x, y);
  const tip = $("tip");
  if (!S.hover) { tip.hidden = true; return; }
  tip.hidden = false;
  tip.textContent = S.hover.text;
  tip.style.left = (e.clientX - rect.left) + "px";
  tip.style.top = (e.clientY - rect.top - 8) + "px";
}

// ------------------------------------------------------------------ Elena's signals

const GROUPS = [
  ["Screen", ["screen_message", "answer_typed", "long_note", "highlight_file"]],
  ["Sound", ["tone", "play_fragment"]],
  ["Printer", ["print_message"]],
  ["Recovery", ["request_pause", "transfer_response"]],
  ["Wait", ["stay_silent"]],
];
const LOCK_HINTS = {
  file_route: "Opens after Marycel looks at the files, notes, log, map or video.",
  fragments: "Opens after she plays the recording.",
  text_channel: "Opens after she runs diagnostics.",
  print_route: "Opens after she turns on printing with the printer ready.",
};
const CHOICE_WORDS = { agreed: "Yes", declined: "No", warned: "Danger", more_tests: "More tests" };

function choiceLabel(sid, c) {
  if (sid === "highlight_file") {
    const f = S.files.find((x) => x.id === c);
    return f ? f.name : c.replace(/_/g, " ").toUpperCase();
  }
  if (sid === "transfer_response") return CHOICE_WORDS[c] || c;
  return c.replace(/_/g, " ");
}

function buildSignals() {
  const box = $("signals");
  box.innerHTML = "";
  const byId = Object.fromEntries(S.signals.map((s) => [s.id, s]));
  for (const [title, ids] of GROUPS) {
    const g = document.createElement("div");
    g.className = "group";
    g.innerHTML = `<h3>${title}</h3>`;
    for (const sid of ids) {
      const s = byId[sid];
      if (!s) continue;
      const row = document.createElement("form");
      row.className = "sig";
      row.dataset.signal = sid;
      const label = document.createElement("span");
      label.className = "label";
      label.textContent = s.label;
      row.append(label);
      let input = null;
      if (s.params.includes("text")) {
        input = document.createElement("input");
        input.name = "text";
        input.maxLength = s.max_chars;
        input.placeholder = `up to ${s.max_chars} letters`;
        input.setAttribute("aria-label", s.label);
        if (s.max_chars <= 12) input.addEventListener("input", () => { input.value = input.value.toUpperCase(); });
        row.append(input);
      } else if (s.choices) {
        input = document.createElement("select");
        input.name = "choice";
        input.setAttribute("aria-label", s.label);
        for (const c of s.choices) input.add(new Option(choiceLabel(sid, c), c));
        row.append(input);
      }
      const send = document.createElement("button");
      send.type = "submit";
      send.textContent = sid === "stay_silent" ? "Stay silent" : "Send";
      row.append(send);
      const lock = document.createElement("span");
      lock.className = "lock";
      lock.textContent = LOCK_HINTS[s.unlock] || "";
      row.append(lock);
      row.addEventListener("submit", (e) => { e.preventDefault(); sendSignal(s, input); });
      g.append(row);
    }
    box.append(g);
  }
  updateSignalLocks();
}

function updateSignalLocks() {
  for (const row of document.querySelectorAll(".sig")) {
    const s = S.signals.find((x) => x.id === row.dataset.signal);
    const open = S.order.some((id) => S.rooms[id].unlocked[s.unlock] && !S.rooms[id].ended);
    row.querySelectorAll("input, select, button").forEach((el) => { el.disabled = !open || !S.started || S.over; });
    row.querySelector(".lock").hidden = open || !LOCK_HINTS[s.unlock];
  }
}

const STATUS_WORDS = {
  noticed: ["ok", "she noticed"],
  sent: ["warn", "sent, not noticed yet"],
  no_route: ["warn", "no way to reach her"],
  unavailable: ["bad", "not possible here"],
  ended: ["dim", "night over"],
};

async function sendSignal(s, input) {
  const params = {};
  if (input) {
    const v = input.value.trim();
    if (s.params.includes("text") && !v) { input.focus(); return; }
    params[input.name] = v;
  }
  try {
    const res = await api("/api/signal", { signal: s.id, params });
    setRooms(res.rooms);
    if (s.id === "transfer_response") for (const id of S.order) S.rt[id].askedAt = null;
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
    if (s.id === "tone" || s.id === "play_fragment") sfx("tone");
    else if (s.id === "print_message") sfx("printer");
    else if (s.id !== "stay_silent") sfx("screen");
    renderPanel();
  } catch (e) {
    setStatus(e.message, true);
  }
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
  const banner = $("banner");
  if (room.question && !room.ended) {
    banner.hidden = false;
    banner.textContent = `Marycel asks you: "${room.question}"  Answer with Recovery > Agree, decline or warn.`;
  } else banner.hidden = true;

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
  bridge: ["The bridge", "Marycel moved Elena's own stream to the new drive, with her yes."],
  wrong_voice: ["The wrong voice", "The stream she moved was not Elena's. Something else left the machine."],
  promise: ["The promise", "Elena said no. The passage is held, and the contact is kept."],
  recording_survives: ["The recording survives", "The family video is safe. Elena was never recognized."],
  unresolved: ["Unresolved", "The night ended without a transfer or a safe copy."],
};
const FACT_WORDS = {
  video: { none: "video not copied", copying: "video copy unfinished", preserved: "family video copied", failed: "video copy failed" },
  passage: { dormant: "passage untouched", stirring: "passage stirring", active: "passage active", contained: "passage contained",
             transfer: "a stream crossed over", uncertain: "passage uncertain" },
};

async function showEnding() {
  if (S.over) return;
  S.over = true;
  setStatus();
  let rooms = S.order.map((id) => S.rooms[id]);
  try { rooms = (await api("/api/end", {})).rooms; } catch (_) { /* show what we have */ }
  const box = $("outcomes");
  box.innerHTML = "";
  for (const r of rooms) {
    const o = r.outcome || { key: "unresolved", video: r.world.video_copy, passage: r.world.passage,
                             stream: r.world.selected_stream, consent: r.world.transfer_consent, steps: r.steps };
    const [name, text] = ENDINGS[o.key];
    const div = document.createElement("div");
    div.className = "outcome";
    const streamWord = o.stream === "none" ? "no stream chosen" :
      `chose ${o.stream.replace("_", " ")} (Elena's was ${String(o.elena_stream || "?").replace("_", " ")})`;
    div.innerHTML = `<h3></h3><div class="name"></div><p></p><ul></ul>`;
    div.querySelector("h3").textContent = r.label;
    div.querySelector(".name").textContent = name;
    div.querySelector("p").textContent = text;
    for (const f of [FACT_WORDS.video[o.video], FACT_WORDS.passage[o.passage], streamWord,
                     `your answer: ${CHOICE_WORDS[o.consent] || o.consent.replace(/_/g, " ")}`, `${o.steps} steps`]) {
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
  fitScale();
  window.addEventListener("resize", fitScale);
  $("view").addEventListener("mousemove", onHover);
  $("view").addEventListener("mouseleave", () => { S.hover = null; $("tip").hidden = true; });
  $("pause").addEventListener("click", () => {
    S.paused = !S.paused;
    $("pause").textContent = S.paused ? "Resume" : "Pause";
    setStatus();
  });
  $("end").addEventListener("click", showEnding);
  $("again").addEventListener("click", async () => {
    $("ending").hidden = true;
    try { await newGame(); } catch (e) { setStatus(e.message, true); return; }
    S.started = true;
    setStatus();
    updateSignalLocks();
    updateMusic();
  });
  $("start").addEventListener("click", () => {
    $("intro").hidden = true;
    S.started = true;
    $("pause").disabled = false;
    $("end").disabled = false;
    setStatus();
    updateSignalLocks();
    updateMusic();
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
  try {
    await Music.load();
    await Voice.load();
    await loadSprites();
    await newGame();
    $("start").disabled = false;
    $("start").focus();
  } catch (e) {
    $("intro-error").textContent = e.message;
  }
  requestAnimationFrame(frame);
}

init();
