# Phase Title
Dashboard UI & Node Management

# Phase Goal
Build the main dashboard interface to display saved nodes and the UI to add/edit them.

# Why This Phase Exists
Users need a visual interface to manage their multiple PWA connections. This phase replaces the old `SetupActivity`.

# Scope
- Create `DashboardActivity` with a `RecyclerView`.
- Create a `NodeCard` UI layout for the list items.
- Create an "Add/Edit Node" dialog or bottom sheet for inputting node details.
- Wire the UI to the `NodeRepository` created in Phase 1.

# Out of Scope
- Launching the WebView.
- Implementing the status pinging mechanism.

# Prerequisites
- Phase 1 (Foundation & Data Model) is complete.

# Task Checklist
- [x] Create `DashboardActivity` and set it as the main launcher activity in `AndroidManifest.xml`.
- [x] Implement `RecyclerView` in `DashboardActivity` layout.
- [x] Create `item_node_card.xml` layout for individual nodes (showing Name, URL, Category, Color).
- [x] Implement `NodeAdapter` for the `RecyclerView`.
- [x] Create UI for adding/editing a node (e.g., a simple DialogFragment with fields for Name, URL, Category, Color, Role).
- [x] Connect the UI actions (Add, Edit, Delete) to the `NodeRepository`.
- [x] Remove `SetupActivity` and its related XML file as it is now obsolete.

# Validation Checklist
- [x] App launches directly to the `DashboardActivity`.
- [x] User can add a new node and see it appear in the list.
- [x] User can edit an existing node and see changes reflect.
- [x] User can delete a node.
- [x] Data persists across app restarts.

# Risks / Watchouts
- Ensuring the RecyclerView updates correctly when the underlying data changes.
- Handling input validation (e.g., ensuring URLs are well-formed before saving).

# Notes
- Keep the UI simple; standard Material Design components are sufficient.
