"""Phone status without leaving the app: battery, storage, device, screen, network, time.

Ported to Python/pyjnius from PokeClaw's GetDeviceInfoTool.java
(https://github.com/agents-io/PokeClaw, Copyright 2026 agents.io, Apache License 2.0).
Changes: rewritten in Python; WiFi network name and Bluetooth device names left out (they need
location / nearby-devices permissions); next-alarm and free-memory readings added.
Everything is read on the phone; nothing goes to the internet.
"""
from . import android_util as au
from .base import Adapter

CATEGORIES = ("battery", "storage", "device", "screen", "network", "time", "alarm", "memory")


def fmt_bytes(n):
    return "%.1f GB" % (n / 1e9) if n >= 1e9 else "%.0f MB" % (n / 1e6)


class AndroidDeviceInfoAdapter(Adapter):
    name = "device_info"

    def capability_check(self):
        return au.ANDROID

    def permission_check(self):
        return "not_required"

    def _svc(self, name):
        Context = au.autoclass("android.content.Context")
        return au.mActivity.getSystemService(getattr(Context, name))

    def get(self, category):
        """dict of facts for one category (raises on unknown category)."""
        return getattr(self, "_" + category)()

    def _battery(self):
        from jnius import cast  # type: ignore
        BM = au.autoclass("android.os.BatteryManager")
        bm = cast("android.os.BatteryManager", self._svc("BATTERY_SERVICE"))
        level = int(bm.getIntProperty(BM.BATTERY_PROPERTY_CAPACITY))
        status = int(bm.getIntProperty(BM.BATTERY_PROPERTY_STATUS))
        charging = status in (BM.BATTERY_STATUS_CHARGING, BM.BATTERY_STATUS_FULL)
        Intent, IF = au.autoclass("android.content.Intent"), au.autoclass("android.content.IntentFilter")
        sticky = au.mActivity.registerReceiver(None, IF(Intent.ACTION_BATTERY_CHANGED))
        temp = (sticky.getIntExtra(BM.EXTRA_TEMPERATURE, 0) / 10.0) if sticky is not None else 0
        return {"level": level, "charging": bool(charging), "temp_c": temp or None}

    def _storage(self):
        Env, StatFs = au.autoclass("android.os.Environment"), au.autoclass("android.os.StatFs")
        st = StatFs(Env.getDataDirectory().getAbsolutePath())
        total, free = int(st.getTotalBytes()), int(st.getAvailableBytes())
        return {"total": total, "free": free, "used_pct": int((total - free) * 100 / total) if total else 0}

    def _memory(self):
        from jnius import cast  # type: ignore
        am = cast("android.app.ActivityManager", self._svc("ACTIVITY_SERVICE"))
        mi = au.autoclass("android.app.ActivityManager$MemoryInfo")()
        am.getMemoryInfo(mi)
        return {"total": int(mi.totalMem), "free": int(mi.availMem), "low": bool(mi.lowMemory)}

    def _device(self):
        B, V = au.autoclass("android.os.Build"), au.autoclass("android.os.Build$VERSION")
        return {"android": str(V.RELEASE), "api": int(V.SDK_INT), "maker": str(B.MANUFACTURER),
                "model": str(B.MODEL), "patch": str(V.SECURITY_PATCH or "")}

    def _screen(self):
        S = au.autoclass("android.provider.Settings$System")
        cr = au.mActivity.getContentResolver()
        try:
            bright = int(S.getInt(cr, S.SCREEN_BRIGHTNESS)) * 100 // 255
        except Exception:
            bright = None
        try:
            auto = int(S.getInt(cr, S.SCREEN_BRIGHTNESS_MODE)) == 1
        except Exception:
            auto = None
        Conf = au.autoclass("android.content.res.Configuration")
        mode = au.mActivity.getResources().getConfiguration().uiMode & Conf.UI_MODE_NIGHT_MASK
        return {"brightness_pct": bright, "auto": auto, "dark": mode == Conf.UI_MODE_NIGHT_YES}

    def _network(self):
        from jnius import cast  # type: ignore
        cm = cast("android.net.ConnectivityManager", self._svc("CONNECTIVITY_SERVICE"))
        NC = au.autoclass("android.net.NetworkCapabilities")
        net = cm.getActiveNetwork()
        caps = cm.getNetworkCapabilities(net) if net is not None else None
        if caps is None:
            return {"online": False, "type": None}
        kind = ("wifi" if caps.hasTransport(NC.TRANSPORT_WIFI) else
                "mobile data" if caps.hasTransport(NC.TRANSPORT_CELLULAR) else "other")
        return {"online": True, "type": kind}

    def _time(self):
        import datetime
        now = datetime.datetime.now().astimezone()
        return {"now": now}

    def _alarm(self):
        """Next alarm set in the Clock app (AlarmManager.getNextAlarmClock)."""
        from jnius import cast  # type: ignore
        am = cast("android.app.AlarmManager", self._svc("ALARM_SERVICE"))
        nxt = am.getNextAlarmClock()
        return {"next_ms": int(nxt.getTriggerTime()) if nxt is not None else None}
