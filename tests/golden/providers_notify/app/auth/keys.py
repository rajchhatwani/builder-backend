"""Print a fresh signing secret for your .env file (generated).

    python -m app.auth.keys

The line it prints is a secret: put it in .env (which is git-ignored) or your secret store.
"""

import secrets


def main() -> None:
    print(f"AUTH_JWT_SECRET={secrets.token_urlsafe(48)}")


if __name__ == "__main__":
    main()
