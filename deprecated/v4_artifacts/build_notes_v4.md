## v4.2.8 - HTML RWI Builder (2025-12-04)

This update introduces a new HTML-based module for building the RWI system prompt, replacing the old `SystemPromptBuilderPopup`.

- **New RWI Builder Module:**
    - A new web-based interface has been created in `modules/rwi_builder/`.
    - It runs on a local Python server (port 8000) started by the main application.
    - The interface allows users to create, edit, reorder, and toggle prompt components.
    - It communicates with the backend via API endpoints to read and write configuration files in `build_prompt/`.
    - Style matches the `LYRN Style Guide.html`.

- **GUI Changes:**
    - The "System Prompt" button now opens the new HTML interface in the default web browser.
    - Removed `SystemPromptBuilderPopup`, `ComponentBuilderPopup`, and `FullRWIViewerPopup` classes and files.
    - Removed `full_rwi_viewer_popup.py`.

- **Versioning:**
    - The main application file has been versioned to `lyrn_sad_v4.2.8.py`.
    - The previous version `lyrn_sad_v4.2.7.py` (and `.pyw`) have been archived in `deprecated/Old/`.

### Logging
- No changes to logging mechanisms were necessary for this update.

## v4.2.9 - RWI Builder Enhancements (2025-12-05)

This update adds requested features to the HTML RWI Builder.

- **RWI Builder Improvements:**
    - **File Lock:** Added a toggle to lock the master prompt from being overwritten by the builder. The state is saved in `build_prompt/builder_config.json`.
    - **Pinning:** Added functionality to pin components to the top of the list. Order and pin status are automatically saved.
    - **Theme Toggle:** Added a theme toggle in the new footer to switch between Light and Dark modes.
    - **Renamed HTML:** Renamed `index.html` to `rwi_builder.html` for better linking structure.

- **GUI Changes:**
    - Updated `lyrn_sad_v4.2.9.py` to point to the new `rwi_builder.html` URL.

- **Versioning:**
    - The main application file has been versioned to `lyrn_sad_v4.2.9.py`.
    - The previous version `lyrn_sad_v4.2.8.py` has been archived in `deprecated/Old/`.

### Logging
- Updated RWI Server to handle settings endpoints.

## v4.2.11 - HTML Job Manager Finalization (2025-12-05)

This update finalizes the port of the Job Manager to an HTML-based module, fixing initialization issues and removing legacy code.

- **Job Manager Fixes:**
    - **Initialization:** Fixed an issue where the Job Manager server started before backend managers were initialized, causing tabs to be empty. Server start is now deferred until initialization is complete.
    - **Fetching:** Updated server logic to access managers dynamically via the main app instance.

- **Feature Updates:**
    - **Reflection Removed:** Completely removed the "Reflection" cycle functionality, including the tab in the UI, backend endpoints, and execution logic.
    - **Pinning Implemented:** Added "Pinning" functionality to the HTML Job Manager. Pinned jobs are now visually distinct and protected from deletion.
    - **Execution:** Verified that jobs triggered from the web interface correctly execute in the main application's context.

- **Cleanup:**
    - **Legacy UI Removed:** Deleted `JobWatcherPopup`, `DaySchedulePopup`, `JobBuilderPopup`, `JobInstructionViewerPopup`, and `DraggableListbox` from the main Python application.
    - **Logic Ported:** Ported the logic for managing active jobs (pinning) from `JobWatcherPopup` to `LyrnAIInterface`.

- **Versioning:**
    - The main application file has been versioned to `lyrn_sad_v4.2.11.py`.
    - The previous version `lyrn_sad_v4.2.10.py` has been archived in `deprecated/Old/`.

### Logging
- Added traceback printing to Job Manager Server for better error visibility.

## LYRN Dashboard v5 - Inventory Module (2025-12-05)

Implemented a standalone Inventory Module for the upcoming Dashboard v5.

- **Inventory Interface:**
    - Created `LYRN_v5/modules/Inventory.html` as a standalone single-file module.
    - Implemented a Grid View for inventory items and a specific "Equipped" tab.
    - Included a Details Panel that displays item information on selection.
    - Implemented an "Equip/Unequip" toggle button.
    - Added a Settings modal to configure the remote API endpoint (URL/Port), persisting to `localStorage`.
    - **No Backend:** This module is purely frontend and uses `fetch` to communicate with a configurable API. Included mock data fallback for offline verification.
