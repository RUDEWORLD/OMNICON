# CREATED BY PHILLIP RUDE
# FOR OMNICON DUO PI, MONO PI, & HUB
# V4.2.9
# 11/25/2024
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
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(message)s')

# Helper function to get system time with fresh timezone
def get_system_time():
    """Get the current system time, forcing a fresh read of timezone info"""
    try:
        # Force timezone reload by resetting the environment
        if 'TZ' in os.environ:
            del os.environ['TZ']
        time.tzset()

        # Use subprocess to get the actual system time
        result = subprocess.run(['date', '+%Y-%m-%d %H:%M:%S %z'],
                              capture_output=True, text=True, check=True)
        date_str = result.stdout.strip()

        # Parse the date string and create a datetime object
        # Format: YYYY-MM-DD HH:MM:SS +ZZZZ
        parts = date_str.split()
        date_part = parts[0]
        time_part = parts[1]

        # Create a datetime from the parsed values
        year, month, day = map(int, date_part.split('-'))
        hour, minute, second = map(int, time_part.split(':'))

        # Return a datetime-like object with strftime method
        from datetime import datetime as dt
        return dt(year, month, day, hour, minute, second)
    except Exception as e:
        logging.warning(f"Failed to get system time via subprocess: {e}")
        # Fallback to regular datetime but try to reload timezone
        time.tzset()
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
    try:
        # Try to connect to a known server (Google DNS)
        socket.create_connection(("8.8.8.8", 53), timeout=2)
        return True
    except OSError:
        pass
    return False


# Function to save state to file
def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

# Function to execute a command
def execute_command(command):
    subprocess.run(command, shell=True)

# Function to check if a service is active
def is_service_active(service_name):
    result = subprocess.run(["systemctl", "is-active", service_name], capture_output=True, text=True)
    return result.stdout.strip() == "active"

# Function to get active network connection
def get_active_connection():
    result = subprocess.run(["nmcli", "-t", "-f", "ACTIVE,NAME", "connection", "show", "--active"], capture_output=True, text=True)
    for line in result.stdout.splitlines():
        active, name = line.split(':')
        if active == "yes":
            return name
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

def toggle_service(service=None):
    state = load_state()
    if service:
        state["service"] = service
    if state["service"] == "companion":
        logging.info('Toggling to Companion service.')
        if is_service_active("satellite.service"):
            execute_command(command_stop_satellite)
        execute_command(command_start_companion)
    else:
        logging.info('Toggling to Satellite service.')
        if is_service_active("companion.service"):
            execute_command(command_stop_companion)
        execute_command(command_start_satellite)
    save_state(state)

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
last_interaction_time = time.time()
timeout_flag = False
update_flag = True
debounce_time = 0.05  # Debounce time for button presses
last_update_time = time.time()  # Initialize the last update time

# Global flag to indicate message display
message_displayed = False

# Menu options
main_menu = ["APPLICATION", "CONFIGURATION", "POWER", "EXIT"]
application_menu = ["RUN COMPANION", "RUN SATELLITE", "UPDATE APPS", "EXIT"]
app_updates_menu = ["UPDATE APP", "COMPANION", "SATELLITE", "EXIT"]
app_update_companion_menu = ["UPDATE COMPANION", "CURRENT STABLE", "", "CANCEL"]
app_update_satellite_menu = ["UPDATE SATELLITE", "CURRENT STABLE", "", "CANCEL"]
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
    "update_companion": ["UPDATE COMPANION", "CURRENT STABLE", "", "CANCEL"],
    "update_satellite": ["UPDATE SATELLITE", "CURRENT STABLE", "", "CANCEL"],

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
    ip = subprocess.check_output(["hostname", "-I"]).decode('utf-8').strip().split()[0]
    subnet = subprocess.check_output(["ip", "-o", "-f", "inet", "addr", "show"]).decode('utf-8')
    subnet = [line.split()[3] for line in subnet.splitlines() if 'eth0' in line]
    subnet = subnet[0].split('/')[1] if subnet else "N/A"
    subnet = cidr_to_subnet_mask(subnet)
    gateway = subprocess.check_output(["ip", "route", "show", "default"]).decode('utf-8').split()[2]
    dns = subprocess.check_output(["nmcli", "dev", "show"]).decode('utf-8')
    dns_servers = [line.split(':')[-1].strip() for line in dns.splitlines() if 'IP4.DNS' in line]
    dns = dns_servers[0] if dns_servers else "N/A"
    return ip, subnet, gateway, dns

