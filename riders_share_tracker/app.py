#!/usr/bin/env python3
"""
Riders Share Tracker
Mobile-friendly web app to track rentals, income splits, maintenance,
and owner statements across a fleet of Riders Share bikes.
"""

import calendar
import functools
import hmac
import os
from datetime import date, datetime, timedelta

from flask import Flask, jsonify, redirect, render_template, request, url_for

import db

app = Flask(__name__)

API_TOKEN = os.getenv("API_TOKEN")


def require_api_token(f):
    """Guard for /api/* routes hit by the iOS Shortcut. Requires the
    X-API-Key header to match the API_TOKEN env var (set your own long
    random value - see README's Shortcuts section)."""

    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not API_TOKEN:
            return jsonify({"error": "Server has no API_TOKEN configured"}), 503
        provided = request.headers.get("X-API-Key", "")
        if not hmac.compare_digest(provided, API_TOKEN):
            return jsonify({"error": "Invalid or missing X-API-Key header"}), 401
        return f(*args, **kwargs)

    return wrapper


# ─── SPLIT / CUT CALCULATIONS ────────────────────────────────────────────────

def booking_cuts(bike: dict, payout_amount: float) -> tuple[float, float]:
    """Return (your_cut, owner_cut) for a booking's payout on a given bike."""
    if bike["ownership"] == "own":
        return payout_amount, 0.0
    your_pct = bike["split_pct"]
    return payout_amount * your_pct, payout_amount * (1 - your_pct)


def overlap_days(b_start: date, b_end: date, p_start: date, p_end: date) -> int:
    """Days a booking [b_start, b_end] overlaps a period [p_start, p_end], inclusive."""
    lo = max(b_start, p_start)
    hi = min(b_end, p_end)
    return max(0, (hi - lo).days + 1)


def parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def month_bounds(month_str: str) -> tuple[date, date]:
    """month_str like '2026-07' -> (first day, last day) of that month."""
    year, mon = (int(x) for x in month_str.split("-"))
    first = date(year, mon, 1)
    last = date(year, mon, calendar.monthrange(year, mon)[1])
    return first, last


def adjacent_months(month_str: str) -> tuple[str, str]:
    """Return (prev_month_str, next_month_str) for a 'YYYY-MM' string."""
    year, mon = (int(x) for x in month_str.split("-"))
    prev_year, prev_mon = (year - 1, 12) if mon == 1 else (year, mon - 1)
    next_year, next_mon = (year + 1, 1) if mon == 12 else (year, mon + 1)
    return f"{prev_year:04d}-{prev_mon:02d}", f"{next_year:04d}-{next_mon:02d}"


