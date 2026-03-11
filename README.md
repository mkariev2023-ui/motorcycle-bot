# 🏍️ Motorcycle Deal Finder Bot

A 24/7 bot that monitors Facebook Marketplace for motorcycle deals and sends instant Telegram alerts when it finds listings significantly below market value.

## What It Does

- **Scrapes Facebook Marketplace** every 30 minutes using Apify API
- **Searches** in Tustin, CA within 200 miles, price range $3,000–$7,000
- **Compares** each listing against estimated market value (KBB/NADA/heuristic)
- **Sends Telegram alerts** instantly for listings 15%+ below market value
- **Remembers listings** so you never get duplicate alerts
- **Runs 24/7** on Railway.app (or any cloud platform)

## Deal Quality Tiers

- 🔥 **FIRE DEAL**: 25%+ below market value
- ✅ **GOOD DEAL**: 15-24% below market value

## Tech Stack

- **Python 3.11+**
- **Apify API** (`apify~facebook-marketplace-scraper` actor)
- **httpx** for all HTTP calls (no Playwright/Selenium needed!)
- **Telegram Bot API** for notifications
- **Railway.app** worker (no web server needed)

---

## Setup Guide

### Prerequisites

1. **Telegram Bot Token**
   - Message [@BotFather](https://t.me/BotFather) on Telegram
   - Send `/newbot` and follow prompts
   - Save your bot token (looks like `123456:ABCdef...`)

2. **Telegram Chat ID**
   - Start a chat with your new bot
   - Visit: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
   - Find `"chat":{"id":XXXXXXXXX}` in the response

3. **Apify API Token**
   - Sign up at [apify.com](https://apify.com) (free tier available)
   - Go to Settings → Integrations → API tokens
   - Create a new token and save it

---

## Deployment to Railway.app

### Step 1: Push to GitHub

```bash
cd motorcycle_bot

# If you haven't already initialized git:
git init
git add .
git commit -m "Initial commit"

# Create a GitHub repo and push:
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git branch -M main
git push -u origin main
```

### Step 2: Deploy on Railway

1. Go to [railway.app](https://railway.app) and sign up
2. Click **"New Project"** → **"Deploy from GitHub repo"**
3. Select your `motorcycle-bot` repository
4. Railway will auto-detect it's a Python app

### Step 3: Add Environment Variables

In Railway dashboard → Variables tab, add:

| Variable | Value |
|----------|-------|
| `TELEGRAM_BOT_TOKEN` | Your Telegram bot token |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID |
| `APIFY_API_TOKEN` | Your Apify API token |
| `SEARCH_LOCATION` | `tustin-ca` (optional, defaults to this) |

### Step 4: Verify It's Running

- Check Railway logs: You should see "🏍️ Motorcycle Deal Bot starting up..."
- You'll receive a Telegram message confirming the bot is live
- The bot will scan every 30 minutes

---

## Local Testing (Optional)

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export TELEGRAM_BOT_TOKEN="your_token"
export TELEGRAM_CHAT_ID="your_chat_id"
export APIFY_API_TOKEN="your_apify_token"

# Run the bot
python bot.py
```

---

## Configuration

Edit `bot.py` to customize:

```python
MIN_PRICE = 3000              # Minimum price filter
MAX_PRICE = 7000              # Maximum price filter
RADIUS_MILES = 200            # Search radius
CHECK_INTERVAL_SECONDS = 1800 # Scan interval (30 min)
FIRE_DEAL_THRESHOLD = 0.75    # 25%+ below market
GOOD_DEAL_THRESHOLD = 0.85    # 15%+ below market
```

After editing, commit and push to GitHub:

```bash
git add bot.py
git commit -m "Updated search settings"
git push
```

Railway will auto-deploy the changes.

---

## Example Telegram Alert

```
🔥 MOTORCYCLE FIRE DEAL ALERT 🔥

📋 2019 Honda CB500F
💰 Listed: $4,200
📊 KBB Value: ~$5,800
💸 You Save: ~27.6% below market

🔗 View Listing

⏰ Found: Mar 11, 2026 09:42 AM
```

---

## How It Works

### Market Value Estimation

1. **Parse** year, make, model from listing title
2. **Try KBB**: Fetch and scrape `kbb.com/motorcycles/{make}/{year}/`
3. **Fallback to NADA**: If KBB fails, try `nadaguides.com`
4. **Heuristic**: If both fail, use depreciation-based estimate:
   - 0-2 years old: assume 10% below market
   - 3-5 years old: assume 12% below market
   - 6+ years old: assume 15% below market

### Apify Integration

1. **Start run**: POST to Apify actor with search URL
2. **Poll status**: Check every 10 seconds (max 5 min)
3. **Fetch results**: Get dataset items when run succeeds
4. **Parse listings**: Extract ID, title, price, URL

### Seen Listings

- Stored in `seen_listings.json`
- Auto-trims to last 5,000 listings
- Prevents duplicate alerts

### Error Handling

- If Apify run fails: log error, skip cycle, retry next interval
- If Telegram fails: retry once after 5 seconds
- If market value lookup fails: use heuristic fallback
- Main loop wrapped in try/except so errors never kill the bot

---

## Monitoring

**View logs in Railway:**
1. Go to your Railway dashboard
2. Click your project → "Deployments"
3. Select active deployment → "View Logs"

**Log output example:**
```
2026-03-11 09:30:00 [INFO] Starting Apify scrape...
2026-03-11 09:30:15 [INFO] Apify run started: abc123
2026-03-11 09:31:00 [INFO] Apify run status: SUCCEEDED
2026-03-11 09:31:05 [INFO] Apify returned 23 valid listings
2026-03-11 09:31:10 [INFO] [123456] 2019 Honda CB500F | $4,200 | -27.6% vs market (kbb)
2026-03-11 09:31:11 [INFO] Telegram notification sent
2026-03-11 09:31:45 [INFO] Scan complete. Found 23 listings, sent 2 deal alert(s).
2026-03-11 09:31:45 [INFO] Sleeping 30 minutes until next scan...
```

---

## Free Tier Limits

**Railway**: $5 credit/month (≈500 hours) - plenty for 24/7 operation
**Apify**: 500 actor compute units/month on free tier - enough for ~1,000 scrapes

---

## Troubleshooting

**"APIFY_API_TOKEN not set"**
- Verify you added the environment variable in Railway dashboard
- Check spelling and that there are no extra spaces

**"No listings returned from Apify"**
- Check Apify logs at apify.com/console
- Verify your Apify account has available compute units
- Facebook may have changed their HTML structure (wait for Apify actor update)

**"Telegram error: Unauthorized"**
- Double-check your TELEGRAM_BOT_TOKEN
- Ensure you started a chat with your bot first

**Bot keeps restarting**
- Check Railway logs for the error
- Common issue: Invalid credentials or Apify quota exceeded

---

## Cost Estimate

**Completely free** on Railway + Apify free tiers for this use case:
- Railway: 500 hours/month (this bot uses ~720 hours/month full time, but $5 credit covers it)
- Apify: 500 compute units/month (each scrape uses ~0.5 units, 30 min intervals = ~1,440 scrapes/month ≈ 720 units)

You may need to upgrade Apify to paid tier (~$50/month for 5,000 units) if scraping more frequently or multiple locations.

---

## Contributing

Found a bug or want to add features? Pull requests welcome!

## License

MIT License - feel free to use and modify for your own projects.

---

**Happy deal hunting!** 🏍️🔥
