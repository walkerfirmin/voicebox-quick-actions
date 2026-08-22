#!/usr/bin/env python3
"""Emit MenuCue-compatible packages + Automator .workflow bundles."""
from __future__ import annotations

import json
import textwrap
import uuid
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

ROOT = Path("/Users/admin/git/voicebox-quick-actions")

PRELUDE = r'''
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

vb_fail() {
  osascript >/dev/null 2>&1 <<EOF
tell application "System Events" to activate
display alert "Voicebox" message $(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$1")
EOF
  echo "FAIL $1" >> /tmp/vb-speak-selection.log
  exit 1
}

vb_ok() {
  osascript -e "display notification \"$1\" with title \"Voicebox\"" >/dev/null 2>&1 || true
}

vb_base() {
  if [[ -n "${VOICEBOX_API:-}" ]]; then
    echo "${VOICEBOX_API%/}"
    return
  fi
  local port
  port="$(ps -axo command= | python3 -c 'import sys,re
for line in sys.stdin:
    m = re.search(r"voicebox-server.*--port\s+(\d+)", line)
    if m:
        print(m.group(1))
        break
')"
  if [[ -n "$port" ]]; then
    echo "http://127.0.0.1:${port}"
  else
    echo "http://127.0.0.1:17493"
  fi
}

vb_ensure() {
  local api tries
  api="$(vb_base)"
  if curl -sf --max-time 2 "${api}/health" >/dev/null 2>&1; then
    printf "%s" "$api"
    return
  fi
  vb_ok "Starting Voicebox…"
  open -a Voicebox >/dev/null 2>&1 || true
  tries=0
  while (( tries < 20 )); do
    sleep 1
    api="$(vb_base)"
    if curl -sf --max-time 2 "${api}/health" >/dev/null 2>&1; then
      printf "%s" "$api"
      return
    fi
    tries=$((tries + 1))
  done
  vb_fail "Voicebox is not running. Open Voicebox and try again."
}

vb_read_text() {
  local t=""
  if [[ $# -gt 0 ]]; then
    t="$*"
  elif [[ -p /dev/stdin || ! -t 0 ]]; then
    t="$(cat | tr -d '\000-\010\013\014\016-\031\177')"
  fi
  printf "%s" "$t"
}

vb_choose_profile() {
  local api="$1" out rc
  set +e
  out="$(vb_pick_profile "$api")"
  rc=$?
  set -e
  if [[ $rc -eq 0 && -z "$out" ]]; then
    exit 0
  fi
  if [[ $rc -ne 0 || -z "$out" ]]; then
    vb_fail "Could not list Voicebox voices. Is Voicebox running?"
  fi
  printf "%s" "$out"
}

vb_pick_profile() {
  local api="$1"
  python3 - "$api" <<'PY'
import json, os, subprocess, sys, tempfile, urllib.request
from pathlib import Path

api = sys.argv[1]
log = Path("/tmp/vb-speak-selection.log")
def logw(msg):
    prev = log.read_text() if log.exists() else ""
    log.write_text(prev + msg + "\n")

forced = os.environ.get("VOICEBOX_PROFILE", "").strip()
last_path = Path.home() / "Library/Application Support/voicebox-quick-actions/last-profile.txt"
try:
    profiles = json.loads(urllib.request.urlopen(api + "/profiles", timeout=15).read())
except Exception as e:
    logw(f"list failed: {e}")
    print(f"ERR list failed: {e}", file=sys.stderr)
    sys.exit(2)
if not profiles:
    logw("no profiles")
    sys.exit(2)
by_name = {p["name"]: p["id"] for p in profiles}
names = [p["name"] for p in profiles]

def emit(name):
    last_path.parent.mkdir(parents=True, exist_ok=True)
    last_path.write_text(name + "\n", encoding="utf-8")
    print(by_name[name])
    print(name)

if forced:
    match = next((n for n in names if n.lower() == forced.lower()), None)
    if not match:
        logw(f"VOICEBOX_PROFILE not found: {forced}")
        sys.exit(2)
    emit(match)
    sys.exit(0)

last = last_path.read_text(encoding="utf-8").strip() if last_path.exists() else ""
default = last if last in names else names[0]
quoted = ", ".join(json.dumps(n) for n in names)
script = f"""
tell application "System Events" to activate
delay 0.15
set voiceNames to {{{quoted}}}
set theChoice to choose from list voiceNames with title "Voicebox" with prompt "Choose a Voicebox voice" default items {{{json.dumps(default)}}} OK button name "Speak" cancel button name "Cancel"
if theChoice is false then
  return "CANCEL"
end if
return item 1 of theChoice
"""
with tempfile.NamedTemporaryFile("w", suffix=".applescript", delete=False) as fh:
    fh.write(script)
    path = fh.name
try:
    out = subprocess.check_output(["osascript", path], text=True).strip()
finally:
    Path(path).unlink(missing_ok=True)
logw(f"picker out={out!r}")
if out in ("", "CANCEL", "false"):
    sys.exit(0)
emit(out)
PY
}

vb_srt_text() {
  python3 - "$1" <<'PY'
import re, sys
from pathlib import Path
p = Path(sys.argv[1])
if not p.exists():
    sys.exit(0)
lines = []
for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
    line = line.strip()
    if not line or re.fullmatch(r"\d+", line) or re.match(r"\d{2}:\d{2}:\d{2}[,.]\d+", line):
        continue
    lines.append(line)
print(" ".join(lines))
PY
}

vb_json_field() {
  python3 -c 'import json,sys; d=json.loads(sys.stdin.read() or "{}"); print(d.get(sys.argv[1] or "") or d.get("text") or d.get("transcript") or "")' "$1"
}

vb_transcribe_file() {
  local api="$1" f="$2"
  curl -sf --max-time 120 -X POST "${api}/transcribe" -F "file=@${f}" | python3 -c 'import json,sys
d=json.loads(sys.stdin.read() or "{}")
print(d.get("text") or d.get("transcript") or d.get("transcription") or "")'
}
'''

