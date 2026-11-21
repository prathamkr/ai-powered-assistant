package org.pa.assistant;

import android.Manifest;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.telephony.SmsManager;

import org.json.JSONObject;

import java.util.ArrayList;

/**
 * Fires at the scheduled time (app may be closed). Sets tomorrow's alarm first, then:
 *  - sms: sends the SMS automatically (needs SEND_SMS) and shows a notification;
 *  - whatsapp: shows a notification; tapping it opens WhatsApp with the text filled in and the
 *    user presses Send (WhatsApp offers no way for other apps to send on their own).
 */
public class DailyReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context ctx, Intent intent) {
        int id = intent.getIntExtra("id", -1);
        JSONObject o = DailyMessages.load(ctx, id);
        if (o == null) return; // deleted meanwhile
        if ("reminder".equals(o.optString("channel"))) {  // one-time: show it and forget it
            showReminder(ctx, id, o.optString("text"), false);
            DailyMessages.cancel(ctx, id);
            return;
        }
        try {
            int hour = o.getInt("hour"), minute = o.getInt("minute");
            // next time (tomorrow / next allowed weekday), even if sending fails below
            DailyMessages.setAlarm(ctx, id, hour, minute, o.optInt("days", 0));
            if ("routine".equals(o.optString("channel"))) {
                String name = o.getString("name");
                Intent run = new Intent(ctx, RoutineTapActivity.class);
                run.setData(Uri.parse("pa-routine://" + id));  // one PendingIntent per routine
                run.putExtra("pa_run_routine", name);
                run.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                PendingIntent tap = PendingIntent.getActivity(ctx, id, run,
                        PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
                DailyMessages.notify(ctx, id, "Routine: " + name, "Tap to run it now.", tap);
                return;
            }
            String channel = o.getString("channel"), number = o.getString("number");
            String name = o.getString("name"), text = o.getString("text");
            if ("sms".equals(channel)) {
                sendSms(ctx, id, number, name, text);
            } else {
                whatsApp(ctx, id, number, name, text);
            }
        } catch (Exception e) {
            DailyMessages.notify(ctx, id, "Daily message failed", "Open Lazey to check it.", openApp(ctx, id));
        }
    }

    static void showReminder(Context ctx, int id, String text, boolean missed) {
        DailyMessages.notify(ctx, id, missed ? "Missed reminder" : "Reminder", text, openApp(ctx, id));
    }

    static PendingIntent openApp(Context ctx, int id) {
        Intent launch = ctx.getPackageManager().getLaunchIntentForPackage(ctx.getPackageName());
        if (launch == null) return null;
        return PendingIntent.getActivity(ctx, id, launch, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    static void sendSms(Context ctx, int id, String number, String name, String text) {
        if (ctx.checkSelfPermission(Manifest.permission.SEND_SMS) != PackageManager.PERMISSION_GRANTED) {
            DailyMessages.notify(ctx, id, "Daily SMS to " + name + " NOT sent",
                    "SMS permission is off. Open Lazey and allow it.", openApp(ctx, id));
            return;
        }
        try {
            SmsManager sm = Build.VERSION.SDK_INT >= 31 ? ctx.getSystemService(SmsManager.class) : SmsManager.getDefault();
            ArrayList<String> parts = sm.divideMessage(text);
            sm.sendMultipartTextMessage(number, null, parts, null, null);
            DailyMessages.notify(ctx, id, "Daily SMS sent to " + name, text, openApp(ctx, id));
        } catch (Exception e) {
            DailyMessages.notify(ctx, id, "Daily SMS to " + name + " NOT sent",
                    "The phone could not send it (" + e.getClass().getSimpleName() + ").", openApp(ctx, id));
        }
    }

    /** WhatsApp wants the number with country code and no '+'. 10-digit numbers are taken as India (+91). */
    static String waNumber(String number) {
        String d = number.replaceAll("[^0-9]", "");
        if (d.length() == 11 && d.startsWith("0")) d = d.substring(1);
        if (d.length() == 10) d = "91" + d;
        return d;
    }

    static void whatsApp(Context ctx, int id, String number, String name, String text) {
        Uri u = Uri.parse("https://api.whatsapp.com/send?phone=" + waNumber(number) + "&text=" + Uri.encode(text));
        Intent wa = new Intent(Intent.ACTION_VIEW, u);
        wa.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        if (ctx.getPackageManager().getLaunchIntentForPackage("com.whatsapp") != null) {
            wa.setPackage("com.whatsapp");
        }
        PendingIntent tap = PendingIntent.getActivity(ctx, id, wa,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        DailyMessages.notify(ctx, id, "Send WhatsApp to " + name, text + "\n(Tap, then press Send in WhatsApp.)", tap);
    }
}
