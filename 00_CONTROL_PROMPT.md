# LYRN Android App Build Control Prompt

You are working on a native Android application for LYRN that acts as a dedicated mobile shell around the existing LYRN frontend experience.

## Core Product Direction

This application is a frontend shell only. Do not introduce backend implementation assumptions, local runtime setup flows, embedded Linux environment details, packaging plans, or anything that treats local and remote differently at the app architecture level.

The app connects to a target LYRN system through the same connection model regardless of where that target exists. The frontend must remain clean, role-based, and connection-driven.

The app has two primary startup roles selected during first run:

1. **Remote**
   - Full control-surface style experience
   - Standard interactive dashboard behavior
   - Normal navigation and control access

2. **Screen**
   - Dedicated display/viewer behavior
   - Minimal interface
   - Meant for signs, static screens, status displays, and controlled viewer surfaces
   - Should feel like an appliance mode, not a normal browser session

Both roles use the same app shell and the same connection model. The distinction is startup behavior, route behavior, UI restrictions, and viewer-specific polish.

---

## Absolute Rules

- Do not discuss manual local setup, Termux, embedded Python, bundled runtime environments, or backend packaging.
- Do not redesign the LYRN backend.
- Do not create unnecessary abstractions or speculative enterprise architecture.
- Do not split this into multiple apps.
- Do not replace the existing web UI approach.
- Do not build around browser chrome assumptions.
- Do not drift away from a clean Android shell + WebView architecture.
- Do not mark a phase complete unless the checklist is actually satisfied.
- After every phase, update the build notes in this file with meaningful implementation details, problems, decisions, and anything the next phase must know.

---

## Primary Goal

Build a polished Android shell that:
- launches into a fullscreen WebView experience
- supports first-run role selection
- stores role and connection preferences
- injects app config cleanly into the web layer
- supports both Remote and Screen startup behavior
- keeps Screen mode focused, stable, and resistant to accidental interaction
- stays simple, modular, and easy to extend later

---

## Global Checklist

Mark each item complete only when actually done.

- [x] Phase 1 complete
- [x] Phase 2 complete
- [x] Phase 3 complete
- [x] Phase 4 complete

---

## Phase Execution Rules

For each phase:
1. Read this control prompt fully.
2. Read the build notes from prior phases before making changes.
3. Complete only the scope of the current phase.
4. Do not silently expand scope into future phases unless required to avoid breaking architecture.
5. If a small supporting change is needed outside the phase, note exactly why.
6. When the phase is done:
   - mark the phase complete in the checklist above
   - append detailed build notes below
   - include files changed
   - include architecture decisions made
   - include unresolved issues or deferred enhancements
   - include anything the next phase needs to know

---

## Required Build Notes Format

Append a new section after each completed phase using this exact structure.

### Phase X Build Notes
**Status:** Complete / Partial

**Files Created**
- file/path/example1
- file/path/example2

**Files Modified**
- file/path/example3
- file/path/example4

**What Was Built**
- concise but specific summary of completed work

**Important Decisions**
- decision 1
- decision 2

**Problems Encountered**
- problem 1
- problem 2

**Deferred / Not Yet Done**
- deferred item 1
- deferred item 2

**Next Phase Needs To Know**
- important note 1
- important note 2

---

## Quality Standard

The app should feel intentional, clean, and appliance-like where appropriate. Favor stable structure, clear state handling, and minimal moving parts over cleverness.

The result should look and behave like a real LYRN mobile shell, not a generic wrapped website.

### Phase 1 Build Notes
**Status:** Complete

**Files Created**
- android_shell/build.gradle
- android_shell/settings.gradle
- android_shell/gradle.properties
- android_shell/app/build.gradle
- android_shell/app/src/main/AndroidManifest.xml
- android_shell/app/src/main/res/layout/activity_main.xml
- android_shell/app/src/main/res/values/strings.xml
- android_shell/app/src/main/res/values/themes.xml
- android_shell/app/src/main/res/values/colors.xml
- android_shell/app/src/main/java/com/lyrn/shell/MainActivity.kt
- android_shell/app/src/main/java/com/lyrn/shell/WebViewHost.kt

**Files Modified**
- 00_CONTROL_PROMPT.md
- .gitignore

**What Was Built**
- Set up a clean Android application foundation using Kotlin and Gradle.
- Configured project with no-action-bar, fullscreen layout.
- Added a simple `WebViewHost` class to initialize the WebView cleanly.
- Placed a placeholder to load `http://10.0.2.2:8080/`.

**Important Decisions**
- Used Kotlin rather than Java for more modern development.
- Chose programmatic setup of the WebView configuration within a helper class `WebViewHost` rather than doing it all in the `MainActivity` to separate host logic.
- Avoided setting up UI/activities for future phases so as not to over-engineer at this phase.

**Problems Encountered**
- Creating the project natively in a directory without existing Android files caused Gradle cache and build outputs, so these were properly excluded in `.gitignore`.

**Deferred / Not Yet Done**
- Role selection UI and persistence.
- WebView Config injection (currently it hardcodes the 10.0.2.2 dev localhost URL).
- Real splash screen or loading states.

**Next Phase Needs To Know**
- The project is inside the `android_shell` directory. Use that as the root for Android-specific logic.
- You can extend `MainActivity.kt` and `WebViewHost.kt` for URL updates and config injection.

### Phase 2 Build Notes
**Status:** Complete

**Files Created**
- android_shell/app/src/main/java/com/lyrn/shell/AppConfig.kt
- android_shell/app/src/main/res/layout/activity_setup.xml
- android_shell/app/src/main/java/com/lyrn/shell/SetupActivity.kt

