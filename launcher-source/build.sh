#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
SDK=../sdk/android; BT=$SDK/build-tools/34.0.0; JAR=$SDK/platforms/android-29/android.jar
export JAVA_HOME=$(ls -d ../sdk/jdk/*/); export PATH=$JAVA_HOME/bin:$PATH
rm -rf build && mkdir -p build/classes build/dex
$BT/aapt2 compile --dir res -o build/res.zip
$BT/aapt2 link -I $JAR --manifest AndroidManifest.xml -A assets -o build/unsigned.apk build/res.zip --java build/gen --min-sdk-version 21 --target-sdk-version 29 -0 jpg
javac -source 8 -target 8 -Xlint:-options -encoding UTF-8 -bootclasspath $JAR:$BT/core-lambda-stubs.jar -classpath $JAR -d build/classes $(find src build/gen -name '*.java')
$BT/d8 --min-api 21 --release --lib $JAR --output build/dex $(find build/classes -name '*.class')
(cd build/dex && zip -qj ../unsigned.apk classes.dex 2>/dev/null) || python3 -c "import zipfile;z=zipfile.ZipFile('build/unsigned.apk','a');z.write('build/dex/classes.dex','classes.dex');z.close()"
$BT/zipalign -f -p 4 build/unsigned.apk build/aligned.apk
[ -f home.keystore ] || keytool -genkeypair -keystore home.keystore -storepass tvhome -keypass tvhome -alias home -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=TV Home" >/dev/null 2>&1
$BT/apksigner sign --ks home.keystore --ks-pass pass:tvhome --out TVHome.apk build/aligned.apk
ls -la TVHome.apk
