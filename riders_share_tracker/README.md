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

## Syncing from Riders Share

Riders Share's dashboard is a logged-in web app, not a public API, so
`scraper.py` works the same way `bot.py` (the Facebook Marketplace bot
elsewhere in this repo) does: it sends your real browser session cookie
with the request and looks for embedded booking data in the response.

This **will need one round of iteration** — the exact page/API structure
can't be verified without a live logged-in session to test against.

To try it:

1. Log into ridersshare.com in Safari or Chrome on your computer.
2. Open Dev Tools → Network tab, reload your bookings/host dashboard page.
3. Click the main document request, find the `Cookie` request header, copy
   its full value.
4. Set it as an environment variable: `RS_COOKIE_HEADER="<paste here>"`.
5. Go to **Dashboard → Sync from Riders Share → Run sync now**.
6. It'll log what it finds (status codes, any booking-shaped JSON keys).
   Share that log in a follow-up session and the field-mapping in
   `scraper.py` can be tightened to actually import bookings.

Until that's dialed in, manual entry is the reliable path and only takes
a few seconds per booking.
