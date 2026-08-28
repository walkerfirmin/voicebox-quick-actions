# Changelog

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

Speak Selection and Stream Speak call `POST /speak` and let Voicebox play the audio (no local playback).

Generate WAV from Text uses `POST /generate`, polls `GET /history/{id}` until `completed`, then `GET /history/{id}/export-audio` to save `<stem>.wav`.

### Library actions (Voicebox `:17493`)

Transcribe, clone, import zip/audio, add sample, avatar, export, load/unload Qwen, and clear cache still talk to Voicebox. Profile lists use Finder-front `choose from list`.

Do not poll `GET /generate/{id}/status` as one-shot JSON.
