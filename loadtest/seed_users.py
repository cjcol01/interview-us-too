"""Seed (or clean up) free-tier test users for load testing the local dev server.

Reuses the app's own DB/auth modules so seeded users are indistinguishable from real
rows in interview.db, but every one is created at AccountLevel.free. That matters:
_gate_basic_access() in server.py rejects free accounts with a 403 *before* any call
to Anthropic/OpenAI, so load-testing traffic from these accounts can never cost money.

Usage:
    python loadtest/seed_users.py --count 50        # create users, write accounts.json
    python loadtest/seed_users.py --cleanup         # delete all loadtest_* users

Run this in the same environment as the dev server (same interview.db / DATA_DIR),
with the server stopped or at least not mid-migration. `python server.py` should be
runnable immediately before or after.
"""
import argparse
import json
import secrets
import sys
from pathlib import Path

# Make the app package importable when this script is run from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import SessionLocal, init_db  # noqa: E402
from models import AccountLevel, User  # noqa: E402
from auth import hash_password, generate_unique_referral_code, create_token  # noqa: E402

USERNAME_PREFIX = "loadtest_"
DEFAULT_PASSWORD = "loadtest-pw-123"
ACCOUNTS_FILE = Path(__file__).resolve().parent / "accounts.json"


def seed(count: int, password: str) -> list[dict]:
    init_db()
    db = SessionLocal()
    accounts = []
    try:
        for i in range(count):
            username = f"{USERNAME_PREFIX}{i}"
            email = f"{username}@loadtest.invalid"

            existing = db.query(User).filter(User.username == username).first()
            if existing:
                user = existing
                user.account_level = AccountLevel.free
                if not user.api_token:
                    user.api_token = secrets.token_urlsafe(32)
            else:
                user = User(
                    username=username,
                    email=email,
                    full_name=f"Load Test {i}",
                    password_hash=hash_password(password),
                    account_level=AccountLevel.free,
                    email_verified=True,
                    is_active=True,
                    setup_complete=True,
                    api_token=secrets.token_urlsafe(32),
                    referral_code=generate_unique_referral_code(db),
                )
                db.add(user)
            db.flush()

            # Hard safety check: never let a non-free account leak into accounts.json.
            assert user.account_level == AccountLevel.free, (
                f"refusing to seed non-free account for {username}"
            )
            accounts.append({
                "username": user.username,
                "password": password,
                "api_token": user.api_token,
                "account_level": user.account_level.value,
                # A ready-to-use session cookie, so the load test can simulate a
                # returning user with an already-valid session instead of always
                # hitting /auth/login (real traffic is mostly already-logged-in
                # users, not fresh logins on every request).
                "session_token": create_token(user.id),
            })
        db.commit()
    finally:
        db.close()
    return accounts


def cleanup() -> int:
    init_db()
    db = SessionLocal()
    try:
        users = db.query(User).filter(User.username.like(f"{USERNAME_PREFIX}%")).all()
        n = len(users)
        for u in users:
            db.delete(u)
        db.commit()
    finally:
        db.close()
    if ACCOUNTS_FILE.exists():
        ACCOUNTS_FILE.unlink()
    return n


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=50, help="number of test users to seed")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="shared password for seeded users")
    parser.add_argument("--cleanup", action="store_true", help="delete all loadtest_* users and accounts.json")
    args = parser.parse_args()

    if args.cleanup:
        n = cleanup()
        print(f"Deleted {n} loadtest user(s) and removed {ACCOUNTS_FILE.name} if present.")
        return

    accounts = seed(args.count, args.password)
    non_free = [a for a in accounts if a["account_level"] != "free"]
    if non_free:
        # Should be unreachable given the assert above, but double-guard the file write.
        raise SystemExit(f"Refusing to write accounts.json: {len(non_free)} non-free account(s) found.")

    ACCOUNTS_FILE.write_text(json.dumps(accounts, indent=2))
    print(f"Seeded {len(accounts)} free-tier users -> {ACCOUNTS_FILE}")
    print(f"Shared password: {args.password}")


if __name__ == "__main__":
    main()
