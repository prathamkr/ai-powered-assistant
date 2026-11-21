plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "com.pocketmind.voice"
    compileSdk = 37

    defaultConfig {
        minSdk = 26
        consumerProguardFiles("consumer-rules.pro")
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    testOptions { unitTests.isReturnDefaultValues = true }
}

// sherpa-onnx's native code calls the Kotlin callback via JNI as Function1.invoke([F)Ljava/lang/Integer;
// That signature only exists on classically-compiled lambda classes, not invokedynamic lambdas.
kotlin {
    compilerOptions { freeCompilerArgs.add("-Xlambdas=class") }
}

dependencies {
    // Offline STT + TTS (native libs for arm64-v8a, armeabi-v7a, x86, x86_64)
    api(mapOf("name" to "sherpa-onnx-1.13.8", "ext" to "aar"))

    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    implementation("androidx.core:core-ktx:1.16.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.9.1")
    implementation("org.apache.commons:commons-compress:1.27.1") // .tar.bz2 model extraction

    // Reusable Compose UI (VoiceSettingsScreen, MicButton)
    implementation(platform("androidx.compose:compose-bom:2025.06.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.10.2")
}
