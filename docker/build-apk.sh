#!/bin/bash
# Runs INSIDE the build container (see docker/Dockerfile).
#   /src                 project, mounted read-only
#   /out                 the finished APK is copied here
#   /root/.buildozer     cache volume: Android SDK, NDK, python-for-android
#   /work/.buildozer     cache volume: compiled recipes (Python, Kivy, SDL2, ...)
# DEV=1 builds "Lazey Dev" (package org.pa.localassistantdev), which installs next to the normal
# app; only this container's copy of buildozer.spec is changed for that.
set -euo pipefail

rsync -a --delete --exclude .buildozer --exclude bin --exclude .venv --exclude .git \
      --exclude __pycache__ --exclude bin-docker /src/ /work/
cd /work

if [ "${DEV:-0}" = 1 ]; then
  sed -i 's/^title = Lazey$/title = Lazey Dev/; s/^package.name = localassistant$/package.name = localassistantdev/' buildozer.spec
fi
grep -E '^(title|package.name|version) =' buildozer.spec

rm -f bin/*.apk /out/*.apk   # a failed build must not leave an older APK that looks new
buildozer android debug < /dev/null
cp -v bin/*.apk /out/
echo BUILD_DONE
