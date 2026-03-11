#!/usr/bin/env python3
"""
Facebook Marketplace Motorcycle Deal Finder
Queries Facebook's GraphQL API directly - completely free, no third-party services.
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import httpx

# ─── CONFIG ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Search parameters (Tustin, CA area)
SEARCH_LATITUDE = 33.7175
SEARCH_LONGITUDE = -117.8311
MIN_PRICE = 2500
MAX_PRICE = 10000
RADIUS_MILES = 200

# Deal thresholds
FIRE_DEAL_THRESHOLD = 0.75  # 25%+ below market
GOOD_DEAL_THRESHOLD = 0.85  # 15%+ below market

CHECK_INTERVAL_SECONDS = 1800  # 30 minutes

SEEN_IDS_FILE = Path("seen_listings.json")
MAX_SEEN_IDS = 5000  # Trim file if it grows beyond this

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ─── SEEN LISTINGS PERSISTENCE ───────────────────────────────────────────────

def load_seen_ids() -> set:
    """Load previously seen listing IDs from disk."""
    if SEEN_IDS_FILE.exists():
        try:
            data = json.loads(SEEN_IDS_FILE.read_text())
            # Trim if too large
            if len(data) > MAX_SEEN_IDS:
                data = data[-MAX_SEEN_IDS:]
            return set(data)
        except Exception as e:
            log.error(f"Error loading seen IDs: {e}")
            return set()
    return set()


def save_seen_ids(ids: set):
    """Save seen listing IDs to disk, trimming if necessary."""
    id_list = list(ids)
    if len(id_list) > MAX_SEEN_IDS:
        id_list = id_list[-MAX_SEEN_IDS:]
    try:
        SEEN_IDS_FILE.write_text(json.dumps(id_list))
    except Exception as e:
        log.error(f"Error saving seen IDs: {e}")


# ─── FACEBOOK GRAPHQL SCRAPER ────────────────────────────────────────────────

async def scrape_facebook_marketplace() -> list[dict]:
    """
    Query Facebook's internal GraphQL API directly to fetch motorcycle listings.
    Completely free - no third-party services needed.
    Returns a list of listing dicts with: id, title, price, url, location
    """
    log.info(f"Querying Facebook GraphQL API (lat: {SEARCH_LATITUDE}, lng: {SEARCH_LONGITUDE}, radius: {RADIUS_MILES} mi)")

    # GraphQL query parameters
    variables = {
        "count": 40,
        "params": {
            "bqf": {
                "callsite": "COMMERCE_MSITE_MARKETPLACE_FEED",
                "query": "Motorcycle"
            },
            "bqvariables": {
                "buyLocation": {
                    "latitude": SEARCH_LATITUDE,
                    "longitude": SEARCH_LONGITUDE
                },
                "priceRange": [MIN_PRICE, MAX_PRICE],
                "radius": RADIUS_MILES
            }
        }
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://www.facebook.com",
        "Referer": "https://www.facebook.com/marketplace/",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }

    # Try multiple known doc_ids for FB Marketplace search (2025/2026)
    doc_ids = [
        "9053288348063931",
        "6243297902381423",
        "7111939778879383",
    ]

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            for doc_id in doc_ids:
                log.info(f"Trying doc_id: {doc_id}")

                # Form-encoded body for GraphQL request
                form_data = {
                    "variables": json.dumps(variables),
                    "doc_id": doc_id
                }

                resp = await client.post(
                    "https://www.facebook.com/api/graphql/",
                    headers=headers,
                    data=urlencode(form_data),
                )

                if resp.status_code != 200:
                    log.error(f"Facebook GraphQL API returned status {resp.status_code} for doc_id {doc_id}")
                    log.debug(f"Response: {resp.text[:500]}")
                    continue

                # DEBUG: Print raw response to see actual structure
                log.info(f"RAW RESPONSE (doc_id {doc_id}): {resp.text[:3000]}")

                try:
                    data = resp.json()
                except Exception as e:
                    log.error(f"Failed to parse JSON for doc_id {doc_id}: {e}")
                    continue

                # Check if response has 'data' key
                if not isinstance(data, dict) or "data" not in data:
                    log.warning(f"No 'data' key in response for doc_id {doc_id}")
                    continue

                log.info(f"doc_id {doc_id} returned valid response with 'data' key")

                # Try multiple response path fallbacks
                feed_units = None
                response_paths = [
                    ("data", "marketplace_search", "feed_units", "edges"),
                    ("data", "viewer", "marketplace_feed_stories", "edges"),
                    ("data", "marketplace_feed", "edges"),
                ]

                for path in response_paths:
                    try:
                        current = data
                        for key in path:
                            current = current[key]
                        feed_units = current
                        log.info(f"Successfully found data at path: {' -> '.join(path)}")
                        break
                    except (KeyError, TypeError):
                        continue

                if not feed_units:
                    log.warning(f"Could not find feed_units in any known path for doc_id {doc_id}")
                    log.debug(f"Available keys in data: {list(data.get('data', {}).keys()) if 'data' in data else 'N/A'}")
                    continue

                # Parse listings from feed_units
                listings = []
                for edge in feed_units:
                    try:
                        node = edge.get("node", {})
                        listing_data = node.get("listing", {})

                        if not listing_data:
                            continue

                        # Extract listing details
                        listing_id = listing_data.get("id", "")
                        title = listing_data.get("marketplace_listing_title", "Unknown")

                        # Extract price
                        price_data = listing_data.get("formatted_price", {})
                        price_text = price_data.get("text", "")
                        price = None
                        if price_text:
                            price_match = re.search(r'[\d,]+', price_text.replace("$", ""))
                            if price_match:
                                price = int(price_match.group().replace(",", ""))

                        # Extract location
                        location_data = listing_data.get("location", {})
                        reverse_geocode = location_data.get("reverse_geocode", {})
                        city = reverse_geocode.get("city", "Unknown")

                        # Extract image URL (optional, for future use)
                        photo_data = listing_data.get("primary_listing_photo", {})
                        image_data = photo_data.get("image", {})
                        image_url = image_data.get("uri", "")

                        # Build marketplace URL
                        url = f"https://www.facebook.com/marketplace/item/{listing_id}/"

                        if listing_id and price and MIN_PRICE <= price <= MAX_PRICE:
                            listings.append({
                                "id": listing_id,
                                "title": title,
                                "price": price,
                                "url": url,
                                "location": city,
                                "image_url": image_url,
                            })

                    except Exception as e:
                        log.debug(f"Error parsing listing node: {e}")
                        continue

                if listings:
                    log.info(f"Facebook GraphQL API returned {len(listings)} valid listings using doc_id {doc_id}")
                    return listings
                else:
                    log.warning(f"doc_id {doc_id} returned 0 listings, trying next doc_id...")

            # If we get here, none of the doc_ids worked
            log.error("All doc_ids failed to return listings")
            return []

    except httpx.TimeoutException:
        log.error("Facebook GraphQL API request timed out")
        return []
    except Exception as e:
        log.error(f"Error querying Facebook GraphQL API: {e}", exc_info=True)
        return []


# ─── MARKET VALUE ESTIMATOR ───────────────────────────────────────────────────

def parse_year_make_model(title: str) -> tuple[str, str, str]:
    """Best-effort parse of year, make, model from a listing title."""
    year_match = re.search(r'\b(19|20)\d{2}\b', title)
    year = year_match.group() if year_match else ""

    makes = [
        "Honda", "Yamaha", "Kawasaki", "Suzuki", "Harley", "Harley-Davidson",
        "Ducati", "BMW", "KTM", "Triumph", "Royal Enfield", "Indian",
        "Aprilia", "Husqvarna", "Can-Am", "Moto Guzzi", "Zero",
    ]
    make = ""
    for m in makes:
        if m.lower() in title.lower():
            make = m
            break

    # Model = everything after make (simplified)
    model = title
    if year:
        model = model.replace(year, "").strip()
    if make:
        idx = model.lower().find(make.lower())
        if idx != -1:
            model = model[idx + len(make):].strip()
    model = re.sub(r'[^\w\s]', '', model).strip()[:30]

    return year, make, model


async def estimate_market_value(title: str, listed_price: int) -> dict:
    """
    Estimate market value using KBB or NADA Guides.
    Falls back to depreciation heuristic if both fail.
    """
    year, make, model = parse_year_make_model(title)
    market_estimate = None
    source = "heuristic"

    # Try KBB first
    if year and make:
        try:
            async with httpx.AsyncClient(
                timeout=10,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            ) as client:
                kbb_url = f"https://www.kbb.com/motorcycles/{make.lower().replace(' ', '-')}/{year}/"
                resp = await client.get(kbb_url)
                if resp.status_code == 200:
                    # Look for price patterns like $4,500 - $6,200
                    prices = re.findall(r'\$(\d{1,3}(?:,\d{3})*)', resp.text)
                    numeric = [int(p.replace(',', '')) for p in prices
                               if 1000 < int(p.replace(',', '')) < 50000]
                    if numeric:
                        market_estimate = int(sum(numeric[:4]) / len(numeric[:4]))
                        source = "kbb"
                        log.debug(f"KBB estimate for {title}: ${market_estimate:,}")
        except Exception as e:
            log.debug(f"KBB lookup failed: {e}")

    # Try NADA Guides if KBB failed
    if not market_estimate and year and make:
        try:
            async with httpx.AsyncClient(
                timeout=10,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            ) as client:
                nada_url = f"https://www.nadaguides.com/Motorcycles/{year}/{make.replace(' ', '-')}"
                resp = await client.get(nada_url)
                if resp.status_code == 200:
                    prices = re.findall(r'\$(\d{1,3}(?:,\d{3})*)', resp.text)
                    numeric = [int(p.replace(',', '')) for p in prices
                               if 1000 < int(p.replace(',', '')) < 50000]
                    if numeric:
                        market_estimate = int(sum(numeric[:4]) / len(numeric[:4]))
                        source = "nada"
                        log.debug(f"NADA estimate for {title}: ${market_estimate:,}")
        except Exception as e:
            log.debug(f"NADA lookup failed: {e}")

    # Heuristic fallback based on age
    if not market_estimate:
        current_year = datetime.now().year
        if year:
            age = current_year - int(year)
            if age <= 2:
                market_estimate = int(listed_price / 0.90)  # assume 10% below
            elif age <= 5:
                market_estimate = int(listed_price / 0.88)  # assume 12% below
            else:
                market_estimate = int(listed_price / 0.85)  # assume 15% below
        else:
            # No year found, conservative estimate
            market_estimate = int(listed_price / 0.88)
        source = "heuristic"

    discount_pct = round((1 - listed_price / market_estimate) * 100, 1) if market_estimate else 0
    is_fire_deal = listed_price <= market_estimate * FIRE_DEAL_THRESHOLD
    is_good_deal = listed_price <= market_estimate * GOOD_DEAL_THRESHOLD

    return {
        "market_estimate": market_estimate,
        "discount_pct": discount_pct,
        "is_fire_deal": is_fire_deal,
        "is_good_deal": is_good_deal,
        "source": source,
        "year": year,
        "make": make,
        "model": model,
    }


# ─── TELEGRAM NOTIFIER ───────────────────────────────────────────────────────

async def send_telegram(message: str, retry: bool = True):
    """Send a message to Telegram with optional retry."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("Telegram credentials not set!")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }

    async with httpx.AsyncClient(timeout=10) as client:
        for attempt in range(2 if retry else 1):
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    log.info("Telegram notification sent")
                    return
                else:
                    log.error(f"Telegram error: {resp.text}")
            except Exception as e:
                log.error(f"Telegram send failed (attempt {attempt + 1}): {e}")

            if retry and attempt == 0:
                await asyncio.sleep(5)


