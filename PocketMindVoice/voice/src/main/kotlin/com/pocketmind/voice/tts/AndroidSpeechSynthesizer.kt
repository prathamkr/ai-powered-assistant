package com.pocketmind.voice.tts

import android.content.Context
import android.os.Bundle
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.speech.tts.Voice
import com.pocketmind.voice.model.SpeechParams
import kotlinx.coroutines.CancellableContinuation
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import java.util.Locale
import java.util.concurrent.ConcurrentHashMap
import kotlin.coroutines.coroutineContext
import kotlin.coroutines.resume

/**
 * Fallback / always-available TTS using the device's [TextToSpeech] engine.
 * Installed voices differ per device, so voices are discovered at runtime, never assumed.
 *
 * Android TTS has no real pause, so pause = stop the current sentence and replay it on resume.
 */
class AndroidSpeechSynthesizer(private val context: Context) : SpeechSynthesizer {

    override val name: String get() = if (offline) "Android TextToSpeech (on-device voice)" else "Android TextToSpeech (network voice)"
    override val isOffline: Boolean get() = offline
    private var offline = true

    private enum class Outcome { DONE, STOPPED, ERROR }

    private var tts: TextToSpeech? = null
    private val pending = ConcurrentHashMap<String, CancellableContinuation<Outcome>>()
    private val paused = MutableStateFlow(false)
    @Volatile private var stopped = false
    private var counter = 0L

    override suspend fun prepare(): Boolean {
        if (tts != null) return true
        val ready = withTimeoutOrNull(8_000) {
            withContext(Dispatchers.Main) {
                suspendCancellableCoroutine { cont ->
                    var created: TextToSpeech? = null
                    created = TextToSpeech(context.applicationContext) { status ->
                        if (status == TextToSpeech.SUCCESS) {
                            tts = created
                            cont.resume(true)
                        } else {
                            runCatching { created?.shutdown() }
                            cont.resume(false)
                        }
                    }
                    cont.invokeOnCancellation { runCatching { created?.shutdown() } }
                }
            }
        } ?: false
        if (!ready) return false
        tts!!.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) {}
            override fun onDone(utteranceId: String?) = finish(utteranceId, Outcome.DONE)
            @Deprecated("Deprecated in Java")
            override fun onError(utteranceId: String?) = finish(utteranceId, Outcome.ERROR)
            override fun onError(utteranceId: String?, errorCode: Int) = finish(utteranceId, Outcome.ERROR)
            override fun onStop(utteranceId: String?, interrupted: Boolean) = finish(utteranceId, Outcome.STOPPED)
        })
        return true
    }

    private fun finish(id: String?, outcome: Outcome) {
        id?.let { pending.remove(it) }?.let { c -> if (c.isActive) c.resume(outcome) }
    }

    /** English (or requested language) voices that are installed, best quality first, stable order. */
    private fun candidateVoices(engine: TextToSpeech, language: String): List<Voice> {
        val lang = language.substringBefore('-').lowercase()
        return runCatching { engine.voices.orEmpty() }.getOrDefault(emptySet())
            .filter { it.locale.language.lowercase() == lang && !it.features.orEmpty().contains(TextToSpeech.Engine.KEY_FEATURE_NOT_INSTALLED) }
            .sortedWith(compareBy<Voice>({ it.isNetworkConnectionRequired }, { -it.quality }, { it.name }))
    }

    override suspend fun speak(text: String, params: SpeechParams, onSentence: (String) -> Unit) {
        val engine = tts ?: error("Android TTS not ready")
        val chunks = SentenceChunker.split(text)
        if (chunks.isEmpty()) return
        stopped = false
        paused.value = false

        val voices = candidateVoices(engine, params.language)
        val chosen = voices.getOrNull(params.nativeVoiceIndex.mod(voices.size.coerceAtLeast(1)))
        if (chosen != null) {
            runCatching { engine.voice = chosen }
            offline = !chosen.isNetworkConnectionRequired
        } else {
            runCatching { engine.language = Locale.forLanguageTag(params.language) }
        }
        engine.setPitch(params.pitch)
        engine.setSpeechRate(params.rate)
        val args = Bundle().apply { putFloat(TextToSpeech.Engine.KEY_PARAM_VOLUME, params.volume.coerceIn(0f, 1f)) }

        var i = 0
        while (i < chunks.size) {
            coroutineContext.ensureActive()
            if (stopped) return
            paused.first { !it } // suspends here while paused
            if (stopped) return
            onSentence(chunks[i].text)
            when (speakOne(engine, chunks[i].text, args)) {
                Outcome.DONE -> {
                    if (chunks[i].paragraphEnd) delay(280)
                    i++
                }
                Outcome.STOPPED -> if (!paused.value) return // interrupted; if paused, replay same sentence
                Outcome.ERROR -> error("Android TTS failed on sentence $i")
            }
        }
    }

    private suspend fun speakOne(engine: TextToSpeech, text: String, args: Bundle): Outcome =
        suspendCancellableCoroutine { cont ->
            val id = "pm-${counter++}"
            pending[id] = cont
            cont.invokeOnCancellation { pending.remove(id); runCatching { engine.stop() } }
            if (engine.speak(text, TextToSpeech.QUEUE_FLUSH, args, id) == TextToSpeech.ERROR) {
                pending.remove(id)
                if (cont.isActive) cont.resume(Outcome.ERROR)
            }
        }

    override fun pause() {
        paused.value = true
        runCatching { tts?.stop() } // current sentence reports STOPPED and is replayed on resume
    }

    override fun resume() { paused.value = false }

    override fun stop() {
        stopped = true
        paused.value = false
        runCatching { tts?.stop() }
    }

    override fun release() {
        stop()
        pending.clear()
        runCatching { tts?.shutdown() }
        tts = null
    }
}
