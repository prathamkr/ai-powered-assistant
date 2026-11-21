package com.pocketmind.voice.tts

import android.util.Log
import com.k2fsa.sherpa.onnx.OfflineTts
import com.k2fsa.sherpa.onnx.OfflineTtsConfig
import com.k2fsa.sherpa.onnx.OfflineTtsModelConfig
import com.k2fsa.sherpa.onnx.OfflineTtsVitsModelConfig
import com.pocketmind.voice.audio.PcmStreamPlayer
import com.pocketmind.voice.model.SpeechParams
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.job
import kotlinx.coroutines.withContext
import java.io.File
import kotlin.coroutines.coroutineContext

/**
 * Offline neural TTS: sherpa-onnx running a Piper (VITS) model. Multi-speaker models map each
 * [com.pocketmind.voice.model.VoiceProfile] to a different speaker id.
 *
 * Streaming: audio is pushed to the AudioTrack as the model produces it, sentence by sentence,
 * so the first words play after roughly one sentence of generation time.
 *
 * Pitch: sherpa-onnx has no pitch control, so the track plays at `sampleRate * pitch` and the
 * generator speed is divided by `pitch` to keep the tempo. Formants shift slightly with pitch,
 * which is fine for +-25 %.
 */
class SherpaSpeechSynthesizer(private val modelDir: File) : SpeechSynthesizer {

    override val name = "Piper neural voice via sherpa-onnx (on-device)"
    override val isOffline = true

    private var tts: OfflineTts? = null
    @Volatile private var player: PcmStreamPlayer? = null
    @Volatile private var pausedFlag = false
    var numSpeakers: Int = 1
        private set

    override suspend fun prepare(): Boolean = withContext(Dispatchers.Default) {
        if (tts != null) return@withContext true
        try {
            val onnx = modelDir.listFiles()?.firstOrNull { it.extension == "onnx" }
                ?: return@withContext false
            val vits = OfflineTtsVitsModelConfig().apply {
                model = onnx.absolutePath
                tokens = File(modelDir, "tokens.txt").absolutePath
                dataDir = File(modelDir, "espeak-ng-data").absolutePath
                noiseScale = 0.667f
                noiseScaleW = 0.8f
                lengthScale = 1.0f
            }
            val model = OfflineTtsModelConfig().apply {
                this.vits = vits
                numThreads = 2
                debug = false
            }
            val t = OfflineTts(null, OfflineTtsConfig().apply { this.model = model })
            numSpeakers = t.numSpeakers().coerceAtLeast(1)
            tts = t
            true
        } catch (t: Throwable) {
            tts = null
            false
        }
    }

    override suspend fun speak(text: String, params: SpeechParams, onSentence: (String) -> Unit) {
        val engine = tts ?: error("TTS model not loaded")
        val chunks = SentenceChunker.split(text)
        if (chunks.isEmpty()) return

        val pitch = params.pitch.coerceIn(0.5f, 2f)
        val speed = (params.rate / pitch).coerceIn(0.4f, 2.5f)
        val sid = params.speakerId.coerceIn(0, numSpeakers - 1)
        val p = PcmStreamPlayer((engine.sampleRate() * pitch).toInt(), params.volume)
        player = p
        if (pausedFlag) p.pause()
        val job = coroutineContext.job
        val t0 = System.nanoTime()
        var firstAudioLogged = false
        try {
            withContext(Dispatchers.Default) {
                for (chunk in chunks) {
                    ensureActive()
                    if (p.isAborted) break
                    onSentence(chunk.text)
                    var samplesOut = 0
                    val g0 = System.nanoTime()
                    engine.generateWithCallback(chunk.text, sid, speed) { samples ->
                        if (!firstAudioLogged) {
                            firstAudioLogged = true
                            Log.i(TAG, "first audio after ${(System.nanoTime() - t0) / 1_000_000} ms")
                        }
                        samplesOut += samples.size
                        // Return 1 to continue, 0 to make the generator stop right away.
                        if (job.isActive && p.write(samples)) 1 else 0
                    }
                    val audioMs = samplesOut * 1000L / (engine.sampleRate() * pitch).toInt()
                    Log.i(TAG, "chunk ${chunk.text.length} chars: audio ${audioMs} ms, wall ${(System.nanoTime() - g0) / 1_000_000} ms")
                    if (chunk.paragraphEnd && !p.isAborted) p.writeSilence(280)
                }
                // Wait until the audio has really been played: never cut off the last sentence.
                if (!p.isAborted) p.drain()
            }
        } finally {
            p.release()
            if (player === p) player = null
        }
    }

    override fun pause() { pausedFlag = true; player?.pause() }
    override fun resume() { pausedFlag = false; player?.resume() }
    override fun stop() { pausedFlag = false; player?.abort() }

    override fun release() {
        stop()
        tts?.release()
        tts = null
    }

    private companion object { const val TAG = "PMVoice" }
}
