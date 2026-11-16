# Load Voicebox Model

Lists downloaded TTS models from `GET /models/status`, lets you pick one to load into memory, or unload the active model(s). Qwen models use `POST /models/load?model_size=…` and are detected via `/models/status` plus `/health.model_size`. Other engines (Chatterbox, LuxTTS, Kokoro, TADA) warm-load via a short `POST /generate/stream` with the matching `engine`. Unload uses `POST /models/{model_name}/unload` (and also `POST /models/unload` for Qwen). Selecting a `(loaded)` model toggles it off; load/unload results are verified before the action finishes.

## Dependencies

Voicebox running locally.

## How to use

Run **Load Voicebox Model** from Services, pick a downloaded model to load, select a `(loaded)` model to unload it, or choose **Unload model** to free RAM.