SCRIPTS: dict[str, str] = {}

SCRIPTS["speak-selection"] = PRELUDE + r'''
echo "$(date '+%Y-%m-%d %H:%M:%S') speak-selection start args=$#" >> /tmp/vb-speak-selection.log
TEXT="$(vb_read_text "$@")"
echo "text_len=${#TEXT}" >> /tmp/vb-speak-selection.log
if [[ -z "${TEXT//[$' \t\n\r']/}" ]]; then
  vb_fail "No text selected. Highlight text, then run Speak Selection from the Services menu."
fi
if (( ${#TEXT} > 500 )); then
  TEXT="${TEXT:0:500}"
fi
CLIP_DIR="/Users/admin/Music/sample-audio-clips"
TTS_HOST="http://127.0.0.1:8002"
LAST="$HOME/Library/Application Support/voicebox-quick-actions/last-profile.txt"
NAME="${VOICEBOX_PROFILE:-}"
if [[ -z "$NAME" ]]; then
  NAME="$(python3 - "$CLIP_DIR" "$LAST" <<'PY'
import json, subprocess, sys, tempfile
from pathlib import Path

clip = Path(sys.argv[1])
last_path = Path(sys.argv[2])
voices = []
seen = set()
for wav in sorted(clip.glob("*.wav")):
    stem = wav.stem
    if stem.endswith("_10s"):
        stem = stem[: -4]
    label = " ".join(p.capitalize() if p.lower() != "and" else p for p in stem.split("_"))
    if label.lower() in seen:
        continue
    seen.add(label.lower())
    voices.append(label)
if not voices:
    sys.exit(2)
last = last_path.read_text(encoding="utf-8").strip() if last_path.exists() else ""
default = last if last in voices else voices[0]
quoted = ", ".join(json.dumps(n) for n in voices)
script = f"""
tell application "Finder"
  activate
  set voiceNames to {{{quoted}}}
  set theChoice to choose from list voiceNames with title "Speak Selection" with prompt "Choose a voice" default items {{{json.dumps(default)}}} OK button name "Speak" cancel button name "Cancel"
  if theChoice is false then
    return "CANCEL"
  end if
  return item 1 of theChoice
end tell
"""
with tempfile.NamedTemporaryFile("w", suffix=".applescript", delete=False) as fh:
    fh.write(script)
    path = fh.name
try:
    out = subprocess.check_output(["osascript", path], text=True).strip()
finally:
    Path(path).unlink(missing_ok=True)
if out in ("", "CANCEL", "false"):
    sys.exit(0)
last_path.parent.mkdir(parents=True, exist_ok=True)
last_path.write_text(out + "\n", encoding="utf-8")
print(out)
PY
)"
  rc=$?
  if [[ $rc -eq 0 && -z "$NAME" ]]; then
    exit 0
  fi
  if [[ $rc -ne 0 || -z "$NAME" ]]; then
    vb_fail "Could not show the voice picker."
  fi
fi
mkdir -p "$(dirname "$LAST")"
printf "%s\n" "$NAME" > "$LAST"
echo "voice=$NAME via mlx :8002" >> /tmp/vb-speak-selection.log
OUT="/tmp/vb-speak-selection.mp3"
python3 - "$TTS_HOST" "$CLIP_DIR" "$NAME" "$TEXT" "$OUT" <<'PY'
import json, re, sys, urllib.error, urllib.request
from pathlib import Path
host, clip_dir, name, text, out = sys.argv[1:6]
clip = Path(clip_dir)
slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
wav = None
for cand in (clip / f"{slug}_10s.wav", clip / f"{slug}.wav", clip / f"{slug}_10s.mp3"):
    if cand.exists():
        wav = cand
        break
if wav is None:
    sys.stderr.write(f"no sample wav for {name} ({slug})\n")
    sys.exit(3)
stem = wav.stem.replace("_10s", "")
srt = None
for cand in (wav.with_suffix(".srt"), clip / f"{slug}.srt", clip / f"{stem}.srt"):
    if cand.exists():
        srt = cand
        break
ref = ""
if srt is not None:
    lines = []
    for line in srt.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or re.fullmatch(r"\d+", line) or re.match(r"\d{2}:\d{2}:\d{2}", line):
            continue
        lines.append(line)
    ref = " ".join(lines)
if not ref:
    sys.stderr.write("missing reference transcript\n")
    sys.exit(3)
payload = json.dumps({
    "model": "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-6bit",
    "input": text,
    "ref_audio": str(wav),
    "ref_text": ref,
    "speed": 1.0,
    "seed": 42,
}).encode()
req = urllib.request.Request(host + "/v1/audio/speech", data=payload, headers={"Content-Type": "application/json"}, method="POST")
try:
    with urllib.request.urlopen(req, timeout=90) as r:
        Path(out).write_bytes(r.read())
except urllib.error.HTTPError as e:
    sys.stderr.write(e.read().decode("utf-8", "replace")[:500])
    sys.exit(4)
print(wav.name)
PY
RC=$?
if [[ $RC -ne 0 || ! -s "$OUT" ]]; then
  echo "mlx failed rc=$RC" >> /tmp/vb-speak-selection.log
  vb_fail "Could not synthesize with $NAME (MLX TTS on port 8002)."
fi
vb_ok "Speaking with ${NAME}"
if command -v ffplay >/dev/null; then
  ffplay -nodisp -autoexit -loglevel error "$OUT"
else
  afplay "$OUT"
fi
'''

