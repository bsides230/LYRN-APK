# Phase Title
Status Pinging & Polish

# Phase Goal
Implement periodic networking checks to update connection status indicators on the dashboard cards, and perform final polish.

# Why This Phase Exists
This fulfills the requirement of the dashboard acting as a live status monitor for the nodes, rather than just a static list of links.

# Scope
- Implement a background task/coroutine in the `DashboardActivity` or a bound service to ping node URLs.
- Update the `NodeCard` UI to display a status indicator (e.g., green/red circle).
- Handle cleanup and final polish of the user experience.

# Out of Scope
- Complex background services that run when the app is killed.

# Prerequisites
- Phase 1, 2, and 3 are complete.

# Task Checklist
- [x] Add basic UI element to `item_node_card.xml` for status (e.g., a colored dot).
- [x] Implement a mechanism (e.g., Coroutines + simple HTTP HEAD/GET request) to periodically ping the URL of each saved node.
- [x] Update the `NodeAdapter` to refresh the status indicator based on ping results.
- [x] Ensure pinging only occurs when `DashboardActivity` is in the foreground (`onResume` to start, `onPause` to stop) to save resources.
- [x] Add basic error handling for the ping requests (timeouts, connection refused).
- [x] Review entire flow for edge cases (e.g., empty dashboard state).

# Validation Checklist
- [x] Nodes that are reachable show a "green" or online status.
- [x] Nodes that are unreachable (bad IP, server down) show a "red" or offline status.
- [x] Status updates automatically while sitting on the dashboard screen.
- [x] App does not crash if a node is unreachable.

# Risks / Watchouts
- Pinging many nodes could cause UI jank if not properly offloaded to IO threads.
- Timeouts need to be reasonable so the UI updates relatively quickly (e.g., 2-3 second timeout max).

# Notes
- A simple `HttpURLConnection` is sufficient for the ping check; no need to import Retrofit just for this feature.
