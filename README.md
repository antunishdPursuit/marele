# Marele

A pixel-art browser game for the Hacktoberfest 2026 Week 4 challenge ("Ghost in the Machine"), built around a fine-tuned open-weight model (Qwen3-8B with a LoRA trained on Tinker). Play it at https://marele.tech.

## Playing the game

The game runs in the browser, served by a small local Python server that uses the same rules engine and prompt format as the training data:

```
ollama serve                                # if Ollama is not already running
.venv/Scripts/python game/server.py         # then open http://127.0.0.1:8765
```

You play Elena. Three versions of Marycel work in the three rooms at once; each of her steps comes from the local `marycel-v2` model (set `MARYCEL_MODEL` to try another Ollama model) and is checked by the rules before anything changes. One signal from Elena reaches all three rooms, and each Marycel notices it only if she can see or hear it from where she is. The Echo acts on its own, as in training. Each room's night ends when a transfer completes or after 120 steps, or when you end the night; the ending comes from the room's actual state.

Hosted copy: with `MARYCEL_BACKEND=tinker` and `TINKER_API_KEY` set, the server asks the same fine-tuned checkpoint on Tinker instead of Ollama, prompted exactly as in training. Each visitor gets their own night (a cookie), and `DAILY_STEP_LIMIT` (default 6000 steps, about $3 a day) caps the cost. `render.yaml` deploys it on Render; the key is set in Render's dashboard, never in the repository.

`game/server.py` holds the rooms and talks to the model; `game/web/` is the client (canvas drawing at 640x224 per room, scaled by whole numbers, plus HTML controls). The GPU needs about 6.3 GB free for the model.

Sound: effects are synthesized in the browser (`game/web/sound.js`; try them at `/game/web/sound-test.html`). Music is generated offline with ACE-Step 1.5 (MIT code and weights) by `tools/make_music.py`, run with ACE-Step's own Python (installed separately, outside this repository): each room has its own theme (repair shop: ofrenda, electronics workshop: workshop, family home: home), the eerie passage music plays while the passage stirs in the room on screen, and morning plays over the endings. Each theme is a playlist of four one-minute takes in `game/web/audio/music/`; prompts and seeds are logged in `game/web/audio/takes/log.jsonl`, credits in `game/web/audio/CREDITS.md`.

Marycel's voice is recorded ahead of play, not generated live: `tools/record_voice.py lines` collects every line she knows (from the training data and the trained model's test replies), and `tools/record_voice.py record`, run with a separate Qwen3-TTS environment (Apache-2.0), speaks them in one designed voice. Only the room on screen speaks; a line without a recording stays a subtitle.
## Character sprites

`tools/build_character_sprites.py` turns the two Marycel character sheets (star sweater, green cardigan) into animation-ready sprites in `assets/sprites/marycel/`:

- Animations: `idle`, `walk` (4-frame loop), `pickup` (kneel, reach, stand), `pickup_and_read`, `read`, `sit_type`.
- Two scales: `hd` (320 px tall, a smooth reference) and `native` (110 px tall, the game asset on the shared pixel grid and palette).
- Each animation has a horizontal sheet (`walk.png`), single frames in `frames/`, and a `*_preview.gif`.
- `manifest.json` lists cell size, the foot origin (place it on the floor point), frame durations, looping, and gameplay events (`pickup` fires `grab` on frame 5 and `item_in_hand` on frame 7). Sprites face right; mirror them to face left.

## Pixel grid

All game art follows one grid, set in `tools/pixel_spec.py`. The screen is 640x360 and is enlarged only by whole numbers (2x or 3x) with nearest-neighbour sampling. Sprites are never resized in the game. Rooms are 960x224 (1.5 screens wide; the 640 px view scrolls to follow Marycel), Marycel is 110 px tall, and everything uses the shared 73-colour palette (`assets/pixel/palette.gpl`, loadable in Pixelorama).

