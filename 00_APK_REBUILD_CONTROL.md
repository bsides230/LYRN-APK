# Project Title
LYRN Systems APK - Multi-Node Dashboard Rebuild

# Objective
Transition the LYRN Systems APK from a single-URL PWA wrapper into a multi-node dashboard that manages multiple PWA connections (cards), displays their status, and launches them as overlays.

# Current State Summary
The app is a single-purpose wrapper. It stores one URL and Role in SharedPreferences. On launch, it opens `MainActivity` containing a full-screen WebView pointing to that URL.

# Target State Summary
The app will be a Dashboard showing a grid/list of saved Node Cards (each with IP, Name, Category, Color). It will ping nodes for status lights. Clicking a card opens that specific PWA in a WebView overlay, which can be dismissed to return to the dashboard.

# Phase Index
| Phase | Name | Goal | Status | File |
|-------|------|------|--------|------|
| 1 | Foundation & Data Model | Replace single-URL storage with a multi-node data model | Complete | `PHASE_01_FOUNDATION_AND_DATA_MODEL.md` |
| 2 | Dashboard UI & Node Management | Build the RecyclerView dashboard and node creation UI | Complete | `PHASE_02_DASHBOARD_AND_NODE_MANAGEMENT.md` |
| 3 | WebView Integration & Bridge Updates | Launch WebView as an overlay and update NativeBridge | Not Started | `PHASE_03_WEBVIEW_INTEGRATION.md` |
| 4 | Status Pinging & Polish | Add connection status polling and finalize user flows | Not Started | `PHASE_04_STATUS_PINGING_AND_POLISH.md` |

# Global Rules
- Do not drift from defined scope
- Preserve working functionality where possible
- Prefer clean replacements over patching broken architecture
- Record deviations before making them
- Keep notes updated as work progresses
- Check off completed tasks in both the phase file and control file

# Global Checklist
- [x] Phase 1: Foundation & Data Model
- [x] Phase 2: Dashboard UI & Node Management
- [x] Phase 3: WebView Integration & Bridge Updates
- [ ] Phase 4: Status Pinging & Polish

# Build Notes Section
### Assumptions
- **Data Persistence:** Opting for SharedPreferences with JSON serialization (using Gson or Moshi) for simplicity over Room, given the list of nodes will be small and we want to keep data storage simple.
- **NativeBridge:** The bridge will pass the specific node's config (URL, Role) to the PWA when launched. The PWA does not need to know about other nodes.
- **UI Flow:** The Android Back button will dismiss the WebView overlay and return to the dashboard.
- **Networking:** Status pinging will only occur while the dashboard is in the foreground (no background service required).
- **Role Handling:** The "role" concept will be preserved per node.

# Phase Completion Tracking
- [x] Phase 1: Complete
- [x] Phase 2: Complete
- [x] Phase 3: Complete
- [ ] Phase 4: Not Started

### Phase 1: Foundation & Data Model
- **Status:** Complete
- **What was done:**
  - Added Gson dependency to `app/build.gradle` for JSON serialization.
  - Added Robolectric and androidx.test.core dependencies for testing.
  - Created `Node` data model with ID, Name, URL, Category, Color, and Role.
  - Created `NodeRepository` managing SharedPreferences storage, persisting a list of nodes via JSON.
  - Updated `AppConfig` to act as a backward compatibility layer, mapping its legacy `role` and `targetUrl` getters/setters to the first node in the repository, and migrating any legacy configuration to a single node.
  - Verified project compiles and tests pass successfully.
- **Why it was done:** The app needed a flexible multi-node structure to evolve into a dashboard, replacing the hardcoded single-URL configuration.
- **Deviations:** Refactored `AppConfig` to wrap `NodeRepository` instead of replacing it entirely, maintaining backward compatibility for existing `MainActivity` and `SetupActivity` logic that heavily relies on `AppConfig` until they are updated in future phases.
- **Decisions made:** SharedPreferences + JSON was chosen as planned. Migrating legacy `role` and `target_url` config keys directly into the first `Node` entry simplifies transitions.

### Phase 2: Dashboard UI & Node Management
- **Status:** Complete
- **What was done:**
  - Created `DashboardActivity` with a `RecyclerView` and `FloatingActionButton`.
  - Added `NodeAdapter` for binding `Node` objects to the `RecyclerView`.
  - Created layouts `activity_dashboard.xml` and `item_node_card.xml`.
  - Created `dialog_node_edit.xml` and implemented a dialog to add/edit/delete nodes.
  - Removed `SetupActivity` and updated `AndroidManifest.xml` to set `DashboardActivity` as the launcher.
  - Updated `MainActivity` and `NativeBridge` to bypass/replace legacy `SetupActivity` logic.
- **Why it was done:** Replacing the old 1-to-1 setup with a dashboard allowing multi-node management required for the goal.
- **Deviations:** Modified `MainActivity`'s setup logic block to not reference the deleted `SetupActivity`. Modified `NativeBridge`'s `resetConfig` method to launch `DashboardActivity`.
- **Decisions made:** Using an `AlertDialog` for Add/Edit is simpler and faster than fragments or bottom sheets.

### Phase 3: WebView Integration & Bridge Updates
- **Status:** Complete
- **What was done:**
  - Refactored `NativeBridge.kt` to accept `role` and `targetUrl` explicitly, removing the dependency on `AppConfig`. Updated its `resetConfig` method to `finish()` the current Activity if possible, or launch the Dashboard.
  - Refactored `MainActivity.kt` to accept `EXTRA_URL` and `EXTRA_ROLE` intent extras and pass them to `NativeBridge` instead of using `AppConfig`.
  - Updated `DashboardActivity.kt` so that clicking a node card launches `MainActivity` with the selected node's `url` and `role` as extras.
  - Verified logic using tests and compilation.
- **Why it was done:** To allow the WebView to open dynamically with the configuration of any node clicked on the dashboard, matching the new multi-node architecture.
- **Deviations:** Modified `resetConfig` in `NativeBridge.kt` to explicitly finish the Activity if it is an instance of `Activity`, ensuring the WebView is cleanly dismissed from the stack.
- **Decisions made:** Reusing `MainActivity` by passing intent extras avoids creating unnecessary Fragment/Activity abstractions, and the default back button handling (`super.onBackPressed()`) naturally returns the user to the Dashboard.
