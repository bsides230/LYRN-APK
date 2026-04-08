# LYRN Systems APK - Technical Audit Report

## 1. Executive Summary
- **Current Behavior:** The APK acts as a very basic, single-purpose Progressive Web App (PWA) wrapper. It allows a user to input a single URL and a "role" on first launch, saves this locally, and then loads that single URL in a full-screen, kiosk-like WebView on all subsequent launches.
- **App Type:** It behaves like a thin native wrapper for a web application (a "dumb viewer" or "kiosk browser").
- **Alignment Assessment:** **Highly Misaligned.** The app currently supports only a single hardcoded connection (1 to 1 mapping). The intended vision is a dashboard managing multiple connections (1 to N mapping) with features like card grids, connection status indicators, metadata settings (name, color, category), and modal/overlay WebView launching.

## 2. Build + Runtime Overview
- **Project Structure:** Standard single-module Android project (`android_shell/app/`).
- **Main Entry Points:** `SetupActivity.kt` (if unconfigured) or `MainActivity.kt` (if configured).
- **Important Files:**
  - `MainActivity.kt`: Hosts the WebView.
  - `SetupActivity.kt`: Initial configuration screen.
  - `AppConfig.kt`: SharedPreferences wrapper for saving the single URL.
  - `WebViewHost.kt`: Configures the WebView settings.
  - `NativeBridge.kt`: Exposes limited native functions to the loaded Javascript.
- **Build System:** Gradle (AGP 8.2.2, Kotlin 1.9.22). Builds successfully (`./gradlew assembleDebug`).
- **Startup Path:** `Launch -> OS checks Manifest -> SetupActivity launched -> Checks AppConfig`. If `isSetupComplete` is true, immediately routes to `MainActivity`, initializes WebView, and loads the saved URL.
- **Dependencies:** Standard AndroidX libraries. No external third-party SDKs or complex networking libraries like Retrofit are present.

## 3. Current Feature Inventory
1. **First-Launch Setup Configuration**
   - **Intended:** Allow user to set URL and Role.
   - **Actual:** Fully implemented. Shows simple UI, saves URL/Role to SharedPreferences.
   - **Files:** `SetupActivity.kt`, `activity_setup.xml`
2. **Kiosk WebView Loading**
   - **Intended:** Load the configured URL in full screen.
   - **Actual:** Fully implemented. Loads URL with JS enabled and DOM storage. Hides ActionBar.
   - **Files:** `MainActivity.kt`, `WebViewHost.kt`
3. **Javascript to Native Bridge**
   - **Intended:** Allow the PWA to request config or reset the app.
   - **Actual:** Fully implemented. Injects `LyrnNative` object into JS. Provides `getConfig()` and `resetConfig()`.
   - **Files:** `NativeBridge.kt`
4. **Maintenance Tap Area (Reset UI)**
   - **Intended:** A hidden area to tap and reset the app.
   - **Actual:** Broken / Stubbed. The UI element (`R.id.maintenanceTapArea`) exists in XML, but `MainActivity.kt` immediately sets its visibility to `GONE` unconditionally if the role is remote, and there are no click listeners wired to it for *any* role.

## 4. Screen Inventory
1. **Setup Screen**
   - **Name:** `SetupActivity`
   - **Purpose:** Get initial URL and Role.
   - **Reached by:** Launching app when `isSetupComplete` is false, or if JS triggers `resetConfig()`.
   - **Actions:** Select Role (Radio), Enter URL (Text), Save (Button).
   - **Result:** Saves to `AppConfig`, launches `MainActivity`.
   - **Completeness:** Complete (for single-URL paradigm).
2. **Main Screen**
   - **Name:** `MainActivity`
   - **Purpose:** Display the PWA.
   - **Reached by:** Normal launch when configured.
   - **Actions:** Android Back Button (navigates WebView history if possible, else exits).
   - **Result:** Renders web content.
   - **Completeness:** Complete (for single-URL paradigm).

## 5. Full User Flow Mapping
**First Launch:**
Launch -> `SetupActivity` -> Enter URL "http://10.0.x.x" -> Tap "Start LYRN" -> Saves state -> Launches `MainActivity` -> WebView loads URL

