#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Omnicon Simple Web GUI - Remote Control for omnicon.py
This acts as a remote control for the existing omnicon.py script
"""

from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_cors import CORS
from functools import wraps
import json
import os
import logging
import subprocess
import hashlib
import secrets
import psutil
from datetime import datetime
import threading
import requests

# Try to import SocketIO support - if not available, fall back to simple terminal
SOCKETIO_AVAILABLE = False  # Disabled for now until we fix it properly

# Initialize Flask app
app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
CORS(app)

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Version
WEB_GUI_VERSION = "4.2.8"  # Web GUI now triggers updates via omnicon.py for OLED feedback

# Configuration
STATE_FILE = "state.json"
COMMAND_FILE = "web_command.json"  # File to communicate with omnicon.py
CONFIG_FILE = "web_config.json"

# Default configuration
DEFAULT_CONFIG = {
    "username": "admin",
    "password": hashlib.sha256("omnicon".encode()).hexdigest(),
    "port": 8080
}

def load_config():
    """Load web GUI configuration"""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
    except:
        pass
    save_config(DEFAULT_CONFIG)
    return DEFAULT_CONFIG

def save_config(config):
    """Save web GUI configuration"""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        return True
    except:
        return False

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Login disabled - always allow access
        return f(*args, **kwargs)
    return decorated_function

def load_state():
    """Load system state from omnicon.py's state file"""
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except:
        return {
            "service": "companion",
            "network": "STATIC",
            "static_ip": [192, 168, 0, 100],
            "subnet_mask": [255, 255, 255, 0],
            "gateway": [192, 168, 0, 1],
            "time_format_24hr": True
        }

def send_command_to_omnicon(command, params=None):
    """Send a command to omnicon.py via command file"""
    try:
        cmd_data = {
            "command": command,
            "params": params or {},
            "timestamp": datetime.now().isoformat()
        }

        # Write command file
        with open(COMMAND_FILE, 'w') as f:
            json.dump(cmd_data, f)

        logging.info(f"Sent command to omnicon: {command}")

        # Trigger omnicon.py to process the command
        # This could be done via a signal, file watch, or periodic check in omnicon.py
        # For now, we'll use a simple touch file mechanism
        open('trigger_command', 'a').close()

        return True
    except Exception as e:
        logging.error(f"Failed to send command: {e}")
        return False

