# Build Notes

## v6.0.4 - Claude-Scoped Quick Status Panel + Dashboard Cleanup

This update moves the quick status surface into the Claude Code module (where it is needed during Claude operations) and removes the dashboard-level quick panel experiment.

- **Claude module quick status panel (`LYRN_v6/modules/ClaudeCode.html`)**
  - Added a right-edge toggle button in the terminal area that opens/closes a hidden-by-default status drawer.
  - Added at-a-glance status cards for terminal connection, Claude auth, worker state, model state, CPU/RAM, and last update timestamp.
  - Wired updates to existing module events (`setStatus`, `refreshAuth`) and the existing polling loop (`pollOnce` + `/health`) without backend API changes.

- **Claude mobile usability**
  - Retained and documented the explicit in-panel mobile close button for the left drawer (`✕`) plus backdrop close behavior.

- **Dashboard rollback + maximize fix retention (`LYRN_v6/dashboard.html`)**
  - Removed the dashboard-scoped quick status panel so status glance behavior lives only in the Claude module.
  - Kept the maximize geometry fix (`top: 0`, `height: 100%`) to eliminate top-gap artifacts.

- **Versioning + archival**
  - Bumped dashboard title to `v0.62`.
  - Archived prior dashboard iteration to `deprecated/Old/dashboard_v0.61.html`.
  - Archived prior Claude module iteration to `deprecated/Old/ClaudeCode_v6.0.3.html` before applying this update.

- **Logging updates**
  - No backend log format/schema changes were made.
  - Quick status values in the Claude module are derived from existing `/health` and auth polling responses.

## v6.0.3 - Claude Panel Readability, Mobile Close Controls, and Quick Status Drawer

This update improves dashboard/module usability on smaller screens, adds a fast right-side health glance panel, and removes maximize spacing artifacts.

- **Claude Code module panel sizing (`LYRN_v6/modules/ClaudeCode.html`)**
  - Increased desktop control panel minimum width and clamp range so section inputs are no longer compressed into unreadable widths.
  - Raised baseline input/preview control heights to improve readability and touch usability.
  - Preserved vertical scrolling behavior with themed scrollbars so all sections remain reachable when viewport height is limited.

- **Claude Code mobile drawer close behavior**
  - Added an explicit in-panel close button (`✕`) at the top of the mobile control drawer.
  - Kept backdrop-close behavior and existing hamburger open action for consistent open/close affordances on phones.

- **Dashboard quick status drawer (`LYRN_v6/dashboard.html`)**
  - Added a right-side quick status drawer (hidden by default) with a slim edge toggle button.
  - Drawer now provides at-a-glance values for backend connectivity, worker state, model state, CPU/RAM, and last health check time.
  - Wired drawer updates directly to existing `/health` polling so no backend contract changes were required.

- **Maximized window top-gap fix**
  - Updated maximize logic to fill the desktop workspace (`top: 0`, `height: 100%`) and remove the visual gap between dashboard top bar and app top bars when maximized.

- **Versioning + archival**
  - Bumped GUI title from `v0.60` to `v0.61`.
  - Archived previous dashboard file to `deprecated/Old/dashboard_v0.60.html` before applying this update.

- **Logging updates**
  - No new backend log files or schemas were introduced.
  - Quick status values are derived from the existing dashboard `/health` polling loop and existing status-light updates.

## v6.0.2 - Claude Module Guide, Panel Sizing, and Mobile Drawer

This update improves Claude Code module usability for first-time users and fixes left-panel layout constraints on smaller displays.

- **Claude module UX (`LYRN_v6/modules/ClaudeCode.html`)**
  - Added an always-visible circular **`?` guide button** to the header, positioned to the right of **Reconnect**.
  - Added a full in-module **User Guide popup** that documents every control group and action button with visual button chips and plain-language descriptions.
  - Added a clear **startup sequence section** in the guide so users launch the model with normal LYRN controls first, then connect/launch in the Claude module.

- **Left panel sizing and readability**
  - Updated the desktop control panel to use a wider, constrained range (`clamp`) with a minimum width to prevent form content compression.
  - Enabled horizontal resize on desktop so users can expand the control panel while keeping a vertical scrollbar for full section access.

- **Mobile vertical layout**
  - Added a top-left hamburger (`☰`) control for mobile widths.
  - Converted the left panel into an overlay drawer on mobile with a dim backdrop and smooth slide-in behavior.
  - Kept terminal content full width behind the drawer to match vertical app behavior across LYRN modules.

- **Versioning + archival**
  - Archived the previous Claude module implementation to `deprecated/Old/ClaudeCode_v6.0.html` before applying the new UX update.

