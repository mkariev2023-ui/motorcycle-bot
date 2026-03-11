#!/usr/bin/env python3
"""
Facebook Marketplace Motorcycle Deal Finder
Scrapes listings, compares to KBB estimates, and sends good deals to Telegram.
"""

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

# ─── CONFIG ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8277158161:AAGPpCxXIRvV5sJ_H_zKSopvJ5uErHqkAFs")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID",   "844726737")

SEARCH_LOCATION    = os.getenv("SEARCH_LOCATION", "Tustin")   # e.g. "dallas"
SEARCH_ZIP         = os.getenv("SEARCH_ZIP",      "92782")        # your ZIP code
RADIUS_MILES       = 200
MIN_PRICE          = 2000
MAX_PRICE          = 7500

# A listing is a "good deal" if price <= KBB_DEAL_THRESHOLD * KBB estimate
# 0.85 means 15% or more below KBB = good deal
KBB_DEAL_THRESHOLD = 0.85

CHECK_INTERVAL_SECONDS = 900   # 15 minutes between scans

SEEN_IDS_FILE = Path("seen_listings.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ─── SEEN LISTINGS PERSISTENCE ───────────────────────────────────────────────

def load_seen_ids() -> set:
    if SEEN_IDS_FILE.exists():
        return set(json.loads(SEEN_IDS_FILE.read_text()))
    return set()

def save_seen_ids(ids: set):
    SEEN_IDS_FILE.write_text(json.dumps(list(ids)))


# ─── FACEBOOK MARKETPLACE SCRAPER ────────────────────────────────────────────

async def scrape_facebook_marketplace(playwright) -> list[dict]:
    """Scrape FB Marketplace motorcycle listings using a headless browser."""
    listings = []

    # Build search URL
    url = (
        f"https://www.facebook.com/marketplace/{SEARCH_LOCATION}/vehicles/motorcycles"
        f"?minPrice={MIN_PRICE}&maxPrice={MAX_PRICE}"
        f"&radius={RADIUS_MILES}&exact=false"
    )

    log.info(f"Scraping: {url}")

    browser = await playwright.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-setuid-sandbox"]
    )

    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        ),
        viewport={"width": 390, "height": 844},
    )

    page = await context.new_page()

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)  # let JS render

        # Scroll to load more listings
        for _ in range(4):
            await page.evaluate("window.scrollBy(0, 1200)")
            await asyncio.sleep(1.5)

        # Extract listing cards via JSON-LD or aria attributes
        raw = await page.evaluate("""
            () => {
                const results = [];
                // FB Marketplace listing cards share a common structure
                const cards = document.querySelectorAll('a[href*="/marketplace/item/"]');
                cards.forEach(card => {
                    const href = card.getAttribute('href') || '';
                    const idMatch = href.match(/\\/marketplace\\/item\\/(\\d+)/);
                    if (!idMatch) return;

                    const id = idMatch[1];
                    const text = card.innerText || '';
                    const lines = text.split('\\n').map(l => l.trim()).filter(Boolean);

                    // Heuristic parsing: first line often title, then price, then location
                    const priceMatch = text.match(/\\$([\\d,]+)/);
                    const price = priceMatch ? parseInt(priceMatch[1].replace(/,/g, '')) : null;

                    results.push({
                        id,
                        url: 'https://www.facebook.com' + href.split('?')[0],
                        title: lines[0] || 'Unknown',
                        price,
                        raw_text: lines.slice(0, 6).join(' | '),
                    });
                });
                // Deduplicate by id
                const seen = new Set();
                return results.filter(r => {
                    if (seen.has(r.id)) return false;
                    seen.add(r.id);
                    return true;
                });
            }
        """)

        listings = [r for r in raw if r.get("price") and MIN_PRICE <= r["price"] <= MAX_PRICE]
        log.info(f"Found {len(listings)} listings in price range")

    except Exception as e:
        log.error(f"Scrape error: {e}")
    finally:
        await browser.close()

    return listings


# ─── KBB VALUE ESTIMATOR ─────────────────────────────────────────────────────

