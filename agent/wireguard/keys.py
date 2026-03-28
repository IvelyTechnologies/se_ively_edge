# WireGuard key management — generate and load WG key pairs

import os
import subprocess

from agent.wireguard.config import WG_KEYS_DIR, WG_PRIVATE_KEY_PATH, WG_PUBLIC_KEY_PATH


def _ensure_keys_dir():
    """Create key storage directory with restrictive permissions."""
    os.makedirs(WG_KEYS_DIR, mode=0o700, exist_ok=True)


def generate_keypair() -> tuple[str, str]:
    """
    Generate a WireGuard key pair. Returns (private_key, public_key).
    Keys are saved to disk and returned as base64 strings.
    """
    _ensure_keys_dir()

    # Generate private key
    result = subprocess.run(
        ["wg", "genkey"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(f"wg genkey failed: {result.stderr.strip()}")

    private_key = result.stdout.strip()

    # Derive public key
    result = subprocess.run(
        ["wg", "pubkey"],
        input=private_key,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(f"wg pubkey failed: {result.stderr.strip()}")

    public_key = result.stdout.strip()

    # Save keys with restrictive permissions
    with open(WG_PRIVATE_KEY_PATH, "w", encoding="utf-8") as f:
        f.write(private_key)
    os.chmod(WG_PRIVATE_KEY_PATH, 0o600)

    with open(WG_PUBLIC_KEY_PATH, "w", encoding="utf-8") as f:
        f.write(public_key)
    os.chmod(WG_PUBLIC_KEY_PATH, 0o644)

    return private_key, public_key


def load_keypair() -> tuple[str, str] | None:
    """
    Load existing key pair from disk. Returns (private_key, public_key) or None if not found.
    """
    try:
        with open(WG_PRIVATE_KEY_PATH, encoding="utf-8") as f:
            private_key = f.read().strip()
        with open(WG_PUBLIC_KEY_PATH, encoding="utf-8") as f:
            public_key = f.read().strip()
        if private_key and public_key:
            return private_key, public_key
    except FileNotFoundError:
        pass
    return None


def get_or_create_keypair() -> tuple[str, str]:
    """Load existing keys or generate new ones. Returns (private_key, public_key)."""
    existing = load_keypair()
    if existing:
        return existing
    return generate_keypair()


def get_public_key() -> str:
    """Return the public key (generate if needed)."""
    _, pub = get_or_create_keypair()
    return pub
