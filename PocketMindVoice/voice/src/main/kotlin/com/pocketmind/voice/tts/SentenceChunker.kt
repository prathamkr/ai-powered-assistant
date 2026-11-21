package com.pocketmind.voice.tts

/** One speakable unit. [paragraphEnd] means a longer pause should follow it. */
data class SpeechChunk(val text: String, val paragraphEnd: Boolean)

/**
 * Turns raw AI output (possibly markdown, multi-paragraph, very long) into sentence-sized chunks.
 * Sentence-aware boundaries keep interruptions clean and keep TTS latency low.
 */
object SentenceChunker {

    private const val MAX_CHUNK = 260
    private const val MIN_CHUNK = 24

    private val abbreviations = setOf("mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "st.", "vs.", "etc.", "e.g.", "i.e.", "no.")
    private val sentenceBreak = Regex("(?<=[.!?…])[\"')\\]]*\\s+")
    private val codeBlock = Regex("```.*?```", RegexOption.DOT_MATCHES_ALL)
    private val inlineCode = Regex("`([^`]*)`")
    private val link = Regex("\\[([^\\]]+)]\\([^)]*\\)")
    private val bareUrl = Regex("https?://\\S+")
    private val emoji = Regex("[\\p{So}\\p{Cs}\\u200d\\ufe0f]")
    private val mdDecor = Regex("(?m)^\\s{0,3}(#{1,6}|>|[-*+]|\\d+[.)])\\s+")
    private val emphasis = Regex("[*_~]{1,3}")

    /** Remove markup that would be read out loud as noise. */
    fun clean(raw: String): String = raw
        .replace(codeBlock, " code block omitted. ")
        .replace(inlineCode, "$1")
        .replace(link, "$1")
        .replace(bareUrl, "link")
        .replace(mdDecor, "")
        .replace(emphasis, "")
        .replace(emoji, "")
        .replace(' ', ' ')
        .replace(Regex("[ \\t]+"), " ")
        .trim()

    fun split(raw: String): List<SpeechChunk> {
        val cleaned = clean(raw)
        if (cleaned.isBlank()) return emptyList()
        val out = ArrayList<SpeechChunk>()
        val paragraphs = cleaned.split(Regex("\\n\\s*\\n|\\n")).map { it.trim() }.filter { it.isNotEmpty() }
        paragraphs.forEachIndexed { pi, para ->
            val sentences = mergeShort(splitSentences(para))
            sentences.forEachIndexed { si, s ->
                val last = si == sentences.lastIndex
                for ((i, piece) in hardWrap(s).withIndex()) {
                    out += SpeechChunk(piece, paragraphEnd = last && pi != paragraphs.lastIndex && i == hardWrap(s).lastIndex)
                }
            }
        }
        return out
    }

    private fun splitSentences(para: String): List<String> {
        val parts = para.split(sentenceBreak).map { it.trim() }.filter { it.isNotEmpty() }
        // Re-join pieces that were split after an abbreviation such as "Dr."
        val merged = ArrayList<String>()
        for (p in parts) {
            val prev = merged.lastOrNull()
            if (prev != null && abbreviations.any { prev.lowercase().endsWith(it) }) {
                merged[merged.lastIndex] = "$prev $p"
            } else merged += p
        }
        return merged
    }

    private fun mergeShort(sentences: List<String>): List<String> {
        val out = ArrayList<String>()
        for (s in sentences) {
            val prev = out.lastOrNull()
            if (prev != null && (prev.length < MIN_CHUNK) && prev.length + s.length < MAX_CHUNK) {
                out[out.lastIndex] = "$prev $s"
            } else out += s
        }
        return out
    }

    /** Split overly long sentences at commas/semicolons, then at spaces. */
    private fun hardWrap(s: String): List<String> {
        if (s.length <= MAX_CHUNK) return listOf(s)
        val out = ArrayList<String>()
        var rest = s
        while (rest.length > MAX_CHUNK) {
            val window = rest.substring(0, MAX_CHUNK)
            var cut = window.lastIndexOfAny(charArrayOf(',', ';', ':'))
            if (cut < MAX_CHUNK / 3) cut = window.lastIndexOf(' ')
            if (cut <= 0) cut = MAX_CHUNK - 1
            out += rest.substring(0, cut + 1).trim()
            rest = rest.substring(cut + 1).trim()
        }
        if (rest.isNotEmpty()) out += rest
        return out
    }
}
