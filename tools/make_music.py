"""Generates the game's background music offline with ACE-Step 1.5 (MIT code
and weights; its model card allows commercial use of the output).

Runs in ACE-Step's own environment (Tools/ACE-Step-1.5 in Home Codex), with
the 2B turbo model only: the 1.7B planner LM is skipped, since a 10 GB GPU
can't load it alongside the DiT anyway. Stop Ollama's model first so the GPU
is free (ollama stop marycel-v2).

    "<Home Codex>/Tools/ACE-Step-1.5/.venv/Scripts/python" tools/make_music.py --download
    "<Home Codex>/Tools/ACE-Step-1.5/.venv/Scripts/python" tools/make_music.py [--only ofrenda] [--takes 4]
    "<Home Codex>/Tools/ACE-Step-1.5/.venv/Scripts/python" tools/make_music.py --encode   # OGG playlists (ffmpeg)

Takes go to game/web/audio/takes/<cue>-<seed>.flac; every take's prompt and
seed are appended to game/web/audio/takes/log.jsonl so a kept track can be
traced and regenerated.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACE = Path(os.environ.get("ACE_STEP", ROOT.parents[2] / "Tools" / "ACE-Step-1.5"))
CHECKPOINTS = ACE / "checkpoints"
OUT = ROOT / "game" / "web" / "audio" / "takes"
NEEDED = ["acestep-v15-turbo", "vae", "Qwen3-Embedding-0.6B"]  # the main repo minus the planner LM

# One cue per mood. Concrete instruments, key and tempo keep the model from drifting to pop.
CUES = {
    "ofrenda": dict(
        caption="slow ambient instrumental, soft marimba, music box, warm nylon-string guitar, distant small bells, "
                "gentle pad, candlelit Day of the Dead night, nostalgic and slightly eerie, sparse, no drums, no vocals",
        keyscale="A minor", bpm=66),
    "workshop": dict(
        caption="quiet dark ambient instrumental, low warm analog synth pad, faint tape hiss, soft glassy bells, "
                "old computer hum, mysterious late night workshop, calm, sparse, no drums, no vocals",
        keyscale="D minor", bpm=60),
    "home": dict(
        caption="intimate slow instrumental, old upright piano slightly out of tune, soft accordion drone, gentle clock "
                "ticking, faint music box, a family house half unpacked at night, warm but slightly unsettling, sparse, "
                "no drums, no vocals",
        keyscale="B minor", bpm=63),
    "passage": dict(
        caption="eerie ambient instrumental, slow reversed piano, breathy wordless choir pad, distant wind, "
                "music box detuned, haunting but gentle, slow swells, no drums, no vocals",
        keyscale="E minor", bpm=60),
    "morning": dict(
        caption="tender instrumental, nylon-string guitar and marimba, warm soft strings, hopeful and bittersweet, "
                "Day of the Dead memory at dawn, gentle waltz, no drums, no vocals",
        keyscale="C major", bpm=72, timesignature="3"),
}


def download():
    from huggingface_hub import snapshot_download
    snapshot_download("ACE-Step/Ace-Step1.5", local_dir=str(CHECKPOINTS),
                      allow_patterns=[f"{c}/*" for c in NEEDED] + ["*.json", "*.md", "LICENSE*"])
    print("checkpoints:", sorted(p.name for p in CHECKPOINTS.iterdir()))


def generate(cues, takes, duration):
    sys.path.insert(0, str(ACE))
    os.chdir(ACE)
    import acestep.core.generation.handler.init_service_downloads as dl
    # The planner LM is part of the "main model" check; without this ACE-Step would download it.
    dl.check_main_model_exists = lambda path: all((Path(path) / c).exists() for c in NEEDED)
    from acestep.handler import AceStepHandler
    from acestep.inference import GenerationConfig, GenerationParams, generate_music

    dit = AceStepHandler()
    msg, ok = dit.initialize_service(project_root=str(ACE), config_path="acestep-v15-turbo", device="cuda",
                                     offload_to_cpu=True)
    if not ok:
        raise SystemExit(msg)
    OUT.mkdir(parents=True, exist_ok=True)
    log = (OUT / "log.jsonl").open("a", encoding="utf-8")
    for name in cues:
        cue = CUES[name]
        t = time.time()
        params = GenerationParams(caption=cue["caption"], lyrics="[Instrumental]", instrumental=True,
                                  bpm=cue["bpm"], keyscale=cue["keyscale"], timesignature=cue.get("timesignature", ""),
                                  duration=duration, thinking=False, use_cot_metas=False, use_cot_caption=False,
                                  use_cot_language=False, shift=3.0)
        result = generate_music(dit, None, params, GenerationConfig(batch_size=takes, audio_format="flac"),
                                save_dir=str(OUT))
        if not result.success:
            print(name, "failed:", result.error)
            continue
        for audio in result.audios:
            seed = audio["params"]["seed"]
            path = Path(audio["path"])
            final = OUT / f"{name}-{seed}.flac"
            path.replace(final)
            log.write(json.dumps({"cue": name, "file": final.name, "seed": seed, "duration": duration,
                                  "model": "ACE-Step 1.5 acestep-v15-turbo (MIT)", **cue}) + "\n")
            log.flush()
        print(f"{name}: {len(result.audios)} takes in {time.time() - t:.0f}s", flush=True)


def encode():
    """Every full-length take becomes game/web/audio/music/<cue>-<n>.ogg (Vorbis, via ffmpeg),
    listed per cue in music/playlists.json for the game to play in turn."""
    import subprocess
    music = OUT.parent / "music"
    music.mkdir(exist_ok=True)
    playlists: dict[str, list] = {}
    for line in (OUT / "log.jsonl").read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        if e["duration"] < 60:
            continue
        lst = playlists.setdefault(e["cue"], [])
        ogg = music / f"{e['cue']}-{len(lst) + 1}.ogg"
        if not ogg.exists():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(OUT / e["file"]), "-c:a", "libvorbis",
                            "-q:a", "5", str(ogg)], check=True)
        lst.append({"file": ogg.name, "seed": e["seed"], "source": e["file"]})
    (music / "playlists.json").write_text(json.dumps(playlists, indent=1), encoding="utf-8")
    print({k: len(v) for k, v in playlists.items()})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--encode", action="store_true", help="turn the takes into OGG playlists for the game")
    ap.add_argument("--only", choices=list(CUES))
    ap.add_argument("--takes", type=int, default=4)
    ap.add_argument("--duration", type=float, default=60)
    args = ap.parse_args()
    if args.download:
        return download()
    if args.encode:
        return encode()
    generate([args.only] if args.only else list(CUES), args.takes, args.duration)


if __name__ == "__main__":
    main()
