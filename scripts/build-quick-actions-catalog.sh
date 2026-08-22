#!/usr/bin/env bash
# Build a publishable / bundleable Quick Actions catalog tree:
# index.json, per-package package.json + README.md + workflow.zip (checksum updated in DEST only).
# Default SRC_DIR is the repo root (this catalog lives at the root, unlike MenuCue).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

die() {
  echo "error: $*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: build-quick-actions-catalog.sh [SRC_DIR] DEST_DIR

  SRC_DIR   Catalog source (default: repo root)
  DEST_DIR  Output directory (replaced)

Builds workflow.zip for each package and writes sha256 checksums into DEST package.json.
Does not modify SRC_DIR. Does not copy .workflow source trees into DEST.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -eq 0 ]]; then
  usage >&2
  exit 1
fi

if [[ $# -eq 1 ]]; then
  SRC_DIR="$ROOT"
  DEST_DIR="$1"
elif [[ $# -eq 2 ]]; then
  SRC_DIR="$1"
  DEST_DIR="$2"
else
  usage >&2
  exit 1
fi

if [[ "$SRC_DIR" != /* ]]; then
  SRC_DIR="$ROOT/$SRC_DIR"
fi
if [[ "$DEST_DIR" != /* ]]; then
  DEST_DIR="$ROOT/$DEST_DIR"
fi

[[ -f "$SRC_DIR/index.json" ]] || die "missing index.json in $SRC_DIR"
[[ -d "$SRC_DIR/packages" ]] || die "missing packages/ in $SRC_DIR"

command -v python3 >/dev/null || die "python3 not found"
command -v ditto >/dev/null || die "ditto not found"
command -v shasum >/dev/null || die "shasum not found"

echo "==> Building catalog"
echo "    src:  $SRC_DIR"
echo "    dest: $DEST_DIR"

rm -rf "$DEST_DIR"
mkdir -p "$DEST_DIR/packages"

python3 - "$SRC_DIR/index.json" "$DEST_DIR/index.json" <<'PY'
import json, sys
from pathlib import Path

def scrub(v):
    if isinstance(v, str):
        return v.replace("\r", "").strip()
    if isinstance(v, list):
        return [scrub(x) for x in v]
    if isinstance(v, dict):
        return {k: scrub(val) for k, val in v.items()}
    return v

src, dest = Path(sys.argv[1]), Path(sys.argv[2])
data = scrub(json.loads(src.read_text(encoding="utf-8")))
dest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PY
if [[ -f "$SRC_DIR/README.md" ]]; then
  cp "$SRC_DIR/README.md" "$DEST_DIR/README.md"
fi

shopt -s nullglob
package_dirs=("$SRC_DIR/packages"/*/)
shopt -u nullglob

(( ${#package_dirs[@]} > 0 )) || die "no packages found under $SRC_DIR/packages"

for pkg_src in "${package_dirs[@]}"; do
  slug="$(basename "$pkg_src")"
  [[ "$slug" == .* ]] && continue

  pkg_json="$pkg_src/package.json"
  [[ -f "$pkg_json" ]] || die "missing package.json in packages/$slug"

  workflow_name="$(
    python3 - "$pkg_json" <<'PY'
import json, sys
from pathlib import Path
raw = Path(sys.argv[1]).read_text(encoding="utf-8")
data = json.loads(raw)
name = data.get("workflow") or ""
print(name.replace("\r", "").strip())
PY
  )"

  if [[ -z "$workflow_name" ]]; then
    candidates=("$pkg_src"/*.workflow)
    (( ${#candidates[@]} == 1 )) || die "packages/$slug: set package.json workflow or keep exactly one .workflow"
    workflow_name="$(basename "${candidates[0]}")"
  fi

  workflow_src="$pkg_src/$workflow_name"
  [[ -d "$workflow_src" ]] || die "packages/$slug: workflow not found: $workflow_name"

  pkg_dest="$DEST_DIR/packages/$slug"
  mkdir -p "$pkg_dest"
  cp "$pkg_json" "$pkg_dest/package.json"
  if [[ -f "$pkg_src/README.md" ]]; then
    cp "$pkg_src/README.md" "$pkg_dest/README.md"
  fi

  (
    cd "$pkg_dest"
    rm -f workflow.zip
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT
    ditto "$workflow_src" "$tmp/$workflow_name"
    ditto -c -k --sequesterRsrc --keepParent "$tmp/$workflow_name" workflow.zip
  )

  checksum="sha256:$(shasum -a 256 "$pkg_dest/workflow.zip" | awk '{print $1}')"
  python3 - "$pkg_dest/package.json" "$checksum" "$workflow_name" <<'PY'
import json, sys
from pathlib import Path

path = Path(sys.argv[1])
checksum = sys.argv[2]
workflow_name = sys.argv[3]
data = json.loads(path.read_text(encoding="utf-8"))

def scrub(v):
    if isinstance(v, str):
        return v.replace("\r", "").strip()
    return v

for key in list(data.keys()):
    data[key] = scrub(data[key])
if isinstance(data.get("servicesReceives"), list):
    data["servicesReceives"] = [scrub(x) for x in data["servicesReceives"]]
if isinstance(data.get("dependencies"), dict) and isinstance(data["dependencies"].get("brew"), list):
    data["dependencies"]["brew"] = [scrub(x) for x in data["dependencies"]["brew"]]

data["workflow"] = workflow_name
data["workflowZip"] = "workflow.zip"
data["checksum"] = checksum
path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PY

  echo "    packaged $slug ($workflow_name) $checksum"
done

echo "==> Catalog build complete: $DEST_DIR"