SCRIPTS["generate-wav-from-text"] = PRELUDE + r'''
API="$(vb_ensure)"
PICK="$(vb_choose_profile "$API")"
PID="$(printf "%s\n" "$PICK" | sed -n '1p')"
NAME="$(printf "%s\n" "$PICK" | sed -n '2p')"
(( $# > 0 )) || vb_fail "Select a text file in Finder."
for f in "$@"; do
  [[ -f "$f" ]] || continue
  TEXT="$(cat "$f")"
  if [[ -z "${TEXT//[$' \t\n\r']/}" ]]; then
    vb_fail "Empty file: $f"
  fi
  BODY="$(python3 -c 'import json,sys; print(json.dumps({"profile_id": sys.argv[1], "text": sys.argv[2], "engine": "qwen", "language": "en"}))' "$PID" "$TEXT")"
  RESP="$(curl -sf --max-time 60 -X POST "${API}/generate" -H "Content-Type: application/json" -d "$BODY")" \
    || vb_fail "Generate request failed."
  GID="$(printf "%s" "$RESP" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); print(d.get("id") or d.get("generation_id") or "")')"
  [[ -n "$GID" ]] || vb_fail "No generation id returned."
  STATUS=""
  for _ in {1..180}; do
    ST="$(curl -sf --max-time 10 "${API}/generate/${GID}/status")" || true
    STATUS="$(printf "%s" "$ST" | python3 -c 'import json,sys
try:
  d=json.loads(sys.stdin.read() or "{}")
except Exception:
  d={}
print((d.get("status") or d.get("state") or "").lower())')"
    case "$STATUS" in
      completed|complete|done|success|ready) break ;;
      failed|error|cancelled|canceled) vb_fail "Generation failed ($STATUS)." ;;
    esac
    sleep 1
  done
  DIR="$(dirname "$f")"
  BASE="$(basename "$f")"
  STEM="${BASE%.*}"
  OUT="${DIR}/${STEM}.wav"
  curl -sf --max-time 120 -L "${API}/audio/${GID}" -o "$OUT" || vb_fail "Could not download audio."
  vb_ok "Saved ${STEM}.wav using ${NAME}."
done
'''

SCRIPTS["transcribe-audio"] = PRELUDE + r'''
API="$(vb_ensure)"
(( $# > 0 )) || vb_fail "Select an audio file in Finder."
for f in "$@"; do
  [[ -f "$f" ]] || continue
  TEXT="$(vb_transcribe_file "$API" "$f")"
  [[ -n "$TEXT" ]] || vb_fail "Empty transcript for $f"
  DIR="$(dirname "$f")"
  BASE="$(basename "$f")"
  STEM="${BASE%.*}"
  printf "%s\n" "$TEXT" > "${DIR}/${STEM}.txt"
  vb_ok "Wrote ${STEM}.txt"
done
'''

