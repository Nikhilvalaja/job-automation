"""Setup script for Gmail Account 2: valajashekarnikhil12@gmail.com

Run this once to authenticate the second Gmail account:
    python -m src.gmail.setup_account2

It will open a browser window. Sign in with valajashekarnikhil12@gmail.com
The token will be saved to credentials/gmail_token2.json
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    print("\n" + "=" * 60)
    print("  Gmail Account 2 Setup")
    print("  Account: valajashekarnikhil12@gmail.com")
    print("=" * 60)
    print()
    print("A browser window will open. Sign in with:")
    print("  valajashekarnikhil12@gmail.com")
    print()
    print("After authorizing, the token will be saved automatically.")
    print()

    try:
        from src.gmail.multi_account import get_account2_service
        service = get_account2_service()

        # Verify it works
        profile = service.users().getProfile(userId="me").execute()
        email = profile.get("emailAddress", "unknown")
        count = profile.get("messagesTotal", 0)
        print(f"\n✅ Success! Connected to: {email}")
        print(f"   Inbox has {count:,} total messages")
        print()
        print("Account 2 is now active. The email bot will monitor both accounts.")
        print("Token saved to: credentials/gmail_token2.json")
    except Exception as e:
        print(f"\n❌ Setup failed: {e}")
        print("\nMake sure credentials/gmail_credentialsss.json exists")
        print("(Download from Google Cloud Console → APIs & Services → Credentials)")
        sys.exit(1)


if __name__ == "__main__":
    main()
