# Stream Speak

Uses Voicebox `POST /generate/stream` to receive WAV audio directly (no History export step), saves each clip under `/tmp/vb-stream-speak/`, then plays it locally — the same pattern a remote client would use to fetch and play on its own machine.

## Dependencies

Voicebox running locally.

## How to use

Select text → Services → **Stream Speak** → pick a Voicebox profile. WAV is saved in `/tmp/vb-stream-speak/` then played.
