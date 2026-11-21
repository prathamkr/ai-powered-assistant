package com.pocketmind.voice

import android.content.Context
import com.pocketmind.voice.model.VoiceProfile
import com.pocketmind.voice.model.VoiceProfiles
import com.pocketmind.voice.model.VoiceSettings
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Local persistence of [VoiceSettings] (SharedPreferences: tiny, synchronous, no extra dependency).
 * Also the "voice profile manager": select a preset or tweak individual values.
 */
class VoicePreferences(context: Context) {

    private val prefs = context.applicationContext.getSharedPreferences("pocketmind_voice", Context.MODE_PRIVATE)
    private val _settings = MutableStateFlow(load())
    val settings: StateFlow<VoiceSettings> = _settings.asStateFlow()

    private fun load(): VoiceSettings {
        val d = VoiceSettings()
        return VoiceSettings(
            profileId = prefs.getString("profile", d.profileId) ?: d.profileId,
            speakerId = prefs.getInt("speaker", d.speakerId),
            pitch = prefs.getFloat("pitch", d.pitch).coerceIn(VoiceSettings.PITCH_MIN, VoiceSettings.PITCH_MAX),
            speechRate = prefs.getFloat("rate", d.speechRate).coerceIn(VoiceSettings.RATE_MIN, VoiceSettings.RATE_MAX),
            volume = prefs.getFloat("volume", d.volume).coerceIn(0f, 1f),
            nativeVoiceIndex = prefs.getInt("nativeVoice", d.nativeVoiceIndex),
            language = prefs.getString("lang", d.language) ?: d.language,
            preferOffline = prefs.getBoolean("offline", d.preferOffline),
        )
    }

    @Synchronized
    fun update(block: (VoiceSettings) -> VoiceSettings) {
        val s = block(_settings.value)
        _settings.value = s
        prefs.edit()
            .putString("profile", s.profileId).putInt("speaker", s.speakerId)
            .putFloat("pitch", s.pitch).putFloat("rate", s.speechRate).putFloat("volume", s.volume)
            .putInt("nativeVoice", s.nativeVoiceIndex).putString("lang", s.language)
            .putBoolean("offline", s.preferOffline)
            .apply()
    }

    fun selectProfile(p: VoiceProfile) = update { VoiceSettings.from(p, it) }
    fun currentProfile(): VoiceProfile = VoiceProfiles.byId(_settings.value.profileId)
}
