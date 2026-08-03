#!/usr/bin/env bash
# Build the dataset if it is missing, then serve the PWA locally.
set -euo pipefail

cd "$(dirname "$0")"

VERSES="${VERSES:-../scripture_text.db}"
ANNOTATIONS="${ANNOTATIONS:-../resources/annotations/scripture_annotations_20260802.sqlite}"
PORT="${PORT:-8000}"

if [ ! -f app/data/app.sqlite ]; then
  echo "building app/data/app.sqlite …"
  python3 build_data.py --verses "$VERSES" --annotations "$ANNOTATIONS"
fi

echo "serving http://localhost:$PORT  (ctrl-c to stop)"
cd app
exec python3 -m http.server "$PORT"
