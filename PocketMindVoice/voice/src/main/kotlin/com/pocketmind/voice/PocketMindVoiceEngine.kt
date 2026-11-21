package com.pocketmind.voice

import androidx.lifecycle.LifecycleOwner
import com.pocketmind.voice.model.VoiceEvent
import com.pocketmind.voice.model.VoiceProfile
import com.pocketmind.voice.model.VoiceSettings
import com.pocketmind.voice.model.VoiceState
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow

/**
 * The only type the rest of PocketMind needs to know about.
 *
 * The engine converts audio -> text ([VoiceEvent.FinalTranscript]) and text -> audio ([speak]).
 * It never generates answers itself.
 *
 * All suspend functions are main-safe. Every function is safe to call repeatedly and in any state.
 */
interface PocketMindVoiceEngine {

    /** Current phase + backend info + live partial transcript. Collect this to drive UI. */
    val state: StateFlow<VoiceState>

    /** Transcripts, speech lifecycle and errors. Hot flow; collect it before calling startListening. */
    val events: SharedFlow<VoiceEvent>

    /** Persisted preferences. */
    val settings: StateFlow<VoiceSettings>

    /** Loads preferences and probes backends. Cheap; heavy models are loaded lazily on first use. */
    suspend fun initialize()

    /** Starts recording. Stops any speech first. Emits Partial* then FinalTranscript (or NoSpeechDetected). */
    suspend fun startListening()

    /** Stop recording and deliver the transcript of what was heard so far. */
    suspend fun stopListening()

    /** Stop recording and discard everything. */
    suspend fun cancelListening()

    /**
     * Speak [text] aloud. Suspends until the speech ends or is interrupted. Long text and
     * multiple paragraphs are fine; the last sentence is never cut off.
     * Cancelling the calling coroutine stops the speech.
     */
    suspend fun speak(text: String)

    /** Immediately silence the assistant (interrupt). */
    suspend fun stopSpeaking()
    suspend fun pauseSpeaking()
    suspend fun resumeSpeaking()

    /** Short sample in the current voice (or [profile] without changing the saved voice). */
    suspend fun previewVoice(profile: VoiceProfile? = null)

    /** Tell the engine the AI is thinking, so the UI can show "Processing". Optional. */
    fun notifyProcessing(active: Boolean)

    fun setVoiceProfile(profile: VoiceProfile)
    fun setPitch(value: Float)
    fun setSpeechRate(value: Float)
    fun setVolume(value: Float)
    fun setSpeakerId(id: Int)
    fun setLanguage(tag: String)
    fun setPreferOffline(value: Boolean)

    /** Download the offline STT+TTS models (~150 MB) and switch to them. */
    suspend fun downloadOfflineModels(onProgress: (stage: String, fraction: Float) -> Unit)

    /** Pauses speech / stops the mic when the app goes to background; resumes speech on return. */
    fun attachLifecycle(owner: LifecycleOwner)

    /** Free models and audio resources. The engine can be re-initialized afterwards. */
    fun release()
}
