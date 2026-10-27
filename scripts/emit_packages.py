#!/usr/bin/env python3
"""Emit MenuCue-compatible packages + Automator .workflow bundles."""
from __future__ import annotations

import json
import textwrap
import uuid
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

ROOT = Path("/Users/admin/git/voicebox-quick-actions")
PACKAGE_VERSION = "1.0.2"

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

vb_ensure_tts_ready() {
  local api="$1" out rc
  set +e
  out="$(/usr/bin/python3 - "$api" <<'PY'
import json, sys, time, urllib.error, urllib.parse, urllib.request

api = sys.argv[1].rstrip("/")

def get_json(url, timeout=15):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")

def post_json(url, payload, timeout=300):
    data = None if payload is None else json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode() or "{}"
        try:
            return json.loads(body)
        except Exception:
            return {}

try:
    health = get_json(api + "/health", 5)
except Exception as e:
    print(f"ERROR:Could not reach Voicebox health: {e}")
    sys.exit(2)
if health.get("model_loaded"):
    print(health.get("model_size") or "loaded")
    sys.exit(0)

try:
    status = get_json(api + "/models/status", 15)
except Exception as e:
    print(f"ERROR:Could not list Voicebox models: {e}")
    sys.exit(2)

models = status.get("models") or []
downloaded = [
    m for m in models
    if m.get("downloaded") and "whisper" not in str(m.get("model_name") or "").lower()
]
if not downloaded:
    print(
        "ERROR:No TTS model is downloaded. Download Qwen TTS 1.7B (or another voice model) in Voicebox, then try again."
    )
    sys.exit(2)

prefer = ["qwen-tts-1.7B", "qwen-tts-0.6B", "kokoro", "luxtts"]
choice = next((m for name in prefer for m in downloaded if m.get("model_name") == name), None)
if choice is None:
    choice = downloaded[0]
model_name = choice["model_name"]

def load_model(name: str) -> None:
    try:
        post_json(api + "/models/load", {"model_name": name}, 300)
        return
    except Exception:
        pass
    upper = name.upper()
    size = "1.7B" if "1.7" in upper else ("0.6B" if "0.6" in upper else None)
    if not size:
        raise RuntimeError(f"unsupported model for legacy load: {name}")
    url = api + "/models/load?model_size=" + urllib.parse.quote(size, safe="")
    req = urllib.request.Request(url, method="POST")
    urllib.request.urlopen(req, timeout=300).read()

try:
    load_model(model_name)
except Exception as e:
    detail = str(e)
    if isinstance(e, urllib.error.HTTPError):
        detail = e.read().decode("utf-8", "replace")[:300] or detail
    print(f"ERROR:Could not load {model_name}. {detail}")
    sys.exit(2)

for _ in range(90):
    try:
        health = get_json(api + "/health", 5)
        if health.get("model_loaded"):
            print(health.get("model_size") or model_name)
            sys.exit(0)
    except Exception:
        pass
    time.sleep(1)
print("ERROR:Timed out waiting for the TTS model to load.")
sys.exit(2)
PY
)"
  rc=$?
  set -e
  if [[ $rc -ne 0 ]]; then
    if [[ "$out" == ERROR:* ]]; then
      vb_fail "${out#ERROR:}"
    fi
    vb_fail "No TTS model is ready. Download and load a model in Voicebox, then try again."
  fi
  [[ -n "${VB_QA_SLUG:-}" ]] && vb_log "${VB_QA_SLUG}" "tts_ready=${out}"
  printf "%s" "$out"
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