# ─── DASHBOARD ────────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    conn = db.get_conn()
    today = date.today()
    month_str = request.args.get("month", today.strftime("%Y-%m"))
    period_start, period_end = month_bounds(month_str)

    bikes = conn.execute("SELECT * FROM bikes WHERE active = 1 ORDER BY name").fetchall()

    # Bookings overlapping the selected month
    bookings = conn.execute(
        """SELECT b.*, k.name AS bike_name, k.ownership, k.split_pct, k.owner_name
           FROM bookings b JOIN bikes k ON k.id = b.bike_id
           WHERE b.status != 'cancelled'
             AND b.start_date <= ? AND b.end_date >= ?
           ORDER BY b.start_date""",
        (period_end.isoformat(), period_start.isoformat()),
    ).fetchall()

    total_payout = 0.0
    total_your_cut = 0.0
    total_owner_cut = 0.0
    bike_days_booked = {bike["id"]: 0 for bike in bikes}

    for bk in bookings:
        your_cut, owner_cut = booking_cuts(bk, bk["payout_amount"])
        total_payout += bk["payout_amount"]
        total_your_cut += your_cut
        total_owner_cut += owner_cut
        b_start, b_end = parse_date(bk["start_date"]), parse_date(bk["end_date"])
        days = overlap_days(b_start, b_end, period_start, period_end)
        if bk["bike_id"] in bike_days_booked:
            bike_days_booked[bk["bike_id"]] += days

    days_in_month = (period_end - period_start).days + 1
    utilization = [
        {
            "bike": bike,
            "days_booked": bike_days_booked.get(bike["id"], 0),
            "pct": round(100 * bike_days_booked.get(bike["id"], 0) / days_in_month),
        }
        for bike in bikes
    ]

    upcoming = conn.execute(
        """SELECT b.*, k.name AS bike_name FROM bookings b JOIN bikes k ON k.id = b.bike_id
           WHERE b.start_date >= ? AND b.status != 'cancelled'
           ORDER BY b.start_date LIMIT 5""",
        (today.isoformat(),),
    ).fetchall()

    maintenance_due = conn.execute(
        """SELECT m.*, k.name AS bike_name FROM maintenance m JOIN bikes k ON k.id = m.bike_id
           WHERE m.next_due_date IS NOT NULL AND m.next_due_date <= ?
           ORDER BY m.next_due_date LIMIT 10""",
        ((today + timedelta(days=14)).isoformat(),),
    ).fetchall()

    conn.close()
    prev_month, next_month = adjacent_months(month_str)
    return render_template(
        "dashboard.html",
        month_str=month_str,
        prev_month=prev_month,
        next_month=next_month,
        total_payout=total_payout,
        total_your_cut=total_your_cut,
        total_owner_cut=total_owner_cut,
        utilization=utilization,
        upcoming=upcoming,
        maintenance_due=maintenance_due,
        bike_count=len(bikes),
        own_count=sum(1 for b in bikes if b["ownership"] == "own"),
        managed_count=sum(1 for b in bikes if b["ownership"] == "managed"),
        today=today,
    )


# ─── BIKES ────────────────────────────────────────────────────────────────────

@app.route("/bikes")
def bikes_list():
    conn = db.get_conn()
    bikes = conn.execute("SELECT * FROM bikes ORDER BY ownership, name").fetchall()
    conn.close()
    return render_template("bikes.html", bikes=bikes)


