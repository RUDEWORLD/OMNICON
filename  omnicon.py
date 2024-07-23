# CREATED BY PHILLIP RUDE
# FOR OMNICON DUO PI AND MONO PI
# v1.0.0
# JUNE 18, 2024

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
            return state
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "service": "companion",
            "network": "STATIC",
            "static_ip": [192, 168, 0, 100],
            "subnet_mask": [255, 255, 255, 0],
            "gateway": [192, 168, 0, 1]
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
main_menu = ["SYSTEM", "NETWORK", "POWER", "EXIT"]
system_menu = ["COMPANION", "SATELLITE", "", "EXIT"]
network_menu = ["DHCP", "STATIC IP", "SET STATIC", "EXIT"]
power_menu = ["REBOOT", "SHUTDOWN", "", "EXIT"]
reboot_confirm_menu = ["CANCEL", "REBOOT"]
shutdown_confirm_menu = ["CANCEL", "SHUTDOWN"]
set_static_menu = ["IP ADDRESS", "SUBNET MASK", "GATEWAY", "EXIT"]
menu_options = {
    "default": main_menu,
    "main": main_menu,
    "system": system_menu,
    "network": network_menu,
    "power": power_menu,
    "set_static": set_static_menu,
    "reboot_confirm": reboot_confirm_menu,
    "shutdown_confirm": shutdown_confirm_menu,
    "set_static_ip": set_static_menu,
    "set_static_sm": set_static_menu,
    "set_static_gw": set_static_menu,
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
    ip = subprocess.check_output(["hostname", "-I"]).decode('utf-8').strip()
    subnet = subprocess.check_output(["ip", "-o", "-f", "inet", "addr", "show"]).decode('utf-8')
    subnet = [line.split()[3] for line in subnet.splitlines() if 'eth0' in line]
    subnet = subnet[0].split('/')[1] if subnet else "N/A"
    subnet = cidr_to_subnet_mask(subnet)
    gateway = subprocess.check_output(["ip", "route", "show", "default"]).decode('utf-8').split()[2]
    dns = subprocess.check_output(["nmcli", "dev", "show"]).decode('utf-8')
    dns_servers = [line.split(':')[-1].strip() for line in dns.splitlines() if 'IP4.DNS' in line]
    dns = ', '.join(dns_servers)
    return ip, subnet, gateway, dns

def cidr_to_subnet_mask(cidr):
    cidr = int(cidr)
    mask = (0xffffffff >> (32 - cidr)) << (32 - cidr)
    return f'{(mask >> 24) & 0xff}.{(mask >> 16) & 0xff}.{(mask >> 8) & 0xff}.{mask & 0xff}'

def get_pi_health():
    temp = subprocess.check_output(["vcgencmd", "measure_temp"]).decode('utf-8').strip().split('=')[1]
    voltage = subprocess.check_output(["vcgencmd", "measure_volts"]).decode('utf-8').strip().split('=')[1].replace('V', '')
    cpu_usage = subprocess.check_output(["top", "-bn1"]).decode('utf-8')
    cpu = [line for line in cpu_usage.split('\n') if "Cpu(s)" in line][0].split()[1]
    memory = subprocess.check_output(["free", "-m"]).decode('utf-8')
    memory = [line for line in memory.split('\n') if "Mem:" in line][0].split()
    memory_used = memory[2]
    memory_total = memory[1]
    memory_percentage = (int(memory_used) / int(memory_total)) * 100
    watt_input = float(voltage) * 0.85  # Assuming the current draw is approximately 0.85A
    return temp, voltage, watt_input, cpu, f"{memory_used}/{memory_total}MB {memory_percentage:.2f}%"

# Function to clear the OLED display before drawing new content
def clear_display():
    logging.debug("Clearing display")
    draw.rectangle((0, 0, oled.width, oled.height), outline=0, fill=0)

# Function to update OLED display
def update_oled_display():
    global blink_state, gateway, update_flag, last_update_time
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
        local_draw.text((title_x, 0), title, font=font15, fill=255)
        local_draw.text((85, 32), Temp, font=font12, fill=255)
        local_draw.text((0, 32), EthProfile, font=font12, fill=255)
        local_draw.text((0, 16), IP, font=font11, fill=255)
        local_draw.text((95, 16), port, font=font11, fill=255)
        local_draw.text((0, 48), "OMNICONPRO.COM /help", font=font10, fill=255)

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
        local_draw.text((0, 0), f"Temp: {temp}", font=font11, fill=255)
        local_draw.text((0, 16), f"Voltage: {voltage}V", font=font11, fill=255)
        local_draw.text((0, 32), f"Watt: {watt_input:.2f}W CPU: {cpu}", font=font11, fill=255)
        local_draw.text((0, 48), f"RAM: {memory}", font=font11, fill=255)

    else:
        options = menu_options[menu_state]
        state = load_state()
        for i, option in enumerate(options):
            if option:
                prefix = ""
                if menu_state == "network":
                    if (option == "DHCP" and state["network"] == DHCP_PROFILE) or (option == "STATIC IP" and state["network"] == STATIC_PROFILE):
                        prefix = "*"
                if menu_state == "system":
                    if (option == "COMPANION" and is_service_active("companion.service")) or (option == "SATELLITE" and is_service_active("satellite.service")):
                        prefix = "*"
                suffix = indicators[f"K{i+1}"]
                local_draw.text((0, i * 16), f"{prefix}{option}", font=font11, fill=255)
                local_draw.text((112, i * 16), suffix, font=font11, fill=255)

    oled.image(local_image.rotate(180))
    oled.show()
    blink_state = not blink_state
    update_flag = True
    logging.debug("OLED display updated")

def reset_to_main():
    global menu_state, ip_address, subnet_mask, gateway, timeout_flag
    if not timeout_flag:
        logging.debug("Timeout: Resetting to main display")
        menu_state = "default"
        ip_address = original_ip_address[:]
        subnet_mask = original_subnet_mask[:]
        gateway = original_gateway[:]
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
    global menu_state, menu_selection, ip_octet, last_interaction_time, timeout_flag
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
    else:
        menu_selection = 0
        activate_menu_item()
    update_oled_display()

@debounce
def button_k2_pressed():
    global menu_state, menu_selection, ip_octet, last_interaction_time, timeout_flag
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
    else:
        menu_selection = 1
        activate_menu_item()
    update_oled_display()

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
    elif menu_state in ["set_static_ip", "set_static_sm", "set_static_gw"]:
        ip_octet = (ip_octet - 1) % 4
    else:
        menu_selection = 2
        activate_menu_item()
    update_oled_display()

@debounce
def button_k4_pressed():
    global menu_state, menu_selection, ip_octet, ip_address, subnet_mask, gateway, original_ip_address, original_subnet_mask, original_gateway, last_interaction_time, timeout_flag
    logging.debug("K4 pressed")
    last_interaction_time = time.time()
    timeout_flag = False
    
    if menu_state in ["show_network_info", "show_pi_health"]:
        reset_to_main()
    elif menu_state == "default":
        menu_state = "show_network_info"
    elif menu_state in ["set_static_ip", "set_static_sm", "set_static_gw"]:
        ip_octet = (ip_octet + 1) % 4
    else:
        menu_selection = 3
        activate_menu_item()
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
        menu_selection = 0
    update_oled_display()  # Update the display immediately after change

def hold_k4():
    global menu_state, ip_address, subnet_mask, gateway, original_ip_address, original_subnet_mask, original_gateway, last_interaction_time
    logging.debug("K4 held for 1 seconds")
    last_interaction_time = time.time()
    
    if menu_state in ["set_static_ip", "set_static_sm", "set_static_gw"]:
        save_static_settings()
        apply_static_settings()
        original_ip_address = ip_address[:]
        original_subnet_mask = subnet_mask[:]
        original_gateway = gateway[:]
        menu_state = "set_static"
        menu_selection = 0
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

# Update OLED display in a separate thread
def update_oled():
    while True:
        update_oled_display()
        time.sleep(LOOPTIME)

def main():
    initial_setup()

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
    global menu_state, ip_octet, ip_address, subnet_mask, gateway
    start_time = time.time()
    while button.is_held:
        if menu_state == "set_static_ip":
            ip_address[ip_octet] = (ip_address[ip_octet] + increment) % 256
        elif menu_state == "set_static_sm":
            subnet_mask[ip_octet] = (subnet_mask[ip_octet] + increment) % 256
        elif menu_state == "set_static_gw":
            gateway[ip_octet] = (gateway[ip_octet] + increment) % 256
        update_oled_display()  # Update the display immediately to show the changing values
        time.sleep(.6)  # Reduce sleep time to make the changes more responsive


def check_timeout():
    global last_interaction_time
    while True:
        if time.time() - last_interaction_time > 20:  # 20 seconds timeout
            reset_to_main()
        time.sleep(1)

def activate_menu_item():
    global menu_state, menu_selection, ip_octet, ip_address, subnet_mask, gateway, original_ip_address, original_subnet_mask, original_gateway, last_interaction_time, timeout_flag
    options = menu_options[menu_state]
    selected_option = options[menu_selection]

    if menu_state == "main":
        if selected_option == "SYSTEM":
            menu_state = "system"
            menu_selection = 0
        elif selected_option == "NETWORK":
            menu_state = "network"
            menu_selection = 0
        elif selected_option == "POWER":
            menu_state = "power"
            menu_selection = 0
        elif selected_option == "EXIT":
            menu_state = "default"
            menu_selection = 0

    elif menu_state == "system":
        if selected_option == "COMPANION":
            toggle_service("companion")
            menu_state = "default"
        elif selected_option == "SATELLITE":
            toggle_service("satellite")
            menu_state = "default"
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
            menu_state = "default"

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

    logging.debug(f"Activated menu item: {selected_option}")
    update_oled_display()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.info('Script interrupted by user.')
