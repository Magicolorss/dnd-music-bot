#!/usr/bin/env bash
# DnD Music Bot — Setup Wizard
# ============================================================
set -e

echo "🎵 DnD Music Bot — Setup Wizard"
echo "================================"
echo ""

# Check Docker
if ! command -v docker &>/dev/null; then
    echo "❌ Docker not found. Install Docker first: https://docs.docker.com/get-docker/"
    exit 1
fi

# Get tokens
read -p "🤖 Telegram Bot Token (from @BotFather): " TELEGRAM_TOKEN
if [ -z "$TELEGRAM_TOKEN" ]; then
    echo "❌ Token required"
    exit 1
fi

read -p "🔑 Lidarr API Key: " LIDARR_API_KEY
read -p "🌐 Lidarr URL [http://lidarr:8686]: " LIDARR_URL
LIDARR_URL=${LIDARR_URL:-http://lidarr:8686}

read -p "🧠 OpenRouter API Key (optional, for AI corrections): " OR_KEY
read -p "👤 Allowed User IDs (comma-separated, optional): " ALLOWED_USERS

# Write .env
cat > .env << EOF
TELEGRAM_TOKEN=$TELEGRAM_TOKEN
LIDARR_API_KEY=$LIDARR_API_KEY
LIDARR_URL=$LIDARR_URL
OPENROUTER_API_KEY=$OR_KEY
ALLOWED_USERS=$ALLOWED_USERS
EOF

echo ""
echo "✅ .env created"

# Build Docker image
echo ""
echo "🐳 Building Docker image..."
docker build -t dnd-bot bot/

echo ""
echo "✅ Build complete!"
echo ""
echo "▶️  Start the bot:  docker compose up -d dnd-bot"
echo "📋 View logs:       docker logs dnd-bot -f"
echo "🛑 Stop:            docker compose down"
echo ""
echo "🎵 DnD Music Bot is ready!"