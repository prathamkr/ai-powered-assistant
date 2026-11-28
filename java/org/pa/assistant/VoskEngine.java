package org.pa.assistant;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;

import org.json.JSONObject;
import org.vosk.LibVosk;
import org.vosk.LogLevel;
import org.vosk.Model;
import org.vosk.Recognizer;
import org.vosk.android.RecognitionListener;
import org.vosk.android.SpeechService;
import org.vosk.android.StorageService;

import java.io.IOException;

/**
 * Lazey's built-in voice pack: the Vosk speech engine (Apache-2.0) with the small Indian English
 * model (vosk-model-small-en-in-0.4, Apache-2.0) shipped inside the APK as assets/model-en-in.
 * Everything runs on the phone; audio never leaves it (the app has no INTERNET permission).
 *
 * The model is copied once from the APK to the app's files folder (again only when the model's
 * uuid changes), then loaded. Python (pa/adapters/voice_android.py) calls the static methods and
 * gets events back through {@link Listener} on the main thread:
 *   loaded | load_error   (model)
 *   ready | partial | final | nospeech | error   (one listening turn)
 * A turn ends by itself after the first sentence (Vosk's end-of-speech detection), after ~5 s of
 * silence, after {@link #MAX_MS}, or when stop() is called (the user tapped the mic again).
 */
public class VoskEngine {
    public interface Listener {
        void onEvent(String kind, String value);
    }

    private static final String TAG = "LazeyVosk";
    private static final String ASSET = "model-en-in";
    private static final String TARGET = "model-en-in";
    private static final float RATE = 16000.0f;
    private static final int MAX_MS = 15000;

    private static Model model;
    private static String state = "none";   // none | loading | ready | error
    private static String loadError = "";
    private static Listener loadListener;

    private static SpeechService service;
    private static Recognizer recognizer;
    private static int turn = 0;             // callbacks from an older turn are ignored
    private static String lastPartial = "";

    private static final Handler MAIN = new Handler(Looper.getMainLooper());

    public static synchronized String state() {
        return state;
    }

    public static synchronized String loadError() {
        return loadError;
    }

    /** Copy (first time) and load the model in the background. Safe to call more than once. */
    public static synchronized void load(Context ctx, Listener l) {
        loadListener = l;
        if (state.equals("loading") || state.equals("ready")) {
            if (state.equals("ready")) post(l, "loaded", "");
            return;
        }
        state = "loading";
        try {
            LibVosk.setLogLevel(LogLevel.WARNINGS);
        } catch (Throwable t) {
            Log.w(TAG, "log level: " + t);
        }
        try {
            StorageService.unpack(ctx.getApplicationContext(), ASSET, TARGET,
                    (Model m) -> loaded(m, null),
                    (IOException e) -> loaded(null, "copy: " + e.getMessage()));
        } catch (Throwable t) {
            loaded(null, t.toString());
        }
    }

    private static void loaded(Model m, String err) {
        Listener l;
        synchronized (VoskEngine.class) {
            if (m != null) {
                model = m;
                state = "ready";
                loadError = "";
            } else {
                state = "error";
                loadError = err == null ? "unknown" : err;
            }
            l = loadListener;
        }
        Log.i(TAG, "model " + (m != null ? "ready" : "failed: " + err));
        post(l, m != null ? "loaded" : "load_error", m != null ? "" : loadError);
    }

    /** Start one listening turn. Events go to l. Returns false (and sends "error") if it cannot start. */
    public static synchronized boolean start(final Listener l) {
        stopService(true);
        if (model == null) {
            post(l, "error", state.equals("error") ? "load:" + loadError : "loading");
            return false;
        }
        final int my = ++turn;
        lastPartial = "";
        try {
            recognizer = new Recognizer(model, RATE);
            try {
                // wait for up to 5 s of silence before the first word, and end the sentence only after
                // 1.2 s of silence (the model's own 0.5 s cut people off at a short pause:
                // "send hi ... to rahul on whatsapp" came out as "hi up" on the phone), 15 s at most
                recognizer.setEndpointerDelays(5.0f, 1.2f, 15.0f);
            } catch (Throwable t) {
                Log.w(TAG, "endpointer: " + t);
            }
            service = new SpeechService(recognizer, RATE);
        } catch (Throwable t) {
            stopService(true);
            post(l, "error", "mic:" + t.getMessage());
            return false;
        }
        service.startListening(new RecognitionListener() {
            @Override
            public void onPartialResult(String hyp) {
                String t = text(hyp, "partial");
                if (!t.isEmpty() && current(my)) {
                    lastPartial = t;
                    l.onEvent("partial", t);
                }
            }

            @Override
            public void onResult(String hyp) {
                String t = text(hyp, "text");
                if (!t.isEmpty()) {
                    finish(my, l, "final", t);   // first sentence heard: this turn is done
                } else if (lastPartial.isEmpty()) {
                    finish(my, l, "nospeech", "");   // only silence so far (Vosk waits ~5 s for speech)
                } else if (current(my)) {
                    lastPartial = "";   // a noise that came to nothing: keep listening
                }
            }

            @Override
            public void onFinalResult(String hyp) {   // after stop(): what was heard so far
                String t = text(hyp, "text");
                if (t.isEmpty()) t = lastPartial;
                finish(my, l, t.isEmpty() ? "nospeech" : "final", t);
            }

            @Override
            public void onError(Exception e) {
                finish(my, l, "error", "mic:" + e.getMessage());
            }

            @Override
            public void onTimeout() {   // MAX_MS reached while the person was still talking
                finish(my, l, lastPartial.isEmpty() ? "nospeech" : "final", lastPartial);
            }
        }, MAX_MS);
        post(l, "ready", "");
        return true;
    }

    /** The user tapped the mic again: stop recording; the words heard so far come as "final". */
    public static synchronized void stop() {
        if (service != null) {
            service.stop();   // Vosk then calls onFinalResult on the main thread
        }
    }

    /** Throw the turn away (app going to the background, user cancelled): no more events. */
    public static synchronized void cancel() {
        turn++;
        stopService(true);
    }

    public static synchronized boolean listening() {
        return service != null;
    }

    private static synchronized boolean current(int my) {
        return my == turn;
    }

    private static void finish(int my, Listener l, String kind, String value) {
        synchronized (VoskEngine.class) {
            if (my != turn) return;   // already finished or cancelled
            turn++;
            stopService(true);
        }
        l.onEvent(kind, value);
    }

    private static void stopService(boolean cancel) {
        if (service != null) {
            try {
                if (cancel) service.cancel();
                service.shutdown();
            } catch (Throwable t) {
                Log.w(TAG, "stop: " + t);
            }
            service = null;
        }
        if (recognizer != null) {
            try {
                recognizer.close();
            } catch (Throwable t) {
                Log.w(TAG, "close: " + t);
            }
            recognizer = null;
        }
    }

    private static String text(String json, String key) {
        try {
            return new JSONObject(json).optString(key, "").trim();
        } catch (Exception e) {
            return "";
        }
    }

    private static void post(final Listener l, final String kind, final String value) {
        if (l == null) return;
        MAIN.post(() -> l.onEvent(kind, value));
    }
}
