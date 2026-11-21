package com.pocketmind.demo

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val Dark = darkColorScheme(
    primary = Color(0xFF8C9BFF), onPrimary = Color(0xFF10123A),
    secondary = Color(0xFFB0B6D8), tertiary = Color(0xFF5FD7C9),
    background = Color(0xFF0E0F14), onBackground = Color(0xFFE6E7EE),
    surface = Color(0xFF14161C), onSurface = Color(0xFFE6E7EE),
    surfaceContainer = Color(0xFF1A1D25), onSurfaceVariant = Color(0xFFA2A6B8),
    outlineVariant = Color(0xFF2B2F3B),
)

private val Light = lightColorScheme(
    primary = Color(0xFF4757D6), onPrimary = Color.White,
    secondary = Color(0xFF5B6180), tertiary = Color(0xFF0E9F92),
    background = Color(0xFFF7F8FB), onBackground = Color(0xFF14161C),
    surface = Color.White, onSurface = Color(0xFF14161C),
    surfaceContainer = Color(0xFFEEF0F7), onSurfaceVariant = Color(0xFF5E6275),
    outlineVariant = Color(0xFFD7DAE6),
)

@Composable
fun PocketMindTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = if (isSystemInDarkTheme()) Dark else Light, content = content)
}
