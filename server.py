#!/usr/bin/env python3
"""
KEYZ INK — Fullstack Backend Server
===================================

Pure Python standard library backend.

Features:
- Public website
- JSON booking API
- SQLite database
- Admin login
- Admin dashboard API
- Booking management
- PayFast ITN webhook receiver
- PayFast payment verification
- Secure static-file serving

RUN LOCALLY:

    python server.py

Then visit:

    http://localhost:8000/
    http://localhost:8000/admin
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


# ==========================================================================
# CONFIG
# ==========================================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

PUBLIC_DIR = os.path.abspath(
    os.path.join(
        BASE_DIR,
        "public"
    )
)

DB_PATH = os.path.join(
    BASE_DIR,
    "data",
    "keyzink.db"
)

PORT = int(
    os.environ.get(
        "PORT",
        8000
    )
)

SESSION_COOKIE_NAME = (
    "keyzink_admin_session"
)

SESSION_LIFETIME_HOURS = 12


# ==========================================================================
# ADMIN CONFIG
# ==========================================================================

DEFAULT_ADMIN_USERNAME = os.environ.get(
    "ADMIN_USERNAME",
    "admin"
)

DEFAULT_ADMIN_PASSWORD = os.environ.get(
    "ADMIN_PASSWORD",
    "change-me-now"
)


# ==========================================================================
# BOOKING CONFIG
# ==========================================================================

DEPOSIT_AMOUNT = 200.00


# ==========================================================================
# PAYFAST CONFIG
# ==========================================================================

# IMPORTANT:
# These should be environment variables when going live.
#
# Windows PowerShell example:
#
# $env:PAYFAST_MERCHANT_ID="14413558"
# $env:PAYFAST_MERCHANT_KEY="YOUR_NEW_MERCHANT_KEY"
# $env:PAYFAST_PASSPHRASE="YOUR_PASSPHRASE"
#
# DO NOT put these values into GitHub.

PAYFAST_MERCHANT_ID = os.environ.get(
    "PAYFAST_MERCHANT_ID",
    "14413558"
).strip()

PAYFAST_MERCHANT_KEY = os.environ.get(
    "PAYFAST_MERCHANT_KEY",
    " yx20no5w4a29h"
).strip()

PAYFAST_PASSPHRASE = os.environ.get(
    "PAYFAST_PASSPHRASE",
    ""
)


# ==========================================================================
# PAYFAST MODE
# ==========================================================================

PAYFAST_MODE = os.environ.get(
    "PAYFAST_MODE",
    "live"
).strip().lower()


if PAYFAST_MODE == "live":

    PAYFAST_PROCESS_URL = (
        "https://www.payfast.co.za/eng/process"
    )

    PAYFAST_VALIDATE_URL = (
        "https://www.payfast.co.za/eng/query/validate"
    )

else:

    PAYFAST_PROCESS_URL = (
        "https://sandbox.payfast.co.za/eng/process"
    )

    PAYFAST_VALIDATE_URL = (
        "https://sandbox.payfast.co.za/eng/query/validate"
    )


# ==========================================================================
# PUBLIC WEBSITE URL
# ==========================================================================

# When hosted, set this to the actual public HTTPS website.
#
# Example:
#
# PUBLIC_BASE_URL=https://keyzink.co.za
#
# Locally, it automatically uses localhost.

PUBLIC_BASE_URL = os.environ.get(
    "PUBLIC_BASE_URL",
    ""
).strip().rstrip("/")


# ==========================================================================
# DATABASE
# ==========================================================================

def get_db():

    os.makedirs(
        os.path.dirname(DB_PATH),
        exist_ok=True
    )

    conn = sqlite3.connect(
        DB_PATH
    )

    conn.row_factory = sqlite3.Row

    conn.execute(
        "PRAGMA foreign_keys = ON"
    )

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


    # --------------------------------------------------------------
    # Create default admin only if there are no admins.
    # --------------------------------------------------------------

    row = conn.execute(
        """
        SELECT COUNT(*) AS c
        FROM admin_users
        """
    ).fetchone()


    if row["c"] == 0:

        create_admin_user(
            conn,
            DEFAULT_ADMIN_USERNAME,
            DEFAULT_ADMIN_PASSWORD
        )


        if DEFAULT_ADMIN_PASSWORD == "change-me-now":

            print("=" * 70)

            print(
                "WARNING: using the default admin login."
            )

            print(
                "Username: admin"
            )

            print(
                "Password: change-me-now"
            )

            print(
                "Set ADMIN_USERNAME and ADMIN_PASSWORD "
                "before going live."
            )

            print("=" * 70)


    conn.close()


# ==========================================================================
# PASSWORDS
# ==========================================================================

def hash_password(
    password,
    salt=None
):

    if salt is None:

        salt = secrets.token_hex(
            16
        )


    pw_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        200_000
    ).hex()


    return pw_hash, salt


def create_admin_user(
    conn,
    username,
    password
):

    pw_hash, salt = hash_password(
        password
    )


    conn.execute(
        """
        INSERT OR REPLACE INTO admin_users
        (
            username,
            password_hash,
            salt,
            created_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            username,
            pw_hash,
            salt,
            datetime.now(
                timezone.utc
            ).isoformat()
        )
    )


    conn.commit()


