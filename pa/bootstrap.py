"""Wires everything together. UI-independent so it can be tested without Kivy."""
import os
from datetime import datetime

from .adapters.alarms import AndroidAlarmsAdapter
from .adapters.apps import AndroidAppsAdapter
from .adapters.calendar import ANDROID, AndroidCalendarAdapter
from .adapters.contacts import AndroidContactsAdapter
from .adapters.control import AndroidControlAdapter
from .adapters.daily_android import AndroidDailyAdapter
from .adapters.device_info import AndroidDeviceInfoAdapter
from .adapters.messages import AndroidMessagesAdapter
from .adapters.phone import AndroidPhoneAdapter
from .adapters.photos import AndroidPhotosAdapter
from .assistant import Assistant
from .crypto import Crypto
from .inference import load_backend
from .keys import AndroidKeystoreKeyProvider, DevFileKeyProvider, KeyUnavailable  # noqa: F401
from .storage import Store


def reset_encrypted_store(data_dir):
    """After an unrecoverable key error: move the unreadable database and key file aside (renamed to
    *.broken-<time>, not deleted) and forget the Keystore key, so the next start creates a fresh store.
    Returns the names that were moved."""
    import time
    stamp = time.strftime("%Y%m%d-%H%M%S")
    moved = []
    for name in ("pa.db", "pa.db-wal", "pa.db-shm", "dek.wrapped", "dek.wrapped.tmp", "dev.key"):
        p = os.path.join(data_dir, name)
        if os.path.exists(p):
            os.replace(p, "%s.broken-%s" % (p, stamp))
            moved.append(name)
    if ANDROID:
        try:
            AndroidKeystoreKeyProvider(os.path.join(data_dir, "dek.wrapped")).delete_alias()
        except Exception:
            pass  # a fresh key is made under the same alias only if this one is gone; see keys.py
    return moved


def build_assistant(data_dir):
    """Raises KeyUnavailable if no key provider works. There is NO plaintext fallback."""
    os.makedirs(data_dir, exist_ok=True)
    if ANDROID:
        kp = AndroidKeystoreKeyProvider(os.path.join(data_dir, "dek.wrapped"))
    else:
        kp = DevFileKeyProvider(os.path.join(data_dir, "dev.key"))  # refuses unless env opt-in
    key = kp.get_key()
    store = Store(os.path.join(data_dir, "pa.db"), Crypto(key))
    # timezone-aware, recomputed on each call so DST/zone changes are honoured
    return Assistant(store, load_backend(None), AndroidCalendarAdapter(), lambda: datetime.now().astimezone(),
                     contacts=AndroidContactsAdapter(), phone=AndroidPhoneAdapter(),
                     photos=AndroidPhotosAdapter(), apps=AndroidAppsAdapter(), daily=AndroidDailyAdapter(),
                     messages=AndroidMessagesAdapter(), alarms=AndroidAlarmsAdapter(),
                     device=AndroidDeviceInfoAdapter(), control=AndroidControlAdapter())
