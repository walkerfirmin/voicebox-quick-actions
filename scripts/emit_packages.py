#!/usr/bin/env python3
"""Emit MenuCue-compatible packages + Automator .workflow bundles."""
from __future__ import annotations

import json
import textwrap
import uuid
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

ROOT = Path("/Users/admin/git/voicebox-quick-actions")

PRELUDE = r"""
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
LAST_VB="$HOME/Library/Application Support/voicebox-quick-actions/last-vb-profile.txt"

vb_log() {
  local slug="$1"; shift
  mkdir -p /tmp
  echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "/tmp/vb-qa-${slug}.log"
  echo "$(date '+%Y-%m-%d %H:%M:%S') [$slug] $*" >> /tmp/vb-qa.log
}

vb_shell_start() {
  export VB_QA_SLUG="$1"
  vb_log "$1" "shell start argc=$#"
}

vb_fail() {
  local msg="$1"
  echo "$(date '+%Y-%m-%d %H:%M:%S') FAIL ${msg}" >> /tmp/vb-qa.log
  if [[ -n "${VB_QA_SLUG:-}" ]]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') FAIL ${msg}" >> "/tmp/vb-qa-${VB_QA_SLUG}.log"
  fi
  /usr/bin/python3 - "$msg" <<'PY'
import json, subprocess, sys, tempfile
from pathlib import Path
msg = json.dumps(sys.argv[1])
script = f'''
tell application "Finder"
  activate
  display alert "Voicebox" message {msg}
end tell
'''
p = Path(tempfile.mkstemp(suffix=".applescript")[1])
p.write_text(script)
subprocess.run(["osascript", str(p)], check=False)
p.unlink(missing_ok=True)
PY
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
  local port=""
  set +e
  port="$(ps -axo command= 2>/dev/null | /usr/bin/python3 -c 'import sys,re
for line in sys.stdin:
    m = re.search(r"voicebox-server.*--port\s+(\d+)", line)
    if m:
        print(m.group(1))
        break
')"
  set -e
  if [[ -n "$port" ]]; then
    echo "http://127.0.0.1:${port}"
  else
    echo "http://127.0.0.1:17493"
  fi
}

vb_curl() {
  /usr/bin/osascript - "$@" <<'APPLESCRIPT'
on run argv
  set cmd to item 1 of argv
  return do shell script cmd
end run
APPLESCRIPT
}

vb_ensure() {
  local api tries
  api="$(vb_base)"
  if /usr/bin/curl -sf --max-time 2 "${api}/health" >/dev/null 2>&1 \
    || vb_curl "/usr/bin/curl -sf --max-time 2 $(printf '%q' "${api}/health")" >/dev/null 2>&1; then
    [[ -n "${VB_QA_SLUG:-}" ]] && vb_log "${VB_QA_SLUG}" "api=${api}"
    printf "%s" "$api"
    return
  fi
  vb_ok "Starting Voicebox…"
  /usr/bin/open -a Voicebox >/dev/null 2>&1 || true
  tries=0
  while (( tries < 20 )); do
    sleep 1
    api="$(vb_base)"
    if /usr/bin/curl -sf --max-time 2 "${api}/health" >/dev/null 2>&1 \
      || vb_curl "/usr/bin/curl -sf --max-time 2 $(printf '%q' "${api}/health")" >/dev/null 2>&1; then
      [[ -n "${VB_QA_SLUG:-}" ]] && vb_log "${VB_QA_SLUG}" "api=${api}"
      printf "%s" "$api"
      return
    fi
    tries=$((tries + 1))
  done
  vb_fail "Voicebox is not running. Open Voicebox and try again."
}

vb_write_text() {
  local path="$1" text="$2"
  if printf "%s\n" "$text" > "$path" 2>/dev/null; then
    printf "%s" "$path"
    return 0
  fi
  path="${HOME}/Downloads/$(basename "$path")"
  printf "%s\n" "$text" > "$path" || return 1
  printf "%s" "$path"
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

vb_normalize_path() {
  /usr/bin/python3 - "$1" <<'PY'
import sys
from urllib.parse import unquote, urlparse

raw = sys.argv[1].strip()
if raw.startswith("file://"):
    p = urlparse(raw)
    path = unquote(p.path)
    if p.netloc and p.netloc not in ("", "localhost"):
        path = f"/{p.netloc}{path}"
    print(path)
else:
    print(raw)
PY
}

vb_finder_selection() {
  /usr/bin/osascript 2>/dev/null <<'APPLESCRIPT'
tell application "Finder"
  activate
  delay 0.3
  if (count of selection) is 0 then return ""
  set out to ""
  repeat with f in (selection as list)
    set out to out & (POSIX path of (f as alias)) & linefeed
  end repeat
  return text 1 thru -2 of out
end tell
APPLESCRIPT
}

vb_collect_files() {
  local -a files=()
  local f line
  for f in "$@"; do
    [[ -n "$f" ]] || continue
    files+=("$(vb_normalize_path "$f")")
  done
  if (( ${#files[@]} == 0 )) && [[ -p /dev/stdin || ! -t 0 ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
      line="${line//$'\r'/}"
      [[ -n "$line" ]] || continue
      files+=("$(vb_normalize_path "$line")")
    done
  fi
  if (( ${#files[@]} == 0 )); then
    while IFS= read -r line; do
      [[ -n "$line" ]] || continue
      files+=("$(vb_normalize_path "$line")")
    done < <(vb_finder_selection)
  fi
  printf '%s\n' "${files[@]}"
}

vb_finder_choose() {
  python3 - "$@" <<'PY'
import json, subprocess, sys, tempfile
from pathlib import Path
title, prompt, default, last_path = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
items = json.loads(sys.argv[5])
if not items:
    sys.exit(2)
if default not in items:
    default = items[0]
quoted = ", ".join(json.dumps(n) for n in items)
script = f'''
tell application "Finder"
  activate
  set theItems to {{{quoted}}}
  set theChoice to choose from list theItems with title {json.dumps(title)} with prompt {json.dumps(prompt)} default items {{{json.dumps(default)}}} OK button name "OK" cancel button name "Cancel"
  if theChoice is false then
    return "CANCEL"
  end if
  return item 1 of theChoice
end tell
'''
p = Path(tempfile.mkstemp(suffix=".applescript")[1])
p.write_text(script)
try:
    out = subprocess.check_output(["osascript", str(p)], text=True).strip()
finally:
    p.unlink(missing_ok=True)
if out in ("", "CANCEL", "false"):
    sys.exit(0)
Path(last_path).parent.mkdir(parents=True, exist_ok=True)
Path(last_path).write_text(out + "\n", encoding="utf-8")
print(out)
PY
}

vb_choose_profile() {
  local api="$1" out rc
  set +e
  out="$(vb_pick_profile "$api")"
  rc=$?
  set -e
  if [[ $rc -eq 0 && -z "$out" ]]; then
    [[ -n "${VB_QA_SLUG:-}" ]] && vb_log "${VB_QA_SLUG}" "profile picker cancelled"
    exit 0
  fi
  if [[ $rc -ne 0 || -z "$out" ]]; then
    vb_fail "Could not list Voicebox voices. Is Voicebox running?"
  fi
  printf "%s" "$out"
}

vb_pick_profile() {
  local api="$1"
  python3 - "$api" "$LAST_VB" "${VOICEBOX_PROFILE:-}" <<'PY'
import json, subprocess, sys, tempfile, urllib.request
from pathlib import Path
api, last_path_s, forced = sys.argv[1], sys.argv[2], sys.argv[3].strip()
last_path = Path(last_path_s)
try:
    profiles = json.loads(urllib.request.urlopen(api + "/profiles", timeout=15).read())
except Exception as e:
    print(f"ERR list failed: {e}", file=sys.stderr)
    sys.exit(2)
if not profiles:
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
        sys.exit(2)
    emit(match)
    sys.exit(0)
last = last_path.read_text(encoding="utf-8").strip() if last_path.exists() else ""
default = last if last in names else names[0]
quoted = ", ".join(json.dumps(n) for n in names)
script = f'''
tell application "Finder"
  activate
  set voiceNames to {{{quoted}}}
  set theChoice to choose from list voiceNames with title "Voicebox" with prompt "Choose a Voicebox voice" default items {{{json.dumps(default)}}} OK button name "OK" cancel button name "Cancel"
  if theChoice is false then
    return "CANCEL"
  end if
  return item 1 of theChoice
end tell
'''
p = Path(tempfile.mkstemp(suffix=".applescript")[1])
p.write_text(script)
try:
    out = subprocess.check_output(["osascript", str(p)], text=True).strip()
finally:
    p.unlink(missing_ok=True)
if out in ("", "CANCEL", "false"):
    sys.exit(0)
emit(out)
PY
}

vb_voicebox_wait() {
  local api="$1" gen_id="$2"
  /usr/bin/python3 - "$api" "$gen_id" <<'PY'
import json, sys, time, urllib.error, urllib.request

api, gen_id = sys.argv[1:3]
for _ in range(90):
    try:
        with urllib.request.urlopen(api.rstrip("/") + f"/history/{gen_id}", timeout=10) as r:
            row = json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        print(e.read().decode("utf-8", "replace")[:500], file=sys.stderr)
        sys.exit(4)
    status = row.get("status") or ""
    if status == "completed":
        sys.exit(0)
    if status == "failed":
        print(row.get("error") or "Voicebox generation failed", file=sys.stderr)
        sys.exit(4)
    time.sleep(1)
print("Voicebox generation timed out", file=sys.stderr)
sys.exit(4)
PY
}

vb_voicebox_speak() {
  local api="$1" name="$2" text="$3"
  local rc err
  set +e
  err="$(/usr/bin/python3 - "$api" "$name" "$text" <<'PY'
import json, sys, urllib.error, urllib.request

api, name, text = sys.argv[1:4]
body = json.dumps({"text": text, "profile": name}).encode()
req = urllib.request.Request(
    api.rstrip("/") + "/speak",
    data=body,
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        gen = json.loads(r.read().decode() or "{}")
except urllib.error.HTTPError as e:
    print(e.read().decode("utf-8", "replace")[:500], file=sys.stderr)
    sys.exit(4)
except urllib.error.URLError as e:
    print(str(e.reason)[:500], file=sys.stderr)
    sys.exit(4)
gen_id = gen.get("id")
if not gen_id:
    print(json.dumps(gen)[:500], file=sys.stderr)
    sys.exit(4)
print(gen_id)
PY
)"
  rc=$?
  set -e
  if [[ $rc -ne 0 ]]; then
    [[ -n "$err" ]] && vb_log "${VB_QA_SLUG:-voicebox}" "voicebox speak error: ${err:0:200}"
    return "$rc"
  fi
  set +e
  vb_voicebox_wait "$api" "$err"
  rc=$?
  set -e
  if [[ $rc -ne 0 ]]; then
    vb_log "${VB_QA_SLUG:-voicebox}" "voicebox speak wait failed rc=$rc"
    return "$rc"
  fi
  return 0
}

vb_voicebox_generate() {
  local api="$1" profile_id="$2" text="$3" out="$4"
  local rc err gen_id
  set +e
  err="$(/usr/bin/python3 - "$api" "$profile_id" "$text" <<'PY'
import json, sys, urllib.error, urllib.request

api, profile_id, text = sys.argv[1:4]
body = json.dumps({"profile_id": profile_id, "text": text}).encode()
req = urllib.request.Request(
    api.rstrip("/") + "/generate",
    data=body,
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        gen = json.loads(r.read().decode() or "{}")
except urllib.error.HTTPError as e:
    print(e.read().decode("utf-8", "replace")[:500], file=sys.stderr)
    sys.exit(4)
except urllib.error.URLError as e:
    print(str(e.reason)[:500], file=sys.stderr)
    sys.exit(4)
gen_id = gen.get("id")
if not gen_id:
    print(json.dumps(gen)[:500], file=sys.stderr)
    sys.exit(4)
print(gen_id)
PY
)"
  rc=$?
  set -e
  if [[ $rc -ne 0 ]]; then
    [[ -n "$err" ]] && vb_log "${VB_QA_SLUG:-voicebox}" "voicebox generate error: ${err:0:200}"
    return "$rc"
  fi
  gen_id="$err"
  set +e
  vb_voicebox_wait "$api" "$gen_id"
  rc=$?
  set -e
  if [[ $rc -ne 0 ]]; then
    vb_log "${VB_QA_SLUG:-voicebox}" "voicebox generate wait failed rc=$rc"
    return "$rc"
  fi
  set +e
  err="$(/usr/bin/python3 - "$api" "$gen_id" "$out" <<'PY'
import sys, urllib.error, urllib.request
from pathlib import Path

api, gen_id, out = sys.argv[1:4]
try:
    with urllib.request.urlopen(api.rstrip("/") + f"/history/{gen_id}/export-audio", timeout=60) as r:
        Path(out).write_bytes(r.read())
except urllib.error.HTTPError as e:
    print(e.read().decode("utf-8", "replace")[:500], file=sys.stderr)
    sys.exit(4)
print(out)
PY
)"
  rc=$?
  set -e
  if [[ $rc -ne 0 ]]; then
    [[ -n "$err" ]] && vb_log "${VB_QA_SLUG:-voicebox}" "voicebox export error: ${err:0:200}"
    return "$rc"
  fi
  [[ -s "$out" ]] || return 1
  return 0
}

vb_voicebox_stream() {
  local api="$1" profile_id="$2" text="$3" out="$4"
  local rc err
  mkdir -p "$(dirname "$out")"
  set +e
  err="$(/usr/bin/python3 - "$api" "$profile_id" "$text" "$out" <<'PY'
import json, sys, urllib.error, urllib.request
from pathlib import Path

api, profile_id, text, out = sys.argv[1:5]
body = json.dumps({"profile_id": profile_id, "text": text}).encode()
req = urllib.request.Request(
    api.rstrip("/") + "/generate/stream",
    data=body,
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
except urllib.error.HTTPError as e:
    print(e.read().decode("utf-8", "replace")[:500], file=sys.stderr)
    sys.exit(4)
except urllib.error.URLError as e:
    print(str(e.reason)[:500], file=sys.stderr)
    sys.exit(4)
if not data:
    print("empty stream response", file=sys.stderr)
    sys.exit(4)
Path(out).write_bytes(data)
print(out)
PY
)"
  rc=$?
  set -e
  if [[ $rc -ne 0 ]]; then
    [[ -n "$err" ]] && vb_log "${VB_QA_SLUG:-voicebox}" "voicebox stream error: ${err:0:200}"
    return "$rc"
  fi
  [[ -s "$out" ]] || return 1
  return 0
}

vb_play() {
  local f="$1"
  if command -v ffplay >/dev/null; then
    ffplay -nodisp -autoexit -loglevel error "$f"
  else
    afplay "$f"
  fi
}

vb_transcribe_file() {
  local api="$1" f="$2"
  local cmd resp rc
  cmd="$(/usr/bin/python3 -c 'import shlex,sys; api,f=sys.argv[1],sys.argv[2]; url=api+"/transcribe"; print(f"/usr/bin/curl -s --max-time 120 -X POST {shlex.quote(url)} -F file=@{shlex.quote(f)}")' "$api" "$f")"
  set +e
  resp="$(/usr/bin/curl -s --max-time 120 -X POST "${api}/transcribe" -F "file=@${f}")"
  rc=$?
  if [[ $rc -ne 0 || -z "$resp" ]]; then
    resp="$(vb_curl "$cmd")"
    rc=$?
  fi
  set -e
  if [[ $rc -ne 0 || -z "$resp" ]]; then
    vb_fail "Transcription request failed for $(basename "$f"). Is Voicebox running?"
  fi
  local text
  text="$(printf "%s" "$resp" | /usr/bin/python3 -c 'import json,sys
d=json.loads(sys.stdin.read() or "{}")
if "detail" in d:
    detail = d["detail"]
    if isinstance(detail, dict):
        msg = detail.get("message") or detail.get("detail") or str(detail)
    else:
        msg = str(detail)
    print(f"ERROR:{msg}")
    sys.exit(0)
text = d.get("text") or d.get("transcript") or d.get("transcription") or ""
print(text)')"
  if [[ "$text" == ERROR:* ]]; then
    vb_fail "${text#ERROR:}"
  fi
  [[ -n "$text" ]] || vb_fail "Empty transcript for $(basename "$f")."
  printf "%s" "$text"
}
"""