def verify_admin_login(
    username,
    password
):

    conn = get_db()


    row = conn.execute(
        """
        SELECT *
        FROM admin_users
        WHERE username = ?
        """,
        (username,)
    ).fetchone()


    conn.close()


    if not row:
        return False


    check_hash, _ = hash_password(
        password,
        row["salt"]
    )


    return hmac.compare_digest(
        check_hash,
        row["password_hash"]
    )


# ==========================================================================
# SESSIONS
# ==========================================================================

def create_session(username):

    conn = get_db()


    token = secrets.token_urlsafe(
        32
    )


    now = datetime.now(
        timezone.utc
    )


    expires = (
        now
        + timedelta(
            hours=SESSION_LIFETIME_HOURS
        )
    )


    conn.execute(
        """
        INSERT INTO sessions
        (
            token,
            username,
            created_at,
            expires_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            token,
            username,
            now.isoformat(),
            expires.isoformat()
        )
    )


    conn.commit()

    conn.close()


    return token, expires


def get_session(token):

    if not token:
        return None


    conn = get_db()


    row = conn.execute(
        """
        SELECT *
        FROM sessions
        WHERE token = ?
        """,
        (token,)
    ).fetchone()


    conn.close()


    if not row:
        return None


    try:

        expires_at = datetime.fromisoformat(
            row["expires_at"]
        )

    except ValueError:

        return None


    if expires_at < datetime.now(
        timezone.utc
    ):

        delete_session(
            token
        )

        return None


    return row


def delete_session(token):

    if not token:
        return


    conn = get_db()


    conn.execute(
        """
        DELETE FROM sessions
        WHERE token = ?
        """,
        (token,)
    )


    conn.commit()

    conn.close()


# ==========================================================================
# BOOKING HELPERS
# ==========================================================================

REQUIRED_BOOKING_FIELDS = [
    "fullName",
    "phone",
    "email",
    "service",
    "date",
    "time",
    "description"
]


def create_booking(data):

    conn = get_db()


    cur = conn.execute(
        """
        INSERT INTO bookings
        (
            created_at,
            full_name,
            phone,
            email,
            service,
            appt_date,
            appt_time,
            description,
            deposit_amount,
            payment_status,
            booking_status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 'new')
        """,
        (
            datetime.now(
                timezone.utc
            ).isoformat(),

            data["fullName"].strip(),

            data["phone"].strip(),

            data["email"].strip(),

            data["service"].strip(),

            data["date"].strip(),

            data["time"].strip(),

            data.get(
                "description",
                ""
            ).strip(),

            DEPOSIT_AMOUNT
        )
    )


    conn.commit()


    booking_id = cur.lastrowid


    conn.close()


    return booking_id


def list_bookings(
    status_filter=None
):

    conn = get_db()


    if status_filter:

        rows = conn.execute(
            """
            SELECT *
            FROM bookings
            WHERE payment_status = ?
               OR booking_status = ?
            ORDER BY id DESC
            """,
            (
                status_filter,
                status_filter
            )
        ).fetchall()

    else:

        rows = conn.execute(
            """
            SELECT *
            FROM bookings
            ORDER BY id DESC
            """
        ).fetchall()


    conn.close()


    return [
        dict(row)
        for row in rows
    ]


def update_booking(
    booking_id,
    fields
):

    allowed = {
        "payment_status",
        "booking_status",
        "notes",
        "payfast_payment_id"
    }


    sets = []

    values = []


    for key, value in fields.items():

        if key in allowed:

            sets.append(
                f"{key} = ?"
            )

            values.append(
                value
            )


    if not sets:
        return False


    values.append(
        booking_id
    )


    conn = get_db()


    conn.execute(
        f"""
        UPDATE bookings
        SET {', '.join(sets)}
        WHERE id = ?
        """,
        values
    )


    changed = (
        conn.total_changes > 0
    )


    conn.commit()

    conn.close()


    return changed


def delete_booking(
    booking_id
):

    conn = get_db()


    conn.execute(
        """
        DELETE FROM bookings
        WHERE id = ?
        """,
        (booking_id,)
    )


    conn.commit()

    conn.close()


def find_booking_by_m_payment_id(
    m_payment_id
):

    match = re.match(
        r"^KEYZINK-(\d+)-",
        m_payment_id or ""
    )


    if not match:
        return None


    return int(
        match.group(1)
    )


def stats():

    conn = get_db()


    total = conn.execute(
        """
        SELECT COUNT(*) c
        FROM bookings
        """
    ).fetchone()["c"]


    paid = conn.execute(
        """
        SELECT COUNT(*) c
        FROM bookings
        WHERE payment_status = 'paid'
        """
    ).fetchone()["c"]


    pending = conn.execute(
        """
        SELECT COUNT(*) c
        FROM bookings
        WHERE payment_status = 'pending'
        """
    ).fetchone()["c"]


    revenue = conn.execute(
        """
        SELECT COALESCE(
            SUM(deposit_amount),
            0
        ) r
        FROM bookings
        WHERE payment_status = 'paid'
        """
    ).fetchone()["r"]


    conn.close()


    return {
        "total_bookings": total,
        "deposits_paid": paid,
        "deposits_pending": pending,
        "deposit_revenue": revenue
    }


# ==========================================================================
# PAYFAST HELPERS
# ==========================================================================

def payfast_signature_valid(
    fields
):

    signature = fields.get(
        "signature",
        ""
    )


    if not signature:

        print(
            "PayFast ITN: no signature received."
        )

        return False


    # --------------------------------------------------------------
    # Build the parameter string in the same order PayFast sent it.
    # --------------------------------------------------------------

    pairs = []


    for key, value in fields.items():

        if key == "signature":
            continue


        pairs.append(
            f"{key}="
            + urllib.parse.quote_plus(
                str(value)
            )
        )


    # --------------------------------------------------------------
    # Passphrase
    # --------------------------------------------------------------

    if PAYFAST_PASSPHRASE:

        pairs.append(
            "passphrase="
            + urllib.parse.quote_plus(
                PAYFAST_PASSPHRASE
            )
        )


    param_string = "&".join(
        pairs
    )


    computed = hashlib.md5(
        param_string.encode(
            "utf-8"
        )
    ).hexdigest()


    valid = hmac.compare_digest(
        computed.lower(),
        signature.lower()
    )


    if not valid:

        print(
            "PayFast ITN: signature verification failed."
        )


    return valid


def payfast_server_confirms(
    raw_body
):

    try:

        request = urllib.request.Request(

            PAYFAST_VALIDATE_URL,

            data=raw_body,

            headers={
                "Content-Type":
                    "application/x-www-form-urlencoded"
            },

            method="POST"
        )


        with urllib.request.urlopen(
            request,
            timeout=15
        ) as response:

            result = (
                response
                .read()
                .decode(
                    "utf-8",
                    errors="replace"
                )
                .strip()
            )


            print(
                "PayFast validation response:",
                result
            )


            return result == "VALID"


    except Exception as error:

        print(
            "PayFast server validation failed:",
            error
        )

        return False


def payfast_amount_valid(
    fields,
    booking_id
):

    try:

        received_amount = float(
            fields.get(
                "amount",
                "0"
            )
        )

    except (
        ValueError,
        TypeError
    ):

        return False


    conn = get_db()


    row = conn.execute(
        """
        SELECT deposit_amount
        FROM bookings
        WHERE id = ?
        """,
        (booking_id,)
    ).fetchone()


    conn.close()


    if not row:
        return False


    expected_amount = float(
        row["deposit_amount"]
    )


    return abs(
        received_amount
        - expected_amount
    ) < 0.01


# ==========================================================================
# HTTP HANDLER
# ==========================================================================

class Handler(
    http.server.BaseHTTPRequestHandler
):

    server_version = "KeyzInk/1.0"


    # ======================================================================
    # JSON RESPONSE
    # ======================================================================

    def send_json(
        self,
        obj,
        status=200,
        extra_headers=None
    ):

        body = json.dumps(
            obj
        ).encode(
            "utf-8"
        )


        self.send_response(
            status
        )


        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )


        self.send_header(
            "Content-Length",
            str(len(body))
        )


        self.send_header(
            "Cache-Control",
            "no-store"
        )


        for key, value in (
            extra_headers or {}
        ).items():

            self.send_header(
                key,
                value
            )


        self.end_headers()


        self.wfile.write(
            body
        )


    # ======================================================================
    # REQUEST BODY
    # ======================================================================

    def read_json_body(self):

        try:

            length = int(
                self.headers.get(
                    "Content-Length",
                    0
                )
            )

        except ValueError:

            return {}


        if length <= 0:
            return {}


        raw = self.rfile.read(
            length
        )


        try:

            return json.loads(
                raw.decode(
                    "utf-8"
                )
            )

        except (
            json.JSONDecodeError,
            UnicodeDecodeError
        ):

            return {}


    def read_raw_body(self):

        try:

            length = int(
                self.headers.get(
                    "Content-Length",
                    0
                )
            )

        except ValueError:

            return b""


        if length <= 0:
            return b""


        return self.rfile.read(
            length
        )


    # ======================================================================
    # COOKIES
    # ======================================================================

    def get_session_token(self):

        raw_cookie = self.headers.get(
            "Cookie"
        )


        if not raw_cookie:
            return None


        jar = cookies.SimpleCookie()


        try:

            jar.load(
                raw_cookie
            )

        except cookies.CookieError:

            return None


        if SESSION_COOKIE_NAME in jar:

            return jar[
                SESSION_COOKIE_NAME
            ].value


        return None


    def require_admin(self):

        token = self.get_session_token()


        session = get_session(
            token
        )


        if not session:

            self.send_json(
                {
                    "error":
                        "Not authenticated"
                },
                status=401
            )

            return None


        return session


    def set_session_cookie(
        self,
        token,
        expires
    ):

        cookie = cookies.SimpleCookie()


        cookie[
            SESSION_COOKIE_NAME
        ] = token


        cookie[
            SESSION_COOKIE_NAME
        ]["path"] = "/"


        cookie[
            SESSION_COOKIE_NAME
        ]["httponly"] = True


        cookie[
            SESSION_COOKIE_NAME
        ]["samesite"] = "Lax"


        cookie[
            SESSION_COOKIE_NAME
        ]["expires"] = expires.strftime(
            "%a, %d %b %Y %H:%M:%S GMT"
        )


        # Secure should be used on HTTPS hosting.
        if PAYFAST_MODE == "live":

            cookie[
                SESSION_COOKIE_NAME
            ]["secure"] = True


        return cookie[
            SESSION_COOKIE_NAME
        ].OutputString()


    def clear_session_cookie(self):

        cookie = cookies.SimpleCookie()


        cookie[
            SESSION_COOKIE_NAME
        ] = ""


        cookie[
            SESSION_COOKIE_NAME
        ]["path"] = "/"


        cookie[
            SESSION_COOKIE_NAME
        ]["max-age"] = 0


        return cookie[
            SESSION_COOKIE_NAME
        ].OutputString()


    # ======================================================================
    # STATIC FILE SERVING
    # ======================================================================

    def serve_static(
        self,
        path
    ):

        # --------------------------------------------------------------
        # Route shortcuts
        # --------------------------------------------------------------

        if path == "/":

            path = "/index.html"


        elif path in (
            "/admin",
            "/admin/"
        ):

            path = "/admin.html"


        # --------------------------------------------------------------
        # Windows-safe path handling
        # --------------------------------------------------------------

        relative_path = path.lstrip(
            "/\\"
        )


        relative_path = os.path.normpath(
            relative_path
        )


        if (
            relative_path == ".."
            or relative_path.startswith(
                ".." + os.sep
            )
        ):

            self.send_error(
                403,
                "Forbidden"
            )

            return


        # --------------------------------------------------------------
        # Absolute path
        # --------------------------------------------------------------

        full_path = os.path.abspath(
            os.path.join(
                PUBLIC_DIR,
                relative_path
            )
        )


        # --------------------------------------------------------------
        # Security check
        # --------------------------------------------------------------

        try:

            common_path = os.path.commonpath(
                [
                    PUBLIC_DIR,
                    full_path
                ]
            )

        except ValueError:

            self.send_error(
                403,
                "Forbidden"
            )

            return


        if common_path != PUBLIC_DIR:

            self.send_error(
                403,
                "Forbidden"
            )

            return


        # --------------------------------------------------------------
        # File existence
        # --------------------------------------------------------------

        if not os.path.isfile(
            full_path
        ):

            self.send_error(
                404,
                "Not found"
            )

            return


        # --------------------------------------------------------------
        # MIME types
        # --------------------------------------------------------------

        content_types = {

            ".html":
                "text/html; charset=utf-8",

            ".css":
                "text/css; charset=utf-8",

            ".js":
                "application/javascript; charset=utf-8",

            ".json":
                "application/json; charset=utf-8",

            ".png":
                "image/png",

            ".jpg":
                "image/jpeg",

            ".jpeg":
                "image/jpeg",

            ".webp":
                "image/webp",

            ".gif":
                "image/gif",

            ".svg":
                "image/svg+xml",

            ".ico":
                "image/x-icon",

            ".woff":
                "font/woff",

            ".woff2":
                "font/woff2",

            ".ttf":
                "font/ttf"
        }


        extension = os.path.splitext(
            full_path
        )[1].lower()


        content_type = content_types.get(
            extension,
            "application/octet-stream"
        )


        # --------------------------------------------------------------
        # Read file
        # --------------------------------------------------------------

        try:

            with open(
                full_path,
                "rb"
            ) as file:

                body = file.read()

        except OSError:

            self.send_error(
                404,
                "Unable to read file"
            )

            return


        self.send_response(
            200
        )


        self.send_header(
            "Content-Type",
            content_type
        )


        self.send_header(
            "Content-Length",
            str(len(body))
        )


        self.send_header(
            "Cache-Control",
            "no-cache"
        )


        self.end_headers()


        self.wfile.write(
            body
        )


    # ======================================================================
    # GET
    # ======================================================================

    def do_GET(self):

        parsed = urllib.parse.urlparse(
            self.path
        )


        path = parsed.path


        query = urllib.parse.parse_qs(
            parsed.query
        )


        # --------------------------------------------------------------
        # Admin session
        # --------------------------------------------------------------

        if path == "/api/admin/me":

            session = self.require_admin()


            if session:

                self.send_json(
                    {
                        "username":
                            session["username"]
                    }
                )


            return


        # --------------------------------------------------------------
        # Admin bookings
        # --------------------------------------------------------------

        if path == "/api/admin/bookings":

            session = self.require_admin()


            if not session:
                return


            status_filter = query.get(
                "status",
                [None]
            )[0]


            self.send_json(
                {
                    "bookings":
                        list_bookings(
                            status_filter
                        )
                }
            )


            return


        # --------------------------------------------------------------
        # Admin statistics
        # --------------------------------------------------------------

        if path == "/api/admin/stats":

            session = self.require_admin()


            if not session:
                return


            self.send_json(
                stats()
            )


            return


        # --------------------------------------------------------------
        # Public/static files
        # --------------------------------------------------------------

        self.serve_static(
            path
        )


    # ======================================================================
    # POST
    # ======================================================================

    def do_POST(self):

        parsed = urllib.parse.urlparse(
            self.path
        )


        path = parsed.path


        # --------------------------------------------------------------
        # CREATE BOOKING
        # --------------------------------------------------------------

        if path == "/api/bookings":

            data = self.read_json_body()


            missing = [
                field
                for field in REQUIRED_BOOKING_FIELDS
                if not data.get(field)
            ]


            if missing:

                self.send_json(
                    {
                        "error":
                            "Missing fields: "
                            + ", ".join(
                                missing
                            )
                    },
                    status=400
                )

                return


            try:

                booking_id = create_booking(
                    data
                )

            except Exception as error:

                print(
                    "Booking creation error:",
                    error
                )


                self.send_json(
                    {
                        "error":
                            "Unable to create booking"
                    },
                    status=500
                )

                return


            self.send_json(
                {
                    "id":
                        booking_id,

                    "deposit_amount":
                        DEPOSIT_AMOUNT
                }
            )


            return


        # --------------------------------------------------------------
        # ADMIN LOGIN
        # --------------------------------------------------------------

        if path == "/api/admin/login":

            data = self.read_json_body()


            username = str(
                data.get(
                    "username",
                    ""
                )
            ).strip()


            password = str(
                data.get(
                    "password",
                    ""
                )
            )


            if verify_admin_login(
                username,
                password
            ):

                token, expires = create_session(
                    username
                )


                self.send_json(
                    {
                        "ok": True,

                        "username":
                            username
                    },

                    extra_headers={
                        "Set-Cookie":
                            self.set_session_cookie(
                                token,
                                expires
                            )
                    }
                )


            else:

                self.send_json(
                    {
                        "error":
                            "Invalid username or password"
                    },
                    status=401
                )


            return


        # --------------------------------------------------------------
        # ADMIN LOGOUT
        # --------------------------------------------------------------

        if path == "/api/admin/logout":

            token = self.get_session_token()


            if token:

                delete_session(
                    token
                )


            self.send_json(
                {
                    "ok":
                        True
                },

                extra_headers={
                    "Set-Cookie":
                        self.clear_session_cookie()
                }
            )


            return


        # --------------------------------------------------------------
        # PAYFAST ITN
        # --------------------------------------------------------------

        if path == "/api/payfast/notify":

            raw = self.read_raw_body()


            if not raw:

                self.send_error(
                    400,
                    "Empty PayFast payload"
                )

                return


            # ----------------------------------------------------------
            # Parse PayFast payload
            # ----------------------------------------------------------

            try:

                parsed_pairs = (
                    urllib.parse.parse_qsl(
                        raw.decode(
                            "utf-8"
                        ),
                        keep_blank_values=True
                    )
                )

            except (
                UnicodeDecodeError,
                ValueError
            ):

                self.send_error(
                    400,
                    "Invalid PayFast payload"
                )

                return


            fields = dict(
                parsed_pairs
            )


            print()
            print(
                "========== PAYFAST ITN =========="
            )


            print(
                "Payment ID:",
                fields.get(
                    "pf_payment_id",
                    ""
                )
            )


            print(
                "Merchant ID:",
                fields.get(
                    "merchant_id",
                    ""
                )
            )


            print(
                "Payment status:",
                fields.get(
                    "payment_status",
                    ""
                )
            )


            print(
                "Amount:",
                fields.get(
                    "amount",
                    ""
                )
            )


            print(
                "Booking reference:",
                fields.get(
                    "m_payment_id",
                    ""
                )
            )


            # ----------------------------------------------------------
            # Signature verification
            # ----------------------------------------------------------

            if not payfast_signature_valid(
                fields
            ):

                print(
                    "PayFast ITN rejected: "
                    "invalid signature."
                )


                self.send_response(
                    400
                )

                self.end_headers()

                return


            # ----------------------------------------------------------
            # Merchant ID verification
            # ----------------------------------------------------------

            received_merchant_id = fields.get(
                "merchant_id",
                ""
            )


            if (
                PAYFAST_MERCHANT_ID
                and
                received_merchant_id
                != PAYFAST_MERCHANT_ID
            ):

                print(
                    "PayFast ITN rejected: "
                    "merchant ID mismatch."
                )


                self.send_response(
                    400
                )

                self.end_headers()

                return


            # ----------------------------------------------------------
            # Booking reference
            # ----------------------------------------------------------

            m_payment_id = fields.get(
                "m_payment_id",
                ""
            )


            booking_id = (
                find_booking_by_m_payment_id(
                    m_payment_id
                )
            )


            if not booking_id:

                print(
                    "PayFast ITN: could not find "
                    "KEYZ INK booking ID."
                )


                self.send_response(
                    400
                )

                self.end_headers()

                return


            # ----------------------------------------------------------
            # Amount verification
            # ----------------------------------------------------------

            if not payfast_amount_valid(
                fields,
                booking_id
            ):

                print(
                    "PayFast ITN rejected: "
                    "amount mismatch."
                )


                self.send_response(
                    400
                )

                self.end_headers()

                return


            # ----------------------------------------------------------
            # PayFast server validation
            # ----------------------------------------------------------

            if not payfast_server_confirms(
                raw
            ):

                print(
                    "PayFast ITN rejected: "
                    "PayFast server validation failed."
                )


                self.send_response(
                    400
                )

                self.end_headers()

                return


            # ----------------------------------------------------------
            # Payment status
            # ----------------------------------------------------------

            payment_status = fields.get(
                "payment_status",
                ""
            ).upper()


            if payment_status == "COMPLETE":

                updated = update_booking(
                    booking_id,
                    {
                        "payment_status":
                            "paid",

                        "payfast_payment_id":
                            fields.get(
                                "pf_payment_id",
                                ""
                            )
                    }
                )


                if updated:

                    print(
                        f"PayFast ITN: booking "
                        f"#{booking_id} marked PAID."
                    )

                else:

                    print(
                        f"PayFast ITN: booking "
                        f"#{booking_id} was not updated."
                    )


            else:

                print(
                    "PayFast ITN: payment was not COMPLETE."
                )


            print(
                "================================="
            )
            print()


            # ----------------------------------------------------------
            # Respond to PayFast
            # ----------------------------------------------------------

            self.send_response(
                200
            )

            self.end_headers()

            return


        # --------------------------------------------------------------
        # Unknown POST
        # --------------------------------------------------------------

        self.send_error(
            404
        )


    # ======================================================================
    # PATCH
    # ======================================================================

    def do_PATCH(self):

        parsed = urllib.parse.urlparse(
            self.path
        )


        path = parsed.path


        match = re.match(
            r"^/api/admin/bookings/(\d+)$",
            path
        )


        if match:

            session = self.require_admin()


            if not session:
                return


            booking_id = int(
                match.group(1)
            )


            data = self.read_json_body()


            ok = update_booking(
                booking_id,
                data
            )


            self.send_json(
                {
                    "ok":
                        ok
                }
            )


            return


        self.send_error(
            404
        )


    # ======================================================================
    # DELETE
    # ======================================================================

    def do_DELETE(self):

        parsed = urllib.parse.urlparse(
            self.path
        )


        path = parsed.path


        match = re.match(
            r"^/api/admin/bookings/(\d+)$",
            path
        )


        if match:

            session = self.require_admin()


            if not session:
                return


            booking_id = int(
                match.group(1)
            )


            delete_booking(
                booking_id
            )


            self.send_json(
                {
                    "ok":
                        True
                }
            )


            return


        self.send_error(
            404
        )


    # ======================================================================
    # LOGGING
    # ======================================================================

    def log_message(
        self,
        fmt,
        *args
    ):

        print(
            f"[{self.log_date_time_string()}] "
            f"{fmt % args}"
        )


# ==========================================================================
# THREADED SERVER
# ==========================================================================

class ThreadingHTTPServer(
    socketserver.ThreadingMixIn,
    http.server.HTTPServer
):

    daemon_threads = True


# ==========================================================================
# MAIN
# ==========================================================================

def main():

    # ----------------------------------------------------------------------
    # Public folder
    # ----------------------------------------------------------------------

    if not os.path.isdir(
        PUBLIC_DIR
    ):

        print()
        print(
            "ERROR: public folder was not found:"
        )
        print(
            PUBLIC_DIR
        )
        print()

        return


    # ----------------------------------------------------------------------
    # Database
    # ----------------------------------------------------------------------

    init_db()


    # ----------------------------------------------------------------------
    # Startup information
    # ----------------------------------------------------------------------

    print("=" * 70)

    print(
        "KEYZ INK SERVER"
    )

    print(
        f"Mode: {PAYFAST_MODE.upper()}"
    )

    print(
        f"Port: {PORT}"
    )

    print(
        f"Public site: "
        f"http://localhost:{PORT}/"
    )

    print(
        f"Admin: "
        f"http://localhost:{PORT}/admin"
    )

    print(
        f"PayFast process URL: "
        f"{PAYFAST_PROCESS_URL}"
    )

    print(
        f"PayFast validation URL: "
        f"{PAYFAST_VALIDATE_URL}"
    )

    print(
        "Merchant ID configured:",
        "YES"
        if PAYFAST_MERCHANT_ID
        else "NO"
    )

    print(
        "Merchant Key configured:",
        "YES"
        if PAYFAST_MERCHANT_KEY
        else "NO"
    )

    print(
        "Passphrase configured:",
        "YES"
        if PAYFAST_PASSPHRASE
        else "NO"
    )

    print("=" * 70)


    # ----------------------------------------------------------------------
    # Start server
    # ----------------------------------------------------------------------

    server = ThreadingHTTPServer(
        (
            "0.0.0.0",
            PORT
        ),
        Handler
    )


    try:

        server.serve_forever()

    except KeyboardInterrupt:

        print(
            "\nShutting down."
        )

        server.shutdown()

        server.server_close()


# ==========================================================================
# START
# ==========================================================================

if __name__ == "__main__":

    main()