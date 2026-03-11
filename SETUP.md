# 🏍️ Motorcycle Deal Bot — Setup Guide

## What it does
- Scrapes Facebook Marketplace every 15 minutes for motorcycles ($3k–$7k, within 200 miles)
- Compares each listing price to KBB market value
- Sends instant Telegram alerts for listings 15%+ below market value
- Remembers listings it's already seen so you only get new alerts

---

## Step 1 — Create your Telegram Bot (5 minutes)

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow the prompts (pick any name/username)
3. BotFather gives you a **Bot Token** — save it (looks like `123456:ABCdef...`)
4. Start a chat with your new bot (click the link BotFather gives you, hit Start)
5. Get your **Chat ID**:
   - Visit this URL in your browser (replace YOUR_TOKEN):
     `https://api.telegram.org/botYOUR_TOKEN/getUpdates`
   - Send any message to your bot first, then reload the URL
   - Find `"chat":{"id":XXXXXXXXX}` — that number is your Chat ID

---

## Step 2 — Set your location

Edit `bot.py` and update these two lines near the top:

```python
SEARCH_LOCATION = "dallas"    # your city (lowercase, as it appears in FB Marketplace URLs)
SEARCH_ZIP      = "75001"     # your ZIP code
```

To find your city slug: go to `facebook.com/marketplace` in your browser,
navigate to motorcycles, and look at the URL — it will show `/marketplace/CITYNAME/`.

---

## Step 3 — Install & run on your computer

### Mac / Linux

```bash
# Install Python 3.11+ if needed: https://python.org

# Clone / download this folder, then:
cd motorcycle_bot

# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Set your Telegram credentials
export TELEGRAM_BOT_TOKEN="123456:ABCdef..."
export TELEGRAM_CHAT_ID="987654321"

# Run!
python bot.py
```

### Windows

```cmd
cd motorcycle_bot
pip install -r requirements.txt
playwright install chromium

set TELEGRAM_BOT_TOKEN=123456:ABCdef...
set TELEGRAM_CHAT_ID=987654321

python bot.py
```

---

## Step 4 (Optional) — Run 24/7 for free on a cloud server

So you don't need your Mac on all the time:

### Option A: Railway.app (easiest, free tier)
1. Create account at railway.app
2. New Project → Deploy from GitHub (upload this folder)
3. Add environment variables: `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
4. It runs 24/7 automatically

### Option B: Oracle Cloud (always free, more powerful)
1. Sign up at cloud.oracle.com (free tier is genuinely free forever)
2. Create a free VM (Ubuntu, 1 CPU, 1GB RAM is enough)
3. SSH in and follow the Mac/Linux steps above
4. Use `screen` or `tmux` to keep it running after you disconnect:
   ```bash
   screen -S motobot
   python bot.py
   # Press Ctrl+A then D to detach
   ```

---

## Customizing deal sensitivity

In `bot.py`, adjust `KBB_DEAL_THRESHOLD`:

```python
KBB_DEAL_THRESHOLD = 0.85   # alert if price <= 85% of KBB (15%+ discount)
KBB_DEAL_THRESHOLD = 0.80   # stricter: only 20%+ below KBB
KBB_DEAL_THRESHOLD = 0.90   # looser: 10%+ below KBB
```

---

## Troubleshooting

**Bot sends no messages?**
- Make sure you sent your bot at least one message in Telegram before running
- Double-check your Bot Token and Chat ID

**Facebook blocks the scraper?**
- FB occasionally adds CAPTCHAs. If this happens consistently, you may need to
  log in via the browser first. Open an issue and we can add cookie-based auth.

**KBB shows "heuristic" estimates?**
- KBB's website blocks automated requests sometimes. The bot still works —
  it just uses a conservative market estimate instead of live KBB data.

---

## Example Telegram alert

```
🔥 MOTORCYCLE DEAL ALERT 🔥

📋 2019 Honda CB500F
💰 Listed: $4,200
📊 Est. Market Value: ~$5,800
💸 You Save: ~27.6% below market

🔗 View on Facebook Marketplace

⏰ Found at Mar 10, 2026 09:42 AM
```
