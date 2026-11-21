"""Open installed apps ("open whatsapp", "youtube kholo").

Lists apps that have a launcher icon (ACTION_MAIN + CATEGORY_LAUNCHER) and starts one with
PackageManager.getLaunchIntentForPackage. Needs no permission; on Android 11+ the manifest
<queries> entry for the launcher intent (extra_manifest.xml) makes these apps visible.
Read-only and reversible (the user just leaves the app), so no approval is asked.
"""
import time

from . import android_util as au
from .base import Adapter, Result

CACHE_SECONDS = 60  # apps can be installed while we run; don't keep the list forever


def _s(cs):
    if cs is None:
        return ""
    return cs if isinstance(cs, str) else str(cs.toString())


class AndroidAppsAdapter(Adapter):
    name = "apps"

    def __init__(self):
        self._cache, self._at = None, 0.0

    def capability_check(self):
        return au.ANDROID

    def permission_check(self):
        return "not_required"

    def list_apps(self):
        """[{label, package}] for every app with a launcher icon, except this app."""
        if self._cache is not None and time.time() - self._at < CACHE_SECONDS:
            return self._cache
        Intent = au.autoclass("android.content.Intent")
        pm = au.mActivity.getPackageManager()
        it = Intent(Intent.ACTION_MAIN)
        it.addCategory(Intent.CATEGORY_LAUNCHER)
        lst = pm.queryIntentActivities(it, 0)
        me = au.mActivity.getPackageName()
        out, seen = [], set()
        for i in range(lst.size() if lst is not None else 0):
            ri = lst.get(i)
            pkg = str(ri.activityInfo.packageName)
            if pkg == me or pkg in seen:
                continue
            seen.add(pkg)
            out.append({"label": _s(ri.loadLabel(pm)) or pkg, "package": pkg})
        out.sort(key=lambda a: a["label"].lower())
        self._cache, self._at = out, time.time()
        return out

    def open(self, package):
        if not au.ANDROID:
            return Result("unsupported", "not running on Android")
        try:
            Intent = au.autoclass("android.content.Intent")
            li = au.mActivity.getPackageManager().getLaunchIntentForPackage(package)
            if li is None:
                return Result("failed", "app cannot be opened")
            li.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            au.mActivity.startActivity(li)
            return Result("handed_off", "app opened")
        except Exception as ex:
            return Result("failed", "could not open app: %s" % type(ex).__name__)
