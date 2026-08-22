# Speak Selection

Reads the highlighted text aloud in a chosen Voicebox voice and plays it on your speakers. Does not save a file.

## Dependencies

Voicebox running locally.

## How to use

Select text → Services → **Speak Selection**. Speaks with the last voice (default Ad) using the same local MLX TTS server on port 8002 as Speak with MLX TTS Ad. Set `VOICEBOX_PROFILE` or edit `~/Library/Application Support/voicebox-quick-actions/last-profile.txt` to change voice (must match a sample in Music/sample-audio-clips).