@app.route("/bikes/new", methods=["GET", "POST"])
def bike_new():
    if request.method == "POST":
        conn = db.get_conn()
        ownership = request.form["ownership"]
        conn.execute(
            """INSERT INTO bikes (name, make, model, year, ownership, owner_name, split_pct, odometer)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                request.form["name"],
                request.form.get("make", ""),
                request.form.get("model", ""),
                request.form.get("year") or None,
                ownership,
                request.form.get("owner_name") if ownership == "managed" else None,
                float(request.form.get("split_pct") or 0.5) if ownership == "managed" else 1.0,
                int(request.form.get("odometer") or 0),
            ),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("bikes_list"))
    return render_template("bike_form.html", bike=None)


@app.route("/bikes/<int:bike_id>/edit", methods=["GET", "POST"])
def bike_edit(bike_id):
    conn = db.get_conn()
    if request.method == "POST":
        ownership = request.form["ownership"]
        conn.execute(
            """UPDATE bikes SET name=?, make=?, model=?, year=?, ownership=?, owner_name=?,
               split_pct=?, odometer=?, active=? WHERE id=?""",
            (
                request.form["name"],
                request.form.get("make", ""),
                request.form.get("model", ""),
                request.form.get("year") or None,
                ownership,
                request.form.get("owner_name") if ownership == "managed" else None,
                float(request.form.get("split_pct") or 0.5) if ownership == "managed" else 1.0,
                int(request.form.get("odometer") or 0),
                1 if request.form.get("active") else 0,
                bike_id,
            ),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("bikes_list"))
    bike = conn.execute("SELECT * FROM bikes WHERE id = ?", (bike_id,)).fetchone()
    conn.close()
    return render_template("bike_form.html", bike=bike)


@app.route("/bikes/<int:bike_id>/delete", methods=["POST"])
def bike_delete(bike_id):
    conn = db.get_conn()
    conn.execute("DELETE FROM bikes WHERE id = ?", (bike_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("bikes_list"))


# ─── BOOKINGS ─────────────────────────────────────────────────────────────────

@app.route("/bookings")
def bookings_list():
    conn = db.get_conn()
    month_str = request.args.get("month", date.today().strftime("%Y-%m"))
    bike_id = request.args.get("bike_id", type=int)
    period_start, period_end = month_bounds(month_str)

    query = """SELECT b.*, k.name AS bike_name, k.ownership, k.split_pct
               FROM bookings b JOIN bikes k ON k.id = b.bike_id
               WHERE b.start_date <= ? AND b.end_date >= ?"""
    params = [period_end.isoformat(), period_start.isoformat()]
    if bike_id:
        query += " AND b.bike_id = ?"
        params.append(bike_id)
    query += " ORDER BY b.start_date DESC"

    bookings = conn.execute(query, params).fetchall()
    rows = []
    for bk in bookings:
        your_cut, owner_cut = booking_cuts(bk, bk["payout_amount"])
        rows.append({"b": bk, "your_cut": your_cut, "owner_cut": owner_cut})

    bikes = conn.execute("SELECT * FROM bikes ORDER BY name").fetchall()
    conn.close()
    prev_month, next_month = adjacent_months(month_str)
    return render_template(
        "bookings.html", rows=rows, bikes=bikes, month_str=month_str, bike_id=bike_id,
        prev_month=prev_month, next_month=next_month,
    )


@app.route("/bookings/new", methods=["GET", "POST"])
def booking_new():
    conn = db.get_conn()
    if request.method == "POST":
        conn.execute(
            """INSERT INTO bookings (bike_id, start_date, end_date, payout_amount,
               renter_name, status, source, notes) VALUES (?, ?, ?, ?, ?, ?, 'manual', ?)""",
            (
                request.form["bike_id"],
                request.form["start_date"],
                request.form["end_date"],
                float(request.form.get("payout_amount") or 0),
                request.form.get("renter_name", ""),
                request.form.get("status", "completed"),
                request.form.get("notes", ""),
            ),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("bookings_list"))
    bikes = conn.execute("SELECT * FROM bikes WHERE active = 1 ORDER BY name").fetchall()
    conn.close()
    return render_template("booking_form.html", booking=None, bikes=bikes)


@app.route("/bookings/<int:booking_id>/edit", methods=["GET", "POST"])
def booking_edit(booking_id):
    conn = db.get_conn()
    if request.method == "POST":
        conn.execute(
            """UPDATE bookings SET bike_id=?, start_date=?, end_date=?, payout_amount=?,
               renter_name=?, status=?, notes=? WHERE id=?""",
            (
                request.form["bike_id"],
                request.form["start_date"],
                request.form["end_date"],
                float(request.form.get("payout_amount") or 0),
                request.form.get("renter_name", ""),
                request.form.get("status", "completed"),
                request.form.get("notes", ""),
                booking_id,
            ),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("bookings_list"))
    booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    bikes = conn.execute("SELECT * FROM bikes ORDER BY name").fetchall()
    conn.close()
    return render_template("booking_form.html", booking=booking, bikes=bikes)


@app.route("/bookings/<int:booking_id>/delete", methods=["POST"])
def booking_delete(booking_id):
    conn = db.get_conn()
    conn.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("bookings_list"))


# ─── CALENDAR ─────────────────────────────────────────────────────────────────

@app.route("/calendar")
def calendar_view():
    conn = db.get_conn()
    month_str = request.args.get("month", date.today().strftime("%Y-%m"))
    bike_id = request.args.get("bike_id", type=int)
    period_start, period_end = month_bounds(month_str)

    query = """SELECT b.*, k.name AS bike_name FROM bookings b JOIN bikes k ON k.id = b.bike_id
               WHERE b.status != 'cancelled' AND b.start_date <= ? AND b.end_date >= ?"""
    params = [period_end.isoformat(), period_start.isoformat()]
    if bike_id:
        query += " AND b.bike_id = ?"
        params.append(bike_id)
    bookings = conn.execute(query, params).fetchall()

    days_in_month = period_end.day
    day_bookings = {d: [] for d in range(1, days_in_month + 1)}
    for bk in bookings:
        b_start, b_end = parse_date(bk["start_date"]), parse_date(bk["end_date"])
        for d in range(1, days_in_month + 1):
            cur = date(period_start.year, period_start.month, d)
            if b_start <= cur <= b_end:
                day_bookings[d].append(bk)

    first_weekday = period_start.weekday()  # Monday=0
    leading_blanks = (first_weekday + 1) % 7  # start week on Sunday

    bikes = conn.execute("SELECT * FROM bikes ORDER BY name").fetchall()
    conn.close()
    prev_month, next_month = adjacent_months(month_str)
    return render_template(
        "calendar.html",
        month_str=month_str,
        period_start=period_start,
        days_in_month=days_in_month,
        day_bookings=day_bookings,
        leading_blanks=leading_blanks,
        bikes=bikes,
        bike_id=bike_id,
        prev_month=prev_month,
        next_month=next_month,
        today=date.today(),
    )


# ─── MAINTENANCE ──────────────────────────────────────────────────────────────

@app.route("/maintenance")
def maintenance_list():
    conn = db.get_conn()
    records = conn.execute(
        """SELECT m.*, k.name AS bike_name FROM maintenance m JOIN bikes k ON k.id = m.bike_id
           ORDER BY m.date DESC"""
    ).fetchall()
    conn.close()
    return render_template("maintenance.html", records=records)


@app.route("/maintenance/new", methods=["GET", "POST"])
def maintenance_new():
    conn = db.get_conn()
    if request.method == "POST":
        conn.execute(
            """INSERT INTO maintenance (bike_id, date, type, odometer, cost, notes,
               next_due_date, next_due_odometer) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                request.form["bike_id"],
                request.form["date"],
                request.form["type"],
                int(request.form.get("odometer") or 0) or None,
                float(request.form.get("cost") or 0),
                request.form.get("notes", ""),
                request.form.get("next_due_date") or None,
                int(request.form.get("next_due_odometer") or 0) or None,
            ),
        )
        # Keep the bike's odometer current if this record is the latest reading
        odo = request.form.get("odometer")
        if odo:
            conn.execute(
                "UPDATE bikes SET odometer = ? WHERE id = ? AND odometer < ?",
                (int(odo), request.form["bike_id"], int(odo)),
            )
        conn.commit()
        conn.close()
        return redirect(url_for("maintenance_list"))
    bikes = conn.execute("SELECT * FROM bikes WHERE active = 1 ORDER BY name").fetchall()
    conn.close()
    return render_template("maintenance_form.html", bikes=bikes)


