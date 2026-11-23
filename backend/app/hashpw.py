"""Print a ready-to-paste .env line:  python -m app.hashpw

Single-quoted because Docker Compose would otherwise interpolate the `$` in argon2 hashes."""
import getpass

from .auth import hash_password

if __name__ == "__main__":
    print(f"AUTH_PASSWORD_HASH='{hash_password(getpass.getpass('Password: '))}'")