**Repeat Launch:**
Launch -> `SetupActivity` (invisible check) -> Sees config exists -> Launches `MainActivity` -> WebView loads URL

**Reset Flow (Triggered by PWA):**
PWA calls `window.LyrnNative.resetConfig()` -> Clears SharedPreferences -> Launches `SetupActivity`

## 6. State Management + Data Flow
- **State Storage:** SharedPreferences (`AppConfig.kt`).
- **Stored Data:** Only three primitives: `isSetupComplete` (Boolean), `role` (String), `targetUrl` (String).
- **Remote Data:** Handled entirely by the WebView. The native app has no knowledge of network data, sockets, or backends.
- **Assumptions:** Assumes the backend URL provided will always be available. There is no native error handling for WebView load failures (e.g., if the server is down, it just shows the default Chrome offline page).

## 7. Permissions + Device Behavior
- **Permissions:** `android.permission.INTERNET`. Required and used to load the WebView.
- **Services/Background:** None. The app dies when swiped away.
- **Hardware Access:** None configured natively (no camera/mic permissions declared in Manifest).

## 8. Backend / External Integration Audit
- **WebView Integration:** `WebViewHost.kt` enables JS, DOM storage, Database, and sets WideViewPort.
- **JS Interface:** `NativeBridge.kt` exposes `getConfig()` (returns JSON string of role/url) and `resetConfig()`.
- **Network Calls:** None made natively. All handled by the WebView.

## 9. Broken, Risky, or Confusing Areas
- **Dead Code:** `rgRole` variable in `SetupActivity.kt` is initialized but never used (Warning in compiler).
- **Stubbed Logic:** The `maintenanceTapArea` in `activity_main.xml` is hidden and has no logic attached, meaning a user cannot natively reset the app once configured unless the PWA itself implements the JS reset button. If the user enters a bad URL, they are permanently stuck and must clear app data via Android Settings.
- **Fragile Assumptions:** WebView lacks a `WebViewClient.onReceivedError` override. A bad connection results in an ugly browser error page.

## 10. Gap Analysis for Future Direction
**What exists vs. What is needed:**
The current app maps **1 App to 1 PWA**. The vision requires **1 App to Many PWAs**.
- **Data Model:** Currently stores 1 string URL. Needs a database (e.g., Room) or complex JSON SharedPreference to store a list of Node Objects (ID, Name, URL, IP/Port, Category, Color).
- **UI Architecture:** Currently has 1 Setup screen and 1 WebView screen. Needs a Dashboard Dashboard Activity (RecyclerView grid of cards), a Settings Modal/Dialog, and a mechanism to overlay a WebView on top of the dashboard.
- **Network Capability:** Currently relies purely on WebView. Needs native network polling (coroutines/Retrofit or simple HTTP client) to ping the saved IP:Ports and drive the "status light" UI on the cards before the WebView is even opened.

## 11. Recommended Next-Step Worklist
**Must understand first:**
- How the transition from the single-role to the multi-node UI impacts existing LYRN JS files that expect `LyrnNative.getConfig()` to return a single URL/Role.

**Architectural decisions before implementation:**
- Choose data persistence method for Node configurations (Room DB recommended over SharedPreferences for lists and categories).
- Decide if the "WebView Overlay" should be a Fragment added to the Dashboard Activity, or a separate Activity entirely.

**Safe cleanup/refactor candidates:**
- Delete `SetupActivity.kt`. It is incompatible with a dashboard-first design.
- Remove `maintenanceTapArea` from XML.

## 12. Code Reference Appendix
- `AndroidManifest.xml`: Declares entry points and Internet permission.
- `MainActivity.kt`: Hosts the WebView and delegates setup.
- `SetupActivity.kt`: Form to input the single URL/Role.
- `AppConfig.kt`: SharedPreferences wrapper for the single URL/Role.
- `WebViewHost.kt`: Boilerplate to configure Chrome client and settings.
- `NativeBridge.kt`: The `@JavascriptInterface` allowing web-to-native communication.
