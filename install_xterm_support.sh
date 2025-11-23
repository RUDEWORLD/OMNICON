#!/bin/bash
# Install xterm.js terminal support dependencies

echo "Installing xterm.js terminal support..."
echo "This will add real terminal emulation to the web GUI"
echo ""

# Activate virtual environment if it exists
if [ -d "/home/omnicon/env" ]; then
    echo "Activating virtual environment..."
    source /home/omnicon/env/bin/activate
fi

# Install the required packages
echo "Installing Flask-SocketIO and dependencies..."
pip3 install flask-socketio python-socketio python-engineio eventlet

echo ""
echo "Installation complete!"
echo ""
echo "IMPORTANT: After installing, restart the omnicon service:"
echo "  sudo systemctl restart omnicon"
echo ""
echo "The terminal page will now use a real terminal emulator with full support for:"
echo "  - ANSI colors and escape codes"
echo "  - Interactive menus (arrow key navigation)"
echo "  - Real-time output"
echo "  - Multiple concurrent sessions"
echo ""
echo "Access the terminal at: http://[your-ip]:8080/terminal"