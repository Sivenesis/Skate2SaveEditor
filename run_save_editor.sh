#!/usr/bin/env bash
# -----------------------------------------------------------------
# Touchgrind Skate 2 // Save Editor Launcher for macOS & Linux
# -----------------------------------------------------------------

set -e

# Switch to script directory
cd "$(dirname "$0")"

echo "===================================================="
echo "TOUCHGRIND SKATE 2 // SAVE EDITOR"
echo "===================================================="
echo

# Detect Python interpreter
PY_CMD=""
if command -v python3 &>/dev/null; then
    PY_CMD="python3"
elif command -v python &>/dev/null; then
    PY_CMD="python"
else
    echo "[ERROR] Python 3 was not detected on your system PATH."
    echo
    echo "Please install Python 3.10 or newer to run this editor."
    echo "macOS: brew install python3"
    echo "Linux: sudo apt update && sudo apt install python3"
    exit 1
fi

echo "[INFO] Detected Python runtime: $($PY_CMD --version)"
echo

PORT="8765"
if [ -n "$1" ]; then
    PORT="$1"
fi

URL="http://localhost:${PORT}"
echo "[INFO] Starting web server on ${URL} ..."
echo "[INFO] Launching default web browser..."
echo

# Open browser in parallel
if [[ "$OSTYPE" == "darwin"* ]]; then
    open "${URL}" &
elif command -v xdg-open &>/dev/null; then
    xdg-open "${URL}" &
fi

# Run editor server module (blocks until Ctrl+C)
exec "$PY_CMD" -m editor.server --port "${PORT}"
