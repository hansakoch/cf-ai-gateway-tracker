#!/bin/bash
# Auto-update CF AI Gateway Tracker from GitHub
# Run via cron or systemd timer

REPO_DIR="/tmp/cf-ai-gateway-tracker"
INSTALL_DIR="$HOME/.local/bin"

# Clone if missing
if [ ! -d "$REPO_DIR" ]; then
    git clone https://github.com/hansakoch/cf-ai-gateway-tracker.git "$REPO_DIR"
fi

# Pull latest
cd "$REPO_DIR" && git pull --quiet 2>/dev/null

# Install collector and wrapper
cp src/collector.py "$INSTALL_DIR/cf-ai-gateway-collector"
cp src/omarchy-agent-usage-cf-gateway "$INSTALL_DIR/omarchy-agent-usage-cf-gateway"
chmod +x "$INSTALL_DIR/omarchy-agent-usage-cf-gateway"

# Install icon if Omarchy panel exists
if [ -d /usr/share/omarchy/shell/plugins/agents/assets ]; then
    sudo cp assets/cf-ai-gateway.svg /usr/share/omarchy/shell/plugins/agents/assets/ 2>/dev/null
fi

# Symlink into Omarchy bin if it exists
if [ -d /usr/share/omarchy/bin ]; then
    sudo ln -sf "$INSTALL_DIR/omarchy-agent-usage-cf-gateway" /usr/share/omarchy/bin/omarchy-agent-usage-cf-gateway 2>/dev/null
fi