vb_voicebox_generate() {
  local api="$1" profile_id="$2" text="$3" out="$4"
  local rc err gen_id
  set +e
  err="$(/usr/bin/python3 - "$api" "$profile_id" "$text" <<'PY'
import json, os, sys, urllib.error, urllib.request

api, profile_id, text = sys.argv[1:4]
payload = {"profile_id": profile_id, "text": text}
model_size = os.environ.get("VOICEBOX_MODEL_SIZE", "").strip()
if not model_size:
    try:
        with urllib.request.urlopen(api.rstrip("/") + "/health", timeout=5) as r:
            health = json.loads(r.read().decode() or "{}")
        if health.get("model_loaded") and health.get("model_size"):
            model_size = str(health["model_size"])
    except Exception:
        pass
if model_size:
    payload["model_size"] = model_size
body = json.dumps(payload).encode()
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
import json, os, sys, urllib.error, urllib.request
from pathlib import Path

api, profile_id, text, out = sys.argv[1:5]
payload = {"profile_id": profile_id, "text": text}
model_size = os.environ.get("VOICEBOX_MODEL_SIZE", "").strip()
if not model_size:
    try:
        with urllib.request.urlopen(api.rstrip("/") + "/health", timeout=5) as r:
            health = json.loads(r.read().decode() or "{}")
        if health.get("model_loaded") and health.get("model_size"):
            model_size = str(health["model_size"])
    except Exception:
        pass
if model_size:
    payload["model_size"] = model_size
body = json.dumps(payload).encode()
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
    body = e.read().decode("utf-8", "replace")[:500]
    try:
        detail = json.loads(body).get("detail") or body
    except Exception:
        detail = body
    print(detail)
    sys.exit(4)
except urllib.error.URLError as e:
    print(str(e.reason)[:500])
    sys.exit(4)
if not data:
    print("empty stream response")
    sys.exit(4)
Path(out).write_bytes(data)
print(out)
PY
)"
  rc=$?
  set -e
  if [[ $rc -ne 0 ]]; then
    VB_LAST_STREAM_ERR="${err:0:300}"
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