SCRIPTS: dict[str, str] = {}

_SPEAK_BODY = r'''
TEXT="$(vb_read_text "$@")"
vb_log SPEAK_SLUG "text_len=${#TEXT}"
if [[ -z "${TEXT//[$' \t\n\r']/}" ]]; then
  vb_fail "No text selected. Highlight text, then run this from the Services menu."
fi
if (( ${#TEXT} > 500 )); then
  TEXT="${TEXT:0:500}"
fi
API="$(vb_ensure)"
PICK="$(vb_choose_profile "$API")"
PID="$(printf "%s\n" "$PICK" | sed -n '1p')"
NAME="$(printf "%s\n" "$PICK" | sed -n '2p')"
[[ -n "$NAME" ]] || exit 0
vb_log SPEAK_SLUG "voice=$NAME"
OUT="/tmp/vb-SPEAK_SLUG.wav"
set +e
vb_voicebox_generate "$API" "$PID" "$TEXT" "$OUT"
rc=$?
set -e
if [[ $rc -ne 0 || ! -s "$OUT" ]]; then
  vb_fail "Could not speak with ${NAME}. Is Voicebox running?"
fi
vb_log SPEAK_SLUG "played $OUT"
vb_ok "Speaking with ${NAME}"
vb_play "$OUT"
'''

