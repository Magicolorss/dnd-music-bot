# DnD Music Bot 🎵

> A Telegram bot that automates music discovery and downloading through Lidarr, Soulseek, Torrents, Bandcamp, YouTube, and SoundCloud — with AI-powered search, confirmation flow, and download notifications.

## 🎯 Overview

**DnD Music Bot** is a Telegram bot that manages your entire music acquisition pipeline. Send an artist name, and the bot:

1. **Searches MusicBrainz** for the artist
2. **Shows album artwork + details** with inline confirmation buttons
3. **Adds to Lidarr** which triggers downloads via:
   - 🔵 Soulseek (FLAC/DSD) — via slskd + soularr
   - ⚡ Torrents (FLAC) — via Prowlarr + qBittorrent
4. **Fallback platforms** if not found on Soulseek/Torrents:
   - 🟣 **Bandcamp** — paste URL → real FLAC download
   - 🔴 **YouTube** — best Opus audio with cover art
   - 🟠 **SoundCloud** — direct downloads

## ✨ Features

| Feature | Description |
|---|---|
| 🤖 **AI Corrections** | OpenRouter-powered spell correction for artist names |
| 🖼️ **Album Artwork** | Shows cover art in confirmation + download notifications |
| ✅ **Confirmation Flow** | Asks before adding anything to Lidarr |
| 📥 **Download Notifications** | Sends 📥 when albums finish importing |
| 📊 **/status Command** | Live Lidarr queue, qBittorrent progress, disk usage |
| 🎤 **Multiple Platforms** | Soulseek → Torrents → Bandcamp → YouTube → SoundCloud |
| 🔒 **User Restriction** | Whitelist-only access |
| 🩺 **Auto-Repair** | Watchdog monitors and restarts failed containers |
| ⚡ **Instant Feedback** | Inline buttons respond instantly, searches run in background |

## 📋 Bot Commands

| Command | Action |
|---|---|
| `Artist Name` | Search + add to Lidarr |
| `/help` or `/commands` | Show all commands |
| `/status` | Queue + disk overview |
| `/queue` | Lidarr download queue |
| `/recent` | Last 10 imported albums |
| `/disk` | Disk usage details |
| `/lidarr` | Open Lidarr web UI |
| `/qbit` | Open qBittorrent web UI |
| `/slskd` | Open slskd web UI |
| `/prowlarr` | Open Prowlarr web UI |
| `/restart <service>` | Restart a container |
| `/stack` | All containers status |

## 🏗️ Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────────┐
│  Telegram    │────▶│  dnd-bot     │────▶│  Lidarr (8686)   │
│  @dnd_...   │     │  (Python)    │     │  ┌────────────┐  │
└─────────────┘     └──────────────┘     │  │ Prowlarr   │  │
                                          │  │ (9696)     │──▶ qBittorrent (8080)
                                          │  ├────────────┤  │
                                          │  │ soularr    │──▶ slskd (5030)
                                          │  │ (8265)     │  │
                                          │  └────────────┘  │
                                          └──────────────────┘
                ┌──────────────┐
                │  yt-dlp      │  Bandcamp / YouTube / SoundCloud
                └──────────────┘
```

## 🚀 Quick Start

### Prerequisites
- Docker & Docker Compose
- Telegram Bot Token (from [@BotFather](https://t.me/botfather))
- Lidarr instance with API key
- (Optional) OpenRouter API key for AI corrections

### 1. Clone & Setup
```bash
git clone https://github.com/Magicolorss/dnd-music-bot.git
cd dnd-music-bot

# Set up environment
cp .env.example .env
# Edit .env with your tokens:
#   TELEGRAM_TOKEN=your_bot_token
#   LIDARR_API_KEY=your_lidarr_api_key
#   LIDARR_URL=http://lidarr:8686
#   OPENROUTER_API_KEY=your_key  (optional)
#   ALLOWED_USERS=user_id_1,user_id_2
```

### 2. Build & Run
```bash
docker build -t dnd-bot bot/
docker compose up -d dnd-bot
```

### 3. Watch Logs
```bash
docker logs dnd-bot -f
```

## 🔧 Full Stack (with Lidarr + services)

```bash
docker compose -f docker-compose.stack.yml up -d
```

## 🔒 Security

- Bot responds only to whitelisted user IDs
- No external ports exposed (uses Docker internal networking)
- API keys stored in environment variables, never in code
- Artist lookup uses public MusicBrainz API (no auth needed)

## 🖼️ Branding Assets

Custom brand icons for each platform are designed as minimal square icons (512×512px):
- 🟣 **Bandcamp** — Purple music note on dark gradient
- 🔴 **YouTube** — Red play button on dark
- 🟠 **SoundCloud** — Orange waveform on dark
- 🔵 **Soulseek** — Blue headphone on dark
- ⚡ **Torrent** — Lightning bolt on dark

Generate via Magnific or any icon tool → place in `assets/` directory.

## 🤝 Contributing

This is a personal project by [@Magicolorss](https://github.com/Magicolorss). Feel free to fork and adapt.

## 📄 License

MIT
