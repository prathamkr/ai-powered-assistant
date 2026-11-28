#!/bin/sh
# Build the Lazey APK in a container, the same way on every machine.
#
#   docker/build.sh          -> bin-docker/localassistant-<version>-arm64-v8a-debug.apk
#   DEV=1 docker/build.sh    -> "Lazey Dev" (org.pa.localassistantdev), installs next to the normal app
#
# ENGINE=docker (default) or ENGINE=nerdctl. SRC / OUT override the project and output folders.
# The first build downloads the Android SDK/NDK and compiles Python, Kivy, SDL2 (about 1 hour under
# Rosetta); both are kept in the volumes lazey-sdk and lazey-work, so later builds take minutes.
# Gradle (~150 MB, downloaded by the build) is kept in the volume lazey-gradle.
# The debug signing key lives in the volume lazey-keys: Android installs an update only when it is
# signed with the SAME key, so keep that volume (a new key means uninstalling the app and its data).
set -eu

ENGINE=${ENGINE:-docker}
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=${SRC:-$(dirname "$HERE")}
OUT=${OUT:-$SRC/bin-docker}
mkdir -p "$OUT"
if [ ! -f "$SRC/vosk_model/uuid" ]; then
  echo "The voice pack model is missing: run docker/get-voice-model.sh first." >&2
  exit 1
fi

$ENGINE build --platform linux/amd64 -t lazey-build "$HERE"
$ENGINE run --rm --platform linux/amd64 \
    -e DEV="${DEV:-0}" \
    -v "$SRC":/src:ro \
    -v "$OUT":/out \
    -v lazey-sdk:/root/.buildozer \
    -v lazey-work:/work/.buildozer \
    -v lazey-keys:/root/.android \
    -v lazey-gradle:/root/.gradle \
    lazey-build
