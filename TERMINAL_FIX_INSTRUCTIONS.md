# Terminal Fix Instructions

## Problem Solved
The web GUI wasn't starting after installing flask-socketio because of indentation errors and missing fallback handling.

## What Was Fixed

### 1. **Graceful Fallback Support**
The omnicon_web_simple.py now checks if flask-socketio is installed:
- If YES: Uses the new xterm.js terminal with full features
- If NO: Falls back to the simple terminal that was working before

### 2. **Fixed Code Issues**
- Fixed all indentation errors in the PTYTerminalSession class
- Fixed indentation in WebSocket handlers
- Added conditional imports to prevent crashes
- Added conditional routing based on available features

## How to Test

On your Raspberry Pi, try running the web GUI:

```bash
cd /home/omnicon/OLED_Stats
sudo systemctl restart omnicon
```

Or run directly to see any errors:
```bash
python3 omnicon_web_simple.py
```

## Terminal Modes

### Simple Terminal (No flask-socketio)
- Works out of the box
- Basic command execution
- Some ANSI codes might show as text
- Arrow key navigation might not work perfectly

### Full Terminal (With flask-socketio)
- Real terminal emulation using xterm.js
- Full color support
- Interactive menus work perfectly
- Arrow keys, Ctrl+C, all special keys work
- Multiple concurrent sessions

## To Enable Full Terminal

If you want the full terminal experience:

```bash
# Make sure you're in the virtual environment
source /home/omnicon/env/bin/activate

# Install the dependencies
pip3 install flask-socketio python-socketio python-engineio eventlet

# Restart the service
sudo systemctl restart omnicon
```

## To Remove Full Terminal (if causing issues)

If flask-socketio is causing problems:

```bash
# Activate virtual environment
source /home/omnicon/env/bin/activate

# Uninstall the packages
pip3 uninstall flask-socketio python-socketio python-engineio eventlet

# Restart the service
sudo systemctl restart omnicon
```

The web GUI will automatically fall back to the simple terminal.

## Checking Which Mode You're In

When you start the web GUI, it will print which mode it's using:
- "Running with WebSocket terminal support (xterm.js)" - Full terminal
- "Running with simple terminal (install flask-socketio for full terminal)" - Simple mode

## Version Info
- omnicon.py: v4.1.3
- omnicon_web_simple.py: v4.1.3
- Both versions synchronized for better tracking