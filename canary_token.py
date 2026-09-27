"""
ORACLE SYSTEM — Canary Token Sharing Verification
=============================================================
Viral growth mechanism: each user gets a unique canary token.
Share a link → someone clicks → the token verifies the share → free pick earned.

Token format: oracle-v1-{user_id}-{random_hex}
Verification: GET /api/verify-share?token={token}&verifier={clicker_id}
"""

import json, secrets, hashlib, time, os, sqlite3
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "accounts.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_canary_db():
    """Create the canary sharing tables if they don't exist."""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS canary_tokens (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            max_clicks INTEGER DEFAULT 50
        );
        CREATE TABLE IF NOT EXISTS canary_clicks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT NOT NULL,
            verifier_id TEXT NOT NULL,
            clicked_at TEXT NOT NULL,
            verified_at TEXT,
            FOREIGN KEY (token) REFERENCES canary_tokens(token)
        );
        CREATE TABLE IF NOT EXISTS free_picks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            earned_at TEXT NOT NULL,
            type TEXT NOT NULL,
            note TEXT,
            used_at TEXT
        );
    """)
    conn.commit()
    conn.close()


def generate_token(user_id: str) -> str:
    """Generate a unique canary token for a user."""
    raw = f"oracle-v1-{user_id}-{secrets.token_hex(16)}"
    token = hashlib.sha256(raw.encode()).hexdigest()[:32]
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO canary_tokens (token, user_id, created_at) VALUES (?, ?, ?)",
        (token, user_id, datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()
    return token


def get_user_token(user_id: str) -> str:
    """Get or create a canary token for a user. Always creates fresh."""
    init_canary_db()
    conn = get_db()
    # Delete any old token for this user (always create fresh)
    conn.execute("DELETE FROM canary_tokens WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    return generate_token(user_id)


def get_share_link(user_id: str, base_url: str = "https://oracle.system") -> str:
    """Generate a share link with the user's canary token."""
    token = get_user_token(user_id)
    return f"{base_url}/refer/{token}"


def verify_click(token: str, verifier_id: str) -> dict:
    """
    Verify a click on a share link. Returns:
    {
        "valid": bool,
        "sharer_id": str,
        "free_pick_earned": bool,
        "total_clicks": int,
        "total_free_picks": int
    }
    """
    conn = get_db()
    now = datetime.utcnow().isoformat()
    
    # Check if token exists
    row = conn.execute(
        "SELECT token, user_id, max_clicks FROM canary_tokens WHERE token = ?",
        (token,)
    ).fetchone()
    
    if not row:
        conn.close()
        return {"valid": False, "error": "invalid_token"}
    
    sharer_id = row["user_id"]
    max_clicks = row["max_clicks"]
    
    # Check if verifier already clicked this token
    existing = conn.execute(
        "SELECT id FROM canary_clicks WHERE token = ? AND verifier_id = ?",
        (token, verifier_id)
    ).fetchone()
    
    if existing:
        conn.close()
        return {"valid": True, "sharer_id": sharer_id, "already_clicked": True, "error": "already_clicked"}
    
    # Check click limit
    click_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM canary_clicks WHERE token = ?", (token,)
    ).fetchone()["cnt"]
    
    if click_count >= max_clicks:
        conn.close()
        return {"valid": False, "error": "click_limit_reached", "sharer_id": sharer_id}
    
    # Record the click
    conn.execute(
        "INSERT INTO canary_clicks (token, verifier_id, clicked_at) VALUES (?, ?, ?)",
        (token, verifier_id, now)
    )
    
    # Award free pick (one per unique verifier)
    free_pick_earned = True
    conn.execute(
        "INSERT INTO free_picks (user_id, earned_at, type, note) VALUES (?, ?, ?, ?)",
        (sharer_id, now, "canary_share", f"Verified share click from {verifier_id}")
    )
    
    conn.commit()
    total_clicks = conn.execute(
        "SELECT COUNT(*) as cnt FROM canary_clicks WHERE token = ?", (token,)
    ).fetchone()["cnt"]
    total_free_picks = conn.execute(
        "SELECT COUNT(*) as cnt FROM free_picks WHERE user_id = ? AND type = 'canary_share'",
        (sharer_id,)
    ).fetchone()["cnt"]
    conn.close()
    
    return {
        "valid": True,
        "sharer_id": sharer_id,
        "free_pick_earned": True,
        "total_clicks": total_clicks,
        "total_free_picks": total_free_picks
    }


def get_user_free_picks(user_id: str) -> int:
    """Get the number of earned but unused free picks for a user."""
    conn = get_db()
    count = conn.execute(
        "SELECT COUNT(*) as cnt FROM free_picks WHERE user_id = ? AND type = 'canary_share' AND used_at IS NULL",
        (user_id,)
    ).fetchone()["cnt"]
    conn.close()
    return count


def mark_pick_used(user_id: str, pick_id: int = None) -> bool:
    """Mark a free pick as used."""
    conn = get_db()
    if pick_id:
        conn.execute(
            "UPDATE free_picks SET used_at = ? WHERE id = ? AND user_id = ? AND used_at IS NULL",
            (datetime.utcnow().isoformat(), pick_id, user_id)
        )
    else:
        conn.execute(
            "UPDATE free_picks SET used_at = ? WHERE user_id = ? AND type = 'canary_share' AND used_at IS NULL LIMIT 1",
            (datetime.utcnow().isoformat(), user_id)
        )
    conn.commit()
    conn.close()
    return True


def get_sharing_stats(user_id: str) -> dict:
    """Get sharing stats for a user."""
    conn = get_db()
    token = conn.execute(
        "SELECT token FROM canary_tokens WHERE user_id = ?", (user_id,)
    ).fetchone()
    if not token:
        conn.close()
        return {"token": None, "total_clicks": 0, "total_free_picks": 0}
    
    token_str = token["token"]
    total_clicks = conn.execute(
        "SELECT COUNT(*) as cnt FROM canary_clicks WHERE token = ?", (token_str,)
    ).fetchone()["cnt"]
    total_free_picks = conn.execute(
        "SELECT COUNT(*) as cnt FROM free_picks WHERE user_id = ? AND type = 'canary_share' AND used_at IS NULL",
        (user_id,)
    ).fetchone()["cnt"]
    conn.close()
    return {
        "token": token_str,
        "total_clicks": total_clicks,
        "total_free_picks": total_free_picks,
        "share_link": f"https://oracle.system/refer/{token_str}"
    }


# CLI interface for testing
if __name__ == "__main__":
    init_canary_db()
    
    # Simulate a user signing up
    sharer = "user_alice_123"
    token = generate_token(sharer)
    link = get_share_link(sharer)
    print(f"Sharer: {sharer}")
    print(f"Token: {token}")
    print(f"Link: {link}")
    
    # Simulate someone clicking the link
    result = verify_click(token, "user_bob_456")
    print(f"\nClick result: {json.dumps(result, indent=2)}")
    
    # Check free picks
    picks = get_user_free_picks(sharer)
    print(f"\nFree picks for {sharer}: {picks}")
    
    # Check stats
    stats = get_sharing_stats(sharer)
    print(f"\nSharing stats: {json.dumps(stats, indent=2)}")
