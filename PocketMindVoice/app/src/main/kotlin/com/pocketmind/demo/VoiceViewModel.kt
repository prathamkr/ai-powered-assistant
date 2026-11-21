package com.pocketmind.demo

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.pocketmind.voice.PocketMindVoiceEngine
import com.pocketmind.voice.VoiceEngine
import com.pocketmind.voice.integration.PocketMindAIAdapter
import kotlinx.coroutines.launch

class VoiceViewModel(app: Application) : AndroidViewModel(app) {

    val engine: PocketMindVoiceEngine = VoiceEngine(app)

    // Integration point: swap DemoAi for the real PocketMind AI.
    val adapter = PocketMindAIAdapter(engine, DemoAi(), viewModelScope)

    init {
        adapter.start()
        viewModelScope.launch { engine.initialize() }
        // Debug timeline of everything the engine does.
        viewModelScope.launch { engine.events.collect { android.util.Log.i("PMEvent", it.toString().take(90)) } }
        viewModelScope.launch {
            var last: Any? = null
            engine.state.collect { s -> if (s.phase != last) { last = s.phase; android.util.Log.i("PMEvent", "phase -> ${s.phase}  stt=${s.sttBackend.take(12)} tts=${s.ttsBackend.take(12)}") } }
        }
        viewModelScope.launch { adapter.turns.collect { t -> t.lastOrNull()?.let { android.util.Log.i("PMEvent", "turn user=${it.fromUser}: ${it.text.take(70)}") } } }
    }

    fun onMic() = viewModelScope.launch { adapter.onMicPressed() }

    fun setContinuous(on: Boolean) { adapter.continuousMode = on }

    override fun onCleared() {
        adapter.stop()
        engine.release()
    }
}