def format_deal_message(listing: dict, value_info: dict) -> str:
    """Format a deal alert message for Telegram."""
    if value_info["is_fire_deal"]:
        emoji = "🔥"
        deal_type = "FIRE DEAL"
    else:
        emoji = "✅"
        deal_type = "GOOD DEAL"

    source_label = {
        "kbb": "KBB",
        "nada": "NADA",
        "heuristic": "Est. Market"
    }.get(value_info["source"], "Est. Market")

    msg = (
        f"{emoji} <b>MOTORCYCLE {deal_type} ALERT</b> {emoji}\n\n"
        f"📋 <b>{listing['title']}</b>\n"
        f"💰 Listed: <b>${listing['price']:,}</b>\n"
        f"📊 {source_label} Value: ~${value_info['market_estimate']:,}\n"
        f"💸 You Save: ~{value_info['discount_pct']}% below market\n"
        f"📍 Location: {listing['location']}\n\n"
        f"🔗 <a href=\"{listing['url']}\">View Listing</a>\n\n"
        f"⏰ Found: {datetime.now().strftime('%b %d, %Y %I:%M %p')}"
    )
    return msg


# ─── MAIN LOOP ────────────────────────────────────────────────────────────────

async def run_scan(seen_ids: set) -> set:
    """Run one complete scan cycle."""
    log.info("=" * 60)
    log.info("Starting new scan...")

    listings = await scrape_facebook_marketplace()
    if not listings:
        log.warning("No listings returned from Facebook GraphQL API")
        return seen_ids

    new_deals = 0
    for listing in listings:
        lid = listing["id"]

        # Skip if already seen
        if lid in seen_ids:
            continue

        seen_ids.add(lid)

        # Estimate market value
        value_info = await estimate_market_value(listing["title"], listing["price"])

        log.info(
            f"  [{lid}] {listing['title'][:50]} | ${listing['price']:,} | "
            f"{value_info['discount_pct']:+.1f}% vs market ({value_info['source']})"
        )

        # Send alert if it's a deal
        if value_info["is_good_deal"]:
            msg = format_deal_message(listing, value_info)
            await send_telegram(msg)
            new_deals += 1
            await asyncio.sleep(1)  # Rate limit

    log.info(f"Scan complete. Found {len(listings)} listings, sent {new_deals} deal alert(s).")
    save_seen_ids(seen_ids)
    return seen_ids