def get_system_info():
    """Get current system information"""
    try:
        state = load_state()

        # Basic system info
        cpu_usage = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        # Get temperature
        try:
            temp_output = subprocess.check_output(["vcgencmd", "measure_temp"], text=True)
            temp = temp_output.strip().split('=')[1]
        except:
            temp = "N/A"

        # Get IP
        try:
            ip_output = subprocess.check_output(["hostname", "-I"], text=True)
            ip_address = ip_output.strip().split()[0] if ip_output.strip() else "N/A"
        except:
            ip_address = "N/A"

        # Check which service is active from state
        active_service = state.get("service", "none")

        # Determine port based on service
        if active_service == "companion":
            service_port = "8000"
        elif active_service == "satellite":
            service_port = "9999"
        else:
            service_port = "N/A"

        return {
            "temperature": temp,
            "cpu_usage": round(cpu_usage, 2),
            "memory": {
                "used": round(memory.used / (1024**3), 2),
                "total": round(memory.total / (1024**3), 2),
                "percent": round(memory.percent, 2)
            },
            "disk": {
                "used": round(disk.used / (1024**3), 2),
                "total": round(disk.total / (1024**3), 2),
                "percent": round(disk.percent, 2)
            },
            "ip_address": ip_address,
            "active_service": active_service,
            "service_port": service_port,
            "network_mode": state.get("network", "STATIC"),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logging.error(f"Error getting system info: {e}")
        return {"error": str(e)}

def get_network_settings():
    """Get network settings from state file"""
    try:
        state = load_state()
        network_mode = state.get("network", "STATIC")

        # Get current IP
        try:
            ip_output = subprocess.check_output(["hostname", "-I"], text=True)
            current_ip = ip_output.strip().split()[0] if ip_output.strip() else "N/A"
        except:
            current_ip = "N/A"

        # Get actual network configuration
        actual_subnet = "N/A"
        actual_gateway = "N/A"
        actual_dns = "N/A"

        if network_mode == "DHCP":
            # Get actual network info from the system
            try:
                # Get subnet mask and interface info
                import socket
                import fcntl
                import struct

                # Find the primary network interface (usually eth0 or wlan0)
                interface = None
                try:
                    # Try eth0 first
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    fcntl.ioctl(sock.fileno(), 0x8915, struct.pack('256s', b'eth0'))
                    interface = 'eth0'
                except:
                    try:
                        # Try wlan0
                        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                        fcntl.ioctl(sock.fileno(), 0x8915, struct.pack('256s', b'wlan0'))
                        interface = 'wlan0'
                    except:
                        pass

                # Get subnet mask using ip command
                if interface:
                    ip_info = subprocess.check_output(["ip", "addr", "show", interface], text=True)
                    for line in ip_info.split('\n'):
                        if 'inet ' in line and not 'inet6' in line:
                            # Extract IP and subnet from line like: inet 192.168.1.100/24 brd ...
                            parts = line.strip().split()
                            if len(parts) >= 2:
                                ip_with_prefix = parts[1]
                                if '/' in ip_with_prefix:
                                    prefix = int(ip_with_prefix.split('/')[1])
                                    # Convert prefix to subnet mask
                                    mask = (0xffffffff << (32 - prefix)) & 0xffffffff
                                    actual_subnet = '.'.join([str((mask >> (8 * i)) & 0xff) for i in range(3, -1, -1)])

                # Get gateway
                route_output = subprocess.check_output(["ip", "route", "show", "default"], text=True)
                if route_output:
                    # Extract gateway from line like: default via 192.168.1.1 dev eth0 ...
                    parts = route_output.strip().split()
                    if len(parts) >= 3 and parts[0] == 'default' and parts[1] == 'via':
                        actual_gateway = parts[2]

                # Get DNS servers
                try:
                    with open('/etc/resolv.conf', 'r') as f:
                        resolv_content = f.read()
                        dns_servers = []
                        for line in resolv_content.split('\n'):
                            if line.startswith('nameserver'):
                                dns_servers.append(line.split()[1])
                        if dns_servers:
                            actual_dns = ', '.join(dns_servers[:2])  # Show first 2 DNS servers
                except:
                    pass

            except Exception as e:
                logging.error(f"Error getting DHCP network info: {e}")

            # In DHCP mode, return actual network configuration
            return {
                "current_ip": current_ip,
                "static_ip": '.'.join(map(str, state.get("static_ip", [192, 168, 0, 100]))),
                "static_subnet": '.'.join(map(str, state.get("subnet_mask", [255, 255, 255, 0]))),
                "static_gateway": '.'.join(map(str, state.get("gateway", [192, 168, 0, 1]))),
                "actual_subnet": actual_subnet,
                "actual_gateway": actual_gateway,
                "actual_dns": actual_dns,
                "network_mode": network_mode
            }
        else:
            # In STATIC mode, return configured values
            return {
                "current_ip": current_ip,
                "static_ip": '.'.join(map(str, state.get("static_ip", [192, 168, 0, 100]))),
                "static_subnet": '.'.join(map(str, state.get("subnet_mask", [255, 255, 255, 0]))),
                "static_gateway": '.'.join(map(str, state.get("gateway", [192, 168, 0, 1]))),
                "actual_subnet": '.'.join(map(str, state.get("subnet_mask", [255, 255, 255, 0]))),
                "actual_gateway": '.'.join(map(str, state.get("gateway", [192, 168, 0, 1]))),
                "actual_dns": "N/A",
                "network_mode": network_mode
            }
    except Exception as e:
        logging.error(f"Error getting network settings: {e}")
        return {"error": str(e)}

# Routes
@app.route('/')
def index():
    # No login required
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    config = load_config()
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        password_hash = hashlib.sha256(password.encode()).hexdigest()

        if username == config['username'] and password_hash == config['password']:
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error='Invalid credentials')

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/terminal')
@login_required
def terminal():
    """Terminal page for interactive updates"""
    # For now, just use simple terminal until we fix xterm
    return render_template('terminal_simple.html')

@app.route('/api/system/info')
@login_required
def api_system_info():
    return jsonify(get_system_info())

@app.route('/api/network/settings')
@login_required
def api_network_settings():
    return jsonify(get_network_settings())

