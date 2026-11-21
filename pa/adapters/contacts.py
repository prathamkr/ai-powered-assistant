"""Contacts lookup (read-only). Needs READ_CONTACTS. Returns at most a few matches."""
import re

from . import android_util as au
from .base import Adapter


def _norm(num):
    d = re.sub(r"\D", "", num or "")
    return d[-10:]


class AndroidContactsAdapter(Adapter):
    name = "contacts"

    def capability_check(self):
        return au.ANDROID

    def permission_check(self):
        return "granted" if au.granted(au.READ_CONTACTS) else "denied"

    def required_permissions(self):
        return [au.READ_CONTACTS, au.CALL_PHONE, au.READ_PHONE_STATE]

    def search(self, name, limit=20):
        """[{name, number}] matching display name, de-duplicated by number."""
        Phone = au.autoclass("android.provider.ContactsContract$CommonDataKinds$Phone")
        # literal column names: pyjnius does not expose constants inherited from interfaces
        cur = au.mActivity.getContentResolver().query(
            Phone.CONTENT_URI, ["display_name", "data1"], "display_name LIKE ?",
            ["%" + name + "%"], "display_name ASC")
        out, seen = [], set()
        for disp, num in au.rows(cur, 2, limit=50):
            key = _norm(num)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append({"name": disp or num, "number": num})
            if len(out) >= limit:
                break
        return out
