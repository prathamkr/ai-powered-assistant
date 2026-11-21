package com.pocketmind.voice.stt

import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import com.pocketmind.voice.model.SpeechResult
import com.pocketmind.voice.model.VoiceError
import com.pocketmind.voice.model.VoiceErrorCode
import com.pocketmind.voice.model.VoiceException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.withContext

/**
 * Fallback STT using Android's platform [SpeechRecognizer].
 *
 * Honest offline status: only an *on-device* recognizer (API 33+ and the language pack installed)
 * is reported as offline. A normal recognizer may use Google's servers, so it is reported as online.
 */
class AndroidSpeechToText(
    private val context: Context,
    private val preferOffline: () -> Boolean,
) : SpeechToText {

    override val name: String get() = if (isOffline) "Android on-device recognizer" else "Android SpeechRecognizer (may use network)"
    override var isOffline: Boolean = false
        private set

    private var recognizer: SpeechRecognizer? = null

    override suspend fun prepare(): Boolean = withContext(Dispatchers.Main) {
        val onDevice = Build.VERSION.SDK_INT >= 33 && SpeechRecognizer.isOnDeviceRecognitionAvailable(context)
        isOffline = onDevice && preferOffline()
        onDevice || SpeechRecognizer.isRecognitionAvailable(context)
    }

    override fun finish() {
        // stopListening() makes the recognizer deliver results for the audio captured so far.
        android.os.Handler(android.os.Looper.getMainLooper()).post { runCatching { recognizer?.stopListening() } }
    }

    override fun listen(language: String): Flow<SpeechResult> = callbackFlow {
        val sr = if (isOffline && Build.VERSION.SDK_INT >= 33) {
            SpeechRecognizer.createOnDeviceSpeechRecognizer(context)
        } else {
            SpeechRecognizer.createSpeechRecognizer(context)
        }
        recognizer = sr
        sr.setRecognitionListener(object : RecognitionListener {
            override fun onReadyForSpeech(params: Bundle?) {}
            override fun onBeginningOfSpeech() {}
            override fun onRmsChanged(rmsdB: Float) {}
            override fun onBufferReceived(buffer: ByteArray?) {}
            override fun onEndOfSpeech() {}
            override fun onEvent(eventType: Int, params: Bundle?) {}

            override fun onPartialResults(partialResults: Bundle?) {
                val t = partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()
                if (!t.isNullOrBlank()) trySend(SpeechResult.Partial(t))
            }

            override fun onResults(results: Bundle?) {
                val t = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.trim()
                trySend(if (t.isNullOrEmpty()) SpeechResult.NoSpeech else SpeechResult.Final(t))
                close()
            }

            override fun onError(error: Int) {
                when (error) {
                    SpeechRecognizer.ERROR_NO_MATCH, SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> {
                        trySend(SpeechResult.NoSpeech); close()
                    }
                    SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> close(
                        VoiceException(VoiceError(VoiceErrorCode.PERMISSION_DENIED, "Microphone permission denied"))
                    )
                    SpeechRecognizer.ERROR_NETWORK, SpeechRecognizer.ERROR_NETWORK_TIMEOUT,
                    SpeechRecognizer.ERROR_SERVER -> close(
                        VoiceException(VoiceError(VoiceErrorCode.NETWORK, "Speech recognition needs a network connection (offline language pack not installed)"))
                    )
                    SpeechRecognizer.ERROR_CLIENT -> close() // we cancelled it ourselves
                    SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> close(
                        VoiceException(VoiceError(VoiceErrorCode.AUDIO_ERROR, "Recognizer busy, try again"))
                    )
                    else -> close(VoiceException(VoiceError(VoiceErrorCode.STT_UNAVAILABLE, "Recognizer error $error")))
                }
            }
        })
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, language)
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
            putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, preferOffline())
            putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, context.packageName)
        }
        sr.startListening(intent)
        awaitClose {
            runCatching { sr.cancel() }
            runCatching { sr.destroy() }
            if (recognizer === sr) recognizer = null
        }
    }.flowOn(Dispatchers.Main) // SpeechRecognizer must be used from the main thread

    override fun release() {
        recognizer?.let { r -> android.os.Handler(android.os.Looper.getMainLooper()).post { runCatching { r.destroy() } } }
        recognizer = null
    }
}
