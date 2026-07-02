# CREATED BY PHILLIP RUDE
# FOR OMNICON DUO PI, MONO PI, & HUB
# V4.2.074
# 12/24/2024
# -*- coding: utf-8 -*-
# NOT FOR DISTRIBUTION OR USE OUTSIDE OF OMNICON PRODUCTS

import time
import board
import busio
import digitalio
from PIL import Image, ImageDraw, ImageFont
import adafruit_ssd1306
import subprocess
import json
import logging
from gpiozero import Button
import lgpio
import threading
from datetime import datetime
import os
import sys
import locale
import psutil  # Added for accurate CPU usage
import requests
import re
import socket
import zipfile
import shutil

# Set up logging
# INFO level: DEBUG floods the journal with ~3 lines/sec of OLED refresh noise,
# which is constant SD card write load (a freeze suspect) and buries real errors.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

# ============================================================================
# FULLSCREEN KIOSK GUI
# ============================================================================
KIOSK_PASSWORD = "3113"
KIOSK_ENABLED = True

def run_kiosk_gui():
    """Simple fullscreen GTK window with WebView inside."""
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('WebKit2', '4.1')
    from gi.repository import Gtk, WebKit2

    # Get port from config
    port = 8080
    try:
        with open('/home/omnicon/OLED_Stats/web_config.json', 'r') as f:
            port = json.load(f).get('port', 8080)
    except Exception:
        pass

    # Create fullscreen window
    window = Gtk.Window(title="Omnicon")
    window.set_decorated(False)
    window.fullscreen()
    window.connect('delete-event', lambda w, e: True)  # Block close

    # Overlay for webview + close button
    overlay = Gtk.Overlay()
    window.add(overlay)

    # WebView with hardware acceleration disabled
    webview = WebKit2.WebView()
    settings = webview.get_settings()
    settings.set_property('hardware-acceleration-policy', WebKit2.HardwareAccelerationPolicy.NEVER)
    webview.load_uri(f'http://127.0.0.1:{port}')
    overlay.add(webview)

    # Close button - small red circle
    btn = Gtk.Button(label="✕")
    btn.set_size_request(24, 24)
    btn.set_halign(Gtk.Align.END)
    btn.set_valign(Gtk.Align.START)
    btn.set_margin_top(8)
    btn.set_margin_end(8)

    # Style it red and round
    css = Gtk.CssProvider()
    css.load_from_data(b'''
        button {
            background: #cc0000;
            border-radius: 12px;
            border: none;
            color: white;
            font-size: 12px;
            padding: 0;
            min-width: 24px;
            min-height: 24px;
        }
        button:hover {
            background: #ff0000;
        }
    ''')
    btn.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    overlay.add_overlay(btn)

    def on_close_clicked(button):
        dialog = Gtk.MessageDialog(
            parent=window,
            flags=Gtk.DialogFlags.MODAL,
            type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            message_format="Enter password to minimize:"
        )
        entry = Gtk.Entry()
        entry.set_visibility(False)
        dialog.get_content_area().pack_end(entry, False, False, 0)
        dialog.show_all()

        if dialog.run() == Gtk.ResponseType.OK and entry.get_text() == KIOSK_PASSWORD:
            dialog.destroy()
            restore_keybindings()  # Restore shortcuts
            Gtk.main_quit()  # Exit the GTK loop and close kiosk
            return
        dialog.destroy()

    btn.connect('clicked', on_close_clicked)

    window.show_all()
    Gtk.main()

def setup_kiosk_keybindings():
    """Disable wayfire keyboard shortcuts for kiosk mode."""
    config_file = '/home/omnicon/.config/wayfire.ini'
    backup_file = '/home/omnicon/.config/wayfire.ini.backup'

    try:
        # Backup original config if not already backed up
        if os.path.exists(config_file) and not os.path.exists(backup_file):
            shutil.copy(config_file, backup_file)
            logging.info("Backed up original wayfire config")

        # Read current config and comment out dangerous keybindings
        if os.path.exists(backup_file):
            with open(backup_file, 'r') as f:
                content = f.read()
        else:
            with open(config_file, 'r') as f:
                content = f.read()

        # Comment out terminal, menu, and other shortcuts
        lines = content.split('\n')
        new_lines = []
        for line in lines:
            # Disable these bindings by commenting them out
            if any(x in line for x in ['binding_terminal', 'command_terminal',
                                        'binding_menu', 'command_menu',
                                        'binding_quit', 'command_quit',
                                        'binding_netman', 'command_netman',
                                        'binding_bluetooth', 'command_bluetooth']):
                if not line.strip().startswith('#'):
                    new_lines.append('# KIOSK_DISABLED: ' + line)
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)

        # Add section to disable switcher (Alt+Tab) and other escapes
        new_lines.append('')
        new_lines.append('# KIOSK MODE - disable window switching and escapes')
        new_lines.append('[switcher]')
        new_lines.append('next_view = none')
        new_lines.append('prev_view = none')
        new_lines.append('[fast-switcher]')
        new_lines.append('activate = none')
        new_lines.append('activate_backward = none')
        new_lines.append('[expo]')
        new_lines.append('toggle = none')
        new_lines.append('[vswitch]')
        new_lines.append('binding_left = none')
        new_lines.append('binding_right = none')
        new_lines.append('binding_up = none')
        new_lines.append('binding_down = none')

        # Force HDMI to 1920x1080 and mirror displays
        new_lines.append('')
        new_lines.append('# KIOSK MODE - force 1080p on HDMI')
        new_lines.append('[output:HDMI-A-1]')
        new_lines.append('mode = 1920x1080@60')
        new_lines.append('[output:HDMI-A-2]')
        new_lines.append('mode = 1920x1080@60')

        with open(config_file, 'w') as f:
            f.write('\n'.join(new_lines))

        # Wayfire needs IPC to reload - try dbus or write to socket
        subprocess.run(['pkill', '-HUP', 'wayfire'], capture_output=True)
        # Also try wf-msg if available
        subprocess.run(['wf-msg', 'reload'], capture_output=True)
        logging.info("Kiosk keybindings applied (wayfire)")
    except Exception as e:
        logging.error(f"Failed to setup kiosk keybindings: {e}")

def restore_keybindings():
    """Restore original wayfire config when kiosk is minimized."""
    config_file = '/home/omnicon/.config/wayfire.ini'
    backup_file = '/home/omnicon/.config/wayfire.ini.backup'
    try:
        if os.path.exists(backup_file):
            shutil.copy(backup_file, config_file)
            subprocess.run(['pkill', '-HUP', 'wayfire'], capture_output=True)
            logging.info("Restored original wayfire keybindings")
    except Exception as e:
        logging.error(f"Failed to restore keybindings: {e}")

def ensure_autologin():
    """Ensure desktop autologin and 1080p resolution for kiosk mode."""
    try:
        result = subprocess.run(['raspi-config', 'nonint', 'get_autologin'],
                                capture_output=True, text=True)
        if result.stdout.strip() != '0':
            # Autologin not enabled, enable it (B4 = desktop autologin)
            subprocess.run(['sudo', 'raspi-config', 'nonint', 'do_boot_behaviour', 'B4'],
                          capture_output=True)
            logging.info("Enabled desktop autologin for kiosk mode")
    except Exception as e:
        logging.error(f"Failed to check/set autologin: {e}")

def start_kiosk():
    """Start kiosk if display available."""
    if not KIOSK_ENABLED:
        return None

    # Ensure autologin is enabled
    ensure_autologin()

    # Wait for display to be available (up to 60 seconds)
    import pwd
    uid = pwd.getpwnam('omnicon').pw_uid
    runtime_dir = f"/run/user/{uid}"

    for attempt in range(60):
        if os.environ.get('WAYLAND_DISPLAY') or os.environ.get('DISPLAY'):
            break
        try:
            if os.path.exists(runtime_dir):
                for item in os.listdir(runtime_dir):
                    if item.startswith('wayland-') and not item.endswith('.lock'):
                        os.environ['WAYLAND_DISPLAY'] = item
                        os.environ['XDG_RUNTIME_DIR'] = runtime_dir
                        logging.info(f"Found display {item} after {attempt}s")
                        break
        except Exception:
            pass

        if os.environ.get('WAYLAND_DISPLAY') or os.environ.get('DISPLAY'):
            break
        time.sleep(1)

    if not (os.environ.get('WAYLAND_DISPLAY') or os.environ.get('DISPLAY')):
        logging.info("No display available after 60s - skipping kiosk")
        return None

    # Disable compositor shortcuts
    setup_kiosk_keybindings()

    # Auto-install webkit if needed
    try:
        import gi
        gi.require_version('WebKit2', '4.1')
    except Exception:
        subprocess.run(['sudo', 'apt-get', 'install', '-y', 'gir1.2-webkit2-4.1'],
                      capture_output=True, timeout=120)

    # Start in separate process
    import multiprocessing
    p = multiprocessing.Process(target=run_kiosk_gui, daemon=True)
    p.start()
    logging.info(f"Kiosk started (PID: {p.pid})")
    # Reap the kiosk when it exits: join() collects the child, so a closed or
    # crashed kiosk doesn't linger as a <defunct> zombie process.
    threading.Thread(target=p.join, daemon=True).start()
    return p

# ============================================================================

# Helper function to get system time with fresh timezone
def get_system_time():
    """Get the current system time, forcing a fresh read of timezone info.
    tzset() with TZ unset makes datetime.now() read /etc/localtime fresh, so
    timezone changes show up immediately - same answer the old `date`
    subprocess gave, without forking a process every second."""
    try:
        if 'TZ' in os.environ:
            del os.environ['TZ']
        time.tzset()
    except Exception as e:
        logging.warning(f"Failed to reload timezone: {e}")
    from datetime import datetime as dt
    return dt.now()

# GPIO setup
BUTTON_K1 = 26  # Using GPIO pin 26
BUTTON_K2 = 19  # Using GPIO pin 19
BUTTON_K3 = 13  # Using GPIO pin 13
BUTTON_K4 = 6   # Using GPIO pin 6

# Release GPIO pins
def release_gpio_pins(pins):
    h = lgpio.gpiochip_open(0)
    for pin in pins:
        try:
            lgpio.gpio_claim_input(h, pin)
        except lgpio.error as e:
            logging.warning(f"GPIO pin {pin} could not be claimed: {e}")
    lgpio.gpiochip_close(h)

# Release the GPIO pins
release_gpio_pins([BUTTON_K1, BUTTON_K2, BUTTON_K3, BUTTON_K4])

# Initialize buttons
try:
    button_k1 = Button(BUTTON_K1, pull_up=True, hold_time=0.3, bounce_time=0.1, hold_repeat=True)
    button_k2 = Button(BUTTON_K2, pull_up=True, hold_time=0.3, bounce_time=0.1, hold_repeat=True)
    button_k3 = Button(BUTTON_K3, pull_up=True, hold_time=1, bounce_time=0.1)
    button_k4 = Button(BUTTON_K4, pull_up=True, hold_time=1, bounce_time=0.1)
    logging.info('Buttons initialized successfully')
except lgpio.error as e:
    logging.error(f"Error initializing GPIO pins: {e}")
    exit(1)

# NetworkManager connection profiles
DHCP_PROFILE = "DHCP"
STATIC_PROFILE = "STATIC"

# Define terminal commands for services
command_start_companion = "sudo systemctl start companion.service"
command_stop_companion = "sudo systemctl stop companion.service"
command_start_satellite = "sudo systemctl start satellite.service"
command_stop_satellite = "sudo systemctl stop satellite.service"

# RETRIEVE COMPANION & SATELLITE VERSION
def get_companion_version():
    try:
        with open('/opt/companion/package.json', 'r') as f:
            data = json.load(f)
            version = data.get('version', 'Unknown')
            # Extract only the first three numbers
            match = re.match(r'^(\d+\.\d+\.\d+)', version)
            if match:
                return match.group(1)
            else:
                return 'Unknown'
    except Exception as e:
        logging.error(f"Error reading companion version: {e}")
        return 'Unknown'

def get_satellite_version():
    try:
        with open('/opt/companion-satellite/satellite/package.json', 'r') as f:
            data = json.load(f)
            version = data.get('version', 'Unknown')
            # Extract only the first three numbers
            match = re.match(r'^(\d+\.\d+\.\d+)', version)
            if match:
                return match.group(1)
            else:
                return 'Unknown'
    except Exception as e:
        logging.error(f"Error reading satellite version: {e}")
        return 'Unknown'

# State file
STATE_FILE = "state.json"

# Global variables
time_format_24hr = True  # True for 24-hour format, False for 12-hour format
available_versions = []  # To store fetched versions
selected_version = None  # Initialize selected_version at the global level
updating_application = False
oled_lock = threading.Lock()

# Companion/Satellite version picker globals
app_version_list = []  # List of version strings fetched from Bitfocus API
app_version_scroll = 0  # Current scroll position in the version list
app_version_cursor = 0  # Cursor position (0-2, which of the 3 visible items is selected)
app_version_target = ""  # "companion" or "satellite"

# Function to get current version from the script
def get_current_version():
    script_path = sys.argv[0]  # Get the current script path
    try:
        with open(script_path, 'r') as file:
            for line in file:
                if line.startswith("# V"):
                    return line.strip().split(' ')[1]
    except Exception as e:
        logging.error(f"Error reading script for version: {e}")
    return "Unknown"

# Update the update_menu dynamically
current_version = get_current_version()
update_menu = [f"CURRENT: {current_version}", "UPDATE", "DOWNGRADE", "EXIT"]

# Function to load state from file
def load_state():
    def parse_ip_octets(ip):
        if isinstance(ip, list):
            return [int(octet) for octet in ip]
        return [int(octet) for octet in ip.split('.') if octet.isdigit()]

    try:
        with open(STATE_FILE, 'r') as f:
            state = json.load(f)
            state["static_ip"] = parse_ip_octets(state.get("static_ip", "192.168.0.100"))
            state["subnet_mask"] = parse_ip_octets(state.get("subnet_mask", "255.255.255.0"))
            state["gateway"] = parse_ip_octets(state.get("gateway", "192.168.0.1"))
            state["time_format_24hr"] = state.get("time_format_24hr", True)
            return state
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "service": "companion",
            "network": "STATIC",
            "static_ip": [192, 168, 0, 100],
            "subnet_mask": [255, 255, 255, 0],
            "gateway": [192, 168, 0, 1],
            "time_format_24hr": True
        }

def is_connected():
    # Try multiple methods to detect internet connectivity
    # Method 1: HTTP HEAD request to GitHub (what we actually need to reach)
    try:
        import urllib.request
        req = urllib.request.Request("https://api.github.com", method="HEAD")
        urllib.request.urlopen(req, timeout=5)
        return True
    except Exception:
        pass
    # Method 2: Try connecting to common HTTPS port
    try:
        socket.create_connection(("github.com", 443), timeout=3)
        return True
    except OSError:
        pass
    # Method 3: Original DNS check as fallback
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=2)
        return True
    except OSError:
        pass
    return False


def fetch_bitfocus_versions(product):
    """Fetch available stable versions from Bitfocus API for companion or satellite.
    product: 'companion' or 'companion-satellite'
    Returns list of version strings like ['v2.8.0', 'v2.7.0', ...]"""
    try:
        import urllib.request
        target = "linux-arm64-tgz"
        url = f"https://api.bitfocus.io/v1/product/{product}/packages?branch=stable&limit=10&target={target}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        versions = []
        for pkg in data.get('packages', []):
            if pkg.get('target') == target:
                versions.append(pkg['version'])
        return versions
    except Exception as e:
        logging.error(f"Error fetching Bitfocus versions for {product}: {e}")
        return []


# Function to save state to file
def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

# Function to execute a command
def execute_command(command):
    subprocess.run(command, shell=True)

