"""
Riders Share booking-history scraper (best-effort, discovery-first).

Riders Share's dashboard is a logged-in, JS-rendered app, so this can't work
like a plain public scrape. The approach mirrors the Facebook Marketplace
scraper in bot.py: send an authenticated request using your real browser
session cookie, then hunt through any embedded JSON (Next.js __NEXT_DATA__,
data-sjs script tags, or a JSON API response) for booking-shaped data.

This WILL need iteration once run against a real session — the exact page/
API structure can't be verified without one. Until then, `sync_bookings`
logs everything it finds so the discovery loop is fast: run it, read the
log, tell me what came back, and the parsing rules get tightened.

Setup: log into ridersshare.com in Safari/Chrome, open dev tools > Network,
reload the "My Bookings" / host dashboard page, find the request to
ridersshare.com, copy its full `Cookie` request header value, and set it as
the RS_COOKIE_HEADER environment variable.
"""

import json
import logging
import os
import re

import httpx

log = logging.getLogger(__name__)

RS_COOKIE_HEADER = os.getenv("RS_COOKIE_HEADER")

# Candidate pages/endpoints to probe for booking data. Update this list once
# the real dashboard URL structure is known.
CANDIDATE_URLS = [
    "https://ridersshare.com/dashboard/bookings",
    "https://ridersshare.com/host/bookings",
    "https://ridersshare.com/api/host/bookings",
    "https://ridersshare.com/api/bookings",
    "https://app.ridersshare.com/bookings",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                  "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

BOOKING_KEY_TERMS = ["booking", "trip", "reservation", "payout", "rental"]


def find_keys(obj, search_terms, path="", results=None):
    """Recursively collect key paths whose name matches a search term."""
    if results is None:
        results = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if any(term in str(k).lower() for term in search_terms):
                results.append(f"{path}.{k} = {str(v)[:120]}")
            find_keys(v, search_terms, f"{path}.{k}", results)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:50]):
            find_keys(v, search_terms, f"{path}[{i}]", results)
    return results


def extract_embedded_json(html: str) -> list[dict]:
    """Pull out __NEXT_DATA__ and data-sjs JSON blobs, common in modern SPAs."""
    blobs = []

    next_data = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL
    )
    if next_data:
        try:
            blobs.append(json.loads(next_data.group(1)))
        except json.JSONDecodeError:
            log.debug("Found __NEXT_DATA__ but couldn't parse it as JSON")

    for match in re.findall(r'<script type="application/json"[^>]*>(.*?)</script>', html, re.DOTALL):
        try:
            blobs.append(json.loads(match))
        except json.JSONDecodeError:
            continue

    return blobs


async def fetch_candidates() -> dict:
    """Try each candidate URL with the session cookie, return a discovery log."""
    log_lines = []
    findings = []

    async with httpx.AsyncClient(
        timeout=20, follow_redirects=True, headers={**HEADERS, "Cookie": RS_COOKIE_HEADER or ""}
    ) as client:
        for url in CANDIDATE_URLS:
            try:
                resp = await client.get(url)
                log_lines.append(f"GET {url} -> {resp.status_code} ({len(resp.text)} bytes)")

                if resp.status_code != 200:
                    continue

                content_type = resp.headers.get("content-type", "")
                if "application/json" in content_type:
                    try:
                        data = resp.json()
                        keys_found = find_keys(data, BOOKING_KEY_TERMS)
                        log_lines.append(f"  JSON response, {len(keys_found)} booking-shaped keys found")
                        for k in keys_found[:15]:
                            log_lines.append(f"    {k}")
                        findings.append({"url": url, "data": data})
                    except json.JSONDecodeError:
                        log_lines.append("  Could not parse JSON body")
                else:
                    blobs = extract_embedded_json(resp.text)
                    log_lines.append(f"  HTML response, {len(blobs)} embedded JSON blob(s)")
                    for blob in blobs:
                        keys_found = find_keys(blob, BOOKING_KEY_TERMS)
                        if keys_found:
                            log_lines.append(f"    {len(keys_found)} booking-shaped keys found")
                            for k in keys_found[:15]:
                                log_lines.append(f"      {k}")
                            findings.append({"url": url, "data": blob})

            except httpx.RequestError as e:
                log_lines.append(f"GET {url} -> request error: {e}")

    return {"log": "\n".join(log_lines), "findings": findings}


def sync_bookings(conn) -> dict:
    """
    Entry point called from the /sync route. Runs discovery against Riders
    Share and reports what it found. Does not attempt to guess a parser for
    unknown JSON shapes -- once real output is available, add a mapping
    here from Riders Share's actual field names to the bookings table
    (bike_id, start_date, end_date, payout_amount, renter_name,
    platform_booking_id) and insert with `INSERT OR IGNORE` keyed on
    platform_booking_id so re-syncing is safe.
    """
    import asyncio

    if not RS_COOKIE_HEADER:
        return {
            "status": "No RS_COOKIE_HEADER set - running discovery unauthenticated "
                      "(will likely get redirected to login).",
            "log": "Set RS_COOKIE_HEADER and re-run to probe your real dashboard.",
        }

    result = asyncio.run(fetch_candidates())

    if not result["findings"]:
        return {
            "status": "No booking-shaped data found in any candidate URL. "
                      "The real dashboard is probably at a different path than guessed here.",
            "log": result["log"],
        }

    return {
        "status": f"Found {len(result['findings'])} response(s) with booking-shaped keys. "
                   "Share this log to wire up real field parsing and enable import.",
        "log": result["log"],
        "imported": 0,
    }
