"""Voice on Android with the phone's own engines (the "Android fallback" path of the
PocketMind Voice branch, rewritten in Python/pyjnius):

  Listener: android.speech.SpeechRecognizer. The on-device recognizer is used when the phone
  has one (Android 13+); otherwise the normal recognizer, which MAY send audio to Google.
  The UI shows which one is in use. Our app itself has no INTERNET permission.
  Speaker:  android.speech.tts.TextToSpeech, sentence by sentence (pa.voice.chunk).

Rules kept from the branch: mic and speaker are never on together (listening stops speech,
speaking cancels listening); everything stops when the app goes to the background.
Callbacks arrive on Android threads; `on_event` must hand them to the UI thread itself.
"""
from . import android_util as au
from .. import voice as V

try:
    from jnius import PythonJavaClass, java_method  # type: ignore
    from android.runnable import run_on_ui_thread  # type: ignore
except Exception:  # desktop: keep the module importable
    PythonJavaClass = object

    def java_method(_sig):
        return lambda f: f

    def run_on_ui_thread(f):
        return f

# SpeechRecognizer error codes
NETWORK_ERRORS = {1, 2, 4, 11}          # network timeout, network, server, server disconnected
NO_SPEECH = {6, 7}                      # speech timeout, no match
LANG_ERRORS = {12, 13, 14}              # language not supported / unavailable / can't check
ERROR_TEXT = {3: "audio recording error", 8: "recognizer busy, try again",
              9: "microphone permission missing", 10: "too many requests, wait a moment",
              12: "language not supported", 13: "language pack not installed", 14: "language check failed"}
FALLBACK_LANGUAGE = "en-US"
RESULTS_KEY = "results_recognition"     # SpeechRecognizer.RESULTS_RECOGNITION


def _first(bundle):
    if bundle is None:
        return ""
    lst = bundle.getStringArrayList(RESULTS_KEY)
    if lst is None or lst.size() == 0:
        return ""
    v = lst.get(0)
    return (v if isinstance(v, str) else str(v.toString())).strip() if v is not None else ""


class _Listener(PythonJavaClass):
    __javainterfaces__ = ["android/speech/RecognitionListener"]
    __javacontext__ = "app"

    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    @java_method("(Landroid/os/Bundle;)V")
    def onReadyForSpeech(self, params):
        self.owner._event("ready", None)

    @java_method("()V")
    def onBeginningOfSpeech(self):
        pass

    @java_method("(F)V")
    def onRmsChanged(self, rms):
        pass

    @java_method("([B)V")
    def onBufferReceived(self, buf):
        pass

    @java_method("()V")
    def onEndOfSpeech(self):
        self.owner._event("processing", None)

    @java_method("(I)V")
    def onError(self, code):
        self.owner._on_error(int(code))

    @java_method("(Landroid/os/Bundle;)V")
    def onResults(self, results):
        self.owner._on_results(_first(results))

    @java_method("(Landroid/os/Bundle;)V")
    def onPartialResults(self, partial):
        t = _first(partial)
        if t:
            self.owner._event("partial", t)

    @java_method("(ILandroid/os/Bundle;)V")
    def onEvent(self, event_type, params):
        pass


class _InitListener(PythonJavaClass):
    __javainterfaces__ = ["android/speech/tts/TextToSpeech$OnInitListener"]
    __javacontext__ = "app"

    def __init__(self, cb):
        super().__init__()
        self.cb = cb

    @java_method("(I)V")
    def onInit(self, status):
        self.cb(int(status))


