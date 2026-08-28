# Speak Selection

Reads highlighted text aloud using the local MLX TTS server (port 8002) and a sample clip voice. Does not use Voicebox's 1.7B generate queue.

## Dependencies

Voicebox running locally.

## How to use

Select text → Services → **Speak Selection**. A Finder voice list appears. Audio plays via MLX TTS on port 8002. Set `VOICEBOX_PROFILE` to skip the picker.
