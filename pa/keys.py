"""Key providers. No provider => the app refuses to open the DB (no plaintext fallback)."""
import os


class KeyUnavailable(Exception):
    """recoverable=True: the stored key data exists but cannot be used (damaged file, lost Keystore key).
    The old data can never be read again; the user may reset (pa.bootstrap.reset_encrypted_store)."""

    def __init__(self, msg, recoverable=False):
        super().__init__(msg)
        self.recoverable = recoverable


def short_error(e, limit=200):
    """First line of an exception, without the Java stack trace pyjnius puts into the message."""
    text = str(e).strip().splitlines()[0] if str(e).strip() else ""
    return ("%s: %s" % (type(e).__name__, text))[:limit]


class KeyProvider:
    def get_key(self) -> bytes:
        raise NotImplementedError


class DevFileKeyProvider(KeyProvider):
    """INSECURE: key sits next to the DB. Dev only, must be enabled explicitly."""

    def __init__(self, path):
        self.path = path

    def get_key(self):
        if os.environ.get("PA_ALLOW_INSECURE_DEV_KEY") != "1":
            raise KeyUnavailable("Dev key disabled. Set PA_ALLOW_INSECURE_DEV_KEY=1 (not for real data).")
        if os.path.exists(self.path):
            return open(self.path, "rb").read()
        k = os.urandom(32)
        write_atomic(self.path, k)
        return k


class AndroidKeystoreKeyProvider(KeyProvider):
    """UNVERIFIED on a device. A random 32-byte data key is wrapped (AES-GCM) by a
    non-exportable Android Keystore key; only the wrapped blob is stored on disk."""

    ALIAS = "pa_master_v1"

    def __init__(self, wrapped_path):
        self.path = wrapped_path

    @staticmethod
    def _b(x):  # pyjnius byte[] -> bytes
        return bytes(bytearray([v & 0xFF for v in x]))

    WRAPPED_MIN = 12 + 32 + 16  # IV + data key + GCM tag

    def get_key(self):
        try:
            from jnius import autoclass  # noqa: F401
        except Exception as e:
            raise KeyUnavailable("Android Keystore not available: %s" % e)
        try:
            return self._get_key()
        except KeyUnavailable:
            raise
        except Exception as e:
            # Seen on an emulator: the app was killed while it first wrote the wrapped key, and every
            # later start failed in Cipher.init with a long Java stack trace on screen.
            raise KeyUnavailable("Android Keystore error: %s" % short_error(e), recoverable=os.path.exists(self.path))

    def delete_alias(self):
        from jnius import autoclass
        ks = autoclass("java.security.KeyStore").getInstance("AndroidKeyStore")
        ks.load(None)
        if ks.containsAlias(self.ALIAS):
            ks.deleteEntry(self.ALIAS)

    def _get_key(self):
        from jnius import autoclass
        KeyStore = autoclass("java.security.KeyStore")
        Cipher = autoclass("javax.crypto.Cipher")
        ks = KeyStore.getInstance("AndroidKeyStore")
        ks.load(None)
        if not ks.containsAlias(self.ALIAS):
            Builder = autoclass("android.security.keystore.KeyGenParameterSpec$Builder")
            Props = autoclass("android.security.keystore.KeyProperties")
            KG = autoclass("javax.crypto.KeyGenerator")
            # setBlockModes/setEncryptionPaddings are Java varargs (String...): pass the
            # string itself. Passing a Python list makes pyjnius build String[][] and the
            # JVM aborts the whole process with ArrayStoreException (seen on emulator).
            spec = (Builder(self.ALIAS, Props.PURPOSE_ENCRYPT | Props.PURPOSE_DECRYPT)
                    .setBlockModes(Props.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(Props.ENCRYPTION_PADDING_NONE)
                    .setKeySize(256).build())
            g = KG.getInstance(Props.KEY_ALGORITHM_AES, "AndroidKeyStore")
            g.init(spec)
            g.generateKey()
        mk = ks.getKey(self.ALIAS, None)
        c = Cipher.getInstance("AES/GCM/NoPadding")
        if os.path.exists(self.path):
            blob = open(self.path, "rb").read()
            if len(blob) < self.WRAPPED_MIN:
                raise KeyUnavailable("the stored key file is damaged (%d bytes)" % len(blob), recoverable=True)
            iv, ct = blob[:12], blob[12:]
            GCM = autoclass("javax.crypto.spec.GCMParameterSpec")
            c.init(Cipher.DECRYPT_MODE, mk, GCM(128, iv))
            return self._b(c.doFinal(ct))
        dek = os.urandom(32)
        c.init(Cipher.ENCRYPT_MODE, mk)
        iv = self._b(c.getIV())
        ct = self._b(c.doFinal(dek))
        write_atomic(self.path, iv + ct)
        return dek


def write_atomic(path, data):
    """Write so that the file is either the old one or the complete new one, never half written."""
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
