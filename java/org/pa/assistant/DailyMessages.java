package org.pa.assistant;

import android.app.AlarmManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Build;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import org.json.JSONObject;

import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.util.Calendar;
import java.util.HashSet;
import java.util.Set;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/**
 * Daily messages that must run while the app (and Python) is closed.
 *
 * Each schedule is kept in app-private SharedPreferences, ENCRYPTED with an AES-256-GCM key from
 * the Android Keystore, so it survives reboots without storing names, numbers or text in plain
 * form. The alarm itself only carries the schedule id. Python calls the static methods via pyjnius.
 */
public class DailyMessages {
    static final String PREFS = "pa_daily";
    static final String ALIAS = "pa_daily_key";
    static final String ACTION = "org.pa.assistant.DAILY";
    static final String CHANNEL = "daily_messages";

    // ---------- public API (called from Python) ----------

    /** Save (or replace) a schedule and set its next alarm. Returns false if it could not be saved. */
    public static boolean save(Context ctx, int id, String channel, String number, String name,
                               String text, int hour, int minute) {
        return saveDays(ctx, id, channel, number, name, text, hour, minute, 0);
    }

    /** Like save(), only on some weekdays. days = bitmask, bit (Calendar.DAY_OF_WEEK - 1),
     *  e.g. Monday = 1 << 1; 0 means every day. */
    public static boolean saveDays(Context ctx, int id, String channel, String number, String name,
                                   String text, int hour, int minute, int days) {
        try {
            JSONObject o = new JSONObject();
            o.put("channel", channel).put("number", number).put("name", name).put("text", text)
             .put("hour", hour).put("minute", minute).put("days", days);
            store(ctx, id, o);
            setAlarm(ctx, id, hour, minute, days);
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    /** A routine reminder: at the time a notification "Routine X: tap to run" opens the app,
     *  which runs the routine (Python cannot run while the app is closed). */
    public static boolean saveRoutine(Context ctx, int id, String name, int hour, int minute, int days) {
        try {
            JSONObject o = new JSONObject();
            o.put("channel", "routine").put("name", name).put("hour", hour).put("minute", minute).put("days", days);
            store(ctx, id, o);
            setAlarm(ctx, id, hour, minute, days);
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    static void store(Context ctx, int id, JSONObject o) throws Exception {
        SharedPreferences p = prefs(ctx);
        Set<String> ids = new HashSet<>(p.getStringSet("ids", new HashSet<String>()));
        ids.add(String.valueOf(id));
        p.edit().putString("s_" + id, encrypt(o.toString())).putStringSet("ids", ids).commit();
    }

    /** One-time reminder: a notification with `text` at `atMillis` (then it removes itself). */
    public static boolean saveReminder(Context ctx, int id, String text, long atMillis) {
        try {
            JSONObject o = new JSONObject();
            o.put("channel", "reminder").put("text", text).put("at", atMillis);
            SharedPreferences p = prefs(ctx);
            Set<String> ids = new HashSet<>(p.getStringSet("ids", new HashSet<String>()));
            ids.add(String.valueOf(id));
            p.edit().putString("s_" + id, encrypt(o.toString())).putStringSet("ids", ids).commit();
            setAlarmAt(ctx, id, atMillis);
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    public static void cancel(Context ctx, int id) {
        AlarmManager am = (AlarmManager) ctx.getSystemService(Context.ALARM_SERVICE);
        PendingIntent pi = PendingIntent.getBroadcast(ctx, id, alarmIntent(ctx, id),
                PendingIntent.FLAG_NO_CREATE | PendingIntent.FLAG_IMMUTABLE);
        if (pi != null) {
            am.cancel(pi);
            pi.cancel();
        }
        SharedPreferences p = prefs(ctx);
        Set<String> ids = new HashSet<>(p.getStringSet("ids", new HashSet<String>()));
        ids.remove(String.valueOf(id));
        p.edit().remove("s_" + id).putStringSet("ids", ids).commit();
    }

    public static void cancelAll(Context ctx) {
        for (String s : new HashSet<>(prefs(ctx).getStringSet("ids", new HashSet<String>()))) {
            try {
                cancel(ctx, Integer.parseInt(s));
            } catch (NumberFormatException ignored) {
            }
        }
    }

    /** Set alarms for every saved schedule (after reboot, app update or app start). */
    public static int rescheduleAll(Context ctx) {
        int n = 0;
        // iterate over a copy: a missed reminder is removed (cancel) inside the loop
        for (String s : new HashSet<>(prefs(ctx).getStringSet("ids", new HashSet<String>()))) {
            try {
                int id = Integer.parseInt(s);
                JSONObject o = load(ctx, id);
                if (o == null) continue;
                if ("reminder".equals(o.optString("channel"))) {
                    long at = o.getLong("at");
                    if (at > System.currentTimeMillis()) {
                        setAlarmAt(ctx, id, at);
                    } else {  // phone was off at the time: show it now, once
                        DailyReceiver.showReminder(ctx, id, o.getString("text"), true);
                        cancel(ctx, id);
                    }
                } else {
                    setAlarm(ctx, id, o.getInt("hour"), o.getInt("minute"), o.optInt("days", 0));
                }
                n++;
            } catch (Exception ignored) {
            }
        }
        return n;
    }

    /** Ids saved on the Java side (Python compares them with its own encrypted records). */
    public static String[] ids(Context ctx) {
        return prefs(ctx).getStringSet("ids", new HashSet<String>()).toArray(new String[0]);
    }

    public static boolean exactAllowed(Context ctx) {
        if (Build.VERSION.SDK_INT < 31) return true;
        AlarmManager am = (AlarmManager) ctx.getSystemService(Context.ALARM_SERVICE);
        return am.canScheduleExactAlarms();
    }

    // ---------- internals ----------

    static SharedPreferences prefs(Context ctx) {
        return ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    static JSONObject load(Context ctx, int id) {
        String enc = prefs(ctx).getString("s_" + id, null);
        if (enc == null) return null;
        try {
            return new JSONObject(decrypt(enc));
        } catch (Exception e) {
            return null;
        }
    }

    static Intent alarmIntent(Context ctx, int id) {
        Intent i = new Intent(ctx, DailyReceiver.class);
        i.setAction(ACTION);
        i.setData(Uri.parse("pa-daily://" + id)); // makes each schedule's PendingIntent unique
        i.putExtra("id", id);
        return i;
    }

    /** Next hour:minute (at least 30 s from now) on an allowed weekday (days bitmask, 0 = any). */
    static long nextTime(int hour, int minute, int days) {
        Calendar now = Calendar.getInstance();
        Calendar c = (Calendar) now.clone();
        c.set(Calendar.HOUR_OF_DAY, hour);
        c.set(Calendar.MINUTE, minute);
        c.set(Calendar.SECOND, 0);
        c.set(Calendar.MILLISECOND, 0);
        for (int i = 0; i < 8; i++) {
            boolean dayOk = days == 0 || (days & (1 << (c.get(Calendar.DAY_OF_WEEK) - 1))) != 0;
            if (dayOk && c.getTimeInMillis() > now.getTimeInMillis() + 30_000L) break;
            c.add(Calendar.DAY_OF_MONTH, 1);
        }
        return c.getTimeInMillis();
    }

    static void setAlarm(Context ctx, int id, int hour, int minute) {
        setAlarm(ctx, id, hour, minute, 0);
    }

    static void setAlarm(Context ctx, int id, int hour, int minute, int days) {
        setAlarmAt(ctx, id, nextTime(hour, minute, days));
    }

    static void setAlarmAt(Context ctx, int id, long at) {
        AlarmManager am = (AlarmManager) ctx.getSystemService(Context.ALARM_SERVICE);
        PendingIntent pi = PendingIntent.getBroadcast(ctx, id, alarmIntent(ctx, id),
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        if (exactAllowed(ctx)) {
            am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi);
        } else {
            am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi); // may be a few minutes late
        }
    }

    static void notify(Context ctx, int id, String title, String body, PendingIntent tap) {
        NotificationManager nm = (NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= 26 && nm.getNotificationChannel(CHANNEL) == null) {
            nm.createNotificationChannel(new NotificationChannel(CHANNEL, "Daily messages",
                    NotificationManager.IMPORTANCE_HIGH));
        }
        int icon = ctx.getApplicationInfo().icon;
        // Lock screen shows only this neutral text, never the name or the message.
        Notification pub = new Notification.Builder(ctx, CHANNEL).setSmallIcon(icon)
                .setContentTitle("Lazey").setContentText("Daily message").build();
        Notification.Builder b = new Notification.Builder(ctx, CHANNEL)
                .setSmallIcon(icon)
                .setContentTitle(title)
                .setContentText(body)
                .setStyle(new Notification.BigTextStyle().bigText(body))
                .setVisibility(Notification.VISIBILITY_PRIVATE)
                .setPublicVersion(pub)
                .setAutoCancel(true);
        if (tap != null) b.setContentIntent(tap);
        try {
            nm.notify(id, b.build());
        } catch (SecurityException ignored) { // notification permission off
        }
    }

    // ---------- Keystore encryption ----------

    static SecretKey key() throws Exception {
        KeyStore ks = KeyStore.getInstance("AndroidKeyStore");
        ks.load(null);
        if (!ks.containsAlias(ALIAS)) {
            KeyGenerator kg = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            kg.init(new KeyGenParameterSpec.Builder(ALIAS,
                    KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setKeySize(256)
                    .build());
            kg.generateKey();
        }
        return ((KeyStore.SecretKeyEntry) ks.getEntry(ALIAS, null)).getSecretKey();
    }

    static String encrypt(String plain) throws Exception {
        Cipher c = Cipher.getInstance("AES/GCM/NoPadding");
        c.init(Cipher.ENCRYPT_MODE, key());
        byte[] ct = c.doFinal(plain.getBytes(StandardCharsets.UTF_8));
        return Base64.encodeToString(c.getIV(), Base64.NO_WRAP) + ":" + Base64.encodeToString(ct, Base64.NO_WRAP);
    }

    static String decrypt(String s) throws Exception {
        String[] parts = s.split(":", 2);
        Cipher c = Cipher.getInstance("AES/GCM/NoPadding");
        c.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, Base64.decode(parts[0], Base64.NO_WRAP)));
        return new String(c.doFinal(Base64.decode(parts[1], Base64.NO_WRAP)), StandardCharsets.UTF_8);
    }
}
