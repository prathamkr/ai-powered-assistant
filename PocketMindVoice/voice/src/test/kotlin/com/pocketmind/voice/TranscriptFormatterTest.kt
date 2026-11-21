package com.pocketmind.voice

import com.pocketmind.voice.stt.TranscriptFormatter
import org.junit.Assert.assertEquals
import org.junit.Test

class TranscriptFormatterTest {
    @Test fun sentenceCasesShoutedText() =
        assertEquals("Tell me a long story", TranscriptFormatter.format("TELL ME A LONG STORY"))

    @Test fun fixesPronounI() {
        assertEquals("Send a message saying I will be late", TranscriptFormatter.format("SEND A MESSAGE SAYING I WILL BE LATE"))
        assertEquals("I'm late and I can't come", TranscriptFormatter.format("I'M LATE AND I CAN'T COME"))
    }

    @Test fun leavesAlreadyCasedTextAlone() =
        assertEquals("What's the weather like in Paris?", TranscriptFormatter.format("What's the weather like in Paris?"))

    @Test fun trimsAndCollapsesWhitespace() =
        assertEquals("Hello there", TranscriptFormatter.format("  HELLO   THERE "))

    @Test fun emptyStaysEmpty() = assertEquals("", TranscriptFormatter.format("   "))
}
