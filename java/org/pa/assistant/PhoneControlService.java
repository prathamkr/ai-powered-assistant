package org.pa.assistant;

import android.accessibilityservice.AccessibilityService;
import android.content.ActivityNotFoundException;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.graphics.Rect;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.PersistableBundle;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * "Lazey phone control": performs a list of simple steps (open app, tap, type, search, scroll,
 * back, home, read screen) that the user said and APPROVED in Lazey.
 * Safety rules:
 *  - does nothing at all unless an approved plan is running (no event is read otherwise);
 *  - a plan stops after 90 seconds, after the first failed step, or on the last step;
 *  - never types into or reads password fields;
 *  - never taps a button whose label has a "real action" word (send, pay, delete, install, ...)
 *    unless the user's own words for that step contain the same word;
 *  - never taps inside Lazey itself.
 */
public class PhoneControlService extends AccessibilityService {
    static volatile PhoneControlService instance;

    static final Pattern RISKY = Pattern.compile("\\b(send|bhejo|pay|payment|buy|order|purchase|delete|remove|"
            + "uninstall|install|confirm|submit|post|share|transfer|call|subscribe|unsubscribe|block|report|"
            + "logout|log out|sign out|erase|reset|accept|allow)\\b", Pattern.CASE_INSENSITIVE);
    static final long PLAN_MS = 90000, STEP_MS = 8000, TICK_MS = 300, GAP_MS = 700;

    private final Handler h = new Handler(Looper.getMainLooper());
    private JSONArray steps;
    private int idx, stage;
    private long planDeadline, stepStart, stepDeadline;
    private boolean running;
    private String why = "";
    private final List<String> readOut = new ArrayList<>();

    @Override
    protected void onServiceConnected() {
        super.onServiceConnected();
        instance = this;
    }

    @Override
    public boolean onUnbind(Intent intent) {
        switchedOff();
        instance = null;
        return super.onUnbind(intent);
    }

    @Override
    public void onDestroy() {
        switchedOff();
        instance = null;
        super.onDestroy();
    }

    /** Android switched the service off in the middle of a plan (on the test phone, vivo, this happens
     *  whenever the Settings app is on screen): stop and say so, never leave the plan 'running'. */
    private void switchedOff() {
        if (running) {
            stop();
            PhoneControl.finish(this, result("failed", idx,
                    "Android switched 'Lazey phone control' off (this phone does that while the Settings app is open)"));
        } else {
            stop();
        }
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        // Steps are driven by a timer while a plan runs; events are not used or stored.
    }

    @Override
    public void onInterrupt() {
    }

    void startPlan(String json) {
        h.post(() -> {
            try {
                steps = new JSONArray(json);
            } catch (JSONException e) {
                PhoneControl.finish(this, result("failed", 0, "bad plan"));
                return;
            }
            readOut.clear();
            idx = 0;
            running = true;
            planDeadline = now() + PLAN_MS;
            beginStep();
            h.postDelayed(this::tick, TICK_MS);
        });
    }

    private void stop() {
        running = false;
        h.removeCallbacksAndMessages(null);
    }

    private static long now() {
        return System.currentTimeMillis();
    }

    private void beginStep() {
        stage = 0;
        why = "";
        stepStart = now();
        JSONObject s = steps.optJSONObject(idx);
        long extra = s != null && "wait".equals(s.optString("op")) ? s.optInt("seconds", 2) * 1000L : 0;
        stepDeadline = stepStart + STEP_MS + extra + (s != null && ("search".equals(s.optString("op")) || "expect".equals(s.optString("op"))) ? 6000 : 0);
    }

