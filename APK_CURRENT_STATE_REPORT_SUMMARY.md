# LYRN Systems APK - Executive Summary

## What the App Does Now
The APK currently functions as a single-purpose, hardcoded PWA viewer. On first launch, the user provides a single URL and a "role". The app saves this, and on all future launches, it simply opens a full-screen, kiosk-mode WebView pointing to that single URL. It has no native backend awareness and acts only as a wrapper.

## Current Flow in Brief
1. App Launch -> Check Configuration
2. If No Config: Show `SetupActivity` -> Enter URL -> Save -> Go to Step 3.
3. If Config Exists: Show `MainActivity` -> Hide Android UI -> Load URL in WebView -> Wait for user to interact with web content or trigger JS reset.

## Biggest Gaps against Intended Vision
The intended vision is a **Dashboard Manager for multiple connections (1 to N)**, while the current app is a **Single Viewer (1 to 1)**.
1. **Data Model:** It can only store one URL. It needs a database to store a list of Node Cards with settings (IP, name, color, category).
2. **User Interface:** It lacks a Dashboard grid. `SetupActivity` needs to be replaced entirely with a multi-card RecyclerView Dashboard, and the WebView needs to become an overlay/modal rather than the root view.
3. **Native Networking:** It lacks the ability to natively ping IPs to drive a "status light" on the cards; currently, networking only happens inside the active WebView.

## Top 5 Next Actions
1. **Architect Data Layer:** Implement a local database (e.g., Room) to store lists of Node Objects (IP, Name, Category, Color).
2. **Build Dashboard UI:** Create a new `DashboardActivity` with a RecyclerView to display the saved Node Cards.
3. **Implement Settings Modal:** Create the UI logic for adding/editing a Node Card (the text boxes, color picker, and category dropdown you described).
4. **Implement Status Pinging:** Add a native background task or coroutine to periodically ping the saved IP/Ports to update the connection status light on the Dashboard cards.
5. **Convert WebView to Overlay:** Refactor `MainActivity` (or create a new Fragment) so that tapping a card opens the WebView *on top* of the Dashboard, allowing the user to dismiss it and return to the grid.