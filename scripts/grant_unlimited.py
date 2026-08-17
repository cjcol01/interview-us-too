"""One-shot script: grant a user unlimited account level.
Usage:
    railway run python scripts/grant_unlimited.py cjcol01
"""
import sys
import os

# bootstrap path so imports work from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from models import User, AccountLevel

username = sys.argv[1] if len(sys.argv) > 1 else "cjcol01"

db = SessionLocal()
try:
    user = db.query(User).filter(User.username == username).first()
    if not user:
        print(f"ERROR: no user found with username '{username}'")
        sys.exit(1)

    print(f"Found: {user.email}  current level={user.account_level.value}")

    user.account_level    = AccountLevel.unlimited
    user.sub_invoice_paid = True          # passes the billing-gate check at /app load
    user.setup_complete   = True          # skip onboarding redirect
    user.welcome_seen     = True          # skip welcome redirect
    user.sessions_remaining = 0          # not used for unlimited, but clear any misleading value

    db.commit()
    db.refresh(user)
    print(f"Done.  {user.username} is now: {user.account_level.value}")
finally:
    db.close()
