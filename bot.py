#!/usr/bin/env python3
"""
Facebook Marketplace Motorcycle Deal Finder
Uses authenticated Facebook session cookies to scrape marketplace listings.
Completely free - no third-party services needed.
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

# Facebook session cookies (for authenticated requests)
FB_C_USER = os.getenv("FB_C_USER")
FB_XS = os.getenv("FB_XS")
FB_DATR = os.getenv("FB_DATR")
FB_FR = os.getenv("FB_FR")

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


# ─── FACEBOOK AUTHENTICATED SCRAPER ──────────────────────────────────────────

async def scrape_facebook_marketplace() -> list[dict]:
    """
    Scrape Facebook Marketplace using authenticated session cookies.
    Fetches the HTML page and extracts embedded JSON data.
    Returns a list of listing dicts with: id, title, price, url, location
    """
    if not all([FB_C_USER, FB_XS, FB_DATR, FB_FR]):
        log.error("Facebook session cookies not set! Need FB_C_USER, FB_XS, FB_DATR, FB_FR")
        return []

    log.info("Fetching Facebook Marketplace page with authenticated session cookies")

    # Build marketplace search URL
    marketplace_url = (
        f"https://www.facebook.com/marketplace/112204368792315/search"
        f"?minPrice={MIN_PRICE}&maxPrice={MAX_PRICE}"
        f"&daysSinceListed=1&query=Motorcycle&exact=false"
    )

    # Prepare cookies
    cookies = {
        "c_user": FB_C_USER,
        "xs": FB_XS,
        "datr": FB_DATR,
        "fr": FB_FR,
    }

    # Headers to mimic real browser
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": marketplace_url,
        "Origin": "https://www.facebook.com",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    }

    try:
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            cookies=cookies
        ) as client:
            # Make GET request to marketplace page
            log.info(f"GET {marketplace_url}")
            resp = await client.get(marketplace_url, headers=headers)

            if resp.status_code != 200:
                log.error(f"Facebook returned status {resp.status_code}")
                log.debug(f"Response: {resp.text[:500]}")
                return []

            html = resp.text

            # DEBUG: Log HTML analysis info
            log.info(f"Full HTML length: {len(html)} chars")

            # Find __bbox position (Facebook's data container)
            bbox_pos = html.find('__bbox')
            if bbox_pos != -1:
                log.info(f"Found '__bbox' at position: {bbox_pos}")
                # Log snippet around __bbox to see the data structure
                log.info(f"BBOX SNIPPET: {html[bbox_pos:bbox_pos+500]}")
            else:
                log.warning("'__bbox' not found in HTML")

            # Log snippet from around position 255000 where __bbox was reported
            log.info(f"SNIPPET AT 255000: {html[255000:256000]}")

            # Extract embedded JSON data from HTML
            listings = []

            # Try to extract __bbox JSON blob
            bbox_data = None
            bbox_patterns = [
                r'__bbox\s*=\s*(\{.*?\})\s*;',
                r'"__bbox":\s*(\{[^}]+\})',
                r'__bbox"?:\s*(\{(?:[^{}]|\{[^{}]*\})*\})',
            ]

            for pattern in bbox_patterns:
                bbox_match = re.search(pattern, html, re.DOTALL)
                if bbox_match:
                    try:
                        bbox_json = bbox_match.group(1)
                        bbox_data = json.loads(bbox_json)
                        log.info(f"Successfully parsed __bbox JSON using pattern: {pattern[:30]}...")
                        log.info(f"__bbox keys: {list(bbox_data.keys()) if isinstance(bbox_data, dict) else 'not a dict'}")
                        break
                    except Exception as e:
                        log.debug(f"Failed to parse __bbox JSON: {e}")

            # Try alternative patterns for server-side rendered listing data
            # Pattern 1: listing_id
            listing_ids = re.findall(r'"listing_id":"(\d+)"', html)
            log.info(f"Found {len(listing_ids)} listing_ids")

            # Pattern 2: name (titles between 10-80 chars)
            names = re.findall(r'"name":"([^"]{10,80})"', html)
            log.info(f"Found {len(names)} names")

            # Pattern 3: price with $ and amount
            price_pattern = r'"\$":"([^"]+)".*?"amount":"(\d+)"'
            price_tuples = re.findall(price_pattern, html)
            log.info(f"Found {len(price_tuples)} price tuples")

            # Also try simpler patterns
            simple_listing_ids = re.findall(r'"id":"(\d{15,16})"', html)
            log.info(f"Found {len(simple_listing_ids)} simple IDs (15-16 digits)")

            # Combine data sources - prioritize listing_ids if found
            ids_to_use = listing_ids if len(listing_ids) > 0 else simple_listing_ids
            titles_to_use = names

            # Extract prices from tuples
            price_matches = [int(amount) for _, amount in price_tuples] if price_tuples else []

            log.info(f"Using {len(ids_to_use)} IDs, {len(titles_to_use)} titles, {len(price_matches)} prices")

            # Match up IDs, titles, and prices (they should appear in same order in the HTML)
            max_items = min(len(ids_to_use), len(titles_to_use), len(price_matches)) if price_matches else min(len(ids_to_use), len(titles_to_use))

            log.info(f"Attempting to match up {max_items} listings from IDs/titles/prices")

            for i in range(max_items):
                try:
                    # Try to get the i-th ID, title, and price
                    listing_id = ids_to_use[i] if i < len(ids_to_use) else None
                    title = titles_to_use[i] if i < len(titles_to_use) else None
                    price = price_matches[i] if i < len(price_matches) else None

                    if not listing_id or not title:
                        continue

                    # If we don't have price data, try to extract it from title or skip
                    if not price:
                        # Try to extract price from title if it contains a dollar amount
                        price_in_title = re.search(r'\$?([\d,]+)', title)
                        if price_in_title:
                            try:
                                price = int(price_in_title.group(1).replace(',', ''))
                            except:
                                log.debug(f"Could not parse price from title: {title}")
                                continue
                        else:
                            log.debug(f"No price available for listing {listing_id}")
                            continue

                    # Build listing URL
                    url = f"https://www.facebook.com/marketplace/item/{listing_id}/"

                    # Filter by price range
                    if price and MIN_PRICE <= price <= MAX_PRICE:
                        listings.append({
                            "id": listing_id,
                            "title": title,
                            "price": price,
                            "url": url,
                            "location": "Unknown",  # Location not easily extractable from HTML
                            "image_url": "",
                        })
                        log.debug(f"Extracted listing: {listing_id} - {title} - ${price}")

                except Exception as e:
                    log.debug(f"Error processing listing {i}: {e}")
                    continue

            # Deduplicate by ID
            seen_ids = set()
            unique_listings = []
            for listing in listings:
                if listing["id"] not in seen_ids:
                    seen_ids.add(listing["id"])
                    unique_listings.append(listing)

            log.info(f"Facebook Marketplace returned {len(unique_listings)} valid listings")
            return unique_listings

    except httpx.TimeoutException:
        log.error("Facebook request timed out")
        return []
    except Exception as e:
        log.error(f"Error scraping Facebook Marketplace: {e}", exc_info=True)
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
        log.warning("No listings returned from Facebook Marketplace")
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
    log.info(f"   Using authenticated Facebook session cookies")

    # Verify credentials
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("ERROR: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set!")
        return

    if not all([FB_C_USER, FB_XS, FB_DATR, FB_FR]):
        log.error("ERROR: Facebook session cookies not set! Need FB_C_USER, FB_XS, FB_DATR, FB_FR")
        return

    seen_ids = load_seen_ids()
    log.info(f"   Loaded {len(seen_ids)} previously seen listings")

    # Send startup message
    await send_telegram(
        f"🏍️ <b>Motorcycle Bot is now running!</b>\n"
        f"Searching ${MIN_PRICE:,}–${MAX_PRICE:,} within {RADIUS_MILES} miles.\n"
        f"Using authenticated Facebook session - no costs!\n"
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