# Function to setup port 80 to 8080 redirect using nftables
def setup_port_redirect():
    """Configure nftables to redirect port 80 to 8080 for web GUI access without port number"""
    nftables_conf = "/etc/nftables.conf"
    nftables_content = """#!/usr/sbin/nft -f

flush ruleset

table ip nat {
\tchain prerouting {
\t\ttype nat hook prerouting priority dstnat; policy accept;
\t\ttcp dport 80 redirect to :8080
\t}
}
"""
    try:
        # Check if nftables.conf already has the correct content
        needs_update = True
        try:
            with open(nftables_conf, 'r') as f:
                current_content = f.read()
                if 'tcp dport 80 redirect to :8080' in current_content and 'flush ruleset' in current_content:
                    needs_update = False
                    logging.debug("Port 80 redirect already configured")
        except FileNotFoundError:
            pass

        if needs_update:
            logging.info("Setting up port 80 to 8080 redirect...")
            # Write the nftables config
            result = subprocess.run(
                ['sudo', 'tee', nftables_conf],
                input=nftables_content,
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                logging.error(f"Failed to write nftables config: {result.stderr}")
                return

            # Enable and restart nftables service
            subprocess.run(['sudo', 'systemctl', 'enable', 'nftables'], capture_output=True)
            subprocess.run(['sudo', 'systemctl', 'restart', 'nftables'], capture_output=True)
            logging.info("Port 80 redirect configured successfully")
        else:
            # Ensure nftables service is running even if config exists
            subprocess.run(['sudo', 'systemctl', 'start', 'nftables'], capture_output=True)
    except Exception as e:
        logging.error(f"Failed to setup port redirect: {e}")

# Function to check if a service is active
def is_service_active(service_name):
    try:
        result = subprocess.run(["systemctl", "is-active", service_name],
                                capture_output=True, text=True, timeout=5)
        return result.stdout.strip() == "active"
    except Exception:
        return False  # timeout/hang counts as not-active rather than freezing the caller

# Function to get active network connection
def get_active_connection():
    try:
        result = subprocess.run(["nmcli", "-t", "-f", "ACTIVE,NAME", "connection", "show", "--active"],
                                capture_output=True, text=True, timeout=5)
        for line in result.stdout.splitlines():
            active, name = line.split(':', 1)  # maxsplit: profile names may contain ':'
            if active == "yes":
                return name
    except Exception as e:
        logging.error(f"get_active_connection failed: {e}")
    return None

# DEFINE COMP & SAT VERSION FOR MENU
companion_version = get_companion_version()
satellite_version = get_satellite_version()
application_menu = [f"Companion {companion_version}", f"Satellite {satellite_version}", "UPDATE APPS", "EXIT"]

# Function to switch network profile
def switch_network_profile(new_profile):
    active_profile = get_active_connection()
    if active_profile != new_profile:
        if active_profile:
            subprocess.run(["sudo", "nmcli", "connection", "down", active_profile])
        subprocess.run(["sudo", "nmcli", "connection", "up", new_profile], capture_output=True, text=True)
        subprocess.run(["sudo", "nmcli", "device", "reapply"], capture_output=True, text=True)
        active_profile = get_active_connection()
        if active_profile == new_profile:
            logging.info(f"Successfully switched to {new_profile} profile")
        else:
            logging.info(f"Failed to switch to {new_profile} profile")

def initial_setup():
    # Setup port 80 redirect for web GUI access without port number
    setup_port_redirect()

    state = load_state()

    # Ensure only one service is active at startup
    if state["service"] == "companion":
        logging.info('Setting initial state: Companion service.')
        execute_command(command_start_companion)
        execute_command(command_stop_satellite)
    else:
        logging.info('Setting initial state: Satellite service.')
        execute_command(command_start_satellite)
        execute_command(command_stop_companion)

    # Ensure the correct network profile is active
    current_network = get_active_connection()
    if state["network"] == "DHCP" and current_network != DHCP_PROFILE:
        switch_network_profile(DHCP_PROFILE)
    elif state["network"] == "STATIC" and current_network != STATIC_PROFILE:
        switch_network_profile(STATIC_PROFILE)

def enforce_single_app_service():
    """HARD INVARIANT: Companion and Satellite must NEVER run simultaneously.

    The Bitfocus update wrappers unconditionally (re)start the app they just
    updated - companion-update literally ends with `systemctl start companion`
    even when this unit is in Satellite mode. The old post-update reboot
    accidentally masked that (boot re-asserts the mode from state.json); with
    the reboot gone this guard does it explicitly: if BOTH are active, stop
    the one state.json does not name. Stop-only by design - starting the
    intended app is the job of startup/toggle, so this can never fight
    systemd over a crash-looping service."""
    try:
        mode = load_state().get('service', 'companion')
        other = 'satellite' if mode == 'companion' else 'companion'
        if is_service_active(f"{other}.service") and is_service_active(f"{mode}.service"):
            logging.warning(f"INVARIANT: both app services active (mode={mode}) - stopping {other}")
            subprocess.run(['sudo', 'systemctl', 'stop', other],
                           capture_output=True, timeout=60)
            invalidate_stats_cache()  # OLED reflects the correction immediately
    except Exception as e:
        logging.error(f"enforce_single_app_service failed: {e}")


def toggle_service(service=None):
    state = load_state()
    if service:
        state["service"] = service
    # Save the chosen mode FIRST (declare intent before acting): if the
    # single-app guard fires mid-toggle it then pushes toward the SAME target
    # instead of racing us back to the old mode.
    save_state(state)
    if state["service"] == "companion":
        logging.info('Toggling to Companion service.')
        if is_service_active("satellite.service"):
            execute_command(command_stop_satellite)
        execute_command(command_start_companion)
    else:
        logging.info('Toggling to Satellite service.')
        # Pre-switch guard: never start Satellite without its runtime. If a
        # Companion update deleted /opt/fnm, rebuild it first (shows the OLED
        # self-heal splash) so the switch can't land on a 203/EXEC "SYSTEM OFF".
        if not fnm_healthy():
            ensure_fnm(reason="switch-to-satellite")
        if is_service_active("companion.service"):
            execute_command(command_stop_companion)
        execute_command(command_start_satellite)
    invalidate_stats_cache()  # OLED title reflects the new service immediately

def toggle_network(network=None):
    state = load_state()
    if network:
        state["network"] = network
    if state["network"] == "DHCP":
        logging.info('Toggling to DHCP profile.')
        switch_network_profile(DHCP_PROFILE)
        state["network"] = "DHCP"
    else:
        logging.info('Toggling to Static profile.')
        switch_network_profile(STATIC_PROFILE)
        state["network"] = "STATIC"
    save_state(state)
    invalidate_stats_cache()  # OLED profile name reflects the change immediately

# Define the Reset Pin
oled_reset = digitalio.DigitalInOut(board.D4)

# Display Parameters
WIDTH = 128
HEIGHT = 64
BORDER = 5

# Display Refresh
LOOPTIME = 0.5  # Refresh rate reduced to 0.5 seconds

# Use for I2C.
i2c = board.I2C()
oled = adafruit_ssd1306.SSD1306_I2C(WIDTH, HEIGHT, i2c, addr=0x3C, reset=oled_reset)

# Clear display.
oled.fill(0)
oled.show()

# Create blank image for drawing.
image = Image.new("1", (oled.width, oled.height))

# Get drawing object to draw on image.
draw = ImageDraw.Draw(image)

# Draw a white background
draw.rectangle((0, 0, oled.width, oled.height), outline=255, fill=255)

# Load fonts
font7 = ImageFont.truetype('DejaVuSans.ttf', 7)
font9 = ImageFont.truetype('DejaVuSans.ttf', 9)
font10 = ImageFont.truetype('DejaVuSans.ttf', 10)
font11 = ImageFont.truetype('DejaVuSans.ttf', 11)
font12 = ImageFont.truetype('DejaVuSans.ttf', 12)
font13 = ImageFont.truetype('DejaVuSans.ttf', 13)
font14 = ImageFont.truetype('DejaVuSans.ttf', 14)
font15 = ImageFont.truetype('DejaVuSans.ttf', 15)

# Global variables for menu navigation
menu_state = "default"
menu_selection = 0
ip_octet = 0

state = load_state()
ip_address = state["static_ip"]
subnet_mask = state["subnet_mask"]
gateway = state["gateway"]

original_ip_address = ip_address[:]
original_subnet_mask = subnet_mask[:]
original_gateway = gateway[:]

blink_state = True
last_interaction_time = time.monotonic()  # Use monotonic for timeout tracking (immune to time changes)
timeout_flag = False
update_flag = True
debounce_time = 0.05  # Debounce time for button presses
last_update_time = time.monotonic()  # Initialize the last update time (monotonic to handle time changes)

# Global flag to indicate message display
message_displayed = False

# Menu options
main_menu = ["APPLICATION", "CONFIGURATION", "POWER", "EXIT"]
application_menu = ["RUN COMPANION", "RUN SATELLITE", "UPDATE APPS", "EXIT"]
app_updates_menu = ["UPDATE APP", "COMPANION", "SATELLITE", "EXIT"]
app_update_companion_menu = ["UPDATE COMPANION", "LATEST STABLE", "SPECIFIC STABLE", "CANCEL"]
app_update_satellite_menu = ["UPDATE SATELLITE", "LATEST STABLE", "SPECIFIC STABLE", "CANCEL"]
configuration_menu = ["NETWORK", "SET DATE/TIME", "UPDATE", "EXIT"]
network_menu = ["DHCP", "STATIC IP", "SET STATIC", "EXIT"]
power_menu = ["REBOOT", "SHUTDOWN", "", "EXIT"]
reboot_confirm_menu = ["CANCEL", "REBOOT"]
shutdown_confirm_menu = ["CANCEL", "SHUTDOWN"]
set_static_menu = ["IP ADDRESS", "SUBNET MASK", "GATEWAY", "EXIT"]
set_datetime_menu = ["CURRENT DATE/TIME", "SET DATE", "SET TIME", "EXIT"]
menu_options = {
    "default": main_menu,
    "main": main_menu,
    "application": application_menu,
    "app_updates": app_updates_menu,
    "app_update_companion": app_update_companion_menu,
    "app_update_satellite": app_update_satellite_menu,
    "configuration": configuration_menu,
    "network": network_menu,
    "power": power_menu,
    "set_static": set_static_menu,
    "reboot_confirm": reboot_confirm_menu,
    "shutdown_confirm": shutdown_confirm_menu,
    "set_static_ip": set_static_menu,
    "set_static_sm": set_static_menu,
    "set_static_gw": set_static_menu,
    "set_datetime": set_datetime_menu,
    "update": update_menu,
    "update_confirm": [],
    "downgrade_confirm": [],
    "set_date": [],
    "set_time": [],
    "upgrade_select": [],
    "downgrade_select": [],
    "update_companion": ["UPDATE COMPANION", "LATEST STABLE", "SPECIFIC STABLE", "CANCEL"],
    "update_satellite": ["UPDATE SATELLITE", "LATEST STABLE", "SPECIFIC STABLE", "CANCEL"],
    "pick_companion_version": [],
    "pick_satellite_version": [],

}

# Button indicators
indicators = {
    "K1": "▲",
    "K2": "▼",
    "K3": "◀",
    "K4": "▶"
}

# Function to get current network settings
def get_current_network_settings():
    """Info for the NETWORK INFO screen. Each value is independently
    timeout-guarded with an N/A fallback: this runs on the render path, and the
    old version had no timeouts (a hung nmcli froze the OLED) and crashed with
    no network (hostname -I returns nothing -> [0] IndexError; subnet 'N/A' ->
    int() ValueError in cidr_to_subnet_mask)."""
    try:
        out = subprocess.check_output(["hostname", "-I"], timeout=5).decode('utf-8').strip().split()
        ip = out[0] if out else "N/A"
    except Exception:
        ip = "N/A"
    try:
        subnet_out = subprocess.check_output(["ip", "-o", "-f", "inet", "addr", "show"], timeout=5).decode('utf-8')
        cidrs = [line.split()[3] for line in subnet_out.splitlines() if 'eth0' in line]
        subnet = cidr_to_subnet_mask(cidrs[0].split('/')[1]) if cidrs else "N/A"
    except Exception:
        subnet = "N/A"
    try:
        gw_out = subprocess.check_output(["ip", "route", "show", "default"], timeout=5).decode('utf-8').split()
        gateway = gw_out[2] if len(gw_out) > 2 else "N/A"
    except Exception:
        gateway = "N/A"
    try:
        dns_out = subprocess.check_output(["nmcli", "dev", "show"], timeout=5).decode('utf-8')
        dns_servers = [line.split(':')[-1].strip() for line in dns_out.splitlines() if 'IP4.DNS' in line]
        dns = dns_servers[0] if dns_servers else "N/A"
    except Exception:
        dns = "N/A"
    return ip, subnet, gateway, dns

def get_lan_network_info():
    """Get LAN (eth0) network information for display"""
    try:
        # Get network mode (DHCP or STATIC)
        mode = state.get("network", "DHCP")

        # Get IP address for eth0
        try:
            ip_output = subprocess.check_output(["ip", "-4", "addr", "show", "eth0"], text=True, timeout=5)
            ip = "N/A"
            subnet = "N/A"
            for line in ip_output.split('\n'):
                if 'inet ' in line:
                    parts = line.strip().split()
                    ip_with_cidr = parts[1]
                    ip = ip_with_cidr.split('/')[0]
                    cidr = ip_with_cidr.split('/')[1]
                    subnet = cidr_to_subnet_mask(cidr)
                    break
        except Exception:
            ip = "N/A"
            subnet = "N/A"

        # Get gateway
        try:
            gw_output = subprocess.check_output(["ip", "route", "show", "default"], text=True, timeout=5)
            gateway = gw_output.split()[2] if gw_output else "N/A"
        except Exception:
            gateway = "N/A"

        return mode, ip, subnet, gateway
    except Exception as e:
        logging.error(f"Error getting LAN info: {e}")
        return "N/A", "N/A", "N/A", "N/A"

def get_wifi_network_info():
    """Get WiFi (wlan0) network information for display"""
    try:
        # Check if WiFi is enabled and connected
        try:
            result = subprocess.run(
                ["nmcli", "-t", "-f", "DEVICE,STATE", "device"],
                capture_output=True, text=True, timeout=5
            )
            wifi_connected = False
            wifi_enabled = False
            for line in result.stdout.strip().split('\n'):
                if line.startswith('wlan0:'):
                    state_val = line.split(':')[1]
                    wifi_enabled = state_val not in ['unavailable', 'unmanaged']
                    wifi_connected = state_val == 'connected'
                    break
        except Exception:
            return None  # WiFi not available

        if not wifi_enabled:
            return None  # WiFi disabled

        if not wifi_connected:
            return "DISCONNECTED", None, None, None

        # Get SSID
        try:
            result = subprocess.run(
                ["nmcli", "-t", "-f", "ACTIVE,SSID", "device", "wifi", "list", "ifname", "wlan0"],
                capture_output=True, text=True, timeout=10
            )
            ssid = "Unknown"
            for line in result.stdout.strip().split('\n'):
                parts = line.split(':')
                if len(parts) >= 2 and parts[0] == 'yes':
                    ssid = parts[1]
                    break
        except Exception:
            ssid = "Unknown"

        # Get IP address for wlan0
        try:
            ip_output = subprocess.check_output(["ip", "-4", "addr", "show", "wlan0"], text=True, timeout=5)
            ip = "N/A"
            subnet = "N/A"
            for line in ip_output.split('\n'):
                if 'inet ' in line:
                    parts = line.strip().split()
                    ip_with_cidr = parts[1]
                    ip = ip_with_cidr.split('/')[0]
                    cidr = ip_with_cidr.split('/')[1]
                    subnet = cidr_to_subnet_mask(cidr)
                    break
        except Exception:
            ip = "N/A"
            subnet = "N/A"

        # Get gateway (might be different from LAN)
        try:
            gw_output = subprocess.check_output(["ip", "route", "show", "default", "dev", "wlan0"], text=True, timeout=5)
            gateway = gw_output.split()[2] if gw_output else "N/A"
        except Exception:
            gateway = "N/A"

        return ssid, ip, subnet, gateway
    except Exception as e:
        logging.error(f"Error getting WiFi info: {e}")
        return None

# ============================================================================
# UNIFIED UPDATE SCREEN
# One screen for the whole Companion/Satellite update:
#     UPDATING COMPANION
#     DO NOT UNPLUG
#     EXTRACTING            ~50s
#     [############............]
# The phase label is REAL (parsed from the updater's own output markers); the
# bar and time-remaining are ESTIMATES learned from this unit's previous
# updates (per app, per phase, in diagnostics/update_times.json, blended 50/50
# after each run). The first-ever update uses ballpark defaults and
# self-corrects from then on. The bar caps at 99% until the process actually
# exits, and the real wget % drives the bar within the DOWNLOADING slice.
# ============================================================================
UPDATE_PHASES = ['PREPARING', 'DOWNLOADING', 'EXTRACTING', 'FINISHING', 'FINALIZING']
_DEFAULT_PHASE_TIMES = {'PREPARING': 12.0, 'DOWNLOADING': 15.0,
                        'EXTRACTING': 35.0, 'FINISHING': 25.0,
                        'FINALIZING': 20.0}  # the fnm self-heal after companion updates


def _update_times_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'diagnostics', 'update_times.json')


def _load_update_times(app):
    """Learned per-phase durations for this app, defaults where unknown."""
    try:
        with open(_update_times_path()) as f:
            stored = json.load(f).get(app, {})
    except Exception:
        stored = {}
    return {p: float(stored.get(p, _DEFAULT_PHASE_TIMES[p])) for p in UPDATE_PHASES}


