// Marele: synthesized sound. Every effect is built with the Web
// Audio API at play time, so there are no audio files to license or load.
// Usage: Sound.play("tone"); const stop = Sound.loop("ambience"); stop();
"use strict";

const Sound = (() => {
  let ctx = null, master = null, verb = null, noiseBuf = null;

  function init() {
    if (ctx) return ctx;
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    const comp = ctx.createDynamicsCompressor();
    comp.threshold.value = -18; comp.ratio.value = 3;
    master = ctx.createGain();
    master.gain.value = 0.7;
    master.connect(comp).connect(ctx.destination);
    // A small dark room: decaying noise as the impulse response.
    const len = ctx.sampleRate * 2.2, ir = ctx.createBuffer(2, len, ctx.sampleRate);
    for (let c = 0; c < 2; c++) {
      const d = ir.getChannelData(c);
      for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, 3.2);
    }
    verb = ctx.createConvolver();
    verb.buffer = ir;
    const wet = ctx.createGain();
    wet.gain.value = 0.35;
    verb.connect(wet).connect(master);
    noiseBuf = ctx.createBuffer(1, ctx.sampleRate * 2, ctx.sampleRate);
    const n = noiseBuf.getChannelData(0);
    for (let i = 0; i < n.length; i++) n[i] = Math.random() * 2 - 1;
    return ctx;
  }

  // ---------------------------------------------------------------- building blocks

  const now = () => ctx.currentTime;
  const rand = (a, b) => a + Math.random() * (b - a);

  function out(node, { gain = 1, reverb = 0 } = {}) {
    const g = ctx.createGain();
    g.gain.value = gain;
    node.connect(g);
    g.connect(master);
    if (reverb) {
      const s = ctx.createGain();
      s.gain.value = reverb;
      g.connect(s).connect(verb);
    }
    return g;
  }

  function env(param, t, attack, hold, release, peak = 1) {
    param.setValueAtTime(0.0001, t);
    param.exponentialRampToValueAtTime(peak, t + attack);
    param.setValueAtTime(peak, t + attack + hold);
    param.exponentialRampToValueAtTime(0.0001, t + attack + hold + release);
  }

  function osc(type, freq) {
    const o = ctx.createOscillator();
    o.type = type;
    o.frequency.value = freq;
    return o;
  }

  function noise() {
    const s = ctx.createBufferSource();
    s.buffer = noiseBuf;
    s.loop = true;
    return s;
  }

  function filter(type, freq, q = 1) {
    const f = ctx.createBiquadFilter();
    f.type = type; f.frequency.value = freq; f.Q.value = q;
    return f;
  }

  function crusher(steps) {
    const ws = ctx.createWaveShaper(), curve = new Float32Array(1024);
    for (let i = 0; i < 1024; i++) {
      const x = i / 511.5 - 1;
      curve[i] = Math.round(x * steps) / steps;
    }
    ws.curve = curve;
    return ws;
  }

  // One short note with an envelope; returns its end time.
  function note(type, freq, t, { attack = 0.005, hold = 0, release = 0.2, gain = 0.3, reverb = 0, detune = 0, through = null } = {}) {
    const o = osc(type, freq), g = ctx.createGain();
    o.detune.value = detune;
    env(g.gain, t, attack, hold, release, 1);
    if (through) o.connect(through).connect(g); else o.connect(g);
    out(g, { gain, reverb });
    o.start(t);
    o.stop(t + attack + hold + release + 0.05);
    return t + attack + hold + release;
  }

  function burst(t, dur, { type = "bandpass", freq = 2000, q = 1, gain = 0.3, reverb = 0, attack = 0.002 } = {}) {
    const s = noise(), f = filter(type, freq, q), g = ctx.createGain();
    env(g.gain, t, attack, 0, dur, 1);
    s.connect(f).connect(g);
    out(g, { gain, reverb });
    s.start(t, rand(0, 1.5));
    s.stop(t + attack + dur + 0.05);
  }

  // ---------------------------------------------------------------- one-shot effects

  const FX = {
    // Elena's tone: clean and warm, the one sound that is plainly hers.
    tone(t) {
      note("sine", 660, t, { attack: 0.03, hold: 0.25, release: 1.1, gain: 0.32, reverb: 0.8 });
      note("sine", 990, t, { attack: 0.03, hold: 0.1, release: 0.8, gain: 0.08, reverb: 0.8 });
      note("sine", 1320, t + 0.02, { attack: 0.02, hold: 0, release: 0.5, gain: 0.04, reverb: 0.6 });
    },

    // Words appearing on the old screen: two phosphor blips.
    screen(t) {
      note("square", 1180, t, { release: 0.06, gain: 0.08 });
      note("square", 1580, t + 0.07, { release: 0.08, gain: 0.07 });
    },

    // The Echo: a voice-like smear, crushed and wobbling, swelling instead of speaking.
    echo(t) {
      const dur = 1.6;
      for (const [f0, det] of [[118, 0], [118, 23], [236, -11]]) {
        const o = osc("sawtooth", f0), g = ctx.createGain();
        o.detune.value = det;
        const wob = osc("sine", rand(5, 7)), wg = ctx.createGain();
        wg.gain.value = 9;
        wob.connect(wg).connect(o.frequency);
        o.frequency.setValueAtTime(f0, t);
        o.frequency.linearRampToValueAtTime(f0 * 0.82, t + dur);
        const f1 = filter("bandpass", 700, 6), f2 = filter("bandpass", 1150, 8);
        f1.frequency.setValueAtTime(700, t); f1.frequency.linearRampToValueAtTime(420, t + dur);
        f2.frequency.setValueAtTime(1150, t); f2.frequency.linearRampToValueAtTime(1900, t + dur);
        const mix = ctx.createGain();
        o.connect(f1).connect(mix); o.connect(f2).connect(mix);
        g.gain.setValueAtTime(0.0001, t);
        g.gain.exponentialRampToValueAtTime(1, t + dur * 0.8);
        g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
        mix.connect(crusher(9)).connect(g);
        out(g, { gain: 0.22, reverb: 0.9 });
        o.start(t); o.stop(t + dur + 0.1); wob.start(t); wob.stop(t + dur + 0.1);
      }
      burst(t + 1.45, 0.25, { freq: 3000, q: 0.7, gain: 0.05, reverb: 1 });
    },

    // Marycel typing on the old keyboard.
    typing(t, keys = 9) {
      let at = t;
      for (let i = 0; i < keys; i++) {
        burst(at, 0.03, { type: "highpass", freq: rand(1800, 3200), q: 0.8, gain: rand(0.12, 0.2) });
        burst(at, 0.05, { type: "lowpass", freq: 300, gain: 0.08 });
        at += rand(0.07, 0.17) + (Math.random() < 0.15 ? 0.2 : 0);
      }
    },

    // Dot-matrix printer: a buzzing head pass, a line feed, another pass, the paper out.
    printer(t) {
      for (let line = 0; line < 3; line++) {
        const t0 = t + line * 0.85;
        const o = osc("square", 155), am = osc("square", 38), amg = ctx.createGain(), g = ctx.createGain();
        amg.gain.value = 0.5;
        am.connect(amg).connect(g.gain);
        env(g.gain, t0, 0.01, 0.55, 0.05, 0.5);
        o.connect(filter("bandpass", 1300, 2)).connect(g);
        out(g, { gain: 0.16, reverb: 0.2 });
        o.start(t0); o.stop(t0 + 0.7); am.start(t0); am.stop(t0 + 0.7);
        burst(t0 + 0.66, 0.08, { type: "lowpass", freq: 500, gain: 0.18 });  // line feed
      }
      burst(t + 2.6, 0.35, { type: "bandpass", freq: 3500, q: 0.5, gain: 0.06 });  // paper out
    },

    // Tape deck: the motor comes up to speed under the hiss.
    tape(t) {
      const o = osc("sine", 30), g = ctx.createGain();
      o.frequency.setValueAtTime(30, t);
      o.frequency.exponentialRampToValueAtTime(62, t + 0.9);
      env(g.gain, t, 0.2, 1.4, 0.5, 1);
      o.connect(g);
      out(g, { gain: 0.25 });
      o.start(t); o.stop(t + 2.2);
      burst(t + 0.1, 0.06, { type: "lowpass", freq: 600, gain: 0.3 });  // clunk
      const s = noise(), f = filter("bandpass", 5200, 0.6), ng = ctx.createGain();
      env(ng.gain, t + 0.3, 0.4, 1.0, 0.5, 1);
      s.connect(f).connect(ng);
      out(ng, { gain: 0.05 });
      s.start(t + 0.3); s.stop(t + 2.3);
    },

    // Old drive seeking: clicks with a whirr.
    disk(t) {
      for (let i = 0; i < 7; i++) burst(t + i * rand(0.06, 0.12), 0.02, { type: "highpass", freq: 2500, gain: 0.14 });
      note("triangle", 220, t, { attack: 0.1, hold: 0.6, release: 0.3, gain: 0.05 });
    },

    // Moving a stream to the new drive: steps rising, ending on a soft chord.
    transfer(t) {
      const steps = [0, 3, 7, 10, 12, 15, 19, 22, 24];
      steps.forEach((s, i) => note("square", 220 * Math.pow(2, s / 12), t + i * 0.18,
        { release: 0.12, gain: 0.05, reverb: 0.3, through: filter("lowpass", 2400) }));
      const end = t + steps.length * 0.18;
      for (const s of [0, 4, 7, 12]) note("sine", 440 * Math.pow(2, s / 12), end, { attack: 0.05, hold: 0.4, release: 1.4, gain: 0.07, reverb: 0.8 });
    },

    // A step the rules refused: a low, polite "no".
    refused(t) {
      note("square", 196, t, { release: 0.1, gain: 0.07, through: filter("lowpass", 900) });
      note("square", 147, t + 0.11, { release: 0.16, gain: 0.07, through: filter("lowpass", 900) });
    },

    // Footsteps on wooden boards.
    steps(t, n = 4) {
      for (let i = 0; i < n; i++) {
        burst(t + i * 0.36, 0.09, { type: "lowpass", freq: rand(260, 340), q: 1.5, gain: 0.35 });
        burst(t + i * 0.36 + 0.01, 0.03, { type: "bandpass", freq: 1800, q: 2, gain: 0.03 });
      }
    },

    // A door that needs oil.
    door(t) {
      const o = osc("sawtooth", 95), f = filter("bandpass", 900, 9), g = ctx.createGain();
      for (let i = 0; i < 14; i++) o.frequency.setValueAtTime(rand(70, 130), t + i * 0.06);
      env(g.gain, t, 0.08, 0.6, 0.25, 1);
      o.connect(f).connect(g);
      out(g, { gain: 0.08, reverb: 0.4 });
      o.start(t); o.stop(t + 1.1);
      burst(t + 1.0, 0.15, { type: "lowpass", freq: 180, gain: 0.5, reverb: 0.3 });
    },

    // Endings.
    bridge(t) {
      [0, 4, 7, 11, 14].forEach((s, i) => note("sine", 523 * Math.pow(2, s / 12), t + i * 0.22,
        { attack: 0.01, release: 1.8, gain: 0.12, reverb: 1 }));
      [0, 7].forEach((s) => note("triangle", 131 * Math.pow(2, s / 12), t, { attack: 0.4, hold: 1, release: 2, gain: 0.06, reverb: 0.6 }));
    },
    wrong_voice(t) {
      [12, 8, 3, 0].forEach((s, i) => note("sine", 330 * Math.pow(2, s / 12), t + i * 0.32,
        { attack: 0.01, release: 1.2, gain: 0.1, reverb: 1, detune: i * 18 }));
      FX.echo(t + 1.1);
    },
  };

  // ---------------------------------------------------------------- loops (return a stop function)

  function stopper(nodes, gain, fade = 0.8) {
    return () => {
      const t = now();
      gain.gain.cancelScheduledValues(t);
      gain.gain.setValueAtTime(gain.gain.value, t);
      gain.gain.linearRampToValueAtTime(0, t + fade);
      setTimeout(() => nodes.forEach((n) => { try { n.stop(); } catch (_) { /* already stopped */ } }), fade * 1000 + 100);
    };
  }

  const LOOPS = {
    // The old computer: mains hum and a little fan hiss.
    hum() {
      const g = ctx.createGain();
      g.gain.setValueAtTime(0, now());
      g.gain.linearRampToValueAtTime(1, now() + 1);
      const a = osc("sine", 60), b = osc("sine", 120), s = noise(), f = filter("bandpass", 900, 0.4);
      const ag = ctx.createGain(); ag.gain.value = 0.5;
      const bg = ctx.createGain(); bg.gain.value = 0.15;
      const sg = ctx.createGain(); sg.gain.value = 0.05;
      a.connect(ag).connect(g); b.connect(bg).connect(g); s.connect(f).connect(sg).connect(g);
      out(g, { gain: 0.12 });
      [a, b, s].forEach((n) => n.start());
      return stopper([a, b, s], g);
    },

    // The passage stirring: two detuned low voices that slowly breathe.
    drone() {
      const g = ctx.createGain();
      g.gain.setValueAtTime(0, now());
      g.gain.linearRampToValueAtTime(1, now() + 3);
      const lp = filter("lowpass", 380, 2), lfo = osc("sine", 0.07), lg = ctx.createGain();
      lg.gain.value = 180;
      lfo.connect(lg).connect(lp.frequency);
      const a = osc("sawtooth", 55), b = osc("sawtooth", 55);
      b.detune.value = 14;
      const c = osc("sine", 82.4);
      a.connect(lp); b.connect(lp); c.connect(lp);
      lp.connect(g);
      out(g, { gain: 0.09, reverb: 0.7 });
      [a, b, c, lfo].forEach((n) => n.start());
      return stopper([a, b, c, lfo], g, 2);
    },

    // Night ambience: wind under the window, crickets, and a far-off music box now and then.
    ambience() {
      const g = ctx.createGain();
      g.gain.setValueAtTime(0, now());
      g.gain.linearRampToValueAtTime(1, now() + 2);
      out(g, { gain: 1 });
      const s = noise(), lp = filter("lowpass", 500, 0.7), lfo = osc("sine", 0.11), lg = ctx.createGain(), wg = ctx.createGain();
      lg.gain.value = 260;
      wg.gain.value = 0.05;
      lfo.connect(lg).connect(lp.frequency);
      s.connect(lp).connect(wg).connect(g);
      s.start(); lfo.start();
      let alive = true;
      const box = [523, 587, 659, 784, 880, 1047];
      (function crickets() {
        if (!alive) return;
        const t = now() + 0.05;
        for (let i = 0; i < 3; i++) note("sine", 4400 + rand(-80, 80), t + i * 0.055, { release: 0.03, gain: 0.012 });
        setTimeout(crickets, rand(700, 2600));
      })();
      (function musicBox() {
        if (!alive) return;
        const t = now() + 0.05;
        const n = 2 + Math.floor(rand(0, 3));
        for (let i = 0; i < n; i++) note("sine", box[Math.floor(rand(0, box.length))], t + i * rand(0.35, 0.6),
          { attack: 0.003, release: 1.6, gain: 0.04, reverb: 1.2 });
        setTimeout(musicBox, rand(7000, 14000));
      })();
      const stop = stopper([s, lfo], g, 1.5);
      return () => { alive = false; stop(); };
    },
  };

  return {
    play(name, ...args) {
      init();
      if (ctx.state === "suspended") ctx.resume();
      FX[name](now() + 0.02, ...args);
    },
    loop(name) {
      init();
      if (ctx.state === "suspended") ctx.resume();
      return LOOPS[name]();
    },
    volume(v) { init(); master.gain.value = v; },
    names: () => ({ effects: Object.keys(FX), loops: Object.keys(LOOPS) }),
  };
})();