# ─── OWNER STATEMENTS ─────────────────────────────────────────────────────────

@app.route("/owners")
def owners_list():
    conn = db.get_conn()
    month_str = request.args.get("month", date.today().strftime("%Y-%m"))
    period_start, period_end = month_bounds(month_str)

    managed_bikes = conn.execute(
        "SELECT * FROM bikes WHERE ownership = 'managed' ORDER BY owner_name"
    ).fetchall()

    owners = {}
    for bike in managed_bikes:
        owners.setdefault(bike["owner_name"], []).append(bike)

    statements = []
    for owner_name, owner_bikes in owners.items():
        bike_ids = [b["id"] for b in owner_bikes]
        placeholders = ",".join("?" * len(bike_ids))
        bookings = conn.execute(
            f"""SELECT b.*, k.split_pct FROM bookings b JOIN bikes k ON k.id = b.bike_id
                WHERE b.bike_id IN ({placeholders}) AND b.status != 'cancelled'
                AND b.start_date <= ? AND b.end_date >= ?""",
            (*bike_ids, period_end.isoformat(), period_start.isoformat()),
        ).fetchall()
        total_payout = sum(bk["payout_amount"] for bk in bookings)
        total_owner_cut = sum(bk["payout_amount"] * (1 - bk["split_pct"]) for bk in bookings)
        total_your_cut = total_payout - total_owner_cut
        statements.append(
            {
                "owner_name": owner_name,
                "bikes": owner_bikes,
                "booking_count": len(bookings),
                "total_payout": total_payout,
                "total_owner_cut": total_owner_cut,
                "total_your_cut": total_your_cut,
            }
        )

    conn.close()
    prev_month, next_month = adjacent_months(month_str)
    return render_template(
        "owners.html", statements=statements, month_str=month_str,
        prev_month=prev_month, next_month=next_month,
    )


