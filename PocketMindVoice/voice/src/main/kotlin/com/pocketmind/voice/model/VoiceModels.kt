package com.pocketmind.voice.model

/**
 * A voice personality. These are *presets*: a speaker id (when the TTS model is multi-speaker)
 * plus pitch / rate / volume. They are not different neural voices unless the model has
 * several speakers.
 */
data class VoiceProfile(
    val id: String,
    val displayName: String,
    val tagline: String,
    /** Speaker id used by the offline multi-speaker model (ignored by native Android TTS). */
    val speakerId: Int,
    /** 1.0 = unchanged. Practical range 0.7..1.4 */
    val pitch: Float,
    /** 1.0 = normal. Practical range 0.6..1.6 */
    val speechRate: Float,
    /** 0..1 */
    val volume: Float = 1f,
    /** Used by the native Android TTS fallback to pick a different installed voice per profile. */
    val nativeVoiceIndex: Int = 0,
)

object VoiceProfiles {
    // NOTE: speaker ids refer to the downloaded multi-speaker Piper "libritts_r" model (904 speakers).
    // They are provisional picks: audition them in the Voice Settings screen and adjust.
    val Nova = VoiceProfile("nova", "Nova", "Warm and friendly", speakerId = 22, pitch = 1.04f, speechRate = 1.0f, nativeVoiceIndex = 0)
    val Atlas = VoiceProfile("atlas", "Atlas", "Deep and confident", speakerId = 60, pitch = 0.84f, speechRate = 0.94f, nativeVoiceIndex = 1)
    val Echo = VoiceProfile("echo", "Echo", "Calm and professional", speakerId = 100, pitch = 1.0f, speechRate = 1.0f, nativeVoiceIndex = 2)
    val Luna = VoiceProfile("luna", "Luna", "Soft and soothing", speakerId = 140, pitch = 1.06f, speechRate = 0.88f, volume = 0.9f, nativeVoiceIndex = 3)
    val Spark = VoiceProfile("spark", "Spark", "Energetic and expressive", speakerId = 190, pitch = 1.12f, speechRate = 1.14f, nativeVoiceIndex = 4)

    val all: List<VoiceProfile> = listOf(Nova, Atlas, Echo, Luna, Spark)
    fun byId(id: String?): VoiceProfile = all.firstOrNull { it.id == id } ?: Nova
}

/** Persisted user preferences. Slider values are absolute and are seeded from the selected profile. */
data class VoiceSettings(
    val profileId: String = VoiceProfiles.Nova.id,
    val speakerId: Int = VoiceProfiles.Nova.speakerId,
    val pitch: Float = VoiceProfiles.Nova.pitch,
    val speechRate: Float = VoiceProfiles.Nova.speechRate,
    val volume: Float = VoiceProfiles.Nova.volume,
    val nativeVoiceIndex: Int = VoiceProfiles.Nova.nativeVoiceIndex,
    val language: String = "en-US",
    /** Prefer on-device engines. If false, the platform recognizer may use the network. */
    val preferOffline: Boolean = true,
) {
    companion object {
        const val PITCH_MIN = 0.7f
        const val PITCH_MAX = 1.4f
        const val RATE_MIN = 0.6f
        const val RATE_MAX = 1.6f
        fun from(p: VoiceProfile, base: VoiceSettings = VoiceSettings()) = base.copy(
            profileId = p.id, speakerId = p.speakerId, pitch = p.pitch,
            speechRate = p.speechRate, volume = p.volume, nativeVoiceIndex = p.nativeVoiceIndex,
        )
    }
}

/** Parameters handed to a speech synthesizer for one utterance. */
data class SpeechParams(
    val speakerId: Int,
    val pitch: Float,
    val rate: Float,
    val volume: Float,
    val nativeVoiceIndex: Int,
    val language: String,
)

/** Results emitted by speech-to-text backends. */
sealed interface SpeechResult {
    data class Partial(val text: String) : SpeechResult
    data class Final(val text: String) : SpeechResult
    /** The user did not say anything intelligible (timeout / no match). Not an error. */
    data object NoSpeech : SpeechResult
}

enum class VoiceErrorCode {
    PERMISSION_DENIED, STT_UNAVAILABLE, TTS_UNAVAILABLE, AUDIO_ERROR, MODEL_ERROR, NETWORK, UNKNOWN
}

data class VoiceError(val code: VoiceErrorCode, val message: String, val cause: Throwable? = null)

class VoiceException(val error: VoiceError) : Exception(error.message, error.cause)

enum class VoicePhase { Uninitialized, Initializing, Idle, Listening, Processing, Speaking, Paused, Error }

/** Everything a UI needs to render, as one immutable snapshot. */
data class VoiceState(
    val phase: VoicePhase = VoicePhase.Uninitialized,
    /** Live partial transcript while [VoicePhase.Listening]. */
    val partialTranscript: String = "",
    val sttBackend: String = "-",
    val ttsBackend: String = "-",
    val sttOffline: Boolean = false,
    val ttsOffline: Boolean = false,
    val offlineModelsInstalled: Boolean = false,
    /** Sentence currently being spoken (for captions). */
    val currentSentence: String = "",
    val error: VoiceError? = null,
)

/** One-shot events for the integration layer. */
sealed interface VoiceEvent {
    data class Partial(val text: String) : VoiceEvent
    /** A complete user utterance. This is what the main AI should consume. */
    data class FinalTranscript(val text: String) : VoiceEvent
    data object NoSpeechDetected : VoiceEvent
    data object SpeechStarted : VoiceEvent
    /** Spoken to the end (not emitted when interrupted). */
    data object SpeechFinished : VoiceEvent
    data object SpeechInterrupted : VoiceEvent
    data class Error(val error: VoiceError) : VoiceEvent
}