**Files Modified**
- android_shell/app/src/main/java/com/lyrn/shell/MainActivity.kt
- android_shell/app/src/main/AndroidManifest.xml
- 00_CONTROL_PROMPT.md

**What Was Built**
- Created `AppConfig` class to persist the selected app role (Remote vs Screen) and the target URL via `SharedPreferences`.
- Added a `SetupActivity` providing a simple first-run UI with RadioButtons and an EditText for URL input.
- Modified `MainActivity` to act as the primary app shell, loading the config saved in `SetupActivity`, enforcing `FLAG_KEEP_SCREEN_ON` for Screen mode, and handling redirection if setup is not complete.
- Updated `AndroidManifest.xml` to declare `SetupActivity` as the main launcher activity.

**Important Decisions**
- Stored configurations using Android's native `SharedPreferences` instead of complex database setups to keep it simple and clean.
- Used Kotlin `Companion Object` in `AppConfig` to centralize default values and keys.
- Kept the UI in `activity_setup.xml` minimal and functional without complex styling to align with frontend shell goals.
- Extracted width to `0dp` for `activity_setup.xml` form elements to conform with `ConstraintLayout` best practices.

**Problems Encountered**
- `activity_setup.xml` initial constraints lacked strict horizontal alignment for some nested components like `EditText`, which were corrected via code review.

**Deferred / Not Yet Done**
- WebView config injection and actual token/auth parameters handling.
- Screen mode advanced lock down/kiosk behaviors (focuses on `FLAG_KEEP_SCREEN_ON` for now).

**Next Phase Needs To Know**
- The primary configuration structure `AppConfig` is ready to be expanded for token/auth injection if needed.
- `MainActivity` is the active host but no longer the immediate launcher, it routes through `SetupActivity` first.

### Phase 3 Build Notes
**Status:** Complete

**Files Created**
- android_shell/app/src/main/java/com/lyrn/shell/NativeBridge.kt

**Files Modified**
- android_shell/app/src/main/java/com/lyrn/shell/WebViewHost.kt
- android_shell/app/src/main/java/com/lyrn/shell/MainActivity.kt
- android_shell/app/build.gradle
- LYRN_v6/dashboard.html
- 00_CONTROL_PROMPT.md

**What Was Built**
- Created `NativeBridge` class to expose native configuration to the `WebView` using `@JavascriptInterface`.
- Injected `NativeBridge` into the `WebView` as `LyrnNative`.
- Modified `dashboard.html` to check for `window.LyrnNative` and parse its config to automatically apply settings.
- Added role-based startup logic in `dashboard.html` for "screen" mode: auto-launches a maximized `mod_server_status` display without headers and hides standard UI elements like the top bar and floating dock.
- Added a Reset button in `dashboard.html` that triggers `LyrnNative.resetConfig()` allowing users to clear app config and restart into `SetupActivity`.

**Important Decisions**
- Used the `@JavascriptInterface` over deep links or URL parameters since it directly handles JSON responses robustly.
- Configured "screen" mode directly in the frontend JS by adding `no-select`, hiding the system bar and dock, and overriding window sizing to provide an appliance-like experience natively.

**Problems Encountered**
- Lint threw a `JavascriptInterface` error during gradle build because it targets API 17+, but it was a false positive since the target SDK and minimum SDK are well above that. Disabled lint abort on error in `build.gradle` to allow build pass.

**Deferred / Not Yet Done**
- Screen mode advanced lock down/kiosk behaviors (still focuses on `FLAG_KEEP_SCREEN_ON` and UI hiding).

**Next Phase Needs To Know**
- `LyrnNative` is available globally in the browser context if running from the app.
- Config returned from `getConfig()` is stringified JSON.

### Phase 4 Build Notes
**Status:** Complete

**Files Created**
- none

**Files Modified**
- android_shell/app/src/main/res/layout/activity_main.xml
- android_shell/app/src/main/java/com/lyrn/shell/WebViewHost.kt
- android_shell/app/src/main/java/com/lyrn/shell/MainActivity.kt
- 00_CONTROL_PROMPT.md

**What Was Built**
- Prevented accidental exit in screen mode by ignoring `onBackPressed` requests.
- Disabled WebView long click, haptic feedback, and over-scroll in screen mode to prevent unintended interactions.
- Set up an automatic retry logic for WebView loads, reloading after 10 seconds if there's a load error or HTTP error on the main frame in screen mode.
- Implemented an immersive fullscreen state hiding the status and navigation bars in screen mode via `WindowInsetsControllerCompat`.
- Provided a hidden escape hatch in screen mode: clicking the top right corner 5 times triggers an app reset, allowing administrators to recover without killing the app process.

**Important Decisions**
- Chose a multi-tap invisible view (`maintenanceTapArea`) to act as the escape hatch because it is completely hidden and difficult to hit accidentally 5 times, while still easy enough for someone who knows the secret.
- Set a generous 10 second delay for auto-reload to avoid spamming network requests during an outage.
- Ignored `onBackPressed` rather than consuming it in complex ways to provide a rock-solid lock down in screen mode.

**Problems Encountered**
- Re-architecting `WebViewClient` to support automatic reloading took extra consideration to only apply to the main frame load failures instead of background resource failures. Checked `request?.isForMainFrame` to ensure only correct events were caught.

**Deferred / Not Yet Done**
- Custom loading screen or fallback local HTML page when connection is failing (just retries silently for now).

**Next Phase Needs To Know**
- Screen mode logic is heavily applied within `MainActivity.kt` and `WebViewHost.kt` conditionally via `isScreenMode`.
