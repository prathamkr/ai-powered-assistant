package com.pocketmind.voice.ui

import androidx.compose.animation.Crossfade
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Mic
import androidx.compose.material.icons.rounded.Pause
import androidx.compose.material.icons.rounded.Stop
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.pocketmind.voice.model.VoicePhase

/**
 * The main voice control.
 *  Idle -> mic | Listening -> pulsing rings + stop | Processing -> spinner | Speaking -> rings + stop (interrupt)
 * Animations only run in the phases that need them (no idle CPU cost).
 */
@Composable
fun MicButton(
    phase: VoicePhase,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    size: Dp = 96.dp,
) {
    val active = phase == VoicePhase.Listening || phase == VoicePhase.Speaking
    val base = when (phase) {
        VoicePhase.Listening -> MaterialTheme.colorScheme.primary
        VoicePhase.Speaking, VoicePhase.Paused -> MaterialTheme.colorScheme.tertiary
        VoicePhase.Processing -> MaterialTheme.colorScheme.secondary
        else -> MaterialTheme.colorScheme.primary
    }
    val label = when (phase) {
        VoicePhase.Listening -> "Stop listening"
        VoicePhase.Speaking -> "Interrupt"
        VoicePhase.Paused -> "Stop speaking"
        VoicePhase.Processing -> "Thinking"
        else -> "Start listening"
    }

    Box(modifier.size(size * 1.9f), contentAlignment = Alignment.Center) {
        if (active) {
            val t = rememberInfiniteTransition(label = "pulse")
            for (i in 0..1) {
                val p by t.animateFloat(
                    initialValue = 0f, targetValue = 1f,
                    animationSpec = infiniteRepeatable(tween(1800, delayMillis = i * 900), RepeatMode.Restart),
                    label = "ring$i",
                )
                Box(
                    Modifier
                        .size(size)
                        .graphicsLayer { // layer properties: no recomposition per frame
                            val s = 1f + p * 0.9f
                            scaleX = s; scaleY = s; alpha = (1f - p) * 0.35f
                        }
                        .clip(CircleShape)
                        .background(base)
                )
            }
        }
        Box(
            Modifier
                .size(size)
                .clip(CircleShape)
                .background(base)
                .clickable(onClickLabel = label, onClick = onClick)
                .semantics { contentDescription = label },
            contentAlignment = Alignment.Center,
        ) {
            Crossfade(targetState = phase, label = "micIcon") { ph ->
                val tint = MaterialTheme.colorScheme.onPrimary
                when (ph) {
                    VoicePhase.Processing, VoicePhase.Initializing ->
                        CircularProgressIndicator(Modifier.size(size * 0.4f), color = tint, strokeWidth = 3.dp)
                    VoicePhase.Listening, VoicePhase.Speaking, VoicePhase.Paused ->
                        Icon(Icons.Rounded.Stop, null, Modifier.size(size * 0.42f), tint)
                    else -> Icon(Icons.Rounded.Mic, null, Modifier.size(size * 0.46f), tint)
                }
            }
        }
    }
}

/** Short human label for a phase. */
fun VoicePhase.label(): String = when (this) {
    VoicePhase.Uninitialized, VoicePhase.Initializing -> "Getting ready"
    VoicePhase.Idle -> "Tap to talk"
    VoicePhase.Listening -> "Listening"
    VoicePhase.Processing -> "Thinking"
    VoicePhase.Speaking -> "Speaking"
    VoicePhase.Paused -> "Paused"
    VoicePhase.Error -> "Something went wrong"
}
