# Music credits

Music in `takes/` is generated offline by `tools/make_music.py` with ACE-Step 1.5
(`acestep-v15-turbo`, https://github.com/ace-step/ACE-Step-1.5). Code and weights
are MIT-licensed (copy in `LICENSE-ACE-Step.txt`); the model card states that
generated music may be used commercially. Each take's prompt, key, tempo and seed
are in `takes/log.jsonl`. Sound effects are synthesized in `game/web/sound.js`.

Marycel's voice in `voice/` is recorded ahead of play by `tools/record_voice.py` with Kokoro 82M
(Apache-2.0, https://github.com/hexgrad/kokoro), preset voice `af_heart`, the same speaker for every
line (no cloning of any person). An earlier take used Qwen3-TTS 1.7B VoiceDesign (Apache-2.0), which
re-creates a voice from a description on each call and drifted between lines. `voice/lines.json` lists the lines; `voice/manifest.json`
maps each line to its file. Lines without a recording are shown as subtitles only.
