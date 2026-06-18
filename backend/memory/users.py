"""
Simple username/password auth.

Deliberately minimal — enough for testers to keep separate, persistent progress
(fresh vs. returning), not a production identity system. Passwords are hashed with
pbkdf2-hmac-sha256 (stdlib, no extra deps); we never store plaintext.

`user_id` is the normalized username, which is the key every progress table already
uses, so authenticating as a username transparently restores that user's data.
"""

import binascii
import hashlib
import hmac
import os

from psycopg2.extras import RealDictCursor

from memory.longterm import _conn
from observability.logger import log

_PBKDF2_ROUNDS = 100_000


def normalize_username(username: str) -> str:
    return (username or "").strip().lower()


def _hash_password(password: str, salt: bytes = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS)
    return f"{binascii.hexlify(salt).decode()}${binascii.hexlify(dk).decode()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, dk_hex = stored.split("$", 1)
        salt = binascii.unhexlify(salt_hex)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS)
        return hmac.compare_digest(binascii.hexlify(dk).decode(), dk_hex)
    except Exception:  # noqa: BLE001 — malformed hash never verifies
        return False


def get_user(user_id: str) -> dict | None:
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT user_id, username, exam_date FROM users WHERE user_id = %s", (user_id,)
        )
        row = cur.fetchone()
        if not row:
            return None
        u = dict(row)
        u["exam_date"] = u["exam_date"].isoformat() if u.get("exam_date") else None
        return u


def get_exam_date(user_id: str) -> str | None:
    """ISO date string (YYYY-MM-DD) or None."""
    u = get_user(user_id)
    return u["exam_date"] if u else None


def set_exam_date(user_id: str, exam_date: str | None) -> str | None:
    """Set (or clear, with None) the user's GRE exam date. Returns the stored value."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET exam_date = %s WHERE user_id = %s",
            (exam_date or None, user_id),
        )
        conn.commit()
    return exam_date or None


def create_user(username: str, password: str) -> dict | None:
    """Create a user. Returns {user_id, username}, or None if the username is taken."""
    uid = normalize_username(username)
    pw_hash = _hash_password(password)
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO users (user_id, username, password_hash)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id) DO NOTHING
            """,
            (uid, username.strip(), pw_hash),
        )
        created = cur.rowcount == 1
        conn.commit()
    if not created:
        return None
    log("user_created", user_id=uid)
    return {"user_id": uid, "username": username.strip()}


def authenticate(username: str, password: str) -> dict | None:
    """Return {user_id, username} on a correct password, else None."""
    uid = normalize_username(username)
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT user_id, username, password_hash FROM users WHERE user_id = %s", (uid,))
        row = cur.fetchone()
    if not row or not _verify_password(password, row["password_hash"]):
        return None
    return {"user_id": row["user_id"], "username": row["username"]}
