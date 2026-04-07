import customtkinter as ctk
import os
import json
from tkinter import colorchooser
from typing import List, Dict
from color_picker import CustomColorPickerPopup
import importlib.util
import sys
import tkinter as tk
import queue


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _widget_id(widget: tk.Widget) -> str:
    """Generate a stable identifier for a widget based on its path."""
    return f"{widget.winfo_class()}::{widget.winfo_pathname(widget.winfo_id())}"


def _walk(root: tk.Widget) -> list:
    """Walk the widget tree starting from root, returning a flat list."""
    stack = [root]
    out: list = []
    while stack:
        w = stack.pop(0)
        out.append(w)
        stack[0:0] = list(w.winfo_children())
    return out


def load_gui_module(filepath: str):
    """Dynamically load a Python module from a given file path."""
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"GUI module not found: {filepath}")
    module_name = os.path.splitext(os.path.basename(filepath))[0]
    spec = importlib.util.spec_from_file_location(module_name, filepath)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load spec for {filepath}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[call-arg]
    return module


class Tooltip:
    """Create a tooltip for a given widget."""
    def __init__(self, widget, text, delay=1000):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.tooltip_window = None
        self.after_id = None
        self.widget.bind("<Enter>", self.schedule_tooltip)
        self.widget.bind("<Leave>", self.hide_tooltip)

    def schedule_tooltip(self, event=None):
        self.after_id = self.widget.after(self.delay, self.show_tooltip)

    def show_tooltip(self):
        x, y, _, _ = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 25

        self.tooltip_window = ctk.CTkToplevel(self.widget)
        self.tooltip_window.wm_overrideredirect(True)
        self.tooltip_window.wm_geometry(f"+{x}+{y}")

        label = ctk.CTkLabel(self.tooltip_window, text=self.text, corner_radius=5, fg_color="#333333", text_color="white", padx=10, pady=5)
        label.pack()

    def hide_tooltip(self, event=None):
        if self.after_id:
            self.widget.after_cancel(self.after_id)
            self.after_id = None
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None


class ThemeManager:
    """Discovers, loads, and applies themes from the 'themes' directory."""
    def __init__(self):
        self.themes_dir = os.path.join(SCRIPT_DIR, "themes")
        self.themes = {}
        self.current_theme_name = "Purple Dark"  # Fallback default
        self.current_colors = {}
        self.load_available_themes()

    def load_available_themes(self):
        """Scans the themes directory and loads all valid .json theme files."""
        if not os.path.exists(self.themes_dir):
            print(f"Warning: Themes directory not found at {self.themes_dir}. Creating it.")
            os.makedirs(self.themes_dir)
            return

        for filename in os.listdir(self.themes_dir):
            if filename.endswith(".json"):
                try:
                    with open(os.path.join(self.themes_dir, filename), 'r', encoding='utf-8') as f:
                        theme_data = json.load(f)
                        if "name" in theme_data and "appearance_mode" in theme_data and "colors" in theme_data:
                            self.themes[theme_data["name"]] = theme_data
                            print(f"Loaded theme: {theme_data['name']}")
                        else:
                            print(f"Warning: Invalid theme file format in {filename}")
                except Exception as e:
                    print(f"Error loading theme file {filename}: {e}")

        if not self.themes:
            print("Warning: No themes found. Using fallback default.")
            self.themes["Purple Dark"] = {
                "name": "Purple Dark",
                "appearance_mode": "dark",
                "colors": {
                    "primary": "#880ED4", "accent": "#A855F7", "success": "#10B981",
                    "warning": "#F59E0B", "error": "#EF4444", "info": "#3B82F6",
                    "frame_bg": "#000000", "textbox_bg": "#1A202C", "textbox_fg": "#E2E8F0",
                    "label_text": "#E2E8F0", "system_text": "#E5E7EB", "user_text": "#60A5FA",
                    "assistant_text": "#34D399", "thinking_text": "#F472B6",
                    "display_text_color": "#FFFFFF", "border_color": "#880ED4", "status_bg_color": "#3A475A"
                }
            }

    def get_theme_names(self) -> List[str]:
        return sorted(list(self.themes.keys()))

    def get_current_theme_name(self) -> str:
        return self.current_theme_name

    def get_color(self, color_name: str, fallback: str = "#FF00FF") -> str:
        return self.current_colors.get(color_name, fallback)

    def apply_theme(self, theme_name: str):
        if theme_name not in self.themes:
            print(f"Error: Theme '{theme_name}' not found.")
            return
        theme_data = self.themes[theme_name]
        self.current_theme_name = theme_name
        self.current_colors = theme_data.get("colors", {})
        appearance_mode = theme_data.get("appearance_mode", "dark")
        ctk.set_appearance_mode(appearance_mode)
        print(f"Theme '{theme_name}' applied with {appearance_mode} mode.")