def _save_update_times(app, observed):
    """Blend this run's observed phase durations into the history (50/50)."""
    try:
        path = _update_times_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path) as f:
                data = json.load(f)
        except Exception:
            data = {}
        cur = data.get(app, {})
        for phase, secs in observed.items():
            old = float(cur.get(phase, _DEFAULT_PHASE_TIMES.get(phase, secs)))
            cur[phase] = round(0.5 * old + 0.5 * secs, 1)
        data[app] = cur
        with open(path, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        logging.error(f"_save_update_times failed: {e}")


def _fit_font(d, text, max_w=124):
    """Largest font (12 down to 9) that fits the OLED width for this text."""
    for f in (font12, font11, font10, font9):
        l, t, r, b = d.textbbox((0, 0), text, font=f)
        if r - l <= max_w:
            return f
    return font9


def update_oled_update_screen(title, phase, pct, eta_secs):
    """Render the unified update screen: title / DO NOT UNPLUG / phase + ETA /
    outlined progress bar."""
    with oled_lock:
        img = Image.new("1", (oled.width, oled.height))
        d = ImageDraw.Draw(img)

        def center(text, y):
            f = _fit_font(d, text)
            l, t, r, b = d.textbbox((0, 0), text, font=f)
            d.text(((oled.width - (r - l)) // 2, y), text, font=f, fill=255)

        center(title, 0)
        center("DO NOT UNPLUG", 15)
        d.text((4, 31), phase, font=font11, fill=255)
        if eta_secs is not None:
            if eta_secs >= 90:
                eta = f"~{round(eta_secs / 60.0)}m"
            else:
                secs = max(int(eta_secs), 1)
                eta = f"~{((secs + 4) // 5) * 5}s"  # round up to nearest 5s
            l, t, r, b = d.textbbox((0, 0), eta, font=font11)
            d.text((oled.width - (r - l) - 4, 31), eta, font=font11, fill=255)
        # Outlined gauge with fill so it reads as a bar even when nearly empty
        d.rectangle((10, 48, 118, 58), outline=255, fill=0)
        fill_w = int((min(pct, 99) / 100.0) * 106)
        if fill_w > 0:
            d.rectangle((11, 49, 11 + fill_w, 57), outline=255, fill=255)
        oled.image(img.rotate(180))
        oled.show()


def resolve_bitfocus_package(app_name, version):
    """Look up the exact tarball for a specific Companion/Satellite version on
    the Bitfocus API. Returns (uri, exact_name) or (None, None). Version match
    is v-prefix agnostic ('4.3.3' == 'v4.3.3')."""
    product = 'companion' if app_name == 'companion' else 'companion-satellite'
    want = str(version).lstrip('vV')
    try:
        import urllib.request
        url = (f"https://api.bitfocus.io/v1/product/{product}/packages"
               f"?branch=stable&limit=50&target=linux-arm64-tgz")
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        for pkg in data.get('packages', []):
            if (pkg.get('target') == 'linux-arm64-tgz'
                    and str(pkg.get('version', '')).lstrip('vV') == want):
                return pkg.get('uri'), pkg.get('version')
    except Exception as e:
        logging.error(f"resolve_bitfocus_package({app_name}, {version}) failed: {e}")
    return None, None


def build_versioned_update_command(app_name, version):
    """Update Companion/Satellite to a SPECIFIC version.

    Two upstream Bitfocus bugs make the naive `sudo companion-update stable X`
    silently install the LATEST instead of X:
      1. The wrappers forward only $1 to update.sh ('./update.sh $1'), so the
         version argument is dropped. We replicate the tiny wrapper inline and
         pass BOTH branch and version.
      2. The current CompanionPi picker fetches only the single NEWEST build in
         non-interactive mode, so any other requested version is "not found"
         and skipped. Countermeasure: resolve the exact tarball URI from the
         Bitfocus API ourselves and PRE-SEED the picker's selection file - the
         picker never deletes it (it only writes on success), and update.sh
         installs whatever selection exists after the picker runs.
    Plain ';' separators (not bash -e) so the service is started again even if
    a step fails, and seed files are cleaned up afterwards so a failed run
    can't leave a stale selection for a future manual update."""
    safe_ver = re.sub(r'[^0-9A-Za-z._-]', '', str(version))
    uri, exact_name = resolve_bitfocus_package(app_name, safe_ver)
    seed = cleanup = ''
    if uri and re.fullmatch(r'https://[0-9A-Za-z._~:/?#@!$&()*+,;=%-]+', uri):
        logging.info(f"{app_name} {safe_ver} resolved to {uri}")
        if app_name == 'companion':
            seed = f'printf %s "{uri}" > /tmp/companion-version-selection; '
            cleanup = 'rm -f /tmp/companion-version-selection; '
        else:
            seed = (f'printf %s "{uri}" > /tmp/satellite-version-selection; '
                    f'printf %s "{exact_name}" > /tmp/satellite-version-selection-name; ')
            cleanup = 'rm -f /tmp/satellite-version-selection /tmp/satellite-version-selection-name; '
    else:
        logging.warning(f"{app_name} {safe_ver}: no API match - relying on the picker alone")
    if app_name == 'companion':
        return ("sudo bash -c '" + seed +
                "systemctl stop companion; "
                "cd /usr/local/src/companionpi && git pull -q; "
                f"./update.sh stable {safe_ver}; " + cleanup +
                "systemctl start companion; echo Update is complete'")
    return ("sudo bash -c '" + seed +
            "systemctl stop satellite; "
            "cd /usr/local/src/companion-satellite && git pull -q; "
            f"./pi-image/update.sh stable {safe_ver}; " + cleanup +
            "systemctl start satellite; echo Update is complete'")


# FUNCTION TO UPDATE COMMAND WITH PROGRESS
def execute_command_with_progress(command):
    """Run a Companion/Satellite update with the unified update screen.

    Output is drained by a background thread at full speed (pipe backpressure
    once throttled a 3-second download into 5-10 minutes of OLED-paint-speed
    reads). The drain thread watches for the updater's own phase markers:
    "Installing from ..." -> DOWNLOADING, "Extracting..." -> EXTRACTING,
    "Finishing" -> FINISHING; everything before is PREPARING. wget percentages
    are only honored during DOWNLOADING so tools that print their own % (fnm,
    yarn) can't fake download progress.

    Owns the OLED for its whole duration: sets the updating_application global
    itself (gates update_oled_display) so no caller can ever forget it and put
    two painters on the screen at once."""
    global updating_application
    # satellite checked first: 'companion-satellite' contains 'companion'
    app = ('satellite' if ('satellite-update' in command or 'companion-satellite' in command)
           else 'companion' if ('companion-update' in command or 'companionpi' in command)
           else 'app')
    title = {'companion': 'UPDATING COMPANION',
             'satellite': 'UPDATING SATELLITE'}.get(app, 'UPDATING')
    times = _load_update_times(app)
    updating_application = True
    try:
        process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True)
        state = {'done': False, 'phase': 'PREPARING', 'dl_pct': None}
        phase_started = {'PREPARING': time.monotonic()}
        observed = {}

        def set_phase(new):
            old = state['phase']
            if UPDATE_PHASES.index(new) <= UPDATE_PHASES.index(old):
                return  # phases only ever move forward
            now = time.monotonic()
            observed[old] = now - phase_started[old]
            phase_started[new] = now
            state['phase'] = new

        def drain():
            try:
                for line in iter(process.stdout.readline, ''):
                    if line == '':
                        break
                    low = line.strip().lower()
                    # Journal the updater's key decision lines (selected what?
                    # skipped why?) - invaluable when a user reports "it said
                    # complete but nothing changed". Bounded: a handful per run.
                    if any(m in low for m in ('selected', 'no matching', 'no version',
                                              'already installed', 'skipping',
                                              'installing from', 'error')):
                        logging.info(f"updater: {line.strip()}")
                    if low.startswith('installing from'):
                        set_phase('DOWNLOADING')
                    elif low.startswith('extracting'):
                        set_phase('EXTRACTING')
                    elif low.startswith('finishing'):
                        set_phase('FINISHING')
                    if state['phase'] == 'DOWNLOADING':
                        p = parse_progress(line)
                        if p is not None:
                            state['dl_pct'] = p
            finally:
                state['done'] = True

        threading.Thread(target=drain, daemon=True).start()

        total = sum(times.values())

        def render_now():
            ph = state['phase']
            idx = UPDATE_PHASES.index(ph)
            elapsed_in_phase = time.monotonic() - phase_started[ph]
            if ph == 'DOWNLOADING' and state['dl_pct'] is not None:
                frac = min(state['dl_pct'] / 100.0, 1.0)  # real download progress
            else:
                frac = min(elapsed_in_phase / max(times[ph], 1.0), 1.0)
            done_secs = sum(times[p] for p in UPDATE_PHASES[:idx])
            pct = (done_secs + frac * times[ph]) / total * 100.0
            eta = max(times[ph] * (1.0 - frac), 0.0) + sum(times[p] for p in UPDATE_PHASES[idx + 1:])
            update_oled_update_screen(title, ph, pct, eta)

        while not state['done']:
            render_now()
            time.sleep(0.5)

        process.stdout.close()
        process.wait()

        # FINALIZING: run the fnm self-heal as the last stage of the SAME
        # screen/bar (a companion update just deleted /opt/fnm; for satellite
        # it's a quick no-op). The heal draws nothing itself here - this loop
        # keeps rendering, and the phase's duration is learned like the others.
        set_phase('FINALIZING')
        heal = {'ok': True, 'done': False}

        def do_heal():
            try:
                heal['ok'] = ensure_fnm(reason="post-app-update", show_splash=False)
                # The wrapper just unconditionally started the app it updated,
                # even if this unit is in the OTHER mode - kill any dual-run.
                enforce_single_app_service()
            finally:
                heal['done'] = True

        threading.Thread(target=do_heal, daemon=True).start()
        while not heal['done']:
            render_now()
            time.sleep(0.5)

        # Record the final phase's duration, then learn from this run
        observed[state['phase']] = time.monotonic() - phase_started[state['phase']]
        if app != 'app':
            _save_update_times(app, observed)
        if not heal['ok']:
            show_message("UPDATE INCOMPLETE\nNEEDS INTERNET", 3)
    except Exception as e:
        logging.error(f"Error executing command with progress: {e}")
    finally:
        updating_application = False  # release the OLED no matter how we exit

# PARSE PROGRESS
def parse_progress(output_line):
    # Use regex to search for percentage
    match = re.search(r'(\d+)%', output_line)
    if match:
        progress = int(match.group(1))
        return progress
    else:
        return None

# UPDATE OLED FUNCTION
def update_oled_with_progress(progress):
    with oled_lock:
        # Create a new image to display
        local_image = Image.new("1", (oled.width, oled.height))
        local_draw = ImageDraw.Draw(local_image)

        # Display progress percentage
        local_draw.text((30, 0), f"UPDATING", font=font12, fill=255)
        local_draw.text((10, 16), f"DO NOT TURN OFF", font=font12, fill=255)
        local_draw.text((0, 32), f"Progress: {progress}%", font=font12, fill=255)

        # Draw a progress bar
        bar_width = int((progress / 100) * (oled.width - 20))
        local_draw.rectangle((10, 50, 10 + bar_width, 58), outline=255, fill=255)

        oled.image(local_image.rotate(180))
        oled.show()


def cidr_to_subnet_mask(cidr):
    cidr = int(cidr)
    mask = (0xffffffff >> (32 - cidr)) << (32 - cidr)
    return f'{(mask >> 24) & 0xff}.{(mask >> 16) & 0xff}.{(mask >> 8) & 0xff}.{mask & 0xff}'

_pi_health_last_voltage = "0.0000"

def get_pi_health():
    """Vitals for the PI HEALTH screen - same values/format as before, but safe
    for the per-second render path: cpu_percent(interval=None) is non-blocking
    (the old interval=1 froze the display thread for a full second per redraw),
    temp/memory read /sys and /proc directly, and the one remaining fork
    (vcgencmd for voltage, which has no /sys equivalent) has a timeout with a
    last-known-value fallback so a hang can't freeze the OLED."""
    global _pi_health_last_voltage
    try:
        with open('/sys/class/thermal/thermal_zone0/temp') as f:
            temp = f"{int(f.read().strip()) / 1000.0:.1f}'C"
    except Exception:
        temp = "N/A"
    try:
        v_out = subprocess.check_output(["vcgencmd", "measure_volts"], timeout=5).decode('utf-8')
        _pi_health_last_voltage = v_out.strip().split('=')[1].replace('V', '')
    except Exception:
        pass  # keep last known voltage
    voltage = _pi_health_last_voltage
    cpu_usage = psutil.cpu_percent(interval=None)  # avg since last call, no 1s block
    vm = psutil.virtual_memory()
    memory_used = vm.used / (1024 ** 3)
    memory_total = vm.total / (1024 ** 3)
    watt_input = float(voltage) * 0.85  # Assuming the current draw is approximately 0.85A
    return temp, voltage, watt_input, cpu_usage, f"{memory_used:.2f}/{memory_total:.2f}GB"

# Function to clear the OLED display before drawing new content
def clear_display():
    logging.debug("Clearing display")
    draw.rectangle((0, 0, oled.width, oled.height), outline=0, fill=0)

# Function to update OLED display
# ============================================================================
# FAST STATS - subprocess-free system stats for the OLED render path.
# The default screen redraws every second; it used to fork ~8 shell pipelines
# per redraw (top/free/df/hostname/vcgencmd/nmcli/systemctl) with no timeouts,
# all while holding oled_lock - so one hung nmcli could freeze the OLED and
# buttons forever. These read /proc and /sys directly; the two genuinely
# external facts (NetworkManager profile, service state) are cached briefly
# and refreshed with strict timeouts, keeping the last known value on failure.
# ============================================================================
_stats_cache = {'eth_profile': ('', 0.0), 'service': (None, 0.0)}


def get_display_ip():
    """First IPv4 address, preferring wired - same answer as `hostname -I | cut -d' ' -f1`."""
    try:
        if_addrs = psutil.net_if_addrs()
        ordered = ['eth0', 'wlan0'] + [i for i in if_addrs if i not in ('eth0', 'wlan0', 'lo')]
        for iface in ordered:
            for a in if_addrs.get(iface, []):
                if a.family == socket.AF_INET and not a.address.startswith('169.254'):
                    return a.address
    except Exception:
        pass
    return ""


def get_eth_profile(max_age=10):
    """Active NetworkManager profile name on the wired interface, cached."""
    val, ts = _stats_cache['eth_profile']
    if time.monotonic() - ts < max_age:
        return val
    try:
        out = subprocess.run(["nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show", "--active"],
                             capture_output=True, text=True, timeout=3).stdout
        val = next((line.split(':')[0] for line in out.splitlines() if 'eth' in line), '')
    except Exception:
        pass  # keep last known value rather than blanking the display
    _stats_cache['eth_profile'] = (val, time.monotonic())
    return val


def get_active_app_service(max_age=5):
    """Which app service is running: 'companion', 'satellite' or None. Cached."""
    val, ts = _stats_cache['service']
    if time.monotonic() - ts < max_age:
        return val
    try:
        if subprocess.run(["systemctl", "is-active", "--quiet", "companion.service"], timeout=3).returncode == 0:
            val = 'companion'
        elif subprocess.run(["systemctl", "is-active", "--quiet", "satellite.service"], timeout=3).returncode == 0:
            val = 'satellite'
        else:
            val = None
    except Exception:
        pass  # keep last known value
    _stats_cache['service'] = (val, time.monotonic())
    return val


def invalidate_stats_cache():
    """Force fresh reads on the next render (call after toggling service/network)."""
    _stats_cache['eth_profile'] = (_stats_cache['eth_profile'][0], 0.0)
    _stats_cache['service'] = (_stats_cache['service'][0], 0.0)


def get_cpu_temp_str():
    """SoC temperature formatted like vcgencmd ("49.4'C"), read from /sys."""
    try:
        with open('/sys/class/thermal/thermal_zone0/temp') as f:
            return f"{int(f.read().strip()) / 1000.0:.1f}'C"
    except Exception:
        return "N/A"


def update_oled_display(force=False):
    global blink_state, gateway, update_flag, last_update_time, datetime_temp, time_format_24hr, message_displayed, selected_version
    global companion_version, satellite_version  # Declare as global to modify them
    # Use monotonic time for throttle check (not affected by system time changes)
    current_monotonic = time.monotonic()
    if message_displayed or updating_application:
        return
    # Skip LOOPTIME throttle when force=True (e.g., button presses)
    if not force and (not update_flag or (current_monotonic - last_update_time) < LOOPTIME):
        return
    update_flag = False
    last_update_time = current_monotonic
    logging.debug("Updating OLED display")

    with oled_lock:
        local_image = Image.new("1", (oled.width, oled.height))
        local_draw = ImageDraw.Draw(local_image)

        state = load_state()

        clear_display()

        if menu_state == "default":
            current_time_format = "%H:%M:%S" if time_format_24hr else "%I:%M:%S %p"
            current_time_str = get_system_time().strftime(current_time_format)
            # System stats via FAST STATS (see above) - no subprocesses in the
            # per-second render path. Note: the old top/free/df pipelines were
            # computing CPU/Mem/Disk strings that were never drawn on this
            # screen, so they are simply gone.
            IP = get_display_ip()
            Temp = get_cpu_temp_str()
            EthProfile = get_eth_profile()

            active_service = get_active_app_service()
            if active_service == 'companion':
                title = "COMPANION"
                port = ":8000"
            elif active_service == 'satellite':
                title = "SATELLITE"
                port = ":9999"
            else:
                title = "SYSTEM OFF"
                port = ""

            # Center the title text
            title_bbox = local_draw.textbbox((0, 0), title, font=font14)
            title_x = (oled.width - (title_bbox[2] - title_bbox[0])) // 2

            # Pi Stats Display
            local_draw.text((0, 0), f"{title}", font=font9, fill=255)
            local_draw.text((95, 0), EthProfile, font=font9, fill=255)
            local_draw.text((0, 12), IP, font=font11, fill=255)
            local_draw.text((95, 12), port, font=font11, fill=255)
            local_draw.text((0, 26), f"{current_time_str}", font=font11, fill=255)
            local_draw.text((92, 26), Temp, font=font11, fill=255)
            # Center the version text horizontally
            version_text = f"Omnicon {current_version}"
            version_bbox = local_draw.textbbox((0, 0), version_text, font=font11)
            version_x = (oled.width - (version_bbox[2] - version_bbox[0])) // 2
            local_draw.text((version_x, 39), version_text, font=font11, fill=255)
            local_draw.text((6, 54), "OMNICONPRO.COM / HELP", font=font9, fill=255)

        elif menu_state == "application":
            # Refresh versions
            companion_version = get_companion_version()
            satellite_version = get_satellite_version()
            # Update the menu with the new versions
            application_menu[0] = f"Companion {companion_version}"
            application_menu[1] = f"Satellite {satellite_version}"

            options = menu_options[menu_state]
            for i, option in enumerate(options):
                if option:
                    prefix = ""
                    # Check if the service is active
                    if option.startswith("Companion") and is_service_active("companion.service"):
                        prefix = "*"
                    elif option.startswith("Satellite") and is_service_active("satellite.service"):
                        prefix = "*"
                    suffix = indicators.get(f"K{i+1}", "")  # Use .get to avoid KeyError
                    local_draw.text((0, i * 16), f"{prefix}{option}", font=font11, fill=255)
                    local_draw.text((112, i * 16), suffix, font=font11, fill=255)

        elif menu_state == "set_static_ip":
            ip_display = [f"{ip:03}" for ip in ip_address]
            if blink_state:
                ip_display[ip_octet] = f"[{ip_display[ip_octet]}]"  # Highlight the selected octet with brackets
            else:
                ip_display[ip_octet] = f" {ip_display[ip_octet]} "  # Remove brackets during blink off
            local_draw.text((0, 0), "   SET IP ADDRESS", font=font12, fill=255)
            local_draw.text((0, 16), ' '.join(ip_display), font=font12, fill=255)
            local_draw.text((0, 32), "CANCEL : 1 SECOND  ◀", font=font11, fill=255)
            local_draw.text((0, 48), "APPLY :    1 SECOND  ▶", font=font11, fill=255)

        elif menu_state == "set_static_sm":
            sm_display = [f"{sm:03}" for sm in subnet_mask]
            if blink_state:
                sm_display[ip_octet] = f"[{sm_display[ip_octet]}]"  # Highlight the selected octet with brackets
            else:
                sm_display[ip_octet] = f" {sm_display[ip_octet]} "  # Remove brackets during blink off
            local_draw.text((0, 0), "  SET SUBNET MASK", font=font12, fill=255)
            local_draw.text((0, 16), ' '.join(sm_display), font=font12, fill=255)
            local_draw.text((0, 32), "CANCEL : 1 SECOND  ◀", font=font11, fill=255)
            local_draw.text((0, 48), "APPLY :    1 SECOND  ▶", font=font11, fill=255)

        elif menu_state == "set_static_gw":
            gw_display = [f"{gw:03}" for gw in gateway]
            if blink_state:
                gw_display[ip_octet] = f"[{gw_display[ip_octet]}]"  # Highlight the selected octet with brackets
            else:
                gw_display[ip_octet] = f" {gw_display[ip_octet]} "  # Remove brackets during blink off
            local_draw.text((0, 0), "     SET GATEWAY", font=font12, fill=255)
            local_draw.text((0, 16), ' '.join(gw_display), font=font12, fill=255)
            local_draw.text((0, 32), "CANCEL : 1 SECOND  ◀", font=font11, fill=255)
            local_draw.text((0, 48), "APPLY :    1 SECOND  ▶", font=font11, fill=255)

        elif menu_state == "show_network_info":
            ip, subnet, gateway_addr, dns = get_current_network_settings()
            local_draw.text((0, 0), f"IP: {ip}", font=font11, fill=255)
            local_draw.text((0, 16), f"SUB: {subnet}", font=font11, fill=255)
            local_draw.text((0, 32), f"GW: {gateway_addr}", font=font11, fill=255)
            local_draw.text((0, 48), f"DNS: {dns}", font=font11, fill=255)

        elif menu_state == "show_pi_health":
            temp, voltage, watt_input, cpu, memory = get_pi_health()
            current_datetime = get_system_time().strftime("%m/%d/%y  %H:%M" if time_format_24hr else "%m/%d/%y  %I:%M %p")
            local_draw.text((0, 0), f" {current_datetime}", font=font12, fill=255)
            local_draw.text((12, 16), f"RAM: {memory}", font=font11, fill=255)
            local_draw.text((11, 32), f"V: {voltage}   W: {watt_input:.2f}", font=font11, fill=255)
            local_draw.text((39, 48), f"CPU: {cpu:.2f}%", font=font11, fill=255)

        elif menu_state == "show_lan_stats":
            mode, ip, subnet, gw = get_lan_network_info()
            local_draw.text((0, 0), f"LAN: {mode}", font=font11, fill=255)
            local_draw.text((0, 16), f"IP: {ip}", font=font11, fill=255)
            local_draw.text((0, 32), f"SUB: {subnet}", font=font11, fill=255)
            local_draw.text((0, 48), f"GW: {gw}", font=font11, fill=255)

        elif menu_state == "show_wifi_stats":
            wifi_info = get_wifi_network_info()
            if wifi_info is None:
                # WiFi disabled or not available
                local_draw.text((0, 0), "WIFI", font=font11, fill=255)
                local_draw.text((0, 24), "DISCONNECTED", font=font14, fill=255)
            elif wifi_info[0] == "DISCONNECTED":
                # WiFi enabled but not connected
                local_draw.text((0, 0), "WIFI", font=font11, fill=255)
                local_draw.text((0, 24), "DISCONNECTED", font=font14, fill=255)
            else:
                ssid, ip, subnet, gw = wifi_info
                # Truncate SSID if too long
                display_ssid = ssid[:10] if len(ssid) > 10 else ssid
                local_draw.text((0, 0), f"WIFI: {display_ssid}", font=font11, fill=255)
                local_draw.text((0, 16), f"IP: {ip}", font=font11, fill=255)
                local_draw.text((0, 32), f"SUB: {subnet}", font=font11, fill=255)
                local_draw.text((0, 48), f"GW: {gw}", font=font11, fill=255)

        elif menu_state == "set_date":
            date_display = datetime_temp.strftime("%m/%d/%y")
            if blink_state:
                if ip_octet == 0:
                    date_display = f"[{date_display[:2]}]{date_display[2:]}"
                elif ip_octet == 1:
                    date_display = f"{date_display[:3]}[{date_display[3:5]}]{date_display[5:]}"
                elif ip_octet == 2:
                    date_display = f"{date_display[:6]}[{date_display[6:]}]"
            else:
                date_display = datetime_temp.strftime("%m/%d/%y")
            local_draw.text((0, 0), "          SET DATE", font=font12, fill=255)
            local_draw.text((35, 16), date_display, font=font12, fill=255)
            local_draw.text((0, 32), "CANCEL : 1 SECOND  ◀", font=font11, fill=255)
            local_draw.text((0, 48), "APPLY :    1 SECOND  ▶", font=font11, fill=255)

        elif menu_state == "set_time":
            time_format_display = "24hr" if time_format_24hr else "12hr"
            time_display = datetime_temp.strftime("%H:%M:%S" if time_format_24hr else "%I:%M:%S")
            am_pm_display = datetime_temp.strftime("%p") if not time_format_24hr else ""

            if blink_state:
                if ip_octet == 0:
                    time_format_display = f"[{time_format_display}]"
                elif ip_octet == 1:
                    # Hours: [HH]:MM:SS
                    time_display = f"[{time_display[:2]}]{time_display[2:]}"
                elif ip_octet == 2:
                    # Minutes: HH:[MM]:SS
                    time_display = f"{time_display[:3]}[{time_display[3:5]}]{time_display[5:]}"
                elif ip_octet == 3:
                    # Seconds: HH:MM:[SS]
                    time_display = f"{time_display[:6]}[{time_display[6:]}]"
                elif ip_octet == 4 and not time_format_24hr:
                    am_pm_display = f"[{am_pm_display}]"
            else:
                time_format_display = "24hr" if time_format_24hr else "12hr"
                time_display = datetime_temp.strftime("%H:%M:%S" if time_format_24hr else "%I:%M:%S")
                am_pm_display = datetime_temp.strftime("%p") if not time_format_24hr else ""

            local_draw.text((0, 0), "          SET TIME", font=font12, fill=255)
            local_draw.text((0, 16), f"{time_format_display} - {time_display} {am_pm_display}", font=font12, fill=255)
            local_draw.text((0, 32), "CANCEL : 1 SECOND  ◀", font=font11, fill=255)
            local_draw.text((0, 48), "APPLY :    1 SECOND  ▶", font=font11, fill=255)

        elif menu_state == "set_datetime":
            current_datetime = get_system_time().strftime("%m/%d/%y   %H:%M" if time_format_24hr else "%m/%d/%y   %I:%M %p")
            local_draw.text((0, 0), f"{current_datetime}", font=font12, fill=255)
            local_draw.text((0, 16), "SET DATE", font=font12, fill=255)
            local_draw.text((0, 32), "SET TIME", font=font12, fill=255)
            local_draw.text((0, 48), "EXIT", font=font12, fill=255)
            local_draw.text((112, 16), indicators["K2"], font=font11, fill=255)  # Down button for SET DATE
            local_draw.text((112, 32), indicators["K3"], font=font11, fill=255)  # Left button for SET TIME
            local_draw.text((112, 48), indicators["K4"], font=font11, fill=255)  # Right button for EXIT

        elif menu_state == "update":
            for i, option in enumerate(update_menu):
                if option:
                    suffix = indicators.get(f"K{i+1}", "")  # Use .get to avoid KeyError
                    local_draw.text((0, i * 16), option, font=font11, fill=255)
                    if i > 0:  # Skip the indicator for the first line
                        local_draw.text((112, i * 16), suffix, font=font11, fill=255)

        elif menu_state == "update_confirm":
            if selected_version is None:
                display_version = "Unknown"
            else:
                display_version = selected_version
            local_draw.text((0, 0), f"CURRENT: {current_version}", font=font11, fill=255)
            local_draw.text((0, 16), f"AVAILABLE: {display_version}", font=font11, fill=255)
            local_draw.text((0, 32), "CANCEL", font=font11, fill=255)
            local_draw.text((112, 32), indicators["K3"], font=font11, fill=255)
            local_draw.text((0, 48), "APPLY", font=font11, fill=255)
            local_draw.text((112, 48), indicators["K4"], font=font11, fill=255)


        elif menu_state == "downgrade_confirm":
            if selected_version is None:
                display_version = "Unknown"
            else:
                display_version = selected_version
            local_draw.text((0, 0), f"CURRENT: {current_version}", font=font11, fill=255)
            local_draw.text((0, 16), f"AVAILABLE: {display_version}", font=font11, fill=255)
            local_draw.text((0, 32), "CANCEL", font=font11, fill=255)
            local_draw.text((112, 32), indicators["K3"], font=font11, fill=255)
            local_draw.text((0, 48), "APPLY", font=font11, fill=255)
            local_draw.text((112, 48), indicators["K4"], font=font11, fill=255)


        elif menu_state in ["upgrade_select", "downgrade_select"]:
            for i, version in enumerate(available_versions[:3]):
                suffix = indicators.get(f"K{i+1}", "")  # Use .get to avoid KeyError
                local_draw.text((0, i * 16), version, font=font11, fill=255)
                local_draw.text((112, i * 16), suffix, font=font11, fill=255)
            local_draw.text((0, 48), "EXIT", font=font11, fill=255)
            local_draw.text((112, 48), indicators["K4"], font=font11, fill=255)

        elif menu_state in ["pick_companion_version", "pick_satellite_version"]:
            # Scrollable version picker: show 3 versions + EXIT
            # K1=scroll up, K2=scroll down, K3=select, K4=back
            if not app_version_list:
                local_draw.text((0, 0), "NO VERSIONS", font=font11, fill=255)
                local_draw.text((0, 48), "BACK", font=font11, fill=255)
                local_draw.text((112, 48), indicators["K4"], font=font11, fill=255)
            else:
                visible = app_version_list[app_version_scroll:app_version_scroll + 3]
                for i, ver in enumerate(visible):
                    prefix = "> " if i == app_version_cursor else "  "
                    local_draw.text((0, i * 16), prefix + ver, font=font11, fill=255)
                # Show scroll position and button hints
                total = len(app_version_list)
                pos_text = f"{app_version_scroll + app_version_cursor + 1}/{total}"
                local_draw.text((45, 48), pos_text, font=font11, fill=255)
                local_draw.text((0, 48), indicators["K3"], font=font11, fill=255)
                local_draw.text((10, 48), "EXIT", font=font11, fill=255)
                local_draw.text((88, 48), "SEL", font=font11, fill=255)
                local_draw.text((112, 48), indicators["K4"], font=font11, fill=255)

        elif menu_state == "app_updates":
            options = menu_options[menu_state]
            for i, option in enumerate(options):
                if option:
                    if i == 0:
                        # Center the first line and remove the indicator
                        text_width, text_height = local_draw.textsize(option, font=font11)
                        x_position = (oled.width - text_width) // 2
                        local_draw.text((x_position, i * 16), option, font=font11, fill=255)
                    else:
                        suffix = indicators.get(f"K{i+1}", "")
                        local_draw.text((0, i * 16), option, font=font11, fill=255)
                        local_draw.text((112, i * 16), suffix, font=font11, fill=255)

        elif menu_state == "update_companion":
            options = menu_options[menu_state]
            for i, option in enumerate(options):
                if option:
                    if i == 0:
                        # Center the text "UPDATE COMPANION" without indicator
                        text_width, text_height = local_draw.textsize(option, font=font11)
                        x_position = (oled.width - text_width) // 2
                        local_draw.text((x_position, i * 16), option, font=font11, fill=255)
                    else:
                        # Show indicators on lines 2, 3, & 4
                        suffix = indicators.get(f"K{i+1}", "")
                        local_draw.text((0, i * 16), option, font=font11, fill=255)
                        local_draw.text((112, i * 16), suffix, font=font11, fill=255)

        elif menu_state == "update_satellite":
            options = menu_options[menu_state]
            for i, option in enumerate(options):
                if option:
                    if i == 0:
                        # Center the text "UPDATE SATELLITE" without indicator
                        text_width, text_height = local_draw.textsize(option, font=font11)
                        x_position = (oled.width - text_width) // 2
                        local_draw.text((x_position, i * 16), option, font=font11, fill=255)
                    else:
                        # Show indicators on lines 2, 3, & 4
                        suffix = indicators.get(f"K{i+1}", "")
                        local_draw.text((0, i * 16), option, font=font11, fill=255)
                        local_draw.text((112, i * 16), suffix, font=font11, fill=255)

        elif menu_state == "app_update_companion":
            options = menu_options[menu_state]
            for i, option in enumerate(options):
                if option:
                    if i == 0:
                        # Center the text "UPDATE COMPANION" and remove button indicator
                        text_width = local_draw.textsize(option, font=font11)[0]
                        x = (oled.width - text_width) // 2
                        local_draw.text((x, i * 16), option, font=font11, fill=255)
                        # No button indicator
                    else:
                        suffix = indicators.get(f"K{i+1}", "")  # Use .get to avoid KeyError
                        local_draw.text((0, i * 16), option, font=font11, fill=255)
                        local_draw.text((112, i * 16), suffix, font=font11, fill=255)

        elif menu_state == "app_update_satellite":
            options = menu_options[menu_state]
            for i, option in enumerate(options):
                if option:
                    if i == 0:
                        # Center the text "UPDATE SATELLITE" and remove button indicator
                        text_width = local_draw.textsize(option, font=font11)[0]
                        x = (oled.width - text_width) // 2
                        local_draw.text((x, i * 16), option, font=font11, fill=255)
                        # No button indicator
                    else:
                        suffix = indicators.get(f"K{i+1}", "")  # Use .get to avoid KeyError
                        local_draw.text((0, i * 16), option, font=font11, fill=255)
                        local_draw.text((112, i * 16), suffix, font=font11, fill=255)

        else:
            options = menu_options.get(menu_state, [])
            state = load_state()
            for i, option in enumerate(options):
                if option:
                    prefix = ""
                    if menu_state == "network":
                        if (option == "DHCP" and state["network"] == DHCP_PROFILE) or (option == "STATIC IP" and state["network"] == STATIC_PROFILE):
                            prefix = "*"
                    suffix = indicators.get(f"K{i+1}", "")  # Use .get to avoid KeyError
                    local_draw.text((0, i * 16), f"{prefix}{option}", font=font11, fill=255)
                    local_draw.text((112, i * 16), suffix, font=font11, fill=255)

        oled.image(local_image.rotate(180))
        oled.show()
        blink_state = not blink_state
        update_flag = True
        logging.debug("OLED display updated")

def reset_to_main():
    global menu_state, ip_address, subnet_mask, gateway, timeout_flag, datetime_temp, ip_octet
    if not timeout_flag:
        logging.debug("Timeout: Resetting to main display")
        menu_state = "default"
        ip_address = original_ip_address[:]
        subnet_mask = original_subnet_mask[:]
        gateway = original_gateway[:]
        datetime_temp = get_system_time()
        ip_octet = 0  # Reset IP octet position
        update_oled_display(force=True)
        timeout_flag = True

# Debounce decorator for button event handlers
def debounce(func):
    def wrapper(*args, **kwargs):
        # Use monotonic time for debounce (not affected by system time changes)
        current_time = time.monotonic()
        if current_time - wrapper.last_called >= debounce_time:
            func(*args, **kwargs)
            wrapper.last_called = current_time
    wrapper.last_called = 0
    return wrapper

# Button event handlers with debounce
@debounce
def button_k1_pressed():
    global menu_state, menu_selection, ip_octet, last_interaction_time, timeout_flag, datetime_temp
    global app_version_cursor, app_version_scroll
    logging.debug("K1 pressed")
    last_interaction_time = time.monotonic()
    timeout_flag = False

    if menu_state in ["show_network_info", "show_pi_health", "show_lan_stats", "show_wifi_stats"]:
        reset_to_main()
    elif menu_state == "default":
        logging.debug("Switching from default to main menu via K1")
        menu_state = "main"
        menu_selection = 0
    elif menu_state == "set_static_ip":
        ip_address[ip_octet] = (ip_address[ip_octet] + 1) % 256
    elif menu_state == "set_static_sm":
        subnet_mask[ip_octet] = (subnet_mask[ip_octet] + 1) % 256
    elif menu_state == "set_static_gw":
        gateway[ip_octet] = (gateway[ip_octet] + 1) % 256
    elif menu_state == "set_date":
        update_date(1)
    elif menu_state == "set_time":
        update_time(1)
    elif menu_state in ["update_confirm", "downgrade_confirm"]:
        # Do nothing on short press
        pass
    elif menu_state in ["pick_companion_version", "pick_satellite_version"]:
        # K1 = scroll up
        if app_version_cursor > 0:
            app_version_cursor -= 1
        elif app_version_scroll > 0:
            app_version_scroll -= 1
    else:
        menu_selection = 0
        activate_menu_item()
    update_oled_display(force=True)

@debounce
def button_k2_pressed():
    global menu_state, menu_selection, ip_octet, last_interaction_time, timeout_flag, datetime_temp
    global app_version_cursor, app_version_scroll
    logging.debug("K2 pressed")
    last_interaction_time = time.monotonic()
    timeout_flag = False

    if menu_state in ["show_network_info", "show_pi_health", "show_lan_stats", "show_wifi_stats"]:
        reset_to_main()
    elif menu_state == "default":
        logging.debug("Switching from default to main menu via K2")
        menu_state = "main"
        menu_selection = 0
    elif menu_state in ["set_static_ip", "set_static_sm", "set_static_gw", "set_date", "set_time"]:
        # Handle special editing screens
        if menu_state == "set_static_ip":
            ip_address[ip_octet] = (ip_address[ip_octet] - 1) % 256
        elif menu_state == "set_static_sm":
            subnet_mask[ip_octet] = (subnet_mask[ip_octet] - 1) % 256
        elif menu_state == "set_static_gw":
            gateway[ip_octet] = (gateway[ip_octet] - 1) % 256
        elif menu_state == "set_date":
            update_date(-1)
        elif menu_state == "set_time":
            update_time(-1)
        # Don't call activate_menu_item for these special editing screens
    elif menu_state in ["update_confirm", "downgrade_confirm"]:
        # Do nothing on short press
        pass
    elif menu_state in ["pick_companion_version", "pick_satellite_version"]:
        # K2 = scroll down
        total = len(app_version_list)
        if app_version_cursor < 2 and (app_version_scroll + app_version_cursor) < total - 1:
            app_version_cursor += 1
        elif (app_version_scroll + 3) < total:
            app_version_scroll += 1
    else:
        menu_selection = 1
        activate_menu_item()
    update_oled_display(force=True)

@debounce
def button_k3_pressed():
    global menu_state, menu_selection, ip_octet, last_interaction_time, timeout_flag, updating_application
    global app_version_list, app_version_scroll, app_version_cursor
    logging.debug("K3 pressed")
    last_interaction_time = time.monotonic()
    timeout_flag = False

    if menu_state in ["show_network_info", "show_pi_health", "show_lan_stats", "show_wifi_stats"]:
        reset_to_main()
    elif menu_state == "default":
        menu_state = "show_pi_health"
    elif menu_state == "application":
        # Move to the app updates menu when K3 is pressed in application menu
        menu_state = "app_updates"
        menu_selection = 0
    elif menu_state in ["set_static_ip", "set_static_sm", "set_static_gw", "set_date"]:
        ip_octet = (ip_octet - 1) % 4  # 4 octets for IP/date
        # Don't call activate_menu_item for these special editing screens
    elif menu_state == "set_time":
        # Time has: format, hours, minutes, seconds (+ AM/PM for 12hr)
        max_octet = 5 if not time_format_24hr else 4
        ip_octet = (ip_octet - 1) % max_octet
    elif menu_state in ["update_confirm", "downgrade_confirm"]:
        # Cancel action
        menu_state = "update"
        selected_version = None  # Reset selected_version
        # Don't call activate_menu_item here
    elif menu_state in ["pick_companion_version", "pick_satellite_version"]:
        # K3 = back/exit
        if menu_state == "pick_companion_version":
            menu_state = "update_companion"
        else:
            menu_state = "update_satellite"
        menu_selection = 0
    else:
        # Only call activate_menu_item for normal menus with selectable options
        menu_selection = 2
        activate_menu_item()
    update_oled_display(force=True)

@debounce
def button_k4_pressed():
    global menu_state, menu_selection, ip_octet, ip_address, subnet_mask, gateway
    global original_ip_address, original_subnet_mask, original_gateway
    global datetime_temp, last_interaction_time, time_format_24hr, selected_version, timeout_flag
    global updating_application  # was missing: its assignment below created a LOCAL,
    # so the display loop kept fighting the update screen (rapid flashing)
    logging.debug("K4 pressed")
    last_interaction_time = time.monotonic()
    timeout_flag = False  # Reset timeout flag

    if menu_state in ["show_network_info", "show_pi_health"]:
        reset_to_main()
    elif menu_state == "default":
        # Show LAN stats when K4 pressed from default
        menu_state = "show_lan_stats"
        logging.debug("Switching to show_lan_stats")
    elif menu_state == "show_lan_stats":
        # Show WiFi stats when K4 pressed from LAN stats
        menu_state = "show_wifi_stats"
        logging.debug("Switching to show_wifi_stats")
    elif menu_state == "show_wifi_stats":
        # Return to default when K4 pressed from WiFi stats
        reset_to_main()
    elif menu_state in ["set_static_ip", "set_static_sm", "set_static_gw", "set_date"]:
        ip_octet = (ip_octet + 1) % 4  # 4 octets for IP/date
        # Don't call activate_menu_item for these special editing screens
    elif menu_state == "set_time":
        # Time has: format, hours, minutes, seconds (+ AM/PM for 12hr)
        max_octet = 5 if not time_format_24hr else 4
        ip_octet = (ip_octet + 1) % max_octet
    elif menu_state == "update_confirm":
        if selected_version:
            result = perform_update(selected_version)
        else:
            result = "NO VERSION SELECTED"
        duration = 5
        show_message(result, duration)
        menu_state = "default"
        selected_version = None  # Reset selected_version
    elif menu_state == "downgrade_confirm":
        if selected_version:
            result = perform_downgrade(selected_version)
        else:
            result = "NO VERSION SELECTED"
        duration = 5
        show_message(result, duration)
        menu_state = "default"
        selected_version = None  # Reset selected_version
    elif menu_state in ["pick_companion_version", "pick_satellite_version"]:
        # K4 = select the highlighted version
        idx = app_version_scroll + app_version_cursor
        if idx < len(app_version_list):
            selected_ver = app_version_list[idx]
            app_name = "companion" if menu_state == "pick_companion_version" else "satellite"
            update_cmd = build_versioned_update_command(app_name, selected_ver)
            if is_connected():
                show_message(f"UPDATING\n{app_name.upper()}\n{selected_ver}", 2)
                updating_application = True
                execute_command_with_progress(update_cmd)
                updating_application = False
                show_message("UPDATE COMPLETE", 2)
            else:
                show_message("PLEASE CONNECT\nTO INTERNET", 3)
                menu_state = "default"
    else:
        menu_selection = 3
        activate_menu_item()
    update_oled_display(force=True)

def hold_k3():
    global menu_state, ip_address, subnet_mask, gateway, original_ip_address, original_subnet_mask, original_gateway, last_interaction_time, selected_version, timeout_flag
    logging.debug("K3 held for 1 seconds")
    last_interaction_time = time.monotonic()
    timeout_flag = False  # Reset timeout flag to ensure buttons remain responsive

    if menu_state in ["set_static_ip", "set_static_sm", "set_static_gw"]:
        ip_address = original_ip_address[:]
        subnet_mask = original_subnet_mask[:]
        gateway = original_gateway[:]
        menu_state = "set_static"
    elif menu_state in ["set_date", "set_time"]:
        menu_state = "set_datetime"
    update_oled_display(force=True)  # Ensure display updates after state change


def hold_k4():
    global menu_state, updating_application, ip_address, subnet_mask, gateway, original_ip_address, original_subnet_mask, original_gateway, datetime_temp, last_interaction_time, time_format_24hr, selected_version, timeout_flag
    logging.info(f"K4 held - menu_state: {menu_state}")
    last_interaction_time = time.monotonic()
    timeout_flag = False  # Reset timeout flag to ensure buttons remain responsive

    if menu_state in ["set_static_ip", "set_static_sm", "set_static_gw"]:
        save_static_settings()
        apply_static_settings()
        original_ip_address = ip_address[:]
        original_subnet_mask = subnet_mask[:]
        original_gateway = gateway[:]
        menu_state = "set_static"
        update_oled_display(force=True)  # Ensure display updates after state change
    elif menu_state in ["set_date", "set_time"]:
        # Run datetime setting in background to prevent OLED freeze
        logging.info(f"Applying datetime: {datetime_temp}")
        def apply_datetime():
            set_system_datetime(datetime_temp)
            state = load_state()
            state["time_format_24hr"] = time_format_24hr
            save_state(state)
            update_clock_format(time_format_24hr)
            # Force timezone reload so display updates immediately
            if 'TZ' in os.environ:
                del os.environ['TZ']
            time.tzset()
            logging.info("Applied datetime via buttons")

        threading.Thread(target=apply_datetime, daemon=True).start()
        # Go back to the main menu immediately (don't wait for datetime to apply)
        menu_state = "default"
        menu_selection = 0
        update_oled_display(force=True)


def save_static_settings():
    state = load_state()
    state["static_ip"] = ip_address
    state["subnet_mask"] = subnet_mask
    state["gateway"] = gateway
    save_state(state)
    logging.info(f"Static settings saved: IP {ip_address}, Subnet {subnet_mask}, Gateway {gateway}")

def apply_static_settings(dns_server=None):
    ip_str = '.'.join(map(str, ip_address))
    sm_str = '.'.join(map(str, subnet_mask))
    gw_str = '.'.join(map(str, gateway))
    cidr = subnet_mask_to_cidr(sm_str)
    # Use provided DNS or default to gateway
    dns_str = dns_server if dns_server else gw_str
    execute_command(f"sudo nmcli connection modify {STATIC_PROFILE} ipv4.addresses {ip_str}/{cidr}")
    execute_command(f"sudo nmcli connection modify {STATIC_PROFILE} ipv4.gateway {gw_str}")
    execute_command(f"sudo nmcli connection modify {STATIC_PROFILE} ipv4.method manual")
    execute_command(f"sudo nmcli connection modify {STATIC_PROFILE} ipv4.dns {dns_str}")
    execute_command(f"sudo nmcli connection up {STATIC_PROFILE}")
    logging.info(f"Static IP settings applied to the network profile. DNS: {dns_str}")

def update_date(increment):
    global datetime_temp
    try:
        if ip_octet == 0:
            new_month = (datetime_temp.month + increment - 1) % 12 + 1
            datetime_temp = datetime_temp.replace(month=new_month)
        elif ip_octet == 1:
            new_day = (datetime_temp.day + increment - 1) % 31 + 1
            datetime_temp = datetime_temp.replace(day=new_day)
        elif ip_octet == 2:
            datetime_temp = datetime_temp.replace(year=datetime_temp.year + increment)
    except ValueError as e:
        logging.error(f"Error updating date: {e}")

def update_time(increment):
    global datetime_temp, time_format_24hr
    try:
        if ip_octet == 0:
            time_format_24hr = not time_format_24hr
        elif ip_octet == 1:
            if time_format_24hr:
                # 24-hour format: Simply increment/decrement hour
                new_hour = (datetime_temp.hour + increment) % 24
            else:
                # 12-hour format: Handle hours 1-12
                current_hour = datetime_temp.hour
                is_pm = current_hour >= 12
                display_hour = current_hour % 12
                if display_hour == 0:
                    display_hour = 12

                # Increment/decrement the display hour
                display_hour = display_hour + increment
                if display_hour > 12:
                    display_hour = 1
                elif display_hour < 1:
                    display_hour = 12

                # Convert back to 24-hour format
                if is_pm:
                    new_hour = display_hour % 12 + 12
                else:
                    new_hour = display_hour % 12

            datetime_temp = datetime_temp.replace(hour=new_hour)
        elif ip_octet == 2:
            new_minute = (datetime_temp.minute + increment) % 60
            datetime_temp = datetime_temp.replace(minute=new_minute)
        elif ip_octet == 3:
            # Seconds
            new_second = (datetime_temp.second + increment) % 60
            datetime_temp = datetime_temp.replace(second=new_second)
        elif ip_octet == 4 and not time_format_24hr:
            # Toggle AM/PM
            current_hour = datetime_temp.hour
            if current_hour >= 12:
                # PM to AM
                new_hour = current_hour - 12
            else:
                # AM to PM
                new_hour = current_hour + 12
            datetime_temp = datetime_temp.replace(hour=new_hour)
    except ValueError as e:
        logging.error(f"Error updating time: {e}")

def set_system_datetime(datetime_temp):
    # Format the full datetime string in a format that 'date' command understands
    # Use 24-hour format for the system command regardless of display preference
    datetime_str = datetime_temp.strftime("%Y-%m-%d %H:%M:%S")

    # Disable NTP first so it doesn't immediately overwrite our manual time
    execute_command("sudo timedatectl set-ntp false")

    # Set the system date and time in one command
    cmd = f"sudo date --set='{datetime_str}'"
    result = execute_command(cmd)

    # Also sync the hardware clock
    execute_command("sudo hwclock --systohc")

    logging.info(f"System datetime set to: {datetime_str}")
    return result

def restart_script():
    """Restarts both omnicon and web GUI services properly."""
    logging.info("Restarting services after update...")

    # Create a restart script that will run independently
    restart_script_content = """#!/bin/bash
# Wait for the current process to exit
sleep 3

# Restart omnicon service
sudo systemctl restart omnicon.service

# Try both possible web service names (omnicon-web.service or omnicon-web-simple.service)
sudo systemctl restart omnicon-web.service 2>/dev/null || sudo systemctl restart omnicon-web-simple.service 2>/dev/null

# Remove this temp script
rm -f /tmp/restart_omnicon.sh
"""

    try:
        # Write the restart script
        with open('/tmp/restart_omnicon.sh', 'w') as f:
            f.write(restart_script_content)

        # Make it executable
        os.chmod('/tmp/restart_omnicon.sh', 0o755)

        # Launch the restart script in the background
        subprocess.Popen(['/bin/bash', '/tmp/restart_omnicon.sh'],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True)

        logging.info("Restart script launched, exiting current process...")

        # Exit cleanly so the restart script can do its work
        sys.exit(0)

    except Exception as e:
        logging.error(f"Failed to create restart script: {e}")
        # Fallback to the old method
        logging.info("Falling back to direct restart")
        os.execv(sys.executable, ['python3'] + sys.argv)

def subnet_mask_to_cidr(mask):
    mask_octets = map(int, mask.split('.'))
    binary_str = ''.join([bin(octet).lstrip('0b').zfill(8) for octet in mask_octets])
    return str(binary_str.count('1'))

def turn_off_oled():
    with oled_lock:
        oled.fill(0)
        oled.show()
        oled.poweroff()

def update_clock_format(time_format_24hr):
    config_file_path = os.path.expanduser("~/.config/wf-panel-pi.ini")

    try:
        # Read the configuration file
        with open(config_file_path, 'r') as file:
            lines = file.readlines()

        # Modify the clock_format line
        with open(config_file_path, 'w') as file:
            for line in lines:
                if line.startswith('clock_format'):
                    if time_format_24hr:
                        file.write('clock_format=%H:%M:%S\n')
                    else:
                        file.write('clock_format=%I:%M:%S %p\n')
                else:
                    file.write(line)

        # Restart the panel to apply changes (may fail if no display attached)
        try:
            subprocess.run(['lxpanelctl', 'restart'], check=False, capture_output=True)
        except Exception:
            pass  # Ignore panel restart errors - service may run without display

        logging.info(f"Clock format set to {'24-hour' if time_format_24hr else '12-hour'} with seconds.")
    except FileNotFoundError:
        logging.warning(f"Panel config file not found: {config_file_path}")
    except Exception as e:
        logging.error(f"Error updating clock format: {e}")

def download_and_extract_zip_from_github(tag, extract_to):
    """Download the entire OMNICON release ZIP and extract it into extract_to."""
    zip_url = f"https://github.com/RUDEWORLD/OMNICON/archive/refs/tags/{tag}.zip"
    local_zip = "/tmp/omnicon_update.zip"
    temp_extract = "/tmp/omnicon_extract"

    # Clean previous temp folders
    if os.path.exists(local_zip):
        os.remove(local_zip)
    if os.path.exists(temp_extract):
        shutil.rmtree(temp_extract)

    try:
        # Show downloading message
        show_message(f"DOWNLOADING\n{tag}...", 0.5)

        # Download the ZIP file with progress.
        # timeout=(connect, read-between-chunks): a dead network mid-download
        # raises instead of blocking forever - without this, a stalled update
        # left updating_application=True and froze the OLED until power cycle.
        # The except below turns it into a clean "UPDATE FAILED".
        r = requests.get(zip_url, stream=True, timeout=(10, 60))
        r.raise_for_status()

        total_size = int(r.headers.get('content-length', 0))
        downloaded = 0

        with open(local_zip, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        progress = int((downloaded / total_size) * 100)
                        update_oled_with_progress(progress)

        # Show extracting message
        show_message("EXTRACTING\nFILES...", 0.5)

        # Extract ZIP
        with zipfile.ZipFile(local_zip, "r") as zip_ref:
            zip_ref.extractall(temp_extract)

        # The extracted folder has a name like "OMNICON-4.0.4/"
        extracted_root = None
        for name in os.listdir(temp_extract):
            if os.path.isdir(os.path.join(temp_extract, name)):
                extracted_root = os.path.join(temp_extract, name)
                break

        if not extracted_root:
            return False, "BAD ZIP CONTENTS"

        # Copy everything EXCEPT the user's state.json
        for root, dirs, files in os.walk(extracted_root):
            rel_path = os.path.relpath(root, extracted_root)
            dest_path = os.path.join(extract_to, rel_path)

            if not os.path.exists(dest_path):
                os.makedirs(dest_path, exist_ok=True)

            for file in files:
                if file == "state.json":
                    continue  # Don't overwrite user settings

                src_file = os.path.join(root, file)
                dst_file = os.path.join(dest_path, file)

                shutil.copy2(src_file, dst_file)

        return True, ""
    except Exception as e:
        logging.error(f"Update ZIP download failed: {e}")
        return False, str(e)

def load_github_token():
    """Load GitHub token from config file if available."""
    try:
        config_path = '/home/omnicon/OLED_Stats/config.json'
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)
                token = config.get('github_token', '').strip()
                if token:
                    logging.info("GitHub token loaded from config")
                    return token
                else:
                    logging.info("No GitHub token found in config")
    except Exception as e:
        logging.warning(f"Could not load GitHub token: {e}")
    return None

def fetch_github_tags():
    url = "https://api.github.com/repos/RUDEWORLD/OMNICON/tags"
    print(f"DEBUG: fetch_github_tags called, URL: {url}")

    # Load GitHub token if available
    github_token = load_github_token()

    # Build headers with authentication if token is available
    base_headers = {
        'Accept': 'application/vnd.github.v3+json',
        'User-Agent': 'Omnicon-Updater/4.2.2'
    }

    if github_token:
        base_headers['Authorization'] = f'token {github_token}'
        logging.info("Using GitHub authentication (5000 requests/hour limit)")
    else:
        logging.warning("No GitHub token - using unauthenticated API (60 requests/hour limit)")
        logging.warning("To add a token, edit /home/pi/OLED_Stats_pi/config.json")

    # Try with full headers first, then fallback options
    headers_options = [
        base_headers,
        {'User-Agent': 'Omnicon-Updater/4.2.2'},  # Minimal headers
        {}  # Try with no headers as last resort
    ]

    for headers in headers_options:
        try:
            logging.info(f"Attempting GitHub API with headers: {headers}")
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            tags = response.json()
            logging.info(f"Successfully fetched {len(tags)} tags from GitHub")
            return [tag['name'] for tag in tags]
        except requests.exceptions.Timeout:
            logging.error("GitHub API request timed out")
            continue
        except requests.exceptions.ConnectionError as e:
            logging.error(f"Cannot connect to GitHub API: {e}")
            continue
        except requests.exceptions.HTTPError as e:
            logging.error(f"GitHub API HTTP error: {e}")
            if e.response:
                logging.error(f"Response status: {e.response.status_code}")
                logging.error(f"Response headers: {e.response.headers}")
                if e.response.status_code == 403:
                    # Check if it's rate limit or authentication issue
                    if 'rate limit' in str(e.response.text).lower():
                        logging.error("GitHub API rate limit exceeded!")
                        if not github_token:
                            logging.error("Solution: Add a GitHub token to /home/pi/OLED_Stats_pi/config.json")
                            logging.error("Visit https://github.com/settings/tokens/new to create one")
                    else:
                        logging.error("GitHub API access denied (check token permissions)")
                    # Try to get rate limit info
                    try:
                        remaining = e.response.headers.get('X-RateLimit-Remaining', 'unknown')
                        reset_time = e.response.headers.get('X-RateLimit-Reset', 'unknown')
                        if reset_time != 'unknown':
                            reset_datetime = datetime.fromtimestamp(int(reset_time))
                            logging.error(f"Rate limit remaining: {remaining}, resets at: {reset_datetime}")
                        else:
                            logging.error(f"Rate limit remaining: {remaining}")
                    except Exception:
                        pass
            continue
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to fetch tags from GitHub: {e}")
            continue
        except Exception as e:
            logging.error(f"Unexpected error fetching tags: {e}")
            continue

    # If all API attempts failed, try alternative approach using releases endpoint
    logging.warning("Tags API failed, trying releases endpoint as fallback...")
    releases_url = "https://api.github.com/repos/RUDEWORLD/OMNICON/releases"

    try:
        headers = base_headers if github_token else {'User-Agent': 'Omnicon-Updater/4.2.2'}
        response = requests.get(releases_url, headers=headers, timeout=15)
        response.raise_for_status()
        releases = response.json()
        # Extract tag names from releases
        tags = [release['tag_name'] for release in releases if 'tag_name' in release]
        if tags:
            logging.info(f"Successfully fetched {len(tags)} releases as fallback")
            return tags
    except Exception as e:
        logging.error(f"Releases endpoint also failed: {e}")

    logging.error("All attempts to fetch GitHub tags failed")
    return []

def update_omnicon():
    global available_versions, current_version, selected_version
    selected_version = None  # Initialize selected_version to None
    available_versions = []  # Clear cache to always fetch fresh versions
    print(f"DEBUG: update_omnicon called, fetching fresh versions...")
    logging.info(f"update_omnicon called, current version = {current_version}")

    if not available_versions:
        # First check if we have internet
        print("DEBUG: Checking internet connection...")
        if not is_connected():
            print("DEBUG: No internet connection detected")
            return "PLEASE CONNECT\nTO INTERNET"

        # We have internet, try to fetch tags
        print("DEBUG: Internet OK, fetching GitHub tags...")
        available_versions = fetch_github_tags()
        print(f"DEBUG: fetch_github_tags returned: {available_versions}")

        if not available_versions:
            # Internet is OK but GitHub fetch failed
            print("DEBUG: GitHub fetch failed despite internet connection")
            logging.error("Connected to internet but cannot fetch updates from GitHub")
            return "UPDATE CHECK\nFAILED"
    # Use lstrip to remove any leading 'v' or 'V'
    current_version_tuple = tuple(map(int, current_version.lstrip('vV').split('.')))
    newer_versions = [
        v for v in available_versions
        if tuple(map(int, v.lstrip('vV').split('.'))) > current_version_tuple
    ]
    if not newer_versions:
        return "YOU'RE UP TO DATE"
    selected_version = newer_versions[0]
    return "UPDATE AVAILABLE"


def perform_update(version):
    global updating_application
    extract_path = "/home/omnicon/OLED_Stats"

    updating_application = True
    show_message(f"UPDATING\nOMNICON\n{version}", 2)

    ok, err = download_and_extract_zip_from_github(version, extract_path)
    updating_application = False

    if ok:
        show_message("UPDATE COMPLETE\nRESTARTING...", 2)
        restart_script()
        return "OMNICON UPDATED"
    else:
        show_message(f"UPDATE FAILED", 3)
        return f"UPDATE FAILED\n{err}"

def downgrade_omnicon():
    global available_versions, current_version, selected_version
    selected_version = None  # Initialize selected_version to None
    available_versions = []  # Clear cache to always fetch fresh versions
    if not available_versions:
        # First check if we have internet
        if not is_connected():
            return "PLEASE CONNECT\nTO INTERNET"

        # We have internet, try to fetch tags
        available_versions = fetch_github_tags()
        if not available_versions:
            # Internet is OK but GitHub fetch failed
            logging.error("Connected to internet but cannot fetch updates from GitHub")
            return "UPDATE CHECK\nFAILED"
    current_version_tuple = tuple(map(int, current_version.lstrip('vV').split('.')))
    older_versions = [
        v for v in available_versions
        if tuple(map(int, v.lstrip('vV').split('.'))) < current_version_tuple
    ]
    if not older_versions:
        return "NO OLDER VERSIONS"
    selected_version = older_versions[0]
    return "DOWNGRADE AVAILABLE"

def perform_downgrade(version):
    global updating_application
    extract_path = "/home/omnicon/OLED_Stats"

    updating_application = True
    show_message(f"DOWNGRADING\nOMNICON\n{version}", 2)

    ok, err = download_and_extract_zip_from_github(version, extract_path)
    updating_application = False

    if ok:
        show_message("DOWNGRADE COMPLETE\nRESTARTING...", 2)
        restart_script()
        return "OMNICON DOWNGRADED"
    else:
        show_message("DOWNGRADE FAILED", 3)
        return f"DOWNGRADE FAILED\n{err}"

# Update OLED display in a separate thread
def update_oled():
    last_displayed_second = -1
    last_monotonic = time.monotonic()

    while True:
        try:
            # Use monotonic time for loop timing (not affected by system time changes)
            current_monotonic = time.monotonic()

            # Check every 0.1 seconds using monotonic clock
            if current_monotonic - last_monotonic >= 0.1:
                last_monotonic = current_monotonic

                # Get wall clock time for display
                now = time.time()
                current_second = int(now)

                # Only update display when the second changes
                if current_second != last_displayed_second:
                    update_oled_display()
                    last_displayed_second = current_second

            # Short sleep using monotonic-safe sleep
            time.sleep(0.05)
        except Exception as e:
            logging.error(f"Error in update_oled loop: {e}")
            last_displayed_second = -1  # Reset to force update on next iteration
            time.sleep(0.5)



# Web command processor for remote control
web_command_file = "web_command.json"
trigger_file = "trigger_command"
web_command_queue = []
web_command_lock = threading.Lock()

def execute_web_commands():
    """Execute queued web commands without blocking the OLED"""
    global menu_state, menu_selection, ip_address, subnet_mask, gateway
    global time_format_24hr, last_interaction_time, web_command_queue

    if not web_command_queue:
        return

    # Process one command at a time
    with web_command_lock:
        if web_command_queue:
            cmd_data = web_command_queue.pop(0)
        else:
            return

    try:
        command = cmd_data.get('command')
        params = cmd_data.get('params', {})

        logging.info(f"Executing web command: {command}")

        # Reset interaction time to prevent timeout
        last_interaction_time = time.monotonic()

        # Process different commands
        if command == 'toggle_service':
            service = params.get('service')
            if service in ['companion', 'satellite']:
                # Don't call toggle_service directly, just set the state
                menu_state = "default"
                # Schedule the service toggle
                threading.Thread(target=lambda: toggle_service(service), daemon=True).start()
                logging.info(f"Service toggle to {service} scheduled")

        elif command == 'toggle_network':
            network = params.get('network')
            if network in ['DHCP', 'STATIC']:
                # Don't block, run in background
                menu_state = "default"
                threading.Thread(target=lambda: toggle_network(network), daemon=True).start()
                logging.info(f"Network toggle to {network} scheduled")

        elif command == 'set_static_ip':
            # Parse IP settings
            ip_str = params.get('ip', '192.168.0.100')
            subnet_str = params.get('subnet', '255.255.255.0')
            gateway_str = params.get('gateway', '192.168.0.1')
            dns_str = params.get('dns', gateway_str)  # Default to gateway if not provided

            # Convert to lists
            ip_address = [int(x) for x in ip_str.split('.')]
            subnet_mask = [int(x) for x in subnet_str.split('.')]
            gateway = [int(x) for x in gateway_str.split('.')]

            # Run in background to avoid blocking
            def apply_settings():
                save_static_settings()
                apply_static_settings(dns_str)
                # Also update network mode to STATIC in state
                state = load_state()
                state["network"] = "STATIC"
                save_state(state)
                logging.info(f"Applied static IP settings via web with DNS: {dns_str}")

            threading.Thread(target=apply_settings, daemon=True).start()

        elif command == 'power':
            action = params.get('action')
            if action == 'reboot':
                logging.info("Rebooting system via web command")
                turn_off_oled()
                execute_command("sudo reboot")
            elif action == 'shutdown':
                logging.info("Shutting down system via web command")
                turn_off_oled()
                execute_command("sudo shutdown now")

        elif command == 'button_press':
            button = params.get('button')
            logging.info(f"Simulating {button} press via web")

            # Simulate button press without blocking
            if button == 'K1':
                button_k1_pressed()
            elif button == 'K2':
                button_k2_pressed()
            elif button == 'K3':
                button_k3_pressed()
            elif button == 'K4':
                button_k4_pressed()

        elif command == 'set_datetime':
            # Handle date/time setting in background
            def set_dt():
                if 'date' in params and 'time' in params:
                    datetime_str = f"{params['date']} {params['time']}"
                    execute_command(f"sudo timedatectl set-ntp false")
                    execute_command(f"sudo timedatectl set-time '{datetime_str}'")
                    logging.info(f"Set date/time to {datetime_str} via web")

                if 'format_24hr' in params:
                    global time_format_24hr
                    time_format_24hr = params['format_24hr']
                    state = load_state()
                    state['time_format_24hr'] = time_format_24hr
                    save_state(state)
                    update_clock_format(time_format_24hr)

                # Force timezone reload so display updates immediately
                if 'TZ' in os.environ:
                    del os.environ['TZ']
                time.tzset()
                logging.info("Forced timezone reload after datetime change")

            threading.Thread(target=set_dt, daemon=True).start()

        elif command == 'reload_timezone':
            # Force reload of timezone info after timezone change from web
            def reload_tz():
                if 'TZ' in os.environ:
                    del os.environ['TZ']
                time.tzset()
                logging.info("Forced timezone reload via web command")

            threading.Thread(target=reload_tz, daemon=True).start()

        elif command == 'update_companion_stable':
            # Trigger companion update through OLED menu system
            logging.info("Triggering Companion stable update via web")
            if is_connected():
                show_message("UPDATING\nCOMPANION", 2)
                global updating_application
                updating_application = True
                execute_command_with_progress('sudo companion-update stable')
                updating_application = False
                show_message("UPDATE COMPLETE", 2)
            else:
                show_message("PLEASE CONNECT\nTO INTERNET", 3)
                menu_state = "default"

        elif command == 'update_satellite_stable':
            # Trigger satellite update through OLED menu system
            logging.info("Triggering Satellite stable update via web")
            if is_connected():
                show_message("UPDATING\nSATELLITE", 2)
                updating_application = True
                execute_command_with_progress('sudo satellite-update stable')
                updating_application = False
                show_message("UPDATE COMPLETE", 2)
            else:
                show_message("PLEASE CONNECT\nTO INTERNET", 3)
                menu_state = "default"

        elif command == 'update_companion_beta':
            logging.info("Triggering Companion beta update via web")
            if is_connected():
                show_message("UPDATING\nCOMPANION BETA", 2)
                updating_application = True
                execute_command_with_progress('sudo companion-update beta')
                updating_application = False
                show_message("UPDATE COMPLETE", 2)
            else:
                show_message("PLEASE CONNECT\nTO INTERNET", 3)
                menu_state = "default"

        elif command == 'update_satellite_beta':
            logging.info("Triggering Satellite beta update via web")
            if is_connected():
                show_message("UPDATING\nSATELLITE BETA", 2)
                updating_application = True
                execute_command_with_progress('sudo satellite-update beta')
                updating_application = False
                show_message("UPDATE COMPLETE", 2)
            else:
                show_message("PLEASE CONNECT\nTO INTERNET", 3)
                menu_state = "default"

        elif command == 'update_companion_version':
            version = params.get('version', '')
            logging.info(f"Triggering Companion update to specific version: {version}")
            if is_connected() and version:
                show_message(f"UPDATING\nCOMPANION\n{version}", 2)
                updating_application = True
                execute_command_with_progress(build_versioned_update_command('companion', version))
                updating_application = False
                show_message("UPDATE COMPLETE", 2)
            else:
                show_message("PLEASE CONNECT\nTO INTERNET", 3)
                menu_state = "default"

        elif command == 'update_satellite_version':
            version = params.get('version', '')
            logging.info(f"Triggering Satellite update to specific version: {version}")
            if is_connected() and version:
                show_message(f"UPDATING\nSATELLITE\n{version}", 2)
                updating_application = True
                execute_command_with_progress(build_versioned_update_command('satellite', version))
                updating_application = False
                show_message("UPDATE COMPLETE", 2)
            else:
                show_message("PLEASE CONNECT\nTO INTERNET", 3)
                menu_state = "default"

    except Exception as e:
        logging.error(f"Error executing web command: {e}")


web_command_file = "web_command.json"
trigger_file = "trigger_command"

web_command_file = "web_command.json"
trigger_file = "trigger_command"

def process_web_commands():
    """Process commands from the web GUI"""
    global menu_state, menu_selection, ip_address, subnet_mask, gateway, time_format_24hr

    while True:
        try:
            # Check if there's a trigger file
            if os.path.exists(trigger_file):
                os.remove(trigger_file)  # Remove trigger

                # Check for command file
                if os.path.exists(web_command_file):
                    with open(web_command_file, 'r') as f:
                        cmd_data = json.load(f)

                    command = cmd_data.get('command')
                    params = cmd_data.get('params', {})

                    logging.info(f"Processing web command: {command}")

                    # Process different commands
                    if command == 'toggle_service':
                        service = params.get('service')
                        if service in ['companion', 'satellite']:
                            toggle_service(service)
                            logging.info(f"Toggled to {service} via web")

                    elif command == 'toggle_network':
                        network = params.get('network')
                        if network in ['DHCP', 'STATIC']:
                            toggle_network(network)
                            logging.info(f"Toggled to {network} via web")

                    elif command == 'set_static_ip':
                        # Parse IP settings
                        ip_str = params.get('ip', '192.168.0.100')
                        subnet_str = params.get('subnet', '255.255.255.0')
                        gateway_str = params.get('gateway', '192.168.0.1')
                        dns_str = params.get('dns', gateway_str)  # Default to gateway if not provided

                        # Convert to lists
                        ip_address = [int(x) for x in ip_str.split('.')]
                        subnet_mask = [int(x) for x in subnet_str.split('.')]
                        gateway = [int(x) for x in gateway_str.split('.')]

                        save_static_settings()
                        apply_static_settings(dns_str)
                        # Also update network mode to STATIC in state
                        state = load_state()
                        state["network"] = "STATIC"
                        save_state(state)
                        logging.info(f"Applied static IP settings via web with DNS: {dns_str}")

                    elif command == 'power':
                        action = params.get('action')
                        if action == 'reboot':
                            logging.info("Rebooting system via web command")
                            turn_off_oled()
                            execute_command("sudo reboot")
                        elif action == 'shutdown':
                            logging.info("Shutting down system via web command")
                            turn_off_oled()
                            execute_command("sudo shutdown now")

                    elif command == 'update_omnicon':
                        version = params.get('version')
                        if version:
                            logging.info(f"Starting Omnicon update to version {version} via web")
                            # Perform the update
                            result = perform_update(version)
                            logging.info(f"Update result: {result}")
                        else:
                            logging.error("No version specified for update")

                    elif command == 'button_press':
                        button = params.get('button')
                        logging.info(f"Simulating {button} press via web")
                        # Reset interaction time to prevent timeout
                        global last_interaction_time
                        last_interaction_time = time.monotonic()

                        # Simulate button press
                        if button == 'K1':
                            button_k1_pressed()
                        elif button == 'K2':
                            button_k2_pressed()
                        elif button == 'K3':
                            button_k3_pressed()
                        elif button == 'K4':
                            button_k4_pressed()

                        # Force display update
                        update_oled_display()

                    elif command == 'set_datetime':
                        # Handle date/time setting
                        if 'date' in params and 'time' in params:
                            datetime_str = f"{params['date']} {params['time']}"
                            execute_command(f"sudo timedatectl set-ntp false")
                            execute_command(f"sudo timedatectl set-time '{datetime_str}'")
                            logging.info(f"Set date/time to {datetime_str} via web")

                        if 'format_24hr' in params:
                            time_format_24hr = params['format_24hr']
                            state = load_state()
                            state['time_format_24hr'] = time_format_24hr
                            save_state(state)
                            update_clock_format(time_format_24hr)
                            logging.info(f"Set time format to {'24hr' if time_format_24hr else '12hr'} via web")

                    elif command == 'menu_navigate':
                        # Direct menu navigation
                        target_menu = params.get('menu')
                        if target_menu:
                            menu_state = target_menu
                            menu_selection = 0
                            update_oled_display()
                            logging.info(f"Navigated to {target_menu} menu via web")

                    elif command == 'update_companion_stable':
                        # Trigger companion update through OLED menu system
                        logging.info("Triggering Companion stable update via web")
                        if is_connected():
                            show_message("UPDATING\nCOMPANION", 2)
                            global updating_application
                            updating_application = True
                            execute_command_with_progress('sudo companion-update stable')
                            updating_application = False
                            show_message("UPDATE COMPLETE", 2)
                        else:
                            show_message("PLEASE CONNECT\nTO INTERNET", 3)

                    elif command == 'update_satellite_stable':
                        # Trigger satellite update through OLED menu system
                        logging.info("Triggering Satellite stable update via web")
                        if is_connected():
                            show_message("UPDATING\nSATELLITE", 2)
                            updating_application = True
                            execute_command_with_progress('sudo satellite-update stable')
                            updating_application = False
                            show_message("UPDATE COMPLETE", 2)
                        else:
                            show_message("PLEASE CONNECT\nTO INTERNET", 3)

                    elif command == 'update_companion_beta':
                        logging.info("Triggering Companion beta update via web")
                        if is_connected():
                            show_message("UPDATING\nCOMPANION BETA", 2)
                            updating_application = True
                            execute_command_with_progress('sudo companion-update beta')
                            updating_application = False
                            show_message("UPDATE COMPLETE", 2)
                        else:
                            show_message("PLEASE CONNECT\nTO INTERNET", 3)

                    elif command == 'update_satellite_beta':
                        logging.info("Triggering Satellite beta update via web")
                        if is_connected():
                            show_message("UPDATING\nSATELLITE BETA", 2)
                            updating_application = True
                            execute_command_with_progress('sudo satellite-update beta')
                            updating_application = False
                            show_message("UPDATE COMPLETE", 2)
                        else:
                            show_message("PLEASE CONNECT\nTO INTERNET", 3)

                    elif command == 'update_companion_version':
                        version = params.get('version', '')
                        logging.info(f"Triggering Companion update to version: {version}")
                        if is_connected() and version:
                            show_message(f"UPDATING\nCOMPANION\n{version}", 2)
                            updating_application = True
                            execute_command_with_progress(build_versioned_update_command('companion', version))
                            updating_application = False
                            show_message("UPDATE COMPLETE", 2)
                        else:
                            show_message("PLEASE CONNECT\nTO INTERNET", 3)

                    elif command == 'update_satellite_version':
                        version = params.get('version', '')
                        logging.info(f"Triggering Satellite update to version: {version}")
                        if is_connected() and version:
                            show_message(f"UPDATING\nSATELLITE\n{version}", 2)
                            updating_application = True
                            execute_command_with_progress(build_versioned_update_command('satellite', version))
                            updating_application = False
                            show_message("UPDATE COMPLETE", 2)
                        else:
                            show_message("PLEASE CONNECT\nTO INTERNET", 3)

                    # Remove command file after processing
                    os.remove(web_command_file)

        except Exception as e:
            logging.error(f"Error processing web command: {e}")

        # Check every 0.5 seconds for new commands
        time.sleep(0.5)


# ============================================================================
# FLIGHT RECORDER - persistent system-health log for diagnosing freezes.
# Samples vitals every 30s to a small rotating file that survives a hard
# crash/reboot. After a freeze, the tail of this file shows what the system
# looked like in its final moments (memory climbing, swap thrash, D-state
# pileup, temperature, throttling, etc).
# ============================================================================
DIAG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'diagnostics')
FLIGHT_RECORDER_FILE = os.path.join(DIAG_DIR, 'flight_recorder.jsonl')
FLIGHT_RECORDER_INTERVAL = 30           # seconds between samples
FLIGHT_RECORDER_MAX_BYTES = 512 * 1024  # rotate at 512KB, keep one old file


def _flight_throttled():
    """Read undervoltage/throttle flags (0x0 = healthy)."""
    try:
        out = subprocess.run(['vcgencmd', 'get_throttled'],
                             capture_output=True, text=True, timeout=5).stdout
        return out.strip().split('=')[1] if '=' in out else None
    except Exception:
        return None


def _flight_cpu_temp():
    try:
        with open('/sys/class/thermal/thermal_zone0/temp') as f:
            return round(int(f.read().strip()) / 1000.0, 1)
    except Exception:
        return None


def take_flight_sample():
    """Collect one vitals sample. Reads /proc directly via psutil - no shell-outs
    except a single vcgencmd for throttle flags."""
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage('/')

    # One pass over all processes: top consumers by RSS + D-state count.
    # D-state (uninterruptible I/O sleep) processes piling up is the classic
    # signature of a dying/stalling SD card.
    top, d_state, total_procs = [], 0, 0
    for p in psutil.process_iter(['pid', 'name', 'memory_info', 'status']):
        try:
            total_procs += 1
            if p.info['status'] == psutil.STATUS_DISK_SLEEP:
                d_state += 1
            rss = p.info['memory_info'].rss if p.info['memory_info'] else 0
            top.append((rss, p.info['pid'], p.info['name']))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    top.sort(reverse=True)

    me = psutil.Process()
    sample = {
        'ts': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'uptime_s': int(time.time() - psutil.boot_time()),
        'load': [round(x, 2) for x in os.getloadavg()],
        'cpu_pct': psutil.cpu_percent(interval=None),
        'mem_avail_mb': mem.available // (1024 * 1024),
        'mem_pct': mem.percent,
        'swap_used_mb': swap.used // (1024 * 1024),
        'swap_pct': swap.percent,
        'disk_free_mb': disk.free // (1024 * 1024),
        'temp_c': _flight_cpu_temp(),
        'throttled': _flight_throttled(),
        'procs': total_procs,
        'd_state': d_state,
        'self_threads': me.num_threads(),
        'self_fds': me.num_fds(),
        'top_rss': [{'mb': r // (1024 * 1024), 'pid': pid, 'n': name}
                    for r, pid, name in top[:6]],
    }
    return sample


def flight_recorder_loop():
    """Daemon thread: append one JSON line per sample, fsync so it survives a
    hard freeze, rotate to keep size bounded. Must never crash omnicon."""
    last_error_log = 0
    os.makedirs(DIAG_DIR, exist_ok=True)
    logging.info(f"Flight recorder started ({FLIGHT_RECORDER_INTERVAL}s interval -> {FLIGHT_RECORDER_FILE})")
    while True:
        try:
            sample = take_flight_sample()
            line = json.dumps(sample, separators=(',', ':')) + '\n'
            with open(FLIGHT_RECORDER_FILE, 'a') as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
            if os.path.getsize(FLIGHT_RECORDER_FILE) > FLIGHT_RECORDER_MAX_BYTES:
                os.replace(FLIGHT_RECORDER_FILE, FLIGHT_RECORDER_FILE + '.1')
        except Exception as e:
            # Log at most once per 10 minutes so a persistent failure
            # (e.g. disk full) can't flood the journal
            if time.monotonic() - last_error_log > 600:
                last_error_log = time.monotonic()
                logging.error(f"Flight recorder error: {e}")
        time.sleep(FLIGHT_RECORDER_INTERVAL)


def ensure_journald_config():
    """Make the systemd journal persistent (survives reboot) and size-capped
    (protects the SD card). Without this, the journal from before a freeze is
    lost on reboot - which is exactly the data we need. Idempotent: only
    writes and restarts journald when the config actually changes."""
    conf_path = '/etc/systemd/journald.conf.d/omnicon.conf'
    desired = (
        "# Written by Omnicon - persistent boot-surviving logs with bounded size\n"
        "[Journal]\n"
        "Storage=persistent\n"
        "SystemMaxUse=256M\n"
        "SystemKeepFree=512M\n"
        "MaxRetentionSec=14day\n"
    )
    try:
        try:
            with open(conf_path, 'r') as f:
                if f.read() == desired:
                    return
        except FileNotFoundError:
            pass
        subprocess.run(['sudo', 'mkdir', '-p', '/etc/systemd/journald.conf.d'],
                       capture_output=True)
        result = subprocess.run(['sudo', 'tee', conf_path], input=desired,
                                capture_output=True, text=True)
        if result.returncode != 0:
            logging.error(f"Failed to write journald config: {result.stderr}")
            return
        subprocess.run(['sudo', 'systemctl', 'restart', 'systemd-journald'],
                       capture_output=True)
        logging.info("Journald configured: persistent storage, 256M cap")
    except Exception as e:
        logging.error(f"Failed to configure journald: {e}")


def disable_os_auto_upgrades():
    """Disable Debian's automatic/unattended OS package upgrades.

    The systemd apt-daily timers run unattended-upgrades in the early morning.
    On a memory-constrained appliance an upgrade run was observed ballooning to
    ~2.5GB RAM, exhausting the Pi and freezing the ENTIRE system (OLED, web GUI,
    Companion) in a swap death-spiral until a manual power cycle - the reported
    "freezes every morning" bug.

    An appliance should update on a controlled schedule (OMNICON's own OTA
    updater plus companion-update / satellite-update), not via blind unattended
    OS upgrades. This masks the timers and tells apt's periodic machinery to do
    nothing. It does NOT remove apt: manual `apt upgrade` and every
    OMNICON/Companion/Satellite update path keep working. Idempotent and safe to
    run on every boot - it only acts when something isn't already disabled, so
    it also self-heals any field unit on the next OMNICON update.
    """
    timers = ['apt-daily.timer', 'apt-daily-upgrade.timer']
    try:
        # Mask (and stop) any timer that isn't already masked.
        to_mask = []
        for t in timers:
            try:
                state = subprocess.run(['systemctl', 'is-enabled', t],
                                       capture_output=True, text=True, timeout=5).stdout.strip()
            except Exception:
                state = ''
            if state != 'masked':
                to_mask.append(t)
        if to_mask:
            # Stop BEFORE masking (masking first makes the stop fail and leaves
            # the unit in a cosmetic "failed" state), then mask so nothing can
            # re-enable it. reset-failed clears any prior residue.
            subprocess.run(['sudo', 'systemctl', 'stop'] + to_mask, capture_output=True, timeout=20)
            subprocess.run(['sudo', 'systemctl', 'mask'] + to_mask, capture_output=True, timeout=20)
            subprocess.run(['sudo', 'systemctl', 'reset-failed'] + to_mask, capture_output=True, timeout=10)
            logging.info(f"Disabled OS auto-upgrade timers: {', '.join(to_mask)}")

        # Belt-and-suspenders: even a manually-triggered periodic run installs
        # nothing with these all set to "0".
        conf_path = '/etc/apt/apt.conf.d/20auto-upgrades'
        desired = (
            '// Written by Omnicon - automatic OS upgrades disabled on appliance\n'
            'APT::Periodic::Update-Package-Lists "0";\n'
            'APT::Periodic::Unattended-Upgrade "0";\n'
            'APT::Periodic::Download-Upgradeable-Packages "0";\n'
            'APT::Periodic::AutocleanInterval "0";\n'
        )
        try:
            with open(conf_path, 'r') as f:
                current = f.read()
        except FileNotFoundError:
            current = None
        if current != desired:
            result = subprocess.run(['sudo', 'tee', conf_path], input=desired,
                                    capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                logging.info("Disabled apt periodic auto-upgrade config")
            else:
                logging.error(f"Failed to write {conf_path}: {result.stderr}")
    except Exception as e:
        logging.error(f"Failed to disable OS auto-upgrades: {e}")


# ============================================================================
# SATELLITE fnm SELF-HEAL
# `companion-update` (Bitfocus CompanionPi) runs `rm -rf /opt/fnm` because modern
# Companion bundles its own Node. But Companion Satellite - co-installed on this
# OMNICON image - needs /opt/fnm to RUN (satellite.service execs the Node there)
# and to UPDATE. So every Companion update silently breaks Satellite. This module
# detects a missing /opt/fnm and rebuilds it, offline-first from a local cache,
# so a unit self-heals without the user doing anything.
# ============================================================================
FNM_VERSION = 'v1.38.1'
FNM_URL = f'https://github.com/Schniz/fnm/releases/download/{FNM_VERSION}/fnm-arm64.zip'
SATELLITE_SRC = '/usr/local/src/companion-satellite'
FNM_DIR = '/opt/fnm'
FNM_BIN = '/opt/fnm/fnm'
FNM_DEFAULT_NODE = '/opt/fnm/aliases/default/bin/node'
FNM_CACHE = '/home/omnicon/.fnm-cache'  # companion-update never touches /home


def satellite_installed():
    return os.path.isdir(SATELLITE_SRC)


def fnm_healthy():
    """True when both the fnm binary and a usable default Node are present."""
    return os.path.exists(FNM_BIN) and os.path.exists(FNM_DEFAULT_NODE)


def _fnm_reconcile():
    """Run satellite's own non-interactive fnm setup (mirrors pi-image/update.sh
    lines 19-27): install the pinned Node if missing and (re)point the default
    alias. Offline-safe when the Node is already on disk (e.g. after a cache copy)."""
    cmd = (f'set -e; cd "{SATELLITE_SRC}"; export FNM_DIR={FNM_DIR}; export PATH={FNM_DIR}:$PATH; '
           'eval "$(fnm env)"; fnm use --install-if-missing; fnm default "$(fnm current)"')
    subprocess.run(['sudo', 'bash', '-c', cmd], capture_output=True, text=True, timeout=300)


def _cache_node_present():
    """The cache is usable if it has the fnm binary and a real Node install
    (checked via the concrete path, NOT the alias symlink which dangles when
    /opt/fnm is deleted)."""
    import glob
    return (os.path.exists(os.path.join(FNM_CACHE, 'fnm')) and
            bool(glob.glob(os.path.join(FNM_CACHE, 'node-versions/*/installation/bin/node'))))


def refresh_fnm_cache():
    """Snapshot a healthy /opt/fnm to /home/omnicon/.fnm-cache for offline restores.
    Stamped by the current Node target so it's a no-op until the version changes
    (e.g. after a Satellite update), avoiding a needless 200MB copy every boot."""
    try:
        if not fnm_healthy():
            return
        target = os.path.realpath(FNM_DEFAULT_NODE)
        stamp = os.path.join(FNM_CACHE, '.source')
        if _cache_node_present():
            try:
                with open(stamp) as f:
                    if f.read().strip() == target:
                        return  # cache already current
            except OSError:
                pass
        subprocess.run(['sudo', 'rm', '-rf', FNM_CACHE], capture_output=True, timeout=60)
        subprocess.run(['sudo', 'cp', '-a', FNM_DIR, FNM_CACHE], capture_output=True, timeout=180)
        subprocess.run(['sudo', 'bash', '-c', f'echo "{target}" > "{stamp}"'], capture_output=True, timeout=10)
        logging.info(f"fnm cache refreshed ({target})")
    except Exception as e:
        logging.error(f"refresh_fnm_cache failed: {e}")


def _restore_fnm_from_cache():
    """Copy the cached /opt/fnm back into place (offline). Returns True on success."""
    if not _cache_node_present():
        return False
    try:
        subprocess.run(['sudo', 'rm', '-rf', FNM_DIR], capture_output=True, timeout=60)
        subprocess.run(['sudo', 'cp', '-a', FNM_CACHE, FNM_DIR], capture_output=True, timeout=180)
        subprocess.run(['sudo', 'rm', '-f', os.path.join(FNM_DIR, '.source')], capture_output=True, timeout=10)
        _fnm_reconcile()  # fix the default alias; Node already on disk so no download
        return fnm_healthy()
    except Exception as e:
        logging.error(f"_restore_fnm_from_cache failed: {e}")
        return False


def _restore_fnm_by_download():
    """Reinstall the fnm binary + pinned Node from the internet. Returns True on success."""
    try:
        install = ('set -e; mkdir -p /opt/fnm; '
                   f'curl -fsSL "{FNM_URL}" -o /tmp/fnm.zip; cd /tmp && unzip -o fnm.zip; '
                   'install -m 755 fnm /opt/fnm/fnm; rm -f /tmp/fnm.zip /tmp/fnm')
        subprocess.run(['sudo', 'bash', '-c', install], capture_output=True, text=True, timeout=180)
        if not os.path.exists(FNM_BIN):
            return False
        _fnm_reconcile()
        return fnm_healthy()
    except Exception as e:
        logging.error(f"_restore_fnm_by_download failed: {e}")
        return False


def _show_heal_splash(message):
    """Draw a centered splash and KEEP it up (message_displayed stays True) for the
    duration of the heal. Same drawing as show_message() but without the fixed sleep."""
    global message_displayed
    message_displayed = True
    try:
        with oled_lock:
            img = Image.new("1", (oled.width, oled.height))
            d = ImageDraw.Draw(img)
            lines = message.split('\n')

            # Space lines by the font's REAL line height (ascent+descent), not the
            # tight glyph bbox - otherwise multi-line text crowds/overlaps.
            ascent, descent = font12.getmetrics()
            line_h = ascent + descent
            total_h = line_h * len(lines)
            y = (oled.height - total_h) // 2
            for line in lines:
                l, t, r, b = d.textbbox((0, 0), line, font=font12)
                w = r - l
                d.text(((oled.width - w) // 2, y), line, font=font12, fill=255)
                y += line_h
            oled.image(img.rotate(180))
            oled.show()
    except Exception as e:
        logging.error(f"_show_heal_splash failed: {e}")


def _clear_heal_splash():
    """Drop the splash so the normal display resumes on the next loop tick."""
    global message_displayed, update_flag, timeout_flag
    message_displayed = False
    update_flag = True
    timeout_flag = True


def _draw_heal_frame(message, frame):
    """One animated frame of the self-heal splash: the message near the top with a
    sweeping bar at the bottom, so a slow (download) restore never looks frozen."""
    global message_displayed
    message_displayed = True
    try:
        with oled_lock:
            img = Image.new("1", (oled.width, oled.height))
            d = ImageDraw.Draw(img)
            lines = message.split('\n')
            ascent, descent = font12.getmetrics()
            line_h = ascent + descent
            block_h = line_h * len(lines)
            # Reserve ~12px at the bottom for the animated bar
            y = max(0, (oled.height - 12 - block_h) // 2)
            for line in lines:
                l, t, r, b = d.textbbox((0, 0), line, font=font12)
                w = r - l
                d.text(((oled.width - w) // 2, y), line, font=font12, fill=255)
                y += line_h
            track = oled.width - 20
            sweep = 24
            x = (frame * 6) % (track - sweep + 1)
            d.rectangle((10 + x, oled.height - 6, 10 + x + sweep, oled.height - 2),
                        outline=255, fill=255)
            oled.image(img.rotate(180))
            oled.show()
    except Exception as e:
        logging.error(f"_draw_heal_frame failed: {e}")


_fnm_heal_lock = threading.Lock()
_fnm_last_impossible = 0.0  # backoff stamp: broken but offline with no cache

# What the splash says depends on what the USER was doing - satellite wording
# when they chose satellite, neutral wording for background repairs (a
# companion user must never see satellite talk). The post-update heal draws
# nothing here at all: it runs as the FINALIZING stage of the unified update
# screen inside execute_command_with_progress (show_splash=False).
_HEAL_MESSAGES = {
    'switch-to-satellite': ("DO NOT UNPLUG\nPREPARING\nSATELLITE", "SATELLITE NEEDS\nINTERNET"),
}
_HEAL_MESSAGE_DEFAULT = ("DO NOT UNPLUG\nSYSTEM\nMAINTENANCE", None)  # watchdog: fail silently


def ensure_fnm(reason="", show_splash=True):
    """Restore /opt/fnm if a Companion update deleted it. Offline-first (local
    cache), download fallback. No-op (and keeps the cache fresh) when already
    healthy. Serialized so concurrent triggers (boot, watchdog, mode-switch,
    post-update) can't race. With show_splash=False it draws nothing - the
    caller owns the screen (the unified update screen's FINALIZING stage).
    Returns True when /opt/fnm is healthy/restored, False when it could not
    be restored yet."""
    global _fnm_last_impossible
    if not satellite_installed():
        return True  # nothing to maintain on this unit
    if fnm_healthy():
        refresh_fnm_cache()
        return True
    if not _fnm_heal_lock.acquire(blocking=False):
        return True  # another trigger is already healing
    try:
        if fnm_healthy():  # re-check inside the lock
            return True
        splash_msg, fail_msg = _HEAL_MESSAGES.get(reason, _HEAL_MESSAGE_DEFAULT)
        is_background = reason not in _HEAL_MESSAGES and show_splash

        # Can we restore at all? Without a cache AND without internet there is
        # nothing to do - don't flash splashes at the user (the watchdog would
        # otherwise repeat them every 30s on an offline unit).
        if not _cache_node_present() and not is_connected():
            if is_background:
                if time.monotonic() - _fnm_last_impossible > 600:
                    _fnm_last_impossible = time.monotonic()
                    logging.warning("ensure_fnm: broken but no cache and offline - waiting for internet")
            else:
                logging.warning(f"ensure_fnm: cannot restore ({reason}) - no cache and offline")
                if show_splash and fail_msg:
                    _show_heal_splash(fail_msg)
                    time.sleep(3)
                    _clear_heal_splash()
            return False

        logging.warning(f"ensure_fnm: /opt/fnm missing - restoring ({reason})")
        # Run the restore in a thread so the splash can ANIMATE while it works.
        # A cache restore is a couple seconds, but a first-time download can take
        # ~a minute - the sweeping bar shows it's alive the whole time.
        result = {'done': False, 'ok': False}

        def _do_restore():
            try:
                if _restore_fnm_from_cache():
                    logging.info("ensure_fnm: restored from local cache (offline-safe)")
                    result['ok'] = True
                elif is_connected() and _restore_fnm_by_download():
                    logging.info("ensure_fnm: restored by download")
                    refresh_fnm_cache()  # seed the cache now that we're healthy
                    result['ok'] = True
            except Exception as e:
                logging.error(f"ensure_fnm restore error: {e}")
            finally:
                result['done'] = True

        try:
            if show_splash:
                _draw_heal_frame(splash_msg, 0)  # show at once
            threading.Thread(target=_do_restore, daemon=True).start()
            frame = 1
            while not result['done']:
                if show_splash:
                    _draw_heal_frame(splash_msg, frame)
                    frame += 1
                time.sleep(0.2)

            if result['ok']:
                # No success splash - the update flow follows with
                # "UPDATE COMPLETE", and background heals just return to normal.
                if load_state().get('service') == 'satellite':
                    subprocess.run(['sudo', 'systemctl', 'restart', 'satellite'],
                                   capture_output=True, timeout=30)
                    logging.info("ensure_fnm: restarted satellite.service after restore")
            else:
                logging.warning(f"ensure_fnm: restore attempt failed ({reason}) - will retry")
                if show_splash and fail_msg:
                    _show_heal_splash(fail_msg)
                    time.sleep(3)
            return result['ok']
        finally:
            if show_splash:
                _clear_heal_splash()
    finally:
        _fnm_heal_lock.release()


def _update_in_progress():
    """True while a Companion/Satellite/apt update is actively running, so the
    watchdog defers instead of racing the updater's own file operations."""
    try:
        if updating_application:
            return True
        out = subprocess.run(['pgrep', '-f', r'companion-update|satellite-update|update\.sh|apt-get|dpkg'],
                             capture_output=True, text=True, timeout=5).stdout
        return bool(out.strip())
    except Exception:
        return False


def fnm_watchdog_loop():
    """Every-30s guardian, no-op when all is well. Two duties:
    1. fnm self-heal: rebuild /opt/fnm whenever it's missing - regardless of
       how it was deleted (Companion update via any path, corruption, etc.).
       Also keeps the offline restore cache fresh.
    2. Single-app invariant: if Companion AND Satellite are ever active at the
       same time (e.g. a manual `sudo companion-update` over SSH while in
       Satellite mode), stop the one state.json doesn't name.
    Both duties defer while an update is actively running, since updaters
    legitimately cycle services mid-run."""
    logging.info("fnm watchdog started (30s)")
    while True:
        try:
            if satellite_installed():
                if _update_in_progress():
                    pass  # let the updater finish; next tick cleans up
                elif not fnm_healthy():
                    ensure_fnm(reason="watchdog")
                else:
                    refresh_fnm_cache()
                    enforce_single_app_service()
        except Exception as e:
            logging.error(f"fnm_watchdog error: {e}")
        time.sleep(30)


def main():
    global datetime_temp, time_format_24hr
    initial_setup()
    datetime_temp = get_system_time()

    state = load_state()
    time_format_24hr = state.get("time_format_24hr", True)

    button_k1.when_pressed = button_k1_pressed
    button_k2.when_pressed = button_k2_pressed
    button_k3.when_pressed = button_k3_pressed
    button_k4.when_pressed = button_k4_pressed

    button_k1.when_held = lambda: fast_adjust_ip(10)
    button_k2.when_held = lambda: fast_adjust_ip(-10)

    button_k3.when_held = hold_k3
    button_k4.when_held = hold_k4

    update_oled_thread = threading.Thread(target=update_oled)
    update_oled_thread.daemon = True
    update_oled_thread.start()
    # Start web command processor thread
    web_command_thread = threading.Thread(target=process_web_commands, daemon=True)
    web_command_thread.start()
    logging.info("Web command processor started")

    # Persistent journald + flight recorder for freeze diagnosis
    ensure_journald_config()
    threading.Thread(target=flight_recorder_loop, daemon=True).start()

    # Stop Debian's unattended OS upgrades - the cause of the morning freezes
    disable_os_auto_upgrades()

    # Self-heal Satellite's fnm runtime if a Companion update deleted it.
    # Watchdog thread: checks on start + every 30s, offline-first restore.
    threading.Thread(target=fnm_watchdog_loop, daemon=True).start()

    # Start web command processor thread

    # Start web command processor thread


    logging.info('Script started successfully')

    # Auto-expand root filesystem if partition is much smaller than SD card
    # This runs every boot but only takes action if expansion is needed.
    # The size check is instant and raspi-config --expand-rootfs is a no-op
    # on an already-expanded disk, so this is safe to run repeatedly.
    try:
        # Get total SD card size in bytes
        with open('/sys/block/mmcblk0/size', 'r') as f:
            card_sectors = int(f.read().strip())
        card_size_gb = (card_sectors * 512) / (1024 ** 3)

        # Get root partition size in bytes
        with open('/sys/block/mmcblk0/mmcblk0p2/size', 'r') as f:
            part_sectors = int(f.read().strip())
        part_size_gb = (part_sectors * 512) / (1024 ** 3)

        logging.info(f"Disk check: SD card={card_size_gb:.1f}GB, root partition={part_size_gb:.1f}GB")

        # If the partition uses less than 80% of the card, expand it
        if card_size_gb > 0 and (part_size_gb / card_size_gb) < 0.80:
            logging.warning(f"Root partition ({part_size_gb:.1f}GB) is much smaller than SD card ({card_size_gb:.1f}GB) - auto-expanding")
            show_message("EXPANDING\nDISK...", 3)
            result = subprocess.run(["sudo", "raspi-config", "--expand-rootfs"],
                                    capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                logging.info("Filesystem expand successful, rebooting to apply")
                show_message("DISK EXPANDED\nREBOOTING...", 3)
                turn_off_oled()
                execute_command("sudo reboot")
            else:
                logging.error(f"Filesystem expand failed: {result.stderr}")
        else:
            logging.info("Disk size OK, no expansion needed")
    except Exception as e:
        logging.error(f"Disk expansion check failed: {e}")

    timeout_thread = threading.Thread(target=check_timeout)
    timeout_thread.daemon = True
    timeout_thread.start()

    # Start the fullscreen kiosk GUI (if display is available)
    start_kiosk()

    # Main heartbeat loop. Guarded like every other loop in the app: an
    # unexpected error is logged and survived instead of killing the main
    # thread (which would exit the whole app and blank the OLED/kiosk until
    # systemd restarts it).
    while True:
        try:
            execute_web_commands()
        except Exception as e:
            logging.error(f"Error in main web-command loop: {e}")
        time.sleep(.1)  # Check every 100ms

def fast_adjust_ip(increment):
    global menu_state, ip_octet, ip_address, subnet_mask, gateway, datetime_temp
    if menu_state == "set_static_ip":
        ip_address[ip_octet] = (ip_address[ip_octet] + increment) % 256
    elif menu_state == "set_static_sm":
        subnet_mask[ip_octet] = (subnet_mask[ip_octet] + increment) % 256
    elif menu_state == "set_static_gw":
        gateway[ip_octet] = (gateway[ip_octet] + increment) % 256
    elif menu_state == "set_date":
        update_date(increment)
    elif menu_state == "set_time":
        update_time(increment)
    update_oled_display()
    time.sleep(.6)  # Reduce sleep time to make the changes more responsive

def check_timeout():
    global last_interaction_time, menu_state
    while True:
        # Use monotonic time for timeout check (not affected by system time changes)
        elapsed = time.monotonic() - last_interaction_time
        # Use 30 second timeout for network stats screens, 20 seconds for other menus
        if menu_state in ["show_lan_stats", "show_wifi_stats"]:
            timeout_seconds = 30
        else:
            timeout_seconds = 20
        if elapsed > timeout_seconds:
            reset_to_main()
        time.sleep(1)

def activate_menu_item():
    global menu_state, menu_selection, updating_application, ip_octet, ip_address, subnet_mask, gateway, original_ip_address, original_subnet_mask, original_gateway, last_interaction_time, timeout_flag, datetime_temp, available_versions, selected_version
    global app_version_list, app_version_scroll, app_version_cursor, app_version_target
    options = menu_options.get(menu_state, [])
    selected_option = options[menu_selection]

    if menu_state == "main":
        if selected_option == "APPLICATION":
            menu_state = "application"
            menu_selection = 0
        elif selected_option == "CONFIGURATION":
            menu_state = "configuration"
            menu_selection = 0
        elif selected_option == "POWER":
            menu_state = "power"
            menu_selection = 0
        elif selected_option == "EXIT":
            menu_state = "default"
            menu_selection = 0

    elif menu_state == "application":
        if selected_option.startswith("Companion"):
            toggle_service("companion")
            menu_state = "default"
        elif selected_option.startswith("Satellite"):
            toggle_service("satellite")
            menu_state = "default"
        elif selected_option == "APP UPDATER":
            menu_state = "app_updates"
            menu_selection = 0
        elif selected_option == "EXIT":
            menu_state = "default"
            menu_selection = 0

    elif menu_state == "configuration":
        if selected_option == "NETWORK":
            menu_state = "network"
            menu_selection = 0
        elif selected_option == "SET DATE/TIME":
            menu_state = "set_datetime"
            menu_selection = 0
            datetime_temp = get_system_time()
        elif selected_option == "UPDATE":
            menu_state = "update"
            menu_selection = 0
        elif selected_option == "EXIT":
            menu_state = "default"

    elif menu_state == "network":
        if selected_option == "DHCP":
            toggle_network("DHCP")
            menu_state = "default"
        elif selected_option == "STATIC IP":
            toggle_network("STATIC")
            menu_state = "default"
        elif selected_option == "SET STATIC":
            menu_state = "set_static"
            menu_selection = 0
        elif selected_option == "EXIT":
            ip_address = original_ip_address[:]
            subnet_mask = original_subnet_mask[:]
            gateway = original_gateway[:]
            menu_state = "default"
            menu_selection = 0

    elif menu_state == "power":
        if selected_option == "REBOOT":
            menu_state = "reboot_confirm"
            menu_selection = 0
        elif selected_option == "SHUTDOWN":
            menu_state = "shutdown_confirm"
            menu_selection = 0
        elif selected_option == "EXIT":
            menu_state = "default"

    elif menu_state == "reboot_confirm":
        if selected_option == "REBOOT":
            turn_off_oled()
            execute_command("sudo reboot")
        elif selected_option == "CANCEL":
            menu_state = "power"
            menu_selection = 0

    elif menu_state == "shutdown_confirm":
        if selected_option == "SHUTDOWN":
            turn_off_oled()
            execute_command("sudo shutdown now")
        elif selected_option == "CANCEL":
            menu_state = "power"
            menu_selection = 0

    elif menu_state == "set_static":
        if selected_option == "IP ADDRESS":
            menu_state = "set_static_ip"
            ip_octet = 0
        elif selected_option == "SUBNET MASK":
            menu_state = "set_static_sm"
            ip_octet = 0
        elif selected_option == "GATEWAY":
            menu_state = "set_static_gw"
            ip_octet = 0
        elif selected_option == "EXIT":
            ip_address = original_ip_address[:]
            subnet_mask = original_subnet_mask[:]
            gateway = original_gateway[:]
            menu_state = "default"
            menu_selection = 0

    elif menu_state == "set_datetime":
        if selected_option == "SET DATE":
            menu_state = "set_date"
            ip_octet = 0
        elif selected_option == "SET TIME":
            menu_state = "set_time"
            ip_octet = 0
        elif selected_option == "EXIT":
            menu_state = "default"
            menu_selection = 0

    elif menu_state == "app_updates":
        if selected_option == "COMPANION":
            menu_state = "update_companion"
            menu_selection = 0
        elif selected_option == "SATELLITE":
            menu_state = "update_satellite"
            menu_selection = 0
        elif selected_option == "EXIT":
            menu_state = "application"
            menu_selection = 0

    elif menu_state == "update_companion":
        if selected_option == "LATEST STABLE":
            if is_connected():
                show_message("UPDATING\nCOMPANION", 2)
                updating_application = True
                execute_command_with_progress('sudo companion-update stable')
                updating_application = False
                show_message("UPDATE COMPLETE", 2)
            else:
                show_message("PLEASE CONNECT\nTO INTERNET", 3)
                menu_state = "default"
        elif selected_option == "SPECIFIC STABLE":
            if is_connected():
                show_message("FETCHING\nVERSIONS...", 1)
                app_version_list = fetch_bitfocus_versions("companion")
                app_version_scroll = 0
                app_version_cursor = 0
                app_version_target = "companion"
                if app_version_list:
                    menu_state = "pick_companion_version"
                else:
                    show_message("NO VERSIONS\nFOUND", 2)
            else:
                show_message("PLEASE CONNECT\nTO INTERNET", 3)
                menu_state = "default"
        elif selected_option == "CANCEL":
            menu_state = "app_updates"
            menu_selection = 0

    elif menu_state == "update_satellite":
        if selected_option == "LATEST STABLE":
            if is_connected():
                show_message("UPDATING\nSATELLITE", 2)
                updating_application = True
                execute_command_with_progress('sudo satellite-update stable')
                updating_application = False
                show_message("UPDATE COMPLETE", 2)
            else:
                show_message("PLEASE CONNECT\nTO INTERNET", 3)
                menu_state = "default"
        elif selected_option == "SPECIFIC STABLE":
            if is_connected():
                show_message("FETCHING\nVERSIONS...", 1)
                app_version_list = fetch_bitfocus_versions("companion-satellite")
                app_version_scroll = 0
                app_version_cursor = 0
                app_version_target = "satellite"
                if app_version_list:
                    menu_state = "pick_satellite_version"
                else:
                    show_message("NO VERSIONS\nFOUND", 2)
            else:
                show_message("PLEASE CONNECT\nTO INTERNET", 3)
                menu_state = "default"
        elif selected_option == "CANCEL":
            menu_state = "app_updates"
            menu_selection = 0


    elif menu_state == "update":
        if selected_option == "UPDATE":
            result = update_omnicon()
            if result == "YOU'RE UP TO DATE":
                duration = 3  # Display for 3 seconds
                show_message(result, duration)
                menu_state = "default"
            elif result == "PLEASE CONNECT\nTO INTERNET":
                duration = 3
                show_message(result, duration)
                menu_state = "default"
            elif result == "UPDATE CHECK\nFAILED":
                duration = 3
                show_message(result, duration)
                menu_state = "default"
            else:
                menu_state = "update_confirm"
        elif selected_option == "DOWNGRADE":
            result = downgrade_omnicon()
            if result == "NO OLDER VERSIONS":
                duration = 3  # Display for 3 seconds
                show_message(result, duration)
                menu_state = "default"
            elif result == "PLEASE CONNECT\nTO INTERNET":
                duration = 3
                show_message(result, duration)
                menu_state = "default"
            elif result == "UPDATE CHECK\nFAILED":
                duration = 3
                show_message(result, duration)
                menu_state = "default"
            else:
                menu_state = "downgrade_confirm"
        elif selected_option == "EXIT":
            menu_state = "default"
            menu_selection = 0

    logging.debug(f"Activated menu item: {selected_option}")
    update_oled_display()

def show_message(message, duration):
    global timeout_flag, message_displayed
    message_displayed = True
    clear_display()
    with oled_lock:
        local_image = Image.new("1", (oled.width, oled.height))
        local_draw = ImageDraw.Draw(local_image)
        # Split message into lines
        lines = message.split('\n')
        font = font12
        # Calculate the total height of the text
        total_height = sum([local_draw.textsize(line, font=font)[1] for line in lines])
        # Starting y position
        y = (oled.height - total_height) // 2
        for line in lines:
            line_width, line_height = local_draw.textsize(line, font=font)
            x = (oled.width - line_width) // 2
            local_draw.text((x, y), line, font=font, fill=255)
            y += line_height
        oled.image(local_image.rotate(180))
        oled.show()
    time.sleep(duration)
    message_displayed = False
    timeout_flag = True


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.info('Script interrupted by user.')