# FUNCTION TO UPDATE COMMAND WITH PROGRESS
def execute_command_with_progress(command):
    try:
        process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in iter(process.stdout.readline, ''):
            if line == '':
                break
            logging.debug(f"Command output: {line.strip()}")
            # Parse the line for progress percentage
            progress = parse_progress(line)
            if progress is not None:
                # Update OLED display with progress
                update_oled_with_progress(progress)
        process.stdout.close()
        process.wait()
    except Exception as e:
        logging.error(f"Error executing command with progress: {e}")

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

def get_pi_health():
    temp = subprocess.check_output(["vcgencmd", "measure_temp"]).decode('utf-8').strip().split('=')[1]
    voltage = subprocess.check_output(["vcgencmd", "measure_volts"]).decode('utf-8').strip().split('=')[1].replace('V', '')
    cpu_usage = psutil.cpu_percent(interval=1)  # Using psutil for accurate CPU usage
    memory = subprocess.check_output(["free", "-m"]).decode('utf-8')
    memory = [line for line in memory.split('\n') if "Mem:" in line][0].split()
    memory_used = int(memory[2]) / 1024
    memory_total = int(memory[1]) / 1024
    memory_percentage = (memory_used / memory_total) * 100
    watt_input = float(voltage) * 0.85  # Assuming the current draw is approximately 0.85A
    return temp, voltage, watt_input, cpu_usage, f"{memory_used:.2f}/{memory_total:.2f}GB"

# Function to clear the OLED display before drawing new content
def clear_display():
    logging.debug("Clearing display")
    draw.rectangle((0, 0, oled.width, oled.height), outline=0, fill=0)

# Function to update OLED display
def update_oled_display(force=False):
    global blink_state, gateway, update_flag, last_update_time, datetime_temp, time_format_24hr, message_displayed, selected_version
    global companion_version, satellite_version  # Declare as global to modify them
    current_time = time.time()
    if message_displayed or updating_application:
        return
    # Skip LOOPTIME throttle when force=True (e.g., button presses)
    if not force and (not update_flag or (current_time - last_update_time) < LOOPTIME):
        return
    update_flag = False
    last_update_time = current_time
    logging.debug("Updating OLED display")

    with oled_lock:
        local_image = Image.new("1", (oled.width, oled.height))
        local_draw = ImageDraw.Draw(local_image)

        state = load_state()

        clear_display()

        if menu_state == "default":
            current_time_format = "%H:%M:%S" if time_format_24hr else "%I:%M:%S %p"
            current_time_str = get_system_time().strftime(current_time_format)
            # Shell scripts for system monitoring
            cmd = "hostname -I | cut -d\' \' -f1"
            IP = subprocess.check_output(cmd, shell=True).decode('utf-8').strip()
            cmd = "top -bn1 | grep load | awk '{printf \"CPU: %.2f\", $(NF-2)}'"
            CPU = subprocess.check_output(cmd, shell=True).decode('utf-8').strip()
            cmd = "free -m | awk 'NR==2{printf \"Mem: %s/%sMB %.2f%%\", $3,$2,$3*100/$2 }'"
            MemUsage = subprocess.check_output(cmd, shell=True).decode('utf-8').strip()
            cmd = "df -h | awk '$NF==\"/\"{printf \"Disk: %d/%dGB %s\", $3,$2,$5}'"
            Disk = subprocess.check_output(cmd, shell=True).decode('utf-8').strip()
            cmd = "vcgencmd measure_temp |cut -f 2 -d '='"
            Temp = subprocess.check_output(cmd, shell=True).decode('utf-8').strip()

            # Get the active ethernet connection profile name
            cmd = "nmcli -t -f NAME,DEVICE connection show --active | grep eth | cut -d':' -f1"
            EthProfile = subprocess.check_output(cmd, shell=True).decode('utf-8').strip()

            # Check the status of the services
            companion_active = subprocess.run(["systemctl", "is-active", "--quiet", "companion.service"]).returncode == 0
            satellite_active = subprocess.run(["systemctl", "is-active", "--quiet", "satellite.service"]).returncode == 0

            if companion_active:
                title = "COMPANION"
                port = ":8000"
            elif satellite_active:
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
            local_draw.text((22, 39), f"Omnicon {current_version}", font=font11, fill=255)
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
            time_display = datetime_temp.strftime("%H:%M" if time_format_24hr else "%I:%M")
            am_pm_display = datetime_temp.strftime("%p") if not time_format_24hr else ""

            if blink_state:
                if ip_octet == 0:
                    time_format_display = f"[{time_format_display}]"
                elif ip_octet == 1:
                    time_display = f"[{time_display[:2]}]{time_display[2:]}"
                elif ip_octet == 2:
                    time_display = f"{time_display[:3]}[{time_display[3:]}]"
                elif ip_octet == 3 and not time_format_24hr:
                    am_pm_display = f"[{am_pm_display}]"
            else:
                time_format_display = "24hr" if time_format_24hr else "12hr"
                time_display = datetime_temp.strftime("%H:%M" if time_format_24hr else "%I:%M")
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
        current_time = time.time()
        if current_time - wrapper.last_called >= debounce_time:
            func(*args, **kwargs)
            wrapper.last_called = current_time
    wrapper.last_called = 0
    return wrapper

