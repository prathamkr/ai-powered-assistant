package com.pocketmind.voice.integration

import com.pocketmind.voice.PocketMindVoiceEngine
import com.pocketmind.voice.model.VoiceEvent
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * THE integration contract. The main-AI developer implements this one function and nothing else:
 *
 *     PocketMindAi { userText -> myConversationEngine.reply(userText) }
 *
 * It receives what the user said (text) and returns what PocketMind should say (text).
 * The voice engine never produces answers itself.
 */
fun interface PocketMindAi {
    suspend fun respond(userText: String): String
}

data class Turn(val fromUser: Boolean, val text: String)

/**
 * Wires  mic -> STT -> [PocketMindAi] -> TTS -> speaker.
 *
 *  - Barge-in: tapping the mic while the assistant talks silences it and starts listening.
 *  - A new utterance cancels any in-flight AI request for the previous one.
 *  - [continuousMode] re-opens the mic automatically after each spoken reply.
 */
class PocketMindAIAdapter(
    private val engine: PocketMindVoiceEngine,
    private val ai: PocketMindAi,
    private val scope: CoroutineScope,
    var continuousMode: Boolean = false,
    private val errorReply: String = "Sorry, I ran into a problem. Please try again.",
) {
    private val _turns = MutableStateFlow<List<Turn>>(emptyList())
    /** Conversation transcript, handy for a chat UI. */
    val turns: StateFlow<List<Turn>> = _turns.asStateFlow()

    private var eventsJob: Job? = null
    private var turnJob: Job? = null

    /** Begin reacting to voice events. Call once (e.g. from your ViewModel's init). */
    fun start() {
        if (eventsJob?.isActive == true) return
        eventsJob = scope.launch {
            engine.events.collect { e ->
                when (e) {
                    is VoiceEvent.FinalTranscript -> handleUserText(e.text)
                    VoiceEvent.NoSpeechDetected -> if (continuousMode) Unit // stay idle; user taps mic again
                    else -> Unit
                }
            }
        }
    }

    fun stop() {
        eventsJob?.cancel(); turnJob?.cancel()
        engine.notifyProcessing(false)
    }

    /** Mic button behaviour: interrupt if the assistant is talking, otherwise listen. */
    suspend fun onMicPressed() {
        val phase = engine.state.value.phase
        when (phase) {
            com.pocketmind.voice.model.VoicePhase.Listening -> engine.stopListening()
            else -> {
                turnJob?.cancel()
                engine.stopSpeaking()
                engine.notifyProcessing(false)
                engine.startListening()
            }
        }
    }

    /** Use this to feed typed input through the same path (e.g. a text box). */
    fun submitText(text: String) = handleUserText(text)

    private fun handleUserText(text: String) {
        if (text.isBlank()) return
        turnJob?.cancel()
        _turns.update { it + Turn(true, text) }
        turnJob = scope.launch {
            engine.notifyProcessing(true)
            val reply = try {
                ai.respond(text)
            } catch (e: CancellationException) {
                engine.notifyProcessing(false)
                throw e
            } catch (t: Throwable) {
                errorReply
            }
            engine.notifyProcessing(false)
            if (reply.isBlank()) return@launch
            _turns.update { it + Turn(false, reply) }
            engine.speak(reply)
            if (continuousMode) {
                // Let the speaker tail / room echo die out so the mic does not transcribe our own voice.
                kotlinx.coroutines.delay(600)
                engine.startListening()
            }
        }
    }
}