SCRIPTS["new-cloned-voice"] = PRELUDE + r'''
API="$(vb_ensure)"
(( $# > 0 )) || vb_fail "Select an audio file in Finder."
AUDIO=""
for f in "$@"; do
  case "${f:l}" in
    *.wav|*.mp3|*.m4a|*.flac|*.ogg|*.aiff|*.aif) AUDIO="$f"; break ;;
  esac
done
[[ -n "$AUDIO" ]] || AUDIO="$1"
[[ -f "$AUDIO" ]] || vb_fail "Not a file: $AUDIO"
NAME="$(osascript -e 'text returned of (display dialog "New voice name:" default answer "" with title "Voicebox")')" \
  || exit 0
NAME="$(printf "%s" "$NAME" | python3 -c 'import sys; print(sys.stdin.read().strip())')"
[[ -n "$NAME" ]] || vb_fail "Name required."
DIR="$(dirname "$AUDIO")"
BASE="$(basename "$AUDIO")"
STEM="${BASE%.*}"
SRT=""
for cand in "${DIR}/${STEM}.srt" "${DIR}/${STEM%_10s}.srt"; do
  [[ -f "$cand" ]] && SRT="$cand" && break
done
if [[ -n "$SRT" ]]; then
  REF="$(vb_srt_text "$SRT")"
else
  REF="$(vb_transcribe_file "$API" "$AUDIO")"
fi
[[ -n "$REF" ]] || vb_fail "Need a transcript (matching .srt or Whisper)."
BODY="$(python3 -c 'import json,sys; print(json.dumps({"name": sys.argv[1], "description": sys.argv[2], "language": "en", "voice_type": "cloned", "default_engine": "qwen"}))' "$NAME" "Cloned from $(basename "$AUDIO")")"
PROF="$(curl -sf --max-time 30 -X POST "${API}/profiles" -H "Content-Type: application/json" -d "$BODY")" \
  || vb_fail "Could not create profile (name may already exist)."
PID="$(printf "%s" "$PROF" | python3 -c 'import json,sys; print(json.loads(sys.stdin.read())["id"])')"
curl -sf --max-time 60 -X POST "${API}/profiles/${PID}/samples" -F "file=@${AUDIO}" -F "reference_text=${REF}" >/dev/null \
  || vb_fail "Could not add sample."
vb_ok "Created voice ${NAME}."
'''

SCRIPTS["import-voice-zip"] = PRELUDE + r'''
API="$(vb_ensure)"
(( $# > 0 )) || vb_fail "Select a Voicebox profile zip in Finder."
for f in "$@"; do
  [[ -f "$f" ]] || continue
  curl -sf --max-time 60 -X POST "${API}/profiles/import" -F "file=@${f}" >/dev/null \
    || vb_fail "Import failed for $f"
  vb_ok "Imported $(basename "$f")"
done
'''

SCRIPTS["add-sample-to-voice"] = PRELUDE + r'''
API="$(vb_ensure)"
PICK="$(vb_choose_profile "$API")"
PID="$(printf "%s\n" "$PICK" | sed -n '1p')"
NAME="$(printf "%s\n" "$PICK" | sed -n '2p')"
(( $# > 0 )) || vb_fail "Select an audio file in Finder."
for AUDIO in "$@"; do
  [[ -f "$AUDIO" ]] || continue
  DIR="$(dirname "$AUDIO")"
  BASE="$(basename "$AUDIO")"
  STEM="${BASE%.*}"
  SRT=""
  for cand in "${DIR}/${STEM}.srt" "${DIR}/${STEM%_10s}.srt"; do
    [[ -f "$cand" ]] && SRT="$cand" && break
  done
  if [[ -n "$SRT" ]]; then
    REF="$(vb_srt_text "$SRT")"
  else
    REF="$(vb_transcribe_file "$API" "$AUDIO")"
  fi
  [[ -n "$REF" ]] || vb_fail "Need a transcript for $AUDIO"
  curl -sf --max-time 60 -X POST "${API}/profiles/${PID}/samples" -F "file=@${AUDIO}" -F "reference_text=${REF}" >/dev/null \
    || vb_fail "Could not add sample to ${NAME}."
  vb_ok "Added sample to ${NAME}."
done
'''

SCRIPTS["import-audio-into-voicebox"] = PRELUDE + r'''
API="$(vb_ensure)"
(( $# > 0 )) || vb_fail "Select an audio file in Finder."
for f in "$@"; do
  [[ -f "$f" ]] || continue
  curl -sf --max-time 60 -X POST "${API}/generate/import" -F "file=@${f}" >/dev/null \
    || vb_fail "Import failed for $f"
  vb_ok "Imported $(basename "$f") into History."
done
'''

SCRIPTS["set-profile-avatar"] = PRELUDE + r'''
API="$(vb_ensure)"
PICK="$(vb_choose_profile "$API")"
PID="$(printf "%s\n" "$PICK" | sed -n '1p')"
NAME="$(printf "%s\n" "$PICK" | sed -n '2p')"
(( $# > 0 )) || vb_fail "Select an image in Finder."
IMG="$1"
[[ -f "$IMG" ]] || vb_fail "Not a file: $IMG"
curl -sf --max-time 30 -X POST "${API}/profiles/${PID}/avatar" -F "file=@${IMG}" >/dev/null \
  || vb_fail "Avatar upload failed."
vb_ok "Updated avatar for ${NAME}."
'''

SCRIPTS["export-voice"] = PRELUDE + r'''
API="$(vb_ensure)"
PICK="$(vb_choose_profile "$API")"
PID="$(printf "%s\n" "$PICK" | sed -n '1p')"
NAME="$(printf "%s\n" "$PICK" | sed -n '2p')"
SAFE="$(python3 -c 'import re,sys; print(re.sub(r"[^A-Za-z0-9._-]+", "-", sys.argv[1]).strip("-") or "voice")' "$NAME")"
OUT="${HOME}/Downloads/${SAFE}.voicebox.zip"
curl -sf --max-time 60 -L "${API}/profiles/${PID}/export" -o "$OUT" \
  || vb_fail "Export failed."
vb_ok "Saved ${SAFE}.voicebox.zip to Downloads."
'''