@app.route('/api/service/toggle', methods=['POST'])
@login_required
def api_toggle_service():
    """Send service toggle command to omnicon.py"""
    try:
        data = request.get_json()
        service = data.get('service')

        if service not in ['companion', 'satellite']:
            return jsonify({"success": False, "error": "Invalid service"}), 400

        # Send command to omnicon.py
        success = send_command_to_omnicon('toggle_service', {'service': service})

        if success:
            return jsonify({"success": True, "service": service})
        else:
            return jsonify({"success": False, "error": "Failed to send command"}), 500

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/network/mode', methods=['POST'])
@login_required
def api_network_mode():
    """Send network mode command to omnicon.py"""
    try:
        data = request.get_json()
        mode = data.get('mode')

        if mode not in ['DHCP', 'STATIC']:
            return jsonify({"success": False, "error": "Invalid mode"}), 400

        # Send command to omnicon.py
        success = send_command_to_omnicon('toggle_network', {'network': mode})

        if success:
            return jsonify({"success": True, "mode": mode})
        else:
            return jsonify({"success": False, "error": "Failed to send command"}), 500

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/network/static', methods=['POST'])
@login_required
def api_set_static():
    """Send static IP configuration to omnicon.py"""
    try:
        data = request.get_json()

        # Send command to omnicon.py
        success = send_command_to_omnicon('set_static_ip', {
            'ip': data.get('ip'),
            'subnet': data.get('subnet'),
            'gateway': data.get('gateway')
        })

        if success:
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "error": "Failed to send command"}), 500

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/datetime', methods=['GET', 'POST'])
@login_required
def api_datetime():
    """Get or set system date/time via omnicon.py"""
    if request.method == 'GET':
        state = load_state()
        current_time = datetime.now()

        # Get current timezone - prioritize file system sources over timedatectl
        # (timedatectl can be out of sync after changes via raspi-config)
        current_tz = "UTC"
        tz_detected = False

        # Method 1: Read from /etc/timezone (MOST RELIABLE after raspi-config changes)
        if not tz_detected:
            try:
                with open('/etc/timezone', 'r') as f:
                    tz_from_file = f.read().strip()
                    if tz_from_file:
                        current_tz = tz_from_file
                        tz_detected = True
                        logging.info(f"Detected timezone from /etc/timezone: {current_tz}")
            except Exception as e:
                logging.warning(f"Failed to read /etc/timezone: {e}")

        # Method 2: readlink /etc/localtime (second most reliable)
        if not tz_detected:
            try:
                import os
                localtime_path = os.path.realpath("/etc/localtime")
                if "/zoneinfo/" in localtime_path:
                    current_tz = localtime_path.split("/zoneinfo/")[1]
                    tz_detected = True
                    logging.info(f"Detected timezone from /etc/localtime: {current_tz}")
            except Exception as e:
                logging.warning(f"Failed to read timezone from /etc/localtime: {e}")

        # Method 3: Use timedatectl as fallback (can be out of sync)
        if not tz_detected:
            try:
                # Try timedatectl show first (simpler output)
                tz_output = subprocess.check_output(["timedatectl", "show", "--property=Timezone", "--value"], text=True)
                if tz_output.strip():
                    current_tz = tz_output.strip()
                    tz_detected = True
                    logging.info(f"Detected timezone from timedatectl show: {current_tz}")
            except Exception as e:
                logging.warning(f"Failed to get timezone from timedatectl show: {e}")

                # Try timedatectl status
                try:
                    tz_output = subprocess.check_output(["timedatectl", "status"], text=True)
                    for line in tz_output.split('\n'):
                        if 'Time zone:' in line:
                            # Extract timezone from line like "Time zone: America/New_York (EST, -0500)"
                            tz_parts = line.split('Time zone:')[1].strip()
                            current_tz = tz_parts.split()[0] if tz_parts else "UTC"
                            tz_detected = True
                            logging.info(f"Detected timezone from timedatectl status: {current_tz}")
                            break
                except Exception as e:
                    logging.warning(f"Failed to get timezone from timedatectl status: {e}")

        logging.info(f"Final detected timezone: {current_tz}")

        # Get list of available timezones
        try:
            tz_list_output = subprocess.check_output(["timedatectl", "list-timezones"], text=True)
            timezones = [tz.strip() for tz in tz_list_output.split('\n') if tz.strip()]
        except:
            timezones = ["UTC", "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
                        "Europe/London", "Europe/Paris", "Asia/Tokyo", "Australia/Sydney"]

        response = jsonify({
            "datetime": current_time.isoformat(),
            "date": current_time.strftime("%Y-%m-%d"),
            "time": current_time.strftime("%H:%M:%S"),
            "format_24hr": state.get("time_format_24hr", True),
            "timezone": current_tz,
            "available_timezones": timezones,
            "refresh_timestamp": datetime.now().timestamp()  # Add timestamp to verify fresh data
        })
        # Add headers to prevent caching
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response

    elif request.method == 'POST':
        try:
            data = request.get_json()

            # Send command to omnicon.py
            success = send_command_to_omnicon('set_datetime', data)

            if success:
                return jsonify({"success": True})
            else:
                return jsonify({"success": False, "error": "Failed to send command"}), 500

        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/timezone/debug')