# ─── SYNC (best-effort Riders Share scrape) ──────────────────────────────────

@app.route("/sync", methods=["GET", "POST"])
def sync():
    result = None
    if request.method == "POST":
        import scraper

        result = scraper.sync_bookings(db.get_conn())
    return render_template("sync.html", result=result, has_cookie=bool(os.getenv("RS_COOKIE_HEADER")))


# ─── DEVICE API (for the iOS Shortcut) ───────────────────────────────────────
# Instead of scraping Riders Share's servers, these endpoints let a Shortcut
# running on your phone push data it already has (from a quick form, an
# OCR'd screenshot, or a parsed email) straight into the tracker.

@app.route("/api/health")
def api_health():
    """Unauthenticated - just lets the Shortcut confirm the URL is reachable."""
    return jsonify({"status": "ok"})


@app.route("/api/bikes")
@require_api_token
def api_bikes():
    conn = db.get_conn()
    bikes = conn.execute(
        "SELECT id, name, ownership, owner_name, split_pct FROM bikes WHERE active = 1 ORDER BY name"
    ).fetchall()
    conn.close()
    return jsonify([dict(b) for b in bikes])


@app.route("/api/bookings", methods=["POST"])
@require_api_token
def api_booking_create():
    payload = request.get_json(silent=True) or request.form
    conn = db.get_conn()

    bike = None
    if payload.get("bike_id"):
        bike = conn.execute("SELECT * FROM bikes WHERE id = ?", (payload["bike_id"],)).fetchone()
    elif payload.get("bike_name"):
        bike = conn.execute(
            "SELECT * FROM bikes WHERE active = 1 AND lower(name) = lower(?)", (payload["bike_name"],)
        ).fetchone()

    if not bike:
        valid_names = [r["name"] for r in conn.execute("SELECT name FROM bikes WHERE active = 1")]
        conn.close()
        return jsonify({"error": "Unknown bike", "valid_bike_names": valid_names}), 404

    for field in ("start_date", "end_date", "payout_amount"):
        if not payload.get(field):
            conn.close()
            return jsonify({"error": f"Missing required field: {field}"}), 400

    try:
        payout_amount = float(payload["payout_amount"])
    except (TypeError, ValueError):
        conn.close()
        return jsonify({"error": "payout_amount must be a number"}), 400

    cur = conn.execute(
        """INSERT OR IGNORE INTO bookings
           (bike_id, start_date, end_date, payout_amount, renter_name, platform_booking_id,
            status, source, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'device', ?)""",
        (
            bike["id"],
            payload["start_date"],
            payload["end_date"],
            payout_amount,
            payload.get("renter_name", ""),
            payload.get("platform_booking_id") or None,
            payload.get("status", "completed"),
            payload.get("notes", ""),
        ),
    )
    conn.commit()

    if cur.rowcount == 0:
        conn.close()
        return jsonify({"status": "duplicate", "message": "A booking with that platform_booking_id already exists"}), 200

    your_cut, owner_cut = booking_cuts(bike, payout_amount)
    conn.close()
    return jsonify(
        {
            "status": "ok",
            "booking_id": cur.lastrowid,
            "bike_name": bike["name"],
            "payout_amount": payout_amount,
            "your_cut": your_cut,
            "owner_cut": owner_cut,
        }
    ), 201


if __name__ == "__main__":
    db.init_db()
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.getenv("DEBUG", "false").lower() == "true")
