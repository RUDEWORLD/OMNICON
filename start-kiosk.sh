#!/bin/bash
# Omnicon Kiosk Mode Launcher
# Waits for web GUI to be ready, then launches Chromium in kiosk mode

# Source user environment if available
if [ -f "$HOME/.profile" ]; then
    . "$HOME/.profile"
fi

# Wait for the web GUI to be available (max 60 seconds)
echo "Waiting for Omnicon Web GUI to start..."
for i in {1..60}; do
    if curl -s -o /dev/null -w "%{http_code}" http://localhost:8080 | grep -q "200"; then
        echo "Web GUI is ready!"
        break
    fi
    sleep 1
done

# Small delay to ensure everything is fully loaded
sleep 2

# Kill any existing Chromium instances to ensure kiosk mode works
pkill -f chromium 2>/dev/null
sleep 1

# Disable screen blanking/power saving
xset s off 2>/dev/null
xset -dpms 2>/dev/null
xset s noblank 2>/dev/null

# Launch Chromium in app mode (kiosk-like but compatible with Wayland)
exec chromium-browser \
    --app=http://localhost:8080 \
    --start-maximized \
    --window-size=2048,1080 \
    --window-position=0,0 \
    --noerrdialogs \
    --disable-infobars \
    --no-first-run \
    --check-for-update-interval=31536000 \
    --disable-session-crashed-bubble \
    --disable-features=TranslateUI \
    --password-store=basic \
    --disable-extensions \
    --force-app-mode
