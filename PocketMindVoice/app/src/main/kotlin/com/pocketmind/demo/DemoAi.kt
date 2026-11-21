package com.pocketmind.demo

import com.pocketmind.voice.integration.PocketMindAi
import kotlinx.coroutines.delay

/**
 * STAND-IN for the real PocketMind AI, used only to demo and test the voice pipeline.
 * It is NOT intelligent. The main-AI developer replaces this with their engine:
 *
 *     PocketMindAIAdapter(engine, PocketMindAi { text -> theirEngine.reply(text) }, scope)
 */
class DemoAi : PocketMindAi {
    override suspend fun respond(userText: String): String {
        delay(600) // simulate thinking so the "Thinking" state is visible
        val t = userText.lowercase()
        return when {
            "long" in t || "story" in t -> LONG_REPLY
            "hello" in t || "hi " in t || t == "hi" -> "Hello! I'm PocketMind. It's good to hear you."
            "time" in t -> "I can't see a clock in this demo, but the real assistant will know."
            else -> "You said: $userText. This is a demo reply, so the real PocketMind AI is not connected yet."
        }
    }

    private companion object {
        val LONG_REPLY = """
            Here is a longer reply to test sentence-by-sentence playback. It has several sentences, and a few commas, so the pauses sound natural.

            This is the second paragraph. There should be a slightly longer pause before it begins. Dr. Smith's appointment is at nine, and that abbreviation must not be treated as the end of a sentence.

            Finally, this is the very last sentence, and it should be spoken completely, without being cut off at the end.
        """.trimIndent()
    }
}
