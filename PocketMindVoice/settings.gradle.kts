pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
        // sherpa-onnx ships as a local AAR (see voice/libs/README.md)
        flatDir { dirs("voice/libs") }
    }
}
rootProject.name = "PocketMindVoice"
include(":app", ":voice")
