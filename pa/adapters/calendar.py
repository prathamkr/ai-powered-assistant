"""Calendar adapter. UNVERIFIED on a real device (written against CalendarContract docs).
execute() only OPENS the system 'new event' screen; the user must tap Save there, so the
result is 'handed_off', never 'done'."""
from datetime import datetime

from .base import Adapter, Result

try:
    from jnius import autoclass  # type: ignore
    from android import mActivity  # type: ignore
    ANDROID = True
except Exception:
    ANDROID = False


class AndroidCalendarAdapter(Adapter):
    name = "calendar"

    def capability_check(self):
        return ANDROID

    def permission_check(self):
        return "not_required"  # ACTION_INSERT needs no calendar permission

    def read_permission_granted(self):
        if not ANDROID:
            return False
        try:
            from android.permissions import Permission, check_permission  # type: ignore
            return bool(check_permission(Permission.READ_CALENDAR))
        except Exception:
            return False

    def validate(self, p):
        errs = []
        try:
            s = datetime.fromisoformat(p["start_iso"])
            e = datetime.fromisoformat(p["end_iso"])
            if s.tzinfo is None or e.tzinfo is None:
                errs.append("times must be timezone-aware")
            elif e <= s:
                errs.append("end must be after start")
        except Exception:
            errs.append("bad start/end")
        if not str(p.get("title", "")).strip():
            errs.append("title required")
        return errs

    def preview(self, p):
        s = datetime.fromisoformat(p["start_iso"])
        e = datetime.fromisoformat(p["end_iso"])
        return "Calendar event: '%s' on %s, %s-%s" % (
            p["title"], s.strftime("%a %d %b %Y"), s.strftime("%H:%M"), e.strftime("%H:%M"))

    def busy(self, day, tz):
        """List of (start, end) for that day, or None if unknown (no permission / not Android)."""
        if not (ANDROID and self.read_permission_granted()):
            return None
        try:
            from datetime import time, timedelta
            Instances = autoclass("android.provider.CalendarContract$Instances")
            ContentUris = autoclass("android.content.ContentUris")
            lo = int(datetime.combine(day, time(0), tz).timestamp() * 1000)
            hi = lo + 86400000
            b = Instances.CONTENT_URI.buildUpon()
            ContentUris.appendId(b, lo)
            ContentUris.appendId(b, hi)
            cur = mActivity.getContentResolver().query(b.build(), ["begin", "end"], None, None, None)
            out = []
            while cur is not None and cur.moveToNext():
                out.append((datetime.fromtimestamp(cur.getLong(0) / 1000, tz),
                            datetime.fromtimestamp(cur.getLong(1) / 1000, tz)))
            if cur is not None:
                cur.close()
            return out
        except Exception:
            return None

    def execute(self, p):
        if not ANDROID:
            return Result("unsupported", "not running on Android")
        try:
            Intent = autoclass("android.content.Intent")
            Events = autoclass("android.provider.CalendarContract$Events")
            Bundle = autoclass("android.os.Bundle")
            s = int(datetime.fromisoformat(p["start_iso"]).timestamp() * 1000)
            e = int(datetime.fromisoformat(p["end_iso"]).timestamp() * 1000)
            # Intent.putExtra has ~25 overloads and pyjnius picked a wrong one (TypeError on
            # emulator). Bundle.putLong/putString have exactly one signature each.
            b = Bundle()
            b.putString("title", str(p["title"]))
            b.putLong("beginTime", s)
            b.putLong("endTime", e)
            it = Intent(Intent.ACTION_INSERT)
            it.setData(Events.CONTENT_URI)
            it.putExtras(b)
            mActivity.startActivity(it)
            return Result("handed_off", "system calendar screen opened; user must tap Save")
        except Exception as ex:
            import traceback
            traceback.print_exc()  # goes to logcat for diagnosis; not to the audit log
            return Result("failed", "could not open calendar: %s" % type(ex).__name__)
