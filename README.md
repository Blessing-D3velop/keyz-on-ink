# KEYZ INK — Fullstack Site

Website + admin dashboard + booking/payment tracking, all served by one
Python file (`server.py`). No pip installs, no Node, no external
database server — it uses Python's built-in SQLite.

## What's in here

```
server.py          ← backend (routes, auth, database, PayFast webhook)
public/
  index.html        ← the public website
  style.css
  script.js          ← booking form now saves to the backend
  admin.html         ← admin dashboard (login-gated)
  admin.css
  admin.js
  images/            ← put your logo.jpeg, about.jpeg, g1.jpeg...g16.jpeg here
```

## Run it locally (to try it out)

You need Python 3.8+ installed. Then:

```bash
cd keyz-ink-fullstack
export ADMIN_USERNAME="Keyzonink"
export ADMIN_PASSWORD="#keyz123"
python3 server.py
```

- Website: http://localhost:8000/
- Admin dashboard: http://localhost:8000/admin

**If you skip the env vars**, it creates a default `admin` /
`change-me-now` login and prints a loud warning every time it starts.
Change it before anyone else can reach the server.

A `data/keyzink.db` SQLite file is created automatically on first run —
that's your entire database (bookings, admin login, sessions). Back it
up like any file; there's nothing else to configure.

## What the admin dashboard does

- View every booking that comes through the site (name, contact,
  service, date/time, description)
- See deposit status: **pending / paid**, with a "Mark Paid" button for
  manual confirmation
- Move a booking through **new → confirmed → completed / cancelled**
- Stats: total bookings, deposits paid, deposits pending, total deposit
  revenue collected
- Delete a booking

## Going live — what you actually need to do

This is the part that can't be done from a sandbox — it needs a real
place to run:

1. **Get hosting.** Cheapest reliable options for something this small:
   - [Render.com](https://render.com) or [Railway.app](https://railway.app) — both auto-detect a
     Python app, give you free HTTPS, and deploy straight from a GitHub
     repo. This is the easiest path.
   - Any small VPS (Hetzner, DigitalOcean) if you want more control —
     you'd run `server.py` behind Nginx or Caddy for HTTPS.

2. **Set real environment variables on the host:**
   - `ADMIN_USERNAME`, `ADMIN_PASSWORD` — your real admin login
   - `PORT` — usually set automatically by the host
   - `PAYFAST_PASSPHRASE` — optional but recommended (see below)

3. **Get real PayFast credentials.** Sign up at
   [payfast.co.za](https://www.payfast.co.za), then in
   Settings → Integration grab your **Merchant ID** and **Merchant Key**.
   Put them in `public/script.js` at the top (`PAYFAST_CONFIG`), and
   change `mode: "sandbox"` to `mode: "live"`.

4. **Set your PayFast notify URL.** In PayFast's integration settings,
   point the ITN notify URL at:
   `https://your-real-domain.com/api/payfast/notify`
   This is what lets a payment automatically flip a booking to "Paid"
   in your admin dashboard — without it, you'd mark deposits paid
   manually by checking your PayFast dashboard.

5. **(Recommended) Set a PayFast passphrase.** In PayFast's integration
   settings, set a passphrase, and put the same value in the
   `PAYFAST_PASSPHRASE` environment variable on your server. This lets
   `server.py` verify that a payment notification genuinely came from
   PayFast and wasn't spoofed by someone hitting your webhook directly.

6. **Add your real images.** Drop `logo.jpeg`, `about.jpeg`, and
   `g1.jpeg`–`g16.jpeg` into `public/images/`.

## Security notes

- Admin passwords are never stored in plain text — they're hashed with
  PBKDF2-SHA256 (200,000 iterations) and a random salt per user.
- Admin sessions are random 32-byte tokens stored server-side, expiring
  after 12 hours, sent as an `HttpOnly` cookie (so page JavaScript can't
  read it, which blocks a common attack).
- The booking form's PayFast redirect can't be trusted on its own —
  anyone could POST a form claiming "payment_status=COMPLETE" without
  actually paying. That's exactly what `PAYFAST_PASSPHRASE`
  verification in `server.py` guards against. Set it once you're live.
- Change the default admin password before deploying. Seriously — the
  server nags you about this in its logs for a reason.