class AndroidVoice:
    """on_event(kind, value): kind in ready | partial | processing | final | nospeech | error | idle."""

    def __init__(self, on_event):
        self.on_event = on_event
        self._listener = _Listener(self)  # keep references: Java holds only weak proxies
        self._sr = None
        self._listening = False
        self._prefer_offline = True
        self.on_device = False           # recognizer currently in use is on-device
        self._on_device_failed = False    # on-device recognizer refused once -> stop trying it
        self._plan = None                 # (on_device, language, prefer_offline) in use
        self._good_plan = None            # last plan that produced a result on this phone
        self._queue = []
        self._tts = None
        self._tts_ready = False
        self._tts_failed = False
        self._init_cb = None
        self._pending_speech = None
        self._uid = 0
        self.tts_voice = "-"

    # ---------- availability ----------
    def available(self):
        return au.ANDROID

    def mic_allowed(self):
        return au.granted(au.RECORD_AUDIO)

    def recognizer_label(self):
        plan = self._plan or self._good_plan or (self._plans(self._prefer_offline) or [None])[0]
        if plan is None:
            return "not available"
        on_device, lang, _offline = plan
        where = "on-device" if on_device else "phone recognizer (may use internet)"
        return "%s, %s" % (where, lang or "phone language")

    def _plans(self, prefer_offline):
        """Ways to start the recognizer, best first: (on_device, language, prefer_offline).
        Phones differ in which language packs exist (the test phone refused en-IN with
        error 13), so later entries fall back to en-US and then to the phone's own language."""
        plans = []
        if prefer_offline and self._can_on_device():
            plans.append((True, V.LANGUAGE, True))
        plans.append((False, V.LANGUAGE, prefer_offline))
        if prefer_offline:
            plans.append((False, V.LANGUAGE, False))
        plans += [(False, FALLBACK_LANGUAGE, prefer_offline), (False, None, prefer_offline)]
        if self._good_plan in plans:  # what worked last time goes first
            plans.remove(self._good_plan)
            plans.insert(0, self._good_plan)
        return plans

    def _can_on_device(self):
        if self._on_device_failed or au.sdk_int() < 33:
            return False
        try:
            SR = au.autoclass("android.speech.SpeechRecognizer")
            return bool(SR.isOnDeviceRecognitionAvailable(au.mActivity))
        except Exception:
            return False

    # ---------- listening ----------
    def _event(self, kind, value):
        self.on_event(kind, value)

    @run_on_ui_thread
    def start_listening(self, prefer_offline=True):
        self.stop_speaking()  # never listen and speak at the same time
        self._destroy_recognizer()
        self._prefer_offline = prefer_offline
        self._queue = self._plans(prefer_offline)
        self._start_next()

    def _start_next(self):
        """Start the recognizer with the next plan. Runs on the UI thread."""
        SR = au.autoclass("android.speech.SpeechRecognizer")
        RI = au.autoclass("android.speech.RecognizerIntent")
        if not self._queue:
            self._plan = None
            self._event("error", "Speech recognition is not available on this phone for %s or %s. "
                                 "Install an offline speech pack in the phone settings (Google > "
                                 "Speech) or type instead." % (V.LANGUAGE, FALLBACK_LANGUAGE))
            return
        on_device, lang, offline = self._plan = self._queue.pop(0)
        self.on_device = on_device
        try:
            if not on_device and not SR.isRecognitionAvailable(au.mActivity):
                self._queue = []
                self._event("error", "No speech recognizer on this phone.")
                return
            sr = (SR.createOnDeviceSpeechRecognizer(au.mActivity) if on_device
                  else SR.createSpeechRecognizer(au.mActivity))
            sr.setRecognitionListener(self._listener)
            b = au.autoclass("android.os.Bundle")()
            b.putString(RI.EXTRA_LANGUAGE_MODEL, RI.LANGUAGE_MODEL_FREE_FORM)
            if lang:
                b.putString(RI.EXTRA_LANGUAGE, lang)
                b.putString(RI.EXTRA_LANGUAGE_PREFERENCE, lang)
            b.putBoolean(RI.EXTRA_PARTIAL_RESULTS, True)
            b.putInt(RI.EXTRA_MAX_RESULTS, 1)
            b.putBoolean(RI.EXTRA_PREFER_OFFLINE, bool(offline))
            b.putString(RI.EXTRA_CALLING_PACKAGE, au.mActivity.getPackageName())
            it = au.autoclass("android.content.Intent")(RI.ACTION_RECOGNIZE_SPEECH)
            it.putExtras(b)
            self._sr, self._listening = sr, True
            sr.startListening(it)
        except Exception as ex:
            self._listening = False
            self._event("error", "Could not start the microphone: %s" % type(ex).__name__)

    @run_on_ui_thread
    def stop_listening(self):
        """Stop recording; the recognizer still delivers what it heard so far."""
        if self._sr is not None and self._listening:
            try:
                self._sr.stopListening()
            except Exception:
                pass

    @run_on_ui_thread
    def cancel_listening(self):
        was = self._listening
        self._destroy_recognizer()
        if was:
            self._event("idle", None)

    def is_listening(self):
        return self._listening

    def _destroy_recognizer(self):
        sr, self._sr, self._listening = self._sr, None, False
        if sr is not None:
            try:
                sr.cancel()
            except Exception:
                pass
            try:
                sr.destroy()
            except Exception:
                pass

    def _on_results(self, text):
        self._good_plan = self._plan  # this plan works on this phone: try it first next time
        self._destroy_recognizer()
        self._event("final" if text else "nospeech", text or None)

    def _on_error(self, code):
        # Called on the UI thread (recognizer callbacks run on the main looper).
        if self._listening and (code in LANG_ERRORS or (self.on_device and code == 5)):
            if self.on_device:
                self._on_device_failed = True
            if self._plan == self._good_plan:
                self._good_plan = None
            self._destroy_recognizer()
            self._start_next()  # same tap: quietly try the next way
            return
        if not self._listening:
            return  # late callback from a recognizer we already cancelled
        self._destroy_recognizer()
        if code in NO_SPEECH:
            self._good_plan = self._plan  # language was accepted, the user just stayed quiet
            self._event("nospeech", None)
        elif code in NETWORK_ERRORS:
            self._event("error", "Speech recognition needs internet on this phone (no offline "
                                 "language pack for %s)." % V.LANGUAGE)
        elif code == 5:
            self._event("idle", None)  # we cancelled it ourselves
        else:
            self._event("error", "Speech recognition failed: %s." % ERROR_TEXT.get(code, "error %d" % code))

    # ---------- speaking ----------
    def _ensure_tts(self, then):
        if self._tts_ready:
            then()
            return
        self._init_cb = then
        if self._tts is None and not self._tts_failed:
            self._create_tts()

    @run_on_ui_thread
    def _create_tts(self):
        try:
            TTS = au.autoclass("android.speech.tts.TextToSpeech")
            self._init_listener = _InitListener(self._on_tts_init)
            self._tts = TTS(au.mActivity, self._init_listener)
        except Exception as ex:
            self._tts_failed = True
            self._event("error", "Text-to-speech is not available: %s" % type(ex).__name__)

    def _on_tts_init(self, status):
        if status == 0:  # TextToSpeech.SUCCESS
            self._tts_ready = True
            cb, self._init_cb = self._init_cb, None
            if cb:
                cb()
        else:
            self._tts_failed = True
            self._event("error", "Text-to-speech engine could not start.")

    def _voices(self, tts):
        """Installed voices for the language, Indian English first, offline first, best quality."""
        lang, country = V.LANGUAGE.split("-")
        out = []
        try:
            arr = tts.getVoices().toArray()
        except Exception:
            return out
        for v in arr:
            try:
                loc = v.getLocale()
                if str(loc.getLanguage()).lower() != lang.lower():
                    continue
                if v.getFeatures().contains("notInstalled"):
                    continue
                out.append((bool(v.isNetworkConnectionRequired()), str(loc.getCountry()).upper() != country,
                            -int(v.getQuality()), str(v.getName()), v))
            except Exception:
                continue
        out.sort(key=lambda x: x[:4])
        return [x[4] for x in out]

    def speak(self, text, s):
        """Speak `text` with settings `s` (pa.voice.VoiceSettings). Returns immediately."""
        pieces = V.chunk(text)
        if not pieces or not au.ANDROID:
            return
        self.cancel_listening()
        self._ensure_tts(lambda: self._speak_now(pieces, s))

    @run_on_ui_thread
    def _speak_now(self, pieces, s):
        tts = self._tts
        if tts is None:
            return
        try:
            TTS = au.autoclass("android.speech.tts.TextToSpeech")
            String = au.autoclass("java.lang.String")
            voices = self._voices(tts)
            if voices:
                v = voices[s.voice_index % len(voices)]
                tts.setVoice(v)
                self.tts_voice = "%s%s" % (v.getName(), " (needs internet)" if v.isNetworkConnectionRequired() else "")
            else:
                tts.setLanguage(au.autoclass("java.util.Locale").forLanguageTag(V.LANGUAGE))
                self.tts_voice = "default"
            tts.setPitch(float(s.pitch))
            tts.setSpeechRate(float(s.rate))
            params = au.autoclass("android.os.Bundle")()
            params.putFloat("volume", float(s.volume))  # TextToSpeech.Engine.KEY_PARAM_VOLUME
            mode = TTS.QUEUE_FLUSH
            for text, para_end in pieces:
                self._uid += 1
                tts.speak(String(text), mode, params, "pa-%d" % self._uid)
                mode = TTS.QUEUE_ADD
                if para_end:
                    self._uid += 1
                    tts.playSilentUtterance(280, TTS.QUEUE_ADD, "pa-%d" % self._uid)
        except Exception as ex:
            self._event("error", "Could not speak: %s" % type(ex).__name__)

    def is_speaking(self):
        try:
            return bool(self._tts is not None and self._tts_ready and self._tts.isSpeaking())
        except Exception:
            return False

    def stop_speaking(self):
        if self._tts is not None and self._tts_ready:
            try:
                self._tts.stop()
            except Exception:
                pass

    # ---------- lifecycle ----------
    def pause(self):
        """App went to the background: release the mic and stop talking."""
        self.cancel_listening()
        self.stop_speaking()

    def release(self):
        self.pause()
        if self._tts is not None:
            try:
                self._tts.shutdown()
            except Exception:
                pass
        self._tts, self._tts_ready = None, False
