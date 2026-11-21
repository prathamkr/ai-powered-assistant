# PocketMind Voice Engine

Self-contained voice subsystem (speech-to-text, text-to-speech, voice personalities, settings UI) for PocketMind.
It converts **audio → text** and **text → audio**. It never generates answers.

```
user speaks → VoiceEngine(STT) → text ──► PocketMindAi.respond(text) ──► reply text → VoiceEngine(TTS) → speaker
                                          (main AI developer's code)
```

## Integration (for the main-AI developer) — 3 steps

1. **Add the module**: copy the `voice/` folder into the project, `include(":voice")` in `settings.gradle.kts`, add
   `flatDir { dirs("voice/libs") }` to the repositories in `settings.gradle.kts`, and download the sherpa-onnx AAR into `voice/libs/`
   (see `voice/libs/README.md`). In your app: `implementation(project(":voice"))`.
   The app needs `minSdk >= 26`, the `org.jetbrains.kotlin.plugin.compose` plugin if you use the bundled UI, and `RECORD_AUDIO` (already merged from the library manifest).
2. **Implement one function**, `PocketMindAi.respond(userText: String): String`:

```kotlin
val engine: PocketMindVoiceEngine = VoiceEngine(applicationContext)
val voice = PocketMindAIAdapter(engine, PocketMindAi { text -> yourAi.reply(text) }, viewModelScope)
voice.start()
lifecycleScope.launch { engine.initialize() }
engine.attachLifecycle(this)      // pause speech / release mic when the app is backgrounded
```

3. **Hook the UI**: mic button → `viewModelScope.launch { voice.onMicPressed() }` (listens; if the assistant is talking it interrupts first).
   Request `RECORD_AUDIO` before the first press (see `app/.../MainActivity.kt`). Reusable UI: `MicButton(phase, onClick)` and
   `VoiceSettingsScreen(engine, onBack)`.

That is the whole contract. Anything else (typed input, your own TTS triggers) is `voice.submitText(...)` / `engine.speak(text)`.

### API summary (`PocketMindVoiceEngine`)
| Call | Behaviour |
|---|---|
| `initialize()` | cheap; models load lazily on first use |
| `startListening()` / `stopListening()` / `cancelListening()` | partial → final transcript via `events` |
| `speak(text)` | suspends until finished or interrupted; long/multi-paragraph OK; last sentence never cut |
| `stopSpeaking()` / `pauseSpeaking()` / `resumeSpeaking()` | immediate |
| `setVoiceProfile / setPitch / setSpeechRate / setVolume / setSpeakerId` | persisted locally |
| `state: StateFlow<VoiceState>` | phase (Idle/Listening/Processing/Speaking/Paused), partial transcript, backend names + offline flags |
| `events: SharedFlow<VoiceEvent>` | `FinalTranscript`, `Partial`, `NoSpeechDetected`, `SpeechStarted/Finished/Interrupted`, `Error` |

## Engines (chosen at runtime — nothing is assumed)

| | Offline pack installed | Fallback |
|---|---|---|
| STT | sherpa-onnx streaming Zipformer "Kroko" (English, 2025; CC-BY-SA community model). **Truly offline.** | Android `SpeechRecognizer`. Reported *offline* only if an on-device recognizer exists (API 33+ with language pack); otherwise reported **Online**. |
| TTS | sherpa-onnx + Piper `libritts_r` (904 speakers, int8). **Truly offline**, streamed sentence-by-sentence. | Android `TextToSpeech` (voices discovered at runtime; Atlas/Echo/… map to different installed voices + pitch/rate). |

The offline models (~77 MB download: 22 MB voices + 55 MB recognizer) are fetched on first use from the Settings screen (GitHub releases of k2-fsa/sherpa-onnx)
and stored in app-private storage. Until then the app works on the native engines. If the offline TTS fails at runtime the engine retries once on native TTS automatically.

Comparison that drove the choice: `SpeechRecognizer` is zero-effort but not reliably offline; whisper.cpp needs JNI/NDK work and is not streaming (higher latency);
sherpa-onnx gives streaming STT **and** multi-speaker neural TTS from one official Android AAR with a Kotlin API, which is the fastest path to both.

## Voice personalities
Nova (warm), Atlas (deep), Echo (calm), Luna (soft), Spark (energetic) are **presets**: speaker id + pitch + speed + volume.
**Speaker ids are provisional and have not been auditioned** (the author could not listen on this machine). Use the Speaker −/+ buttons in
Voice Settings to find the voices you like and edit `VoiceProfiles` in `model/VoiceModels.kt`.
Pitch on the offline engine is done by resampling (plays at `rate × pitch`, tempo compensated) — good for roughly ±25 %; it also shifts timbre slightly. No voice cloning.

## Build
```
# JDK = Android Studio's bundled JBR; Gradle 9.6 (wrapper pinned) ; AGP 9.5.2 ; compileSdk 37 ; minSdk 26
gradlew :voice:testDebugUnitTest :app:assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```
If HTTPS downloads fail with `PKIX path building failed` (antivirus HTTPS scanning), point Gradle at a trust store containing the AV root certificate.

## Lifecycle, audio & threading
- Mic and speaker are never active together: listening stops speech; speaking cancels listening.
- Audio focus: speaking = transient/duck, listening = transient exclusive; a phone call pauses speech, permanent loss stops it.
- App backgrounded: mic stops, speech pauses and resumes on return. (Background listening would need a foreground service — not implemented.)
- All heavy work is off the main thread; `release()` frees models and audio tracks.

