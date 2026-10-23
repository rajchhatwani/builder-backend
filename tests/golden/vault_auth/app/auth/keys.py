"""Print a fresh signing secret for your .env file (generated).

    python -m app.auth.keys

The line it prints is a secret: put it in .env (which is git-ignored) or your secret store.
"""

from app.auth.security import generate_private_key_pem


def main() -> None:
    pem = generate_private_key_pem().strip().replace("\n", "\\n")
    print(f'AUTH_JWT_PRIVATE_KEY="{pem}"')


if __name__ == "__main__":
    main()
