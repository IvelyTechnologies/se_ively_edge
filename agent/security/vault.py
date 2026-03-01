import base64

from cryptography.fernet import Fernet

from .device_key import get_device_key


def _cipher():
    key = base64.urlsafe_b64encode(get_device_key()[:32])
    return Fernet(key)


def encrypt(text: str):
    return _cipher().encrypt(text.encode()).decode()


def decrypt(token: str):
    return _cipher().decrypt(token.encode()).decode()
