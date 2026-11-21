package org.pa.assistant;

import android.accessibilityservice.AccessibilityServiceInfo;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.pm.ServiceInfo;
import android.provider.Settings;
import android.view.accessibility.AccessibilityManager;

import java.util.List;

/**
 * "Armed" state for AutoSendService. Python arms it right before opening a WhatsApp chat with the
 * message typed; the service presses Send only while armed (a few seconds) and only if WhatsApp's
 * text box holds exactly that message. The text is kept only until it is sent or expires.
 */
public class AutoSend {
    static final String PREFS = "pa_autosend";

    public static void arm(Context ctx, String text, long millis) {
        prefs(ctx).edit().putString("text", text).putLong("until", System.currentTimeMillis() + millis)
                .remove("result").commit();
    }

    static boolean armed(Context ctx) {
        return prefs(ctx).getLong("until", 0) > System.currentTimeMillis();
    }

    static String text(Context ctx) {
        return prefs(ctx).getString("text", null);
    }

    static void finish(Context ctx, String result) {
        prefs(ctx).edit().remove("text").remove("until").putString("result", result).commit();
    }

    /** 'sent', 'click_failed', 'waiting' (still armed), 'timeout' (expired), or null (nothing pending). */
    public static String takeResult(Context ctx) {
        SharedPreferences p = prefs(ctx);
        String r = p.getString("result", null);
        if (r != null) {
            p.edit().remove("result").commit();
            return r;
        }
        if (p.getString("text", null) == null) return null;
        if (armed(ctx)) return "waiting";
        p.edit().remove("text").remove("until").commit();
        return "timeout";
    }

    /** True when the user has switched the service on in Settings > Accessibility. First asks the
     *  service itself (connected), then the stored setting and the AccessibilityManager: on the test
     *  phone the stored setting read back '' inside the app after the Accessibility settings screen
     *  had been opened, while the service was on. */
    public static boolean enabled(Context ctx) {
        if (AutoSendService.connected) return true;
        String me = ctx.getPackageName() + "/" + AutoSendService.class.getName();
        String on = Settings.Secure.getString(ctx.getContentResolver(), Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES);
        if (on != null && on.contains(me)) return true;
        try {
            AccessibilityManager am = (AccessibilityManager) ctx.getSystemService(Context.ACCESSIBILITY_SERVICE);
            if (am == null) return false;
            List<AccessibilityServiceInfo> list =
                    am.getEnabledAccessibilityServiceList(AccessibilityServiceInfo.FEEDBACK_ALL_MASK);
            if (list == null) return false;
            for (AccessibilityServiceInfo i : list) {
                ServiceInfo s = i.getResolveInfo() != null ? i.getResolveInfo().serviceInfo : null;
                if (s != null && ctx.getPackageName().equals(s.packageName)
                        && AutoSendService.class.getName().equals(s.name)) return true;
            }
        } catch (RuntimeException e) {
            // fall through: treat as off
        }
        return false;
    }

    static SharedPreferences prefs(Context ctx) {
        return ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }
}
