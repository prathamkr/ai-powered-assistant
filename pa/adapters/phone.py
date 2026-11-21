"""Phone call adapter with SIM selection.
With CALL_PHONE granted, execute() places the call via TelecomManager.placeCall on the chosen
SIM (status 'done' = call placed, not answered). Without it, it opens the dialer with the
number filled in ('handed_off'); the dialer cannot pre-select a SIM.
Listing SIMs needs READ_PHONE_STATE."""
import re

from . import android_util as au
from .base import Adapter, Result

NUM_RE = re.compile(r"^\+?[0-9][0-9 ()\-]{2,19}$")
EXTRA_PHONE_ACCOUNT_HANDLE = "android.telecom.extra.PHONE_ACCOUNT_HANDLE"


def _s(cs):
    """Java CharSequence -> str. pyjnius already returns some of them as Python str
    (calling .toString() on those raised AttributeError on the phone)."""
    if cs is None:
        return None
    return cs if isinstance(cs, str) else cs.toString()


def clean_number(n):
    return re.sub(r"[^\d+]", "", n or "")


class AndroidPhoneAdapter(Adapter):
    name = "phone_call"

    def __init__(self):
        self._handles = {}  # slot -> PhoneAccountHandle (Java object, never leaves the adapter)

    def capability_check(self):
        return au.ANDROID

    def permission_check(self):
        return "not_required"  # dialer fallback needs no permission

    def can_call_directly(self):
        return au.granted(au.CALL_PHONE)

    def required_permissions(self):
        return [au.CALL_PHONE, au.READ_PHONE_STATE]

    def _svc(self, name, cls):
        from jnius import cast  # type: ignore
        Context = au.autoclass("android.content.Context")
        return cast(cls, au.mActivity.getSystemService(getattr(Context, name)))

    def sims(self):
        """[{slot, label}] for call-capable SIMs, or None without READ_PHONE_STATE."""
        if not au.granted(au.READ_PHONE_STATE):
            return None
        tm = self._svc("TELECOM_SERVICE", "android.telecom.TelecomManager")
        handles = tm.getCallCapablePhoneAccounts()
        tel = sm = None
        if au.sdk_int() >= 30:
            try:
                tel = self._svc("TELEPHONY_SERVICE", "android.telephony.TelephonyManager")
                sm = self._svc("TELEPHONY_SUBSCRIPTION_SERVICE", "android.telephony.SubscriptionManager")
            except Exception:
                tel = sm = None
        infos = []  # active SIMs: (subId, slot, carrier, display)
        if sm is not None:
            try:
                lst = sm.getActiveSubscriptionInfoList()
                for j in range(lst.size() if lst is not None else 0):
                    inf = lst.get(j)
                    infos.append((int(inf.getSubscriptionId()), inf.getSimSlotIndex() + 1,
                                  _s(inf.getCarrierName()), _s(inf.getDisplayName())))
            except Exception:
                infos = []  # fall back to handle order; carrier names then unavailable
        out, self._handles = [], {}
        n = handles.size()
        for i in range(n):
            h = handles.get(i)
            slot, names, info, how = i + 1, [], None, "order"
            try:
                acc = tm.getPhoneAccount(h)
                if acc is not None and acc.getLabel() is not None:
                    names.append(_s(acc.getLabel()))  # e.g. "SIM 1"
            except Exception:
                pass
            # Map handle -> SIM. On the vivo test phone getSubscriptionId(handle) gave no match,
            # so try several ways; the last resort pairs them only when there is exactly one of each.
            sub = None
            if tel is not None:
                try:
                    sub = int(tel.getSubscriptionId(h))
                except Exception:
                    sub = None
            hid = str(h.getId() or "")
            for cand in infos:
                if sub is not None and cand[0] == sub:
                    info, how = cand, "subId"
                    break
                if hid and hid == str(cand[0]):
                    info, how = cand, "handleId"
                    break
            if info is None and n == 1 and len(infos) == 1:
                info, how = infos[0], "single"
            carrier = None
            if info is not None:
                slot, carrier = info[1], info[2]
                if info[3]:
                    names.append(info[3])
            if carrier:
                names.append(carrier)
            self._handles[slot] = h
            out.append({"slot": slot, "label": carrier or (names[0] if names else "SIM %d" % slot),
                        "names": [x.lower() for x in names if x]})
        out.sort(key=lambda s: s["slot"])
        return out

    def validate(self, p):
        errs = []
        if not NUM_RE.match(str(p.get("number", "")).strip()):
            errs.append("invalid phone number")
        if not str(p.get("name", "")).strip():
            errs.append("name required")
        if p.get("sim_slot") is not None and not isinstance(p["sim_slot"], int):
            errs.append("bad sim slot")
        return errs

    def preview(self, p):
        sim = (" via SIM %d" % p["sim_slot"]) if p.get("sim_slot") else ""
        return "Call: %s (%s)%s" % (p["name"], p["number"], sim)

    def execute(self, p):
        if not au.ANDROID:
            return Result("unsupported", "not running on Android")
        try:
            Uri = au.autoclass("android.net.Uri")
            uri = Uri.parse("tel:" + clean_number(p["number"]))
            if self.can_call_directly():
                tm = self._svc("TELECOM_SERVICE", "android.telecom.TelecomManager")
                extras = au.autoclass("android.os.Bundle")()
                slot = p.get("sim_slot")
                if slot:
                    if slot not in self._handles:
                        self.sims()
                    h = self._handles.get(slot)
                    if h is None:
                        return Result("failed", "SIM %d not available" % slot)
                    extras.putParcelable(EXTRA_PHONE_ACCOUNT_HANDLE, h)
                tm.placeCall(uri, extras)
                return Result("done", "call placed")
            Intent = au.autoclass("android.content.Intent")
            au.mActivity.startActivity(Intent(Intent.ACTION_DIAL, uri))
            return Result("handed_off", "dialer opened; user must tap Call")
        except Exception as ex:
            import traceback
            traceback.print_exc()
            return Result("failed", "could not start call: %s" % type(ex).__name__)
