"""Alarms and timers in the phone's own Clock app (android.provider.AlarmClock intents).

Needs only the normal permission com.android.alarm.permission.SET_ALARM (granted at install).
EXTRA_SKIP_UI asks the Clock app to set it without opening its screen; some Clock apps still
show it. The alarm then lives in the Clock app: the user sees, changes or deletes it there.
"""
from . import android_util as au
from .base import Adapter, Result


class AndroidAlarmsAdapter(Adapter):
    name = "alarms"

    def capability_check(self):
        return au.ANDROID

    def permission_check(self):
        return "not_required"

    def _start(self, it):
        Intent = au.autoclass("android.content.Intent")
        it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        au.mActivity.startActivity(it)

    def set_alarm(self, hour, minute, label=None, days=None):
        try:
            AC = au.autoclass("android.provider.AlarmClock")
            Intent = au.autoclass("android.content.Intent")
            it = Intent(AC.ACTION_SET_ALARM)
            b = au.autoclass("android.os.Bundle")()  # Bundle setters have one signature each
            b.putInt(AC.EXTRA_HOUR, int(hour))
            b.putInt(AC.EXTRA_MINUTES, int(minute))
            b.putBoolean(AC.EXTRA_SKIP_UI, True)
            if label:
                b.putString(AC.EXTRA_MESSAGE, label)
            if days:
                ArrayList = au.autoclass("java.util.ArrayList")
                Integer = au.autoclass("java.lang.Integer")
                lst = ArrayList()
                for d in days:
                    lst.add(Integer(int(d)))
                b.putIntegerArrayList(AC.EXTRA_DAYS, lst)
            it.putExtras(b)
            self._start(it)
            return Result("handed_off", "alarm sent to the Clock app")
        except Exception as ex:
            return Result("failed", "could not set the alarm: %s" % type(ex).__name__)

    def set_timer(self, seconds, label=None):
        try:
            AC = au.autoclass("android.provider.AlarmClock")
            Intent = au.autoclass("android.content.Intent")
            it = Intent(AC.ACTION_SET_TIMER)
            b = au.autoclass("android.os.Bundle")()
            b.putInt(AC.EXTRA_LENGTH, int(seconds))
            b.putBoolean(AC.EXTRA_SKIP_UI, True)
            if label:
                b.putString(AC.EXTRA_MESSAGE, label)
            it.putExtras(b)
            self._start(it)
            return Result("handed_off", "timer sent to the Clock app")
        except Exception as ex:
            return Result("failed", "could not set the timer: %s" % type(ex).__name__)

    def show_alarms(self):
        try:
            AC = au.autoclass("android.provider.AlarmClock")
            self._start(au.autoclass("android.content.Intent")(AC.ACTION_SHOW_ALARMS))
            return Result("handed_off", "clock app opened")
        except Exception as ex:
            return Result("failed", "could not open the alarms: %s" % type(ex).__name__)
