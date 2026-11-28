"""Phone control adapter: hands an APPROVED list of steps to the "Lazey phone control"
Accessibility service (java/org/pa/assistant/PhoneControlService.java) and reads its result.
The user switches the service on in Settings > Accessibility; without it nothing runs."""
import json
import time

from . import android_util as au
from .base import Adapter, Result
from .. import control

SERVICE = "org.pa.assistant.PhoneControlService"


class AndroidControlAdapter(Adapter):
    name = "phone_control"

    def __init__(self):
        # app class: load on the main thread (pyjnius cannot find app classes from other threads)
        self._pc = None
        if au.ANDROID:
            try:
                self._pc = au.autoclass("org.pa.assistant.PhoneControl")
            except Exception:
                self._pc = None

    def capability_check(self):
        return au.ANDROID and self._pc is not None

    def permission_check(self):
        return "granted" if self.ready() else "denied"

    def ready(self):
        try:
            return bool(self._pc is not None and self._pc.enabled(au.mActivity))
        except Exception as ex:
            print("phone control check failed: %s: %s" % (type(ex).__name__, ex), flush=True)
            return False

    def validate(self, p):
        return control.validate_steps(p.get("steps"))

    def preview(self, p):
        return control.preview(p["steps"])

    def execute(self, p):
        steps = [{k: v for k, v in s.items() if k != "label"} for s in p["steps"]]
        r = str(self._pc.start(au.mActivity, json.dumps(steps)))
        if r == "started":
            return Result("handed_off", "steps running")
        return Result("denied", "phone control is off")

    def take_result(self):
        """dict from the service, {'status': 'running'}, or None."""
        if self._pc is None:
            return None
        try:
            r = self._pc.takeResult(au.mActivity)
        except Exception:
            return None
        if r is None:
            return None
        r = str(r)
        if r == "running":
            return {"status": "running"}
        try:
            return json.loads(r)
        except ValueError:
            return None

    settings_opened_at = 0.0

    def open_settings(self):
        """The Accessibility screen, at 'Lazey phone control' where the Settings app supports it."""
        self.settings_opened_at = time.time()
        try:
            Intent = au.autoclass("android.content.Intent")
            me = au.mActivity.getPackageName() + "/" + SERVICE
            try:
                it = Intent("android.settings.ACCESSIBILITY_DETAILS_SETTINGS")
                it.putExtra("android.intent.extra.COMPONENT_NAME", me)
                it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                au.mActivity.startActivity(it)
                return True
            except Exception:
                pass
            it = Intent("android.settings.ACCESSIBILITY_SETTINGS")
            it.putExtra(":settings:fragment_args_key", me)
            Bundle = au.autoclass("android.os.Bundle")
            b = Bundle()
            b.putString(":settings:fragment_args_key", me)
            it.putExtra(":settings:show_fragment_args", b)
            it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK)
            au.mActivity.startActivity(it)
            return True
        except Exception:
            return False
