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

# Small delay to ensure everything is fully loaded
sleep 2

# Kill any existing Chromium instances to ensure kiosk mode works
pkill -f chromium 2>/dev/null
sleep 1

# Set display for Wayland
export WAYLAND_DISPLAY=wayland-1
export XDG_SESSION_TYPE=wayland

# Disable screen blanking/power saving (X11 fallback)
xset s off 2>/dev/null
xset -dpms 2>/dev/null
xset s noblank 2>/dev/null

# Launch Chromium in kiosk mode
# --kiosk: Full screen, no browser UI
# --noerrdialogs: Suppress error dialogs
# --disable-infobars: Hide info bars
# --no-first-run: Skip first run wizard
# --check-for-update-interval=31536000: Disable update checks (1 year)
# --disable-session-crashed-bubble: Don't show crash recovery
# --disable-features=TranslateUI: Disable translate popups
# --password-store=basic: Disable keyring integration (prevents password popup)
# --disable-extensions: Disable all extensions (prevents extension popups)

exec chromium-browser \
    --kiosk \
    --noerrdialogs \
    --disable-infobars \
    --no-first-run \
    --check-for-update-interval=31536000 \
    --disable-session-crashed-bubble \
    --disable-features=TranslateUI \
    --password-store=basic \
    --disable-extensions \
    --start-fullscreen \
    --window-position=0,0 \
    --ozone-platform=wayland \
    http://localhost:8080
