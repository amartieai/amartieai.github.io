#!/usr/bin/env python3
"""
ORACLE BUSINESS — EVENT-REQUEST SERVICE (step 2 of the locked build).

Turns an allowed account request into an actual EVENT. An EVENT = the ONE
thing we sell: TIMING (when). Never direction, never price, never magnitude.
Tier is a LABEL (MINOR/MID/MAJOR) only — never a point count.

Black-box doctrine (design §2, owner ruling): the envelope a client receives
is EXACTLY  {asset, event_time, window_min, tier, horizon}  and nothing else.
Direction and level exist inside the turn-clock (the free :8721 proof page)
but are NOT part of the paid event — the client reads their own chart and
hedges themselves. Enforced here: dir/level/px are never copied into the
event, and the leak-scan test asserts their absence.

Data source: the crypto turn-clock (:8721) for BTC/ETH (24/7). Futures/FX
session turns wire in on weekdays (step 2b). Non-crypto assets or the 'swing'
horizon return an honest not_available until those engines attach — never a
fabricated event.

Flow: POST /event {email, asset, horizon}
  1. account.request_event gates (verified / daily cap / escrow)
  2. if allowed, fetch the live next-turn for the asset
  3. classify the swing into a tier LABEL (internal amplitude, never emitted)
  4. persist turn_time + window + tier_label + horizon on the event
  5. return the EVENT envelope (timing + tier only)
"""
import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import account  # step 1 — same directory

HOST, PORT = "127.0.0.1", 8724
ET = timezone(timedelta(hours=-4))
CLOCK = "http://127.0.0.1:8721/state"

# tier thresholds — swing as basis points of current price (tunable, label only)
TIER_MINOR_BP = 15
TIER_MID_BP = 60
WINDOW_MIN = 6          # the turn-clock grades over ±6 min (locked there)
SUPPORTED = {"BTC", "ETH"}   # live 24/7; futures/FX join on weekdays


def _jam(bp):
    if bp < TIER_MINOR_BP:
        return "MINOR"
    if bp < TIER_MID_BP:
        return "MID"
    return "MAJOR"


def fetch_turn(asset):
    """Read the live next-turn from the crypto turn-clock. Returns dict or None."""
    req = urllib.request.Request(CLOCK, headers={"User-Agent": "Mozilla/5.0"})
    d = json.loads(urllib.request.urlopen(req, timeout=10).read())
    live = d.get("live", {}).get(asset.upper())
    if not live:
        return None
    call = live.get("call")
    if not call:
        return None
    return {"turn_time": call["turn_time"], "px": live.get("px"),
            "level": call.get("level")}


def classify(px, level):
    """Swing -> tier label. Returns (label, bp). bp is internal, never emitted."""
    if not px or not level or px <= 0:
        return None, None
    bp = abs(level - px) / px * 10000.0
    return _jam(bp), bp


def issue_event(email, asset, horizon="active"):
    """Full event-request flow. Returns the client envelope or a refusal.

    ORDER MATTERS: the account gate consumes a free-event/daily slot, so the
    asset + turn are checked FIRST — a request we cannot serve must not burn
    a slot (verify-before-value-leaves). Only an actually-deliverable event
    touches the account layer."""
    a = (asset or "").upper()
    if a not in SUPPORTED:
        return {"allowed": False, "reason": "asset_not_live", "asset": a}
    turn = fetch_turn(a)
    if not turn:
        return {"allowed": False, "reason": "no_turn_yet", "asset": a}
    resp = account.request_event(email, asset, horizon)
    if not resp.get("allowed"):
        return resp                       # {allowed:false, reason}
    tier, _bp = classify(turn["px"], turn["level"])
    account.attach_event(resp["event_id"], turn["turn_time"], WINDOW_MIN,
                         tier, horizon)
    return {
        "allowed": True, "event_id": resp["event_id"], "asset": a,
        "event_time": turn["turn_time"], "window_min": WINDOW_MIN,
        "tier": tier, "horizon": horizon,
    }


# --------------------------------------------------------------------------
# HTTP server
# --------------------------------------------------------------------------
def _parse_args(handler):
    from urllib.parse import urlparse, parse_qs
    q = parse_qs(urlparse(handler.path).query)
    out = {k: v[0] for k, v in q.items() if v}
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
        if self._route() == "/health":
            self._send({"ok": True, "service": "oracle-event", "port": PORT,
                        "assets": sorted(SUPPORTED),
                        "built": datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S %Z")})
        elif self._route() == "/events":
            self._send(account.list_events(a.get("email", "")))
        else:
            self._send({"service": "oracle-event", "routes":
                        ["POST /event {email,asset,horizon}", "GET /events?email",
                         "GET /health"]})

    def do_POST(self):
        a = _parse_args(self)
        if self._route() == "/event":
            self._send(issue_event(a.get("email", ""), a.get("asset", ""),
                                   a.get("horizon", "active")))
        else:
            self._send({"error": "not_found"}, 404)

    def log_message(self, *a):
        pass


def main():
    account.init()
    srv = ThreadingHTTPServer((HOST, PORT), H)
    print(f"[oracle-event] serving on http://{HOST}:{PORT}/  (clock={CLOCK})")
    srv.serve_forever()


if __name__ == "__main__":
    main()