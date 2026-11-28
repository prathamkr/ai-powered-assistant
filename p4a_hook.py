"""python-for-android build hook (buildozer.spec: p4a.hook = ./p4a_hook.py).

The p4a manifest template has no place for <receiver> entries inside <application>, so this adds
the daily-message receivers after the manifest is rendered and before Gradle builds the APK.
It also limits native libraries from Gradle dependencies (Vosk voice pack) to the ABIs being built.
Runs with the dist folder as the current directory. Not part of the app itself.
"""
import os

RECEIVERS = """
        <!-- Daily messages (java/org/pa/assistant). Added by p4a_hook.py -->
        <receiver android:name="org.pa.assistant.DailyReceiver" android:exported="false" />
        <receiver android:name="org.pa.assistant.BootReceiver" android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.BOOT_COMPLETED" />
                <action android:name="android.intent.action.MY_PACKAGE_REPLACED" />
            </intent-filter>
        </receiver>
        <!-- Timed routines: the notification opens this screen-less activity, which opens the app. -->
        <activity android:name="org.pa.assistant.RoutineTapActivity"
                  android:theme="@android:style/Theme.NoDisplay"
                  android:exported="false"
                  android:excludeFromRecents="true"
                  android:noHistory="true"
                  android:taskAffinity="" />
        <!-- WhatsApp auto-send (user turns it on in Settings > Accessibility). -->
        <service android:name="org.pa.assistant.AutoSendService"
                 android:label="@string/autosend_label"
                 android:permission="android.permission.BIND_ACCESSIBILITY_SERVICE"
                 android:exported="true">
            <intent-filter>
                <action android:name="android.accessibilityservice.AccessibilityService" />
            </intent-filter>
            <meta-data android:name="android.accessibilityservice"
                       android:resource="@xml/autosend_service" />
        </service>
        <!-- Phone control: approved step lists in other apps (user turns it on in Settings > Accessibility). -->
        <service android:name="org.pa.assistant.PhoneControlService"
                 android:label="@string/phone_control_label"
                 android:permission="android.permission.BIND_ACCESSIBILITY_SERVICE"
                 android:exported="true">
            <intent-filter>
                <action android:name="android.accessibilityservice.AccessibilityService" />
            </intent-filter>
            <meta-data android:name="android.accessibilityservice"
                       android:resource="@xml/phone_control_service" />
        </service>
"""


def _keep_only_built_abis():
    """The Vosk/JNA AARs bring native libraries for 4 ABIs (~10 MB each). Keep only the ABIs this
    APK is built for (the folders p4a put in libs/), so the APK does not grow by ~30 MB."""
    abis = sorted(d for d in os.listdir("libs") if os.path.isdir(os.path.join("libs", d))) \
        if os.path.isdir("libs") else []
    path = "build.gradle"
    if not abis or not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        gradle = f.read()
    if "abiFilters" in gradle:
        return
    if gradle.count("defaultConfig {") != 1:
        raise RuntimeError("p4a_hook: expected exactly one 'defaultConfig {' in build.gradle")
    line = "defaultConfig {\n        ndk { abiFilters %s }  // added by p4a_hook.py" % ", ".join("'%s'" % a for a in abis)
    with open(path, "w", encoding="utf-8") as f:
        f.write(gradle.replace("defaultConfig {", line))


def before_apk_assemble(toolchain):
    _keep_only_built_abis()
    path = os.path.join("src", "main", "AndroidManifest.xml")
    with open(path, encoding="utf-8") as f:
        xml = f.read()
    if "org.pa.assistant.DailyReceiver" in xml:
        return
    if xml.count("</application>") != 1:
        raise RuntimeError("p4a_hook: expected exactly one </application> in " + path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml.replace("</application>", RECEIVERS + "    </application>"))