_STREAM_SPEAK_BODY = r'''
TEXT="$(vb_read_text "$@")"
vb_log stream-speak "text_len=${#TEXT}"
if [[ -z "${TEXT//[$' \t\n\r']/}" ]]; then
  vb_fail "No text selected. Highlight text, then run this from the Services menu."
fi
if (( ${#TEXT} > 500 )); then
  TEXT="${TEXT:0:500}"
fi
API="$(vb_ensure)"
PICK="$(vb_choose_profile "$API")"
PID="$(printf "%s\n" "$PICK" | sed -n '1p')"
NAME="$(printf "%s\n" "$PICK" | sed -n '2p')"
[[ -n "$NAME" ]] || exit 0
vb_log stream-speak "voice=$NAME"
STREAM_DIR="/tmp/vb-stream-speak"
mkdir -p "$STREAM_DIR"
OUT="${STREAM_DIR}/$(date +%Y%m%d-%H%M%S)-$$.wav"
set +e
vb_voicebox_stream "$API" "$PID" "$TEXT" "$OUT"
rc=$?
set -e
if [[ $rc -ne 0 || ! -s "$OUT" ]]; then
  vb_fail "Could not stream speech with ${NAME}. Is Voicebox running?"
fi
vb_log stream-speak "saved $OUT"
vb_ok "Streaming with ${NAME}"
vb_play "$OUT"
'''

