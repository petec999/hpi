# HaierPi Android preview 0.2.0

Native Android dashboard, Adaptive/experiment readings, in-session charts, confirmed basic control actions via the existing authenticated v2 API. Demonstration mode works offline with simulated data and no control commands. For login and advanced settings, the app opens the existing panel in a restricted same-origin WebView. The V2 button explicitly reopens /v2/ after login; Pulpit returns to native UI. No server update is required if the installed server already has the compatible v2 API. Android 8+. HTTP is allowed with an explicit warning; use trusted LAN or VPN. HTTPS certificates are validated. No cloud account, no bundled telemetry or credentials.

The app reads /v2/api/state every five seconds when foregrounded. Missing or stale state blocks writes; server expected-value checks, CSRF and all control guards remain in force. Each write requires confirmation and is never automatically retried. Chart history is in memory only. This preview does not implement native curve editing, notifications, discovery, production AAB or persistent signing.

Build with Android SDK platform 35/build-tools 35.0.0 and Java 17: bash android-app/build.sh. GitHub Actions uploads the signed preview APK and SHA256 checksum in an artifact ZIP. The default preview signing key is newly generated each build, so uninstall the old preview before installing the new one unless a stable key is configured. No device tests have been run. No server firmware or control changes.

## Download and verify

[Successful 0.2.0 APK build](https://github.com/petec999/hpi/actions/runs/45868217263). In Artifacts, select HaierPi-Android-0.2.0, extract the ZIP, and install the APK from a trusted source. Check SHA256SUMS.txt before installation. Android may request permission to install from that source. This is a preview, not a Play release.

## Open acceptance

Demo and all tabs, live login/session sharing, direct API readback, disconnect handling, stale-state write blocking and confirmed control commands on an actual Android phone remain to be tested. The native app does not infer or change hysteresis thresholds. The WebView V2 button reopens /v2/ after login; the Pulpit button returns to the native dashboard. Release signing/AAB, privacy policy, data-safety form and store listing are still open. Keep the current server on the Adaptive branch rather than deploying inherited server sources from this mobile branch.
