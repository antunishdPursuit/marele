"""Records Marycel's voice ahead of play: every line she knows, in one fixed voice.
In the game a recorded line plays with its subtitle; any other line stays text.

The game uses Kokoro's preset voice af_heart (Apache-2.0): a preset speaker, so every
line has the same voice. The earlier Qwen3-TTS VoiceDesign recording ("record") re-created
the voice from a description on every call, and lines drifted. Neither is a clone.

    .venv/Scripts/python tools/record_voice.py lines                          # game env: collect the lines
    <Tools/Voice/kokoro>/.venv/Scripts/python tools/record_voice.py kokoro     # CPU: (re-)record every line
    <Tools/Voice/qwen3tts>/.venv/Scripts/python tools/record_voice.py record   # GPU: the old VoiceDesign take

Lines come from the training and held-out data (her own "line" field and what
she says aloud) plus every line the trained model produced in testing. Output:
game/web/audio/voice/<n>.ogg and manifest.json (text -> file).
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VOICE = ROOT / "game" / "web" / "audio" / "voice"
LINES = VOICE / "lines.json"
WARM = ("A woman in her late twenties, Mexican-American, with a warm, slightly low voice. She is tired after "
        "a long night of work and talks quietly to herself, gentle and a little wry.")
SEED, BATCH = 31, 8
KOKORO_VOICE = "af_heart"


def spoken(step):
    """What she says out loud in one step: her line, and the words of say_aloud."""
    out = []
    if isinstance(step, dict):
        if isinstance(step.get("line"), str) and step["line"].strip() not in ("", "..."):
            out.append(step["line"].strip())
        if step.get("action") == "say_aloud" and isinstance(step.get("text"), str) and step["text"].strip():
            out.append(step["text"].strip())
    return out


def collect():
    sys.path.insert(0, str(ROOT / "tools"))
    from make_dataset import OUT
    from score_steps import parse
    found = set()
    for f in ("train.jsonl", "eval.jsonl", "eval_consent.jsonl"):
        for line in (OUT / f).read_text(encoding="utf-8").splitlines():
            found.update(spoken(json.loads(json.loads(line)["messages"][2]["content"])))
    for f in sorted(OUT.glob("*v2*.jsonl")):  # replies of the trained model in testing
        for line in f.read_text(encoding="utf-8").splitlines():
            found.update(spoken(parse(json.loads(line)["output"])))
    VOICE.mkdir(parents=True, exist_ok=True)
    LINES.write_text(json.dumps(sorted(found), indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(found)} lines -> {LINES}")


def record():
    import numpy as np
    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel

    lines = json.loads(LINES.read_text(encoding="utf-8"))
    manifest_path = VOICE / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    todo = [t for t in lines if t not in manifest]
    model = Qwen3TTSModel.from_pretrained("Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign", device_map="cuda:0",
                                          dtype=torch.bfloat16)
    start = time.time()
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        torch.manual_seed(SEED)  # same description and seed for every batch keeps the voice steadier
        wavs, sr = model.generate_voice_design(text=batch, language=["English"] * len(batch),
                                               instruct=[WARM] * len(batch))
        for text, wav in zip(batch, wavs):
            a = np.asarray(wav, dtype=np.float32).reshape(-1)
            rms = float(np.sqrt((a ** 2).mean())) or 1e-6
            a = a * min(0.1 / rms, 0.95 / max(1e-6, float(np.abs(a).max())))  # about -20 dBFS, no clipping
            name = f"{len(manifest) + 1:03d}.ogg"
            tmp = VOICE / "tmp.wav"
            sf.write(tmp, a, sr)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp), "-c:a", "libvorbis", "-q:a", "4",
                            str(VOICE / name)], check=True)
            manifest[text] = name
        manifest_path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"{len(manifest)}/{len(lines)} lines, {time.time() - start:.0f}s", flush=True)
    (VOICE / "tmp.wav").unlink(missing_ok=True)


def encode(a, sr, name):
    """Level to about -20 dBFS without clipping and write an Ogg Vorbis file."""
    import numpy as np
    import soundfile as sf
    a = np.asarray(a, dtype=np.float32).reshape(-1)
    rms = float(np.sqrt((a ** 2).mean())) or 1e-6
    a = a * min(0.1 / rms, 0.95 / max(1e-6, float(np.abs(a).max())))
    tmp = VOICE / "tmp.wav"
    sf.write(tmp, a, sr)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp), "-c:a", "libvorbis", "-q:a", "4",
                    str(VOICE / name)], check=True)


def kokoro():
    """Every line in Kokoro's af_heart voice, into the same files the manifest already names."""
    import numpy as np
    from kokoro import KPipeline
    lines = json.loads(LINES.read_text(encoding="utf-8"))
    manifest_path = VOICE / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    pipe = KPipeline(lang_code="a")  # American English
    start = time.time()
    for n, text in enumerate(lines, 1):
        chunks = [a.numpy() if hasattr(a, "numpy") else a for _, _, a in pipe(text, voice=KOKORO_VOICE)]
        name = manifest.get(text) or f"{len(manifest) + 1:03d}.ogg"
        encode(np.concatenate(chunks), 24000, name)
        manifest[text] = name
        if n % 20 == 0 or n == len(lines):
            manifest_path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
            print(f"{n}/{len(lines)} lines, {time.time() - start:.0f}s", flush=True)
    (VOICE / "tmp.wav").unlink(missing_ok=True)


if __name__ == "__main__":
    {"lines": collect, "record": record, "kokoro": kokoro}[sys.argv[1]]()