SCRIPTS["speak-selection"] = PRELUDE + _SPEAK_BODY.replace("SPEAK_SLUG", "speak-selection")
SCRIPTS["stream-speak"] = PRELUDE + _STREAM_SPEAK_BODY

SCRIPTS["generate-wav-from-text"] = PRELUDE + r'''
(( $# > 0 )) || vb_fail "Select a text file in Finder."
API="$(vb_ensure)"
PICK="$(vb_choose_profile "$API")"
PID="$(printf "%s\n" "$PICK" | sed -n '1p')"
NAME="$(printf "%s\n" "$PICK" | sed -n '2p')"
[[ -n "$NAME" ]] || exit 0
vb_log generate-wav-from-text "voice=$NAME"
for f in "$@"; do
  f="$(vb_normalize_path "$f")"
  [[ -f "$f" ]] || continue
  TEXT="$(cat "$f")"
  if [[ -z "${TEXT//[$' \t\n\r']/}" ]]; then
    vb_fail "Empty file: $f"
  fi
  if (( ${#TEXT} > 4000 )); then
    TEXT="${TEXT:0:4000}"
  fi
  DIR="$(dirname "$f")"
  BASE="$(basename "$f")"
  STEM="${BASE%.*}"
  OUT="${DIR}/${STEM}.wav"
  set +e
  vb_voicebox_generate "$API" "$PID" "$TEXT" "$OUT"
  rc=$?
  set -e
  if [[ $rc -ne 0 || ! -s "$OUT" ]]; then
    vb_fail "Could not synthesize ${STEM} with ${NAME}."
  fi
  vb_log generate-wav-from-text "wrote $OUT"
  vb_ok "Saved $(basename "$OUT") using ${NAME}."
done
'''

