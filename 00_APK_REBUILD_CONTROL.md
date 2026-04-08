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
| 1 | Foundation & Data Model | Replace single-URL storage with a multi-node data model | Not Started | `PHASE_01_FOUNDATION_AND_DATA_MODEL.md` |
| 2 | Dashboard UI & Node Management | Build the RecyclerView dashboard and node creation UI | Not Started | `PHASE_02_DASHBOARD_AND_NODE_MANAGEMENT.md` |
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
- [ ] Phase 1: Foundation & Data Model
- [ ] Phase 2: Dashboard UI & Node Management
- [ ] Phase 3: WebView Integration & Bridge Updates
- [ ] Phase 4: Status Pinging & Polish

# Build Notes Section
### Assumptions
- **Data Persistence:** Opting for SharedPreferences with JSON serialization (using Gson or Moshi) for simplicity over Room, given the list of nodes will be small and we want to keep data storage simple.
- **NativeBridge:** The bridge will pass the specific node's config (URL, Role) to the PWA when launched. The PWA does not need to know about other nodes.
- **UI Flow:** The Android Back button will dismiss the WebView overlay and return to the dashboard.
- **Networking:** Status pinging will only occur while the dashboard is in the foreground (no background service required).
- **Role Handling:** The "role" concept will be preserved per node.

# Phase Completion Tracking
- [ ] Phase 1: Not Started
- [ ] Phase 2: Not Started
- [ ] Phase 3: Not Started
- [ ] Phase 4: Not Started