def parse_year_make_model(title: str) -> tuple[str, str, str]:
    """Best-effort parse of year, make, model from a listing title."""
    year_match = re.search(r'\b(19|20)\d{2}\b', title)
    year = year_match.group() if year_match else ""

    makes = [
        "Honda", "Yamaha", "Kawasaki", "Suzuki", "Harley", "Harley-Davidson",
        "Ducati", "BMW", "KTM", "Triumph", "Royal Enfield", "Indian",
        "Aprilia", "Husqvarna", "Can-Am", "Moto Guzzi", "Zero"
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


async def estimate_kbb_value(title: str, listed_price: int) -> dict:
    """
    Attempt to fetch KBB estimate via their public API / page.
    Falls back to a heuristic if unavailable.
    """
    year, make, model = parse_year_make_model(title)

    # KBB doesn't have a free public API; we use their search page and scrape
    # the estimated value range shown. If blocked, we fall back gracefully.
    kbb_estimate = None
    source = "heuristic"

    if year and make:
        try:
            search_url = (
                f"https://www.kbb.com/motorcycles/{make.lower().replace(' ', '-')}/"
                f"?year={year}"
            )
            async with httpx.AsyncClient(
                timeout=10,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0"}
            ) as client:
                resp = await client.get(search_url)
                # Look for price patterns like $4,500 - $6,200
                prices = re.findall(r'\$(\d{1,3}(?:,\d{3})*)', resp.text)
                numeric = [int(p.replace(',', '')) for p in prices
                           if 1000 < int(p.replace(',', '')) < 50000]
                if numeric:
                    kbb_estimate = int(sum(numeric[:4]) / len(numeric[:4]))
                    source = "kbb_page"
        except Exception:
            pass

    # Heuristic fallback: motorcycles typically depreciate ~15% from MSRP
    # Use listed price as anchor if KBB unavailable
    if not kbb_estimate:
        # Conservative: assume listing is roughly at market
        # Flag as deal only if significantly below similar avg
        kbb_estimate = int(listed_price * 1.12)  # assume 12% above asking = market
        source = "heuristic"

    discount_pct = round((1 - listed_price / kbb_estimate) * 100, 1)
    is_deal = listed_price <= kbb_estimate * KBB_DEAL_THRESHOLD

    return {
        "kbb_estimate": kbb_estimate,
        "discount_pct": discount_pct,
        "is_deal": is_deal,
        "source": source,
        "year": year,
        "make": make,
        "model": model,
    }


# ─── TELEGRAM NOTIFIER ───────────────────────────────────────────────────────

async def send_telegram(message: str):
    """Send a message to Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                log.error(f"Telegram error: {resp.text}")
            else:
                log.info("Telegram notification sent ✅")
    except Exception as e:
        log.error(f"Telegram send failed: {e}")


def format_deal_message(listing: dict, kbb_info: dict) -> str:
    deal_emoji = "🔥" if kbb_info["discount_pct"] >= 20 else "✅"
    kbb_source = "KBB" if kbb_info["source"] == "kbb_page" else "Est. Market"

    msg = (
        f"{deal_emoji} <b>MOTORCYCLE DEAL ALERT</b> {deal_emoji}\n\n"
        f"📋 <b>{listing['title']}</b>\n"
        f"💰 Listed: <b>${listing['price']:,}</b>\n"
        f"📊 {kbb_source} Value: ~${kbb_info['kbb_estimate']:,}\n"
        f"💸 You Save: ~{kbb_info['discount_pct']}% below market\n\n"
        f"🔗 <a href=\"{listing['url']}\">View on Facebook Marketplace</a>\n\n"
        f"⏰ Found at {datetime.now().strftime('%b %d, %Y %I:%M %p')}"
    )
    return msg


# ─── MAIN LOOP ────────────────────────────────────────────────────────────────

async def run_once(playwright, seen_ids: set) -> set:
    listings = await scrape_facebook_marketplace(playwright)
    new_deals = 0

    for listing in listings:
        lid = listing["id"]
        if lid in seen_ids:
            continue

        seen_ids.add(lid)

        # Check if it's a good deal
        kbb_info = await estimate_kbb_value(listing["title"], listing["price"])
        log.info(
            f"  [{lid}] {listing['title'][:50]} | ${listing['price']:,} | "
            f"~{kbb_info['discount_pct']}% below est. market"
        )

        if kbb_info["is_deal"]:
            msg = format_deal_message(listing, kbb_info)
            await send_telegram(msg)
            new_deals += 1
            await asyncio.sleep(1)  # rate limit

    log.info(f"Scan complete. {new_deals} new deal(s) sent to Telegram.")
    save_seen_ids(seen_ids)
    return seen_ids


async def main():
    log.info("🏍️  Motorcycle Deal Bot starting up...")
    log.info(f"   Price range: ${MIN_PRICE:,}–${MAX_PRICE:,}")
    log.info(f"   Radius: {RADIUS_MILES} miles")
    log.info(f"   Check interval: {CHECK_INTERVAL_SECONDS // 60} min")

    seen_ids = load_seen_ids()
    log.info(f"   Already seen: {len(seen_ids)} listings")

    # Send startup message
    await send_telegram(
        "🏍️ <b>Motorcycle Bot is now running!</b>\n"
        f"Searching ${MIN_PRICE:,}–${MAX_PRICE:,} within {RADIUS_MILES} miles.\n"
        "I'll alert you the moment a good deal appears. 🔥"
    )

    async with async_playwright() as playwright:
        while True:
            try:
                seen_ids = await run_once(playwright, seen_ids)
            except Exception as e:
                log.error(f"Unexpected error in run loop: {e}")

            log.info(f"Sleeping {CHECK_INTERVAL_SECONDS // 60} minutes until next scan...")
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
