# LYRN Android Shell - Compilation Guide

This guide explains how to compile the LYRN Android Shell into an APK that can be installed on Android devices.

## Prerequisites

1. **Java Development Kit (JDK):** JDK 11 or higher is required.
2. **Android SDK:** Ensure you have the Android SDK installed. This is usually handled automatically if you use Android Studio, or it can be installed manually using the command-line tools.
3. **Gradle:** The project uses the Gradle wrapper (`gradlew`), so you don't need to install Gradle manually. It will be downloaded automatically the first time you run it.

## Compiling from the Command Line

Open your terminal or command prompt and navigate to the `android_shell` directory:

```bash
cd android_shell
```

### 1. Building a Debug APK

A debug APK is suitable for testing during development. It doesn't require a custom signing key, as Gradle uses a default debug key automatically.

Run the following command:

**macOS / Linux:**
```bash
./gradlew assembleDebug
```

**Windows:**
```cmd
gradlew.bat assembleDebug
```

**Where to find the APK:**
Once the build is successful, you can find the generated APK at:
`android_shell/app/build/outputs/apk/debug/app-debug.apk`

### 2. Building a Release APK

A release APK is optimized and suitable for distribution or installing on production screens. To build a standard release APK (which will be unsigned by default if you haven't configured a keystore in Gradle):

**macOS / Linux:**
```bash
./gradlew assembleRelease
```

**Windows:**
```cmd
gradlew.bat assembleRelease
```

**Where to find the APK:**
The generated unsigned APK will be located at:
`android_shell/app/build/outputs/apk/release/app-release-unsigned.apk`

> **Note:** To install an APK on a device outside of a development environment, it must be signed. If you install via Android Studio, it signs it automatically. If installing manually, read the section below.

---

## Signing the Release APK for Production

If you plan to distribute the app or install it on locked-down production devices, you must sign the release APK.

### Step 1: Generate a Keystore (One-time setup)

Use the `keytool` command (which comes with the JDK) to generate a signing key:

```bash
keytool -genkey -v -keystore my-release-key.jks -keyalg RSA -keysize 2048 -validity 10000 -alias my-alias
```
*Follow the prompts to enter passwords and your organizational details. Remember the passwords and alias, as you will need them to sign the app.*

### Step 2: Sign the APK

You can sign the APK manually using `apksigner` (part of the Android SDK Build Tools):

```bash
apksigner sign --ks my-release-key.jks --out app-release.apk android_shell/app/build/outputs/apk/release/app-release-unsigned.apk
```

*(Alternatively, you can configure your `build.gradle` file to sign the app automatically during the `assembleRelease` task. Refer to the [official Android documentation](https://developer.android.com/studio/publish/app-signing) for more details.)*

---

## Compiling with Android Studio

The easiest way to compile and run the app is using Android Studio:

1. Open Android Studio.
2. Select **File > Open** and navigate to the `android_shell` directory (not the root repository directory).
3. Wait for Android Studio to sync the Gradle project.
4. Select the build variant (Debug or Release) from the **Build Variants** panel on the left.
5. Click the **Run** button (green triangle) to compile and install the app directly on a connected device or emulator.
6. To generate a signed release APK via the UI, go to **Build > Generate Signed Bundle / APK...** and follow the wizard.

## Installing the APK via ADB

If you built the APK via the command line and want to install it on a connected device via USB debugging:

```bash
adb install path/to/your/app.apk
```
*(For example: `adb install android_shell/app/build/outputs/apk/debug/app-debug.apk`)*
