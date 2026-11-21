# 🥝 Kiwi Telegram Media Downloader Bot

A high-performance Telegram bot that downloads high-definition videos from **Instagram Reels**, **Pinterest**, and **YouTube (Shorts & 4K/1080p Videos)**, with built-in **320 kbps MP3 Audio Extraction** and **Shazam Music Recognition**.

Powered by the **KiwiAPI** backend (`https://api.kiwiapi.net`).

---

## ✨ Features

- ⚡ **Auto-Download Shorts & Reels**: Send any Instagram Reel, Pinterest video, or YouTube Short to get instant master video.
- 🎬 **YouTube Quality Selector**: For long YouTube videos, displays an interactive inline keyboard to select resolution (`🎬 1080p`, `🎬 720p`, `🎬 480p`, or `🎵 MP3`).
- 💬 **Clean Telegram Video Formats**: Sent as native streamable video with custom caption:
  ```text
  ❤️ @YourBotUsername
  ```
- 👥 **Group Chat (GC) Support**: Add the bot to any group chat. When members post media links, the bot replies directly to the link without spamming normal conversation.
- 🛡️ **Owner & Sudo Admin System**:
  - `/ping` — Measures Telegram round-trip and backend API latency.
  - `/stats` — Displays live CPU, RAM, Disk usage, total downloads, and active user/group counts.
  - `/gc` — Displays group stats and recently active groups.
  - `/addsudo <id>` & `/rmsudo <id>` — Allows the Owner to add or remove Sudo Admins.
  - `/listsudo` — Displays the list of authorized Sudo Admins.
- 🔘 **Interactive Inline Buttons under every video**:
  - `[ 🎵 Extract Audio ]` — Instantly extracts 320 kbps MP3.
  - `[ 🔍 Identify Song ]` — Identifies background music using the Shazam engine.
  - `[ 🎌 Find Anime & Episode ]` — Identifies anime title, episode number, exact timestamp, and scene preview.
- 📦 **Smart 50MB Handling**: Files under 50 MB are sent directly inside Telegram; larger videos provide a direct fast download link.

---

## 🛠️ Project Structure

```text
D:\PC\bot\tg downloader\
├── .env                 # Bot token, username & API configuration
├── .env.example         # Environment template
├── api_client.py        # Asynchronous client for KiwiAPI
├── bot.py               # Main Telegram bot logic and handlers
├── config.py            # Settings loader
├── requirements.txt     # Python dependencies
└── README.md            # Documentation
```

---

## 🚀 Setup & Running

### 1. Get a Bot Token from Telegram
1. Open Telegram and search for [`@BotFather`](https://t.me/BotFather).
2. Send `/newbot` and follow the prompts to choose a name and username (e.g. `MyKiwiDownloaderBot`).
3. Copy the HTTP API token provided by BotFather.

### 2. Configure `.env`
Open `D:\PC\bot\tg downloader\.env` and paste your bot token and bot username:
```env
BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
BOT_USERNAME=MyKiwiDownloaderBot
API_BASE=https://api.kiwiapi.net
API_KEY=your_kiwiapi_key_here
TEMP_DIR=./tmp
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Run the Bot
```bash
python bot.py
```

---

## 🌐 Deploying to VPS (24/7 with PM2)

To run this bot 24/7 on your VPS server (`root@th-bkk05.altare.global`):

1. Copy the folder to your VPS:
   ```bash
   scp -P 25254 -r "D:\PC\bot\tg downloader" root@th-bkk05.altare.global:/opt/kiwibot
   ```
2. On the VPS, start it under PM2:
   ```bash
   cd /opt/kiwibot
   pm2 start bot.py --name kiwibot --interpreter /opt/kiwiapi/api/venv/bin/python
   pm2 save
   ```
3. Check status:
   ```bash
   pm2 status kiwibot
   pm2 logs kiwibot
   ```
