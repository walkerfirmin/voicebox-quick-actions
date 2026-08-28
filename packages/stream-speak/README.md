# Stream Speak

Uses Voicebox `POST /generate/stream` one chunk at a time. Splits on sentence boundaries into ~150-character chunks for fast first audio. While each chunk plays locally via ffplay, the next chunk synthesizes in the background (Voicebox handles one stream at a time). Supports up to 20,000 characters.

## Dependencies

Voicebox running locally.

## How to use

Select text → Services → **Stream Speak** → pick a Voicebox profile. Requires ffplay (`brew install ffmpeg`). Long selections are chunked automatically for fast start and continuous playback.
