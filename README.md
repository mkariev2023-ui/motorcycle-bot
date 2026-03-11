# 🏍️ Motorcycle Deal Finder Bot

A 24/7 bot that monitors Facebook Marketplace for motorcycle deals and sends instant Telegram alerts when it finds listings significantly below market value.

**100% FREE** - Uses authenticated Facebook session cookies to scrape marketplace directly, no third-party services or costs!

## What It Does

- **Scrapes Facebook Marketplace** every 30 minutes using authenticated session cookies
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
- **Authenticated Facebook session** (uses your browser cookies)
- **httpx** for HTTP calls
- **Telegram Bot API** for notifications
- **Railway.app** worker (no web server needed)

---

## Setup Guide

### Prerequisites

You'll need Telegram credentials and Facebook session cookies:

1. **Telegram Bot Token**
   - Message [@BotFather](https://t.me/BotFather) on Telegram
   - Send `/newbot` and follow prompts
   - Save your bot token (looks like `123456:ABCdef...`)

2. **Telegram Chat ID**
   - Start a chat with your new bot
   - Visit: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
   - Find `"chat":{"id":XXXXXXXXX}` in the response

3. **Facebook Session Cookies**
   - Log into Facebook in your browser
   - Open Developer Tools (F12) → Application/Storage → Cookies → facebook.com
   - Copy these 4 cookie values:
     - `c_user` (your Facebook user ID)
     - `xs` (session token)
     - `datr` (device authentication token)
     - `fr` (Facebook request token)

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
| `FB_C_USER` | Your Facebook `c_user` cookie |
| `FB_XS` | Your Facebook `xs` cookie |
| `FB_DATR` | Your Facebook `datr` cookie |
| `FB_FR` | Your Facebook `fr` cookie |

Total: 6 environment variables needed.

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
export FB_C_USER="your_c_user_cookie"
export FB_XS="your_xs_cookie"
export FB_DATR="your_datr_cookie"
export FB_FR="your_fr_cookie"

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

### Authenticated Facebook Session

The bot uses your Facebook session cookies to access Marketplace as a logged-in user:
- **Endpoint**: `https://www.facebook.com/marketplace/...`
- **Method**: GET request with session cookies
- **Response**: HTML page with embedded JSON data
- **Extraction**: Regex patterns to find listing IDs, titles, and prices

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
2026-03-11 09:30:00 [INFO] Fetching Facebook Marketplace page with authenticated session cookies
2026-03-11 09:30:01 [INFO] Found 15 item IDs, 15 titles, 15 prices in HTML
2026-03-11 09:30:02 [INFO] Facebook Marketplace returned 15 valid listings
2026-03-11 09:30:03 [INFO] [123456] 2019 Honda CB500F | $4,200 | -27.6% vs market (kbb)
2026-03-11 09:30:04 [INFO] Telegram notification sent
2026-03-11 09:30:20 [INFO] Scan complete. Found 15 listings, sent 2 deal alert(s).
2026-03-11 09:30:20 [INFO] Sleeping 30 minutes until next scan...
```

---

## Cost Estimate

**Completely FREE!**
- Railway: $5 credit/month (≈500 hours) - plenty for 24/7 operation
- Facebook Marketplace scraping: Free (uses your session cookies)
- KBB/NADA scraping: Free
- Telegram Bot API: Free

No third-party scraping services, no API costs, just free Railway hosting!

---

## Troubleshooting

**"Facebook session cookies not set!"**
- Verify you added all 4 cookie environment variables in Railway
- Check that cookie values don't have extra spaces or quotes
- Make sure you're logged into Facebook when extracting cookies

**"No listings returned from Facebook Marketplace"**
- Your Facebook cookies may have expired (they last ~1-2 months)
- Get fresh cookies by logging into Facebook again
- Check the HTML response in logs for errors

**"Telegram error: Unauthorized"**
- Double-check your TELEGRAM_BOT_TOKEN
- Ensure you started a chat with your bot first

**"Facebook returned status 400/403"**
- Your session cookies are invalid or expired
- Log into Facebook and get fresh cookies
- Update the 4 cookie environment variables in Railway

**Bot keeps restarting**
- Check Railway logs for the error
- Common issues: Invalid or expired Facebook cookies, missing env vars

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
