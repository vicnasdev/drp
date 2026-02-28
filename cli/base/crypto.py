"""
cli/base/crypto.py

Client-side AES-256-GCM encryption/decryption helpers.
Used by up (encrypt), cat/edit (decrypt).
"""
from __future__ import annotations
import getpass
import io
import os


def prompt_passphrase(prompt: str = "decryption passphrase: ") -> str:
    return getpass.getpass(prompt)


def encrypt(file_obj, passphrase: str) -> tuple[io.BytesIO, str]:
    """Returns (encrypted BytesIO, content_type). Always application/octet-stream."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    salt  = os.urandom(16)
    key   = Scrypt(salt=salt, length=32, n=2**14, r=8, p=1).derive(passphrase.encode())
    nonce = os.urandom(12)
    ct    = AESGCM(key).encrypt(nonce, file_obj.read(), None)
    return io.BytesIO(salt + nonce + ct), "application/octet-stream"


def decrypt(data: bytes, passphrase: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    salt, nonce, ct = data[:16], data[16:28], data[28:]
    key = Scrypt(salt=salt, length=32, n=2**14, r=8, p=1).derive(passphrase.encode())
    return AESGCM(key).decrypt(nonce, ct, None)
