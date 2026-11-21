package com.pocketmind.voice

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import androidx.core.content.ContextCompat
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import com.pocketmind.voice.audio.AudioSessionManager
import com.pocketmind.voice.model.SpeechParams
import com.pocketmind.voice.model.SpeechResult
import com.pocketmind.voice.model.VoiceError
import com.pocketmind.voice.model.VoiceErrorCode
import com.pocketmind.voice.model.VoiceEvent
import com.pocketmind.voice.model.VoiceException
import com.pocketmind.voice.model.VoicePhase
import com.pocketmind.voice.model.VoiceProfile
import com.pocketmind.voice.model.VoiceSettings
import com.pocketmind.voice.model.VoiceState
import com.pocketmind.voice.models.ModelManager
import com.pocketmind.voice.models.ModelPacks
import com.pocketmind.voice.stt.AndroidSpeechToText
import com.pocketmind.voice.stt.SherpaSpeechToText
import com.pocketmind.voice.stt.SpeechToText
import com.pocketmind.voice.stt.TranscriptFormatter
import com.pocketmind.voice.tts.AndroidSpeechSynthesizer
import com.pocketmind.voice.tts.SherpaSpeechSynthesizer
import com.pocketmind.voice.tts.SpeechSynthesizer
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

/**
 * Default [PocketMindVoiceEngine].
 *
 * Backend selection (decided at runtime, never assumed):
 *  - STT: sherpa-onnx Zipformer (offline) if the model pack is installed -> else Android SpeechRecognizer.
 *  - TTS: sherpa-onnx Piper (offline, multi-speaker) if installed -> else Android TextToSpeech.
 * A runtime failure of the sherpa TTS automatically retries on Android TTS.
 *
 * Only one of {microphone, speaker} is active at a time: listening stops speech and vice versa.
 */
class VoiceEngine(context: Context) : PocketMindVoiceEngine {

    private val app = context.applicationContext
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val prefs = VoicePreferences(app)
    private val models = ModelManager(app)
    private val audio = AudioSessionManager(app)

    private val _state = MutableStateFlow(VoiceState())
    override val state: StateFlow<VoiceState> = _state.asStateFlow()
    private val _events = MutableSharedFlow<VoiceEvent>(extraBufferCapacity = 64)
    override val events: SharedFlow<VoiceEvent> = _events.asSharedFlow()
    override val settings: StateFlow<VoiceSettings> get() = prefs.settings

    private val opLock = Mutex()
    private val loadLock = Mutex()
    private var stt: SpeechToText? = null
    private var tts: SpeechSynthesizer? = null
    private var ttsForceNative = false

    private var listenJob: Job? = null
    private var speakJob: Job? = null
    @Volatile private var pausedByFocus = false
    @Volatile private var pausedByLifecycle = false

    init {
        audio.onFocusLost = { loss ->
            scope.launch {
                when (_state.value.phase) {
                    VoicePhase.Speaking ->
                        if (loss == AudioSessionManager.Loss.TRANSIENT) { pausedByFocus = true; pauseSpeaking() } else stopSpeaking()
                    VoicePhase.Listening -> cancelListening()
                    else -> Unit
                }
            }
        }
        audio.onFocusRegained = { if (pausedByFocus) { pausedByFocus = false; scope.launch { resumeSpeaking() } } }
    }

    // ---------------------------------------------------------------- lifecycle

    override suspend fun initialize() {
        if (_state.value.phase != VoicePhase.Uninitialized && _state.value.phase != VoicePhase.Error) return
        _state.update { it.copy(phase = VoicePhase.Initializing, error = null) }
        _state.update { it.copy(phase = VoicePhase.Idle, offlineModelsInstalled = models.allInstalled()) }
        // Warm-up: load the offline models in the background so the first reply is not delayed by ~3 s of
        // model loading (costs ~350 MB RAM). Skipped when the packs are not installed.
        if (models.allInstalled() && prefs.settings.value.preferOffline) {
            scope.launch {
                runCatching { ensureTts() }
                runCatching { ensureStt() }
            }
        }
    }

