# Build Notes

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

### v6.1 - Job Instructions to Dynamic Snapshots and Model Flow Documentation Rebuild

**Architectural Updates**
- Migrated job instructions to function entirely as temporary Dynamic Snapshots via the `DSManager`.
- Removed the old `dynamic_snapshot` concept from job definitions, allowing `instructions` themselves to act as the snapshot context.
- Removed late-bound prompt injection from `model_runner.py` to prevent prompt pollution and duplication. Job instructions now properly scope to the beginning of the context loop for caching and clean up after execution.

**Documentation Updates**
- Rebuilt `lyrn-current-model-flow.html` to accurately map the updated architecture.
- Added comprehensive breakdowns of the Relational Web Index (RWI), KV Cache utilization, and DSManager interaction throughout the execution lifecycle.

**Logging Updates**
- Simplified component saving to only retain active job instructions as a single payload to the active `dynamic_snapshot` block within `build_prompt`.
