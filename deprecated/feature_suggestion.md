# Feature Suggestions for LYRN-AI GUI

This document tracks feature suggestions, their status, and implementation history.

---
## Suggested

These features have been proposed and are awaiting approval.

---
## Approved

These features have been approved and are planned for implementation.

### 1. Stable Console Log Redirection
The feature to redirect console output to the 'View Logs' window was temporarily disabled to fix a startup issue. A more stable method should be investigated and implemented to restore this functionality without causing the application to hang.

### 2. System Tray Icon
For better desktop integration, especially with a frameless window, a system tray icon could be added. This would allow the application to be truly minimized (hidden from the taskbar) and restored. It could also provide a context menu for quick actions like reloading the model or quitting. USER_NOTE: use the .png in the images folder to create the logo on top of this)

---
## Future

These are long-term ideas and larger projects planned for future development cycles.

### 1. Plugin System
A plugin system could be implemented to allow for easy extension of the GUI's functionality. This would allow third-party developers (or even the core team) to add new features without having to modify the core codebase. For example:
- New widgets for the sidebars (e.g., a calculator, a notepad, a web browser).
- New job types for the job processor.
- New data sources for the HWiNFO monitor.

### 2. Chat History Search
The ability to **search through past conversations** would be a very useful feature. This would allow users to quickly find information from previous interactions with the model.

### 3. Chat History Browser
Instead of just saving chats to a folder, a more robust chat history browser could be implemented. This would allow users to view a list of past conversations, search their contents, and load them back into the chat window.

### 4. Multi-Model Support
The ability to have **multiple models loaded at once** and switch between them without having to reload from disk would be a huge performance improvement. This would be especially useful for users who frequently switch between different models for different tasks.

### 5. Advanced Theming in UI
The theme builder could be expanded to allow users to control more aspects of the theme from the UI, such as font choices, corner radii for various widgets, and border widths.

### 6. Resizable UI Panes
To provide a more flexible user experience, the main three-column layout could be updated to allow the user to resize the panes by dragging a divider between them.

### 7. Theme Import/Export
To enhance theme customization and sharing, an import/export feature could be added to the Theme Builder. This would allow users to save their themes to a portable file (e.g., `.json`) and import themes created by others.

### 8. Advanced Model Management
The model selection screen could be enhanced to provide more details about the models, such as file size, quantization level, and other metadata. A feature to download models directly from a URL could also be added to streamline the process of adding new models.

---
## Implemented

These features have been successfully implemented in the application.

### Completed in v6.8
- **UI Overhaul:** The system status section has been overhauled with a new layout, including a button to load the model and a restored text box for general status messages.
- **Color Theming:** The "Purple Dark" and "Purple Light" themes have been renamed to "LYRN Dark" and "LYRN Light" and now use the official LYRN purple color.
- **Asset Replacement:** The Lyrn logo is now loaded as a PNG file instead of a JPG.

### Completed in v6.5
- **Custom Frameless Window:** The application now runs in a custom frameless window, with a custom top bar containing window controls (close, minimize, maximize) and a settings button.
- **Full Theme Management in UI:** The "Theme Builder" tab has been enhanced to allow for full lifecycle management of themes.
- **Command Palette:** A command palette, triggered by `Ctrl+Shift+P`, has been added for power users.
- **Copy-to-Clipboard for Responses:** A "Copy" button has been added for easy copying of the assistant's last response.
- **Per-Message Token Count:** The token count for both prompt and response is now displayed in the chat interface.
- **Asynchronous Model Loading with Progress Bar:** The UI now displays a progress bar during model loading.
- **Live Theme Preview:** The theme preview in the settings now updates automatically.
- **Enhanced System Status Panel:** The system status panel has been redesigned for better clarity.
- **Glass Theme Removal:** The experimental "Glass" theme was removed due to instability.

### Completed in v6.4
- **Relocate Settings Button:** The settings button was moved for improved visibility.
- **Add Application Logo:** The header logo is now loaded from an image file.
- **Unify System Status Background Color:** The status panel background now matches the theme's primary color.
- **Rename "Show LLM Log" Button:** Renamed to "View Logs" for clarity.
- **Rename "Clear Chat" Button:** Renamed to "Clear Display Text" to be more descriptive.
- **Add "Clear Chat Folder" Button:** A new button was added to delete all saved chat logs.

---
## Denied

These features were proposed but have been denied for implementation.

### 1. UI Logo Management
A setting to allow the user to select a logo image file from the UI was denied to avoid issues with file paths and formats.

### 2. Workspace Management
The ability to save and load different "workspaces" (including paths, prompts, themes, etc.) was denied.
