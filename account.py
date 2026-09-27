#!/usr/bin/env python3
"""
ORACLE BUSINESS — ACCOUNT LAYER (step 1 of the locked business build).

Owner ruling 2026-09-26 (locked in ~/Downloads/ORACLE_BUSINESS_DESIGN.md): a
monetized website where a trader mid-decision requests an EVENT on an asset
and gets the ONE thing they cannot get anywhere else — the timing ("when"),
never direction, never price, never magnitude. This file is STEP 1 of the
build order: the account layer that makes it a business.

Step 1 scope = ACCOUNT STATE + GATES only:
  - verified-email signup (anti fake-email farming of the free events)
  - 3 FREE events as proof (per account, one per day)
  - daily one-event cap per client (the throughput engine, not a scarcity lie)
  - payment/escrow state (pay-from-profits primary, flat $1,000 alt)
  - gate: issue_event is refused when unverified / over daily cap / delinquent

Events THEMSELVES (timing + MINOR/MID/MAJOR tier) are STEP 2 (event-request
service); on-chain payment verification is STEP 3; public deploy is STEP 4.
This layer stores and gates; it never emits a real market event, and it never
touches engine internals — the events table carries ONLY asset + horizon +
tier label, exactly the black-box doctrine.

Design → schema mapping (locked):
  - "register FREE (verified email)"        → create_account + verify_token
  - "3 FREE events as proof"                → free_events (default 3)
  - "one event per client per day"          → events_today + last_event_date DAILY_CAP=1
  - "event correct + unpaid → cut off"      → escrow_due>0 ⇒ DELINQUENT (gate refuses)
  - "event incorrect → no fee"              → escrow increments only on CORRECT non-free events
  - "no further events until prior paid"    → escrow_due>0 blocks request_event

Status lifecycle: FREE (has free allowance) → ACTIVE (allowance spent, no debt)
→ DELINQUENT (correct event(s) unpaid, cut off) → ACTIVE (paid).

Stdlib only (sqlite3 + http.server + urllib), matching the other ORACLE_NEW
services. No engine constants, no secret math, no formula fields anywhere.
"""
import json
import os
import secrets
import sqlite3
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("ORACLE_ACCOUNT_DB", os.path.join(BASE, "accounts.db"))
HOST, PORT = "127.0.0.1", 8723
ET = timezone(timedelta(hours=-4))

FREE_EVENTS = 3          # locked: 3 free events as proof
DAILY_CAP = 1            # locked: one event per client per day
FLAT_PRICE = 1000        # DESIGN says "example figure — CONFIRM BEFORE COPY"
FROM = "ORACLE SYSTEM <oracle@amartie.com>"
RESEND_KEY_FILE = os.path.expanduser("~/.halo_secrets/resend_full_key.txt")


# --------------------------------------------------------------------------
# storage helpers
# --------------------------------------------------------------------------
def now_et():
    return datetime.now(ET)


