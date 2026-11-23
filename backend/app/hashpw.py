"""Print an argon2 hash for AUTH_PASSWORD_HASH:  python -m app.hashpw"""
import getpass

from .auth import hash_password

if __name__ == "__main__":
    print(hash_password(getpass.getpass("Password: ")))