- **Logging updates**
  - No backend log format changes were required in this update.
  - Existing Claude module runtime indicators remain intact (auth pill, connection status pill, and terminal `[sys]` state lines), now supplemented by guide-first onboarding to reduce operator error.

## v5.0.3 - Restore v4 KV-Cache Reuse

This update restores the high-performance KV-cache reuse behavior from v4 while maintaining compatibility with the v5 headless architecture. It resolves the "inconsistent sequence position" errors observed with llama-cpp-python when reusing context.

- **Headless Worker (`headless_lyrn_worker.py`):**
    -   **Single-Flight Inference:** Implemented a global lock to ensure only one generation request processes at a time.
    -   **KV Cache Reuse:** Added logic to compare the prefix of the current request's message history against the previous state. If the history is an append-only extension, the KV cache is reused. If the history diverges (e.g., edited logs, deleted files), `llm.reset()` is called to ensure consistency.
    -   **v4 Log Format:** Restored the v4 chat log format (`user\n...\n\nmodel\n...`) by removing v5 specific markers (`#MODEL_START#`) and ensuring the `model` header is present. This ensures compatibility with v4-style frontends.
    -   **Stop Handling:** Generation interruptions (`STOP`) now explicitly mark the KV cache as invalid for the next turn to prevent sequence errors.

- **Chat Manager (`chat_manager.py`):**
    -   **Backward Compatibility:** Updated `get_chat_history_messages` to support parsing both the legacy v4 log format and the v5 marker-based format. This ensures seamless operation regardless of the log style used.

## v5.0.2 - Legacy Cleanup & Framework Analysis

This update involves a comprehensive cleanup of the repository to remove legacy artifacts from previous versions and a deep dive into comparing LYRN v5 with other local agent frameworks.

- **Repository Cleanup:**
    -   Moved legacy documentation and asset directories to `deprecated/v4_artifacts/` (`docs/`, `images/`, `languages/`, `lyrn_docs/`, `screenshots/`, `themes/`).
    -   Moved legacy configuration and utility files to `deprecated/v4_artifacts/` (`chat_review.txt`, `LYRN Style Guide.html`, `QUICK_START.md`, `personality.json`, `quotes.txt`, `settings.json.bk`, `verification_error.png`).
    -   The root directory is now streamlined to contain only files essential for the LYRN v5 Dashboard and Headless Worker operation.

- **Framework Analysis:**
    -   (Pending) A detailed report `framework_report.md` will be generated comparing LYRN v5's structured memory and headless architecture against other local agent frameworks.

## v5.0.1 - Chat UX & Stability Improvements

This update focuses on improving the Chat Interface user experience, adding support for reasoning models, and fixing backend stability issues on Windows.

- **Backend (Worker):**
    -   **Encoding Fix:** Modified `headless_lyrn_worker.py` to force UTF-8 encoding for `sys.stdout` and `sys.stderr`. This prevents the worker from crashing with `UnicodeEncodeError: 'charmap' codec...` when models generate special characters (e.g., non-breaking hyphens) on Windows consoles.
    -   **Robust Parsing:** Updated `chat_manager.py` regex to handle unclosed role blocks (e.g., `#MODEL_START#` without a closing tag). This ensures that if a generation is interrupted or the user reopens the chat mid-stream, the partial content is correctly displayed instead of being ignored.

- **Dashboard:**
    -   **Minimize Window:** Added a minimize button (`_`) to the window controls. This hides the window (keeping the DOM and stream active in the background) rather than closing it (which destroys the connection).

- **Chat Interface:**
    -   **Thinking Mode Support:** Added native support for reasoning models (e.g., DeepSeek-R1) that output `<think>...</think>` tags.
        -   **Collapsible UI:** Thinking process is rendered in a distinct, collapsible accordion block (`.think-block`).
        -   **Setting:** Added a "Show Thinking Process" checkbox in the module settings to toggle visibility globally.
        -   **Streaming:** The thinking block updates in real-time during generation.

- **Model Controller:**
    -   **Auto-Refresh:** Added a listener to the Model Selector dropdown. Clicking it now automatically refreshes the model list from the backend, eliminating the need to restart the module after downloading a new model.

## v5.0.0 - Dashboard v5 & Cleanup (Current)

This update marks the official transition to the Dashboard v5 architecture and a major cleanup of the codebase.

- **Architecture Overhaul:**
    -   Fully transitioned to `lyrn_web_v5.py` (FastAPI) and `headless_lyrn_worker.py`.
    -   Legacy CustomTkinter GUI files (`lyrn_sad_v4.*.py`) have been moved to `deprecated/v4_artifacts/`.
    -   Unused Python modules (`episodic_memory_manager.py`, `cycle_manager.py`, `color_picker.py`, `themed_popup.py`, `confirmation_dialog.py`, `model_loader.py`, `system_checker.py`, `help_manager.py`, `system_interaction_service.py`) have been deprecated.

