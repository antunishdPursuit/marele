# Marele

**You are the ghost. The AI plays the person trying to repair your computer.**

On Día de Muertos, Marycel opens an old family computer to recover a recording for the ofrenda. Elena is trapped inside it. Reach Marycel through the screen, speakers and printer while something else in the machine listens.

Built for Hacktoberfest 2026 Week 4: **Ghost in the Machine**.

**[Play at marele.tech](https://marele.tech)** · **[Watch the demo](https://youtu.be/0Zdtyoy7dzg)**

## How to play

- Watch one room and switch between three parallel versions of the same night.
- Send a signal from the computer, speakers or printer. It reaches all three rooms; each Marycel notices only what she can see or hear.
- Unlock more ways to communicate as she repairs the equipment.
- Answer when she asks for permission. You influence her decisions; you do not control her movement.

The rooms can reach different endings. Their names and conditions are left for you to discover.

The hosted game runs on Render with model inference through Tinker. Its first load after inactivity can take about a minute. Use one tab: opening another can reset your night.

## The AI inside the room

Marycel is **Qwen3-8B**, fine-tuned with a rank-32 LoRA on **Tinker**. She receives the room observations and chooses an action plus a short spoken line. The game checks every action and blocks transfers without Elena's consent.

On 394 held-out steps replayable under the current rules:

| Measure | Base model | Fine-tuned v2 |
| --- | --- | --- |
| Actions accepted by the rules | 64.2% | 99.2% |
| Same action as the scripted reference | 26.6% | 75.6% |
| Transfer attempts without consent | 23 | 0 |

These scores use saved predictions, not live player outcomes. Another 25 held-out histories could not replay under the current rules and were excluded for both models. Reaction quality still needs work; Elena currently chooses preset signals rather than typing freely.

## Run locally

The local path has been used on Windows. It needs Python 3.12 or later, Ollama, and the fine-tuned `marycel-v2` model already imported into Ollama. The model weights are **not included**; setup and alternatives are in the [developer guide](docs/DEVELOPMENT.md).

From the repository folder in PowerShell:

```powershell
py -3 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
ollama list
.venv/Scripts/python game/server.py
```

Start Ollama first if it is not running. Confirm that `ollama list` includes `marycel-v2`, then open [localhost:8765](http://127.0.0.1:8765). The model file is about 5.6 GB; the tested local runtime needed about 6.3 GB of free GPU memory. Stop the server with Ctrl+C.

## Development

See the [developer guide](docs/DEVELOPMENT.md) for hosted inference, model training and export, asset tools, and checks.

## Credits and license

Original code: [MIT](LICENSE). Models and dependencies retain their own licenses.

- **Qwen3-8B** and **Kokoro 82M**: Apache-2.0. Marycel uses Kokoro's preset af_heart voice.
- **ACE-Step 1.5**: MIT; [music credits](game/web/audio/CREDITS.md).
- **Ollama / llama.cpp**: local inference and model conversion.
- Title and morning backgrounds: OpenAI image generation.
- Bundled fonts: SIL Open Font License; notices in [game/web/fonts](game/web/fonts/).
- Demo narration: Kokoro's preset ef_dora voice; story stills use OpenAI image generation.
