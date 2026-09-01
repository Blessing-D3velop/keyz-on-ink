#!/usr/bin/env python3
"""
KEYZ INK — backend server
==========================
Pure Python standard library (sqlite3, http.server, hashlib, secrets) —
no pip install required. Serves the public website, a JSON booking API,
an admin login + dashboard API, and a PayFast ITN webhook receiver.

RUN LOCALLY:
    python3 server.py
    -> visit http://localhost:8000  (public site)
    -> visit http://localhost:8000/admin  (admin dashboard)

FIRST-RUN ADMIN ACCOUNT:
    Set these environment variables before first run (recommended),
    otherwise a default admin/change-me-now account is created and a
    warning is printed every time you start the server until you change it.

        export ADMIN_USERNAME="youradminname"
        export ADMIN_PASSWORD="a-strong-password"

DEPLOYING FOR REAL (so PayFast can reach it and customers can pay):
    This needs to run on a real, publicly reachable HTTPS host — PayFast's
    payment-confirmation webhook (ITN) cannot reach your laptop or this
    sandbox. Any of these work with zero code changes:
        - Render.com / Railway.app (free/low-cost, HTTPS included)
        - A small VPS (DigitalOcean, Hetzner) behind Caddy/Nginx for HTTPS
    See README.md for exact steps.
"""

import http.server
import socketserver
import sqlite3
import json
import os
import re
import hmac
import hashlib
import secrets
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http import cookies

# --------------------------------------------------------------------------
# CONFIG
# --------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(BASE_DIR, "public")
DB_PATH = os.path.join(BASE_DIR, "data", "keyzink.db")
PORT = int(os.environ.get("PORT", 8000))

SESSION_COOKIE_NAME = "keyzink_admin_session"
SESSION_LIFETIME_HOURS = 12

DEFAULT_ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "change-me-now")

DEPOSIT_AMOUNT = 200.00

# PayFast — required only for verifying the ITN webhook signature.
# Get this from your PayFast account: Settings -> Integration -> Passphrase.
PAYFAST_PASSPHRASE = os.environ.get("PAYFAST_PASSPHRASE", "")
PAYFAST_VALIDATE_URL = "https://sandbox.payfast.co.za/eng/query/validate"  # switch to
# "https://www.payfast.co.za/eng/query/validate" once you go live


# --------------------------------------------------------------------------
# DATABASE
# --------------------------------------------------------------------------
def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            full_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            email TEXT NOT NULL,
            service TEXT NOT NULL,
            appt_date TEXT NOT NULL,
            appt_time TEXT NOT NULL,
            description TEXT,
            deposit_amount REAL NOT NULL DEFAULT 200,
            payment_status TEXT NOT NULL DEFAULT 'pending',
            payfast_payment_id TEXT,
            booking_status TEXT NOT NULL DEFAULT 'new',
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
        """
    )
    conn.commit()

    row = conn.execute("SELECT COUNT(*) AS c FROM admin_users").fetchone()
    if row["c"] == 0:
        create_admin_user(conn, DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD)
        if DEFAULT_ADMIN_PASSWORD == "change-me-now":
            print("=" * 70)
            print("⚠️  WARNING: using the DEFAULT admin login (admin / change-me-now)")
            print("    Set ADMIN_USERNAME and ADMIN_PASSWORD env vars, delete")
            print("    data/keyzink.db, and restart before this goes live.")
            print("=" * 70)
    conn.close()


def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    pw_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), 200_000
    ).hex()
    return pw_hash, salt


def create_admin_user(conn, username, password):
    pw_hash, salt = hash_password(password)
    conn.execute(
        "INSERT OR REPLACE INTO admin_users (username, password_hash, salt, created_at) "
        "VALUES (?, ?, ?, ?)",
        (username, pw_hash, salt, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def verify_admin_login(username, password):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM admin_users WHERE username = ?", (username,)
    ).fetchone()
    conn.close()
    if not row:
        return False
    check_hash, _ = hash_password(password, row["salt"])
    return hmac.compare_digest(check_hash, row["password_hash"])


def create_session(username):
    conn = get_db()
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=SESSION_LIFETIME_HOURS)
    conn.execute(
        "INSERT INTO sessions (token, username, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (token, username, now.isoformat(), expires.isoformat()),
    )
    conn.commit()
    conn.close()
    return token, expires


def get_session(token):
    if not token:
        return None
    conn = get_db()
    row = conn.execute("SELECT * FROM sessions WHERE token = ?", (token,)).fetchone()
    conn.close()
    if not row:
        return None
    if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
        return None
    return row


def delete_session(token):
    conn = get_db()
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------
# BOOKING HELPERS
# --------------------------------------------------------------------------
REQUIRED_BOOKING_FIELDS = [
    "fullName", "phone", "email", "service", "date", "time", "description"
]


def create_booking(data):
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO bookings
           (created_at, full_name, phone, email, service, appt_date, appt_time,
            description, deposit_amount, payment_status, booking_status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 'new')""",
        (
            datetime.now(timezone.utc).isoformat(),
            data["fullName"].strip(),
            data["phone"].strip(),
            data["email"].strip(),
            data["service"].strip(),
            data["date"].strip(),
            data["time"].strip(),
            data.get("description", "").strip(),
            DEPOSIT_AMOUNT,
        ),
    )
    conn.commit()
    booking_id = cur.lastrowid
    conn.close()
    return booking_id