## Testing status — read this
Tested on a **Samsung Galaxy A36 (SM-A366E), Android 16, arm64, 7.5 GB RAM**, debug build, 2026-11-21. Audio *quality* was **not** judged by ear (the tester could not listen); everything below is verified from logs, `dumpsys audio`, screenshots and the UI tree.

| Scenario | Result |
|---|---|
| Build; 7 `SentenceChunker` unit tests | ✅ |
| In-app offline model download + extraction (22 MB + 55 MB archives → 40 MB + 71 MB on disk) | ✅ |
| Offline engines load on device (STT "sherpa-onnx Kroko Zipformer", TTS "Piper neural voice", both badged Offline) | ✅ |
| Speech out: long 7-sentence, 3-paragraph reply fully spoken, `SpeechFinished` only after the audio drained | ✅ |
| Speech latency: first audio ≈ 0.35–0.45 s warm; ≈ 0.9 s on the first reply after launch (models pre-loaded at `initialize()`); ≈ 3 s if the warm-up has not finished | ✅ |
| Speech → mic interrupt: player silent < 0.9 s after the tap (incl. adb overhead), recorder started | ✅ |
| Microphone → offline transcript (partials + final), silence timeout → `NoSpeechDetected` → Idle, no hallucinated text | ✅ |
| Background during playback → `Paused`, player released; return → `Speaking` | ✅ |
| 30 rapid mic taps: no crash, same process, orderly Listening/NoSpeech/Idle cycles | ✅ |
| Corrupt offline TTS model → no crash, automatic fallback to Android TextToSpeech, speech continues | ✅ |
| Mic permission denied → "Microphone access is off." + Open settings, no crash | ✅ |
| RAM with both models loaded: ≈ 355–365 MB PSS | ✅ |
| Voice profiles sound distinct / speaker ids suit the persona names | ❌ **not judged** (provisional ids; audition with Speaker −/+) |
| Pitch / speed sliders audibly change the voice | ❌ not judged by ear |
| Offline transcription accuracy, **over the air** (PC speaker → phone mic, 12 assistant commands, 12 different synthetic speakers) | ✅ clean: 7.0 % WER, 12/12 captured, 9/12 perfect · with 10 dB room noise: 8.1 % WER, 12/12 captured, 8/12 perfect. Not yet measured on real human speech |
| Battery, 12-hour soak, Bluetooth headsets, phone-call audio-focus loss | ❌ not tested |

### Bugs found only by running on the device (now fixed)
1. **sherpa-onnx 2.x dropped espeak-ng** → Piper voices could not tokenize. Pinned to **1.13.8** (do not upgrade to 2.x).
2. **Native crash** (`NoSuchMethodError … invoke([F)Ljava/lang/Integer`): sherpa-onnx calls the TTS callback through JNI and needs a classically compiled Kotlin lambda → `-Xlambdas=class` in `voice/build.gradle.kts`. **Keep this flag.**
3. First reply was ~3 s late because the models loaded lazily → background warm-up after `initialize()`.
4. Continuous mode now waits 600 ms after speech before reopening the mic (avoid hearing the speaker tail).
5. Demo activity is `singleTop` (a second launch used to create a second engine).

### Debug helpers (debuggable builds only)
`adb shell am start -n com.pocketmind.demo/.MainActivity --es say story` submits text as if spoken (one word only; adb mangles spaces).
`adb logcat -s PMEvent PMVoice` prints the event/phase timeline and TTS timing.

## Choosing the recognizer (why Kroko, and what "training" meant here)
The first recognizer (zipformer-20M) felt wrong in practice: on a benchmark of 12 assistant commands it had **42–69 % word error rate and dropped the first word in 10–12 of 12 clips**.
We did not fine-tune a model (that needs hours of recorded speech and GPUs); we benchmarked alternatives and fixed the audio front-end instead.

| Model (PC benchmark, 12 commands × clean / 0.5 s lead-in / 10 dB noise) | WER | first word wrong | speed (RTF, lower = faster) |
|---|---|---|---|
| zipformer-20M (first choice) | 63 % / 42 % / 69 % | 12 / 10 / 12 of 12 | 0.4–0.5 |
| NeMo fast-conformer 480 ms int8 (101 MB) | 11 % / 6 % / 12 % | 0 | 0.9–1.4 (too slow for phones) |
| **Kroko en-2025 (55 MB) — chosen** | 16 % / 6 % / 7 % | 0 | 0.44–0.51 |
| Kroko + beam search (4 or 8 paths) | no gain (±1 word), slower | | 0.5–0.6 |

Front-end fixes in `SherpaSpeechToText`: 0.5 s of silence is fed before the mic audio and 0.4 s after it (padding alone roughly halved the errors of every model);
no-speech timeout 3.5 s, end-of-speech 1.1 s. `TranscriptFormatter` turns the model's ALL-CAPS output into sentence case ("Tell me a long story") before it reaches the main AI.
Licence: the Kroko *community* model is **CC-BY-SA** (credit Banafo/Kroko ASR). A commercial product should use Kroko's commercial models.
Further gains would need either a larger model (NeMo/Parakeet class, 100–450 MB, slower) or real recordings for fine-tuning.