SCRIPTS["transcribe-audio"] = PRELUDE + r'''
(( $# > 0 )) || vb_fail "Select an audio file in Finder, then run Transcribe Audio from the Services menu."
API="$(vb_ensure)"
processed=0
for f in "$@"; do
  [[ -f "$f" ]] || { vb_log transcribe-audio "skip missing $f"; continue; }
  vb_log transcribe-audio "transcribing $(basename "$f")"
  set +e
  TEXT="$(vb_transcribe_file "$API" "$f")"
  rc=$?
  set -e
  if [[ $rc -ne 0 ]]; then
    vb_fail "Transcription failed for $(basename "$f")."
  fi
  [[ -n "$TEXT" ]] || vb_fail "Empty transcript for $(basename "$f")"
  DIR="$(dirname "$f")"
  BASE="$(basename "$f")"
  STEM="${BASE%.*}"
  OUT="$(vb_write_text "${DIR}/${STEM}.txt" "$TEXT")" || vb_fail "Could not write ${STEM}.txt"
  /usr/bin/open -R "$OUT" >/dev/null 2>&1 || true
  vb_log transcribe-audio "wrote $OUT"
  vb_ok "Wrote $(basename "$OUT")"
  processed=$((processed + 1))
done
(( processed > 0 )) || vb_fail "Could not read the selected audio file(s)."
'''