SCRIPTS["load-unload-qwen"] = PRELUDE + r'''
API="$(vb_ensure)"
CHOICE="$(osascript -e 'choose from list {"Load Qwen 1.7B", "Unload model"} with prompt "Voicebox model" OK button name "Run"')" \
  || exit 0
[[ "$CHOICE" == "false" ]] && exit 0
if [[ "$CHOICE" == "Load Qwen 1.7B" ]]; then
  curl -sf --max-time 300 -X POST "${API}/models/load?model_size=1.7B" >/dev/null \
    || vb_fail "Load failed (the model may still be downloading)."
  vb_ok "Load requested for Qwen 1.7B."
else
  curl -sf --max-time 60 -X POST "${API}/models/unload" >/dev/null \
    || vb_fail "Unload failed."
  vb_ok "Unload requested."
fi
'''

SCRIPTS["clear-cache"] = PRELUDE + r'''
API="$(vb_ensure)"
osascript -e 'display dialog "Clear Voicebox generation cache? Profiles are not deleted." with title "Voicebox" buttons {"Cancel", "Clear"} default button "Cancel" cancel button "Cancel"' >/dev/null \
  || exit 0
curl -sf --max-time 60 -X POST "${API}/cache/clear" >/dev/null \
  || vb_fail "Clear cache failed."
vb_ok "Cache cleared."
'''

SCRIPTS["compose-in-character"] = PRELUDE + r'''
API="$(vb_ensure)"
PICK="$(vb_choose_profile "$API")"
PID="$(printf "%s\n" "$PICK" | sed -n '1p')"
NAME="$(printf "%s\n" "$PICK" | sed -n '2p')"
RESP="$(curl -sf --max-time 60 -X POST "${API}/profiles/${PID}/compose")" \
  || vb_fail "Compose failed (the profile may need a personality prompt)."
TEXT="$(printf "%s" "$RESP" | python3 -c 'import json,sys
d=json.loads(sys.stdin.read() or "{}")
print(d.get("text") or d.get("utterance") or d.get("content") or json.dumps(d))')"
printf "%s" "$TEXT" | pbcopy
vb_ok "Copied in-character line for ${NAME}."
'''

SCRIPTS["stream-speak"] = PRELUDE + r'''
API="$(vb_ensure)"
TEXT="$(vb_read_text "$@")"
if [[ -z "${TEXT//[$' \t\n\r']/}" ]]; then
  vb_fail "No text selected. Highlight text, then run Stream Speak from the Services menu."
fi
PICK="$(vb_choose_profile "$API")"
PID="$(printf "%s\n" "$PICK" | sed -n '1p')"
NAME="$(printf "%s\n" "$PICK" | sed -n '2p')"
BODY="$(python3 -c 'import json,sys; print(json.dumps({"profile_id": sys.argv[1], "text": sys.argv[2], "engine": "qwen", "language": "en"}))' "$PID" "$TEXT")"
TMP="$(mktemp -t vbstream)"
HDR="$(mktemp -t vbhdr)"
CODE="$(curl -sS --max-time 120 -X POST "${API}/generate/stream" -H "Content-Type: application/json" -d "$BODY" -D "$HDR" -o "$TMP" -w "%{http_code}" || true)"
CT="$(python3 -c 'import sys
p=open(sys.argv[1],encoding="utf-8",errors="replace").read().lower()
print("audio" if "content-type:" in p and "audio" in p else "other")
' "$HDR")"
if [[ "$CODE" == "200" && "$CT" == "audio" ]]; then
  afplay "$TMP" || vb_fail "Could not play streamed audio."
else
  SBODY="$(python3 -c 'import json,sys; print(json.dumps({"text": sys.argv[1], "profile": sys.argv[2], "personality": False, "engine": "qwen"}))' "$TEXT" "$NAME")"
  curl -sf --max-time 120 -X POST "${API}/speak" -H "Content-Type: application/json" -d "$SBODY" >/dev/null \
    || vb_fail "Stream failed; speak fallback also failed."
  vb_ok "Played via /speak (${NAME})."
fi
rm -f "$TMP" "$HDR"
'''