    private void tick() {
        if (!running) return;
        if (now() > planDeadline) {
            end("failed", "the steps took too long");
            return;
        }
        JSONObject s = steps.optJSONObject(idx);
        if (s == null) {
            end("failed", "bad step");
            return;
        }
        int r;
        try {
            r = step(s);
        } catch (RuntimeException e) {
            r = -1;
            why = "error: " + e.getClass().getSimpleName();
        }
        if (r < 0 || (r == 0 && now() > stepDeadline)) {
            end("failed", why.isEmpty() ? "could not do it in time" : why);
            return;
        }
        if (r > 0) {
            idx++;
            if (idx >= steps.length()) {
                end("done", "");
                return;
            }
            beginStep();
            h.postDelayed(this::tick, GAP_MS);
            return;
        }
        h.postDelayed(this::tick, TICK_MS);
    }

    private void end(String status, String detail) {
        boolean hadRead = !readOut.isEmpty();
        stop();
        PhoneControl.finish(this, result(status, "done".equals(status) ? steps.length() - 1 : idx, detail));
        if (hadRead || !"done".equals(status)) {
            h.postDelayed(this::backToLazey, 600); // show what was read / what went wrong
        }
    }

    private String result(String status, int at, String detail) {
        JSONObject o = new JSONObject();
        try {
            o.put("status", status);
            o.put("step", at + 1);
            o.put("total", steps == null ? 0 : steps.length());
            o.put("detail", detail);
            o.put("read", new JSONArray(readOut));
        } catch (JSONException e) {
            // keep what we have
        }
        return o.toString();
    }

    private void backToLazey() {
        Intent li = getPackageManager().getLaunchIntentForPackage(getPackageName());
        if (li != null) {
            li.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(li);
        }
    }

