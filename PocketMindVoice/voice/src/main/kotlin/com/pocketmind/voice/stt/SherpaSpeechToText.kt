package com.pocketmind.voice.stt

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import android.media.audiofx.AutomaticGainControl
import android.media.audiofx.NoiseSuppressor
import com.k2fsa.sherpa.onnx.EndpointConfig
import com.k2fsa.sherpa.onnx.EndpointRule
import com.k2fsa.sherpa.onnx.FeatureConfig
import com.k2fsa.sherpa.onnx.OnlineModelConfig
import com.k2fsa.sherpa.onnx.OnlineRecognizer
import com.k2fsa.sherpa.onnx.OnlineRecognizerConfig
import com.k2fsa.sherpa.onnx.OnlineTransducerModelConfig
import com.pocketmind.voice.model.SpeechResult
import com.pocketmind.voice.model.VoiceError
import com.pocketmind.voice.model.VoiceErrorCode
import com.pocketmind.voice.model.VoiceException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.withContext
import java.io.File

/**
 * Fully offline streaming recognizer (sherpa-onnx, streaming Zipformer transducer, English).
 *
 * RAM: ~150 MB while loaded. Latency: partial text every 100 ms. CPU: 2 threads.
 * The model directory comes from [com.pocketmind.voice.models.ModelManager].
 */
class SherpaSpeechToText(private val modelDir: File) : SpeechToText {

    override val name = "sherpa-onnx Zipformer (on-device)"
    override val isOffline = true

    private var recognizer: OnlineRecognizer? = null
    @Volatile private var finishRequested = false

    /** Finds e.g. encoder*.onnx; prefers an int8 file when the pack ships both. */
    private fun find(prefix: String): String {
        val candidates = modelDir.listFiles { f -> f.name.startsWith(prefix) && f.name.endsWith(".onnx") }.orEmpty()
        val f = candidates.firstOrNull { it.name.contains("int8") } ?: candidates.firstOrNull()
            ?: throw IllegalStateException("Missing $prefix*.onnx in ${modelDir.path}")
        return f.absolutePath
    }

    override suspend fun prepare(): Boolean = withContext(Dispatchers.Default) {
        if (recognizer != null) return@withContext true
        try {
            val transducer = OnlineTransducerModelConfig().apply {
                encoder = find("encoder")
                decoder = find("decoder")
                joiner = find("joiner")
            }
            val model = OnlineModelConfig().apply {
                this.transducer = transducer
                tokens = File(modelDir, "tokens.txt").absolutePath
                numThreads = 2 // model type is auto-detected from the ONNX metadata (verified with the CLI)
            }
            val cfg = OnlineRecognizerConfig().apply {
                featConfig = FeatureConfig().apply { sampleRate = SAMPLE_RATE; featureDim = 80 }
                modelConfig = model
                enableEndpoint = true
                decodingMethod = "greedy_search"
                // rule1: no speech at all for 3.5 s (incl. our 0.5 s lead-in) -> give up.
                // rule2: 1.1 s silence after speech -> done. rule3: hard cap on utterance length.
                endpointConfig = EndpointConfig(
                    EndpointRule(false, 3.5f, 0.0f),
                    EndpointRule(true, 1.1f, 0.0f),
                    EndpointRule(false, 0.0f, 20.0f),
                )
            }
            recognizer = OnlineRecognizer(null, cfg)
            true
        } catch (t: Throwable) {
            recognizer = null
            false
        }
    }

    override fun finish() { finishRequested = true }

    @SuppressLint("MissingPermission") // permission is checked by the engine before listen()
    override fun listen(language: String): Flow<SpeechResult> = flow {
        val rec = recognizer ?: throw VoiceException(VoiceError(VoiceErrorCode.MODEL_ERROR, "Speech model not loaded"))
        finishRequested = false

        val minBuf = AudioRecord.getMinBufferSize(SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val record = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION, // tuned for ASR; no heavy AGC colouring
            SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT,
            maxOf(minBuf, SAMPLE_RATE * 2),
        )
        if (record.state != AudioRecord.STATE_INITIALIZED) {
            record.release()
            throw VoiceException(VoiceError(VoiceErrorCode.AUDIO_ERROR, "Microphone could not be opened (in use?)"))
        }
        // Basic noise handling: platform effects when the device offers them.
        val effects = buildList {
            if (NoiseSuppressor.isAvailable()) add(NoiseSuppressor.create(record.audioSessionId))
            if (AutomaticGainControl.isAvailable()) add(AutomaticGainControl.create(record.audioSessionId))
            if (AcousticEchoCanceler.isAvailable()) add(AcousticEchoCanceler.create(record.audioSessionId))
        }.filterNotNull()

        val stream = rec.createStream("")
        try {
            // Lead-in silence: streaming models need some left context, and the mic takes a moment to
            // start. Without this the first word(s) were dropped (benchmark: first word wrong 12/12
            // -> 0/12 once the model was swapped; padding alone cut errors ~2x on every model).
            stream.acceptWaveform(FloatArray(LEAD_SAMPLES), SAMPLE_RATE)
            record.startRecording()
            val shorts = ShortArray(SAMPLE_RATE / 10) // 100 ms
            val floats = FloatArray(shorts.size)
            var last = ""
            val started = System.currentTimeMillis()
            while (true) {
                currentCoroutineContext().ensureActive()
                val n = record.read(shorts, 0, shorts.size)
                if (n < 0) throw VoiceException(VoiceError(VoiceErrorCode.AUDIO_ERROR, "Microphone read failed ($n)"))
                for (i in 0 until n) floats[i] = shorts[i] / 32768f
                stream.acceptWaveform(if (n == floats.size) floats else floats.copyOf(n), SAMPLE_RATE)
                while (rec.isReady(stream)) rec.decode(stream)

                val text = rec.getResult(stream).text.trim()
                if (text != last) { last = text; emit(SpeechResult.Partial(text)) }

                if (rec.isEndpoint(stream) || finishRequested || System.currentTimeMillis() - started > MAX_MS) break
            }
            // Flush: tail silence lets the model emit the last word, then tell it no more audio is coming.
            stream.acceptWaveform(FloatArray(TAIL_SAMPLES), SAMPLE_RATE)
            stream.inputFinished()
            while (rec.isReady(stream)) rec.decode(stream)
            val finalText = rec.getResult(stream).text.trim()
            emit(if (finalText.isEmpty()) SpeechResult.NoSpeech else SpeechResult.Final(finalText))
        } finally {
            runCatching { record.stop() }
            effects.forEach { runCatching { it.release() } }
            record.release()
            stream.release()
        }
    }.flowOn(Dispatchers.Default)

    override fun release() {
        recognizer?.release()
        recognizer = null
    }

    private companion object {
        const val SAMPLE_RATE = 16_000
        const val MAX_MS = 30_000L
        const val LEAD_SAMPLES = SAMPLE_RATE / 2          // 0.5 s
        const val TAIL_SAMPLES = SAMPLE_RATE * 4 / 10     // 0.4 s
    }
}
