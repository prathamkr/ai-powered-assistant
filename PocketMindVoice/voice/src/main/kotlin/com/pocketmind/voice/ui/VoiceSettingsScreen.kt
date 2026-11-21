package com.pocketmind.voice.ui

import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.CloudOff
import androidx.compose.material.icons.rounded.Cloud
import androidx.compose.material.icons.rounded.Pause
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.Stop
import androidx.compose.material.icons.automirrored.rounded.VolumeUp
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.pocketmind.voice.PocketMindVoiceEngine
import com.pocketmind.voice.model.VoicePhase
import com.pocketmind.voice.model.VoiceProfile
import com.pocketmind.voice.model.VoiceProfiles
import com.pocketmind.voice.model.VoiceSettings
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch
import kotlin.math.roundToInt

/**
 * Self-contained voice settings: backend / offline status, model download, voice personalities,
 * pitch / speed / volume, preview and stop. Works with any [PocketMindVoiceEngine].
 * Uses the host app's MaterialTheme, so dark / light just work.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun VoiceSettingsScreen(engine: PocketMindVoiceEngine, onBack: () -> Unit, modifier: Modifier = Modifier) {
    val state by engine.state.collectAsState()
    val s by engine.settings.collectAsState()
    val scope = rememberCoroutineScope()

    var downloading by remember { mutableStateOf<String?>(null) }
    var progress by remember { mutableStateOf(0f) }
    var downloadError by remember { mutableStateOf<String?>(null) }

    Scaffold(
        modifier = modifier,
        topBar = {
            TopAppBar(
                title = { Text("Voice") },
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Rounded.ArrowBack, "Back") } },
            )
        },
    ) { pad ->
        Column(
            Modifier.padding(pad).verticalScroll(rememberScrollState()).padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(20.dp),
        ) {
            // ---------- engine status ----------
            Section("Engine") {
                StatusRow("Listening", state.sttBackend, state.sttOffline)
                StatusRow("Speaking", state.ttsBackend, state.ttsOffline)
                if (!state.offlineModelsInstalled) {
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "Natural offline voices are not installed. Using the phone's built-in engines (works, but sounds more robotic and speech recognition may need internet).",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(8.dp))
                    val busy = downloading != null
                    Button(
                        enabled = !busy,
                        onClick = {
                            downloadError = null
                            scope.launch {
                                try {
                                    engine.downloadOfflineModels { stage, f -> downloading = stage; progress = f }
                                } catch (e: CancellationException) { throw e
                                } catch (e: Exception) { downloadError = e.message
                                } finally { downloading = null }
                            }
                        },
                    ) { Text(if (busy) "Downloading…" else "Download offline voices (~80 MB)") }
                    downloading?.let {
                        Spacer(Modifier.height(8.dp))
                        Text("$it  ${(progress * 100).roundToInt()}%", style = MaterialTheme.typography.labelMedium)
                        LinearProgressIndicator(progress = { progress }, Modifier.fillMaxWidth().padding(top = 4.dp))
                    }
                    downloadError?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
                }
                Row(Modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("Prefer offline", style = MaterialTheme.typography.bodyLarge)
                        Text("Avoid network speech services", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Switch(checked = s.preferOffline, onCheckedChange = engine::setPreferOffline)
                }
            }

            // ---------- personalities ----------
            Section("Voice") {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    VoiceProfiles.all.forEach { p ->
                        ProfileCard(p, selected = p.id == s.profileId) {
                            engine.setVoiceProfile(p)
                            scope.launch { engine.previewVoice() }
                        }
                    }
                }
            }

            // ---------- tuning ----------
            Section("Fine tune") {
                LabeledSlider("Pitch", "%.2f×".format(s.pitch), s.pitch, VoiceSettings.PITCH_MIN..VoiceSettings.PITCH_MAX, engine::setPitch)
                LabeledSlider("Speed", "%.2f×".format(s.speechRate), s.speechRate, VoiceSettings.RATE_MIN..VoiceSettings.RATE_MAX, engine::setSpeechRate)
                LabeledSlider("Volume", "${(s.volume * 100).roundToInt()}%", s.volume, 0f..1f, engine::setVolume)
                if (state.ttsOffline && state.ttsBackend.contains("Piper")) {
                    Row(Modifier.fillMaxWidth().padding(top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text("Speaker #${s.speakerId}", style = MaterialTheme.typography.bodyLarge)
                            Text("The offline model has 904 voices — step through to audition", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        OutlinedButton(onClick = { engine.setSpeakerId((s.speakerId - 1).coerceAtLeast(0)); scope.launch { engine.previewVoice() } }) { Text("−") }
                        Spacer(Modifier.width(8.dp))
                        OutlinedButton(onClick = { engine.setSpeakerId(s.speakerId + 1); scope.launch { engine.previewVoice() } }) { Text("+") }
                    }
                }
            }

            // ---------- transport ----------
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                val speaking = state.phase == VoicePhase.Speaking
                val paused = state.phase == VoicePhase.Paused
                Button(modifier = Modifier.weight(1f), onClick = { scope.launch { engine.previewVoice() } }) {
                    Icon(Icons.AutoMirrored.Rounded.VolumeUp, null); Spacer(Modifier.width(8.dp)); Text("Preview")
                }
                FilledTonalButton(
                    modifier = Modifier.weight(1f), enabled = speaking || paused,
                    onClick = { scope.launch { if (paused) engine.resumeSpeaking() else engine.pauseSpeaking() } },
                ) {
                    Icon(if (paused) Icons.Rounded.PlayArrow else Icons.Rounded.Pause, null)
                    Spacer(Modifier.width(8.dp)); Text(if (paused) "Resume" else "Pause")
                }
                FilledTonalButton(modifier = Modifier.weight(1f), enabled = speaking || paused, onClick = { scope.launch { engine.stopSpeaking() } }) {
                    Icon(Icons.Rounded.Stop, null); Spacer(Modifier.width(8.dp)); Text("Stop")
                }
            }
            state.error?.let {
                Text(it.message, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium)
            }
            Spacer(Modifier.height(24.dp))
        }
    }
}

@Composable
private fun Section(title: String, content: @Composable () -> Unit) {
    Column {
        Text(title, style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.primary, modifier = Modifier.padding(bottom = 8.dp, start = 4.dp))
        Card(
            colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer),
            shape = RoundedCornerShape(20.dp),
        ) { Column(Modifier.padding(16.dp)) { content() } }
    }
}

@Composable
private fun StatusRow(label: String, backend: String, offline: Boolean) {
    Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(if (backend == "-") "Not loaded yet" else backend, style = MaterialTheme.typography.bodyMedium)
        }
        OfflineBadge(offline = offline, known = backend != "-")
    }
}

@Composable
fun OfflineBadge(offline: Boolean, known: Boolean = true) {
    val color = when {
        !known -> MaterialTheme.colorScheme.outline
        offline -> MaterialTheme.colorScheme.primary
        else -> MaterialTheme.colorScheme.error
    }
    Surface(shape = RoundedCornerShape(50), color = color.copy(alpha = 0.14f)) {
        Row(Modifier.padding(horizontal = 10.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(if (!known) Icons.Rounded.Cloud else if (offline) Icons.Rounded.CheckCircle else Icons.Rounded.CloudOff, null, Modifier.size(14.dp), color)
            Spacer(Modifier.width(6.dp))
            Text(if (!known) "—" else if (offline) "Offline" else "Online", style = MaterialTheme.typography.labelMedium, color = color)
        }
    }
}

@Composable
private fun ProfileCard(p: VoiceProfile, selected: Boolean, onClick: () -> Unit) {
    val border by animateColorAsState(if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outlineVariant, label = "border")
    Surface(
        shape = RoundedCornerShape(16.dp),
        color = if (selected) MaterialTheme.colorScheme.primary.copy(alpha = 0.08f) else MaterialTheme.colorScheme.surface,
        border = BorderStroke(if (selected) 2.dp else 1.dp, border),
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
    ) {
        Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(p.displayName, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                Text(p.tagline, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            if (selected) Icon(Icons.Rounded.CheckCircle, "Selected", tint = MaterialTheme.colorScheme.primary)
        }
    }
}

@Composable
private fun LabeledSlider(label: String, valueText: String, value: Float, range: ClosedFloatingPointRange<Float>, onChange: (Float) -> Unit) {
    Column(Modifier.padding(vertical = 2.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(label, style = MaterialTheme.typography.bodyLarge)
            Text(valueText, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Slider(value = value, onValueChange = onChange, valueRange = range)
    }
}
