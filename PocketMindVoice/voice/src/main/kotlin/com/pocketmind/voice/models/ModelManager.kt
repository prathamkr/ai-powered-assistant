package com.pocketmind.voice.models

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import org.apache.commons.compress.archivers.tar.TarArchiveInputStream
import org.apache.commons.compress.compressors.bzip2.BZip2CompressorInputStream
import java.io.BufferedInputStream
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import kotlin.coroutines.coroutineContext

/** A downloadable offline model. [keep] filters archive entries (relative path) to store. */
data class ModelPack(
    val id: String,
    val title: String,
    val url: String,
    val archiveSizeMb: Int,
    val keep: (relativePath: String) -> Boolean = { true },
)

object ModelPacks {
    private const val BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download"

    /**
     * Kroko streaming Zipformer, English (Banafo, 2025), community model licensed CC-BY-SA
     * (attribution required; a commercial product should use Kroko's commercial models).
     * Chosen by benchmark: ~6-16 % WER vs 42-69 % for the older zipformer-20M we shipped first,
     * with the same speed and a 55 MB download. See README "Choosing the recognizer".
     */
    val AsrZipformerEn = ModelPack(
        id = "asr-kroko-en-2025",
        title = "Speech recognition (English)",
        url = "$BASE/asr-models/sherpa-onnx-streaming-zipformer-en-kroko-2025-08-06.tar.bz2",
        archiveSizeMb = 55,
        keep = { p -> p == "tokens.txt" || (p.endsWith(".onnx") && !p.contains('/')) },
    )

    /** Directories of retired model packs; removed on the next install to free storage. */
    val legacyIds = listOf("asr-zipformer-en-20m")

    /** Piper VITS, libritts_r, 904 speakers, int8 (~22 MB). Needs espeak-ng-data. */
    val TtsPiperLibriTts = ModelPack(
        id = "tts-piper-libritts-r-int8",
        title = "Natural voices (multi-speaker)",
        url = "$BASE/tts-models/vits-piper-en_US-libritts_r-medium-int8.tar.bz2",
        archiveSizeMb = 22,
        keep = { !it.endsWith(".json") && it != "MODEL_CARD" },
    )

    val all = listOf(TtsPiperLibriTts, AsrZipformerEn)
}

class ModelManager(context: Context) {

    private val root = File(context.filesDir, "voice-models")

    fun dir(pack: ModelPack) = File(root, pack.id)
    private fun marker(pack: ModelPack) = File(dir(pack), ".complete")

    fun isInstalled(pack: ModelPack) = marker(pack).exists()
    fun allInstalled() = ModelPacks.all.all(::isInstalled)

    fun delete(pack: ModelPack) {
        dir(pack).deleteRecursively()
    }

    /**
     * Downloads and extracts [pack]. Cancellable. Partial downloads are removed on failure.
     * @param onProgress 0..1 (download = 0..0.85, extraction = 0.85..1)
     */
    suspend fun install(pack: ModelPack, onProgress: (Float) -> Unit) = withContext(Dispatchers.IO) {
        ModelPacks.legacyIds.forEach { File(root, it).deleteRecursively() }
        if (isInstalled(pack)) return@withContext
        root.mkdirs()
        val archive = File(root, "${pack.id}.tar.bz2.part")
        val target = dir(pack)
        try {
            download(pack.url, archive) { onProgress(it * 0.85f) }
            target.deleteRecursively()
            target.mkdirs()
            extract(archive, target, pack.keep) { onProgress(0.85f + it * 0.15f) }
            marker(pack).writeText("ok")
        } catch (t: Throwable) {
            target.deleteRecursively()
            throw t
        } finally {
            archive.delete()
        }
    }

    private suspend fun download(url: String, out: File, onProgress: (Float) -> Unit) {
        var conn = URL(url).openConnection() as HttpURLConnection
        conn.connectTimeout = 15_000
        conn.readTimeout = 30_000
        conn.instanceFollowRedirects = true
        try {
            if (conn.responseCode !in 200..299) error("HTTP ${conn.responseCode} for $url")
            val total = conn.contentLengthLong
            var done = 0L
            conn.inputStream.use { input ->
                out.outputStream().buffered().use { sink ->
                    val buf = ByteArray(64 * 1024)
                    while (true) {
                        coroutineContext.ensureActive()
                        val n = input.read(buf)
                        if (n < 0) break
                        sink.write(buf, 0, n)
                        done += n
                        if (total > 0) onProgress((done.toFloat() / total).coerceIn(0f, 1f))
                    }
                }
            }
            if (total > 0 && done != total) error("Incomplete download ($done of $total bytes)")
        } finally {
            conn.disconnect()
        }
    }

    private suspend fun extract(archive: File, target: File, keep: (String) -> Boolean, onProgress: (Float) -> Unit) {
        val canonicalTarget = target.canonicalPath + File.separator
        val total = archive.length().coerceAtLeast(1)
        val counting = CountingStream(archive.inputStream())
        val raw = BufferedInputStream(counting)
        TarArchiveInputStream(BZip2CompressorInputStream(raw)).use { tar ->
            while (true) {
                coroutineContext.ensureActive()
                val entry = tar.nextEntry ?: break
                // Strip the single top-level folder of the archive.
                val rel = entry.name.substringAfter('/', "").trimStart('/')
                if (rel.isEmpty() || entry.isDirectory || !keep(rel)) continue
                val dest = File(target, rel)
                if (!dest.canonicalPath.startsWith(canonicalTarget)) continue // zip-slip guard
                dest.parentFile?.mkdirs()
                dest.outputStream().buffered().use { tar.copyTo(it) }
                onProgress((counting.count.toFloat() / total).coerceIn(0f, 1f))
            }
        }
    }

    private class CountingStream(private val inner: java.io.InputStream) : java.io.InputStream() {
        var count = 0L
        override fun read(): Int = inner.read().also { if (it >= 0) count++ }
        override fun read(b: ByteArray, off: Int, len: Int): Int = inner.read(b, off, len).also { if (it > 0) count += it }
        override fun close() = inner.close()
    }
}
