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

### Speech (MLX TTS on port 8002)

Speak Selection, Stream Speak, and Generate WAV from Text no longer call Voicebox `POST /speak` or `POST /generate`. Those endpoints often stay `generating` and their status URL is SSE, not a single JSON body.

They use:

1. A Finder list of sample clip voices from `/Users/admin/Music/sample-audio-clips`
2. `POST http://127.0.0.1:8002/v1/audio/speech` with matching `*_10s.wav` + `.srt`
3. Playback via `ffplay` or `afplay` (Speak / Stream Speak), or `<stem>.mp3` beside the text file (Generate WAV)

Stream Speak is the same low-latency MLX path as Speak Selection; it does not use Voicebox `/generate/stream`.

Set `VOICEBOX_PROFILE` to skip the clip picker (name must match a clip label).

### Library actions (Voicebox `:17493`)

Transcribe, clone, import zip/audio, add sample, avatar, export, load/unload Qwen, clear cache, and compose still talk to Voicebox. Profile lists use Finder-front `choose from list`. Compose still `POST .../compose` and copies to the clipboard without waiting on TTS.

Do not poll `GET /generate/{id}/status` as one-shot JSON.
