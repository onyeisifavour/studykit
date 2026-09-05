#!/usr/bin/env bash
# Launch StudyKit desktop app (Electron) with its FastAPI sidecar.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Build renderer + node main if missing or stale.
npm run build >/dev/null 2>&1 || { echo "build failed"; exit 1; }

exec ./node_modules/.bin/electron .
