# dzmm Android client

Flutter client for playing an existing dzmm session hosted by the Mac app. The
Mac remains the only backend, database, and model host.

## Local development

```bash
flutter pub get
flutter analyze
flutter test
flutter build apk --debug
```

There is no build-time production host or device token. Discovery and pairing
select a host at runtime, and device tokens are stored with
`flutter_secure_storage` rather than shared preferences.

Android v1 deliberately permits cleartext HTTP to a private LAN host. Use it
only on a trusted network; it does not make dzmm safe to expose to the internet.

## Internal release signing

Release builds never fall back to the debug key. To sign an internal build,
create the ignored `android/key.properties` file:

```properties
storeFile=/absolute/path/to/dzmm-upload.jks
storePassword=...
keyAlias=...
keyPassword=...
```

Then build with `flutter build apk --release` or
`flutter build appbundle --release`. Keep the keystore and property file out of
the repository. Without all four values, Gradle may produce an unsigned release
artifact for build verification, but it is not an installable release.

The Android application ID is `com.dzmm.mobile`. Flutter stable 3.44 currently
sets the minimum supported Android SDK to 24.