    /** 1 = step finished, 0 = not yet (try again), -1 = failed (why says why). */
    private int step(JSONObject s) {
        String op = s.optString("op");
        switch (op) {
            case "home":
                return performGlobalAction(GLOBAL_ACTION_HOME) ? 1 : fail("home did not work");
            case "back":
                return performGlobalAction(GLOBAL_ACTION_BACK) ? 1 : fail("back did not work");
            case "recents":
                return performGlobalAction(GLOBAL_ACTION_RECENTS) ? 1 : fail("recent apps did not open");
            case "notifications":
                return performGlobalAction(GLOBAL_ACTION_NOTIFICATIONS) ? 1 : fail("notifications did not open");
            case "wait":
                return now() >= stepStart + s.optInt("seconds", 2) * 1000L ? 1 : 0;
            case "open":
                return open(s.optString("package"));
            case "open_url":
                return openUrl(s.optString("url"), s.optString("package"));
            default:
                break;
        }
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) return 0;
        if (getPackageName().equals(String.valueOf(root.getPackageName()))) {
            why = "Lazey was on the screen, not another app";
            return 0; // wait: the app opened in an earlier step may still be coming up
        }
        switch (op) {
            case "click":
                return click(root, s.optString("text"));
            case "type":
                return type(root, s.optString("text"));
            case "enter":
                return enter(root);
            case "search":
                return search(root, s.optString("text"));
            case "scroll":
                return scroll(root, "up".equals(s.optString("dir")));
            case "read":
                read(root);
                return 1;
            case "expect":
                return expect(root, s.optString("text"), s.optString("chat_id"));
            case "expect_sent":
                return expectSent(root, s.optString("text"));
            case "pick":
                return pick(root, s.optString("text"), s.optString("id"), s.optString("suffix"));
            default:
                return fail("unknown step");
        }
    }

    private int fail(String reason) {
        why = reason;
        return -1;
    }

    private int open(String pkg) {
        if (stage == 0) {
            Intent li = getPackageManager().getLaunchIntentForPackage(pkg);
            if (li == null) return fail("that app cannot be opened");
            li.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(li);
            stage = 1;
            return 0;
        }
        AccessibilityNodeInfo root = getRootInActiveWindow();
        why = "the app did not open";
        return root != null && pkg.equals(String.valueOf(root.getPackageName())) ? 1 : 0;
    }

    /** A chat link (ig.me/m/<user>, m.me/<user>, ...) opened in that app only, never a browser. */
    private int openUrl(String url, String pkg) {
        if (stage == 0) {
            if (!url.startsWith("https://") || pkg.isEmpty() || pkg.equals(getPackageName())) return fail("bad link");
            Intent it = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
            it.setPackage(pkg);
            it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            try {
                startActivity(it);
            } catch (ActivityNotFoundException e) {
                return fail("that app is not installed");
            }
            stage = 1;
            return 0;
        }
        AccessibilityNodeInfo root = getRootInActiveWindow();
        why = "the app did not open the chat";
        return root != null && pkg.equals(String.valueOf(root.getPackageName())) ? 1 : 0;
    }

    /** Safety check before typing a message. Passes when the username is on the screen (exact match,
     *  also "@user", so "rahul_23" never passes for "rahul_2"), or when the app's own chat text box is
     *  there (chatId, e.g. Instagram's row_thread_composer_edittext): the chat link names the user, and
     *  for an unknown user Instagram shows the inbox instead, which has no such box (seen on the phone).
     *  Tapping the chat header to find the username was tried and dropped: it opens a details page
     *  without the username once the chat has messages. */
    private int expect(AccessibilityNodeInfo root, String text, String chatId) {
        String want = norm(text).replaceFirst("^@", "");
        if (shows(root, want, false)) return 1;
        if (!chatId.isEmpty()) {
            for (AccessibilityNodeInfo n : all(root)) {
                if (n.isVisibleToUser() && n.isEditable() && norm(n.getViewIdResourceName()).endsWith("/" + chatId)) {
                    return 1;
                }
            }
        }
        why = "the chat on the screen is not with \"" + text + "\", so nothing was typed or sent";
        return 0;
    }

    /** After Send: the message must show up in the chat (not in the text box), or the plan fails —
     *  so Lazey never reports a message as sent when the app did not send it. */
    private int expectSent(AccessibilityNodeInfo root, String text) {
        if (shows(root, norm(text), true)) return 1;
        why = "the message did not show up in the chat after Send, so it may not have been sent";
        return 0;
    }

    /** Open the chat of one person from an app's chat list, by name. Names come from rows whose view id
     *  ends with `id` (LinkedIn: messaging_conversation_list_item_title) or whose description ends with
     *  `suffix` (Discord: "<name> (direct message)"). A name matches when it equals the wanted words or
     *  starts with them ("sarita" -> "Sarita Sheoran"). One match: tap it. Several: stop and report them
     *  as "CHOOSE:<a>|<b>" so Lazey can ask which one. None: stop. */
    private int pick(AccessibilityNodeInfo root, String text, String id, String suffix) {
        String want = norm(text);
        java.util.LinkedHashMap<String, AccessibilityNodeInfo> found = new java.util.LinkedHashMap<>();
        AccessibilityNodeInfo exact = null;
        for (AccessibilityNodeInfo n : all(root)) {
            if (!n.isVisibleToUser()) continue;
            String name = null;
            if (id.isEmpty() && suffix.isEmpty()) {   // any row whose label is the name (Slack, Google Chat)
                CharSequence t = n.getText() != null ? n.getText() : n.getContentDescription();
                name = t == null ? null : t.toString().split("[\\n,]")[0].trim();
            } else if (!id.isEmpty() && norm(n.getViewIdResourceName()).endsWith("/" + id)) {
                name = n.getText() == null ? null : n.getText().toString().trim();
            } else if (!suffix.isEmpty() && n.getContentDescription() != null) {
                String d = n.getContentDescription().toString().trim();
                if (d.toLowerCase(Locale.ROOT).endsWith(suffix.toLowerCase(Locale.ROOT))) {
                    name = d.substring(0, d.length() - suffix.length()).trim();
                }
            }
            if (name == null || name.isEmpty()) continue;
            String nl = norm(name);
            if (nl.equals(want) || nl.startsWith(want + " ")) {
                if (nl.equals(want) && exact == null) exact = n;
                if (!found.containsKey(nl)) found.put(nl, n);
            }
        }
        if (found.isEmpty()) {
            why = "no chat named \"" + text + "\" in the list on the screen, so nothing was sent";
            return 0;
        }
        AccessibilityNodeInfo target = exact;
        if (target == null && found.size() == 1) target = found.values().iterator().next();
        if (target == null) {
            StringBuilder b = new StringBuilder("CHOOSE:");
            int k = 0;
            for (AccessibilityNodeInfo n : found.values()) {
                String nm = n.getText() != null && (!id.isEmpty() || suffix.isEmpty()) ? n.getText().toString().split("[\\n,]")[0].trim()
                        : n.getContentDescription().toString().trim().replaceFirst("(?i)" + Pattern.quote(suffix) + "$", "").trim();
                if (k++ > 0) b.append("|");
                b.append(nm);
                if (k >= 6) break;
            }
            return fail(b.toString());
        }
        AccessibilityNodeInfo c = clickable(target);
        return c != null && c.performAction(AccessibilityNodeInfo.ACTION_CLICK) ? 1 : fail("could not open that chat");
    }

    private boolean shows(AccessibilityNodeInfo root, String want, boolean skipTextBoxes) {
        for (AccessibilityNodeInfo n : all(root)) {
            if (!n.isVisibleToUser() || (skipTextBoxes && n.isEditable())) continue;
            for (String l : new String[]{norm(n.getText()), norm(n.getContentDescription())}) {
                String v = l.replace('\u00a0', ' ').trim().replaceFirst("^@", "");
                if (v.equals(want)) return true;
            }
        }
        return false;
    }

    // ---------- finding things on the screen ----------
    private static String norm(CharSequence cs) {
        return cs == null ? "" : cs.toString().replaceAll("\\s+", " ").trim().toLowerCase(Locale.ROOT);
    }

    private static String label(AccessibilityNodeInfo n) {
        String t = norm(n.getText());
        return t.isEmpty() ? norm(n.getContentDescription()) : t;
    }

    private static List<AccessibilityNodeInfo> all(AccessibilityNodeInfo root) {
        List<AccessibilityNodeInfo> out = new ArrayList<>();
        ArrayDeque<AccessibilityNodeInfo> q = new ArrayDeque<>();
        q.add(root);
        while (!q.isEmpty() && out.size() < 3000) {
            AccessibilityNodeInfo n = q.poll();
            if (n == null) continue;
            out.add(n);
            for (int i = 0; i < n.getChildCount(); i++) {
                AccessibilityNodeInfo c = n.getChild(i);
                if (c != null) q.add(c);
            }
        }
        return out;
    }

    private static int score(String lbl, String want) {
        if (lbl.isEmpty()) return 0;
        if (lbl.equals(want)) return 4;
        if (Pattern.compile("(^|\\W)" + Pattern.quote(want) + "(\\W|$)").matcher(lbl).find()) {
            return lbl.startsWith(want) ? 3 : 2;
        }
        return lbl.contains(want) ? 1 : 0;
    }

    private static AccessibilityNodeInfo clickable(AccessibilityNodeInfo n) {
        int up = 0;
        while (n != null && !n.isClickable() && up++ < 6) n = n.getParent();
        return n;
    }

    static final Pattern NOT_SEARCH_BOX = Pattern.compile("voice|mic|camera|lens|image|photo|filter|history",
            Pattern.CASE_INSENSITIVE);

    /** "search pe click karo": the app's search box / search button, never a voice or camera search. */
    private int clickSearch(AccessibilityNodeInfo root) {
        AccessibilityNodeInfo e = editable(root);
        if (e != null && !e.isPassword()) {
            e.performAction(AccessibilityNodeInfo.ACTION_FOCUS);
            return 1; // a search box is already there
        }
        for (AccessibilityNodeInfo n : all(root)) {
            if (!n.isVisibleToUser()) continue;
            String lbl = label(n), id = norm(n.getViewIdResourceName());
            if (!(lbl.contains("search") || id.contains("search"))) continue;
            if (NOT_SEARCH_BOX.matcher(lbl).find() || NOT_SEARCH_BOX.matcher(id).find()) continue;
            AccessibilityNodeInfo c = clickable(n);
            if (c != null && c.performAction(AccessibilityNodeInfo.ACTION_CLICK)) return 1;
        }
        why = "could not find a search box";
        return 0;
    }

    private int click(AccessibilityNodeInfo root, String text) {
        String want = norm(text);
        if (want.matches("search( bar| box| button| icon)?")) return clickSearch(root);
        AccessibilityNodeInfo best = null;
        int bestScore = 0;
        for (AccessibilityNodeInfo n : all(root)) {
            if (!n.isVisibleToUser() || n.isPassword()) continue;
            int sc = score(label(n), want);
            // only the exact label or one that STARTS with the words ("rahul" -> "Rahul Sharma"); a word in
            // the middle ("search" -> "Voice search") tapped the wrong button on the phone
            if (sc >= 3 && sc > bestScore && clickable(n) != null) {
                best = n;
                bestScore = sc;
            }
        }
        if (best == null) {
            why = "could not find \"" + text + "\" on the screen";
            return 0;
        }
        Matcher m = RISKY.matcher(label(best));
        while (m.find()) {
            if (!want.contains(m.group(1).toLowerCase(Locale.ROOT))) {
                return fail("did not tap \"" + label(best) + "\": it does something for real and you did not say \""
                        + m.group(1) + "\"");
            }
        }
        AccessibilityNodeInfo c = clickable(best);
        return c.performAction(AccessibilityNodeInfo.ACTION_CLICK) ? 1 : fail("the tap did not work");
    }

    private static AccessibilityNodeInfo editable(AccessibilityNodeInfo root) {
        AccessibilityNodeInfo f = root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT);
        if (f != null && f.isEditable()) return f;
        for (AccessibilityNodeInfo n : all(root)) {
            if (n.isEditable() && n.isVisibleToUser()) return n;
        }
        return null;
    }

    private int setText(AccessibilityNodeInfo e, String text) {
        if (e.isPassword()) return fail("that is a password field, so I did not type in it");
        Bundle b = new Bundle();
        b.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text);
        return e.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, b) ? 1 : fail("typing did not work");
    }

    /** Types by PASTING, as a person would: some apps (Instagram, seen on the phone) show text set with
     *  ACTION_SET_TEXT but do not send it. Then checks the box holds exactly the text; falls back to
     *  ACTION_SET_TEXT. The message stays on the clipboard afterwards. */
    private int type(AccessibilityNodeInfo root, String text) {
        AccessibilityNodeInfo e = editable(root);
        if (e == null) {
            why = "no text box on the screen";
            return 0;
        }
        if (e.isPassword()) return fail("that is a password field, so I did not type in it");
        String want = text.replaceAll("\\s+", " ").trim();
        if (stage > 0) {
            String got = e.getText() == null ? "" : e.getText().toString().replaceAll("\\s+", " ").trim();
            if (got.equals(want)) return 1;
            if (stage == 1) {                   // paste did not work: set the text directly
                stage = 2;
                return setText(e, text) < 0 ? -1 : 0;
            }
            why = "the text box did not take the text";
            return 0;
        }
        e.performAction(AccessibilityNodeInfo.ACTION_FOCUS);
        e.performAction(AccessibilityNodeInfo.ACTION_CLICK);
        Bundle clear = new Bundle();
        clear.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, "");
        e.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, clear);
        ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
        boolean pasted = false;
        if (cm != null) {
            ClipData clip = ClipData.newPlainText("Lazey", text);
            // the message is private: keyboards must not show it or keep it in their clipboard history
            PersistableBundle extras = new PersistableBundle();
            extras.putBoolean("android.content.extra.IS_SENSITIVE", true);   // ClipDescription.EXTRA_IS_SENSITIVE (13+)
            clip.getDescription().setExtras(extras);
            cm.setPrimaryClip(clip);
            pasted = e.performAction(AccessibilityNodeInfo.ACTION_PASTE);   // returns after the app pasted
            if (Build.VERSION.SDK_INT >= 28) {
                try {
                    cm.clearPrimaryClip();   // do not leave the message in the clipboard
                } catch (Exception ignored) {
                }
            }
        }
        if (!pasted) {
            stage = 2;
            return setText(e, text) < 0 ? -1 : 0;
        }
        stage = 1;
        return 0;                               // check the box on the next tick
    }

    private int enter(AccessibilityNodeInfo root) {
        AccessibilityNodeInfo e = editable(root);
        if (e == null) {
            why = "no text box on the screen to press Enter in";
            return 0;
        }
        if (Build.VERSION.SDK_INT < 30) return fail("Enter needs Android 11 or newer");
        return e.performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_IME_ENTER.getId())
                ? 1 : fail("Enter did not work");
    }

    private int search(AccessibilityNodeInfo root, String text) {
        AccessibilityNodeInfo e = editable(root);
        if (e == null) {
            if (stage == 0) {
                // open the app's search box: a button labelled / described / named "search"
                for (AccessibilityNodeInfo n : all(root)) {
                    if (!n.isVisibleToUser()) continue;
                    String id = norm(n.getViewIdResourceName());
                    if ((label(n).contains("search") || id.contains("search"))
                            && !NOT_SEARCH_BOX.matcher(label(n)).find() && !NOT_SEARCH_BOX.matcher(id).find()) {
                        AccessibilityNodeInfo c = clickable(n);
                        if (c != null && c.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                            stage = 1;
                            break;
                        }
                    }
                }
            }
            why = "could not find a search box";
            return 0;
        }
        if (e.isPassword()) return fail("that is a password field, so I did not type in it");
        if (stage < 2) {
            if (setText(e, text) < 0) return -1;
            stage = 2;
            return 0; // press Enter on the next tick, after the app saw the text
        }
        if (Build.VERSION.SDK_INT < 30) return 1;
        e.performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_IME_ENTER.getId());
        return 1;
    }

    private int scroll(AccessibilityNodeInfo root, boolean up) {
        AccessibilityNodeInfo best = null;
        long bestArea = 0;
        Rect r = new Rect();
        for (AccessibilityNodeInfo n : all(root)) {
            if (!n.isScrollable() || !n.isVisibleToUser()) continue;
            n.getBoundsInScreen(r);
            long a = (long) r.width() * r.height();
            if (a > bestArea) {
                best = n;
                bestArea = a;
            }
        }
        if (best == null) {
            why = "nothing to scroll on this screen";
            return 0;
        }
        int act = up ? AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD : AccessibilityNodeInfo.ACTION_SCROLL_FORWARD;
        return best.performAction(act) ? 1 : fail("cannot scroll further");
    }

    private void read(AccessibilityNodeInfo root) {
        Set<String> seen = new LinkedHashSet<>();
        for (AccessibilityNodeInfo n : all(root)) {
            if (!n.isVisibleToUser() || n.isPassword()) continue;
            CharSequence t = n.getText() != null ? n.getText() : n.getContentDescription();
            if (t == null) continue;
            String s = t.toString().replaceAll("\\s+", " ").trim();
            if (s.isEmpty()) continue;
            seen.add(s.length() > 80 ? s.substring(0, 80) + "..." : s);
            if (seen.size() >= 40) break;
        }
        readOut.clear();
        readOut.addAll(seen);
    }
}