# Button event handlers with debounce
@debounce
def button_k1_pressed():
    global menu_state, menu_selection, ip_octet, last_interaction_time, timeout_flag, datetime_temp
    logging.debug("K1 pressed")
    last_interaction_time = time.time()
    timeout_flag = False

    if menu_state in ["show_network_info", "show_pi_health"]:
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
    else:
        menu_selection = 0
        activate_menu_item()
    update_oled_display(force=True)

@debounce
def button_k2_pressed():
    global menu_state, menu_selection, ip_octet, last_interaction_time, timeout_flag, datetime_temp
    logging.debug("K2 pressed")
    last_interaction_time = time.time()
    timeout_flag = False

    if menu_state in ["show_network_info", "show_pi_health"]:
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
    else:
        menu_selection = 1
        activate_menu_item()
    update_oled_display(force=True)

@debounce
def button_k3_pressed():
    global menu_state, menu_selection, ip_octet, last_interaction_time, timeout_flag
    logging.debug("K3 pressed")
    last_interaction_time = time.time()
    timeout_flag = False

    if menu_state in ["show_network_info", "show_pi_health"]:
        reset_to_main()
    elif menu_state == "default":
        menu_state = "show_pi_health"
    elif menu_state == "application":
        # Move to the app updates menu when K3 is pressed in application menu
        menu_state = "app_updates"
        menu_selection = 0
    elif menu_state in ["set_static_ip", "set_static_sm", "set_static_gw", "set_date", "set_time"]:
        ip_octet = (ip_octet - 1) % 4  # Corrected to allow all 4 octets
        # Don't call activate_menu_item for these special editing screens
    elif menu_state in ["update_confirm", "downgrade_confirm"]:
        # Cancel action
        menu_state = "update"
        selected_version = None  # Reset selected_version
        # Don't call activate_menu_item here
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
    logging.debug("K4 pressed")
    last_interaction_time = time.time()
    timeout_flag = False  # Reset timeout flag

    if menu_state in ["show_network_info", "show_pi_health"]:
        reset_to_main()
    elif menu_state in ["set_static_ip", "set_static_sm", "set_static_gw", "set_date", "set_time"]:
        ip_octet = (ip_octet + 1) % 4  # Corrected to allow all 4 octets
        # Don't call activate_menu_item for these special editing screens
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
    else:
        menu_selection = 3
        activate_menu_item()
    update_oled_display(force=True)

def hold_k3():
    global menu_state, ip_address, subnet_mask, gateway, original_ip_address, original_subnet_mask, original_gateway, last_interaction_time, selected_version, timeout_flag
    logging.debug("K3 held for 1 seconds")
    last_interaction_time = time.time()
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
    logging.debug("K4 held for 1 seconds")
    last_interaction_time = time.time()
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
        set_system_datetime(datetime_temp)
        state = load_state()
        state["time_format_24hr"] = time_format_24hr
        save_state(state)
        update_clock_format(time_format_24hr)
        # Go back to the main menu after setting date/time
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

