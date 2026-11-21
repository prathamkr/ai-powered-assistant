package com.pocketmind.voice.tts

import com.pocketmind.voice.model.SpeechParams

/** A text-to-speech backend. The engine picks one at runtime and falls back if it is unavailable. */
interface SpeechSynthesizer {
    val name: String

    /** True only if synthesis runs fully on the device. */
    val isOffline: Boolean

    /** Load model / bind to the system engine. @return false if this backend cannot be used. */
    suspend fun prepare(): Boolean

    /**
     * Speak [text] sentence by sentence. Suspends until the last sentence has actually been
     * played, or until [stop] / coroutine cancellation. [onSentence] is called as each sentence starts.
     */
    suspend fun speak(text: String, params: SpeechParams, onSentence: (String) -> Unit)

    fun pause()
    fun resume()

    /** Thread-safe, immediate. A pending [speak] returns promptly. */
    fun stop()

    fun release()
}
