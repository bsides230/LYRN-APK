# Phase Title
WebView Integration & Bridge Updates

# Phase Goal
Launch the WebView as an overlay when a node card is clicked, and ensure the NativeBridge provides the correct context to the PWA.

# Why This Phase Exists
This connects the new dashboard to the core functionality of loading the PWA. It shifts the WebView from being the root view to a dismissible overlay.

# Scope
- Refactor `MainActivity` or create a new `WebViewActivity`/Fragment to act as the overlay.
- Update `NativeBridge` to serve the specific configuration of the selected node.
- Implement dismissal logic (Android Back button).

# Out of Scope
- Status pinging.

# Prerequisites
- Phase 2 (Dashboard UI) is complete.

# Task Checklist
- [ ] Refactor existing WebView logic (from `MainActivity`) into a new `WebViewFragment` or keep it in `MainActivity` but launch it via an Intent with extras from the Dashboard. (Using an Activity launched from the Dashboard is simpler).
- [ ] Update `DashboardActivity` so that clicking a `NodeCard` launches the WebView component, passing the selected `Node`'s URL and Role.
- [ ] Modify `NativeBridge.kt` and its initialization so `getConfig()` returns the specific data for the currently active node, rather than the global `AppConfig`.
- [ ] Implement/verify logic so pressing the Android Back button while the WebView is active closes the WebView and returns the user to the Dashboard.
- [ ] Ensure the PWA's JS reset function (`resetConfig`) now closes the WebView and returns to the Dashboard (instead of launching the old Setup screen).

# Validation Checklist
- [ ] Clicking a node in the dashboard opens its specific URL in the WebView.
- [ ] The PWA receives the correct role via `LyrnNative.getConfig()`.
- [ ] Pressing Back dismisses the WebView and shows the dashboard.
- [ ] PWA reset function returns to dashboard.

# Risks / Watchouts
- Ensuring memory is managed correctly (WebView is destroyed when returning to the dashboard).
- Compatibility with existing PWA JS logic that expects `LyrnNative.getConfig()` to behave synchronously.

# Notes
- Launching a separate Activity for the WebView might be cleaner than a Fragment for full-screen kiosk mode, as it naturally handles the back stack and isolation.
