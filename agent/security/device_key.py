import hashlib
import uuid


def get_device_key():
    mac = uuid.getnode()
    raw = f"ively-{mac}".encode()
    return hashlib.sha256(raw).digest()
