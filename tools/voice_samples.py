"""Voice samples for Marycel, to choose her voice by ear. Each engine runs in its
own environment under Tools/Voice in Home Codex (their dependencies clash).
Both pass the licence rule: Kokoro (Apache-2.0), Qwen3-TTS (Apache-2.0).
Designed voices are used directly, never cloned (a project rule).

    <Tools/Voice/kokoro>/.venv/Scripts/python tools/voice_samples.py kokoro
    <Tools/Voice/qwen3tts>/.venv/Scripts/python tools/voice_samples.py design

Samples go to game/web/audio/voice-samples/<engine>-<voice>.wav, each reading
the same lines (real lines from play-tests), listed in samples.json.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "game" / "web" / "audio" / "voice-samples"
LINES = [
    "Copy the good part first. Always.",
    "Hi, Mom. Hi, Dad. Almost ready for you.",
    "That voice came from the speakers.",
    "Is this you? Can I move you to the new drive?",
    "Hold on. I've got you.",
]
GAP = 0.6  # seconds of silence between lines

KOKORO_VOICES = {"af_heart": "Heart", "af_bella": "Bella", "af_nicole": "Nicole (soft, close)", "af_kore": "Kore"}
DESIGNS = {
    "warm": "A woman in her late twenties, Mexican-American, with a warm, slightly low voice. She is tired after "
            "a long night of work and talks quietly to herself, gentle and a little wry.",
    "bright": "A young woman in her mid twenties, Mexican-American, clear and bright voice, curious and quick, "
              "speaking softly at night so as not to wake anyone, with a hint of nervous humor.",
    "husky": "A woman around thirty, Latina, soft husky voice, calm and grounded, speaking slowly and close to the "
             "microphone, tender when she talks about her family, a little uneasy.",
}


def save(name, label, engine, chunks, sr, seconds):
    OUT.mkdir(parents=True, exist_ok=True)
    gap = np.zeros(int(GAP * sr), dtype=np.float32)
    audio = np.concatenate([x for c in chunks for x in (np.asarray(c, dtype=np.float32).reshape(-1), gap)])
    audio = audio / max(1e-6, np.abs(audio).max()) * 0.9
    sf.write(OUT / f"{name}.wav", audio, sr)
    index = OUT / "samples.json"
    entries = json.loads(index.read_text(encoding="utf-8")) if index.exists() else {}
    entries[name] = {"label": label, "engine": engine, "seconds_to_make": round(seconds, 1),
                     "length": round(len(audio) / sr, 1)}
    index.write_text(json.dumps(entries, indent=1), encoding="utf-8")
    print(f"{name}: {len(audio) / sr:.1f}s of speech in {seconds:.1f}s", flush=True)


def kokoro():
    from kokoro import KPipeline
    pipe = KPipeline(lang_code="a")  # American English
    for voice, label in KOKORO_VOICES.items():
        t, chunks = time.time(), []
        for line in LINES:
            for _, _, audio in pipe(line, voice=voice):
                chunks.append(audio.numpy() if hasattr(audio, "numpy") else audio)
        save(f"kokoro-{voice}", f"Kokoro {label}", "Kokoro 82M (Apache-2.0), CPU", chunks, 24000, time.time() - t)


def design():
    import torch
    from qwen_tts import Qwen3TTSModel
    model = Qwen3TTSModel.from_pretrained("Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign", device_map="cuda:0",
                                          dtype=torch.bfloat16)
    for name, instruct in DESIGNS.items():
        t = time.time()
        wavs, sr = model.generate_voice_design(text=LINES, language=["English"] * len(LINES),
                                               instruct=[instruct] * len(LINES))
        save(f"design-{name}", f"Designed: {name}", "Qwen3-TTS 1.7B VoiceDesign (Apache-2.0), GPU",
             wavs, sr, time.time() - t)


if __name__ == "__main__":
    {"kokoro": kokoro, "design": design}[sys.argv[1]]()
