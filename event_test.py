#!/usr/bin/env python3
"""
EVENT-REQUEST SERVICE — receipt test (step 2). Uses a temp account DB and a
monkeypatched turn-clock fetch so the assertions are deterministic, then
proves the black-box doctrine: the client envelope carries timing + tier
ONLY, never dir / level / price.
"""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="oracle_evt_")
os.environ["ORACLE_ACCOUNT_DB"] = os.path.join(_tmp, "test.db")

import account  # noqa: E402
import event_service as ev  # noqa: E402

account.init()

EMAIL = "proof@example.com"
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {detail}")


def fake_turn(px, level, t="14:00"):
    def _f(_asset):
        return {"turn_time": t, "px": px, "level": level}
    return _f


print("EVENT SERVICE RECEIPT — temp db:", account.DB)
print("=" * 70)

# --- gate pass-through: unverified refused -------------------------------
acct_u, tok_u = account.create_account("unverified@example.com")  # exists, not verified
r = ev.issue_event("unverified@example.com", "BTC", "active")
check("unverified refused (gate passthrough)", r["allowed"] is False and r["reason"] == "not_verified", r)
# bad token cannot verify it away
ok, err = account.verify("unverified@example.com", "wrong")
check("unverified still blocked (token must match)", ok is False)

# --- setup a verified account --------------------------------------------
acct, token = account.create_account(EMAIL)
account.verify(EMAIL, token)

# --- asset not live (must NOT consume a slot) ----------------------------
ev.fetch_turn = fake_turn(px=84000.0, level=84200.0)
r = ev.issue_event(EMAIL, "GC", "active")
check("non-live asset refused honestly", r["allowed"] is False and r["reason"] == "asset_not_live", r)
check("non-live asset consumed NO slot", account.get_account(EMAIL)["free_events"] == 3,
      account.get_account(EMAIL))

# --- no turn available (must NOT consume a slot) -------------------------
ev.fetch_turn = lambda a: None
r = ev.issue_event(EMAIL, "BTC", "active")
check("no turn -> honored refusal", r["allowed"] is False and r["reason"] == "no_turn_yet", r)
check("no-turn consumed NO slot", account.get_account(EMAIL)["free_events"] == 3)

# --- MID event + black-box leak check ------------------------------------
ev.fetch_turn = fake_turn(px=84000.0, level=84200.0)   # 23.8 bp -> MID
r = ev.issue_event(EMAIL, "BTC", "active")
check("MID event issued", r["allowed"] is True and r["tier"] == "MID", r)
check("envelope has timing + tier", all(k in r for k in
      ("asset", "event_time", "window_min", "tier", "horizon", "event_id")))
LEAK = ["dir", "level", "px", "price", "move", "amount", "direction"]
leaked = [k for k in LEAK if k in r]
check("BLACK-BOX: no dir/level/price in envelope", not leaked,
      f"(would leak: {leaked})" if leaked else "")

# --- tier boundaries -----------------------------------------------------
check("MINOR tier (small swing)", ev.classify(84000.0, 84005.0)[0] == "MINOR")
check("MAJOR tier (large swing)", ev.classify(84000.0, 86000.0)[0] == "MAJOR")

# --- event persisted + visible via account layer -------------------------
rows = account.list_events(EMAIL)
check("event persisted (turn + tier only)",
      len(rows) >= 1 and rows[0]["turn_time"] == "14:00"
      and rows[0]["tier_label"] == "MID", rows[:1])

print("=" * 70)
print(f"RESULT: {len(PASS)} PASS / {len(FAIL)} FAIL")
if FAIL:
    print("FAILED:", FAIL)
    raise SystemExit(1)
print("ALL EVENT-SERVICE GATES RECEIPTED — step 2 complete.")