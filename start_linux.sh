#!/bin/bash
# RF Tactical Monitor - Linux Launcher
# Starts dump1090 for ADS-B, then launches the main app.
#
# Prerequisites:
#   - dump1090 installed (apt install dump1090-mutability, or build from source)
#   - HackRF One connected (for ADS-B via dump1090)
#   - Python3 with PyQt5, pyqtgraph, numpy, pyModeS installed
#
# On Raspberry Pi / Debian:
#   sudo apt install dump1090-mutability
#   pip3 install PyQt5 pyqtgraph numpy pyModeS

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================================"
echo " RF TACTICAL MONITOR - Linux Launcher"
echo "============================================================"
echo ""

DUMP1090_PID=""

# Check for dump1090
if command -v dump1090 &>/dev/null; then
    DUMP1090_BIN="dump1090"
elif [ -x "$SCRIPT_DIR/tools/dump1090" ]; then
    DUMP1090_BIN="$SCRIPT_DIR/tools/dump1090"
else
    DUMP1090_BIN=""
fi

# Start dump1090 if found
if [ -n "$DUMP1090_BIN" ]; then
    echo "Starting dump1090 for ADS-B on port 30003/30005..."
    $DUMP1090_BIN --device-type hackrf --net --quiet &
    DUMP1090_PID=$!
    echo "dump1090 started (PID: $DUMP1090_PID)"
    echo "Waiting for dump1090 to initialize..."
    sleep 3
    echo "dump1090 ready - Beast on :30005, SBS on :30003"
else
    echo ""
    echo "WARNING: dump1090 not found!"
    echo "ADS-B decoding will not be available."
    echo ""
    echo "To enable ADS-B:"
    echo "  sudo apt install dump1090-mutability"
    echo "  Or build from: https://github.com/antirez/dump1090"
    echo ""
    echo "The app will still start - other features work without dump1090."
    echo ""
    sleep 2
fi

echo ""
echo "Starting RF Tactical Monitor..."
echo ""

# Cleanup function
cleanup() {
    echo ""
    if [ -n "$DUMP1090_PID" ]; then
        echo "Stopping dump1090 (PID: $DUMP1090_PID)..."
        kill "$DUMP1090_PID" 2>/dev/null || true
        wait "$DUMP1090_PID" 2>/dev/null || true
    fi
    echo "RF Tactical Monitor closed."
}

trap cleanup EXIT

# Launch the main application
# Use DISPLAY=:0 for kiosk mode on framebuffer
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"
python3 main.py "$@"
