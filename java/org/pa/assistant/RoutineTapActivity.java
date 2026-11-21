package org.pa.assistant;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Bundle;

/**
 * Target of the "Routine: X - tap to run" notification. It has no screen: it remembers which
 * routine was tapped, opens the app and closes itself. The app reads the name with take().
 *
 * Why not put the name in the app's own launch intent? The app activity is singleTask: when its
 * process was killed, Android hands the new intent to onNewIntent before Python is listening, so
 * the name was lost (seen on the phone: "current task has been brought to the front").
 */
public class RoutineTapActivity extends Activity {
    static final String PREFS = "pa_routine_tap";

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        String name = getIntent() != null ? getIntent().getStringExtra("pa_run_routine") : null;
        if (name != null) {
            getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                    .putString("name", name).putLong("at", System.currentTimeMillis()).commit();
        }
        Intent li = getPackageManager().getLaunchIntentForPackage(getPackageName());
        if (li != null) {
            li.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(li);
        }
        finish();
    }

    /** The routine tapped in the last 10 minutes, once (then forgotten), or null. */
    public static String take(Context ctx) {
        SharedPreferences p = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        String name = p.getString("name", null);
        long at = p.getLong("at", 0);
        p.edit().remove("name").remove("at").commit();
        return (name != null && System.currentTimeMillis() - at < 10 * 60 * 1000L) ? name : null;
    }
}
