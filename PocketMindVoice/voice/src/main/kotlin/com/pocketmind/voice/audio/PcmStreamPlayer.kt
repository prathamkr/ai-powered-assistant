package com.pocketmind.voice.audio

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import kotlinx.coroutines.delay

/**
 * Streams float PCM to an [AudioTrack] for ONE utterance.
 *
 * - [write] blocks (back-pressure) so a generator can run just ahead of playback.
 * - [pause]/[resume] are instant (they act on the track, not on the generator).
 * - [abort] unblocks a pending [write] immediately (used for interrupts).
 * - [drain] waits until the audio has actually been *played*, so the last sentence is never cut off.
 *
 * Pitch trick: the track is created at `sampleRate * pitch`, which raises/lowers pitch. The caller
 * compensates tempo by generating at `rate / pitch`.
 */
class PcmStreamPlayer(sampleRate: Int, volume: Float) {

    private val track: AudioTrack
    @Volatile private var aborted = false
    @Volatile private var paused = false
    @Volatile private var started = false
    @Volatile private var released = false
    private var framesWritten = 0L
    private val rate = sampleRate

    init {
        val minBytes = AudioTrack.getMinBufferSize(sampleRate, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_FLOAT)
        val twoSeconds = sampleRate * 4 * 2
        track = AudioTrack.Builder()
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ASSISTANT)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build()
            )
            .setAudioFormat(
                AudioFormat.Builder()
                    .setEncoding(AudioFormat.ENCODING_PCM_FLOAT)
                    .setSampleRate(sampleRate)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                    .build()
            )
            .setBufferSizeInBytes(maxOf(minBytes, twoSeconds))
            .setTransferMode(AudioTrack.MODE_STREAM)
            .build()
        track.setVolume(volume.coerceIn(0f, 1f))
    }

    val isAborted get() = aborted

    /** @return false when aborted (caller should stop generating). */
    fun write(samples: FloatArray): Boolean {
        if (aborted || released) return false
        if (!started) {
            started = true
            if (!paused) track.play()
        }
        var off = 0
        while (off < samples.size) {
            if (aborted || released) return false
            val n = track.write(samples, off, samples.size - off, AudioTrack.WRITE_BLOCKING)
            if (n < 0) return false // dead object / invalid operation after abort
            off += n
            framesWritten += n
        }
        return !aborted
    }

    fun writeSilence(ms: Int): Boolean = write(FloatArray(rate * ms / 1000))

    fun pause() {
        paused = true
        if (started && !released) runCatching { track.pause() }
    }

    fun resume() {
        paused = false
        if (started && !released && !aborted) runCatching { track.play() }
    }

    /** Safe to call from any thread. Unblocks a writer that is waiting for buffer space. */
    fun abort() {
        aborted = true
        if (released) return
        runCatching { track.pause() }
        runCatching { track.flush() }
    }

    /** Suspends until every written frame has been played, or abort/stall. */
    suspend fun drain() {
        if (!started) return
        var lastHead = -1
        var stalledMs = 0
        while (!aborted && !released) {
            val head = track.playbackHeadPosition
            if (head.toLong() >= framesWritten) return
            if (paused) { stalledMs = 0 } else {
                if (head == lastHead) stalledMs += 20 else stalledMs = 0
                if (stalledMs > 2000) return // device stopped consuming; do not hang forever
            }
            lastHead = head
            delay(20)
        }
    }

    fun release() {
        if (released) return
        released = true
        runCatching { track.pause() }
        runCatching { track.flush() }
        runCatching { track.release() }
    }
}