PACKAGES = [
    {
        "slug": "speak-selection",
        "name": "Speak Selection",
        "summary": "Speaks selected text in a Voicebox cloned voice on your speakers.",
        "readme": "Reads the highlighted text aloud in a chosen Voicebox voice and plays it on your speakers. Does not save a file.",
        "tags": ["text", "voicebox", "speak"],
        "receives": ["text"],
        "kind": "text",
        "file_types": [],
        "how": "Select text → Services → **Speak Selection**. A Finder voice list appears (last voice is pre-selected). Audio plays via the local MLX TTS server on port 8002. Set `VOICEBOX_PROFILE` to skip the picker.",
    },
    {
        "slug": "generate-wav-from-text",
        "name": "Generate WAV from Text",
        "summary": "Turns a selected text file into a spoken WAV saved beside it.",
        "readme": "Turns a selected text file into spoken audio using a chosen voice, waits until generation finishes, and saves a WAV next to the original file.",
        "tags": ["finder", "voicebox", "generate"],
        "receives": ["files"],
        "kind": "finder",
        "file_types": ["public.text"],
        "how": "Select a `.txt` or `.md` file in Finder → Quick Actions → **Generate WAV from Text**.",
    },
    {
        "slug": "transcribe-audio",
        "name": "Transcribe Audio",
        "summary": "Transcribes selected audio with Voicebox Whisper to a sidecar .txt.",
        "readme": "Runs Voicebox Whisper on the selected audio and writes the spoken words to a sidecar `.txt` beside the clip.",
        "tags": ["finder", "voicebox", "transcribe"],
        "receives": ["files"],
        "kind": "finder",
        "file_types": ["public.audio"],
        "how": "Select wav/mp3/m4a in Finder → Quick Actions → **Transcribe Audio**.",
    },
    {
        "slug": "new-cloned-voice",
        "name": "New Cloned Voice",
        "summary": "Creates a cloned Voicebox profile from selected audio and a transcript.",
        "readme": "Creates a new Voicebox voice profile from a selected audio clip and its matching `.srt` (timestamps stripped). If no SRT exists, Whisper transcribes the clip first.",
        "tags": ["finder", "voicebox", "clone"],
        "receives": ["files"],
        "kind": "finder",
        "file_types": ["public.audio"],
        "how": "Select an audio file (optional sibling `.srt`) → Quick Actions → **New Cloned Voice**. Enter a profile name.",
    },
    {
        "slug": "import-voice-zip",
        "name": "Import Voice ZIP",
        "summary": "Imports an exported Voicebox profile zip into the local app.",
        "readme": "Installs an exported Voicebox profile archive so the voice appears in Profiles without recreating samples by hand.",
        "tags": ["finder", "voicebox", "import"],
        "receives": ["files"],
        "kind": "finder",
        "file_types": ["public.zip-archive", "public.data"],
        "how": "Select a `.zip` / `.voicebox.zip` → Quick Actions → **Import Voice ZIP**.",
    },
    {
        "slug": "add-sample-to-voice",
        "name": "Add Sample to Voice",
        "summary": "Adds another reference recording to an existing cloned voice.",
        "readme": "Attaches another reference recording to an existing cloned voice so cloning quality can improve. You pick which profile receives the file.",
        "tags": ["finder", "voicebox", "clone"],
        "receives": ["files"],
        "kind": "finder",
        "file_types": ["public.audio"],
        "how": "Select audio → Quick Actions → **Add Sample to Voice** → pick a profile.",
    },
    {
        "slug": "import-audio-into-voicebox",
        "name": "Import Audio into Voicebox",
        "summary": "Uploads a local recording into Voicebox History.",
        "readme": "Uploads a local recording into Voicebox History so it shows up in the app without using the in-app file picker.",
        "tags": ["finder", "voicebox", "history"],
        "receives": ["files"],
        "kind": "finder",
        "file_types": ["public.audio"],
        "how": "Select audio → Quick Actions → **Import Audio into Voicebox**.",
    },
    {
        "slug": "set-profile-avatar",
        "name": "Set Profile Avatar",
        "summary": "Sets a Finder image as a Voicebox voice card avatar.",
        "readme": "Sets the selected image as the picture on a Voicebox voice card after you choose which profile to update.",
        "tags": ["finder", "voicebox", "avatar"],
        "receives": ["files"],
        "kind": "finder",
        "file_types": ["public.image"],
        "how": "Select an image → Quick Actions → **Set Profile Avatar** → pick a profile.",
    },
    {
        "slug": "export-voice",
        "name": "Export Voice",
        "summary": "Exports a chosen voice profile zip to Downloads.",
        "readme": "Downloads a chosen voice profile as a zip you can back up or share, including its samples and metadata.",
        "tags": ["voicebox", "export"],
        "receives": [],
        "kind": "none",
        "file_types": [],
        "how": "Run **Export Voice** from Services / MenuCue, pick a profile. The zip lands in `~/Downloads`.",
    },
    {
        "slug": "load-unload-qwen",
        "name": "Load or Unload Qwen",
        "summary": "Loads Qwen 1.7B into memory or unloads the TTS model.",
        "readme": "Loads the TTS model into memory so generation is ready, or unloads it to free RAM. Does not generate or transcribe anything by itself.",
        "tags": ["voicebox", "models"],
        "receives": [],
        "kind": "none",
        "file_types": [],
        "how": "Run **Load or Unload Qwen** from Services and choose Load or Unload.",
    },
    {
        "slug": "clear-cache",
        "name": "Clear Voicebox Cache",
        "summary": "Clears Voicebox generation cache after a confirm dialog.",
        "readme": "Deletes Voicebox’s local generation cache to reclaim disk. Does not delete voice profiles.",
        "tags": ["voicebox", "maintenance"],
        "receives": [],
        "kind": "none",
        "file_types": [],
        "how": "Run **Clear Voicebox Cache** from Services and confirm.",
    },
    {
        "slug": "compose-in-character",
        "name": "Compose in Character",
        "summary": "Copies a fresh in-character line for a chosen voice to the clipboard.",
        "readme": "Asks Voicebox for a fresh utterance in the chosen profile’s character voice (the compose API does not take the selected text as input) and copies the result to the clipboard.",
        "tags": ["text", "voicebox", "llm"],
        "receives": ["text"],
        "kind": "text",
        "file_types": [],
        "how": "Select any text (or run from Services) → **Compose in Character** → pick a profile. Result is on the clipboard.",
    },
    {
        "slug": "stream-speak",
        "name": "Stream Speak",
        "summary": "Speaks selected text via stream playback, falling back to /speak.",
        "readme": "Starts speaking selected text as audio arrives when `/generate/stream` returns audio; otherwise falls back to `POST /speak`.",
        "tags": ["text", "voicebox", "speak"],
        "receives": ["text"],
        "kind": "text",
        "file_types": [],
        "how": "Select text → Services → **Stream Speak** → pick a voice.",
    },
]


