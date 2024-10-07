# CREATED BY PHILLIP RUDE
# FOR OMNICON DUO PI, MONO PI & HUB
# V3.3.8
# OCT 07, 2024

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
import psutil  # Added for accurate CPU usage
import requests

# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(message)s')

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
    button_k1 = Button(BUTTON_K1, pull_up=True, hold_time=1, bounce_time=0.1)
    button_k2 = Button(BUTTON_K2, pull_up=True, hold_time=1, bounce_time=0.1)
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

# State file
STATE_FILE = "state.json"

# Global variables
time_format_24hr = True  # True for 24-hour format, False for 12-hour format
available_versions = []  # To store fetched versions
update_menu = ["CURRENT: " + "V2.1.0", "UPGRADE", "DOWNGRADE", "EXIT"]

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
LOOPTIME = 0.05  # Refresh rate reduced to 0.5 seconds

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

# Load the same font with size 10 for the last line
font10 = ImageFont.truetype('DejaVuSans.ttf', 10)

# Use DejaVuSans font for proper triangle display
font11 = ImageFont.truetype('DejaVuSans.ttf', 11)

# Use DejaVuSans font for proper triangle display
font12 = ImageFont.truetype('DejaVuSans.ttf', 12)

# Use DejaVuSans font for proper triangle display
font13 = ImageFont.truetype('DejaVuSans.ttf', 13)

# Use DejaVuSans font for proper triangle display
font14 = ImageFont.truetype('DejaVuSans.ttf', 14)

# Load the same font with size 15 for the first line
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

# Menu options
main_menu = ["APPLICATION", "CONFIGURATION", "POWER", "EXIT"]
application_menu = ["COMPANION", "SATELLITE", "", "EXIT"]
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
    "set_date": [],
    "set_time": [],
    "upgrade_select": [],
    "downgrade_select": [],
    "show_network_info": [],
    "show_pi_health": [],
}