    override fun attachLifecycle(owner: LifecycleOwner) {
        owner.lifecycle.addObserver(object : DefaultLifecycleObserver {
            override fun onStop(owner: LifecycleOwner) {
                scope.launch {
                    cancelListening()
                    if (_state.value.phase == VoicePhase.Speaking) { pausedByLifecycle = true; pauseSpeaking() }
                }
            }

            override fun onStart(owner: LifecycleOwner) {
                if (pausedByLifecycle) { pausedByLifecycle = false; scope.launch { resumeSpeaking() } }
            }
        })
    }

    override fun release() {
        listenJob?.cancel(); speakJob?.cancel()
        tts?.stop()
        audio.abandon()
        stt?.release(); tts?.release()
        stt = null; tts = null
        _state.value = VoiceState(offlineModelsInstalled = models.allInstalled())
    }

    // ---------------------------------------------------------------- backend loading (lazy)

    private fun micGranted() =
        ContextCompat.checkSelfPermission(app, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED

    private suspend fun ensureStt(): SpeechToText = loadLock.withLock {
        stt?.let { return it }
        val preferSherpa = prefs.settings.value.preferOffline && models.isInstalled(ModelPacks.AsrZipformerEn)
        var chosen: SpeechToText? = null
        if (preferSherpa) {
            val s = SherpaSpeechToText(models.dir(ModelPacks.AsrZipformerEn))
            if (s.prepare()) chosen = s else s.release()
        }
        if (chosen == null) {
            val a = AndroidSpeechToText(app) { prefs.settings.value.preferOffline }
            if (a.prepare()) chosen = a
        }
        val result = chosen ?: throw VoiceException(
            VoiceError(VoiceErrorCode.STT_UNAVAILABLE, "No speech recognizer available. Install the offline voice pack or Google speech services.")
        )
        stt = result
        _state.update { it.copy(sttBackend = result.name, sttOffline = result.isOffline) }
        result
    }

    private suspend fun ensureTts(): SpeechSynthesizer = loadLock.withLock {
        tts?.let { return it }
        var chosen: SpeechSynthesizer? = null
        if (!ttsForceNative && models.isInstalled(ModelPacks.TtsPiperLibriTts)) {
            val s = SherpaSpeechSynthesizer(models.dir(ModelPacks.TtsPiperLibriTts))
            if (s.prepare()) chosen = s else s.release()
        }
        if (chosen == null) {
            val a = AndroidSpeechSynthesizer(app)
            if (a.prepare()) chosen = a else a.release()
        }
        val result = chosen ?: throw VoiceException(
            VoiceError(VoiceErrorCode.TTS_UNAVAILABLE, "No text-to-speech engine available on this device.")
        )
        tts = result
        _state.update { it.copy(ttsBackend = result.name, ttsOffline = result.isOffline) }
        result
    }

    /** Drop loaded backends so the next use re-selects (after a model download or a setting change). */
    private suspend fun resetBackends() {
        cancelListening(); stopSpeaking()
        loadLock.withLock {
            stt?.release(); tts?.release(); stt = null; tts = null; ttsForceNative = false
        }
        _state.update { it.copy(offlineModelsInstalled = models.allInstalled(), sttBackend = "-", ttsBackend = "-") }
    }

    // ---------------------------------------------------------------- listening

    override suspend fun startListening() {
        opLock.withLock {
            if (!micGranted()) {
                fail(VoiceError(VoiceErrorCode.PERMISSION_DENIED, "Microphone permission is required to listen."))
                return
            }
            stopSpeakingLocked()
            cancelListeningLocked()
            val recognizer = try {
                ensureStt()
            } catch (e: VoiceException) {
                fail(e.error); return
            }
            audio.acquire(AudioSessionManager.Purpose.LISTENING)
            _state.update { it.copy(phase = VoicePhase.Listening, partialTranscript = "", error = null) }
            listenJob = scope.launch {
                try {
                    recognizer.listen(prefs.settings.value.language).collect { r ->
                        when (r) {
                            is SpeechResult.Partial -> {
                                val text = TranscriptFormatter.format(r.text)
                                _state.update { it.copy(partialTranscript = text) }
                                _events.tryEmit(VoiceEvent.Partial(text))
                            }
                            is SpeechResult.Final -> _events.emit(VoiceEvent.FinalTranscript(TranscriptFormatter.format(r.text)))
                            SpeechResult.NoSpeech -> _events.emit(VoiceEvent.NoSpeechDetected)
                        }
                    }
                } catch (e: CancellationException) {
                    throw e
                } catch (e: VoiceException) {
                    fail(e.error)
                } catch (t: Throwable) {
                    fail(VoiceError(VoiceErrorCode.AUDIO_ERROR, t.message ?: "Listening failed", t))
                } finally {
                    audio.abandon()
                    _state.update { if (it.phase == VoicePhase.Listening) it.copy(phase = VoicePhase.Idle, partialTranscript = "") else it }
                }
            }
        }
    }

    override suspend fun stopListening() {
        stt?.finish() // the running flow still emits the final transcript
    }

    override suspend fun cancelListening() = opLock.withLock { cancelListeningLocked() }

    private suspend fun cancelListeningLocked() {
        val j = listenJob ?: return
        listenJob = null
        j.cancelAndJoin()
    }

    // ---------------------------------------------------------------- speaking

    override suspend fun speak(text: String) = speakWith(text, currentParams())

    private fun currentParams(s: VoiceSettings = prefs.settings.value) =
        SpeechParams(s.speakerId, s.pitch, s.speechRate, s.volume, s.nativeVoiceIndex, s.language)

    private suspend fun speakWith(text: String, params: SpeechParams) {
        if (text.isBlank()) return
        val job = opLock.withLock {
            cancelListeningLocked()
            stopSpeakingLocked()
            pausedByFocus = false
            scope.launch { runSpeech(text, params) }.also { speakJob = it }
        }
        try {
            job.join()
        } catch (e: CancellationException) {
            // The caller gave up (e.g. its screen closed): silence immediately.
            tts?.stop(); job.cancel()
            throw e
        }
    }

    private suspend fun runSpeech(text: String, params: SpeechParams) {
        var finished = false
        try {
            audio.acquire(AudioSessionManager.Purpose.SPEAKING)
            _state.update { it.copy(phase = VoicePhase.Speaking, currentSentence = "", error = null) }
            _events.tryEmit(VoiceEvent.SpeechStarted)
            var attempt = 0
            while (true) {
                val synth = ensureTts()
                try {
                    synth.speak(text, params) { sentence -> _state.update { it.copy(currentSentence = sentence) } }
                    _state.update { it.copy(ttsBackend = synth.name, ttsOffline = synth.isOffline) }
                    finished = true
                    break
                } catch (e: CancellationException) {
                    throw e
                } catch (t: Throwable) {
                    // Graceful fallback: broken offline model -> native Android TTS, once.
                    android.util.Log.e("PMVoice", "TTS failed on ${synth.name}", t)
                    if (attempt++ == 0 && synth is SherpaSpeechSynthesizer) {
                        loadLock.withLock { synth.release(); tts = null; ttsForceNative = true }
                    } else throw t
                }
            }
        } catch (e: CancellationException) {
            _events.tryEmit(VoiceEvent.SpeechInterrupted)
            throw e
        } catch (e: VoiceException) {
            fail(e.error)
        } catch (t: Throwable) {
            fail(VoiceError(VoiceErrorCode.TTS_UNAVAILABLE, t.message ?: "Speech failed", t))
        } finally {
            audio.abandon()
            _state.update {
                if (it.phase == VoicePhase.Speaking || it.phase == VoicePhase.Paused) it.copy(phase = VoicePhase.Idle, currentSentence = "") else it
            }
        }
        if (finished) _events.emit(VoiceEvent.SpeechFinished)
    }

    override suspend fun stopSpeaking() = opLock.withLock { stopSpeakingLocked() }

    private suspend fun stopSpeakingLocked() {
        val j = speakJob ?: return
        speakJob = null
        tts?.stop()        // unblocks audio writes immediately
        j.cancelAndJoin()
    }

    override suspend fun pauseSpeaking() {
        if (_state.value.phase != VoicePhase.Speaking) return
        tts?.pause()
        _state.update { it.copy(phase = VoicePhase.Paused) }
    }

    override suspend fun resumeSpeaking() {
        if (_state.value.phase != VoicePhase.Paused) return
        pausedByFocus = false; pausedByLifecycle = false
        tts?.resume()
        _state.update { it.copy(phase = VoicePhase.Speaking) }
    }

    override suspend fun previewVoice(profile: VoiceProfile?) {
        val name = profile?.displayName ?: prefs.currentProfile().displayName
        val text = "Hi, I'm $name. This is how I sound. How can I help you today?"
        val params = if (profile == null) currentParams() else SpeechParams(
            profile.speakerId, profile.pitch, profile.speechRate, profile.volume, profile.nativeVoiceIndex, prefs.settings.value.language,
        )
        speakWith(text, params)
    }

    override fun notifyProcessing(active: Boolean) {
        _state.update {
            when {
                active && it.phase == VoicePhase.Idle -> it.copy(phase = VoicePhase.Processing)
                !active && it.phase == VoicePhase.Processing -> it.copy(phase = VoicePhase.Idle)
                else -> it
            }
        }
    }

    // ---------------------------------------------------------------- settings

    override fun setVoiceProfile(profile: VoiceProfile) = prefs.selectProfile(profile)
    override fun setPitch(value: Float) = prefs.update { it.copy(pitch = value.coerceIn(VoiceSettings.PITCH_MIN, VoiceSettings.PITCH_MAX)) }
    override fun setSpeechRate(value: Float) = prefs.update { it.copy(speechRate = value.coerceIn(VoiceSettings.RATE_MIN, VoiceSettings.RATE_MAX)) }
    override fun setVolume(value: Float) = prefs.update { it.copy(volume = value.coerceIn(0f, 1f)) }
    override fun setSpeakerId(id: Int) = prefs.update { it.copy(speakerId = id.coerceAtLeast(0)) }
    override fun setLanguage(tag: String) = prefs.update { it.copy(language = tag) }
    override fun setPreferOffline(value: Boolean) {
        prefs.update { it.copy(preferOffline = value) }
        scope.launch { opLock.withLock { if (_state.value.phase == VoicePhase.Idle) resetBackendsUnlocked() } }
    }

    private suspend fun resetBackendsUnlocked() = loadLock.withLock {
        stt?.release(); stt = null
        _state.update { it.copy(sttBackend = "-") }
    }

    // ---------------------------------------------------------------- offline models

    override suspend fun downloadOfflineModels(onProgress: (String, Float) -> Unit) {
        try {
            for (pack in ModelPacks.all) {
                if (!models.isInstalled(pack)) models.install(pack) { onProgress(pack.title, it) }
            }
        } catch (e: CancellationException) {
            throw e
        } catch (t: Throwable) {
            val err = VoiceError(VoiceErrorCode.NETWORK, "Model download failed: ${t.message}", t)
            fail(err)
            throw VoiceException(err)
        }
        withContext(Dispatchers.Default) { resetBackends() }
    }

    // ---------------------------------------------------------------- errors

    private fun fail(error: VoiceError) {
        _state.update { it.copy(phase = VoicePhase.Idle, error = error, partialTranscript = "") }
        _events.tryEmit(VoiceEvent.Error(error))
    }
}