def uuid_for(slug: str, n: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"voicebox-qa:{slug}:{n}")).upper()


def info_plist(pkg: dict) -> str:
    bid = f"com.voicebox.quickaction.{pkg['slug']}"
    name = pkg["name"]
    ns_extra = ""
    if pkg["kind"] == "finder":
        types = "".join(f"\t\t\t\t<string>{t}</string>\n" for t in pkg["file_types"])
        ns_extra = f"""
			<key>NSRequiredContext</key>
			<dict>
				<key>NSApplicationIdentifier</key>
				<string>com.apple.finder</string>
			</dict>
			<key>NSSendFileTypes</key>
			<array>
{types}			</array>"""
    elif pkg["kind"] == "text":
        ns_extra = """
			<key>NSBackgroundColorName</key>
			<string>background</string>
			<key>NSIconName</key>
			<string>NSActionTemplate</string>
			<key>NSSendTypes</key>
			<array>
				<string>public.utf8-plain-text</string>
				<string>public.plain-text</string>
				<string>NSStringPboardType</string>
			</array>"""
    elif pkg["kind"] == "none":
        ns_extra = """
			<key>NSBackgroundColorName</key>
			<string>background</string>
			<key>NSIconName</key>
			<string>NSActionTemplate</string>"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleName</key>
	<string>{xml_escape(name)}</string>
	<key>CFBundleIdentifier</key>
	<string>{bid}</string>
	<key>CFBundleShortVersionString</key>
	<string>1.0.0</string>
	<key>CFBundleVersion</key>
	<string>1</string>
	<key>CFBundlePackageType</key>
	<string>WFLO</string>
	<key>NSServices</key>
	<array>
		<dict>
			<key>NSMenuItem</key>
			<dict>
				<key>default</key>
				<string>{xml_escape(name)}</string>
			</dict>
			<key>NSMessage</key>
			<string>runWorkflowAsService</string>{ns_extra}
		</dict>
	</array>
</dict>
</plist>
"""


def workflow_meta(pkg: dict) -> str:
    if pkg["kind"] == "finder":
        return """		<key>serviceApplicationBundleID</key>
		<string>com.apple.finder</string>
		<key>serviceApplicationPath</key>
		<string>/System/Library/CoreServices/Finder.app</string>
		<key>serviceInputTypeIdentifier</key>
		<string>com.apple.Automator.fileSystemObject</string>
		<key>serviceOutputTypeIdentifier</key>
		<string>com.apple.Automator.nothing</string>
		<key>serviceProcessesInput</key>
		<integer>0</integer>
		<key>workflowTypeIdentifier</key>
		<string>com.apple.Automator.services.quickaction</string>"""
    if pkg["kind"] == "text":
        return """		<key>inputTypeIdentifier</key>
		<string>com.apple.Automator.text</string>
		<key>outputTypeIdentifier</key>
		<string>com.apple.Automator.nothing</string>
		<key>presentationMode</key>
		<integer>11</integer>
		<key>processesInput</key>
		<false/>
		<key>serviceInputTypeIdentifier</key>
		<string>com.apple.Automator.text</string>
		<key>serviceOutputTypeIdentifier</key>
		<string>com.apple.Automator.nothing</string>
		<key>serviceProcessesInput</key>
		<false/>
		<key>systemImageName</key>
		<string>NSActionTemplate</string>
		<key>useAutomaticInputType</key>
		<true/>
		<key>workflowTypeIdentifier</key>
		<string>com.apple.Automator.servicesMenu</string>"""
    return """		<key>inputTypeIdentifier</key>
		<string>com.apple.Automator.nothing</string>
		<key>outputTypeIdentifier</key>
		<string>com.apple.Automator.nothing</string>
		<key>presentationMode</key>
		<integer>11</integer>
		<key>serviceInputTypeIdentifier</key>
		<string>com.apple.Automator.nothing</string>
		<key>serviceOutputTypeIdentifier</key>
		<string>com.apple.Automator.nothing</string>
		<key>systemImageName</key>
		<string>NSActionTemplate</string>
		<key>workflowTypeIdentifier</key>
		<string>com.apple.Automator.servicesMenu</string>"""


