"""Voice on Android with the phone's own engines (the "Android fallback" path of the
PocketMind Voice branch, rewritten in Python/pyjnius):

  Listener (default, engine "builtin"): Lazey's own voice pack, the Vosk engine with a small
  Indian English model shipped inside the APK (java/org/pa/assistant/VoskEngine.java). It works on
  every phone from the first start, without internet and without a language-pack download.
  Listener (engine "phone"): android.speech.SpeechRecognizer, on-device only (Android 13+); its
  language pack must be downloaded once. Our app itself has no INTERNET permission.
  Speaker:  android.speech.tts.TextToSpeech, sentence by sentence (pa.voice.chunk).

Rules kept from the branch: mic and speaker are never on together (listening stops speech,
speaking cancels listening); everything stops when the app goes to the background.
Callbacks arrive on Android threads; `on_event` must hand them to the UI thread itself.
"""
from . import android_util as au
from .. import voice as V
from ..voice_fix import normalize as fix_builtin_text

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


def _strings(jlist):
    if jlist is None:
        return []
    return [str(jlist.get(i)) for i in range(jlist.size())]


class _SupportCallback(PythonJavaClass):
    """android.speech.RecognitionSupportCallback (Android 13+): which on-device languages exist."""
    __javainterfaces__ = ["android/speech/RecognitionSupportCallback"]
    __javacontext__ = "app"

    def __init__(self, cb):
        super().__init__()
        self.cb = cb

    @java_method("(Landroid/speech/RecognitionSupport;)V")
    def onSupportResult(self, s):
        self.cb(_strings(s.getInstalledOnDeviceLanguages()), _strings(s.getPendingOnDeviceLanguages()),
                _strings(s.getSupportedOnDeviceLanguages()), None)

    @java_method("(I)V")
    def onError(self, code):
        self.cb([], [], [], int(code))


class _VoskListener(PythonJavaClass):
    """org.pa.assistant.VoskEngine.Listener: events from the built-in voice pack (main thread)."""
    __javainterfaces__ = ["org/pa/assistant/VoskEngine$Listener"]
    __javacontext__ = "app"

    def __init__(self, cb):
        super().__init__()
        self.cb = cb

    @java_method("(Ljava/lang/String;Ljava/lang/String;)V")
    def onEvent(self, kind, value):
        self.cb(str(kind), "" if value is None else str(value))


def builtin_error_text(code):
    """VoskEngine error codes -> one line for the chat."""
    code = code or ""
    if code == "loading":
        return "The voice pack is still loading. Try again in a moment."
    if code.startswith("load:"):
        return "Lazey's voice pack could not load (%s). Type instead, or pick 'Phone speech' in Voice." % (
            code[5:][:80] or "unknown error")
    if code.startswith("mic:"):
        return "Could not use the microphone. Another app may be using it; close it and try again."
    return "Voice input failed (%s)." % code[:80]


