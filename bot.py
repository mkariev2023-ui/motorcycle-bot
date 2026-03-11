#!/usr/bin/env python3
"""
Facebook Marketplace Motorcycle Deal Finder
Uses Apify API to scrape listings, compares to market estimates, sends Telegram alerts.
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path

import httpx

# ─── CONFIG ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN")

SEARCH_LOCATION = os.getenv("SEARCH_LOCATION", "losangeles")
MIN_PRICE = 3000
MAX_PRICE = 7000
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


# ─── APIFY SCRAPER ────────────────────────────────────────────────────────────

async def scrape_facebook_marketplace() -> list[dict]:
    """
    Use Apify's facebook-marketplace-scraper actor to fetch listings.
    Returns a list of listing dicts with: id, title, price, url, location
    """
    if not APIFY_API_TOKEN:
        log.error("APIFY_API_TOKEN not set!")
        return []

    # Build search URL
    search_url = (
        f"https://www.facebook.com/marketplace/{SEARCH_LOCATION}/vehicles/motorcycles"
        f"?minPrice={MIN_PRICE}&maxPrice={MAX_PRICE}&radius={RADIUS_MILES}"
    )

    log.info(f"Starting Apify scrape for: {search_url}")

    async with httpx.AsyncClient(timeout=300) as client:
        # Start Apify actor run
        try:
            resp = await client.post(
                "https://api.apify.com/v2/acts/apify~facebook-marketplace-scraper/runs",
                headers={"Authorization": f"Bearer {APIFY_API_TOKEN}"},
                json={
                    "startUrls": [{"url": search_url}],
                    "maxItems": 40,
                    "addListingDetails": False,
                },
            )
            resp.raise_for_status()
            run_data = resp.json()["data"]
            run_id = run_data["id"]
            log.info(f"Apify run started: {run_id}")
        except Exception as e:
            log.error(f"Failed to start Apify run: {e}")
            return []

        # Poll run status (timeout 5 minutes)
        status_url = f"https://api.apify.com/v2/actor-runs/{run_id}"
        max_polls = 30  # 30 polls * 10 sec = 5 min
        for poll_num in range(max_polls):
            await asyncio.sleep(10)
            try:
                resp = await client.get(
                    status_url,
                    headers={"Authorization": f"Bearer {APIFY_API_TOKEN}"},
                )
                resp.raise_for_status()
                status = resp.json()["data"]["status"]
                log.info(f"Apify run status: {status} (poll {poll_num + 1}/{max_polls})")

                if status == "SUCCEEDED":
                    break
                elif status in ("FAILED", "ABORTED", "TIMED-OUT"):
                    log.error(f"Apify run {status}")
                    return []
            except Exception as e:
                log.error(f"Error polling Apify run status: {e}")
                return []
        else:
            log.error("Apify run timed out (5 minutes)")
            return []

        # Fetch results
        try:
            dataset_url = f"https://api.apify.com/v2/actor-runs/{run_id}/dataset/items"
            resp = await client.get(
                dataset_url,
                headers={"Authorization": f"Bearer {APIFY_API_TOKEN}"},
            )
            resp.raise_for_status()
            raw_items = resp.json()

            # Normalize data
            listings = []
            for item in raw_items:
                # Apify actor returns different field names depending on version
                listing_id = str(item.get("id") or item.get("listingId") or item.get("itemId", ""))
                title = item.get("title") or item.get("name") or "Unknown"
                price = item.get("price")
                url = item.get("url") or item.get("link", "")
                location = item.get("location", "")

                # Parse price if it's a string like "$4,500"
                if isinstance(price, str):
                    price_match = re.search(r'[\d,]+', price.replace("$", ""))
                    if price_match:
                        price = int(price_match.group().replace(",", ""))
                    else:
                        price = None

                if listing_id and price and MIN_PRICE <= price <= MAX_PRICE:
                    listings.append({
                        "id": listing_id,
                        "title": title,
                        "price": price,
                        "url": url,
                        "location": location,
                    })

            log.info(f"Apify returned {len(listings)} valid listings")
            return listings

        except Exception as e:
            log.error(f"Error fetching Apify results: {e}")
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
        f"💸 You Save: ~{value_info['discount_pct']}% below market\n\n"
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
        log.warning("No listings returned from Apify")
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
    log.info(f"   Radius: {RADIUS_MILES} miles from {SEARCH_LOCATION}")
    log.info(f"   Check interval: {CHECK_INTERVAL_SECONDS // 60} minutes")
    log.info(f"   Deal thresholds: 🔥 {int((1-FIRE_DEAL_THRESHOLD)*100)}%+ | ✅ {int((1-GOOD_DEAL_THRESHOLD)*100)}%+")

    # Verify credentials
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("ERROR: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set!")
        return
    if not APIFY_API_TOKEN:
        log.error("ERROR: APIFY_API_TOKEN not set!")
        return

    seen_ids = load_seen_ids()
    log.info(f"   Loaded {len(seen_ids)} previously seen listings")

    # Send startup message
    await send_telegram(
        f"🏍️ <b>Motorcycle Bot is now running!</b>\n"
        f"Searching ${MIN_PRICE:,}–${MAX_PRICE:,} within {RADIUS_MILES} miles.\n"
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
