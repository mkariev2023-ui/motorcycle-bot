# Riders Share Tracker

A mobile-friendly web app for tracking a Riders Share motorcycle fleet:
bookings/income, 50/50 owner splits, maintenance, and a booking calendar.
Built to run from your iPhone's browser (Safari) — no App Store needed.

Handles a fleet mix of bikes you own outright and bikes you manage for
other owners at a split (default 50/50, configurable per bike).

## Features

- **Dashboard** — this month's payout total, your cut, amount owed to
  owners, fleet utilization %, upcoming bookings, maintenance due soon.
- **Calendar** — month view of every bike's bookings.
- **Bookings** — log rentals manually (bike, dates, payout amount, renter,
  status). Your cut / owner cut is computed automatically per bike's split.
- **Bikes** — manage your 10 bikes: mark each as "own" or "managed for
  [owner name]" with a split %, track odometer.
- **Maintenance** — log service history per bike with cost and next-due
  date/mileage; due items surface on the dashboard.
- **Owner statements** — per-owner monthly summary of payout, their cut,
  and your cut, for the bikes you manage on their behalf.
- **Sync** (best-effort) — attempts to pull booking history directly from
  Riders Share using your logged-in session cookie. See "Syncing from
  Riders Share" below — this needs a short setup/iteration step since
  Riders Share doesn't have a public API.

## Running locally

```bash
cd riders_share_tracker
pip install -r requirements.txt
python app.py
```

Open `http://localhost:5000` — or, from your iPhone on the same Wi-Fi,
`http://<your-computer's-LAN-IP>:5000`. In Safari, use Share → **Add to
Home Screen** to make it launch full-screen like a real app.

## Deploying so it's reachable from your phone anywhere

Same pattern as the existing bot in this repo — Railway or Render both
work. Point the service at the `riders_share_tracker/` directory, it will
pick up `Procfile` (`web: python app.py`) and `requirements.txt`
automatically. Set the `PORT` env var if your platform requires it (both
Railway and Render set it for you).

The SQLite database lives at `riders_share_tracker/data/tracker.db` and
persists on disk — make sure your deployment target gives you a
persistent volume (Railway volumes, Render disks), otherwise data resets
on redeploy.

## Getting started

1. Deploy or run locally, open it in Safari.
2. Go to **Bikes** → add your 4 owned bikes (ownership: "Own") and your 6
   managed bikes (ownership: "Managed", set owner name + split %, default
   0.5 for 50/50).
3. Go to **Bookings** → log rentals as they happen (or backfill recent
   ones) with the payout amount Riders Share actually paid you.
4. Check **Dashboard** and **Owners** for running totals.

## Logging bookings from your iPhone with a Shortcut (recommended)

Instead of scraping Riders Share's servers, an **iOS Shortcut** running on
your own phone can push data straight into the tracker — you're just
using the device you're already logged into Riders Share on, over an API
the tracker exposes for exactly this.

### 1. Set an API token

Pick a long random value and set it as an environment variable on your
deployment (or locally when testing):

```bash
export API_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
```

Keep this value handy — the Shortcut needs to send it on every request.
Without `API_TOKEN` set, the `/api/*` endpoints refuse all requests.

### 2. Build the Shortcut

Open the **Shortcuts** app on your iPhone → **+** → add these actions in
order:

1. **Choose from Menu** — title it "Which bike?", add a menu item for each
   of your 10 bikes (edit this list if your fleet changes).
2. **Ask for Input** → Date, prompt "Start date".
3. **Ask for Input** → Date, prompt "End date".
4. **Format Date** on the start date result → Date Format: Custom →
   `yyyy-MM-dd`. Do the same for the end date. (The API needs
   `YYYY-MM-DD` strings, not Shortcuts' native date format.)
5. **Ask for Input** → Number, prompt "Payout amount ($)".
6. **Ask for Input** → Text, prompt "Renter name (optional)".
7. **Get Contents of URL**:
   - URL: `https://<your-deployed-url>/api/bookings`
   - Method: `POST`
   - Headers: `X-API-Key` → your `API_TOKEN` value; `Content-Type` →
     `application/json`
   - Request Body: **JSON**, with fields:
     - `bike_name` → the Menu result from step 1
     - `start_date` / `end_date` → the formatted dates from step 4
     - `payout_amount` → the Number from step 5
     - `renter_name` → the Text from step 6
8. **Get Dictionary from Input** on the result of step 7, then
   **Show Notification** or **Show Result** displaying the `your_cut` and
   `owner_cut` values, so you get instant confirmation of the split.

Add it to your Home Screen (or trigger with "Hey Siri, log a rental") so
logging a booking after each rental takes about 10 seconds.

Test the API is reachable first with:

```bash
curl https://<your-deployed-url>/api/health
curl -H "X-API-Key: $API_TOKEN" https://<your-deployed-url>/api/bikes
```

### Other device-side options

The same `/api/bookings` endpoint also works from:
- A **Screenshot + OCR Shortcut** — an automation on "screenshot taken"
  that runs Apple's on-device text recognition on a Riders Share booking
  screen, tries to pull out dates/amount, and posts them (needs the parsing
  logic dialed in against real screenshots — more fragile than the
  quick-log form above).
- An **email-parsing Shortcut** — a Mail automation that fires when a
  booking/payout email from Riders Share arrives and forwards the parsed
  fields (only viable if those emails have a consistent structure).
- **Riders Share's Share Sheet**, if a trip/booking screen exposes one.

## Alternative: scraping Riders Share's servers (not recommended)

`scraper.py` is a discovery-first scraper (same pattern as `bot.py`, the
Facebook Marketplace bot elsewhere in this repo) that sends your browser
session cookie with a request and looks for embedded booking JSON. It's
kept here as a fallback, but the Shortcut approach above is simpler, more
reliable, and doesn't risk Riders Share's bot detection flagging your
account. See `scraper.py`'s docstring if you want to try it anyway.
