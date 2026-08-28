# Changelog

## 1.0.2 (2026-08-27)

- Replace **Load or Unload Qwen** and **Load or Unload Qwen 0.6B** with a single **Load Voicebox Model** quick action.
- The new action lists downloaded models from `GET /models/status` in an OSA menu, loads the selected model, and supports unload (including multiple loaded models).
- Fix embedded Python using 3.10-only type syntax that crashed silently under `/usr/bin/python3` (3.9) before the menu appeared.
- Stream Speak and Generate WAV from Text now pass the loaded `model_size` from `/health` (override with `VOICEBOX_MODEL_SIZE`) so `/generate` does not swap 0.6B for the 1.7B default.

## 1.0.1 (2026-08-27)

- Remove Speak Selection; Stream Speak is the text-to-speech Services action.
- Stream Speak: chunked synthesis with pipelined playback (one Voicebox stream at a time, ffplay per chunk).
- Add **Load or Unload Qwen 0.6B** quick action (`POST /models/load?model_size=0.6B`).
- GitHub Pages catalog deploy for MenuCue installs.

## Quick Action hardening (Speak Selection lessons)

All Automator Services now share the same shell prelude so they behave when run from the Services menu in the background.

### Shared behavior

- **Logs** go to `/tmp/vb-qa-<slug>.log` and `/tmp/vb-qa.log`.
- Every run logs `shell start argc=N` (and `collected=N` for Finder file actions).
- Finder file actions also log AppleScript input in the per-slug log: `applescript start`, `applescript paths`, or `applescript error`.
- Voicebox actions log `api=http://127.0.0.1:…` after `vb_ensure`.
- Failures log `FAIL …` to both the aggregate log and the per-slug log, then show a Finder alert.
- User cancel (picker / confirm dialog) logs `… cancelled` and exits 0.

### Speech (Voicebox only)

Stream Speak uses `POST /generate/stream` one chunk at a time (~150 chars). While ffplay plays chunk *N*, chunk *N+1* synthesizes in the background. Supports up to 20,000 characters.

Generate WAV from Text uses `POST /generate`, polls `GET /history/{id}` until `completed`, then `GET /history/{id}/export-audio` to save `<stem>.wav`.

### Library actions (Voicebox `:17493`)

Transcribe, import zip, export, and load/unload models still talk to Voicebox. Profile and model lists use Finder-front `choose from list`.

Do not poll `GET /generate/{id}/status` as one-shot JSON.
