#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
SDK="${ANDROID_SDK_ROOT:-${ANDROID_HOME:?Android SDK is required}}"
BT="$SDK/build-tools/35.0.0"
JAR="$SDK/platforms/android-35/android.jar"
OUT="$PWD/build"
rm -rf "$OUT"
mkdir -p "$OUT/classes" "$OUT/dex"
"$BT/aapt2" compile --dir res -o "$OUT/res.zip"
"$BT/aapt2" link -I "$JAR" --manifest AndroidManifest.xml -o "$OUT/base.apk" "$OUT/res.zip"
javac -encoding UTF-8 -source 8 -target 8 -classpath "$JAR" -d "$OUT/classes" $(find src -name '*.java')
"$BT/d8" --min-api 26 --lib "$JAR" --output "$OUT/dex" $(find "$OUT/classes" -name '*.class')
(cd "$OUT/dex" && zip -q "$OUT/base.apk" classes.dex)
"$BT/zipalign" -f -p 4 "$OUT/base.apk" "$OUT/aligned.apk"
KEY="${HAIERPI_KEYSTORE:-$OUT/preview.jks}"
if [[ ! -f "$KEY" ]]; then
  keytool -genkeypair -keystore "$KEY" -storepass android -keypass android -alias haierpi-preview \
    -keyalg RSA -keysize 2048 -validity 3650 -dname "CN=HaierPi Preview" -storetype JKS -noprompt
fi
"$BT/apksigner" sign --ks "$KEY" --ks-key-alias haierpi-preview --ks-pass pass:android --key-pass pass:android \
  --out "$OUT/HaierPi-0.1.0-preview.apk" "$OUT/aligned.apk"
"$BT/apksigner" verify --verbose --print-certs "$OUT/HaierPi-0.1.0-preview.apk"
"$BT/aapt2" dump badging "$OUT/HaierPi-0.1.0-preview.apk"
(cd "$OUT" && sha256sum HaierPi-0.1.0-preview.apk > SHA256SUMS.txt)
