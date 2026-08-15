#!/usr/bin/env bash
# ============================================================================
# BridgeTalk — one-time setup (macOS / Linux)
#
#   ./scripts/setup.sh
#
# Creates the Python 3.11 virtual environment, installs pinned Python and npm
# dependencies, downloads the MediaPipe HandLandmarker assets, and creates a
# .env from the template if you do not have one yet.
#
# Safe to re-run: every step is idempotent.
# ============================================================================
set -euo pipefail

# Resolve the repository root from this script's own location, so the script
# works no matter which directory you run it from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

BOLD=$'\033[1m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; RESET=$'\033[0m'
step() { printf '\n%s==> %s%s\n' "$BOLD" "$1" "$RESET"; }
ok()   { printf '%s  ✓ %s%s\n' "$GREEN" "$1" "$RESET"; }
warn() { printf '%s  ! %s%s\n' "$YELLOW" "$1" "$RESET"; }
die()  { printf '%s  ✗ %s%s\n' "$RED" "$1" "$RESET" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 1. Locate a Python 3.11 interpreter
# ---------------------------------------------------------------------------
# 3.11 is pinned because TensorFlow 2.16 has no wheels for 3.13, and building
# it from source on a laptop is not a thing you want to do the week of a review.
step "Locating Python 3.11"
PYTHON_BIN=""
for candidate in python3.11 python3.12 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    version="$("$candidate" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    case "$version" in
      3.11|3.12) PYTHON_BIN="$candidate"; break ;;
    esac
  fi
done

if [ -z "$PYTHON_BIN" ]; then
  die "Python 3.11 not found.
     macOS:  brew install python@3.11
     Ubuntu: sudo apt install python3.11 python3.11-venv
     Then re-run this script."
fi
ok "Using $PYTHON_BIN ($("$PYTHON_BIN" --version 2>&1))"

# ---------------------------------------------------------------------------
# 2. Virtual environment + Python dependencies
# ---------------------------------------------------------------------------
step "Creating virtual environment (.venv)"
if [ -d ".venv" ]; then
  ok ".venv already exists — reusing it"
else
  "$PYTHON_BIN" -m venv .venv
  ok "Created .venv"
fi

# shellcheck disable=SC1091
source .venv/bin/activate

step "Installing Python dependencies (this takes a few minutes — TensorFlow is large)"
python -m pip install --upgrade pip setuptools wheel >/dev/null
python -m pip install -r backend/requirements.txt
ok "Python dependencies installed"

# ---------------------------------------------------------------------------
# 3. Node dependencies
# ---------------------------------------------------------------------------
step "Checking Node.js"
command -v node >/dev/null 2>&1 || die "Node.js not found. Install Node 20 LTS or newer from https://nodejs.org"
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
[ "$NODE_MAJOR" -ge 20 ] || die "Node $(node --version) is too old. BridgeTalk needs Node 20 LTS or newer."
ok "Node $(node --version)"

step "Installing npm dependencies"
(cd frontend && npm install)
ok "npm dependencies installed"

# ---------------------------------------------------------------------------
# 4. MediaPipe assets
# ---------------------------------------------------------------------------
# Two separate things are needed in the browser:
#   - hand_landmarker.task : the trained hand-tracking model (~7 MB), fetched
#     from Google's model repository.
#   - the WASM runtime     : ships inside the npm package; we copy it into
#     public/ so Vite serves it from our own origin. Loading it from a CDN
#     instead is the usual cause of the "MediaPipe WASM 404" failure on a
#     college network that blocks external CDNs.
step "Fetching MediaPipe HandLandmarker assets"
MODEL_DIR="frontend/public/models"
MODEL_FILE="$MODEL_DIR/hand_landmarker.task"
MODEL_URL="https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
mkdir -p "$MODEL_DIR"

if [ -s "$MODEL_FILE" ]; then
  ok "hand_landmarker.task already present ($(du -h "$MODEL_FILE" | cut -f1))"
elif curl -fsSL --retry 3 -o "$MODEL_FILE" "$MODEL_URL"; then
  ok "Downloaded hand_landmarker.task ($(du -h "$MODEL_FILE" | cut -f1))"
else
  rm -f "$MODEL_FILE"
  warn "Could not download hand_landmarker.task (offline or blocked network)."
  warn "Download it manually from:"
  warn "  $MODEL_URL"
  warn "and save it to $MODEL_FILE"
fi

WASM_SRC="frontend/node_modules/@mediapipe/tasks-vision/wasm"
WASM_DEST="$MODEL_DIR/wasm"
if [ -d "$WASM_SRC" ]; then
  mkdir -p "$WASM_DEST"
  cp -f "$WASM_SRC"/* "$WASM_DEST"/
  ok "Copied MediaPipe WASM runtime to $WASM_DEST"
else
  warn "MediaPipe WASM runtime not found at $WASM_SRC — did npm install succeed?"
fi

# ---------------------------------------------------------------------------
# 5. Environment file
# ---------------------------------------------------------------------------
step "Checking .env"
if [ -f ".env" ]; then
  ok ".env already exists — leaving it untouched"
else
  cp .env.example .env
  warn "Created .env from .env.example — you MUST edit it:"
  warn "  - DATABASE_URL     : your MySQL user and password"
  warn "  - JWT_SECRET_KEY   : python -c \"import secrets; print(secrets.token_urlsafe(48))\""
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
printf '\n%s==> Setup complete%s\n\n' "$BOLD" "$RESET"
cat <<'NEXT'
Next steps:
  1. Edit .env (database URL + JWT secret).
  2. Create the database:   mysql -u root -p < database/schema.sql
  3. Start the backend:     ./scripts/run_backend.sh
  4. Start the frontend:    ./scripts/run_frontend.sh
  5. Open http://localhost:5173
NEXT