@login_required
def api_timezone_debug():
    """Debug endpoint to check timezone detection"""
    debug_info = {}

    # Test 1: timedatectl status
    try:
        result = subprocess.run(["timedatectl", "status"], capture_output=True, text=True, timeout=5)
        debug_info['timedatectl_status'] = {
            'stdout': result.stdout,
            'stderr': result.stderr,
            'returncode': result.returncode
        }
    except Exception as e:
        debug_info['timedatectl_status'] = {'error': str(e)}

    # Test 2: timedatectl show
    try:
        result = subprocess.run(["timedatectl", "show", "--property=Timezone", "--value"],
                              capture_output=True, text=True, timeout=5)
        debug_info['timedatectl_show'] = {
            'stdout': result.stdout.strip(),
            'stderr': result.stderr,
            'returncode': result.returncode
        }
    except Exception as e:
        debug_info['timedatectl_show'] = {'error': str(e)}

    # Test 3: /etc/timezone
    try:
        with open('/etc/timezone', 'r') as f:
            debug_info['etc_timezone'] = f.read().strip()
    except Exception as e:
        debug_info['etc_timezone'] = {'error': str(e)}

    # Test 4: /etc/localtime
    try:
        import os
        localtime_link = os.readlink('/etc/localtime')
        debug_info['etc_localtime'] = {
            'link': localtime_link,
            'parsed': localtime_link.split('/zoneinfo/')[-1] if '/zoneinfo/' in localtime_link else 'parse_failed'
        }
    except Exception as e:
        debug_info['etc_localtime'] = {'error': str(e)}

    # Test 5: date command
    try:
        result = subprocess.run(["date", "+%Z"], capture_output=True, text=True, timeout=5)
        debug_info['date_command'] = result.stdout.strip()
    except Exception as e:
        debug_info['date_command'] = {'error': str(e)}

    # Current user
    try:
        import getpass
        debug_info['current_user'] = getpass.getuser()
    except:
        debug_info['current_user'] = 'unknown'

    return jsonify(debug_info)

