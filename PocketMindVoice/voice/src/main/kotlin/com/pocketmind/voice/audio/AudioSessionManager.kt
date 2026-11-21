package com.pocketmind.voice.audio

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.os.Handler
import android.os.Looper

/**
 * Owns Android audio focus for the voice engine.
 *
 * - Speaking asks for transient focus with ducking allowed (music lowers politely).
 * - Listening asks for exclusive transient focus (music pauses so it is not transcribed).
 * - Losing focus (phone call, another assistant) is forwarded as a callback.
 */
class AudioSessionManager(context: Context) {

    enum class Purpose { SPEAKING, LISTENING }
    enum class Loss { TRANSIENT, PERMANENT }

    private val audioManager = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
    private val handler = Handler(Looper.getMainLooper())
    private var request: AudioFocusRequest? = null

    /** Set by the engine. Called on the main thread. */
    var onFocusLost: ((Loss) -> Unit)? = null
    var onFocusRegained: (() -> Unit)? = null

    private val listener = AudioManager.OnAudioFocusChangeListener { change ->
        when (change) {
            AudioManager.AUDIOFOCUS_LOSS -> onFocusLost?.invoke(Loss.PERMANENT)
            AudioManager.AUDIOFOCUS_LOSS_TRANSIENT,
            AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK -> onFocusLost?.invoke(Loss.TRANSIENT)
            AudioManager.AUDIOFOCUS_GAIN -> onFocusRegained?.invoke()
        }
    }

    @Synchronized
    fun acquire(purpose: Purpose): Boolean {
        abandon()
        val speaking = purpose == Purpose.SPEAKING
        val attrs = AudioAttributes.Builder()
            .setUsage(if (speaking) AudioAttributes.USAGE_ASSISTANT else AudioAttributes.USAGE_VOICE_COMMUNICATION)
            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
            .build()
        val req = AudioFocusRequest.Builder(
            if (speaking) AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK else AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_EXCLUSIVE
        )
            .setAudioAttributes(attrs)
            .setOnAudioFocusChangeListener(listener, handler)
            .setWillPauseWhenDucked(false)
            .build()
        request = req
        val granted = audioManager.requestAudioFocus(req) == AudioManager.AUDIOFOCUS_REQUEST_GRANTED
        if (!granted) request = null
        return granted
    }

    @Synchronized
    fun abandon() {
        request?.let { runCatching { audioManager.abandonAudioFocusRequest(it) } }
        request = null
    }
}