def apply_static_settings():
    ip_str = '.'.join(map(str, ip_address))
    sm_str = '.'.join(map(str, subnet_mask))
    gw_str = '.'.join(map(str, gateway))
    cidr = subnet_mask_to_cidr(sm_str)
    execute_command(f"sudo nmcli connection modify {STATIC_PROFILE} ipv4.addresses {ip_str}/{cidr}")
    execute_command(f"sudo nmcli connection modify {STATIC_PROFILE} ipv4.gateway {gw_str}")
    execute_command(f"sudo nmcli connection modify {STATIC_PROFILE} ipv4.method manual")
    execute_command(f"sudo nmcli connection modify {STATIC_PROFILE} ipv4.dns {gw_str}")
    execute_command(f"sudo nmcli connection up {STATIC_PROFILE}")
    logging.info("Static IP settings applied to the network profile.")

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
        elif ip_octet == 3 and not time_format_24hr:
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

    # Restart the panel or system to apply changes
    subprocess.run(['lxpanelctl', 'restart'], check=True)
    logging.info(f"Clock format set to {'24-hour' if time_format_24hr else '12-hour'} with seconds.")

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
        # Download the ZIP file
        r = requests.get(zip_url, stream=True)
        r.raise_for_status()

        with open(local_zip, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

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
        config_path = '/home/pi/OLED_Stats_pi/config.json'
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
                    except:
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
    print(f"DEBUG: update_omnicon called, available_versions = {available_versions}")
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
    extract_path = "/home/omnicon/OLED_Stats"

    ok, err = download_and_extract_zip_from_github(version, extract_path)
    if ok:
        # Show message before restarting
        show_message("RESTARTING\nSERVICES...", 2)
        restart_script()
        return "OMNICON UPDATED"
    else:
        return f"UPDATE FAILED\n{err}"

def downgrade_omnicon():
    global available_versions, current_version, selected_version
    selected_version = None  # Initialize selected_version to None
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
    current_version_tuple = tuple(map(int, current_version.strip('V').split('.')))
    older_versions = [
        v for v in available_versions
        if tuple(map(int, v.strip('V').split('.'))) < current_version_tuple
    ]
    if not older_versions:
        return "NO OLDER VERSIONS"
    selected_version = older_versions[0]
    return "DOWNGRADE AVAILABLE"

def perform_downgrade(version):
    extract_path = "/home/omnicon/OLED_Stats"

    ok, err = download_and_extract_zip_from_github(version, extract_path)
    if ok:
        # Show message before restarting
        show_message("RESTARTING\nSERVICES...", 2)
        restart_script()
        return "OMNICON DOWNGRADED"
    else:
        return f"DOWNGRADE FAILED\n{err}"

# Update OLED display in a separate thread
def update_oled():
    import math
    # Start at the next full second boundary
    next_second = math.floor(time.time()) + 1
    while True:
        # Sleep until the next absolute second boundary
        now = time.time()
        sleep_time = next_second - now
        if sleep_time > 0:
            time.sleep(sleep_time)
        update_oled_display()
        # Always advance by exactly 1 second to prevent drift
        next_second += 1



# Web command processor for remote control
web_command_file = "web_command.json"
trigger_file = "trigger_command"
web_command_queue = []
web_command_lock = threading.Lock()

def process_web_commands():
    """Process commands from the web GUI - Non-blocking version"""
    global web_command_queue

    while True:
        try:
            # Check if there's a trigger file
            if os.path.exists(trigger_file):
                try:
                    os.remove(trigger_file)  # Remove trigger
                except:
                    pass

                # Check for command file
                if os.path.exists(web_command_file):
                    try:
                        with open(web_command_file, 'r') as f:
                            cmd_data = json.load(f)

                        # Add command to queue instead of processing immediately
                        with web_command_lock:
                            web_command_queue.append(cmd_data)

                        logging.info(f"Queued web command: {cmd_data.get('command')}")

                        # Remove command file after reading
                        os.remove(web_command_file)
                    except Exception as e:
                        logging.error(f"Error reading web command: {e}")

        except Exception as e:
            logging.error(f"Error in web command processor: {e}")

        # Check more frequently but don't block
        time.sleep(0.2)

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
        last_interaction_time = time.time()

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

            # Convert to lists
            ip_address = [int(x) for x in ip_str.split('.')]
            subnet_mask = [int(x) for x in subnet_str.split('.')]
            gateway = [int(x) for x in gateway_str.split('.')]

            # Run in background to avoid blocking
            def apply_settings():
                save_static_settings()
                apply_static_settings()
                logging.info("Applied static IP settings via web")

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

            threading.Thread(target=set_dt, daemon=True).start()

        elif command == 'update_companion_stable':
            # Trigger companion update through OLED menu system
            logging.info("Triggering Companion stable update via web")
            if is_connected():
                show_message("UPDATING\nCOMPANION", 2)
                global updating_application
                updating_application = True
                execute_command_with_progress('echo -e "\\033[A\\n" | sudo companion-update')
                updating_application = False
                show_message("REBOOTING...", 2)
                turn_off_oled()
                execute_command("sudo reboot")
            else:
                show_message("PLEASE CONNECT\nTO INTERNET", 3)
                menu_state = "default"

        elif command == 'update_satellite_stable':
            # Trigger satellite update through OLED menu system
            logging.info("Triggering Satellite stable update via web")
            if is_connected():
                show_message("UPDATING\nSATELLITE", 2)
                updating_application = True
                execute_command_with_progress('echo -e "\\033[A\\n" | sudo satellite-update')
                updating_application = False
                show_message("REBOOTING...", 2)
                turn_off_oled()
                execute_command("sudo reboot")
            else:
                show_message("PLEASE CONNECT\nTO INTERNET", 3)
                menu_state = "default"

    except Exception as e:
        logging.error(f"Error executing web command: {e}")


def process_web_commands():
    """Process commands from the web GUI - Non-blocking version"""
    global web_command_queue

    while True:
        try:
            # Check if there's a trigger file
            if os.path.exists(trigger_file):
                try:
                    os.remove(trigger_file)  # Remove trigger
                except:
                    pass

                # Check for command file
                if os.path.exists(web_command_file):
                    try:
                        with open(web_command_file, 'r') as f:
                            cmd_data = json.load(f)

                        # Add command to queue instead of processing immediately
                        with web_command_lock:
                            web_command_queue.append(cmd_data)

                        logging.info(f"Queued web command: {cmd_data.get('command')}")

                        # Remove command file after reading
                        os.remove(web_command_file)
                    except Exception as e:
                        logging.error(f"Error reading web command: {e}")

        except Exception as e:
            logging.error(f"Error in web command processor: {e}")

        # Check more frequently but don't block
        time.sleep(0.2)

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
        last_interaction_time = time.time()

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

            # Convert to lists
            ip_address = [int(x) for x in ip_str.split('.')]
            subnet_mask = [int(x) for x in subnet_str.split('.')]
            gateway = [int(x) for x in gateway_str.split('.')]

            # Run in background to avoid blocking
            def apply_settings():
                save_static_settings()
                apply_static_settings()
                logging.info("Applied static IP settings via web")

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

            threading.Thread(target=set_dt, daemon=True).start()

        elif command == 'update_companion_stable':
            # Trigger companion update through OLED menu system
            logging.info("Triggering Companion stable update via web")
            if is_connected():
                show_message("UPDATING\nCOMPANION", 2)
                global updating_application
                updating_application = True
                execute_command_with_progress('echo -e "\\033[A\\n" | sudo companion-update')
                updating_application = False
                show_message("REBOOTING...", 2)
                turn_off_oled()
                execute_command("sudo reboot")
            else:
                show_message("PLEASE CONNECT\nTO INTERNET", 3)
                menu_state = "default"

        elif command == 'update_satellite_stable':
            # Trigger satellite update through OLED menu system
            logging.info("Triggering Satellite stable update via web")
            if is_connected():
                show_message("UPDATING\nSATELLITE", 2)
                updating_application = True
                execute_command_with_progress('echo -e "\\033[A\\n" | sudo satellite-update')
                updating_application = False
                show_message("REBOOTING...", 2)
                turn_off_oled()
                execute_command("sudo reboot")
            else:
                show_message("PLEASE CONNECT\nTO INTERNET", 3)
                menu_state = "default"

    except Exception as e:
        logging.error(f"Error executing web command: {e}")


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

                        # Convert to lists
                        ip_address = [int(x) for x in ip_str.split('.')]
                        subnet_mask = [int(x) for x in subnet_str.split('.')]
                        gateway = [int(x) for x in gateway_str.split('.')]

                        save_static_settings()
                        apply_static_settings()
                        logging.info("Applied static IP settings via web")

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
                        last_interaction_time = time.time()

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

                    # Remove command file after processing
                    os.remove(web_command_file)

        except Exception as e:
            logging.error(f"Error processing web command: {e}")

        # Check every 0.5 seconds for new commands
        time.sleep(0.5)


# Web command processor for remote control
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

                        # Convert to lists
                        ip_address = [int(x) for x in ip_str.split('.')]
                        subnet_mask = [int(x) for x in subnet_str.split('.')]
                        gateway = [int(x) for x in gateway_str.split('.')]

                        save_static_settings()
                        apply_static_settings()
                        logging.info("Applied static IP settings via web")

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
                        last_interaction_time = time.time()

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

                    # Remove command file after processing
                    os.remove(web_command_file)

        except Exception as e:
            logging.error(f"Error processing web command: {e}")

        # Check every 0.5 seconds for new commands
        time.sleep(0.5)


# Web command processor for remote control
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

                        # Convert to lists
                        ip_address = [int(x) for x in ip_str.split('.')]
                        subnet_mask = [int(x) for x in subnet_str.split('.')]
                        gateway = [int(x) for x in gateway_str.split('.')]

                        save_static_settings()
                        apply_static_settings()
                        logging.info("Applied static IP settings via web")

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
                        last_interaction_time = time.time()

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
                            execute_command_with_progress('echo -e "\\033[A\\n" | sudo companion-update')
                            updating_application = False
                            show_message("REBOOTING...", 2)
                            turn_off_oled()
                            execute_command("sudo reboot")
                        else:
                            show_message("PLEASE CONNECT\nTO INTERNET", 3)

                    elif command == 'update_satellite_stable':
                        # Trigger satellite update through OLED menu system
                        logging.info("Triggering Satellite stable update via web")
                        if is_connected():
                            show_message("UPDATING\nSATELLITE", 2)
                            updating_application = True
                            execute_command_with_progress('echo -e "\\033[A\\n" | sudo satellite-update')
                            updating_application = False
                            show_message("REBOOTING...", 2)
                            turn_off_oled()
                            execute_command("sudo reboot")
                        else:
                            show_message("PLEASE CONNECT\nTO INTERNET", 3)

                    # Remove command file after processing
                    os.remove(web_command_file)

        except Exception as e:
            logging.error(f"Error processing web command: {e}")

        # Check every 0.5 seconds for new commands
        time.sleep(0.5)


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

    # Start web command processor thread

    # Start web command processor thread


    logging.info('Script started successfully')

    timeout_thread = threading.Thread(target=check_timeout)
    timeout_thread.daemon = True
    timeout_thread.start()

    while True:
        execute_web_commands()
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
    global last_interaction_time
    while True:
        if time.time() - last_interaction_time > 20:  # 20 seconds timeout
            reset_to_main()
        time.sleep(1)

def activate_menu_item():
    global menu_state, menu_selection, updating_application, ip_octet, ip_address, subnet_mask, gateway, original_ip_address, original_subnet_mask, original_gateway, last_interaction_time, timeout_flag, datetime_temp, available_versions, selected_version
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
        if selected_option == "CURRENT STABLE":
            if is_connected():
                show_message("UPDATING\nCOMPANION", 2)
                updating_application = True
                execute_command_with_progress('echo -e "\\033[A\\n" | sudo companion-update')
                updating_application = False
                show_message("REBOOTING...", 2)
                turn_off_oled()
                execute_command("sudo reboot")
            else:
                show_message("PLEASE CONNECT\nTO INTERNET", 3)
                menu_state = "default"
        elif selected_option == "CANCEL":
            menu_state = "app_updates"
            menu_selection = 0

    elif menu_state == "update_satellite":
        if selected_option == "CURRENT STABLE":
            if is_connected():
                show_message("UPDATING\nSATELLITE", 2)
                updating_application = True
                execute_command_with_progress('echo -e "\\033[A\\n" | sudo satellite-update')
                updating_application = False
                show_message("REBOOTING...", 2)
                turn_off_oled()
                execute_command("sudo reboot")
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
