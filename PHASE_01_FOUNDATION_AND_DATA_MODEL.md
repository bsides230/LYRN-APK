# Phase Title
Foundation & Data Model

# Phase Goal
Replace the existing single-URL `AppConfig` storage with a mechanism capable of storing multiple nodes (1-to-N).

# Why This Phase Exists
Before building a dashboard, the app must have a way to store and retrieve multiple node configurations. This phase breaks the single-instance assumption.

# Scope
- Define a `Node` data model (ID, Name, URL, Category, Color, Role).
- Refactor `AppConfig` (or create a new `NodeRepository`) to store a list of `Node` objects using JSON serialization in SharedPreferences.
- Provide CRUD (Create, Read, Update, Delete) methods for nodes.

# Out of Scope
- Building the UI (Dashboard or Forms).
- Modifying the WebView or NativeBridge.
- Implementing networking/pinging.

# Prerequisites
- Current codebase is compiling and stable.

# Task Checklist
- [ ] Add JSON serialization library dependency (e.g., Gson) to `app/build.gradle`.
- [ ] Create `Node` data class in a new model package.
- [ ] Create `NodeRepository` class to manage SharedPreferences storage.
- [ ] Implement `getNodes()`, `addNode()`, `updateNode()`, `deleteNode()` methods.
- [ ] Update `AppConfig` to either be replaced by `NodeRepository` or wrap it to maintain backward compatibility temporarily if needed (though replacing is preferred).

# Validation Checklist
- [ ] Project builds successfully.
- [ ] Unit tests (if added) or manual logging confirm nodes can be saved, retrieved, and deleted from SharedPreferences.

# Risks / Watchouts
- Ensuring data persistence works correctly across app restarts.
- Handling data migration if old `AppConfig` data exists (convert the single existing entry into the first `Node` in the new list to prevent data loss).

# Notes
- Opting for SharedPreferences + JSON instead of Room to keep the implementation simple and avoid boilerplate, as the list of nodes is expected to be small.