SCRIPTS["import-voice-zip"] = PRELUDE + r'''
API="$(vb_ensure)"
(( $# > 0 )) || vb_fail "Select a Voicebox profile zip in Finder."
for f in "$@"; do
  f="$(vb_normalize_path "$f")"
  [[ -f "$f" ]] || continue
  curl -sf --max-time 60 -X POST "${API}/profiles/import" -F "file=@${f}" >/dev/null \
    || vb_fail "Import failed for $f"
  vb_log import-voice-zip "imported $f"
  vb_ok "Imported $(basename "$f")"
done
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
vb_log export-voice "wrote $OUT"
vb_ok "Saved ${SAFE}.voicebox.zip to Downloads."
'''

SCRIPTS["load-unload-qwen"] = PRELUDE + r"""
API="$(vb_ensure)"
set +e
CHOICE="$(python3 - "$LAST_VB" <<'PY'
import json, subprocess, sys, tempfile
from pathlib import Path
items = ["Load Qwen 1.7B", "Unload model"]
quoted = ", ".join(json.dumps(n) for n in items)
script = f'''
tell application "Finder"
  activate
  set theItems to {{{quoted}}}
  set theChoice to choose from list theItems with title "Voicebox" with prompt "Voicebox model" default items {{"Load Qwen 1.7B"}} OK button name "Run" cancel button name "Cancel"
  if theChoice is false then
    return "CANCEL"
  end if
  return item 1 of theChoice
end tell
'''
p = Path(tempfile.mkstemp(suffix=".applescript")[1])
p.write_text(script)
try:
    out = subprocess.check_output(["osascript", str(p)], text=True).strip()
finally:
    p.unlink(missing_ok=True)
print(out)
PY
)"
rc=$?
set -e
if [[ $rc -ne 0 || "$CHOICE" == "CANCEL" || -z "$CHOICE" ]]; then
  vb_log load-unload-qwen "picker cancelled"
  exit 0
fi
if [[ "$CHOICE" == "Load Qwen 1.7B" ]]; then
  curl -sf --max-time 300 -X POST "${API}/models/load?model_size=1.7B" >/dev/null \
    || vb_fail "Load failed (the model may still be downloading)."
  vb_log load-unload-qwen "load requested"
  vb_ok "Load requested for Qwen 1.7B."
else
  curl -sf --max-time 60 -X POST "${API}/models/unload" >/dev/null \
    || vb_fail "Unload failed."
  vb_log load-unload-qwen "unload requested"
  vb_ok "Unload requested."
fi
"""