@app.route('/api/timezone', methods=['POST'])
@login_required
def api_set_timezone():
    """Set system timezone"""
    try:
        data = request.get_json()
        timezone = data.get('timezone')

        if not timezone:
            return jsonify({"success": False, "error": "No timezone specified"}), 400

        # Validate timezone exists
        try:
            tz_list = subprocess.check_output(["timedatectl", "list-timezones"], text=True)
            if timezone not in tz_list:
                return jsonify({"success": False, "error": f"Invalid timezone: {timezone}"}), 400
        except:
            pass  # Continue anyway

        # Set timezone directly using timedatectl
        try:
            # Use sudo to set the timezone
            result = subprocess.run(
                ["sudo", "timedatectl", "set-timezone", timezone],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                logging.info(f"Successfully set timezone to {timezone}")

                # Also update /etc/timezone for compatibility
                try:
                    subprocess.run(["sudo", "bash", "-c", f"echo '{timezone}' > /etc/timezone"],
                                 capture_output=True, text=True)
                except:
                    pass  # Not critical if this fails

                return jsonify({"success": True, "message": f"Timezone set to {timezone}"})
            else:
                error_msg = result.stderr or "Failed to set timezone"
                logging.error(f"Failed to set timezone: {error_msg}")
                return jsonify({"success": False, "error": error_msg}), 500

        except subprocess.TimeoutExpired:
            return jsonify({"success": False, "error": "Command timed out"}), 500
        except Exception as e:
            logging.error(f"Error executing timedatectl: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    except Exception as e:
        logging.error(f"Error setting timezone: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/rtc/sync', methods=['POST'])
@login_required
def api_rtc_sync():
    """Sync RTC with system time"""
    try:
        # Run hwclock command to sync RTC with system time
        result = subprocess.run(
            ["sudo", "hwclock", "--systohc"],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode == 0:
            logging.info("RTC synced with system time")
            return jsonify({"success": True, "message": "RTC synced successfully"})
        else:
            error_msg = result.stderr or "Failed to sync RTC"
            logging.error(f"Failed to sync RTC: {error_msg}")
            return jsonify({"success": False, "error": error_msg}), 500

    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "Command timed out"}), 500
    except Exception as e:
        logging.error(f"Error syncing RTC: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/rtc/check')
@login_required
def api_rtc_check():
    """Check RTC time"""
    try:
        # Read RTC time
        rtc_result = subprocess.run(
            ["sudo", "hwclock", "-r"],
            capture_output=True,
            text=True,
            timeout=5
        )

        rtc_time = "Unable to read"
        if rtc_result.returncode == 0 and rtc_result.stdout:
            # Parse the hwclock output
            rtc_time = rtc_result.stdout.strip()

        # Also get system time for comparison
        system_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return jsonify({
            "rtc_time": rtc_time,
            "system_time": system_time,
            "success": True
        })

    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "Command timed out"}), 500
    except Exception as e:
        logging.error(f"Error checking RTC: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/system/power', methods=['POST'])
@login_required
def api_system_power():
    """Send power command to omnicon.py"""
    try:
        data = request.get_json()
        action = data.get('action')

        if action not in ['reboot', 'shutdown']:
            return jsonify({"success": False, "error": "Invalid action"}), 400

        # Send command to omnicon.py
        success = send_command_to_omnicon('power', {'action': action})

        if success:
            return jsonify({"success": True, "message": f"System {action}ing..."})
        else:
            return jsonify({"success": False, "error": "Failed to send command"}), 500

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# Simulate button presses
@app.route('/api/button/press', methods=['POST'])
@login_required
def api_button_press():
    """Simulate a button press in omnicon.py"""
    try:
        data = request.get_json()
        button = data.get('button')  # K1, K2, K3, K4

        if button not in ['K1', 'K2', 'K3', 'K4']:
            return jsonify({"success": False, "error": "Invalid button"}), 400

        # Send command to omnicon.py
        success = send_command_to_omnicon('button_press', {'button': button})

        if success:
            return jsonify({"success": True, "button": button})
        else:
            return jsonify({"success": False, "error": "Failed to send command"}), 500

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# Simple Terminal handling (no WebSocket required)
terminal_sessions = {}

# PTY-based terminal sessions for WebSocket connections (disabled for now)
pty_sessions = {}

# PTY Terminal class removed temporarily while we fix issues
if False:  # SOCKETIO_AVAILABLE disabled
    class PTYTerminalSession:
        """PTY-based terminal session for real terminal emulation"""
        def __init__(self, sid):
            self.sid = sid
            self.pid = None
            self.fd = None
            self.running = False

        def start(self):
            """Start a PTY session with a shell"""
            try:
                # Create a new pseudo-terminal
                self.pid, self.fd = pty.fork()

                if self.pid == 0:
                    # Child process - exec shell
                    os.environ['TERM'] = 'xterm-256color'
                    os.execvp('/bin/bash', ['/bin/bash'])
                else:
                    # Parent process
                    self.running = True
                    # Set non-blocking
                    flags = fcntl.fcntl(self.fd, fcntl.F_GETFL)
                    fcntl.fcntl(self.fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

                    # Start reader thread
                    threading.Thread(target=self._read_output, daemon=True).start()
                    return True

            except Exception as e:
                logging.error(f"Failed to start PTY session: {e}")
                return False

        def _read_output(self):
            """Read output from PTY and send to client"""
            while self.running:
                try:
                    # Check if data is available
                    ready, _, _ = select.select([self.fd], [], [], 0.1)
                    if ready:
                        output = os.read(self.fd, 4096).decode('utf-8', errors='replace')
                        if output:
                            # Send to WebSocket client
                            socketio.emit('terminal_output', output, room=self.sid)
                        else:
                            # EOF - process ended
                            self.stop()
                            break
                except OSError:
                    # Process ended
                    self.stop()
                    break
                except Exception as e:
                    logging.error(f"Error reading PTY output: {e}")

        def write(self, data):
            """Write data to PTY"""
            if self.fd and self.running:
                try:
                    os.write(self.fd, data.encode())
                    return True
                except Exception as e:
                    logging.error(f"Error writing to PTY: {e}")
                    return False
            return False

        def resize(self, cols, rows):
            """Resize the terminal"""
            if self.fd:
                try:
                    # Send terminal size change
                    winsize = struct.pack('HHHH', rows, cols, 0, 0)
                    fcntl.ioctl(self.fd, termios.TIOCSWINSZ, winsize)
                    return True
                except Exception as e:
                    logging.error(f"Error resizing PTY: {e}")
                    return False
            return False

        def stop(self):
            """Stop the PTY session"""
            self.running = False
            if self.fd:
                try:
                    os.close(self.fd)
                except:
                    pass
            if self.pid:
                try:
                    os.kill(self.pid, 9)
                    os.waitpid(self.pid, os.WNOHANG)
                except:
                    pass

class SimpleTerminalSession:
    """Manage a terminal session without WebSockets"""
    def __init__(self, session_id):
        self.session_id = session_id
        self.process = None
        self.output = []
        self.running = False

    def start_command(self, command):
        """Start a terminal command"""
        try:
            self.running = True
            self.output = [f"$ {command}\n"]

            # Start the process
            self.process = subprocess.Popen(
                command,
                shell=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=0
            )

            # Start output reader thread
            def read_output():
                while self.running and self.process:
                    try:
                        line = self.process.stdout.readline()
                        if line:
                            self.output.append(line)
                        elif self.process.poll() is not None:
                            self.running = False
                            break
                    except:
                        break

            thread = threading.Thread(target=read_output, daemon=True)
            thread.start()
            return True

        except Exception as e:
            self.output.append(f"Error: {str(e)}\n")
            self.running = False
            return False

    def send_input(self, text):
        """Send input to the process"""
        if self.process and self.running:
            try:
                self.process.stdin.write(text + '\n')
                self.process.stdin.flush()
                self.output.append(f"> {text}\n")
                return True
            except:
                return False
        return False

    def send_key(self, key):
        """Send special key to process"""
        if self.process and self.running:
            try:
                if key == 'up':
                    # Send up arrow escape sequence
                    self.process.stdin.write('\x1b[A')
                elif key == 'down':
                    # Send down arrow escape sequence
                    self.process.stdin.write('\x1b[B')
                elif key == 'enter':
                    self.process.stdin.write('\n')
                elif key == 'ctrl-c':
                    self.process.terminate()
                    self.output.append("\nProcess terminated\n")
                    self.running = False

                if self.running:
                    self.process.stdin.flush()
                return True
            except:
                return False
        return False

    def get_output(self):
        """Get all output"""
        return ''.join(self.output)

    def stop(self):
        """Stop the process"""
        self.running = False
        if self.process:
            try:
                self.process.terminate()
                import time
                time.sleep(0.5)
                if self.process.poll() is None:
                    self.process.kill()
            except:
                pass

# Omnicon Update API routes
@app.route('/api/omnicon/check_update')
@login_required
def api_check_omnicon_update():
    """Check for Omnicon updates from GitHub"""
    try:
        # Get current version from omnicon.py
        current_version = None
        try:
            with open('/home/omnicon/OLED_Stats/omnicon.py', 'r') as f:
                for line in f:
                    if line.startswith("# V"):
                        current_version = line.strip().split(' ')[1]
                        break
        except:
            current_version = "Unknown"

        # Fetch available versions from GitHub
        available_versions = []
        headers_options = [
            {
                'Accept': 'application/vnd.github.v3+json',
                'User-Agent': 'Mozilla/5.0 (X11; Linux armv7l) AppleWebKit/537.36'
            },
            {
                'User-Agent': 'Omnicon-Updater/4.2.2'
            },
            {}  # Try with no headers as last resort
        ]

        for headers in headers_options:
            try:
                logging.info(f"Attempting GitHub API with headers: {headers}")
                response = requests.get("https://api.github.com/repos/RUDEWORLD/OMNICON/tags",
                                       headers=headers, timeout=15)
                response.raise_for_status()
                tags = response.json()
                available_versions = [tag['name'] for tag in tags]
                logging.info(f"Successfully fetched {len(tags)} tags")
                break
            except Exception as e:
                logging.error(f"Failed attempt with headers {headers}: {e}")
                continue

        # Get the latest version
        if available_versions:
            latest_version = available_versions[0]
        else:
            latest_version = "Check Failed"
            logging.error("Failed to fetch any GitHub tags after all attempts")

        # Check if update is available
        update_available = False
        if current_version != "Unknown" and latest_version != "Check Failed":
            try:
                current_tuple = tuple(map(int, current_version.strip('V').split('.')))
                latest_tuple = tuple(map(int, latest_version.strip('V').split('.')))
                update_available = latest_tuple > current_tuple
            except:
                pass

        return jsonify({
            'current_version': current_version,
            'latest_version': latest_version,
            'available_versions': available_versions,
            'update_available': update_available
        })

    except Exception as e:
        logging.error(f"Error checking for updates: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/omnicon/update', methods=['POST'])
@login_required
def api_update_omnicon():
    """Trigger Omnicon update via omnicon.py command"""
    try:
        data = request.get_json()
        version = data.get('version')

        if not version:
            return jsonify({"success": False, "error": "No version specified"}), 400

        # Send update command to omnicon.py - it will handle the update process
        success = send_command_to_omnicon('update_omnicon', {'version': version})

        if success:
            return jsonify({"success": True, "message": f"Updating to {version}. The system will restart."})
        else:
            return jsonify({"success": False, "error": "Failed to send update command"}), 500

    except Exception as e:
        logging.error(f"Error updating omnicon: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# Application versions and updates
@app.route('/api/versions', methods=['GET'])
@login_required
def api_get_versions():
    """Get all application versions"""
    try:
        import re

        # Get Companion version
        companion_version = 'Unknown'
        try:
            with open('/opt/companion/package.json', 'r') as f:
                data = json.load(f)
                version = data.get('version', 'Unknown')
                # Extract only the first three numbers
                match = re.match(r'^(\d+\.\d+\.\d+)', version)
                if match:
                    companion_version = match.group(1)
        except:
            pass

        # Get Satellite version
        satellite_version = 'Unknown'
        try:
            with open('/opt/companion-satellite/satellite/package.json', 'r') as f:
                data = json.load(f)
                version = data.get('version', 'Unknown')
                # Extract only the first three numbers
                match = re.match(r'^(\d+\.\d+\.\d+)', version)
                if match:
                    satellite_version = match.group(1)
        except:
            pass

        # Get Omnicon version
        omnicon_version = 'Unknown'
        try:
            with open('/home/omnicon/OLED_Stats/omnicon.py', 'r') as f:
                for line in f:
                    if line.startswith("# V"):
                        omnicon_version = line.strip().split(' ')[1]
                        break
        except:
            pass

        return jsonify({
            'omnicon': omnicon_version,
            'companion': companion_version,
            'satellite': satellite_version
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/companion/update', methods=['POST'])
@login_required
def api_update_companion():
    """Update Companion to stable version only - triggers via omnicon.py for OLED feedback"""
    try:
        # Send command to omnicon.py so OLED shows update progress
        success = send_command_to_omnicon('update_companion_stable', {})

        if success:
            return jsonify({
                "success": True,
                "message": "Starting Companion stable update. Check OLED for progress. System will reboot when complete."
            })
        else:
            return jsonify({"success": False, "error": "Failed to send update command"}), 500

    except Exception as e:
        logging.error(f"Error updating companion: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/satellite/update', methods=['POST'])
@login_required
def api_update_satellite():
    """Update Satellite to stable version only - triggers via omnicon.py for OLED feedback"""
    try:
        # Send command to omnicon.py so OLED shows update progress
        success = send_command_to_omnicon('update_satellite_stable', {})

        if success:
            return jsonify({
                "success": True,
                "message": "Starting Satellite stable update. Check OLED for progress. System will reboot when complete."
            })
        else:
            return jsonify({"success": False, "error": "Failed to send update command"}), 500

    except Exception as e:
        logging.error(f"Error updating satellite: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# Terminal API routes
@app.route('/api/terminal/start', methods=['POST'])
@login_required
def start_terminal():
    """Start a terminal command"""
    try:
        data = request.get_json()
        command = data.get('command', 'echo "No command specified"')

        # Get or create session ID from Flask session
        if 'terminal_session_id' not in session:
            session['terminal_session_id'] = secrets.token_hex(16)

        session_id = session['terminal_session_id']

        # Stop existing session if any
        if session_id in terminal_sessions:
            terminal_sessions[session_id].stop()

        # Create new terminal session
        terminal = SimpleTerminalSession(session_id)
        terminal_sessions[session_id] = terminal

        if terminal.start_command(command):
            return jsonify({'success': True, 'session_id': session_id})
        else:
            return jsonify({'success': False, 'error': 'Failed to start process'})

    except Exception as e:
        logging.error(f"Error starting terminal: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/terminal/input', methods=['POST'])
@login_required
def send_terminal_input():
    """Send input to terminal"""
    try:
        session_id = session.get('terminal_session_id')
        if not session_id or session_id not in terminal_sessions:
            return jsonify({'error': 'No active session'}), 400

        data = request.get_json()
        text = data.get('text', '')

        terminal = terminal_sessions[session_id]
        if terminal.send_input(text):
            return jsonify({'success': True})
        else:
            return jsonify({'success': False})

    except Exception as e:
        logging.error(f"Error sending input: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/terminal/key', methods=['POST'])
@login_required
def send_terminal_key():
    """Send special key to terminal"""
    try:
        session_id = session.get('terminal_session_id')
        if not session_id or session_id not in terminal_sessions:
            return jsonify({'error': 'No active session'}), 400

        data = request.get_json()
        key = data.get('key', '')

        terminal = terminal_sessions[session_id]
        if terminal.send_key(key):
            return jsonify({'success': True})
        else:
            return jsonify({'success': False})

    except Exception as e:
        logging.error(f"Error sending key: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/terminal/output')
@login_required
def get_terminal_output():
    """Get terminal output"""
    try:
        session_id = session.get('terminal_session_id')
        if not session_id or session_id not in terminal_sessions:
            return jsonify({'output': '', 'running': False})

        terminal = terminal_sessions[session_id]
        return jsonify({
            'output': terminal.get_output(),
            'running': terminal.running
        })

    except Exception as e:
        logging.error(f"Error getting output: {e}")
        return jsonify({'output': '', 'running': False, 'error': str(e)})

# WebSocket handlers for xterm.js terminal (disabled for now)
if False:  # SOCKETIO_AVAILABLE disabled
    @socketio.on('connect', namespace='/ws/terminal')
    def handle_terminal_connect():
        """Handle WebSocket connection for terminal"""
        sid = request.sid
        logging.info(f"Terminal WebSocket connected: {sid}")

        # Create new PTY session
        terminal = PTYTerminalSession(sid)
        pty_sessions[sid] = terminal

        if terminal.start():
            emit('terminal_output', '\r\nTerminal connected. Type commands below.\r\n')
        else:
            emit('terminal_output', '\r\nFailed to start terminal session.\r\n')
            disconnect()

    @socketio.on('disconnect', namespace='/ws/terminal')
    def handle_terminal_disconnect():
        """Handle WebSocket disconnection"""
        sid = request.sid
        logging.info(f"Terminal WebSocket disconnected: {sid}")

        # Clean up PTY session
        if sid in pty_sessions:
            pty_sessions[sid].stop()
            del pty_sessions[sid]

    @socketio.on('terminal_input', namespace='/ws/terminal')
    def handle_terminal_input(data):
        """Handle terminal input from client"""
        sid = request.sid

        if sid not in pty_sessions:
            emit('terminal_output', '\r\nNo active session. Please reconnect.\r\n')
            return

        terminal = pty_sessions[sid]

        # Handle different message types
        msg_data = data if isinstance(data, dict) else json.loads(data)
        msg_type = msg_data.get('type', 'input')

        if msg_type == 'input':
            # Regular terminal input
            terminal.write(msg_data.get('data', ''))

        elif msg_type == 'resize':
            # Terminal resize
            cols = msg_data.get('cols', 80)
            rows = msg_data.get('rows', 24)
            terminal.resize(cols, rows)

        elif msg_type == 'command':
            # Execute a command
            command = msg_data.get('command', '')
            if command:
                terminal.write(command + '\n')

if __name__ == '__main__':
    config = load_config()

    print("======================================")
    print(f"Omnicon Web GUI v{WEB_GUI_VERSION} - Remote Control")
    print("======================================")
    print(f"Starting on port {config.get('port', 8080)}")
    print("This web GUI acts as a remote control for omnicon.py")
    print("Now with integrated terminal for updates!")
    print("")

    # Run Flask app
    print("Running with simple terminal")
    app.run(host='0.0.0.0', port=config.get('port', 8080), debug=False)
