[app]
title = Lazey
package.name = localassistant
package.domain = org.pa
source.dir = .
source.include_exts = py,ttf,otf,txt
source.exclude_dirs = tests, docs, bin, .buildozer, __pycache__, java, android_res
source.exclude_patterns = p4a_hook.py
version = 0.3
# pycryptodome (not `cryptography`): has a python-for-android recipe and no Rust needed.
# No version pins: use the versions python-for-android tested together.
# (kivy==2.3.0 does NOT compile against the Python 3.14 that p4a v2026.05.09 bundles.)
requirements = python3,kivy,pyjnius,android,pycryptodome
p4a.branch = v2026.05.09
orientation = portrait
fullscreen = 0
# Contacts/call/photos permissions are requested only when the user first uses that feature.
android.permissions = READ_CALENDAR, READ_CONTACTS, CALL_PHONE, READ_PHONE_STATE, RECORD_AUDIO, ACCESS_NETWORK_STATE, com.android.alarm.permission.SET_ALARM, SEND_SMS, POST_NOTIFICATIONS, RECEIVE_BOOT_COMPLETED, REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, USE_EXACT_ALARM, (name=android.permission.SCHEDULE_EXACT_ALARM;maxSdkVersion=32), READ_MEDIA_IMAGES, READ_MEDIA_VISUAL_USER_SELECTED, (name=android.permission.READ_EXTERNAL_STORAGE;maxSdkVersion=32)
android.extra_manifest_xml = ./extra_manifest.xml
# Daily messages: Java receivers (java/) + hook that adds them to the manifest
android.add_src = java
android.add_resources = android_res
p4a.hook = ./p4a_hook.py
android.api = 34
android.minapi = 29
android.archs = arm64-v8a
android.accept_sdk_license = True
android.allow_backup = False

[buildozer]
log_level = 2
warn_on_root = 0
