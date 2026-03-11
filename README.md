# 🏍️ Motorcycle Deal Finder Bot

A 24/7 bot that monitors Facebook Marketplace for motorcycle deals and sends instant Telegram alerts when it finds listings significantly below market value.

**100% FREE** - Uses Facebook's GraphQL API directly, no third-party services or costs!

## What It Does

- **Scrapes Facebook Marketplace** every 30 minutes using direct GraphQL API
- **Searches** Tustin, CA area within 200 miles, price range $2,500–$10,000
- **Compares** each listing against estimated market value (KBB/NADA/heuristic)
- **Sends Telegram alerts** instantly for listings 15%+ below market value
- **Remembers listings** so you never get duplicate alerts
- **Runs 24/7** on Railway.app (or any cloud platform)

## Deal Quality Tiers

- 🔥 **FIRE DEAL**: 25%+ below market value
- ✅ **GOOD DEAL**: 15-24% below market value

## Tech Stack

- **Python 3.11+**
- **Facebook GraphQL API** (direct, no third-party service!)
- **httpx** for HTTP calls
- **Telegram Bot API** for notifications
- **Railway.app** worker (no web server needed)

---

## Setup Guide

### Prerequisites

Only need Telegram credentials - that's it!

1. **Telegram Bot Token**
   - Message [@BotFather](https://t.me/BotFather) on Telegram
   - Send `/newbot` and follow prompts
   - Save your bot token (looks like `123456:ABCdef...`)

2. **Telegram Chat ID**
   - Start a chat with your new bot
   - Visit: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
   - Find `"chat":{"id":XXXXXXXXX}` in the response

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

That's it! Only 2 environment variables needed.

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

# Run the bot
python bot.py
```

---

## Configuration

Edit `bot.py` to customize:

```python
SEARCH_LATITUDE = 33.7175   # Tustin, CA latitude
SEARCH_LONGITUDE = -117.8311 # Tustin, CA longitude
MIN_PRICE = 2500             # Minimum price filter
MAX_PRICE = 10000            # Maximum price filter
RADIUS_MILES = 200           # Search radius
CHECK_INTERVAL_SECONDS = 1800 # Scan interval (30 min)
FIRE_DEAL_THRESHOLD = 0.75   # 25%+ below market
GOOD_DEAL_THRESHOLD = 0.85   # 15%+ below market
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
📍 Location: Irvine

🔗 View Listing

⏰ Found: Mar 11, 2026 09:42 AM
```

---

## How It Works

### Direct Facebook GraphQL API

The bot queries Facebook's internal GraphQL API directly:
- **Endpoint**: `https://www.facebook.com/api/graphql/`
- **Method**: POST with form-encoded data
- **Response**: JSON with marketplace listings

No third-party scraping service needed - completely free!

### Market Value Estimation

1. **Parse** year, make, model from listing title
2. **Try KBB**: Fetch and scrape `kbb.com/motorcycles/{make}/{year}/`
3. **Fallback to NADA**: If KBB fails, try `nadaguides.com`
4. **Heuristic**: If both fail, use depreciation-based estimate:
   - 0-2 years old: assume 10% below market
   - 3-5 years old: assume 12% below market
   - 6+ years old: assume 15% below market

### Seen Listings

- Stored in `seen_listings.json`
- Auto-trims to last 5,000 listings
- Prevents duplicate alerts

### Error Handling

- If Facebook GraphQL API fails: log error, skip cycle, retry next interval
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
2026-03-11 09:30:00 [INFO] Querying Facebook GraphQL API (lat: 33.7175, lng: -117.8311, radius: 200 mi)
2026-03-11 09:30:02 [INFO] Facebook GraphQL API returned 18 valid listings
2026-03-11 09:30:03 [INFO] [123456] 2019 Honda CB500F | $4,200 | -27.6% vs market (kbb)
2026-03-11 09:30:04 [INFO] Telegram notification sent
2026-03-11 09:30:20 [INFO] Scan complete. Found 18 listings, sent 2 deal alert(s).
2026-03-11 09:30:20 [INFO] Sleeping 30 minutes until next scan...
```

---

## Cost Estimate

**Completely FREE!**
- Railway: $5 credit/month (≈500 hours) - plenty for 24/7 operation
- Facebook GraphQL API: Free (no rate limits for reasonable use)
- KBB/NADA scraping: Free
- Telegram Bot API: Free

No third-party scraping services, no API costs, just free Railway hosting!

---

## Troubleshooting

**"No listings returned from Facebook GraphQL API"**
- Facebook may have changed their GraphQL API structure
- Check logs for error details
- The `doc_id` parameter may need updating (Facebook changes these periodically)

**"Telegram error: Unauthorized"**
- Double-check your TELEGRAM_BOT_TOKEN
- Ensure you started a chat with your bot first

**"Facebook GraphQL API returned status 400/403"**
- Facebook may be rate-limiting or detecting automated requests
- Wait 30 minutes and let it retry
- The bot includes proper headers to mimic a real browser

**Bot keeps restarting**
- Check Railway logs for the error
- Common issue: Invalid credentials

---

## Advantages Over Apify/Third-Party Services

✅ **100% Free** - No Apify subscription needed ($50/month saved!)
✅ **Faster** - Direct API calls, no waiting for actor runs
✅ **More Reliable** - No dependency on third-party service uptime
✅ **Simpler Setup** - Only 2 environment variables needed
✅ **No Rate Limits** - (within reasonable use)

---

## Location Customization

To search a different area, update the coordinates in `bot.py`:

```python
# Example: Los Angeles, CA
SEARCH_LATITUDE = 34.0522
SEARCH_LONGITUDE = -118.2437

# Example: San Diego, CA
SEARCH_LATITUDE = 32.7157
SEARCH_LONGITUDE = -117.1611
```

You can find coordinates at [latlong.net](https://www.latlong.net/)

---

## Contributing

Found a bug or want to add features? Pull requests welcome!

## License

MIT License - feel free to use and modify for your own projects.

---

**Happy deal hunting!** 🏍️🔥
