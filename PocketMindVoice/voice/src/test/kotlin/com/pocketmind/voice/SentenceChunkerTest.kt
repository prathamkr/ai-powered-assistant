package com.pocketmind.voice

import com.pocketmind.voice.tts.SentenceChunker
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SentenceChunkerTest {

    @Test fun splitsSentences() {
        val c = SentenceChunker.split("Hello there, how are you doing today? I am doing really well, thank you. Thanks for asking about it!")
        assertEquals(3, c.size)
        assertEquals("Hello there, how are you doing today?", c[0].text)
    }

    @Test fun mergesVeryShortSentencesToAvoidChoppySpeech() {
        val c = SentenceChunker.split("Hello there, how are you doing today? I am fine. Thanks for asking about it!")
        assertEquals(2, c.size)
        assertEquals("I am fine. Thanks for asking about it!", c[1].text)
    }

    @Test fun keepsLastSentence() {
        val c = SentenceChunker.split("First sentence is long enough here. And the very last one without a period")
        assertEquals("And the very last one without a period", c.last().text)
    }

    @Test fun doesNotSplitAfterAbbreviation() {
        val c = SentenceChunker.split("Please call Dr. Smith about the appointment tomorrow morning.")
        assertEquals(1, c.size)
    }

    @Test fun paragraphsGetLongPause() {
        val c = SentenceChunker.split("This is paragraph one and it is fine.\n\nThis is paragraph two and it ends.")
        assertEquals(2, c.size)
        assertTrue(c[0].paragraphEnd)
        assertFalse(c[1].paragraphEnd)
    }

    @Test fun stripsMarkdownAndUrls() {
        val c = SentenceChunker.split("## Title\n**Bold** text with a [link](https://x.y) and https://example.com/a here.")
        val joined = c.joinToString(" ") { it.text }
        assertFalse(joined.contains("*"))
        assertFalse(joined.contains("http"))
        assertFalse(joined.contains("#"))
        assertTrue(joined.contains("link"))
    }

    @Test fun longTextIsBoundedAndLossless() {
        val sentence = "word ".repeat(200).trim() + "."
        val c = SentenceChunker.split(sentence)
        assertTrue(c.all { it.text.length <= 260 })
        assertEquals(200, c.joinToString(" ") { it.text }.split(" ").size)
    }

    @Test fun blankGivesNothing() {
        assertTrue(SentenceChunker.split("  \n ").isEmpty())
    }
}
