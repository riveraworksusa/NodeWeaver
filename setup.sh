#!/usr/bin/env bash
# NodeWeaver — Setup Script

echo ""
echo "  NodeWeaver Setup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "ERROR: Python 3 is not installed."
    echo "Install it from https://python.org and run this script again."
    exit 1
fi

echo "✓ Python $(python3 --version | cut -d' ' -f2) found"

# Install dependencies
echo "→ Installing dependencies..."
pip3 install -r requirements.txt --quiet

if [ $? -ne 0 ]; then
    echo ""
    echo "pip install failed. Trying with --break-system-packages..."
    pip3 install -r requirements.txt --break-system-packages --quiet
fi

echo "✓ Dependencies installed"

# Check for API key
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo ""
    echo "⚠  ANTHROPIC_API_KEY is not set."
    echo ""
    echo "   Get your key at: https://platform.anthropic.com"
    echo ""
    echo "   Then run:"
    echo "   export ANTHROPIC_API_KEY=\"your-key-here\""
    echo ""
    echo "   To make it permanent:"
    echo "   echo 'export ANTHROPIC_API_KEY=\"your-key-here\"' >> ~/.bashrc && source ~/.bashrc"
else
    echo "✓ API key found"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Setup complete."
echo ""
echo "  Run NodeWeaver:"
echo "  python3 nodeweaver.py"
echo ""