_vb_chunks_split_long() {
  local text="$1" max_chunk="$2" seg=""
  for word in ${=text}; do
    if [[ -z "$seg" ]]; then
      seg="$word"
    elif (( ${#seg} + 1 + ${#word} <= max_chunk )); then
      seg="$seg $word"
    else
      CHUNKS+=("$seg")
      seg="$word"
    fi
  done
  [[ -n "$seg" ]] && CHUNKS+=("$seg")
}

_vb_chunks_flush_pending() {
  local text="$1" max_chunk="$2"
  [[ -z "$text" ]] && return
  if (( ${#text} > max_chunk )); then
    _vb_chunks_split_long "$text" "$max_chunk"
  else
    CHUNKS+=("$text")
  fi
}

vb_build_speak_chunks() {
  local text="$1"
  local min_chars="${VB_STREAM_MIN_CHARS:-80}"
  local max_chunk="${VB_STREAM_MAX_CHUNK:-400}"
  typeset -g -a CHUNKS
  CHUNKS=()
  typeset -a sentences
  local sent pending merged
  while IFS= read -r sent; do
    sent="${sent## }"
    sent="${sent%% }"
    [[ -n "$sent" ]] && sentences+=("$sent")
  done < <(python3 - "$text" <<'PYEOF'
import sys, re
text = sys.argv[1]
parts = re.split(r'(?<=[.!?])\s+(?=[A-Z"\(\[])', text)
for p in parts:
    p = p.strip()
    if p:
        print(p)
PYEOF
)
  pending=""
  for sent in "${sentences[@]}"; do
    if [[ -z "$pending" ]]; then
      pending="$sent"
    else
      merged="$pending $sent"
      if (( ${#pending} < min_chars && ${#merged} <= max_chunk )); then
        pending="$merged"
      else
        _vb_chunks_flush_pending "$pending" "$max_chunk"
        pending="$sent"
      fi
    fi
  done
  _vb_chunks_flush_pending "$pending" "$max_chunk"
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

_STREAM_SPEAK_BODY = r'''
TEXT="$(vb_read_text "$@")"
vb_log stream-speak "text_len=${#TEXT}"
if [[ -z "${TEXT//[$' \t\n\r']/}" ]]; then
  vb_fail "No text selected. Highlight text, then run this from the Services menu."
fi
MAX_CHARS=20000
if (( ${#TEXT} > MAX_CHARS )); then
  vb_log stream-speak "truncating ${#TEXT} -> $MAX_CHARS"
  TEXT="${TEXT:0:MAX_CHARS}"
fi
command -v ffplay >/dev/null || vb_fail "ffplay is required for chunked playback (brew install ffmpeg)."
API="$(vb_ensure)"
vb_ensure_tts_ready "$API" >/dev/null
PICK="$(vb_choose_profile "$API")"
PID="$(printf "%s\n" "$PICK" | sed -n '1p')"
NAME="$(printf "%s\n" "$PICK" | sed -n '2p')"
[[ -n "$NAME" ]] || exit 0
vb_log stream-speak "voice=$NAME"
MODEL_SIZE="$(/usr/bin/python3 - "$API" <<'PY'
import json, os, urllib.request, sys
api = sys.argv[1]
model_size = os.environ.get("VOICEBOX_MODEL_SIZE", "").strip()
if not model_size:
    try:
        with urllib.request.urlopen(api.rstrip("/") + "/health", timeout=5) as r:
            health = json.loads(r.read().decode() or "{}")
        if health.get("model_loaded") and health.get("model_size"):
            model_size = str(health["model_size"])
    except Exception:
        pass
print(model_size or "default")
PY
)"
vb_log stream-speak "model_size=$MODEL_SIZE"

export VB_STREAM_MIN_CHARS="${VB_STREAM_MIN_CHARS:-40}"
export VB_STREAM_MAX_CHUNK="${VB_STREAM_MAX_CHUNK:-150}"
vb_build_speak_chunks "$TEXT"
(( ${#CHUNKS[@]} > 0 )) || vb_fail "No speakable text after splitting."
vb_log stream-speak "chunks=${#CHUNKS[@]}"
for i in $(seq 1 ${#CHUNKS[@]}); do
  vb_log stream-speak "chunk $i (${#CHUNKS[$i]} chars)"
done

STREAM_DIR="/tmp/vb-stream-speak"
TIMESTAMP=$(date +%s)
mkdir -p "$STREAM_DIR"
typeset -a AUDIO_FILES
for i in $(seq 1 ${#CHUNKS[@]}); do
  AUDIO_FILES+=("$STREAM_DIR/tts_${TIMESTAMP}_chunk${i}.wav")
done

_dispatch_stream() {
  local idx=$1
  local chunk_text="${CHUNKS[$idx]}"
  local audio_file="${AUDIO_FILES[$idx]}"
  rm -f "${audio_file}" "${audio_file}.ready" "${audio_file}.failed"
  vb_log stream-speak "dispatch chunk $idx"
  (
    VB_LAST_STREAM_ERR=""
    if vb_voicebox_stream "$API" "$PID" "$chunk_text" "$audio_file"; then
      touch "${audio_file}.ready"
    else
      [[ -n "${VB_LAST_STREAM_ERR:-}" ]] && printf "%s" "$VB_LAST_STREAM_ERR" > "${audio_file}.failed"
      [[ -f "${audio_file}.failed" ]] || touch "${audio_file}.failed"
    fi
  ) &
}

_wait_stream_chunk() {
  local idx=$1
  local audio_file="${AUDIO_FILES[$idx]}"
  local wait_ticks=0
  local max_ticks=$(( ${VB_STREAM_CHUNK_TIMEOUT:-120} * 20 ))
  while true; do
    if [[ -f "${audio_file}.ready" ]]; then
      return 0
    fi
    if [[ -f "${audio_file}.failed" ]]; then
      return 1
    fi
    sleep 0.05
    (( wait_ticks++ )) || true
    if (( wait_ticks > max_ticks )); then
      return 2
    fi
  done
}

_play_stream_chunk() {
  local idx=$1
  local audio_file="${AUDIO_FILES[$idx]}"
  vb_log stream-speak "play chunk $idx $audio_file"
  set +e
  ffplay -nodisp -autoexit -loglevel error "$audio_file"
  local rc=$?
  set -e
  rm -f "$audio_file" "${audio_file}.ready" "${audio_file}.failed"
  return "$rc"
}

_dispatch_stream 1
vb_ok "Streaming with ${NAME}"

set +e
_wait_stream_chunk 1
rc=$?
set -e
if [[ $rc -eq 1 ]]; then
  detail=""
  [[ -f "${AUDIO_FILES[1]}.failed" ]] && detail="$(tr -d '\000' < "${AUDIO_FILES[1]}.failed" | head -c 240)"
  if [[ -n "$detail" ]]; then
    vb_fail "Could not stream with ${NAME}: ${detail}"
  fi
  vb_fail "Could not stream chunk 1 with ${NAME}. Check that a TTS model is downloaded and loaded."
elif [[ $rc -eq 2 ]]; then
  vb_fail "Timed out waiting for the first audio chunk."
fi

if (( ${#CHUNKS[@]} >= 2 )); then
  _dispatch_stream 2
fi
_play_stream_chunk 1 || vb_fail "Playback failed for chunk 1."

for i in $(seq 2 ${#CHUNKS[@]}); do
  set +e
  _wait_stream_chunk "$i"
  rc=$?
  set -e
  if [[ $rc -eq 1 ]]; then
    vb_log stream-speak "chunk $i synthesis failed, skipping"
    continue
  elif [[ $rc -eq 2 ]]; then
    vb_log stream-speak "chunk $i timed out, skipping"
    continue
  fi
  if (( i < ${#CHUNKS[@]} )); then
    _dispatch_stream $((i + 1))
  fi
  _play_stream_chunk "$i" || vb_log stream-speak "playback failed chunk $i"
done

vb_log stream-speak "done"
'''

_LOAD_VOICEBOX_MODEL_BODY = r'''
API="$(vb_ensure)"
set +e
OUT="$(/usr/bin/python3 - "$API" <<'PY'
from __future__ import annotations

import json, os, subprocess, sys, tempfile, urllib.error, urllib.parse, urllib.request

api = sys.argv[1]
UNLOAD_LABEL = "Unload model"


def fail(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(2)


def fetch_models():
    with urllib.request.urlopen(api.rstrip("/") + "/models/status", timeout=15) as r:
        return json.loads(r.read().decode())["models"]


def model_size_for(model_name: str):
    upper = model_name.upper()
    for size in ("0.6B", "1.7B", "3B", "1B"):
        if size in upper:
            return size
    return None


def post_json(url: str, payload: dict | None, timeout: int):
    data = None if payload is None else json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def load_model(model_name: str):
    base = api.rstrip("/")
    size = model_size_for(model_name)

    def load_by_size(model_size: str):
        req = urllib.request.Request(
            f"{base}/models/load?model_size={urllib.parse.quote(model_size, safe='')}",
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read().decode() or "{}")

    try:
        result = post_json(base + "/models/load", {"model_name": model_name}, 300)
        msg = str(result.get("message", ""))
        if "loaded successfully" in msg.lower():
            if size and size not in msg:
                return load_by_size(size)
            if not size and model_name.lower() not in msg.lower():
                fail(
                    "This Voicebox build does not support loading that model via the API. "
                    "Update Voicebox or load it from the app."
                )
        return result
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        if not size:
            fail(detail or f"Load failed (HTTP {e.code}).")
        try:
            return load_by_size(size)
        except urllib.error.HTTPError as e2:
            fail(e2.read().decode("utf-8", "replace")[:300] or f"Load failed (HTTP {e2.code}).")


def unload_models(loaded_names: list[str]):
    base = api.rstrip("/")
    errors: list[str] = []
    if loaded_names:
        for name in loaded_names:
            try:
                post_json(f"{base}/models/{urllib.parse.quote(name, safe='')}/unload", None, 60)
            except urllib.error.HTTPError as e:
                errors.append(e.read().decode("utf-8", "replace")[:120])
    else:
        try:
            post_json(base + "/models/unload", None, 60)
        except urllib.error.HTTPError as e:
            errors.append(e.read().decode("utf-8", "replace")[:120])
    if errors and len(errors) == len(loaded_names or [""]):
        fail(errors[0])


def choose_from_list(items: list[str], prompt: str, default: str) -> str:
    if not items:
        fail("No Voicebox models are available.")
    if default not in items:
        default = items[0]
    quoted = ", ".join(json.dumps(item) for item in items)
    script = (
        "tell application \"Finder\"\n"
        "  activate\n"
        f"  set theItems to {{{quoted}}}\n"
        f"  set theChoice to choose from list theItems with title \"Voicebox\" with prompt {json.dumps(prompt)} "
        f"default items {{{json.dumps(default)}}} OK button name \"Run\" cancel button name \"Cancel\"\n"
        "  if theChoice is false then\n"
        "    return \"CANCEL\"\n"
        "  end if\n"
        "  return item 1 of theChoice\n"
        "end tell\n"
    )
    path = tempfile.mkstemp(suffix=".applescript")[1]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(script)
    try:
        out = subprocess.check_output(["osascript", path], text=True).strip()
    finally:
        os.unlink(path)
    if out in ("", "CANCEL", "false"):
        sys.exit(0)
    return out


try:
    models = fetch_models()
except Exception as e:
    fail(f"Could not list Voicebox models: {e}")

downloaded = [m for m in models if m.get("downloaded")]
if not downloaded:
    fail("No Voicebox models are downloaded yet. Download a model in Voicebox first.")

labels: list[str] = []
label_to_name: dict[str, str] = {}
loaded_names = [m["model_name"] for m in downloaded if m.get("loaded")]
for model in downloaded:
    label = model["display_name"]
    if model.get("loaded"):
        label += " (loaded)"
    labels.append(label)
    label_to_name[label] = model["model_name"]

labels.append(UNLOAD_LABEL)
default = next(
  (label for label in labels if label_to_name.get(label) in loaded_names),
  labels[0],
)
choice = choose_from_list(labels, "Choose a Voicebox model to load or unload", default)

if choice == UNLOAD_LABEL:
    if loaded_names:
        if len(loaded_names) == 1:
            unload_models(loaded_names)
            print(f"UNLOAD:{loaded_names[0]}")
        else:
            unload_labels = [next(m["display_name"] for m in downloaded if m["model_name"] == n) for n in loaded_names]
            unload_labels.append("Unload all loaded models")
            picked = choose_from_list(
                unload_labels,
                "Choose a model to unload",
                unload_labels[0],
            )
            if picked == "Unload all loaded models":
                unload_models(loaded_names)
                print("UNLOAD:all")
            else:
                name = next(m["model_name"] for m in downloaded if m["display_name"] == picked)
                unload_models([name])
                print(f"UNLOAD:{name}")
    else:
        unload_models([])
        print("UNLOAD:default")
else:
    model_name = label_to_name[choice]
    result = load_model(model_name)
    print(f"LOAD:{model_name}|{choice}")
PY
)"
rc=$?
set -e
if [[ $rc -eq 2 ]]; then
  vb_fail "${OUT:-Could not load or unload a Voicebox model.}"
fi
if [[ $rc -ne 0 || -z "$OUT" ]]; then
  vb_log load-voicebox-model "picker cancelled"
  exit 0
fi
if [[ "$OUT" == UNLOAD:* ]]; then
  vb_log load-voicebox-model "unload ${OUT#UNLOAD:}"
  vb_ok "Unload requested."
else
  NAME="${OUT#LOAD:}"
  NAME="${NAME%%|*}"
  DISPLAY="${OUT#*|}"
  vb_log load-voicebox-model "load $NAME"
  vb_ok "Load requested for ${DISPLAY%% (loaded)}."
fi
'''

SCRIPTS["load-voicebox-model"] = PRELUDE + _LOAD_VOICEBOX_MODEL_BODY

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

PACKAGES = [
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
        "slug": "load-voicebox-model",
        "name": "Load Voicebox Model",
        "summary": "Loads or unloads a downloaded Voicebox TTS model from a menu.",
        "readme": "Lists downloaded models from `GET /models/status`, lets you pick one to load into memory, or unload the active model(s). Uses `POST /models/load` (with legacy `model_size` fallback) and per-model unload.",
        "tags": ["voicebox", "models"],
        "receives": [],
        "kind": "none",
        "file_types": [],
        "how": "Run **Load Voicebox Model** from Services, pick a downloaded model to load, or choose **Unload model** to free RAM.",
    },
    {
        "slug": "stream-speak",
        "name": "Stream Speak",
        "summary": "Streams selected text as WAV from Voicebox with chunked synthesis and gapless local playback.",
        "readme": "Uses Voicebox `POST /generate/stream` one chunk at a time. Splits on sentence boundaries into ~150-character chunks for fast first audio. While each chunk plays locally via ffplay, the next chunk synthesizes in the background (Voicebox handles one stream at a time). Supports up to 20,000 characters. Passes the currently loaded `model_size` from `/health` (or `VOICEBOX_MODEL_SIZE`) so generation does not force the 1.7B default.",
        "tags": ["text", "voicebox", "speak"],
        "receives": ["text"],
        "kind": "text",
        "file_types": [],
        "how": "Select text → Services → **Stream Speak** → pick a Voicebox profile. Requires ffplay (`brew install ffmpeg`). Long selections are chunked automatically for fast start and continuous playback.",
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
	<string>{PACKAGE_VERSION}</string>
	<key>CFBundleVersion</key>
	<string>2</string>
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
        "updatedAt": "2026-08-27",
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
            "version": PACKAGE_VERSION,
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
                "version": PACKAGE_VERSION,
                "tags": pkg["tags"],
                "path": f"packages/{slug}",
            }
        )
        print("wrote", slug)
    (ROOT / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    print("index.json", len(index["packages"]))


if __name__ == "__main__":
    main()
