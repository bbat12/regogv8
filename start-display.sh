#!/usr/bin/env bash
# start-display.sh — boot the Xvfb + x11vnc + noVNC stack for the LoopNet auth popup.
# Usage: ./start-display.sh

set -u

# 1. Install required packages (idempotent)
if ! command -v x11vnc >/dev/null 2>&1 \
   || ! command -v websockify >/dev/null 2>&1 \
   || [ ! -d /usr/share/novnc ]; then
  echo "[1/7] Installing x11vnc, novnc, websockify..."
  sudo apt-get install -y x11vnc novnc websockify
else
  echo "[1/7] x11vnc, novnc, websockify already installed"
fi

# 2. Kill any existing instances
echo "[2/7] Killing existing Xvfb :99, x11vnc, websockify processes..."
pkill -f 'Xvfb :99' 2>/dev/null || true
pkill -f 'x11vnc'    2>/dev/null || true
pkill -f 'websockify' 2>/dev/null || true
sleep 1

# 3. Start Xvfb on :99
echo "[3/7] Starting Xvfb :99..."
nohup Xvfb :99 -screen 0 1024x768x24 > /tmp/xvfb.log 2>&1 &

# 4. Start x11vnc
echo "[4/7] Starting x11vnc on display :99..."
nohup x11vnc -display :99 -forever -nopw -quiet > /tmp/x11vnc.log 2>&1 &

# 5. Start websockify (noVNC web bridge)
echo "[5/7] Starting websockify on 6080..."
nohup websockify --web /usr/share/novnc 6080 localhost:5900 > /tmp/novnc.log 2>&1 &

# 6. Verify
echo "[6/7] Verifying (sleeping 2s first)..."
sleep 2
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://localhost:6080/vnc.html)
echo "        curl returned: $HTTP_CODE"

# 7. Report
if [ "$HTTP_CODE" = "200" ]; then
  echo "[7/7] Display stack ready"
  echo ""
  echo "  Open in browser: http://localhost:6080/vnc.html"
  echo "  (or your codespace-forwarded URL on port 6080)"
  echo ""
  echo "  Then in another terminal:"
  echo "    DISPLAY=:99 python -m regog.scrapers.loopnet_auth login 300"
else
  echo "[7/7] FAILED - check logs"
  echo "  tail /tmp/xvfb.log"
  echo "  tail /tmp/x11vnc.log"
  echo "  tail /tmp/novnc.log"
fi
