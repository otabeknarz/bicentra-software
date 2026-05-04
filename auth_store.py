"""Encrypted token storage for persisting sessions between app launches."""

import base64
import hashlib
import json
import os
import platform

from cryptography.fernet import Fernet, InvalidToken

# Store in user's home directory
STORE_DIR = os.path.join(os.path.expanduser("~"), ".bicentra")
STORE_FILE = os.path.join(STORE_DIR, "session.enc")


def _get_machine_key() -> bytes:
    """Derive an encryption key from machine-specific data."""
    # Combine username + hostname + platform for a stable machine ID
    raw = f"{os.getlogin()}@{platform.node()}:{platform.system()}-bicentra-desktop"
    # SHA256 → 32 bytes → base64 for Fernet
    digest = hashlib.sha256(raw.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def save_tokens(access_token: str, refresh_token: str, email: str) -> None:
    """Encrypt and save tokens to disk."""
    os.makedirs(STORE_DIR, exist_ok=True)
    fernet = Fernet(_get_machine_key())
    data = json.dumps({
        "access": access_token,
        "refresh": refresh_token,
        "email": email,
    }).encode()
    encrypted = fernet.encrypt(data)
    with open(STORE_FILE, "wb") as f:
        f.write(encrypted)


def load_tokens() -> dict | None:
    """Load and decrypt tokens from disk. Returns None if not found or invalid."""
    if not os.path.exists(STORE_FILE):
        return None
    try:
        fernet = Fernet(_get_machine_key())
        with open(STORE_FILE, "rb") as f:
            encrypted = f.read()
        data = fernet.decrypt(encrypted)
        return json.loads(data)
    except (InvalidToken, json.JSONDecodeError, Exception):
        # Corrupted or from different machine — clear it
        clear_tokens()
        return None


def clear_tokens() -> None:
    """Delete saved tokens."""
    if os.path.exists(STORE_FILE):
        os.remove(STORE_FILE)