async def main():
    """Main bot loop."""
    log.info("🏍️  Motorcycle Deal Bot starting up...")
    log.info(f"   Price range: ${MIN_PRICE:,}–${MAX_PRICE:,}")
    log.info(f"   Radius: {RADIUS_MILES} miles from Tustin, CA")
    log.info(f"   Check interval: {CHECK_INTERVAL_SECONDS // 60} minutes")
    log.info(f"   Deal thresholds: 🔥 {int((1-FIRE_DEAL_THRESHOLD)*100)}%+ | ✅ {int((1-GOOD_DEAL_THRESHOLD)*100)}%+")
    log.info(f"   Using FREE Facebook GraphQL API (no third-party costs!)")

    # Verify credentials
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("ERROR: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set!")
        return

    seen_ids = load_seen_ids()
    log.info(f"   Loaded {len(seen_ids)} previously seen listings")

    # Send startup message
    await send_telegram(
        f"🏍️ <b>Motorcycle Bot is now running!</b>\n"
        f"Searching ${MIN_PRICE:,}–${MAX_PRICE:,} within {RADIUS_MILES} miles.\n"
        f"Using free Facebook GraphQL API - no costs!\n"
        f"I'll alert you for deals 15%+ below market. 🔥"
    )

    # Main loop
    while True:
        try:
            seen_ids = await run_scan(seen_ids)
        except Exception as e:
            log.error(f"Unexpected error in scan cycle: {e}", exc_info=True)
            # Don't crash - continue to next cycle

        log.info(f"Sleeping {CHECK_INTERVAL_SECONDS // 60} minutes until next scan...")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
