package org.pa.assistant;

import android.accessibilityservice.AccessibilityServiceInfo;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.pm.ServiceInfo;
import android.provider.Settings;
import android.view.accessibility.AccessibilityManager;

import java.util.List;

/**
 * Python-facing side of PhoneControlService ("Lazey phone control").
 * Python calls start() only after the user tapped Approve on the exact list of steps; the service
 * runs them and stores one result, which Python reads with takeResult() when Lazey is back.
 */
public class PhoneControl {
    static final String PREFS = "pa_phone_control";

    /** 'started', or 'service_off' when the user has not switched the service on. */
    public static String start(Context ctx, String stepsJson) {
        PhoneControlService s = PhoneControlService.instance;
        if (s == null) return "service_off";
        prefs(ctx).edit().remove("result").putBoolean("running", true).commit();
        s.startPlan(stepsJson);
        return "started";
    }

    /** JSON result of the last plan, 'running', or null (nothing to report). Read once. */
    public static String takeResult(Context ctx) {
        SharedPreferences p = prefs(ctx);
        String r = p.getString("result", null);
        if (r != null) {
            p.edit().remove("result").commit();
            return r;
        }
        return p.getBoolean("running", false) ? "running" : null;
    }

    static void finish(Context ctx, String resultJson) {
        prefs(ctx).edit().putBoolean("running", false).putString("result", resultJson).commit();
    }

    /** True when the user has switched "Lazey phone control" on in Settings > Accessibility. */
    public static boolean enabled(Context ctx) {
        if (PhoneControlService.instance != null) return true;
        String me = ctx.getPackageName() + "/" + PhoneControlService.class.getName();
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
                        && PhoneControlService.class.getName().equals(s.name)) return true;
            }
        } catch (RuntimeException e) {
            // treat as off
        }
        return false;
    }

    static SharedPreferences prefs(Context ctx) {
        return ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }
}