`tools/build_pixel_assets.py` rebuilds everything: the palette, the three rooms (`assets/pixel/rooms`, drawn pixel by pixel in `tools/build_rooms.py`), Marycel's sprites, the props (`assets/pixel/props`, drawn in `tools/build_props.py`, each object Marycel can use with an `_outline` hover sprite), and per room a full-width scene (`*-room.png`) plus a test screen showing the view around Marycel (`assets/pixel/mockup`). It then checks every native file against the palette and alpha rules, and fails if any break them.

```
uv venv .venv && uv pip install --python .venv pillow numpy
.venv/Scripts/python tools/build_pixel_assets.py
```

Walk passing frames and the crouch in-betweens are generated from the sheet poses, not hand-drawn. Replace them with drawn frames if they don't hold up in the game.

## Room data

`data/catalog.json` holds the shared rules: object kinds and their states, which sprite shows each state, Marycel's actions (with what each requires and changes) and Elena's signals (with what must work and when Marycel perceives them). `data/rooms/<room>.json` places each room's objects and items and sets their starting states. The art builder composes every scene from these files, so the picture and the data agree. `.venv/Scripts/python tools/room_data.py` checks the data on its own; the full build checks it too. `data/ACTIONS.md` lists every action and signal in plain words, grouped by object; regenerate it with `.venv/Scripts/python tools/action_reference.py` after editing the catalog. `.venv/Scripts/python tools/sim.py` is the reference rules engine: it applies actions exactly as the catalog describes, plays a complete route in each room, checks that forbidden moves and malformed steps are refused, and pauses, stops and interrupts the long actions (recovery, copying, transfer). `data/content.json` holds what Marycel can read, hear and see (files, notes, the recovery log, the recording, the damaged segment, the streams, photos, printouts, each room's notebook and window); `tools/observe.py` turns it and the live state into her observations and decides whether she notices a signal (distance, facing, and the speaker or headphone route). The simulation also runs the Echo, which can only reuse phrases Marycel has exposed.

`tools/make_dataset.py` writes the training data for Marycel's model to `data/training/` (regenerable, about 55 MB): it plays randomized episodes in all three rooms through the rules engine, with Elena and the Echo acting on their own, and records each of Marycel's steps as a chat example (system prompt with the rules and actions; user prompt with what she can see, her recent steps and what just happened; the step as one JSON object plus a short `line`). Some episodes include a refused step, and the example after it teaches the fix. Training and held-out evaluation use separate seeds. `--check` replays every example through the rules; `tools/score_steps.py` scores a model's replies on the held-out set (valid by the rules, same action, same step).

Fine-tuning runs on Tinker (a LoRA on Qwen3-8B with thinking off): `tools/train_tinker.py --dry-run` counts tokens and estimates the cost without any API calls; without flags it trains (needs `TINKER_API_KEY` in the environment or in a project `.env`, which must never be shared or committed); `--sample <tinker checkpoint path>` writes the held-out replies for `score_steps.py`. `tools/run_ollama.py` does the same for a local Ollama model, such as the untrained baseline.

`tools/export_model.py` brings a trained checkpoint to this machine: it downloads the adapter from Tinker, merges it into Qwen3-8B, converts it to GGUF with llama.cpp's converter, shrinks it to Q5_0 with `tools/quantize_gguf.py` (about 5.6 GB, so it runs fully on a 10 GB GPU) and imports it into Ollama as `marycel-v2`. Model files stay in `data/models/` and are not part of the repository.


## Credits and licenses

The code in this repository is MIT-licensed (see `LICENSE`). Everything it builds on allows commercial use:

- Marycel's model: Qwen3-8B (Apache-2.0) with a LoRA fine-tuned on Thinking Machines' Tinker; run locally with Ollama after conversion with llama.cpp (MIT).
- Music: ACE-Step 1.5 (MIT code and weights), details in `game/web/audio/CREDITS.md`.
- Marycel's voice: Qwen3-TTS 1.7B VoiceDesign (Apache-2.0), a designed voice, not a clone of anyone.
- Title and morning screen backgrounds (`assets/screens/`): painted with OpenAI image generation, then prepared by `tools/build_screens.py`. The game draws the text, buttons and room snapshots on top.
- Fonts: SIL Open Font License; license texts are in `game/web/fonts/`.