class ThemeBuilderPopup(ctk.CTkToplevel):
    """A popup window for creating and editing themes."""
    def __init__(self, parent, theme_manager):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self.parent_app = parent

        self.title("Theme Builder")
        self.geometry("800x650")
        self.minsize(700, 500)

        self.transient(parent)
        self.grab_set()

        self.create_theme_builder_widgets()
        self.load_selected_theme(self.theme_manager.get_current_theme_name())
        self.preview_theme()

    def create_theme_builder_widgets(self):
        try:
            font = ctk.CTkFont(family="Consolas", size=12)
            title_font = ctk.CTkFont(family="Consolas", size=14, weight="bold")
        except:
            font = ("Consolas", 12)
            title_font = ("Consolas", 14, "bold")

        main_frame = ctk.CTkFrame(self)
        main_frame.pack(expand=True, fill="both", padx=20, pady=10)
        main_frame.grid_columnconfigure(0, weight=1)
        main_frame.grid_columnconfigure(1, weight=1)

        left_frame = ctk.CTkScrollableFrame(main_frame, label_text="Color Settings")
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        right_frame = ctk.CTkFrame(main_frame)
        right_frame.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        manage_frame = ctk.CTkFrame(left_frame)
        manage_frame.pack(fill="x", padx=10, pady=10)

        self.theme_selector_combo = ctk.CTkComboBox(manage_frame, values=self.theme_manager.get_theme_names(), command=self.load_selected_theme)
        self.theme_selector_combo.pack(side="left", expand=True, fill="x", padx=(0,5))

        delete_button = ctk.CTkButton(manage_frame, text="Delete", width=60, command=self.delete_selected_theme)
        delete_button.pack(side="left")

        ctk.CTkLabel(left_frame, text="Theme Name:", font=font).pack(anchor="w", padx=10, pady=(10, 0))
        self.theme_name_entry = ctk.CTkEntry(left_frame, font=font)
        self.theme_name_entry.pack(fill="x", padx=10, pady=(0, 10))

        self.color_widgets = {}
        color_labels = {
            "primary": "Primary", "accent": "Accent", "button_hover": "Button Hover",
            "success": "Success", "warning": "Warning", "error": "Error", "info": "Info",
            "frame_bg": "Frame BG", "textbox_bg": "Textbox BG", "textbox_fg": "Textbox FG",
            "label_text": "Label Text", "system_text": "System Text", "user_text": "User Text",
            "assistant_text": "Assistant Text", "thinking_text": "Thinking Text",
            "display_text_color": "Display Text", "border_color": "Border Color"
        }

        for key, label_text in color_labels.items():
            container = ctk.CTkFrame(left_frame)
            container.pack(fill="x", padx=10, pady=4)
            ctk.CTkLabel(container, text=label_text, font=font, width=120, anchor="w").pack(side="left", padx=5)
            hex_label = ctk.CTkLabel(container, text="#000000", font=font, width=70)
            hex_label.pack(side="left", padx=5)
            color_swatch = ctk.CTkFrame(container, fg_color="#000000", width=100, height=25, corner_radius=3, border_width=1)
            color_swatch.pack(side="left", padx=10, fill="x", expand=True)
            self.color_widgets[key] = {'label': hex_label, 'swatch': color_swatch}
            for widget in [color_swatch, hex_label]:
                widget.bind("<Button-1>", lambda e, k=key: self.choose_color(k))

        button_frame = ctk.CTkFrame(left_frame)
        button_frame.pack(fill="x", padx=10, pady=10)
        apply_theme_button = ctk.CTkButton(button_frame, text="Apply", font=font, command=self.apply_preview_theme)
        apply_theme_button.pack(side="left", padx=10)
        save_theme_button = ctk.CTkButton(button_frame, text="Save Theme", font=font, command=self.save_theme)
        save_theme_button.pack(side="right", padx=10)

        self.preview_frame = ctk.CTkFrame(right_frame, border_width=2)
        self.preview_frame.pack(expand=True, fill="both", padx=10, pady=10)
        ctk.CTkLabel(self.preview_frame, text="Theme Preview", font=title_font).pack(pady=5)
        self.preview_widgets = {}
        self.preview_widgets["label"] = ctk.CTkLabel(self.preview_frame, text="This is a label.")
        self.preview_widgets["label"].pack(pady=5, padx=10)
        self.preview_widgets["button"] = ctk.CTkButton(self.preview_frame, text="Click Me")
        self.preview_widgets["button"].pack(pady=5, padx=10)
        self.preview_widgets["textbox"] = ctk.CTkTextbox(self.preview_frame, height=50)
        self.preview_widgets["textbox"].insert("0.0", "This is a textbox.")
        self.preview_widgets["textbox"].pack(pady=5, padx=10, fill="x")

    def choose_color(self, key):
        initial_color = self.color_widgets[key]['label'].cget("text")
        picker = CustomColorPickerPopup(self, initial_color=initial_color)
        new_color = picker.get_color()
        if new_color:
            self.color_widgets[key]['label'].configure(text=new_color)
            self.color_widgets[key]['swatch'].configure(fg_color=new_color)
            self.preview_theme()

    def apply_preview_theme(self):
        theme_name = self.theme_name_entry.get()
        if not theme_name: return
        preview_colors = {key: widgets['label'].cget("text") for key, widgets in self.color_widgets.items()}
        self.theme_manager.current_theme_name = f"{theme_name} (Preview)"
        self.theme_manager.current_colors = preview_colors
        self.parent_app.apply_color_theme()

    def preview_theme(self):
        colors = {key: widgets['label'].cget("text") for key, widgets in self.color_widgets.items()}
        primary = colors.get("primary", "#007BFF")
        accent = colors.get("accent", "#28A745")
        frame_bg = colors.get("frame_bg", "#F8F9FA")
        textbox_bg = colors.get("textbox_bg", "#FFFFFF")
        textbox_fg = colors.get("textbox_fg", "#212529")
        label_text = colors.get("label_text", "#495057")
        border = colors.get("border_color", "#DEE2E6")
        button_text_color = colors.get("textbox_bg", "#FFFFFF")

        self.preview_frame.configure(fg_color=frame_bg, border_color=accent)
        self.preview_widgets["label"].configure(text_color=label_text)
        self.preview_widgets["button"].configure(fg_color=primary, text_color=button_text_color)
        self.preview_widgets["textbox"].configure(fg_color=textbox_bg, text_color=textbox_fg, border_color=border)

    def load_selected_theme(self, theme_name: str):
        if not theme_name or theme_name not in self.theme_manager.themes: return
        theme_data = self.theme_manager.themes[theme_name]
        self.theme_name_entry.delete(0, "end")
        self.theme_name_entry.insert(0, theme_data.get("name", ""))
        theme_colors = theme_data.get("colors", {})
        for key, widgets in self.color_widgets.items():
            color = theme_colors.get(key, "#ffffff")
            widgets['label'].configure(text=color)
            widgets['swatch'].configure(fg_color=color)
        self.preview_theme()

    def delete_selected_theme(self):
        theme_name = self.theme_selector_combo.get()
        if not theme_name or theme_name not in self.theme_manager.themes: return
        dialog = ctk.CTkInputDialog(text=f"Type DELETE to confirm deleting theme '{theme_name}':", title="Confirm Deletion")
        if dialog.get_input() != "DELETE": return

        filename = f"{theme_name.lower().replace(' ', '_')}.json"
        filepath = os.path.join(self.theme_manager.themes_dir, filename)
        if os.path.exists(filepath):
            os.remove(filepath)
            self.theme_manager.load_available_themes()
            new_theme_names = self.theme_manager.get_theme_names()
            self.theme_selector_combo.configure(values=new_theme_names)
            self.theme_selector_combo.set(new_theme_names[0] if new_theme_names else "")

    def save_theme(self):
        theme_name = self.theme_name_entry.get()
        if not theme_name: return
        theme_data = {"name": theme_name, "appearance_mode": "dark", "colors": {}}
        for key, widgets in self.color_widgets.items():
            theme_data["colors"][key] = widgets['label'].cget("text")

        themes_dir = os.path.join(SCRIPT_DIR, "themes")
        os.makedirs(themes_dir, exist_ok=True)
        filename = f"{theme_name.lower().replace(' ', '_')}.json"
        filepath = os.path.join(themes_dir, filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(theme_data, f, indent=4)

        self.theme_manager.load_available_themes()
        new_theme_names = self.theme_manager.get_theme_names()
        self.theme_selector_combo.configure(values=new_theme_names)
        self.theme_selector_combo.set(theme_name)


class GUIDesigner(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("LYRN-AI GUI Designer")
        self.geometry("1200x800")

        self.theme_manager = ThemeManager()
        self.theme_manager.apply_theme("LYRN Dark")

        self.loaded_widgets = {}
        self.selected_widget = None
        self.overlay = None
        self.app_instance = None

        # Configure the main grid layout
        self.grid_columnconfigure(0, weight=1)  # Left panel
        self.grid_columnconfigure(1, weight=3)  # Center panel (Design Surface)
        self.grid_columnconfigure(2, weight=1)  # Right panel
        self.grid_rowconfigure(0, weight=1)

        # Left Panel: Widget Toolbox and Component Hierarchy
        self.left_panel = ctk.CTkFrame(self, width=250, corner_radius=0)
        self.left_panel.grid(row=0, column=0, sticky="nsew")

        # Center Panel: Design Surface
        self.design_surface = ctk.CTkFrame(self)
        self.design_surface.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)

        # Right Panel: Property Inspector
        self.right_panel = ctk.CTkFrame(self, width=250, corner_radius=0)
        self.right_panel.grid(row=0, column=2, sticky="nsew")
        self.right_panel.grid_rowconfigure(1, weight=1)

        # Add placeholder labels
        ctk.CTkLabel(self.left_panel, text="Widget Toolbox").pack(pady=5)

        # Add Theme Builder button
        self.theme_builder_button = ctk.CTkButton(self.left_panel, text="Open Theme Builder", command=self.open_theme_builder)
        self.theme_builder_button.pack(pady=10, padx=10, fill="x")

        ctk.CTkLabel(self.left_panel, text="Component Hierarchy").pack(pady=5)
        self.hierarchy_tree = ctk.CTkTextbox(self.left_panel, width=280)
        self.hierarchy_tree.pack(pady=10, padx=10, fill="both", expand=True)
        self.hierarchy_tree.configure(state="disabled")

        ctk.CTkLabel(self.design_surface, text="Design Surface").pack(pady=10)

        ctk.CTkLabel(self.right_panel, text="Property Inspector").pack(pady=10)
        self.property_inspector = ctk.CTkScrollableFrame(self.right_panel)
        self.property_inspector.pack(pady=10, padx=10, fill="both", expand=True)

        self.apply_color_theme()

        self.load_gui_for_editing()
        self._create_overlay()
        self._bind_picker()

    def _create_overlay(self):
        """Create a translucent overlay used to highlight the selected widget."""
        self.overlay = ctk.CTkToplevel(self)
        self.overlay.overrideredirect(True)
        self.overlay.attributes("-alpha", 0.3)
        self.overlay.configure(fg_color="cyan")
        self.overlay.withdraw()

    def _bind_picker(self):
        """Bind a global click handler to allow widget selection."""
        self.bind_all("<Button-1>", self._on_global_click, add="+")

    def _on_global_click(self, event: tk.Event):
        """Handle clicks anywhere in the application, selecting widgets."""
        # Ignore clicks inside the designer window
        if str(event.widget).startswith(str(self)):
            return

        # Select the widget that was clicked
        self.select_widget(event.widget)

    def _highlight(self, widget: tk.Widget):
        """Show the overlay on top of the selected widget."""
        if not self.overlay:
            return
        try:
            x = widget.winfo_rootx()
            y = widget.winfo_rooty()
            w = widget.winfo_width()
            h = widget.winfo_height()
            if w < 2 or h < 2:
                widget.update_idletasks()
                w = widget.winfo_width()
                h = widget.winfo_height()
            self.overlay.geometry(f"{w}x{h}+{x}+{y}")
            self.overlay.deiconify()
            self.overlay.lift()
        except Exception:
            self.overlay.withdraw()

    def load_gui_for_editing(self):
        """Loads the target GUI, walks its widget tree, and populates the hierarchy view."""
        try:
            gui_path = os.path.join(SCRIPT_DIR, "lyrn_sad_v4.0.3.pyw")
            gui_module = load_gui_module(gui_path)

            log_queue = queue.Queue()
            self.app_instance = gui_module.LyrnAIInterface(master=self, log_queue=log_queue)

            self.app_instance.geometry(f"800x600+{(self.design_surface.winfo_rootx())}+{(self.design_surface.winfo_rooty())}")

            self.update()
            all_widgets = _walk(self.app_instance)

            self.hierarchy_tree.configure(state="normal")
            self.hierarchy_tree.delete("1.0", "end")

            for widget in all_widgets:
                try:
                    widget_id = _widget_id(widget)
                    self.loaded_widgets[widget_id] = widget

                    parent_path = widget.winfo_parent()
                    depth = parent_path.count('.')
                    indent = "  " * depth

                    tag_name = f"widget_tag_{widget_id.replace('.', '_').replace(':', '_')}"

                    self.hierarchy_tree.insert("end", f"{indent}{widget_id}\n", (tag_name,))
                    self.hierarchy_tree.tag_bind(tag_name, "<Button-1>", lambda e, w=widget: self.select_widget(w))

                except Exception:
                    pass

            self.hierarchy_tree.configure(state="disabled")

        except Exception as e:
            print(f"Error loading GUI for editing: {e}")
            self.hierarchy_tree.configure(state="normal")
            self.hierarchy_tree.insert("end", f"Error loading GUI:\n{e}")
            self.hierarchy_tree.configure(state="disabled")

    def select_widget(self, widget: tk.Widget):
        self.selected_widget = widget
        if self.selected_widget:
            widget_id = _widget_id(self.selected_widget)
            print(f"Selected widget: {widget_id}")
            self._highlight(self.selected_widget)
            self.update_property_inspector()

    def update_property_inspector(self):
        # Clear previous properties
        for widget in self.property_inspector.winfo_children():
            widget.destroy()

        if not self.selected_widget:
            return

        try:
            config = self.selected_widget.configure()
        except tk.TclError:
            return # Widget might be destroyed

        row = 0
        for prop_name, prop_details in sorted(config.items()):
            ctk.CTkLabel(self.property_inspector, text=prop_name, anchor="w").grid(row=row, column=0, sticky="ew", padx=5, pady=2)

            value = prop_details[-1] # The last item in the tuple is the current value
            value_str = str(value)
            if len(value_str) > 50:
                value_str = value_str[:50] + "..."

            ctk.CTkLabel(self.property_inspector, text=value_str, anchor="w").grid(row=row, column=1, sticky="ew", padx=5, pady=2)
            row += 1

        self.property_inspector.grid_columnconfigure(1, weight=1)

    def open_theme_builder(self):
        if not hasattr(self, 'theme_builder_popup') or not self.theme_builder_popup.winfo_exists():
            self.theme_builder_popup = ThemeBuilderPopup(self, self.theme_manager)
            self.theme_builder_popup.focus()
        else:
            self.theme_builder_popup.lift()
            self.theme_builder_popup.focus()

    def apply_color_theme(self):
        """Apply colors from the current theme to all relevant widgets."""
        try:
            tm = self.theme_manager
            primary_color = tm.get_color("primary")
            accent_color = tm.get_color("accent")
            frame_bg = tm.get_color("frame_bg")

            self.configure(fg_color=frame_bg)

            for child in self.winfo_children():
                if isinstance(child, ctk.CTkFrame):
                    child.configure(fg_color=frame_bg)

            self.theme_builder_button.configure(fg_color=primary_color, hover_color=accent_color)

            print("Color theme re-applied to designer.")

        except Exception as e:
            print(f"Error applying color theme: {e}")


if __name__ == "__main__":
    app = GUIDesigner()
    app.mainloop()