class AndroidVoice:
    """on_event(kind, value): kind in loading | ready | partial | processing | final | nospeech | error | idle,
    plus builtin_status / offline_status for the Voice screen."""

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
        self.offline_lang = None          # language whose offline pack is installed (from check_offline)
        self.engine = V.DEFAULT_ENGINE    # "builtin" (Lazey's voice pack) | "phone" (phone's recognizer)
        self.builtin_state = "none"       # none | loading | ready | error
        self.builtin_error = ""
        self._vosk_load_cb = None         # keep references: Java holds only weak proxies
        self._vosk_turn_cb = None
        self._start_when_loaded = False
        self._support_cb = None
        self._helper_sr = None            # on-device recognizer used for check/download
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
        if self.engine == "builtin":
            st = {"loading": ", loading", "error": ", could not load"}.get(self.builtin_state, "")
            return "Lazey voice pack, offline, English (India)%s" % st
        plan = self._plan or self._good_plan or (self._plans(self._prefer_offline) or [None])[0]
        if plan is None:
            return "offline speech not installed" if self._prefer_offline else "not available"
        on_device, lang, _offline = plan
        where = "offline, on-device" if on_device else "phone recognizer (may use internet)"
        return "%s, %s" % (where, lang or "phone language")

    def _plans(self, offline_only):
        """Ways to start the recognizer, best first: (on_device, language, prefer_offline).

        offline_only=True (default): ONLY the on-device recognizer (createOnDeviceSpeechRecognizer
        guarantees audio stays on the phone). Its language pack must be installed once
        (download_offline). Otherwise: on-device first, then the normal recognizer, which may
        use Google's servers. Phones differ in packs (the test phone refused en-IN with error 13),
        so later entries try en-US and the phone's own language."""
        plans = []
        if offline_only:
            if self._can_on_device(ignore_failed=True):
                for lang in dict.fromkeys(x for x in (self.offline_lang, V.LANGUAGE, FALLBACK_LANGUAGE) if x):
                    plans.append((True, lang, True))
            return plans
        if self._can_on_device():
            plans.append((True, V.LANGUAGE, True))
        plans += [(False, V.LANGUAGE, True), (False, V.LANGUAGE, False), (False, FALLBACK_LANGUAGE, False),
                  (False, None, False)]
        if self._good_plan in plans:  # what worked last time goes first
            plans.remove(self._good_plan)
            plans.insert(0, self._good_plan)
        return plans

    def _can_on_device(self, ignore_failed=False):
        if (self._on_device_failed and not ignore_failed) or au.sdk_int() < 33:
            return False
        try:
            SR = au.autoclass("android.speech.SpeechRecognizer")
            return bool(SR.isOnDeviceRecognitionAvailable(au.mActivity))
        except Exception:
            return False

    # ---------- listening ----------
    def _event(self, kind, value):
        self.on_event(kind, value)

    # ---------- built-in voice pack (Vosk) ----------
    def _vosk(self):
        return au.autoclass("org.pa.assistant.VoskEngine")

    def load_builtin(self):
        """Copy (first start only) and load the built-in voice pack in the background.
        Result: event 'builtin_status'. Called on the first mic tap and when Voice is opened."""
        if not au.ANDROID or self.builtin_state in ("loading", "ready"):
            return
        self.builtin_state, self.builtin_error = "loading", ""
        try:
            self._vosk_load_cb = _VoskListener(self._on_builtin_loaded)
            self._vosk().load(au.mActivity, self._vosk_load_cb)
        except Exception as ex:
            self._on_builtin_loaded("load_error", type(ex).__name__)

    def _on_builtin_loaded(self, kind, value):
        if kind == "loaded":
            self.builtin_state, self.builtin_error = "ready", ""
        else:
            self.builtin_state, self.builtin_error = "error", value or "unknown"
        self._event("builtin_status", self.builtin_state)
        if self._start_when_loaded:   # the mic was tapped while the pack was loading
            self._start_when_loaded = False
            if self.builtin_state == "ready":
                self._vosk_start()
            else:
                self._listening = False
                self._event("error", builtin_error_text("load:" + self.builtin_error))

    def _vosk_start(self):
        self._plan, self.on_device = None, True
        try:
            self._vosk_turn_cb = _VoskListener(self._on_builtin_turn)
            self._vosk().start(self._vosk_turn_cb)   # if it cannot start, an "error" event follows
        except Exception as ex:
            self._listening = False
            self._event("error", "Could not start the microphone: %s" % type(ex).__name__)

    def _on_builtin_turn(self, kind, value):
        if not self._listening:
            return   # cancelled meanwhile
        if kind in ("ready", "partial"):
            self._event(kind, value or None)
            return
        self._listening = False
        if kind == "final" and value:
            # the pack has no Hindi words / app names: "battery kidney" -> "battery kitni hai"
            self._event("final", fix_builtin_text(value) or value)
        elif kind in ("final", "nospeech"):
            self._event("nospeech", None)
        else:
            self._event("error", builtin_error_text(value))

    def _start_builtin(self):
        self._listening = True
        if self.builtin_state == "ready":
            self._vosk_start()
            return
        if self.builtin_state == "error":
            self._listening = False
            self._event("error", builtin_error_text("load:" + self.builtin_error))
            return
        self._start_when_loaded = True
        self._event("loading", None)
        self.load_builtin()

    @run_on_ui_thread
    def start_listening(self, prefer_offline=True):
        self.stop_speaking()  # never listen and speak at the same time
        self._destroy_recognizer()
        if self.engine == "builtin":
            self._start_builtin()
            return
        self._prefer_offline = prefer_offline
        self._queue = self._plans(prefer_offline)
        self._start_next()

    def _start_next(self):
        """Start the recognizer with the next plan. Runs on the UI thread."""
        SR = au.autoclass("android.speech.SpeechRecognizer")
        RI = au.autoclass("android.speech.RecognizerIntent")
        if not self._queue:
            self._plan = None
            if self._prefer_offline:
                self._event("error", "Offline speech is not installed yet. Open Voice and tap 'Download "
                                     "offline speech' (needs internet once), or type instead.")
            else:
                self._event("error", "Speech recognition is not available on this phone for %s or %s. "
                                     "Type instead." % (V.LANGUAGE, FALLBACK_LANGUAGE))
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
        if self.engine == "builtin" and self._listening:
            if self._start_when_loaded:   # still loading: nothing was recorded yet
                self._start_when_loaded, self._listening = False, False
                self._event("idle", None)
                return
            try:
                self._vosk().stop()   # what was heard so far arrives as "final"
            except Exception:
                self._listening = False
                self._event("idle", None)
            return
        if self._sr is not None and self._listening:
            try:
                self._sr.stopListening()
            except Exception:
                pass

    @run_on_ui_thread
    def cancel_listening(self):
        was = self._listening
        self._start_when_loaded = False
        if au.ANDROID and self.builtin_state == "ready":
            try:
                self._vosk().cancel()
            except Exception:
                pass
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
        # On the test phone, with internet off, the on-device recognizer answered en-IN (no pack
        # installed) with a NETWORK error, not "language unavailable". In offline mode that also
        # means "try the next installed language" (en-US was installed and works offline).
        offline_retry = self.on_device and self._prefer_offline and code in NETWORK_ERRORS
        if self._listening and (code in LANG_ERRORS or (self.on_device and code == 5) or offline_retry):
            if self.on_device and not self._prefer_offline:
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

    # ---------- offline speech pack ----------
    def _lang_intent(self, lang):
        RI = au.autoclass("android.speech.RecognizerIntent")
        b = au.autoclass("android.os.Bundle")()
        b.putString(RI.EXTRA_LANGUAGE_MODEL, RI.LANGUAGE_MODEL_FREE_FORM)
        b.putString(RI.EXTRA_LANGUAGE, lang)
        it = au.autoclass("android.content.Intent")(RI.ACTION_RECOGNIZE_SPEECH)
        it.putExtras(b)
        return it

    def _helper(self):
        SR = au.autoclass("android.speech.SpeechRecognizer")
        if self._helper_sr is None:
            self._helper_sr = SR.createOnDeviceSpeechRecognizer(au.mActivity)
        return self._helper_sr

    @run_on_ui_thread
    def check_offline(self):
        """Ask the on-device recognizer which languages are installed / can be downloaded.
        Result arrives as event 'offline_status' with a dict."""
        if not au.ANDROID or au.sdk_int() < 33 or not self._can_on_device(ignore_failed=True):
            self._event("offline_status", {"available": False})
            return
        try:
            self._support_cb = _SupportCallback(self._on_support)
            self._helper().checkRecognitionSupport(self._lang_intent(V.LANGUAGE), au.mActivity.getMainExecutor(),
                                                   self._support_cb)
        except Exception as ex:
            self._event("offline_status", {"available": False, "error": type(ex).__name__})

    def _on_support(self, installed, pending, supported, error):
        def has(langs, want):
            return next((x for x in langs if x.lower() == want.lower()), None)
        st = {"available": error is None, "installed": installed, "pending": pending, "supported": supported,
              "error": error}
        self.offline_lang = has(installed, V.LANGUAGE) or has(installed, FALLBACK_LANGUAGE)
        st["ready"] = self.offline_lang
        # what to download: Indian English if the phone offers it, else US English
        st["download"] = None if self.offline_lang else (
            has(supported, V.LANGUAGE) or has(supported, FALLBACK_LANGUAGE)
            or (V.LANGUAGE if not supported else None))
        st["downloading"] = bool(has(pending, V.LANGUAGE) or has(pending, FALLBACK_LANGUAGE))
        # en-US works offline but Indian English understands Hinglish names better: offer it too
        st["better"] = (has(supported, V.LANGUAGE)
                        if self.offline_lang and self.offline_lang.lower() != V.LANGUAGE.lower()
                        and not has(pending, V.LANGUAGE) else None)
        if self.offline_lang:
            self._on_device_failed = False
        self._event("offline_status", st)

    @run_on_ui_thread
    def download_offline(self, lang):
        """Ask Google's on-device recognizer to download the language pack (internet needed once).
        The download runs in the system; check_offline() shows when it is done."""
        try:
            self._helper().triggerModelDownload(self._lang_intent(lang))
            self._event("info", "Downloading offline speech for %s. This needs internet once and can take a "
                                "few minutes. Open Voice again to see when it is ready." % lang)
        except Exception as ex:
            self._event("error", "Could not start the offline speech download: %s" % type(ex).__name__)

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
