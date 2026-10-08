#!/usr/bin/env bash
# One-command launcher for the ZCode Pipeline Console.
#
#   ./run.sh                     # auto-launch a LOCAL Chrome (windowed on desktop,
#                                #   headless on a VPS) and inject the console
#   ./run.sh --headless          # force headless
#   ./run.sh --connect 127.0.0.1:9222   # attach to a Chrome you already run
#   ./run.sh --cdp "wss://..."   # use a remote/cloud browser
#   ./run.sh --port 9222         # pick the local debug port
#   ./run.sh --profile work      # reuse a named profile (keeps logins)
#
# No cloud account or $BU_CDP_WS needed. Requires Chrome/Chromium (or Playwright's
# bundled chromium) plus the two Python deps installed below.

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> ZCode Console launcher"

# 1) Python deps
python3 - <<'PY' || pip install --quiet websockets playwright
import importlib.util, sys
sys.exit(0 if importlib.util.find_spec("websockets") else 1)
PY

# 2) A browser must exist somewhere. Prefer a system Chrome; else Playwright's.
if ! command -v google-chrome >/dev/null 2>&1 \
   && ! command -v chromium >/dev/null 2>&1 \
   && ! command -v chromium-browser >/dev/null 2>&1 \
   && ! command -v chrome >/dev/null 2>&1 \
   && [ ! -d "${HOME}/.cache/ms-playwright" ]; then
  echo "==> no Chrome/Chromium found — installing Playwright's chromium"
  python3 -m playwright install chromium || true
fi

echo "==> starting bridge (Ctrl+C to stop)"
exec python3 "${HERE}/src/console_bridge.py" "$@"