PACKAGES = [
    {
        "slug": "speak-selection",
        "name": "Speak Selection",
        "summary": "Speaks selected text with a Voicebox profile on your speakers.",
        "readme": "Reads highlighted text aloud via Voicebox `POST /generate`: polls History, exports audio, and plays once locally. Saves a generation entry in Voicebox.",
        "tags": ["text", "voicebox", "speak"],
        "receives": ["text"],
        "kind": "text",
        "file_types": [],
        "how": "Select text → Services → **Speak Selection** → pick a Voicebox profile. Set `VOICEBOX_PROFILE` to skip the picker.",
    },
    {
        "slug": "generate-wav-from-text",
        "name": "Generate WAV from Text",
        "summary": "Turns a selected text file into spoken WAV saved beside it.",
        "readme": "Synthesizes a selected text file with Voicebox `POST /generate` and saves `<stem>.wav` next to the file.",
        "tags": ["finder", "voicebox", "generate"],
        "receives": ["files"],
        "kind": "finder",
        "file_types": ["public.text"],
        "how": "Select a `.txt` or `.md` file in Finder → Quick Actions → **Generate WAV from Text** → pick a Voicebox profile. Writes `<stem>.wav` beside the file.",
    },
    {
        "slug": "transcribe-audio",
        "name": "Transcribe Audio",
        "summary": "Transcribes selected audio with Voicebox Whisper to a sidecar .txt.",
        "readme": "Runs Voicebox Whisper on the selected audio and writes the spoken words to a sidecar `.txt` beside the clip.",
        "tags": ["finder", "voicebox", "transcribe"],
        "receives": ["files"],
        "kind": "finder",
        "file_types": ["public.audio", "public.mp3", "public.mpeg-4-audio", "com.apple.m4a-audio", "public.aiff-audio"],
        "how": "Select wav/mp3/m4a in Finder (click to select it first) → Services → **Transcribe Audio**. Voicebox must be running. Do not open this workflow in Automator — that breaks the Services menu entry.",
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
        "slug": "stream-speak",
        "name": "Stream Speak",
        "summary": "Streams selected text as WAV from Voicebox and plays it from a temp file.",
        "readme": "Uses Voicebox `POST /generate/stream` to receive WAV audio directly (no History export step), saves each clip under `/tmp/vb-stream-speak/`, then plays it locally — the same pattern a remote client would use to fetch and play on its own machine.",
        "tags": ["text", "voicebox", "speak"],
        "receives": ["text"],
        "kind": "text",
        "file_types": [],
        "how": "Select text → Services → **Stream Speak** → pick a Voicebox profile. WAV is saved in `/tmp/vb-stream-speak/` then played.",
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
			<key>NSBackgroundColorName</key>
			<string>background</string>
			<key>NSIconName</key>
			<string>NSActionTemplate</string>
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
		<integer>1</integer>
		<key>workflowTypeIdentifier</key>
		<string>com.apple.Automator.servicesMenu</string>"""
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
		<key>serviceProcessesInput</key>
		<false/>
		<key>systemImageName</key>
		<string>NSActionTemplate</string>
		<key>workflowTypeIdentifier</key>
		<string>com.apple.Automator.servicesMenu</string>"""


FINDER_PATHS_APPLESCRIPT = """on run {input, parameters}
	set logPath to "/tmp/vb-qa-__SLUG__.log"
	set ts to do shell script "date '+%Y-%m-%d %H:%M:%S'"
	do shell script "echo " & quoted form of (ts & " applescript start items=" & (count of input)) & " >> " & quoted form of logPath
	try
		set out to ""
		repeat with i in input
			try
				set p to POSIX path of i
			on error
				try
					set p to POSIX path of (i as alias)
				on error
					set p to i as text
				end try
			end try
			if p starts with "file://" then
				set p to do shell script "/usr/bin/python3 -c 'from urllib.parse import unquote, urlparse; import sys; p=urlparse(sys.argv[1]); print(unquote(p.path))' " & quoted form of p
			end if
			if p is not "" then set out to out & p & linefeed
		end repeat
		if out is "" then
			tell application "Finder"
				activate
				delay 0.3
				set sel to selection
				repeat with f in sel
					set out to out & (POSIX path of (f as alias)) & linefeed
				end repeat
			end tell
		end if
		if out ends with linefeed then set out to text 1 thru -2 of out
		set pathCount to 0
		if out is not "" then set pathCount to count of paragraphs of out
		do shell script "echo " & quoted form of (ts & " applescript paths=" & pathCount) & " >> " & quoted form of logPath
		return out
	on error errMsg number errNum
		do shell script "echo " & quoted form of (ts & " applescript error " & errMsg & " (" & errNum & ")") & " >> " & quoted form of logPath
		return ""
	end try
end run
"""


def finder_paths_applescript(slug: str) -> str:
    return FINDER_PATHS_APPLESCRIPT.replace("__SLUG__", slug)


def inject_script_logging(slug: str, script: str, kind: str) -> str:
    body = textwrap.dedent(script).strip()
    header = [f'vb_shell_start "{slug}"']
    if kind == "finder":
        header.extend(
            [
                "FILES=()",
                'while IFS= read -r line; do',
                '  [[ -n "$line" ]] && FILES+=("$line")',
                'done < <(vb_collect_files "$@")',
                f'vb_log "{slug}" "collected=${{#FILES[@]}}"',
                'set -- "${FILES[@]}"',
            ]
        )
    return "\n".join(header) + "\n" + body + "\n"


def shell_script_action_xml(pkg: dict, script: str, *, input_uuid: str, output_uuid: str, action_uuid: str, input_method: int, accept_types: list[str]) -> str:
    types_xml = "".join(f"\n\t\t\t\t\t<string>{t}</string>" for t in accept_types)
    return f"""		<dict>
			<key>action</key>
			<dict>
				<key>AMAccepts</key>
				<dict>
					<key>Container</key>
					<string>List</string>
					<key>Optional</key>
					<true/>
					<key>Types</key>
					<array>{types_xml}
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
				<string>{input_uuid}</string>
				<key>Keywords</key>
				<array>
					<string>Shell</string>
					<string>Script</string>
					<string>Command</string>
					<string>Run</string>
					<string>Unix</string>
				</array>
				<key>OutputUUID</key>
				<string>{output_uuid}</string>
				<key>UUID</key>
				<string>{action_uuid}</string>
				<key>UnlocalizedApplications</key>
				<array>
					<string>Automator</string>
				</array>
				<key>isViewVisible</key>
				<integer>1</integer>
			</dict>
			<key>isViewVisible</key>
			<integer>1</integer>
		</dict>"""


def applescript_paths_action_xml(pkg: dict) -> str:
    slug = pkg["slug"]
    input_uuid = uuid_for(slug, 10)
    output_uuid = uuid_for(slug, 11)
    action_uuid = uuid_for(slug, 12)
    return f"""		<dict>
			<key>action</key>
			<dict>
				<key>AMAccepts</key>
				<dict>
					<key>Container</key>
					<string>List</string>
					<key>Optional</key>
					<true/>
					<key>Types</key>
					<array>
						<string>com.apple.cocoa.path</string>
						<string>com.apple.alias-record</string>
						<string>com.apple.cocoa.string</string>
					</array>
				</dict>
				<key>AMActionVersion</key>
				<string>1.0.2</string>
				<key>AMApplication</key>
				<array>
					<string>Automator</string>
				</array>
				<key>AMParameterProperties</key>
				<dict>
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
				<string>/System/Library/Automator/Run AppleScript.action</string>
				<key>ActionName</key>
				<string>Run AppleScript</string>
				<key>ActionParameters</key>
				<dict>
					<key>source</key>
					<string>{xml_escape(finder_paths_applescript(slug))}</string>
				</dict>
				<key>BundleIdentifier</key>
				<string>com.apple.Automator.RunScript</string>
				<key>CFBundleVersion</key>
				<string>1.0.2</string>
				<key>CanShowSelectedItemsWhenRun</key>
				<false/>
				<key>CanShowWhenRun</key>
				<true/>
				<key>Category</key>
				<array>
					<string>AMCategoryUtilities</string>
				</array>
				<key>Class Name</key>
				<string>RunScriptAction</string>
				<key>InputUUID</key>
				<string>{input_uuid}</string>
				<key>Keywords</key>
				<array>
					<string>Run</string>
				</array>
				<key>OutputUUID</key>
				<string>{output_uuid}</string>
				<key>UUID</key>
				<string>{action_uuid}</string>
				<key>UnlocalizedApplications</key>
				<array>
					<string>Automator</string>
				</array>
				<key>isViewVisible</key>
				<integer>1</integer>
			</dict>
			<key>isViewVisible</key>
			<integer>1</integer>
		</dict>"""


def document_wflow(pkg: dict) -> str:
    slug = pkg["slug"]
    body = SCRIPTS[slug][len(PRELUDE) :]
    script = PRELUDE + inject_script_logging(slug, body, pkg["kind"])
    input_method = 0 if pkg["kind"] in ("text", "finder") else 1
    accept_types = (
        ["com.apple.cocoa.path", "com.apple.cocoa.string"]
        if pkg["kind"] == "finder"
        else ["com.apple.cocoa.string"]
    )
    slug = pkg["slug"]
    if pkg["kind"] == "finder":
        as_out = uuid_for(slug, 11)
        sh_in = uuid_for(slug, 1)
        actions_xml = applescript_paths_action_xml(pkg) + "\n" + shell_script_action_xml(
            pkg,
            script,
            input_uuid=sh_in,
            output_uuid=uuid_for(slug, 2),
            action_uuid=uuid_for(slug, 3),
            input_method=input_method,
            accept_types=accept_types,
        )
        connectors_xml = f"""	<key>connectors</key>
	<dict>
		<key>{as_out}</key>
		<dict>
			<key>from</key>
			<string>{as_out} - {as_out}</string>
			<key>to</key>
			<string>{sh_in} - {sh_in}</string>
		</dict>
	</dict>"""
    else:
        actions_xml = shell_script_action_xml(
            pkg,
            script,
            input_uuid=uuid_for(slug, 1),
            output_uuid=uuid_for(slug, 2),
            action_uuid=uuid_for(slug, 3),
            input_method=input_method,
            accept_types=accept_types,
        )
        connectors_xml = """	<key>connectors</key>
	<dict/>"""
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
{actions_xml}
	</array>
{connectors_xml}
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
