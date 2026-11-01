# Marele developer guide

[Back to the README](../README.md)

## Model setup

The repository includes inference and training tools, but not model weights or a self-contained model installer. The root requirements cover the game and asset tools; training, conversion, music and voice need separate dependencies.

### Local Ollama

The default model is `marycel-v2`. Inspect installed names with `ollama list`.

The export pipeline in [tools/export_model.py](../tools/export_model.py) downloads a Tinker adapter, merges it with Qwen3-8B, converts to GGUF, quantizes to Q5_0, and imports into Ollama. It requires access to the training checkpoint and a Tinker account, `tinker_cookbook`, its model dependencies, sentencepiece, llama.cpp's converter, and an existing `qwen3:8b` Ollama template. Set `LLAMA_CPP` to your llama.cpp checkout; the script otherwise uses a development-machine path.

This is a large download and conversion workflow. The merge downloads roughly 16 GB of base weights and needs additional temporary disk space. Read the script before running it: the final stage removes its intermediate merged model and Q8 GGUF. It is not a verified fresh-install recipe.

For an untrained comparison, an installed `qwen3:8b` model can be selected with:

```powershell
$env:MARYCEL_BACKEND = 'ollama'
$env:MARYCEL_MODEL = 'qwen3:8b'
.venv/Scripts/python game/server.py
```

This does not reproduce the fine-tuned character's behavior.

### Tinker inference

The server can call Tinker's OpenAI-compatible API instead of Ollama. In PowerShell, set:

```powershell
$env:MARYCEL_BACKEND = 'tinker'
$env:TINKER_API_KEY = 'YOUR_TINKER_API_KEY'
$env:TINKER_MODEL = 'YOUR_ACCESSIBLE_SAMPLER_CHECKPOINT'
.venv/Scripts/python game/server.py
```

Replace both placeholders with your own credentials and accessible sampler checkpoint. The default checkpoint in the source belongs to this build; access from another account is not established. Inference uses paid credits. Keep credentials out of Git.

[render.yaml](../render.yaml) describes the hosted web service and a Render Key Value store. Each visitor's night is held on the server and identified by a browser cookie. `DAILY_STEP_LIMIT` caps model steps; `KEY_VALUE_URL` persists the day's count across restarts. An in-memory counter takes over if the store is unavailable. Loading another tab with the same cookie can reset that browser's night.

## Rules and training

- [data/catalog.json](../data/catalog.json): objects, actions, signals, prerequisites and state changes.
- [data/rooms](../data/rooms/): object placement and starting state.
- [data/content.json](../data/content.json): what Marycel can read, hear and see.
- [data/ACTIONS.md](../data/ACTIONS.md): generated action reference; contains mechanics and possible spoilers.
- [tools/sim.py](../tools/sim.py) and [tools/observe.py](../tools/observe.py): rules, perception and the Echo.
- [game/server.py](../game/server.py): room sessions and inference.
- [game/web](../game/web/): browser client.

[tools/make_dataset.py](../tools/make_dataset.py) generates randomized nights and chat examples. Training and evaluation use separate seeds. [tools/train_tinker.py](../tools/train_tinker.py) trains Qwen3-8B LoRA adapters; `--dry-run` estimates tokens and cost without training, while a normal run spends credits. Training needs the Tinker cookbook and its dependencies.

[tools/run_ollama.py](../tools/run_ollama.py) collects local predictions; [tools/score_steps.py](../tools/score_steps.py) scores saved predictions against replayable histories. Do not treat reference-action agreement as a measure of conversation quality or player satisfaction.

## Asset tools

The game ships with prepared art and audio; playing does not require regenerating them.

- [tools/build_pixel_assets.py](../tools/build_pixel_assets.py) rebuilds rooms, props and character sprites, then checks the native assets.
- [tools/build_character_sprites.py](../tools/build_character_sprites.py) prepares animation sheets, frames and manifests. The manifest records origins, timings and gameplay events. Some walk and crouch frames are generated from poses.
- [tools/build_screens.py](../tools/build_screens.py) prepares the title and morning backgrounds.
- [tools/make_music.py](../tools/make_music.py) uses a separate ACE-Step environment.
- [tools/record_voice.py](../tools/record_voice.py) gathers lines and records them with a separate Kokoro environment. Only the active room speaks; unrecorded lines remain subtitles.
- [game/web/sound.js](../game/web/sound.js) synthesizes effects in the browser.

The showcase video's source files are maintained outside this repository.

## Checks

With the game requirements installed, these checks run without model inference:

```powershell
.venv/Scripts/python tools/room_data.py
.venv/Scripts/python tools/sim.py
.venv/Scripts/python tools/check_signals.py
```

They check room data, scripted routes and forbidden actions, and whether signal availability agrees with sending a signal. Scripted routes expose story mechanics. Passing these checks does not establish live model quality or fresh model-install readiness.
