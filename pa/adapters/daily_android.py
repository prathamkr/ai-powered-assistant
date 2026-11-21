"""Daily messages: Python side of java/org/pa/assistant/DailyMessages.java.

Creating a schedule goes through the approval card. After approval the Java side stores it
encrypted (Android Keystore) and sets an alarm that fires even when the app is closed:
  sms      -> sent automatically by the phone (SEND_SMS),
  whatsapp -> a notification; tap opens WhatsApp with the text typed, the user presses Send.
"""
import re

from . import android_util as au
from .base import Adapter, Result

SEND_SMS = "android.permission.SEND_SMS"
POST_NOTIFICATIONS = "android.permission.POST_NOTIFICATIONS"
CHANNELS = {"sms": "SMS (sent automatically)", "whatsapp": "WhatsApp (you tap Send)"}
NUM_RE = re.compile(r"^\+?[0-9][0-9 ()\-]{6,19}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
MAX_TEXT = 500


def needed_permissions(channel, granted=None, sdk=None):
    """Android permissions still missing for this channel."""
    granted = granted or au.granted
    sdk = au.sdk_int() if sdk is None else sdk
    out = []
    if channel == "sms" and not granted(SEND_SMS):
        out.append(SEND_SMS)
    if sdk >= 33 and not granted(POST_NOTIFICATIONS):
        out.append(POST_NOTIFICATIONS)
    return out


def validate_payload(p):
    errs = []
    if not isinstance(p.get("sched_id"), int) or not 0 < p["sched_id"] < 2 ** 31:
        errs.append("bad schedule id")
    if p.get("channel") not in CHANNELS:
        errs.append("channel must be sms or whatsapp")
    if not NUM_RE.match(str(p.get("number", "")).strip()):
        errs.append("invalid phone number")
    if not str(p.get("name", "")).strip():
        errs.append("name required")
    text = str(p.get("text", ""))
    if not text.strip() or len(text) > MAX_TEXT:
        errs.append("message must be 1-%d characters" % MAX_TEXT)
    if not TIME_RE.match(str(p.get("time", ""))):
        errs.append("time must be HH:MM")
    if p.get("days") is not None and (not isinstance(p["days"], list) or not p["days"]
                                      or any(not isinstance(d, int) or not 1 <= d <= 7 for d in p["days"])):
        errs.append("days must be weekday numbers 1-7")
    return errs


DAY_NAMES = {1: "Sunday", 2: "Monday", 3: "Tuesday", 4: "Wednesday", 5: "Thursday", 6: "Friday", 7: "Saturday"}


def days_text(days):
    """[2,3,4,5,6] -> 'weekdays'; None/all -> 'day'; else 'Monday, Friday'."""
    days = sorted(set(days or []))
    if not days or len(days) == 7:
        return "day"
    if days == [2, 3, 4, 5, 6]:
        return "weekday (Mon-Fri)"
    if days == [1, 7]:
        return "weekend day"
    return ", ".join(DAY_NAMES[d] for d in days)


def days_mask(days):
    """Calendar weekday numbers (1=Sunday..7=Saturday) -> Java bitmask; 0 = every day."""
    days = set(days or [])
    return 0 if not days or len(days) == 7 else sum(1 << (d - 1) for d in days)


def preview_payload(p):
    return 'Every %s at %s, %s to %s (%s): "%s"' % (
        days_text(p.get("days")), p["time"], CHANNELS[p["channel"]], p["name"], p["number"], p["text"])


class AndroidDailyAdapter(Adapter):
    name = "daily_message"

    def __init__(self):
        # Load our own Java class NOW (bootstrap runs on the main thread). From a background
        # thread pyjnius only sees Android's classes, not the app's, and autoclass fails with
        # ClassNotFoundException (seen on the phone as "JavaException" at startup).
        self._cls = self._tap = None
        if au.ANDROID:
            try:
                self._cls = au.autoclass("org.pa.assistant.DailyMessages")
                self._tap = au.autoclass("org.pa.assistant.RoutineTapActivity")
            except Exception:
                self._cls = None

    def take_routine_tap(self):
        """Name of the routine whose notification was just tapped (once), or None."""
        try:
            r = self._tap.take(au.mActivity) if self._tap is not None else None
            return str(r) if r is not None else None
        except Exception:
            return None

    def _java(self):
        if self._cls is None:
            raise RuntimeError("DailyMessages Java class not available")
        return self._cls

    def capability_check(self):
        return au.ANDROID and self._cls is not None

    def permission_check(self):
        return "not_required"  # checked per channel before the proposal (missing_permissions)

    def missing_permissions(self, channel):
        return needed_permissions(channel)

    def validate(self, p):
        return validate_payload(p)

    def preview(self, p):
        return preview_payload(p)

    def execute(self, p):
        if needed_permissions(p["channel"]):
            return Result("denied", "permission missing")
        h, m = (int(x) for x in p["time"].split(":"))
        ok = self._java().saveDays(au.mActivity, p["sched_id"], p["channel"], p["number"], p["name"],
                                   p["text"], h, m, days_mask(p.get("days")))
        return Result("done", "scheduled") if ok else Result("failed", "could not save the schedule")

    def set_routine_trigger(self, sched_id, name, time, days=None):
        """At the time: a notification 'Routine X: tap to run' (opens the app, which runs it)."""
        if needed_permissions("whatsapp"):  # notification permission
            return Result("denied", "notification permission missing")
        h, m = (int(x) for x in time.split(":"))
        ok = self._java().saveRoutine(au.mActivity, int(sched_id), name, h, m, days_mask(days))
        return Result("done", "routine scheduled") if ok else Result("failed", "could not schedule the routine")

    def set_reminder(self, rid, text, at_ms):
        """One-time notification at at_ms (epoch milliseconds)."""
        if needed_permissions("whatsapp"):  # only the notification permission matters here
            return Result("denied", "notification permission missing")
        ok = self._java().saveReminder(au.mActivity, int(rid), str(text), int(at_ms))
        return Result("done", "reminder set") if ok else Result("failed", "could not save the reminder")

    def cancel(self, sched_id):
        self._java().cancel(au.mActivity, int(sched_id))

    def cancel_all(self):
        self._java().cancelAll(au.mActivity)

    def java_ids(self):
        return {int(x) for x in self._java().ids(au.mActivity)}

    def reschedule_all(self):
        return int(self._java().rescheduleAll(au.mActivity))

    def exact_allowed(self):
        return bool(self._java().exactAllowed(au.mActivity))

    # Battery: on the vivo test phone the system "froze" the app after the first message and
    # REMOVED the next day's alarm (dumpsys alarm: Reason=frozen). With the standard
    # battery-optimization exemption the alarms survived. So we ask the user for it.
    def battery_exempt(self):
        if not au.ANDROID:
            return True
        try:
            Context = au.autoclass("android.content.Context")
            pm = au.mActivity.getSystemService(Context.POWER_SERVICE)
            return bool(pm.isIgnoringBatteryOptimizations(au.mActivity.getPackageName()))
        except Exception:
            return True  # cannot tell: don't nag

    def request_battery_exemption(self):
        """Opens Android's 'Let app always run in background?' dialog; the user decides."""
        try:
            Intent = au.autoclass("android.content.Intent")
            Uri = au.autoclass("android.net.Uri")
            it = Intent("android.settings.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS",
                        Uri.parse("package:" + au.mActivity.getPackageName()))
            au.mActivity.startActivity(it)
            return True
        except Exception:
            return False