def _conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init():
    with _conn() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS accounts(
            email        TEXT PRIMARY KEY,
            created_at   TEXT NOT NULL,
            verified     INTEGER NOT NULL DEFAULT 0,
            verify_token TEXT,
            free_events  INTEGER NOT NULL DEFAULT 3,
            events_today INTEGER NOT NULL DEFAULT 0,
            last_event_date TEXT,
            escrow_due   INTEGER NOT NULL DEFAULT 0,
            status       TEXT NOT NULL DEFAULT 'FREE',
            tier         TEXT NOT NULL DEFAULT 'pay_from_profit'
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS events(
            id        TEXT PRIMARY KEY,
            email     TEXT NOT NULL,
            asset     TEXT,
            horizon   TEXT,
            tier      TEXT,
            issued_at TEXT,
            turn_time TEXT,
            window_min INTEGER,
            tier_label TEXT,
            graded    INTEGER DEFAULT 0,
            correct   INTEGER
        )""")
        # migration (step 2): add event-enrichment columns on an existing db
        cols = {r["name"] for r in db.execute("PRAGMA table_info(events)")}
        for name, ddl in (("turn_time", "TEXT"), ("window_min", "INTEGER"),
                          ("tier_label", "TEXT")):
            if name not in cols:
                db.execute(f"ALTER TABLE events ADD COLUMN {name} {ddl}")
        db.execute("""CREATE TABLE IF NOT EXISTS payments(
            id     INTEGER PRIMARY KEY AUTOINCREMENT,
            email  TEXT NOT NULL,
            amount INTEGER,
            note   TEXT,
            at     TEXT NOT NULL
        )""")


def _recompute_status(db, email):
    row = db.execute("SELECT * FROM accounts WHERE email=?", (email,)).fetchone()
    if not row:
        return
    if row["free_events"] > 0:
        st = "FREE"
    elif row["escrow_due"] > 0:
        st = "DELINQUENT"
    else:
        st = "ACTIVE"
    db.execute("UPDATE accounts SET status=? WHERE email=?", (st, email))


# --------------------------------------------------------------------------
# account operations
# --------------------------------------------------------------------------
def create_account(email):
    """Register a new account (free). Returns (account_row, verify_token)."""
    email = (email or "").strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        return None, "invalid_email"
    token = secrets.token_urlsafe(24)
    with _conn() as db:
        try:
            db.execute(
                "INSERT INTO accounts(email, created_at, verify_token) VALUES(?,?,?)",
                (email, now_et().isoformat(), token))
        except sqlite3.IntegrityError:
            return None, "already_exists"
        row = db.execute("SELECT * FROM accounts WHERE email=?", (email,)).fetchone()
    return dict(row), token


def verify(email, token):
    """Confirm a verification token (the 'click the link' action)."""
    email = (email or "").strip().lower()
    with _conn() as db:
        row = db.execute("SELECT * FROM accounts WHERE email=?", (email,)).fetchone()
        if not row:
            return False, "no_account"
        if row["verified"]:
            return True, None
        if row["verify_token"] != token:
            return False, "bad_token"
        db.execute("UPDATE accounts SET verified=1, verify_token=NULL WHERE email=?",
                   (email,))
    return True, None


def get_account(email):
    email = (email or "").strip().lower()
    with _conn() as db:
        row = db.execute("SELECT * FROM accounts WHERE email=?", (email,)).fetchone()
    return dict(row) if row else None


# --------------------------------------------------------------------------
# the gate — request_event
# --------------------------------------------------------------------------
def request_event(email, asset=None, horizon=None):
    """The single gate. Returns {allowed, event_id, ...} or {allowed:False, reason}."""
    email = (email or "").strip().lower()
    today = now_et().strftime("%Y-%m-%d")
    with _conn() as db:
        row = db.execute("SELECT * FROM accounts WHERE email=?", (email,)).fetchone()
        if not row:
            return {"allowed": False, "reason": "no_account"}

        # daily rollover — reset the per-day counter on a new calendar day
        if row["last_event_date"] != today:
            db.execute("UPDATE accounts SET events_today=0, last_event_date=? WHERE email=?",
                       (today, email))
            row = db.execute("SELECT * FROM accounts WHERE email=?", (email,)).fetchone()

        if not row["verified"]:
            return {"allowed": False, "reason": "not_verified"}
        # a debtor is cut off absolutely, before the per-day throttle
        if row["escrow_due"] > 0:
            return {"allowed": False, "reason": "delinquent",
                    "escrow_due": row["escrow_due"]}
        if row["events_today"] >= DAILY_CAP:
            return {"allowed": False, "reason": "daily_cap"}

        # allowed — decide tier
        free = row["free_events"] > 0
        tier = "FREE" if free else row["tier"]
        if free:
            db.execute("UPDATE accounts SET free_events=free_events-1 WHERE email=?",
                       (email,))
        elif row["tier"] == "flat":
            # flat = pay-per-event: owe the flat price on issue
            db.execute("UPDATE accounts SET escrow_due=escrow_due+1 WHERE email=?",
                       (email,))

        eid = secrets.token_hex(8)
        db.execute("INSERT INTO events(id,email,asset,horizon,tier,issued_at)"
                   " VALUES(?,?,?,?,?,?)",
                   (eid, email, asset, horizon, tier, now_et().isoformat()))
        db.execute("UPDATE accounts SET events_today=events_today+1 WHERE email=?",
                   (email,))

        # after the last free event is spent, status leaves FREE
        row2 = db.execute("SELECT * FROM accounts WHERE email=?", (email,)).fetchone()
        _recompute_status(db, email)

    return {"allowed": True, "event_id": eid, "asset": asset, "horizon": horizon,
            "tier": tier, "note": "timing + tier only (step 2 attaches the event)"}


# --------------------------------------------------------------------------
# grading + payment (the escrow loop)
# --------------------------------------------------------------------------
def record_event_graded(event_id, correct):
    """Step 2/3 wire this when the tape grades the event. Correct non-free
    events accrue escrow; incorrect accrue nothing (locked 'no fee if wrong')."""
    with _conn() as db:
        ev = db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        if not ev:
            return {"ok": False, "error": "no_such_event"}
        db.execute("UPDATE events SET graded=1, correct=? WHERE id=?",
                   (1 if correct else 0, event_id))
        # FREE events never accrue a fee; pay_from_profit owes on a correct
        # result; flat already owes (charged at issue) and correctness is moot.
        if ev["tier"] == "pay_from_profit" and correct:
            db.execute("UPDATE accounts SET escrow_due=escrow_due+1 WHERE email=?",
                       (ev["email"],))
        _recompute_status(db, ev["email"])
        row = db.execute("SELECT * FROM accounts WHERE email=?", (ev["email"],)).fetchone()
    return {"ok": True, "correct": bool(correct), "escrow_due": row["escrow_due"],
            "status": row["status"]}


def attach_event(event_id, turn_time, window_min, tier_label, horizon=None):
    """Step 2 wires this once a turn is attached. Persists timing + tier label
    on the event; returns the enriched row. Carries NO dir/level/price."""
    with _conn() as db:
        db.execute("UPDATE events SET turn_time=?, window_min=?, tier_label=?, horizon=?"
                   " WHERE id=?",
                   (turn_time, window_min, tier_label, horizon, event_id))
        return db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()


def list_events(email):
    """The client's own event record (timing + tier only, black-box)."""
    email = (email or "").strip().lower()
    with _conn() as db:
        rows = db.execute("SELECT id, asset, horizon, turn_time, window_min,"
                          " tier_label, issued_at, graded, correct"
                          " FROM events WHERE email=? ORDER BY issued_at DESC",
                          (email,)).fetchall()
    return [dict(r) for r in rows]


def record_payment(email, amount=None, note=""):
    """Step 3 wires this with on-chain proof. Clears escrow → ACTIVE."""
    email = (email or "").strip().lower()
    with _conn() as db:
        row = db.execute("SELECT * FROM accounts WHERE email=?", (email,)).fetchone()
        if not row:
            return {"ok": False, "error": "no_account"}
        db.execute("INSERT INTO payments(email, amount, note, at) VALUES(?,?,?,?)",
                   (email, amount, note, now_et().isoformat()))
        db.execute("UPDATE accounts SET escrow_due=0 WHERE email=?", (email,))
        _recompute_status(db, email)
        row = db.execute("SELECT * FROM accounts WHERE email=?", (email,)).fetchone()
    return {"ok": True, "escrow_due": 0, "status": row["status"]}


# --------------------------------------------------------------------------
# email verification rail (Resend) — smoke only; token path is the local test
# --------------------------------------------------------------------------
def _send_verification(email, token, base_url):
    """Send the 'confirm your email' mail. Returns (sent_bool, detail)."""
    try:
        if not os.path.exists(RESEND_KEY_FILE):
            return False, "no_resend_key"
        key = open(RESEND_KEY_FILE).read().strip()
        link = f"{base_url}/verify?email={email}&token={token}"
        html = (f"<p>Confirm your ORACLE address to unlock your 3 free events.</p>"
                f"<p><a href='{link}'>{link}</a></p>"
                f"<p>No card. No commitment. The proof is the timing.</p>")
        body = json.dumps({"from": FROM, "to": [email],
                           "subject": "Confirm your ORACLE address",
                           "html": html}).encode()
        req = urllib.request.Request(
            "https://api.resend.com/emails", data=body,
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json",
                     "User-Agent": "Mozilla/5.0"})
        urllib.request.urlopen(req, timeout=15)
        return True, "sent"
    except Exception as e:
        return False, str(e)


