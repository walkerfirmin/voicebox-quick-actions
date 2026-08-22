# Voicebox Quick Actions

MenuCue-compatible catalog of Automator Quick Actions that talk to a local [Voicebox](https://docs.voicebox.sh) server (`voicebox-server` on `127.0.0.1`).

Voicebox must be running. If it is not, most actions try `open -a Voicebox` and wait for `/health`. Override the base URL with `VOICEBOX_API` (for example `http://127.0.0.1:17493`).

## Layout

```text
index.json
packages/<slug>/
  package.json
  README.md
  <Name>.workflow/
```

This repo **is** the catalog root (same shape as MenuCue’s `QuickActionsCatalog/`). `workflow.zip` files are not committed; CI builds them for GitHub Pages.

## Install locally (before Pages)

Copy each `.workflow` into `~/Library/Services/`, or open it in Automator and save as a Quick Action.

```bash
for d in packages/*/*.workflow; do
  cp -R "$d" ~/Library/Services/
done
/System/Library/CoreServices/pbs -flush
```

## Add to MenuCue later

1. Push this repo and enable **Settings → Pages → Source = GitHub Actions**.
2. After deploy, in MenuCue → **Quick Action Repo Manager…** → **Add Repository…**
3. Paste `https://<user>.github.io/voicebox-quick-actions/index.json`

Only HTTPS indexes are accepted.

## Packages

**Build first:** Speak Selection, Generate WAV from Text, Transcribe Audio, New Cloned Voice, Import Voice ZIP, Add Sample to Voice, Import Audio into Voicebox, Set Profile Avatar.

**Nice later:** Export Voice, Load or Unload Qwen, Clear Voicebox Cache, Compose in Character, Stream Speak.
