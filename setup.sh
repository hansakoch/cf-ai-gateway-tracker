#!/bin/bash
# CF AI Gateway Tracker — Setup Script
# Installs the collector and Omarchy panel applet

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_DIR="$HOME/.config/cf-ai-gateway"
CONFIG_FILE="$CONFIG_DIR/config.json"
COLLECTOR_SRC="$SCRIPT_DIR/src/collector.py"
WRAPPER_SRC="$SCRIPT_DIR/src/omarchy-agent-usage-cf-gateway"

echo "=== CF AI Gateway Tracker Setup ==="

# 1. Create config directory
mkdir -p "$CONFIG_DIR"
if [ ! -f "$CONFIG_FILE" ]; then
    cat > "$CONFIG_FILE" << 'EOF'
{
    "account_id": "",
    "api_token": "",
    "gateway_id": "default",
    "monthly_budget_credits": 0,
    "tier_label": ""
}
EOF
    echo "✓ Created config template: $CONFIG_FILE"
    echo "  → Edit with your Cloudflare account ID and API token"
else
    echo "✓ Config already exists: $CONFIG_FILE"
fi

# 2. Install collector
mkdir -p "$HOME/.local/bin"
cp "$COLLECTOR_SRC" "$HOME/.local/bin/cf-ai-gateway-collector"
chmod +x "$HOME/.local/bin/cf-ai-gateway-collector"
echo "✓ Installed collector: ~/.local/bin/cf-ai-gateway-collector"

# 3. Install Omarchy panel wrapper
cp "$WRAPPER_SRC" "$HOME/.local/bin/omarchy-agent-usage-cf-gateway"
chmod +x "$HOME/.local/bin/omarchy-agent-usage-cf-gateway"
echo "✓ Installed panel wrapper: ~/.local/bin/omarchy-agent-usage-cf-gateway"

# 4. Symlink into Omarchy bin if it exists
if [ -d /usr/share/omarchy/bin ]; then
    sudo ln -sf "$HOME/.local/bin/omarchy-agent-usage-cf-gateway" /usr/share/omarchy/bin/omarchy-agent-usage-cf-gateway 2>/dev/null || true
    echo "✓ Symlinked into /usr/share/omarchy/bin/"
fi

# 5. Test connectivity if config has values
if command -v python3 &>/dev/null; then
    account=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE')).get('account_id',''))" 2>/dev/null)
    if [ -n "$account" ]; then
        echo ""
        echo "=== Testing connectivity ==="
        python3 "$HOME/.local/bin/cf-ai-gateway-collector" --test
    else
        echo ""
        echo "⚠ Config needs account_id and api_token. Edit: $CONFIG_FILE"
    fi
fi

echo ""
echo "=== Setup complete ==="
echo "1. Edit $CONFIG_FILE with your Cloudflare credentials"
echo "2. Run: python3 ~/.local/bin/cf-ai-gateway-collector --test"
echo "3. The Omarchy agents panel will pick up the data automatically"
echo ""
echo "Get your API token: https://dash.cloudflare.com/profile/api-tokens"
echo "  → Permissions: AI Gateway - Read, AI Gateway - Edit"
echo "Get your Account ID: https://dash.cloudflare.com/ (sidebar)"
