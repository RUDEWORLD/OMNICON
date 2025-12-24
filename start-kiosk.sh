#!/bin/bash
# Omnicon Kiosk Mode Launcher
# Waits for web GUI to be ready, then launches Chromium in kiosk mode

# Wait for the web GUI to be available (max 60 seconds)
echo "Waiting for Omnicon Web GUI to start..."
for i in {1..60}; do
    if curl -s -o /dev/null -w "%{http_code}" http://localhost:8080 | grep -q "200"; then
        echo "Web GUI is ready!"
        break
    fi
    sleep 1
done

sleep 2

# Kill any existing Chromium instances
pkill -f chromium 2>/dev/null
sleep 1

# Launch Chromium in background, then send F11 to make it fullscreen
chromium-browser \
    --new-window \
    --noerrdialogs \
    --disable-infobars \
    --no-first-run \
    --check-for-update-interval=31536000 \
    --disable-session-crashed-bubble \
    --disable-features=TranslateUI \
    --password-store=basic \
    --disable-extensions \
    http://localhost:8080 &

# Wait for window to open, then press F11 for fullscreen
sleep 3
wtype -k F11 2>/dev/null || xdotool key F11 2>/dev/null

wait
