"""AES-256-GCM field encryption with two interchangeable backends producing the SAME blob
format: nonce(12) || ciphertext || tag(16).
  - `cryptography` (desktop/tests; may be hard to package for Android: needs Rust)
  - `pycryptodome` (has a python-for-android recipe; used for the APK)"""
import os

_FORCE = os.environ.get("PA_CRYPTO_BACKEND")  # "cryptography" | "pycryptodome" | unset = auto


def _load(name):
    if name == "cryptography":
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        def enc(key, nonce, data, aad):
            return AESGCM(key).encrypt(nonce, data, aad)

        def dec(key, nonce, blob, aad):
            return AESGCM(key).decrypt(nonce, blob, aad)
        return enc, dec
    from Crypto.Cipher import AES  # pycryptodome

    def enc(key, nonce, data, aad):
        c = AES.new(key, AES.MODE_GCM, nonce=nonce)
        c.update(aad)
        ct, tag = c.encrypt_and_digest(data)
        return ct + tag

    def dec(key, nonce, blob, aad):
        c = AES.new(key, AES.MODE_GCM, nonce=nonce)
        c.update(aad)
        return c.decrypt_and_verify(blob[:-16], blob[-16:])
    return enc, dec


def _pick(name=None):
    name = name or _FORCE
    if name:
        return name, _load(name)
    for n in ("cryptography", "pycryptodome"):
        try:
            return n, _load(n)
        except ImportError:
            continue
    raise ImportError("no AES-GCM backend installed (need cryptography or pycryptodome)")


class Crypto:
    def __init__(self, key: bytes, backend=None):
        if len(key) != 32:
            raise ValueError("key must be 32 bytes")
        self.key = key
        self.backend, (self._enc, self._dec) = _pick(backend)

    def enc(self, data: bytes, aad: str) -> bytes:
        nonce = os.urandom(12)
        return nonce + self._enc(self.key, nonce, data, aad.encode())

    def dec(self, blob: bytes, aad: str) -> bytes:
        return self._dec(self.key, blob[:12], blob[12:], aad.encode())
