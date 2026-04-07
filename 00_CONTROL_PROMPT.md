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
- [ ] Phase 2 complete
- [ ] Phase 3 complete
- [ ] Phase 4 complete

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
