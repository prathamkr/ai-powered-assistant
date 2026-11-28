"""Automations that run a command or approved phone-control steps at a time (Menu > Automations).

The approval card shows WHAT will run and WHEN; approving saves a daily / weekday alarm (through the
daily-message adapter's Java side). At the time a notification "Automation: ... - tap to run" opens
the app, which runs it: Android does not let an app open other apps from the background, and phone
control needs the screen unlocked, so a tap starts it. Approved phone-control steps then run without
a second card (the user approved exactly these steps); any other command runs as if typed, so its
own checks and cards still apply.
"""
import re

from .. import control
from .base import Adapter, Result
from .daily_android import days_text

TIME_RE = re.compile(r"([01]\d|2[0-3]):[0-5]\d")


def describe(p):
    """'every day at 07:00' + what runs, for the card and the Automations screen."""
    if p.get("steps"):
        return "\n".join("%d. %s" % (i + 1, control.describe(s)) for i, s in enumerate(p["steps"]))
    return '"%s"' % p.get("command", "")


class AutomationAdapter(Adapter):
    name = "automation"

    def __init__(self, daily):
        self.daily = daily

    def capability_check(self):
        return bool(self.daily.capability_check()) and hasattr(self.daily, "set_automation")

    def permission_check(self):
        need = getattr(self.daily, "missing_permissions", lambda _c: [])("whatsapp")   # notifications
        return "denied" if need else "granted"

    def validate(self, p):
        errs = []
        if not isinstance(p.get("sched_id"), int) or not 0 < p["sched_id"] < 2 ** 31:
            errs.append("bad id")
        if not TIME_RE.fullmatch(str(p.get("time", ""))):
            errs.append("time must be HH:MM")
        days = p.get("days")
        if days is not None and (not isinstance(days, list) or not days or
                                 any(not isinstance(d, int) or not 1 <= d <= 7 for d in days)):
            errs.append("bad days")
        label = p.get("label")
        if not isinstance(label, str) or not label.strip() or len(label) > 120 or re.search(r"[\x00-\x1f]", label):
            errs.append("bad name")
        if p.get("steps") is not None:
            errs += control.validate_steps(p["steps"])
        elif not isinstance(p.get("command"), str) or not p["command"].strip() or len(p["command"]) > 300:
            errs.append("nothing to run")
        return errs

    def preview(self, p):
        return "Automation every %s at %s. At that time you get a notification; tap it and this runs:\n%s" % (
            days_text(p.get("days")), p["time"], describe(p))

    def execute(self, p):
        return self.daily.set_automation(p["sched_id"], p["label"], p["time"], p.get("days")) \
            or Result("failed", "could not save the automation")
