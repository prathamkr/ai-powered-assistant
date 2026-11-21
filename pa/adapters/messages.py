"""Send a message now.

WhatsApp: opens the chat with the text already typed (api.whatsapp.com link). The user presses
Send in WhatsApp: WhatsApp lets no other app send on its own, and screen-automation tricks
break its terms, so they are not used.
SMS: sent by the phone with SmsManager (SEND_SMS), from the chosen SIM. Goes through the
approval card first (an SMS cannot be taken back).
"""
import re

from . import android_util as au
from .base import Adapter, Result

SEND_SMS = "android.permission.SEND_SMS"
NUM_RE = re.compile(r"^\+?[0-9][0-9 ()\-]{2,19}$")
MAX_TEXT = 1000


def wa_number(number):
    """WhatsApp wants the country code and no '+'. 10-digit numbers are taken as India (+91)."""
    d = re.sub(r"\D", "", number or "")
    if len(d) == 11 and d.startswith("0"):
        d = d[1:]
    if len(d) == 10:
        d = "91" + d
    return d


def validate_sms(p):
    errs = []
    if not NUM_RE.match(str(p.get("number", "")).strip()):
        errs.append("invalid phone number")
    if not str(p.get("name", "")).strip():
        errs.append("name required")
    text = str(p.get("text", ""))
    if not text.strip() or len(text) > MAX_TEXT:
        errs.append("message must be 1-%d characters" % MAX_TEXT)
    if p.get("sim_slot") is not None and p["sim_slot"] not in (1, 2):
        errs.append("bad sim slot")
    return errs


def preview_sms(p):
    sim = (" from SIM %d (%s)" % (p["sim_slot"], p.get("sim_label") or "")) if p.get("sim_slot") else ""
    return 'Send SMS to %s (%s)%s: "%s"' % (p["name"], p["number"], sim, p["text"])


class AndroidMessagesAdapter(Adapter):
    name = "sms_message"
    ARM_MS = 20000  # auto-send acts only this long after we opened the chat

    def __init__(self):
        # app class: load on the main thread (pyjnius cannot find app classes from other threads)
        self._auto = None
        if au.ANDROID:
            try:
                self._auto = au.autoclass("org.pa.assistant.AutoSend")
            except Exception:
                self._auto = None

    # ---- WhatsApp auto-send (Accessibility service, user switches it on) ----
    def auto_send_ready(self):
        try:
            return bool(self._auto is not None and self._auto.enabled(au.mActivity))
        except Exception:
            return False

    def arm_auto_send(self, text):
        self._auto.arm(au.mActivity, text, self.ARM_MS)

    def take_auto_send_result(self):
        if self._auto is None:
            return None
        try:
            r = self._auto.takeResult(au.mActivity)
            return str(r) if r is not None else None
        except Exception:
            return None

    def open_accessibility_settings(self):
        try:
            Intent = au.autoclass("android.content.Intent")
            it = Intent("android.settings.ACCESSIBILITY_SETTINGS")
            it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            au.mActivity.startActivity(it)
            return True
        except Exception:
            return False

    def capability_check(self):
        return au.ANDROID

    def permission_check(self):
        return "granted" if au.granted(SEND_SMS) else "denied"

    def required_permissions(self):
        return [SEND_SMS]

    def validate(self, p):
        return validate_sms(p)

    def preview(self, p):
        return preview_sms(p)

    def execute(self, p):
        """Hand the SMS to the phone. 'done' = accepted for sending (delivery is not confirmed)."""
        try:
            SmsManager = au.autoclass("android.telephony.SmsManager")
            sm = None
            if p.get("sim_slot"):
                from jnius import cast  # type: ignore
                Context = au.autoclass("android.content.Context")
                subs = cast("android.telephony.SubscriptionManager",
                            au.mActivity.getSystemService(Context.TELEPHONY_SUBSCRIPTION_SERVICE))
                info = subs.getActiveSubscriptionInfoForSimSlotIndex(int(p["sim_slot"]) - 1)
                if info is None:
                    return Result("failed", "SIM %d not available" % p["sim_slot"])
                sm = SmsManager.getSmsManagerForSubscriptionId(info.getSubscriptionId())
            if sm is None:
                sm = SmsManager.getDefault()
            number = re.sub(r"[^\d+]", "", p["number"])
            parts = sm.divideMessage(p["text"])
            sm.sendMultipartTextMessage(number, None, parts, None, None)
            return Result("done", "sms handed to the phone")
        except Exception as ex:
            return Result("failed", "could not send SMS: %s" % type(ex).__name__)

    def open_whatsapp(self, number, text):
        if not au.ANDROID:
            return Result("unsupported", "not running on Android")
        try:
            Intent = au.autoclass("android.content.Intent")
            Uri = au.autoclass("android.net.Uri")
            uri = Uri.parse("https://api.whatsapp.com/send?phone=%s&text=%s" % (wa_number(number), Uri.encode(text)))
            it = Intent(Intent.ACTION_VIEW, uri)
            it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            if au.mActivity.getPackageManager().getLaunchIntentForPackage("com.whatsapp") is not None:
                it.setPackage("com.whatsapp")
            au.mActivity.startActivity(it)
            return Result("handed_off", "whatsapp chat opened")
        except Exception as ex:
            return Result("failed", "could not open WhatsApp: %s" % type(ex).__name__)
