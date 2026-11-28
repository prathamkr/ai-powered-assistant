#!/bin/sh
# Download Lazey's built-in voice pack model into vosk_model/ (run once on the host, before
# docker/build.sh). The model is packed into the APK as assets/model-en-in.
#
#   vosk-model-small-en-in-0.4  (Indian English, ~37 MB zip, Apache-2.0, https://alphacephei.com/vosk/models)
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
DEST=$(dirname "$HERE")/vosk_model
NAME=vosk-model-small-en-in-0.4
SHA256=20663dcac4d5cb783a579c54d98339344a688e4ec6e1b4a4b059fd1235454cc7

if [ -f "$DEST/uuid" ] && [ "$(cat "$DEST/uuid")" = "$NAME" ]; then
  echo "voice model already in $DEST"
  exit 0
fi
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
curl -fsSL --retry 5 -o "$TMP/model.zip" "https://alphacephei.com/vosk/models/$NAME.zip"
echo "$SHA256  $TMP/model.zip" | shasum -a 256 -c -
(cd "$TMP" && unzip -q model.zip)
mkdir -p "$DEST"
cp -R "$TMP/$NAME/." "$DEST/"
# StorageService (Vosk) copies the model out of the APK again only when this uuid changes
echo "$NAME" > "$DEST/uuid"
echo "voice model ready in $DEST"