def list_bookings(status_filter=None):
    conn = get_db()
    if status_filter:
        rows = conn.execute(
            "SELECT * FROM bookings WHERE payment_status = ? OR booking_status = ? "
            "ORDER BY id DESC",
            (status_filter, status_filter),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM bookings ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_booking(booking_id, fields):
    allowed = {"payment_status", "booking_status", "notes", "payfast_payment_id"}
    sets, values = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k} = ?")
            values.append(v)
    if not sets:
        return False
    values.append(booking_id)
    conn = get_db()
    conn.execute(f"UPDATE bookings SET {', '.join(sets)} WHERE id = ?", values)
    conn.commit()
    changed = conn.total_changes > 0
    conn.close()
    return changed


def delete_booking(booking_id):
    conn = get_db()
    conn.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
    conn.commit()
    conn.close()


def find_booking_by_m_payment_id(m_payment_id):
    # m_payment_id we generate client-side looks like "KEYZINK-<bookingid>-<timestamp>"
    match = re.match(r"KEYZINK-(\d+)-", m_payment_id or "")
    if not match:
        return None
    return int(match.group(1))


def stats():
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) c FROM bookings").fetchone()["c"]
    paid = conn.execute(
        "SELECT COUNT(*) c FROM bookings WHERE payment_status = 'paid'"
    ).fetchone()["c"]
    pending = conn.execute(
        "SELECT COUNT(*) c FROM bookings WHERE payment_status = 'pending'"
    ).fetchone()["c"]
    revenue = conn.execute(
        "SELECT COALESCE(SUM(deposit_amount), 0) r FROM bookings WHERE payment_status = 'paid'"
    ).fetchone()["r"]
    conn.close()
    return {
        "total_bookings": total,
        "deposits_paid": paid,
        "deposits_pending": pending,
        "deposit_revenue": revenue,
    }


# --------------------------------------------------------------------------
# PAYFAST ITN VALIDATION
# (best-effort — requires outbound internet access from wherever this
#  server actually runs; will not work from a fully offline sandbox)
# --------------------------------------------------------------------------
def payfast_signature_valid(fields):
    if not PAYFAST_PASSPHRASE:
        return True  # can't verify without a passphrase configured; caller should log this
    pairs = []
    for key in fields:
        if key == "signature":
            continue
        value = fields[key]
        pairs.append(f"{key}={urllib.parse.quote_plus(str(value))}")
    pairs.append(f"passphrase={urllib.parse.quote_plus(PAYFAST_PASSPHRASE)}")
    param_string = "&".join(pairs)
    computed = hashlib.md5(param_string.encode()).hexdigest()
    return hmac.compare_digest(computed, fields.get("signature", ""))


