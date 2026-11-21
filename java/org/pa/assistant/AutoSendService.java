package org.pa.assistant;

import android.accessibilityservice.AccessibilityService;
import android.content.Intent;
import android.os.Handler;
import android.os.Looper;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import java.util.List;

/**
 * Presses WhatsApp's Send button for a message Lazey just opened (the user asked for
 * this instead of tapping Send). Safety rules:
 *  - acts only while AutoSend is armed (set a few seconds before the chat was opened);
 *  - acts only if WhatsApp's text box contains exactly the armed message;
 *  - presses once, disarms, then brings Lazey back. Reads no other screen content.
 * Only WhatsApp packages are delivered to this service (res/xml/autosend_service.xml).
 */
public class AutoSendService extends AccessibilityService {
    /** True while Android has this service connected (it runs in the app's own process). The most
     *  direct answer to "is auto-send on?": on the test phone, after the Accessibility settings
     *  screen had been opened, the app's view of the stored setting read back '' for a while
     *  although the service was on and bound. */
    static volatile boolean connected = false;

    @Override
    protected void onServiceConnected() {
        super.onServiceConnected();
        connected = true;
    }

    @Override
    public boolean onUnbind(Intent intent) {
        connected = false;
        return super.onUnbind(intent);
    }

    @Override
    public void onDestroy() {
        connected = false;
        super.onDestroy();
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        if (!AutoSend.armed(this)) return;
        String want = AutoSend.text(this);
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (want == null || root == null) return;
        String pkg = String.valueOf(root.getPackageName());
        if (!pkg.startsWith("com.whatsapp")) return;

        AccessibilityNodeInfo entry = first(root.findAccessibilityNodeInfosByViewId(pkg + ":id/entry"));
        if (entry == null || entry.getText() == null) return;
        if (!norm(entry.getText().toString()).equals(norm(want))) return; // not our message: do nothing

        AccessibilityNodeInfo send = first(root.findAccessibilityNodeInfosByViewId(pkg + ":id/send"));
        if (send == null) send = byDescription(root, "Send");
        while (send != null && !send.isClickable()) send = send.getParent();
        if (send == null) return; // wait for the next window event

        AutoSend.finish(this, "pending");
        boolean ok = send.performAction(AccessibilityNodeInfo.ACTION_CLICK);
        AutoSend.finish(this, ok ? "sent" : "click_failed");
        if (ok) {
            new Handler(Looper.getMainLooper()).postDelayed(this::backToAssistant, 800);
        }
    }

    private void backToAssistant() {
        Intent li = getPackageManager().getLaunchIntentForPackage(getPackageName());
        if (li != null) {
            li.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(li);
        }
    }

    private static String norm(String s) {
        return s.replaceAll("\\s+", " ").trim();
    }

    private static AccessibilityNodeInfo first(List<AccessibilityNodeInfo> l) {
        return (l == null || l.isEmpty()) ? null : l.get(0);
    }

    private static AccessibilityNodeInfo byDescription(AccessibilityNodeInfo root, String desc) {
        List<AccessibilityNodeInfo> l = root.findAccessibilityNodeInfosByText(desc);
        if (l == null) return null;
        for (AccessibilityNodeInfo n : l) {
            CharSequence d = n.getContentDescription();
            if (d != null && d.toString().equalsIgnoreCase(desc)) return n;
        }
        return null;
    }

    @Override
    public void onInterrupt() {
    }
}
