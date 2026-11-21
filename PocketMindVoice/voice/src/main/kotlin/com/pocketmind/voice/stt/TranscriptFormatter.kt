package com.pocketmind.voice.stt

/**
 * The offline recognizer emits ALL-CAPS words without punctuation. The main AI should receive
 * natural text, so this lower-cases, capitalizes the first letter and fixes the pronoun "I".
 * (Punctuation cannot be recovered reliably, so none is added.)
 */
object TranscriptFormatter {

    private val pronounI = Regex("\\bi\\b(?=$|\\s|')")

    fun format(raw: String): String {
        val t = raw.trim().replace(Regex("\\s+"), " ")
        if (t.isEmpty()) return t
        // Only touch text that looks shouty; leave already-cased text (e.g. from Android's recognizer) alone.
        val letters = t.filter { it.isLetter() }
        val shouting = letters.isNotEmpty() && letters.all { it.isUpperCase() }
        if (!shouting) return t
        val lower = t.lowercase().replace(pronounI, "I")
        return lower.replaceFirstChar { it.uppercaseChar() }
    }
}
