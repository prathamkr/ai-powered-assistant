package com.pocketmind.voice.stt

import com.pocketmind.voice.model.SpeechResult
import kotlinx.coroutines.flow.Flow

/** A speech-to-text backend. The engine picks one at runtime and falls back if it is unavailable. */
interface SpeechToText {
    val name: String

    /** True only if recognition runs fully on the device (no network). */
    val isOffline: Boolean

    /** Load models / probe availability. @return false if this backend cannot be used. */
    suspend fun prepare(): Boolean

    /**
     * Cold flow. Collecting starts the microphone; cancelling the collection stops it immediately.
     * Emits zero or more [SpeechResult.Partial] and then exactly one [SpeechResult.Final] or
     * [SpeechResult.NoSpeech]. Errors are thrown as [com.pocketmind.voice.model.VoiceException].
     */
    fun listen(language: String): Flow<SpeechResult>

    /** Ask a running [listen] to finish early and still deliver the final transcript. */
    fun finish()

    fun release()
}