def payfast_server_confirms(raw_body):
    """Optional extra check: ask PayFast's servers to confirm the ITN is genuine."""
    try:
        req = urllib.request.Request(
            PAYFAST_VALIDATE_URL,
            data=raw_body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.read().decode().strip() == "VALID"
    except Exception as e:
        print(f"PayFast server validation failed (network issue?): {e}")
        return False


# --------------------------------------------------------------------------
# HTTP HANDLER
# --------------------------------------------------------------------------
class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "KeyzInk/1.0"

    # ---- small helpers ----
    def send_json(self, obj, status=200, extra_headers=None):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def read_raw_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b""

    def get_session_token(self):
        raw_cookie = self.headers.get("Cookie")
        if not raw_cookie:
            return None
        jar = cookies.SimpleCookie()
        jar.load(raw_cookie)
        if SESSION_COOKIE_NAME in jar:
            return jar[SESSION_COOKIE_NAME].value
        return None

    def require_admin(self):
        token = self.get_session_token()
        session = get_session(token)
        if not session:
            self.send_json({"error": "Not authenticated"}, status=401)
            return None
        return session

    def set_session_cookie(self, token, expires):
        cookie = cookies.SimpleCookie()
        cookie[SESSION_COOKIE_NAME] = token
        cookie[SESSION_COOKIE_NAME]["path"] = "/"
        cookie[SESSION_COOKIE_NAME]["httponly"] = True
        cookie[SESSION_COOKIE_NAME]["samesite"] = "Lax"
        cookie[SESSION_COOKIE_NAME]["expires"] = expires.strftime(
            "%a, %d %b %Y %H:%M:%S GMT"
        )
        # OutputString() gives "name=value; attr=..." with no "Set-Cookie:" prefix
        # (str(morsel) would include that prefix, which would double it up here).
        return cookie[SESSION_COOKIE_NAME].OutputString()

    def clear_session_cookie(self):
        cookie = cookies.SimpleCookie()
        cookie[SESSION_COOKIE_NAME] = ""
        cookie[SESSION_COOKIE_NAME]["path"] = "/"
        cookie[SESSION_COOKIE_NAME]["max-age"] = 0
        return cookie[SESSION_COOKIE_NAME].OutputString()

    # ---- static file serving ----
    def serve_static(self, path):
        if path == "/":
            path = "/index.html"
        if path == "/admin" or path == "/admin/":
            path = "/admin.html"

        safe_path = os.path.normpath(path).lstrip("/")
        full_path = os.path.join(PUBLIC_DIR, safe_path)

        if not full_path.startswith(PUBLIC_DIR):
            self.send_error(403)
            return
        if not os.path.isfile(full_path):
            self.send_error(404, "Not found")
            return

        content_types = {
            ".html": "text/html", ".css": "text/css", ".js": "application/javascript",
            ".json": "application/json", ".png": "image/png", ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg", ".svg": "image/svg+xml", ".ico": "image/x-icon",
        }
        ext = os.path.splitext(full_path)[1]
        ctype = content_types.get(ext, "application/octet-stream")

        with open(full_path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---- routing ----
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/api/admin/me":
            session = self.require_admin()
            if session:
                self.send_json({"username": session["username"]})
            return

        if path == "/api/admin/bookings":
            session = self.require_admin()
            if not session:
                return
            status_filter = query.get("status", [None])[0]
            self.send_json({"bookings": list_bookings(status_filter)})
            return

        if path == "/api/admin/stats":
            session = self.require_admin()
            if not session:
                return
            self.send_json(stats())
            return

        self.serve_static(path)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/bookings":
            data = self.read_json_body()
            missing = [f for f in REQUIRED_BOOKING_FIELDS if not data.get(f)]
            if missing:
                self.send_json(
                    {"error": f"Missing fields: {', '.join(missing)}"}, status=400
                )
                return
            booking_id = create_booking(data)
            self.send_json({"id": booking_id, "deposit_amount": DEPOSIT_AMOUNT})
            return

        if path == "/api/admin/login":
            data = self.read_json_body()
            username = data.get("username", "")
            password = data.get("password", "")
            if verify_admin_login(username, password):
                token, expires = create_session(username)
                self.send_json(
                    {"ok": True, "username": username},
                    extra_headers={"Set-Cookie": self.set_session_cookie(token, expires)},
                )
            else:
                self.send_json({"error": "Invalid username or password"}, status=401)
            return

        if path == "/api/admin/logout":
            token = self.get_session_token()
            if token:
                delete_session(token)
            self.send_json(
                {"ok": True}, extra_headers={"Set-Cookie": self.clear_session_cookie()}
            )
            return

        if path == "/api/payfast/notify":
            # PayFast posts application/x-www-form-urlencoded data here.
            raw = self.read_raw_body()
            fields = {
                k: v[0] for k, v in urllib.parse.parse_qs(raw.decode("utf-8")).items()
            }

            if not payfast_signature_valid(fields):
                print("PayFast ITN: signature check failed, ignoring.")
                self.send_response(400)
                self.end_headers()
                return

            booking_id = find_booking_by_m_payment_id(fields.get("m_payment_id"))
            payment_status = fields.get("payment_status", "")
            if booking_id and payment_status == "COMPLETE":
                update_booking(
                    booking_id,
                    {
                        "payment_status": "paid",
                        "payfast_payment_id": fields.get("pf_payment_id", ""),
                    },
                )
                print(f"PayFast ITN: booking #{booking_id} marked paid.")

            # PayFast expects a 200 OK with no body content required
            self.send_response(200)
            self.end_headers()
            return

        self.send_error(404)

    def do_PATCH(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        match = re.match(r"^/api/admin/bookings/(\d+)$", path)
        if match:
            session = self.require_admin()
            if not session:
                return
            booking_id = int(match.group(1))
            data = self.read_json_body()
            ok = update_booking(booking_id, data)
            self.send_json({"ok": ok})
            return
        self.send_error(404)

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        match = re.match(r"^/api/admin/bookings/(\d+)$", path)
        if match:
            session = self.require_admin()
            if not session:
                return
            delete_booking(int(match.group(1)))
            self.send_json({"ok": True})
            return
        self.send_error(404)

    # quieter logging
    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def main():
    init_db()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"KEYZ INK server running: http://0.0.0.0:{PORT}")
    print(f"  Public site: http://localhost:{PORT}/")
    print(f"  Admin login: http://localhost:{PORT}/admin")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
