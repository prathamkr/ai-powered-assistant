package com.pocketmind.demo

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Tune
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.pocketmind.voice.integration.Turn
import com.pocketmind.voice.model.VoiceErrorCode
import com.pocketmind.voice.model.VoicePhase
import com.pocketmind.voice.ui.MicButton
import com.pocketmind.voice.ui.OfflineBadge
import com.pocketmind.voice.ui.VoiceSettingsScreen
import com.pocketmind.voice.ui.label

class MainActivity : ComponentActivity() {

    private val vm: VoiceViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        vm.engine.attachLifecycle(this) // pause speech / stop mic when backgrounded
        setContent { PocketMindTheme { App(vm) } }
        handleDebugIntent(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleDebugIntent(intent)
    }

    /** Debug builds only: `adb shell am start -n com.pocketmind.demo/.MainActivity --es say "hello"` */
    private fun handleDebugIntent(i: Intent?) {
        val debuggable = (applicationInfo.flags and android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0
        if (!debuggable) return
        i?.getStringExtra("say")?.let { vm.adapter.submitText(it) }
    }
}

@Composable
private fun App(vm: VoiceViewModel) {
    var showSettings by remember { mutableStateOf(false) }
    Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
        if (showSettings) {
            androidx.activity.compose.BackHandler { showSettings = false }
            VoiceSettingsScreen(vm.engine, onBack = { showSettings = false })
        } else {
            HomeScreen(vm, onSettings = { showSettings = true })
        }
    }
}

@Composable
private fun HomeScreen(vm: VoiceViewModel, onSettings: () -> Unit) {
    val context = androidx.compose.ui.platform.LocalContext.current
    val state by vm.engine.state.collectAsState()
    val turns by vm.adapter.turns.collectAsState()
    var continuous by remember { mutableStateOf(false) }
    var permissionDenied by remember { mutableStateOf(false) }
    val listState = rememberLazyListState()

    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        permissionDenied = !granted
        if (granted) vm.onMic()
    }
    fun onMicClick() {
        val granted = ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
        if (granted) { permissionDenied = false; vm.onMic() } else permission.launch(Manifest.permission.RECORD_AUDIO)
    }

    LaunchedEffect(turns.size) { if (turns.isNotEmpty()) listState.animateScrollToItem(turns.lastIndex) }

    Column(Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding()) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("PocketMind", style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
            if (state.sttBackend != "-" || state.ttsBackend != "-") OfflineBadge(offline = state.sttOffline && state.ttsOffline)
            IconButton(onClick = onSettings) { Icon(Icons.Rounded.Tune, "Voice settings") }
        }

        Box(Modifier.weight(1f).fillMaxWidth().padding(horizontal = 16.dp)) {
            if (turns.isEmpty()) {
                Text(
                    "Tap the microphone and say something.\nTry “tell me a long story”.",
                    style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.align(Alignment.Center),
                )
            }
            LazyColumn(state = listState, verticalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxSize()) {
                items(turns) { Bubble(it) }
            }
        }

        // Live captions: partial transcript while listening, current sentence while speaking.
        val caption = when (state.phase) {
            VoicePhase.Listening -> state.partialTranscript
            VoicePhase.Speaking, VoicePhase.Paused -> state.currentSentence
            else -> ""
        }
        Text(
            caption, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant,
            maxLines = 2, modifier = Modifier.fillMaxWidth().padding(horizontal = 24.dp).height(44.dp),
        )

        val err = state.error
        if (permissionDenied || err?.code == VoiceErrorCode.PERMISSION_DENIED) {
            Row(Modifier.fillMaxWidth().padding(horizontal = 24.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("Microphone access is off.", color = MaterialTheme.colorScheme.error, modifier = Modifier.weight(1f))
                TextButton(onClick = {
                    context.startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", context.packageName, null)))
                }) { Text("Open settings") }
            }
        } else if (err != null) {
            Text(err.message, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(horizontal = 24.dp))
        }

        Column(Modifier.fillMaxWidth().padding(bottom = 12.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            MicButton(phase = state.phase, onClick = ::onMicClick)
            Text(state.phase.label(), style = MaterialTheme.typography.labelLarge)
            Spacer(Modifier.height(8.dp))
            FilterChip(selected = continuous, onClick = { continuous = !continuous; vm.setContinuous(continuous) }, label = { Text("Continuous conversation") })
        }
    }
}

@Composable
private fun Bubble(t: Turn) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = if (t.fromUser) Arrangement.End else Arrangement.Start) {
        Surface(
            shape = RoundedCornerShape(18.dp),
            color = if (t.fromUser) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surfaceContainer,
            contentColor = if (t.fromUser) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.fillMaxWidth(0.82f),
        ) { Text(t.text, Modifier.padding(horizontal = 14.dp, vertical = 10.dp), style = MaterialTheme.typography.bodyMedium) }
    }
}
