# Voicebox Quick Actions

MenuCue-compatible catalog of Automator Quick Actions that talk to a local [Voicebox](https://docs.voicebox.sh) server (`voicebox-server` on `127.0.0.1`).

Voicebox must be running. If it is not, most actions try `open -a Voicebox` and wait for `/health`. Override the base URL with `VOICEBOX_API` (for example `http://127.0.0.1:17493`).

**Debug logs:** each action writes to `/tmp/vb-qa-<slug>.log` (for example `/tmp/vb-qa-transcribe-audio.log`); all actions also append to `/tmp/vb-qa.log`.

## Layout

```text
index.json
packages/<slug>/
  package.json
  README.md
  <Name>.workflow/
```

This repo **is** the catalog root (same shape as MenuCue’s `QuickActionsCatalog/`). `workflow.zip` files are not committed; CI builds them for GitHub Pages.

## Install with MenuCue

In MenuCue → **Quick Action Repo Manager…** → **Add Repository…**, paste:

```
https://walkerfirmin.github.io/voicebox-quick-actions/index.json
```

Only HTTPS indexes are accepted. `workflow.zip` files are built by CI and served from GitHub Pages (not committed to git).

## Install locally (without MenuCue)

Copy each `.workflow` into `~/Library/Services/`, or open it in Automator and save as a Quick Action.

```bash
for d in packages/*/*.workflow; do
  cp -R "$d" ~/Library/Services/
done
/System/Library/CoreServices/pbs -flush
```

## Packages

**Build first:** Stream Speak, Generate WAV from Text, Transcribe Audio, Import Voice ZIP.

**Nice later:** Export Voice, Load or Unload Qwen.
