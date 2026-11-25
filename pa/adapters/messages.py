"""Send a message now.

WhatsApp: opens the chat with the text already typed (api.whatsapp.com link). The user presses
Send in WhatsApp: WhatsApp lets no other app send on its own, and screen-automation tricks
break its terms, so they are not used.
SMS: sent by the phone with SmsManager (SEND_SMS), from the chosen SIM. Goes through the
approval card first (an SMS cannot be taken back).
"""
import re
import time

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
        # Android switches this service OFF when the app is updated or force-stopped, so an
        # "auto-send is off" reminder after an update can be real. AutoSend.enabled first asks the
        # running service itself (the stored setting read back '' in-app after Settings was opened).
        try:
            return bool(self._auto is not None and self._auto.enabled(au.mActivity))
        except Exception as ex:
            print("auto_send_ready failed: %s: %s" % (type(ex).__name__, ex), flush=True)
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

    settings_opened_at = 0.0  # time.time() when the Accessibility settings screen was last opened

    def open_accessibility_settings(self):
        # On the test phone (vivo, Android 16) opening that screen switched the service OFF while it
        # was shown, and Android switched it back ON about 10 s after leaving it (measured with adb).
        self.settings_opened_at = time.time()
        try:
            Intent = au.autoclass("android.content.Intent")
            me = au.mActivity.getPackageName() + "/org.pa.assistant.AutoSendService"
            # 1) the service's own page with its switch (Android may refuse it to normal apps)
            try:
                it = Intent("android.settings.ACCESSIBILITY_DETAILS_SETTINGS")
                it.putExtra("android.intent.extra.COMPONENT_NAME", me)
                it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                au.mActivity.startActivity(it)
                return True
            except Exception:
                pass
            # 2) the Accessibility list, scrolled to and highlighting "Lazey auto-send" where the
            #    Settings app supports it (the plain list hid it far down under "Downloaded apps")
            it = Intent("android.settings.ACCESSIBILITY_SETTINGS")
            it.putExtra(":settings:fragment_args_key", me)
            Bundle = au.autoclass("android.os.Bundle")
            b = Bundle()
            b.putString(":settings:fragment_args_key", me)
            it.putExtra(":settings:show_fragment_args", b)
            # a fresh Settings task: an old one brought back to the front ignored the highlight
            it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK)
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

    # ---- WhatsApp calls ----
    # WhatsApp adds "Voice call" / "Video call" rows to each synced contact in the phone's
    # contacts (ContactsContract.Data, these mimetypes, DATA1 = "<number>@s.whatsapp.net").
    # Opening such a row with ACTION_VIEW in WhatsApp starts the call: a normal intent, no screen
    # automation. Needs READ_CONTACTS.
    # (package, mimetype prefix): WhatsApp first, then WhatsApp Business (its own rows and prefix).
    WA_APPS = (("com.whatsapp", "vnd.android.cursor.item/vnd.com.whatsapp"),
               ("com.whatsapp.w4b", "vnd.android.cursor.item/vnd.com.whatsapp.w4b"))

    @staticmethod
    def wa_call_mime(prefix, video):
        return prefix + (".video.call" if video else ".voip.call")

    @staticmethod
    def wa_row_matches(data1, want):
        """data1 is '<country code + number>@s.whatsapp.net'; want comes from wa_number()."""
        digits = re.sub(r"\D", "", (data1 or "").split("@")[0])
        if not digits or len(want) < 7:
            return False
        return digits == want or (len(digits) >= 10 and len(want) >= 10 and digits[-10:] == want[-10:])

    def whatsapp_call(self, number, video=False):
        """'done' = WhatsApp call started. 'failed' with detail 'not_installed' when neither
        WhatsApp nor WhatsApp Business is on the phone, 'not_on_whatsapp' when the number has no
        WhatsApp call entry (not on WhatsApp, or WhatsApp has not synced it yet). Any other
        detail is the error's name."""
        if not au.ANDROID:
            return Result("unsupported", "not running on Android")
        try:
            pm = au.mActivity.getPackageManager()
            apps = [(pkg, self.wa_call_mime(prefix, video)) for pkg, prefix in self.WA_APPS
                    if pm.getLaunchIntentForPackage(pkg) is not None]
            if not apps:
                return Result("failed", "not_installed")
            Data = au.autoclass("android.provider.ContactsContract$Data")
            want = wa_number(number)
            for pkg, mime in apps:
                cur = au.mActivity.getContentResolver().query(Data.CONTENT_URI, ["_id", "data1"], "mimetype=?",
                                                              [mime], None)
                row = next((rid for rid, d1 in au.rows(cur, 2) if self.wa_row_matches(d1, want)), None)
                if row is None:
                    continue
                Intent = au.autoclass("android.content.Intent")
                Uri = au.autoclass("android.net.Uri")
                it = Intent(Intent.ACTION_VIEW)
                it.setDataAndType(Uri.parse("content://com.android.contacts/data/%s" % row), mime)
                it.setPackage(pkg)
                it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                au.mActivity.startActivity(it)
                return Result("done", "whatsapp call started")
            return Result("failed", "not_on_whatsapp")
        except Exception as ex:
            return Result("failed", type(ex).__name__)

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
