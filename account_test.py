#!/usr/bin/env python3
"""
ACCOUNT LAYER — end-to-end receipt test (step 1 of the ORACLE business build).

Runs the full lifecycle against a TEMP database (never the live accounts.db)
and prints a receipt. Covers every gate the design locks:

  no_account → not_verified → verified → 3 free events (one per day, daily
  cap enforced) → paid-tier event → correct grade → DELINQUENT cut-off →
  payment → ACTIVE → incorrect grade (no fee).

Because DAILY_CAP=1, the three free events are spread across three simulated
days by rolling last_event_date back — this exercises the daily cap AND the
free allowance honestly (the design intends the free proof to take 3 days).

Run: python3 account_test.py
"""
import os
import tempfile

# point the module at a throwaway DB before importing it
_tmp = tempfile.mkdtemp(prefix="oracle_acct_")
os.environ["ORACLE_ACCOUNT_DB"] = os.path.join(_tmp, "test.db")

import account  # noqa: E402  (import after env override)

account.init()

EMAIL = "proof@example.com"
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {detail}")


print("ACCOUNT LAYER RECEIPT — temp db:", account.DB)
print("=" * 70)

# 1. unknown email
r = account.request_event("nobody@example.com")
check("no_account refuses unknown email", r["allowed"] is False and r["reason"] == "no_account", r)

# 2. signup
acct, token = account.create_account(EMAIL)
check("signup creates account", acct is not None and acct["email"] == EMAIL,
      f"free_events={acct['free_events']} verified={acct['verified']} status={acct['status']}")
check("fresh account has 3 free events", acct["free_events"] == account.FREE_EVENTS)
check("fresh account unverified", acct["verified"] == 0)

# 3. request before verify → refused
r = account.request_event(EMAIL, "BTC", "active")
check("unverified refused (anti fake-email farming)", r["allowed"] is False and r["reason"] == "not_verified", r)

# 4. verify — bad token first (while still unverified), then the good token
ok, err = account.verify(EMAIL, "wrongtoken")
check("verify rejects bad token", ok is False and err == "bad_token", f"err={err}")
ok, err = account.verify(EMAIL, token)
check("verify succeeds", ok is True, f"err={err}")
ok, err = account.verify(EMAIL, token)
check("verify is idempotent (re-verify ok)", ok is True)

# 5. free event 1
r = account.request_event(EMAIL, "BTC", "active")
check("free event #1 allowed", r["allowed"] is True and r["tier"] == "FREE", r)
check("free allowance 3→2", account.get_account(EMAIL)["free_events"] == 2)

# 6. daily cap — same day second request refused
r = account.request_event(EMAIL, "ETH", "active")
check("daily cap refuses 2nd event same day", r["allowed"] is False and r["reason"] == "daily_cap", r)

# 7. roll a day, free event 2
with account._conn() as db:
    db.execute("UPDATE accounts SET last_event_date='1970-01-01' WHERE email=?", (EMAIL,))
r = account.request_event(EMAIL, "ETH", "active")
check("free event #2 allowed (new day)", r["allowed"] is True, r)
check("free allowance 2→1", account.get_account(EMAIL)["free_events"] == 1)

# 8. roll a day, free event 3 (last free)
with account._conn() as db:
    db.execute("UPDATE accounts SET last_event_date='1970-01-01' WHERE email=?", (EMAIL,))
r = account.request_event(EMAIL, "BTC", "active")
check("free event #3 allowed (last free)", r["allowed"] is True and r["tier"] == "FREE", r)
check("free allowance 1→0", account.get_account(EMAIL)["free_events"] == 0)

# 9. roll a day — paid tier (pay_from_profit) event
with account._conn() as db:
    db.execute("UPDATE accounts SET last_event_date='1970-01-01' WHERE email=?", (EMAIL,))
r = account.request_event(EMAIL, "BTC", "swing")
check("paid-tier event allowed after free spent", r["allowed"] is True and r["tier"] == "pay_from_profit", r)
paid_id = r["event_id"]

# 10. grade CORRECT → owe → DELINQUENT
g = account.record_event_graded(paid_id, True)
check("correct paid event accrues escrow", g["ok"] and g["escrow_due"] == 1, g)
check("status → DELINQUENT", g["status"] == "DELINQUENT")

# 11. delinquent cut-off
r = account.request_event(EMAIL, "BTC", "active")
check("delinquent cut off (no further events)", r["allowed"] is False and r["reason"] == "delinquent", r)

# 12. payment clears escrow
p = account.record_payment(EMAIL, 1000, "on-chain (step 3 wires real proof)")
check("payment clears escrow → ACTIVE", p["ok"] and p["escrow_due"] == 0 and p["status"] == "ACTIVE", p)

# 13. incorrect grade → no fee
with account._conn() as db:
    db.execute("UPDATE accounts SET last_event_date='1970-01-01' WHERE email=?", (EMAIL,))
r = account.request_event(EMAIL, "BTC", "active")
wrong_id = r["event_id"]
g = account.record_event_graded(wrong_id, False)
check("incorrect event accrues NO fee (locked)", g["ok"] and g["escrow_due"] == 0, g)

print("=" * 70)
print(f"RESULT: {len(PASS)} PASS / {len(FAIL)} FAIL")
if FAIL:
    print("FAILED:", FAIL)
    raise SystemExit(1)
print("ALL GATES RECEIPTED — account layer step 1 complete.")