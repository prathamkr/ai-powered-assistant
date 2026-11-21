"""Wires everything together. UI-independent so it can be tested without Kivy."""
import os
from datetime import datetime

from .adapters.calendar import ANDROID, AndroidCalendarAdapter
from .adapters.contacts import AndroidContactsAdapter
from .adapters.phone import AndroidPhoneAdapter
from .adapters.photos import AndroidPhotosAdapter
from .assistant import Assistant
from .crypto import Crypto
from .inference import load_backend
from .keys import AndroidKeystoreKeyProvider, DevFileKeyProvider, KeyUnavailable  # noqa: F401
from .storage import Store


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
                     photos=AndroidPhotosAdapter())
