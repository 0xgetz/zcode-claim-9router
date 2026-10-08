#!/usr/bin/env bash
# One-command launcher for the ZCode Pipeline Console (Level 3).
#
#   ./run.sh                 # auto-detect CDP URL (BU_CDP_WS or a running browser)
#   ./run.sh "wss://host/devtools/browser/..."   # explicit CDP URL
#
# It installs the two light deps if missing, then starts the bridge, which
# injects the console into the cloud browser and keeps it live.

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> ZCode Console launcher"

# deps
python3 - <<'PY' || pip install --quiet websockets playwright
import importlib.util, sys
sys.exit(0 if importlib.util.find_spec("websockets") and importlib.util.find_spec("playwright") else 1)
PY

CDP="${1:-${BU_CDP_WS:-}}"

if [[ -z "${CDP}" ]]; then
  echo "!! no CDP URL given and \$BU_CDP_WS is unset."
  echo "   Pass one explicitly:  ./run.sh \"wss://<host>/devtools/browser/<id>\""
  echo "   (get it from your Browser Use cloud session, or any Chromium with --remote-debugging-port)"
  exit 2
fi

echo "==> CDP: ${CDP}"
echo "==> starting bridge (Ctrl+C to stop)"
exec python3 "${HERE}/console_bridge.py" --cdp "${CDP}"