# Button indicators
indicators = {
    "K1": "â²",
    "K2": "â¼",
    "K3": "â€",
    "K4": "â¶"
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
def update_oled_display():
    global blink_state, gateway, update_flag, last_update_time, datetime_temp, time_format_24hr
    current_time = time.time()
    if not update_flag or (current_time - last_update_time) < LOOPTIME:
        return
    update_flag = False
    last_update_time = current_time
    logging.debug("Updating OLED display")

    local_image = Image.new("1", (oled.width, oled.height))
    local_draw = ImageDraw.Draw(local_image)

    state = load_state()

    clear_display()

    if menu_state == "default":
        current_time_format = "%H:%M:%S" if time_format_24hr else "%I:%M:%S %p"
        current_time = datetime.now().strftime(current_time_format)
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
        local_draw.text((0, 0), f"{title}", font=font12, fill=255)
        local_draw.text((90, 0), EthProfile, font=font11, fill=255)
        local_draw.text((0, 16), IP, font=font11, fill=255)
        local_draw.text((95, 16), port, font=font11, fill=255)
        local_draw.text((0, 32), f"{current_time}", font=font12, fill=255)
        local_draw.text((90, 32), Temp, font=font11, fill=255)
        local_draw.text((0, 48), "3.3.8 TEST", font=font10, fill=255)

    elif menu_state == "set_static_ip":
        ip_display = [f"{ip:03}" for ip in ip_address]
        if blink_state:
            ip_display[ip_octet] = f"[{ip_display[ip_octet]}]"  # Highlight the selected octet with brackets
        else:
            ip_display[ip_octet] = f" {ip_display[ip_octet]} "  # Remove brackets during blink off
        local_draw.text((0, 0), "   SET IP ADDRESS", font=font12, fill=255)
        local_draw.text((0, 16), ' '.join(ip_display), font=font12, fill=255)
        local_draw.text((0, 32), "CANCEL : 1 SECOND  â€", font=font11, fill=255)
        local_draw.text((0, 48), "APPLY :    1 SECOND  â¶", font=font11, fill=255)

    elif menu_state == "set_static_sm":
        sm_display = [f"{sm:03}" for sm in subnet_mask]
        if blink_state:
            sm_display[ip_octet] = f"[{sm_display[ip_octet]}]"  # Highlight the selected octet with brackets
        else:
            sm_display[ip_octet] = f" {sm_display[ip_octet]} "  # Remove brackets during blink off
        local_draw.text((0, 0), "  SET SUBNET MASK", font=font12, fill=255)
        local_draw.text((0, 16), ' '.join(sm_display), font=font12, fill=255)
        local_draw.text((0, 32), "CANCEL : 1 SECOND  â€", font=font11, fill=255)
        local_draw.text((0, 48), "APPLY :    1 SECOND  â¶", font=font11, fill=255)

    elif menu_state == "set_static_gw":
        gw_display = [f"{gw:03}" for gw in gateway]
        if blink_state:
            gw_display[ip_octet] = f"[{gw_display[ip_octet]}]"  # Highlight the selected octet with brackets
        else:
            gw_display[ip_octet] = f" {gw_display[ip_octet]} "  # Remove brackets during blink off
        local_draw.text((0, 0), "     SET GATEWAY", font=font12, fill=255)
        local_draw.text((0, 16), ' '.join(gw_display), font=font12, fill=255)
        local_draw.text((0, 32), "CANCEL : 1 SECOND  â€", font=font11, fill=255)
        local_draw.text((0, 48), "APPLY :    1 SECOND  â¶", font=font11, fill=255)

    elif menu_state == "show_network_info":
        ip, subnet, gateway, dns = get_current_network_settings()
        local_draw.text((0, 0), f"IP: {ip}", font=font11, fill=255)
        local_draw.text((0, 16), f"SUB: {subnet}", font=font11, fill=255)
        local_draw.text((0, 32), f"GW: {gateway}", font=font11, fill=255)
        local_draw.text((0, 48), f"DNS: {dns}", font=font11, fill=255)
    
    elif menu_state == "show_pi_health":
        temp, voltage, watt_input, cpu, memory = get_pi_health()
        current_datetime = datetime.now().strftime("%m/%d/%y  %H:%M" if time_format_24hr else "%m/%d/%y  %I:%M %p")
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
        local_draw.text((0, 32), "CANCEL : 1 SECOND  â€", font=font11, fill=255)
        local_draw.text((0, 48), "APPLY :    1 SECOND  â¶", font=font11, fill=255)

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
        local_draw.text((0, 32), "CANCEL : 1 SECOND  â€", font=font11, fill=255)
        local_draw.text((0, 48), "APPLY :    1 SECOND  â¶", font=font11, fill=255)

    elif menu_state == "set_datetime":
        current_datetime = datetime.now().strftime("%m/%d/%y   %H:%M" if time_format_24hr else "%m/%d/%y   %I:%M %p")
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
                suffix = indicators.get(f"K{i+1}", "") if i > 0 else ""  # Remove indicator from the current version line
                local_draw.text((0, i * 16), option, font=font11, fill=255)
                local_draw.text((112, i * 16), suffix, font=font11, fill=255)

    elif menu_state in ["upgrade_select", "downgrade_select"]:
        for i, version in enumerate(available_versions[:3]):
            suffix = indicators.get(f"K{i+1}", "")  # Use .get to avoid KeyError
            local_draw.text((0, i * 16), version, font=font11, fill=255)
            local_draw.text((112, i * 16), suffix, font=font11, fill=255)
        local_draw.text((0, 48), "EXIT", font=font11, fill=255)
        local_draw.text((112, 48), indicators["K4"], font=font11, fill=255)

    else:
        options = menu_options[menu_state]
        state = load_state()
        for i, option in enumerate(options):
            if option:
                prefix = ""
                if menu_state == "network":
                    if (option == "DHCP" and state["network"] == DHCP_PROFILE) or (option == "STATIC IP" and state["network"] == STATIC_PROFILE):
                        prefix = "*"
                if menu_state == "application":
                    if (option == "COMPANION" and is_service_active("companion.service")) or (option == "SATELLITE" and is_service_active("satellite.service")):
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
    global menu_state, ip_address, subnet_mask, gateway, timeout_flag, datetime_temp
    if not timeout_flag:
        logging.debug("Timeout: Resetting to main display")
        menu_state = "default"
        ip_address = original_ip_address[:]
        subnet_mask = original_subnet_mask[:]
        gateway = original_gateway[:]
        datetime_temp = datetime.now()
        update_oled_display()
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
    else:
        menu_selection = 0
        activate_menu_item()
    reset_menu_selection()
    update_oled_display()

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
    elif menu_state == "set_static_ip":
        ip_address[ip_octet] = (ip_address[ip_octet] - 1) % 256
    elif menu_state == "set_static_sm":
        subnet_mask[ip_octet] = (subnet_mask[ip_octet] - 1) % 256
    elif menu_state == "set_static_gw":
        gateway[ip_octet] = (gateway[ip_octet] - 1) % 256
    elif menu_state == "set_date":
        update_date(-1)
    elif menu_state == "set_time":
        update_time(-1)
    else:
        menu_selection = 1
        activate_menu_item()
    reset_menu_selection()
    update_oled_display()

@debounce
def button_k3_pressed():
    global menu_state, menu_selection, ip_octet, last_interaction_time, timeout_flag, time_format_24hr
    logging.debug("K3 pressed")
    last_interaction_time = time.time()
    timeout_flag = False
    
    if menu_state == "default":
        menu_state = "show_pi_health"
    elif menu_state == "show_pi_health":
        reset_to_main()
    elif menu_state in ["set_static_ip", "set_static_sm", "set_static_gw"]:
        ip_octet = (ip_octet - 1) % 4
    elif menu_state == "set_date":
        ip_octet = (ip_octet - 1) % 3  # Cycle between 0 and 2 for date
    elif menu_state == "set_time":
        max_octet = 3 if not time_format_24hr else 2
        ip_octet = (ip_octet - 1) % (max_octet + 1)
    else:
        menu_selection = 2
        activate_menu_item()
    reset_menu_selection()
    update_oled_display()

@debounce
def button_k4_pressed():
    global menu_state, menu_selection, ip_octet, last_interaction_time, timeout_flag, time_format_24hr
    logging.debug("K4 pressed")
    last_interaction_time = time.time()
    timeout_flag = False
    
    if menu_state == "default":
        menu_state = "show_network_info"
    elif menu_state == "show_network_info":
        reset_to_main()
    elif menu_state in ["set_static_ip", "set_static_sm", "set_static_gw"]:
        ip_octet = (ip_octet + 1) % 4
    elif menu_state == "set_date":
        ip_octet = (ip_octet + 1) % 3  # Cycle between 0 and 2 for date
    elif menu_state == "set_time":
        max_octet = 3 if not time_format_24hr else 2
        ip_octet = (ip_octet + 1) % (max_octet + 1)
    else:
        menu_selection = 3
        activate_menu_item()
    reset_menu_selection()
    update_oled_display()


def hold_k3():
    global menu_state, ip_address, subnet_mask, gateway, original_ip_address, original_subnet_mask, original_gateway, last_interaction_time
    logging.debug("K3 held for 1 seconds")
    last_interaction_time = time.time()
    
    if menu_state in ["set_static_ip", "set_static_sm", "set_static_gw"]:
        ip_address = original_ip_address[:]
        subnet_mask = original_subnet_mask[:]
        gateway = original_gateway[:]
        menu_state = "set_static"
    elif menu_state in ["set_date", "set_time"]:
        menu_state = "set_datetime"
    update_oled_display()  # Update the display immediately after change

def hold_k4():
    global menu_state, ip_address, subnet_mask, gateway, original_ip_address, original_subnet_mask, original_gateway, datetime_temp, last_interaction_time, time_format_24hr
    logging.debug("K4 held for 1 seconds")
    last_interaction_time = time.time()
    
    if menu_state in ["set_static_ip", "set_static_sm", "set_static_gw"]:
        save_static_settings()
        apply_static_settings()
        original_ip_address = ip_address[:]
        original_subnet_mask = subnet_mask[:]
        original_gateway = gateway[:]
        menu_state = "set_static"
    elif menu_state in ["set_date", "set_time"]:
        set_system_datetime(datetime_temp)
        state = load_state()
        state["time_format_24hr"] = time_format_24hr
        save_state(state)
        update_clock_format(time_format_24hr)  # Add this line to update the clock format
        restart_script()
    update_oled_display()  # Update the display immediately after change

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
    logging.debug(f"Updating date by {increment} at ip_octet {ip_octet}")
    try:
        if ip_octet == 0:
            new_month = (datetime_temp.month + increment - 1) % 12 + 1
            datetime_temp = datetime_temp.replace(month=new_month)
            logging.debug(f"New month: {new_month}")
        elif ip_octet == 1:
            new_day = (datetime_temp.day + increment - 1) % 31 + 1
            datetime_temp = datetime_temp.replace(day=new_day)
            logging.debug(f"New day: {new_day}")
        elif ip_octet == 2:
            new_year = datetime_temp.year + increment
            datetime_temp = datetime_temp.replace(year=new_year)
            logging.debug(f"New year: {new_year}")
    except ValueError as e:
        logging.error(f"Invalid date adjustment: {e}")

def update_time(increment):
    global datetime_temp, time_format_24hr
    logging.debug(f"Updating time by {increment} at ip_octet {ip_octet}")
    try:
        if ip_octet == 0:
            # Toggle between 24-hour and 12-hour format
            time_format_24hr = not time_format_24hr
            logging.debug(f"Time format changed to {'24hr' if time_format_24hr else '12hr'}")
        elif ip_octet == 1:
            if time_format_24hr:
                new_hour = (datetime_temp.hour + increment) % 24
            else:
                hour = datetime_temp.hour % 12 or 12  # Convert to 12-hour format
                new_hour = (hour + increment - 1) % 12 + 1
                if datetime_temp.strftime("%p") == "PM":
                    new_hour = new_hour % 12 + 12
            datetime_temp = datetime_temp.replace(hour=new_hour)
            logging.debug(f"New hour: {datetime_temp.hour}")
        elif ip_octet == 2:
            new_minute = (datetime_temp.minute + increment) % 60
            datetime_temp = datetime_temp.replace(minute=new_minute)
            logging.debug(f"New minute: {new_minute}")
        elif ip_octet == 3 and not time_format_24hr:
            # Toggle AM/PM
            if datetime_temp.hour >= 12:
                new_hour = datetime_temp.hour - 12
            else:
                new_hour = datetime_temp.hour + 12
            datetime_temp = datetime_temp.replace(hour=new_hour)
            logging.debug(f"AM/PM toggled, new hour: {datetime_temp.hour}")
    except ValueError as e:
        logging.error(f"Invalid time adjustment: {e}")


def set_system_datetime(datetime_temp):
    date_str = datetime_temp.strftime("%Y-%m-%d")
    time_str = datetime_temp.strftime("%H:%M" if time_format_24hr else "%I:%M %p")
    execute_command(f"sudo date --set='{date_str}'")
    execute_command(f"sudo date --set='{time_str}'")

def restart_script():
    """Restarts the current script."""
    logging.info("Restarting script...")
    os.execv(sys.executable, ['python3'] + sys.argv)

def subnet_mask_to_cidr(mask):
    mask_octets = map(int, mask.split('.'))
    binary_str = ''.join([bin(octet).lstrip('0b').zfill(8) for octet in mask_octets])
    return str(len(binary_str.rstrip('0')))

def clear_display():
    logging.debug("Clearing display")
    draw.rectangle((0, 0, oled.width, oled.height), outline=0, fill=0)

def turn_off_oled():
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
    # You might need to adapt this command to restart your specific panel if `lxpanelctl` is not applicable
    subprocess.run(['lxpanelctl', 'restart'], check=True)
    logging.info(f"Clock format set to {'24-hour' if time_format_24hr else '12-hour'} with seconds.")

def get_current_version():
    with open("/home/omnicon/OLED_Stats/omnicon.py", "r") as file:
        for i, line in enumerate(file):
            if i == 2 and line.startswith("# V"):
                return line.strip().split(' ')[1]
    return "Unknown"

def download_file_from_github(tag, local_path):
    url = f"https://raw.githubusercontent.com/RUDEWORLD/OMNICON/{tag}/omnicon.py"
    try:
        response = requests.get(url)
        response.raise_for_status()
        with open(local_path, 'w', encoding='utf-8') as file:  # Ensure UTF-8 encoding is used
            file.write(response.text)
        logging.info(f"Downloaded and saved: {local_path}")
        return True
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to download the script: {e}")
        return False

def fetch_github_tags():
    url = "https://api.github.com/repos/RUDEWORLD/OMNICON/tags"
    try:
        response = requests.get(url)
        response.raise_for_status()
        tags = response.json()
        return [tag['name'] for tag in tags]
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to fetch tags from GitHub: {e}")
        return []

def filter_versions(current_version, versions, upgrade=True):
    current_version_tuple = tuple(map(int, current_version.lstrip('V').split('.')))
    filtered_versions = []
    for v in versions:
        try:
            version_tuple = tuple(map(int, v.lstrip('vV').split('.')))
            if (upgrade and version_tuple > current_version_tuple) or (not upgrade and version_tuple < current_version_tuple):
                filtered_versions.append(v)
        except ValueError:
            logging.warning(f"Skipping invalid version format: {v}")
    return filtered_versions

def update_omnicon():
    global available_versions
    if not available_versions:
        available_versions = fetch_github_tags()
        if not available_versions:
            return "NO TAGS FOUND"
    selected_version = available_versions[menu_selection]
    local_path = "/home/omnicon/OLED_Stats/omnicon.py"
    current_version = get_current_version()
    if selected_version == current_version:
        show_message("YOU'RE UP TO DATE", 3, return_to="update")  # Show message for 3 seconds and return to update menu
        return "YOU'RE UP TO DATE"
    if download_file_from_github(selected_version, local_path):
        restart_script()
        return "OMNICON UPDATED"
    else:
        return "UPDATE FAILED"

def downgrade_omnicon():
    global available_versions
    if not available_versions:
        available_versions = fetch_github_tags()
        if not available_versions:
            return "NO TAGS FOUND"
    selected_version = available_versions[menu_selection]
    local_path = "/home/omnicon/OLED_Stats/omnicon.py"
    if download_file_from_github(selected_version, local_path):
        restart_script()
        return "OMNICON DOWNGRADED"
    else:
        return "DOWNGRADE FAILED"

# Update OLED display in a separate thread
def update_oled():
    while True:
        # Wait for the start of the next second
        now = datetime.now()
        sleep_time = 1 - now.microsecond / 1_000_000
        time.sleep(sleep_time)
        update_oled_display()

def main():
    global datetime_temp, time_format_24hr, update_menu
    initial_setup()
    datetime_temp = datetime.now()

    state = load_state()
    time_format_24hr = state.get("time_format_24hr", True)

    # Get current version for the update menu
    current_version = get_current_version()
    update_menu[0] = f"CURRENT: {current_version}"

    button_k1.when_pressed = button_k1_pressed
    button_k2.when_pressed = button_k2_pressed
    button_k3.when_pressed = button_k3_pressed
    button_k4.when_pressed = button_k4_pressed

    button_k1.when_held = lambda: fast_adjust_ip(button_k1, 10)  # Change value by 10 when held
    button_k2.when_held = lambda: fast_adjust_ip(button_k2, -10)  # Change value by 10 when held

    button_k3.when_held = hold_k3
    button_k4.when_held = hold_k4

    update_oled_thread = threading.Thread(target=update_oled)
    update_oled_thread.daemon = True
    update_oled_thread.start()

    logging.info('Script started successfully')

    timeout_thread = threading.Thread(target=check_timeout)
    timeout_thread.daemon = True
    timeout_thread.start()

    while True:
        time.sleep(.1)  # Check every 100ms

def fast_adjust_ip(button, increment):
    global menu_state, ip_octet, ip_address, subnet_mask, gateway, datetime_temp
    start_time = time.time()
    while button.is_held:
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
        update_oled_display()  # Update the display immediately to show the changing values
        time.sleep(.6)  # Reduce sleep time to make the changes more responsive

def check_timeout():
    global last_interaction_time
    while True:
        if time.time() - last_interaction_time > 20:  # 20 seconds timeout
            reset_to_main()
        time.sleep(1)

# Add this function to reset menu selection if it goes out of range
def reset_menu_selection():
    global menu_selection
    options = menu_options[menu_state]
    if menu_selection >= len(options):
        menu_selection = 0

# Modify the `activate_menu_item` function
def activate_menu_item():
    global menu_state, menu_selection, ip_octet, ip_address, subnet_mask, gateway, original_ip_address, original_subnet_mask, original_gateway, last_interaction_time, timeout_flag, datetime_temp, available_versions

    reset_menu_selection()  # Ensure menu_selection is valid

    options = menu_options[menu_state]
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
        if selected_option == "COMPANION":
            toggle_service("companion")
            menu_state = "default"
        elif selected_option == "SATELLITE":
            toggle_service("satellite")
            menu_state = "default"
        elif selected_option == "EXIT":
            menu_state = "default"

    elif menu_state == "configuration":
        if selected_option == "NETWORK":
            menu_state = "network"
            menu_selection = 0
        elif selected_option == "SET DATE/TIME":
            menu_state = "set_datetime"
            menu_selection = 0
            datetime_temp = datetime.now()
        elif selected_option == "UPDATE":
            available_versions = fetch_github_tags()
            if available_versions:
                current_version = get_current_version()
                menu_options["upgrade_select"] = filter_versions(current_version, available_versions, upgrade=True)[:3] + ["EXIT"]
                menu_options["downgrade_select"] = filter_versions(current_version, available_versions, upgrade=False)[:3] + ["EXIT"]
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

    elif menu_state == "update":
        if selected_option == "UPGRADE":
            available_versions = fetch_github_tags()
            if available_versions:
                current_version = get_current_version()
                upgrade_versions = filter_versions(current_version, available_versions, upgrade=True)
                if not upgrade_versions:
                    show_message("YOU'RE UP TO DATE", 3, return_to="update")
                    return
                menu_options["upgrade_select"] = upgrade_versions[:3] + ["EXIT"]
                menu_state = "upgrade_select"
                menu_selection = 0
            else:
                show_message("NO TAGS FOUND", 3)
                menu_state = "default"
                return
        elif selected_option == "DOWNGRADE":
            available_versions = fetch_github_tags()
            if available_versions:
                current_version = get_current_version()
                menu_options["downgrade_select"] = filter_versions(current_version, available_versions, upgrade=False)[:3] + ["EXIT"]
            menu_state = "downgrade_select"
            menu_selection = 0
        elif selected_option == "EXIT":
            menu_state = "default"

    elif menu_state == "upgrade_select":
        if selected_option == "EXIT":
            menu_state = "update"
            menu_selection = 0
        else:
            update_result = update_omnicon()
            show_message(update_result, 10)  # Show message for 10 seconds
            menu_state = "default"
            menu_selection = 0

    elif menu_state == "downgrade_select":
        if selected_option == "EXIT":
            menu_state = "update"
            menu_selection = 0
        else:
            downgrade_result = downgrade_omnicon()
            show_message(downgrade_result, 5)
            menu_state = "default"
            menu_selection = 0

    logging.debug(f"Activated menu item: {selected_option}")
    update_oled_display()


def show_message(message, duration, return_to="default"):
    global timeout_flag, menu_state
    clear_display()
    draw.text((0, 0), message, font=font12, fill=255)
    oled.image(image.rotate(180))
    oled.show()
    time.sleep(duration)
    timeout_flag = True
    menu_state = return_to
    update_oled_display()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.info('Script interrupted by user.')