def document_wflow(pkg: dict) -> str:
    script = textwrap.dedent(SCRIPTS[pkg["slug"]]).strip() + "\n"
    input_method = 0 if pkg["kind"] == "text" else 1
    optional = "true" if pkg["kind"] != "finder" else "true"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>AMApplicationBuild</key>
	<string>523</string>
	<key>AMApplicationVersion</key>
	<string>2.10</string>
	<key>AMDocumentVersion</key>
	<string>2</string>
	<key>actions</key>
	<array>
		<dict>
			<key>action</key>
			<dict>
				<key>AMAccepts</key>
				<dict>
					<key>Container</key>
					<string>List</string>
					<key>Optional</key>
					<{optional}/>
					<key>Types</key>
					<array>
						<string>com.apple.cocoa.string</string>
					</array>
				</dict>
				<key>AMActionVersion</key>
				<string>2.0.3</string>
				<key>AMApplication</key>
				<array>
					<string>Automator</string>
				</array>
				<key>AMParameterProperties</key>
				<dict>
					<key>COMMAND_STRING</key>
					<dict/>
					<key>CheckedForUserDefaultShell</key>
					<dict/>
					<key>inputMethod</key>
					<dict/>
					<key>shell</key>
					<dict/>
					<key>source</key>
					<dict/>
				</dict>
				<key>AMProvides</key>
				<dict>
					<key>Container</key>
					<string>List</string>
					<key>Types</key>
					<array>
						<string>com.apple.cocoa.string</string>
					</array>
				</dict>
				<key>ActionBundlePath</key>
				<string>/System/Library/Automator/Run Shell Script.action</string>
				<key>ActionName</key>
				<string>Run Shell Script</string>
				<key>ActionParameters</key>
				<dict>
					<key>COMMAND_STRING</key>
					<string>{xml_escape(script)}</string>
					<key>CheckedForUserDefaultShell</key>
					<true/>
					<key>inputMethod</key>
					<integer>{input_method}</integer>
					<key>shell</key>
					<string>/bin/zsh</string>
					<key>source</key>
					<string></string>
				</dict>
				<key>BundleIdentifier</key>
				<string>com.apple.RunShellScript</string>
				<key>CFBundleVersion</key>
				<string>2.0.3</string>
				<key>CanShowSelectedItemsWhenRun</key>
				<false/>
				<key>CanShowWhenRun</key>
				<true/>
				<key>Category</key>
				<array>
					<string>AMCategoryUtilities</string>
				</array>
				<key>Class Name</key>
				<string>RunShellScriptAction</string>
				<key>InputUUID</key>
				<string>{uuid_for(pkg["slug"], 1)}</string>
				<key>Keywords</key>
				<array>
					<string>Shell</string>
					<string>Script</string>
					<string>Command</string>
					<string>Run</string>
					<string>Unix</string>
				</array>
				<key>OutputUUID</key>
				<string>{uuid_for(pkg["slug"], 2)}</string>
				<key>UUID</key>
				<string>{uuid_for(pkg["slug"], 3)}</string>
				<key>UnlocalizedApplications</key>
				<array>
					<string>Automator</string>
				</array>
				<key>isViewVisible</key>
				<integer>1</integer>
			</dict>
			<key>isViewVisible</key>
			<integer>1</integer>
		</dict>
	</array>
	<key>connectors</key>
	<dict/>
	<key>workflowMetaData</key>
	<dict>
{workflow_meta(pkg)}
	</dict>
</dict>
</plist>
"""


def main() -> None:
    index = {
        "schemaVersion": 1,
        "name": "Voicebox Quick Actions",
        "updatedAt": "2026-08-22",
        "packages": [],
    }
    for pkg in PACKAGES:
        slug = pkg["slug"]
        wf_name = f"{pkg['name']}.workflow"
        dest = ROOT / "packages" / slug
        wf = dest / wf_name / "Contents"
        wf.mkdir(parents=True, exist_ok=True)
        (wf / "Info.plist").write_text(info_plist(pkg), encoding="utf-8")
        (wf / "document.wflow").write_text(document_wflow(pkg), encoding="utf-8")
        package = {
            "id": f"com.voicebox.quickaction.{slug}",
            "name": pkg["name"],
            "version": "1.0.0",
            "author": "Voicebox",
            "readme": "README.md",
            "workflow": wf_name,
            "workflowZip": "workflow.zip",
            "servicesReceives": pkg["receives"],
            "dependencies": {"brew": []},
            "minMacOS": "13.0",
            "checksum": "",
        }
        (dest / "package.json").write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
        (dest / "README.md").write_text(
            f"# {pkg['name']}\n\n{pkg['readme']}\n\n## Dependencies\n\nVoicebox running locally.\n\n## How to use\n\n{pkg['how']}\n",
            encoding="utf-8",
        )
        index["packages"].append(
            {
                "id": package["id"],
                "name": pkg["name"],
                "summary": pkg["summary"],
                "version": "1.0.0",
                "tags": pkg["tags"],
                "path": f"packages/{slug}",
            }
        )
        print("wrote", slug)
    (ROOT / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    print("index.json", len(index["packages"]))


if __name__ == "__main__":
    main()