# --------------------------------------------------------------------------
# HTTP server
# --------------------------------------------------------------------------
def _parse_args(handler):
    from urllib.parse import urlparse, parse_qs
    q = parse_qs(urlparse(handler.path).query)
    out = {k: v[0] for k, v in q.items() if v}
    # also accept a JSON body on POST
    try:
        n = int(handler.headers.get("Content-Length", 0) or 0)
        if n:
            raw = handler.rfile.read(n)
            if raw:
                out.update(json.loads(raw))
    except Exception:
        pass
    return out


class H(BaseHTTPRequestHandler):
    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _route(self):
        from urllib.parse import urlparse
        return urlparse(self.path).path

    def do_GET(self):
        a = _parse_args(self)
        path = self._route()
        if path == "/account":
            acct = get_account(a.get("email", ""))
            self._send(acct if acct else {"error": "no_account"})
        elif path == "/verify":
            ok, err = verify(a.get("email", ""), a.get("token", ""))
            self._send({"ok": ok} if ok else {"ok": False, "error": err})
        elif path == "/health":
            with _conn() as db:
                n = db.execute("SELECT COUNT(*) c FROM accounts").fetchone()["c"]
            self._send({"ok": True, "accounts": n, "db": DB,
                        "built": now_et().strftime("%Y-%m-%d %H:%M:%S %Z")})
        else:
            self._send({"service": "oracle-account", "port": PORT,
                        "routes": ["POST /signup", "GET /verify",
                                   "GET /account", "POST /request_event",
                                   "POST /grade_event", "POST /payment"]})

    def do_POST(self):
        a = _parse_args(self)
        path = self._route()
        if path == "/signup":
            acct, token = create_account(a.get("email", ""))
            if acct is None:
                self._send({"ok": False, "error": token}, 400)
                return
            # production: token goes email-only; local step-1 returns it so the
            # receipt test can complete the cycle deterministically.
            sent, det = _send_verification(acct["email"], token,
                                           f"http://{HOST}:{PORT}")
            self._send({"ok": True, "email": acct["email"],
                        "verify_token": token, "email_sent": sent,
                        "email_detail": det})
        elif path == "/request_event":
            r = request_event(a.get("email", ""), a.get("asset"),
                              a.get("horizon"))
            self._send(r)
        elif path == "/grade_event":
            r = record_event_graded(a.get("event_id", ""),
                                    a.get("correct", "").lower() in ("1", "true", "yes"))
            self._send(r)
        elif path == "/payment":
            amt = a.get("amount")
            r = record_payment(a.get("email", ""),
                               int(amt) if amt else None, a.get("note", ""))
            self._send(r)
        else:
            self._send({"error": "not_found"}, 404)

    def log_message(self, *a):
        pass


def main():
    init()
    srv = ThreadingHTTPServer((HOST, PORT), H)
    print(f"[oracle-account] serving on http://{HOST}:{PORT}/  (db={DB})")
    srv.serve_forever()


if __name__ == "__main__":
    main()