- **Model Controller:**
    -   Added a "DEFAULT" preset slot to the Model Controller module.
    -   Users can now save their preferred configuration as the default preset by entering 'default' or 'd' when saving.
    -   The default preset button appears before the numbered presets.

- **Documentation:**
    -   Created new `README.md` focused on v5.
    -   Archived v4 documentation and build notes to `deprecated/v4_artifacts/`.

- **PWA & Startup:**
    -   Added `manifest.json` and `sw.js` to enable PWA installation.
    -   Added `start_lyrn.bat` for easy startup without command line.
    -   Added `port.txt` to configure the web server port (default: 8080).
    -   Cleaned up root directory by moving `req.md`, `GUI_ANALYSIS.md`, `MEMORY_SYSTEM_ANALYSIS.md`, and `settings.json.bk` to `deprecated/v4_artifacts/`.

- **Bug Fixes & Hardening:**
    -   **Chat Logic:** Fixed an issue where the user's latest message was duplicated in the prompt (once from history, once from the active trigger), causing "Conversation roles must alternate" errors. The Worker now explicitly excludes the active chat file when retrieving history.
    -   **Path Handling:** Updated `settings.json` to use relative paths instead of absolute Windows paths. This prevents the creation of invalid directories (e.g., folders named `D:\LYRN-SAD\global_flags`) when the backend is run in a Linux environment.
    -   **Git:** Added `chat_trigger.txt` to `.gitignore`.

- **Startup & Authentication:**
    -   **Token Tools:** Added `token_generator.py` (and `generate_token.bat`) to generate secure admin tokens into `admin_token.txt`.
    -   **Startup Wizard:** Updated `start_lyrn.bat` to prompt users (Y/N) for dependency installation.
    -   **Quick Start:** Added `quick_start.bat` for immediate server launch skipping checks.
    -   **File-Based Auth:** Backend now reads `admin_token.txt` for the admin token, falling back to environment variables.
    -   **Model Manager UI:** Updated Authentication Modal to support direct file upload of `admin_token.txt` for easier login.

## Philosophy & Rules (Ported)

-   **Efficiency and Accessibility:** The primary goal is to create a powerful AI cognition framework that is lightweight enough to run on standard consumer hardware.
-   **Structured Memory over Prompt Injection:** All core context—personality, memory, goals—lives in structured text files and memory tables. The LLM reasons from this stable foundation rather than having it repeatedly injected into a limited context window.
-   **Simplicity and Robustness:** The architecture is inspired by the simplicity of 1990s text-based game parsers. The framework's job is to be a robust, simple system for moving data; the LLM's job is to do the heavy lifting of reasoning.
-   **UI Development:** New modules must be implemented as single-file solutions (combining HTML, CSS, and JS) in `LYRN_v5/modules/` to facilitate loading on smaller systems and minimize floating dependencies. UI must strictly follow `LYRN Style Guide.html`.

### Version 6.0 Update
- **Feature**: Added Claude Code Control Center GUI
  - Integrated `xterm.js` for an interactive terminal.
  - Added configuration flags and preset execution commands in the UI.
- **Backend**: Implemented WebSocket terminal streaming in `start_lyrn.py`.
  - Added `WebTerminalSession` (Windows) and `LocalPTYSession` (Linux/Mac using `pty`).
  - Added dependencies: `websockets`, `uvicorn[standard]`, `pty`.
- **Logging Updates**:
  - Terminal connection status and errors are now printed to `stdout` securely.

## v6.0.1 - Claude Code Runtime Reliability Audit (Remote + venv)

- **Backend hardening (`start_lyrn.py`)**
  - Added deterministic Claude binary resolution for backend-launched subprocesses.
  - Added support for explicit `LYRN_CLAUDE_BIN` / `CLAUDE_BIN` overrides.
  - Added PATH normalization for backend child processes so resolved Claude bin directories are inherited even when service PATH differs from interactive shells.
  - Updated orchestrated run launch and auth status checks to use resolved binary path and explicit subprocess environment.
  - Improved failure messaging when Claude is not visible in backend runtime context.

- **Terminal reliability (`start_lyrn.py`)**
  - Fixed websocket terminal reconnect behavior by introducing session reuse keyed by SID.
  - Added delayed cleanup for terminal sessions so brief browser disconnect/reconnect does not kill the shell.
  - Injected resolved Claude binary directory into PTY session PATH to reduce “works in local shell, fails in remote backend terminal” drift.

- **Logging updates**
  - Added clearer backend-facing error messages for Claude binary discovery failures (includes actionable env guidance).
  - Preserved terminal connection/disconnection logs and now keep reconnect continuity visible through session reuse behavior.
