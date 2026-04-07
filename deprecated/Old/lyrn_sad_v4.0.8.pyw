"""
LYRN-AI Interface

"""

import os
import sys
import json
import subprocess
import re
import time
import queue
import threading
import io
import contextlib
import gc
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from pathlib import Path
import shutil
from tkinter import colorchooser, filedialog
import tkinter as tk
from delta_manager import DeltaManager
from automation_controller import AutomationController, Job
from color_picker import CustomColorPickerPopup
from heartbeat import get_heartbeat_string
from file_lock import SimpleFileLock
from affordance_manager import AffordanceManager, Affordance
from themed_popup import ThemedPopup, ThemeManager
from automation.scheduler_manager import SchedulerManager
import calendar
from cycle_manager import CycleManager
from episodic_memory_manager import EpisodicMemoryManager
from topic_index_popup import TopicIndexPopup
from system_checker import SystemChecker

# CustomTkinter imports
import customtkinter as ctk
from llama_cpp import Llama
try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None
    ImageTk = None
    print("Warning: Pillow library not found. Image features will be disabled.")


# System monitoring imports
import psutil
try:
    import pynvml
except ImportError:
    pynvml = None

# Set initial appearance
ctk.set_appearance_mode("dark")

# Script directory and settings path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(SCRIPT_DIR, "settings.json")
THEME_PATH = os.path.join(SCRIPT_DIR, "lyrn-theme.json")

# LYRN-AI Brand Colors
LYRN_PURPLE = "#7552bf"
LYRN_ACCENT = "#A855F7"
LYRN_SUCCESS = "#10B981"
LYRN_WARNING = "#F59E0B"
LYRN_ERROR = "#EF4444"
LYRN_INFO = "#3B82F6"

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



class DraggableListbox(ctk.CTkScrollableFrame):
    """A scrollable frame that supports drag-and-drop reordering and pinning of items."""
    def __init__(self, master, command=None, **kwargs):
        super().__init__(master, **kwargs)
        self.command = command
        self.items = []
        self.item_map = {}
        self.dragged_item = None
        self.selected_item = None
        self.drop_indicator = ctk.CTkFrame(self, height=2, fg_color=LYRN_ACCENT, corner_radius=0)
        self.drop_indicator_index = -1
        self.drag_offset_y = 0

    def get_selected_item(self):
        """Returns the currently selected item's frame."""
        return self.selected_item

    def add_item(self, item_data: dict, **kwargs):
        """Adds a new draggable item to the list."""
        text = item_data["path"]
        is_pinned = item_data.get("pinned", False)

        item_frame = ctk.CTkFrame(self, corner_radius=3)
        if is_pinned:
            # A light purple to indicate pinned status, works in light/dark themes
            item_frame.configure(fg_color=("#E8D5F9", "#402354"))
        item_frame.pack(fill="x", padx=5, pady=3)

        # Pin button
        pin_char = "📌" if is_pinned else "📍"
        pin_button = ctk.CTkButton(item_frame, text=pin_char, width=30,
                                   command=lambda frame=item_frame: self.toggle_pin(frame))
        pin_button.pack(side="left", padx=5, pady=5)

        label = ctk.CTkLabel(item_frame, text=text, **kwargs)
        label.pack(side="left", padx=10, pady=5)

        for widget in [item_frame, label]:
            widget.bind("<ButtonPress-1>", lambda e, frame=item_frame: self._on_press(e, frame))
            widget.bind("<B1-Motion>", self._on_drag)
            widget.bind("<ButtonRelease-1>", self._on_release)

        self.items.append(item_frame)
        self.item_map[item_frame] = item_data

    def toggle_pin(self, item_frame):
        """Toggles the pinned state of an item and re-sorts the list."""
        item_data = self.item_map[item_frame]
        item_data["pinned"] = not item_data.get("pinned", False)

        # Re-sort all items based on pinned status, then by their original order (for stability)
        self.items.sort(key=lambda frame: not self.item_map[frame].get("pinned", False))

        # Repack all items in the new order
        for item in self.items:
            item.pack_forget()
        for item in self.items:
            item.pack(fill="x", padx=5, pady=3)
            # Update visual state
            is_pinned = self.item_map[item].get("pinned", False)
            pin_char = "📌" if is_pinned else "📍"
            item.winfo_children()[0].configure(text=pin_char) # Assumes pin button is the first child
            if is_pinned:
                item.configure(fg_color=("#E8D5F9", "#402354"))
            else:
                item.configure(fg_color="transparent")


        # Trigger the command to save the new state
        if self.command:
            self.command(self.get_item_objects())

    def clear(self):
        """Removes all items from the list."""
        for item in self.items:
            item.destroy()
        self.items.clear()
        self.item_map.clear()

    def get_item_objects(self) -> List[dict]:
        """Returns the list of item data objects in their current order."""
        return [self.item_map[item] for item in self.items]

    def _on_press(self, event, widget):
        """Callback for when a mouse button is pressed on an item."""
        # Find the actual frame to drag from the widget that was clicked
        if isinstance(widget, (ctk.CTkLabel, ctk.CTkButton)):
            frame_to_select = widget.master
        else:
            frame_to_select = widget

        # Update selection
        self.selected_item = frame_to_select
        self.dragged_item = frame_to_select

        # Visual feedback for selection and drag
        for item in self.items:
            is_pinned = self.item_map[item].get("pinned", False)
            if item == self.selected_item:
                item.configure(fg_color=LYRN_PURPLE) # Drag color
            elif is_pinned:
                item.configure(fg_color=("#E8D5F9", "#402354")) # Pinned color
            else:
                item.configure(fg_color="transparent") # Default color

        self.dragged_item.lift()
        self.drag_offset_y = event.y_root - self.dragged_item.winfo_rooty()

    def _on_drag(self, event):
        """Callback for when an item is being dragged."""
        if not self.dragged_item:
            return

        # Move the item using root coordinates for smoothness
        new_y_root = event.y_root - self.drag_offset_y
        new_y_parent = new_y_root - self.winfo_rooty()
        self.dragged_item.place(y=new_y_parent)

        # Update the drop indicator's position
        self._update_drop_indicator()

    def _update_drop_indicator(self):
        """Calculates and places the drop indicator line."""
        if not self.dragged_item:
            return

        # Use the center of the dragged item to determine its logical position
        drag_center_y = self.dragged_item.winfo_y() + (self.dragged_item.winfo_height() / 2)

        # Find the index where the dragged item should be inserted
        target_index = 0
        for item in self.items:
            if item == self.dragged_item:
                continue
            if drag_center_y > item.winfo_y() + (item.winfo_height() / 2):
                target_index += 1

        self.drop_indicator_index = target_index

        # Determine the visual y-position for the indicator line
        # Place it at the top of the item that will be pushed down
        if target_index < len(self.items):
            # If the target is the dragged item itself, find the next one
            if self.items[target_index] == self.dragged_item:
                if target_index + 1 < len(self.items):
                    indicator_y = self.items[target_index + 1].winfo_y()
                else: # Dragged to the very end
                    last_item = self.items[target_index - 1]
                    indicator_y = last_item.winfo_y() + last_item.winfo_height()
            else:
                 indicator_y = self.items[target_index].winfo_y()
        else: # Dragged past the last item
            last_item = self.items[-1] if self.items[-1] != self.dragged_item else self.items[-2]
            indicator_y = last_item.winfo_y() + last_item.winfo_height()

        self.drop_indicator.place(x=0, y=indicator_y - 1, relwidth=1)
        self.drop_indicator.lift()


    def _on_release(self, event):
        """Callback for when the mouse button is released."""
        if not self.dragged_item:
            return

        # Hide indicator
        self.drop_indicator.place_forget()

        # The visual state of the selected item is now managed in _on_press to make it persistent.
        # We only handle the reordering logic here.

        # Use the calculated target_index from the indicator
        target_index = self.drop_indicator_index

        # Constrain the drop to respect pinning boundaries
        is_pinned = self.item_map[self.dragged_item].get("pinned", False)
        num_pinned = sum(1 for item in self.items if self.item_map[item].get("pinned", False) and item != self.dragged_item)
        if is_pinned:
            target_index = min(target_index, num_pinned)
        else:
            target_index = max(target_index, num_pinned)

        # Move the item in the list and repack everything
        original_item = self.dragged_item
        self.items.remove(original_item)
        self.items.insert(target_index, original_item)

        original_item.place_forget()
        for item in self.items:
            item.pack_forget()
        for item in self.items:
            item.pack(fill="x", padx=5, pady=3)

        self.dragged_item = None
        self.drop_indicator_index = -1

        # Execute the callback command if provided
        if self.command:
            self.command(self.get_item_objects())


class LanguageManager:
    """Manages loading and retrieving translated UI strings."""
    def __init__(self, language="en"):
        self.language_dir = os.path.join(SCRIPT_DIR, "languages")
        self.language = language
        self.strings = {}
        self.load_language()

    def load_language(self, language: str = None):
        """Loads a language file from the 'languages' directory."""
        if language:
            self.language = language

        lang_file_path = os.path.join(self.language_dir, f"{self.language}.json")

        if not os.path.exists(lang_file_path):
            print(f"Warning: Language file not found for '{self.language}'. Falling back to returning keys.")
            self.strings = {}
            return

        try:
            with open(lang_file_path, 'r', encoding='utf-8') as f:
                self.strings = json.load(f)
            print(f"Loaded language: {self.language}")
        except Exception as e:
            print(f"Error loading language file {lang_file_path}: {e}")
            self.strings = {}

    def get_available_languages(self) -> List[str]:
        """Scans the languages directory for available language files."""
        if not os.path.exists(self.language_dir):
            return ["en"]  # Fallback

        try:
            languages = [f.split('.')[0] for f in os.listdir(self.language_dir) if f.endswith(".json")]
            return sorted(languages) if languages else ["en"]
        except Exception as e:
            print(f"Error scanning for languages: {e}")
            return ["en"]

    def get(self, key: str, **kwargs) -> str:
        """Gets a translated string by key, with optional formatting."""
        string = self.strings.get(key, key) # Return key if not found for easy debugging
        if kwargs:
            try:
                string = string.format(**kwargs)
            except KeyError as e:
                print(f"Warning: Missing format key {e} in language string for key '{key}'")
        return string

class SettingsManager:
    """Enhanced settings manager with UI preferences"""

    def __init__(self):
        self.settings = None
        self.first_boot = False
        self.ui_settings = {
            "font_size": 12,
            "window_size": "1400x900",
            "confirmation_preferences": {}
        }
        self.load_or_detect_first_boot()

    def get_setting(self, key: str, default: any = None) -> any:
        """Gets a setting from the UI settings."""
        return self.ui_settings.get(key, default)

    def set_setting(self, key: str, value: any):
        """Sets a setting in the UI settings and saves it."""
        self.ui_settings[key] = value
        self.save_settings()

    def load_or_detect_first_boot(self):
        """Load settings or create a default one on first boot."""
        if os.path.exists(SETTINGS_PATH):
            try:
                with open(SETTINGS_PATH, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.settings = data.get('settings', {})
                    self.ui_settings.update(data.get('ui_settings', {}))

                # Resolve relative paths for the current session
                if "paths" in self.settings:
                    for key, path in self.settings["paths"].items():
                        if path and not os.path.isabs(path):
                            self.settings["paths"][key] = os.path.join(SCRIPT_DIR, path)

                print("Settings loaded successfully")
                self.ensure_automation_flag()
                self.ensure_next_job_flag()
                self.ensure_llm_status_flag()
            except Exception as e:
                print(f"Error loading settings: {e}. Assuming first boot.")
                self.first_boot = True
        else:
            print("No settings.json found - First boot detected. Creating default settings.")
            self.first_boot = True

        if self.first_boot:
            # Create and save a default settings file
            self.settings = self.create_empty_settings_structure()
            default_paths = {
                "static_snapshots": "build_prompt/static_snapshots",
                "dynamic_snapshots": "build_prompt/dynamic_snapshots",
                "active_jobs": "build_prompt/active_jobs",
                "deltas": "deltas",
                "chat": "chat",
                "output": "output",
                "keywords": "active_keywords",
                "topics": "active_topics",
                "active_chunk": "active_chunk",
                "chunk_queue": "automation/chunk_queue.json",
                "job_list": "automation/job_list.txt",
                "job_log": "automation/job_log.json",
                "automation_flag_path": "global_flags/automation.txt",
                "chunk_queue_path": "automation/chunk_queue.json",
                "chat_dir": "chat",
                "chat_parsed_dir": "chat_parsed",
                "audit_dir": "automation/job_audit",
                "metrics_logs": "metrics_logs"
            }
            self.settings["paths"] = default_paths
            self.save_settings() # This saves the file with relative paths

            # Now resolve paths for the current session
            for key, path in self.settings["paths"].items():
                if path and not os.path.isabs(path):
                    self.settings["paths"][key] = os.path.join(SCRIPT_DIR, path)

            self.ensure_automation_flag()
            self.ensure_next_job_flag()
            self.ensure_llm_status_flag()

    def create_empty_settings_structure(self) -> dict:
        """Create empty settings structure for first boot"""
        return {
            "active": {
                "model_path": "",
                "n_ctx": 8192,
                "n_threads": 8,
                "n_gpu_layers": 0,
                "max_tokens": 2048,
                "temperature": 0.7,
                "top_p": 0.95,
                "top_k": 40,
                "stream": True
            },
            "paths": {
                "static_snapshots": "",
                "dynamic_snapshots": "",
                "active_jobs": "",
                "deltas": "",
                "chat": "",
                "output": "",
                "keywords": "",
                "topics": "",
                "active_chunk": "",
                "chunk_queue": "",
                "job_list": "",
                "job_log": "",
                "automation_flag_path": "",
                "chunk_queue_path": "",
                "chat_dir": "",
                "chat_parsed_dir": "",
                "audit_dir": "",
                "metrics_logs": ""
            }
        }

    def save_settings(self, settings: dict = None):
        """Save settings and UI preferences to JSON file"""
        try:
            if os.path.exists(SETTINGS_PATH):
                backup_path = SETTINGS_PATH + '.bk'
                shutil.copy2(SETTINGS_PATH, backup_path)

            data = {
                "settings": settings or self.settings,
                "ui_settings": self.ui_settings
            }

            with open(SETTINGS_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            if settings:
                self.settings = settings
            self.first_boot = False
            print("Settings saved successfully")

        except Exception as e:
            print(f"Error saving settings: {e}")

    def ensure_automation_flag(self):
        """Ensure automation flag is set to 'off' on startup"""
        if not self.settings or "paths" not in self.settings:
            return

        flag_path = self.settings["paths"].get("automation_flag_path", "")
        if not flag_path:
            return

        os.makedirs(os.path.dirname(flag_path), exist_ok=True)
        try:
            with open(flag_path, 'w', encoding='utf-8') as f:
                f.write("off")
        except Exception as e:
            print(f"Warning: Could not set automation flag: {e}")

    def ensure_next_job_flag(self):
        """Ensure next job flag is initialized to 'false' on startup"""
        next_job_path = os.path.join(SCRIPT_DIR, "global_flags", "next_job.txt")
        os.makedirs(os.path.dirname(next_job_path), exist_ok=True)

        try:
            with open(next_job_path, 'w', encoding='utf-8') as f:
                f.write("false")
            print("Next job flag initialized to 'false'")
        except Exception as e:
            print(f"Warning: Could not initialize next job flag: {e}")

    def ensure_llm_status_flag(self):
        """Ensure LLM status flag is initialized to 'idle' on startup."""
        llm_status_path = os.path.join(SCRIPT_DIR, "global_flags", "llm_status.txt")
        os.makedirs(os.path.dirname(llm_status_path), exist_ok=True)
        try:
            with open(llm_status_path, 'w', encoding='utf-8') as f:
                f.write("idle")
            print("LLM status flag initialized to 'idle'")
        except Exception as e:
            print(f"Warning: Could not initialize LLM status flag: {e}")

    def set_automation_flag(self, state: str):
        """Set automation flag to 'on' or 'off'"""
        if not self.settings or "paths" not in self.settings:
            return

        flag_path = self.settings["paths"].get("automation_flag_path", "")
        if not flag_path:
            return

        try:
            with open(flag_path, 'w', encoding='utf-8') as f:
                f.write(state)
        except Exception as e:
            print(f"Error setting automation flag: {e}")

class SnapshotLoader:
    """Loads the static base prompt from the 'build_prompt' directory."""

    def __init__(self, settings_manager: SettingsManager):
        self.settings_manager = settings_manager
        self.build_prompt_dir = os.path.join(SCRIPT_DIR, "build_prompt")
        self.master_prompt_path = os.path.join(self.build_prompt_dir, "master_prompt.txt")
        self.config_path = os.path.join(self.build_prompt_dir, "builder_config.json")
        self.prompt_order_path = os.path.join(self.build_prompt_dir, "prompt_order.json")

    def _load_json_file(self, path: str) -> Optional[list or dict]:
        """Safely loads a JSON file and returns its content."""
        if not os.path.exists(path):
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error reading JSON file {path}: {e}")
            return None

    def _load_text_file(self, path: str) -> str:
        """Safely loads a text file and returns its content."""
        if not os.path.exists(path):
            print(f"Warning: Text file not found at {path}")
            return ""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read().strip()
        except IOError as e:
            print(f"Error reading text file {path}: {e}")
            return ""

    def build_master_prompt_from_components(self) -> str:
        """Builds the master prompt by concatenating enabled components based on their new config files."""
        print("Building master prompt from components...")
        order = self._load_json_file(self.prompt_order_path) or []

        prompt_parts = []
        for component_name in order:
            component_dir = os.path.join(self.build_prompt_dir, component_name)
            config_path = os.path.join(component_dir, "config.json")

            # Special handling for heartbeat as it has a different config structure
            if component_name == 'heartbeat':
                # We only add heartbeat if its own internal config says it's enabled
                heartbeat_config_path = os.path.join(self.build_prompt_dir, "heartbeat", "heartbeat_config.json")
                heartbeat_config = self._load_json_file(heartbeat_config_path)
                if heartbeat_config and heartbeat_config.get("enabled", False):
                    heartbeat_content = get_heartbeat_string()
                    if heartbeat_content:
                        prompt_parts.append(heartbeat_content)
                continue

            config = self._load_json_file(config_path)
            if not config:
                print(f"Warning: Could not load config for component: {component_name}")
                continue

            begin_bracket = config.get("begin_bracket", "")
            end_bracket = config.get("end_bracket", "")
            content_file = config.get("content_file") or config.get("output_file")

            if not content_file:
                print(f"Warning: No content file specified for component: {component_name}")
                continue

            content_path = os.path.join(component_dir, content_file)
            content = self._load_text_file(content_path)

            if content:
                # Assemble the block using the specified brackets and content
                formatted_block = f"{begin_bracket}\n{content}\n{end_bracket}"
                prompt_parts.append(formatted_block)

        full_prompt_text = "\n\n".join(prompt_parts)
        try:
            with open(self.master_prompt_path, 'w', encoding='utf-8') as f:
                f.write(full_prompt_text)
            print("Master prompt file built successfully from components.")
        except IOError as e:
            print(f"Error writing master prompt file: {e}")

        return full_prompt_text

    def load_base_prompt(self) -> str:
        """
        Builds and loads the master prompt file from components.
        """
        print("Loading base prompt...")
        return self.build_master_prompt_from_components()

# JobProcessor class removed, its functionality is being replaced by AutomationController.

class EnhancedPerformanceMetrics:
    """Enhanced performance metrics with better parsing and display"""

    def __init__(self):
        self.reset_metrics()

    def reset_metrics(self):
        """Reset all metrics to zero"""
        self.kv_cache_reused = 0
        self.prompt_tokens = 0
        self.prompt_speed = 0.0
        self.eval_tokens = 0
        self.eval_speed = 0.0
        self.total_tokens = 0
        self.total_time = 0.0
        self.load_time = 0.0

    def parse_llama_logs(self, log_output: str):
        """Enhanced parsing with better error handling"""
        try:
            # Parse KV cache
            kv_match = re.search(r'(\d+)\s+prefix-match hit', log_output)
            if kv_match:
                self.kv_cache_reused = int(kv_match.group(1))

            # Parse prompt evaluation
            prompt_match = re.search(
                r'prompt eval time\s*=\s*([\d.]+)\s*ms\s*/\s*(\d+)\s*tokens.*?([\d.]+)\s*ms per token',
                log_output
            )
            if prompt_match:
                self.prompt_tokens = int(prompt_match.group(2))
                ms_per_token = float(prompt_match.group(3))
                self.prompt_speed = 1000.0 / ms_per_token if ms_per_token > 0 else 0.0

            # Parse generation
            eval_match = re.search(
                r'eval time\s*=\s*([\d.]+)\s*ms\s*/\s*(\d+)\s*runs.*?([\d.]+)\s*ms per token',
                log_output
            )
            if eval_match:
                self.eval_tokens = int(eval_match.group(2))
                ms_per_token = float(eval_match.group(3))
                self.eval_speed = 1000.0 / ms_per_token if ms_per_token > 0 else 0.0

            self.total_tokens = self.prompt_tokens + self.eval_tokens

        except Exception as e:
            print(f"Metrics parsing error: {e}")

    def save_metrics_log(self, settings_manager: SettingsManager):
        """Save formatted metrics to log file"""
        if not settings_manager.settings:
            return

        metrics_dir = settings_manager.settings["paths"].get("metrics_logs", "")
        if not metrics_dir:
            metrics_dir = os.path.join(SCRIPT_DIR, "metrics_logs")

        os.makedirs(metrics_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = os.path.join(metrics_dir, f"log_{timestamp}.txt")

        try:
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write(f"LYRN-AI Performance Metrics Report\n")
                f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"{'='*50}\n\n")
                f.write(f"KV Cache Reused: {self.kv_cache_reused:,} tokens\n")
                f.write(f"Prompt Tokens: {self.prompt_tokens:,}\n")
                f.write(f"Prompt Speed: {self.prompt_speed:.2f} tok/s\n")
                f.write(f"Generation Tokens: {self.eval_tokens:,}\n")
                f.write(f"Generation Speed: {self.eval_speed:.2f} tok/s\n")
                f.write(f"Total Tokens: {self.total_tokens:,}\n")
                f.write(f"Load Time: {self.load_time:.2f} ms\n")
                f.write(f"Total Time: {self.total_time:.2f} s\n")

            print(f"Metrics saved to: {log_file}")
            return log_file

        except Exception as e:
            print(f"Error saving metrics log: {e}")
            return None

class SystemResourceMonitor:
    """Monitors system resources like CPU, RAM, and VRAM in a background thread."""
    def __init__(self, update_queue):
        self.update_queue = update_queue
        self.running = False
        self.thread = None
        self.nvml_initialized = False

        if pynvml:
            try:
                pynvml.nvmlInit()
                self.nvml_initialized = True
                print("NVML initialized for GPU monitoring.")
            except Exception as e:
                print(f"Warning: Could not initialize NVML for GPU monitoring: {e}")

    def get_stats(self) -> Dict[str, any]:
        """Fetches current system stats."""
        stats = {
            "ram_percent": 0, "ram_used_gb": 0, "ram_total_gb": 0,
            "cpu": 0, "cpu_temp": "N/A",
            "vram_percent": 0, "vram_used_gb": 0, "vram_total_gb": 0,
            "disk_percent": 0, "disk_used_gb": 0, "disk_total_gb": 0
        }

        try:
            ram_info = psutil.virtual_memory()
            stats["ram_percent"] = ram_info.percent
            stats["ram_used_gb"] = ram_info.used / (1024**3)
            stats["ram_total_gb"] = ram_info.total / (1024**3)
        except Exception as e:
            print(f"Could not get RAM info: {e}")

        try:
            # Get disk usage for the drive where the script is located
            disk_info = psutil.disk_usage(os.path.abspath(SCRIPT_DIR))
            stats["disk_percent"] = disk_info.percent
            stats["disk_used_gb"] = disk_info.used / (1024**3)
            stats["disk_total_gb"] = disk_info.total / (1024**3)
        except Exception as e:
            print(f"Could not get Disk info: {e}")

        try:
            stats["cpu"] = psutil.cpu_percent()
        except Exception as e:
            print(f"Could not get CPU percent: {e}")

        # Get CPU temperature
        try:
            temps = psutil.sensors_temperatures()
            if 'coretemp' in temps:
                stats["cpu_temp"] = f"{temps['coretemp'][0].current:.1f}°C"
            elif 'k10temp' in temps: # for AMD CPUs
                stats["cpu_temp"] = f"{temps['k10temp'][0].current:.1f}°C"
            elif temps:
                key = list(temps.keys())[0]
                stats["cpu_temp"] = f"{temps[key][0].current:.1f}°C"
        except (AttributeError, KeyError, IndexError, PermissionError) as e:
             # print(f"Could not get CPU temp: {e}")
            pass  # Silently ignore if temp sensors are not available/readable

        # Get VRAM usage if NVML is available
        if self.nvml_initialized:
            try:
                handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                stats["vram_percent"] = (info.used / info.total) * 100
                stats["vram_used_gb"] = info.used / (1024**3)
                stats["vram_total_gb"] = info.total / (1024**3)
            except Exception as e:
                # This can happen if the driver is not running, etc.
                pass

        return stats

    def _monitor_loop(self):
        """The main loop that runs in a thread."""
        while self.running:
            try:
                stats = self.get_stats()
                self.update_queue.put(('system_stats', stats))
                time.sleep(2)  # Update every 2 seconds
            except Exception as e:
                print(f"Error in monitor loop: {e}")
                time.sleep(5) # Wait longer on error

    def start(self):
        """Starts the monitoring thread."""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.thread.start()
            print("System resource monitor started.")

    def stop(self):
        """Stops the monitoring thread and cleans up."""
        self.running = False
        if self.nvml_initialized:
            try:
                pynvml.nvmlShutdown()
                print("NVML shut down.")
            except Exception as e:
                print(f"Warning: NVML shutdown failed: {e}")

class StreamHandler:
    """Enhanced stream handler with better metrics capture"""

    def __init__(self, gui_queue, metrics: EnhancedPerformanceMetrics):
        self.gui_queue = gui_queue
        self.metrics = metrics
        self.current_response = ""
        self.thinking_content = ""
        self.is_finished = False
        self.log_buffer = ""

    def handle_token(self, token_data):
        """Handle streaming tokens with thinking detection"""
        if 'choices' in token_data and len(token_data['choices']) > 0:
            delta = token_data['choices'][0].get('delta', {})
            content = delta.get('content', '')

            if content:
                self.current_response += content

                # Detect thinking tags
                if '<thinking>' in content or self.thinking_content:
                    if '<thinking>' in content:
                        self.thinking_content = content.split('<thinking>')[-1]
                        content = content.split('<thinking>')[0]
                    elif '</thinking>' in content:
                        thinking_end = content.split('</thinking>')[0]
                        self.thinking_content += thinking_end
                        content = content.split('</thinking>', 1)[-1]
                        # Send thinking content separately
                        self.gui_queue.put(('thinking', self.thinking_content))
                        self.thinking_content = ""
                    else:
                        self.thinking_content += content
                        content = ""

                if content:
                    self.gui_queue.put(('token', content, 'assistant'))

            finish_reason = token_data['choices'][0].get('finish_reason')
            if finish_reason is not None:
                self.is_finished = True
                self.gui_queue.put(('finished', self.current_response))

    def capture_logs(self, log_content: str):
        """Enhanced log capture"""
        self.log_buffer += log_content
        if any(marker in self.log_buffer for marker in ["llama_perf_context_print", "eval time", "prompt eval time"]):
            self.metrics.parse_llama_logs(self.log_buffer)
            self.gui_queue.put(('metrics_update', ''))

    def get_response(self) -> str:
        return self.current_response

class QueueIO(io.TextIOBase):
    """A file-like object that writes to a queue."""
    def __init__(self, q):
        self.queue = q

    def write(self, s):
        self.queue.put(s)
        return len(s)

    def flush(self):
        pass

class ConsoleRedirector:
    """Manages the redirection of stdout and stderr to a queue."""
    def __init__(self, queue):
        self.queue = queue
        self.stream = QueueIO(self.queue)
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr

    def start(self):
        """Redirect stdout and stderr."""
        sys.stdout = self.stream
        sys.stderr = self.stream
        print("Console output redirected to GUI.")

    def stop(self):
        """Restore original stdout and stderr."""
        sys.stdout = self.original_stdout
        sys.stderr = self.original_stderr


class LogViewerPopup(ThemedPopup):
    """A popup window that displays redirected console output."""
    def __init__(self, parent, log_queue: queue.Queue, settings_manager: SettingsManager, theme_manager: ThemeManager):
        super().__init__(parent=parent, theme_manager=theme_manager)
        self.log_queue = log_queue
        self.settings_manager = settings_manager

        self.title("LLM & System Log")
        self.geometry("800x600")
        self.minsize(400, 300)

        self.protocol("WM_DELETE_WINDOW", self.withdraw)

        # --- Top bar for controls ---
        top_frame = ctk.CTkFrame(self)
        top_frame.pack(fill="x", padx=10, pady=(10,0))

        self.on_top_var = ctk.BooleanVar(value=True)
        self.on_top_checkbox = ctk.CTkCheckBox(top_frame, text="Keep on Top", variable=self.on_top_var, command=self.toggle_on_top)
        self.on_top_checkbox.pack(side="left", padx=10)
        self.toggle_on_top() # Apply the default state on launch

        # --- Main textbox ---
        self.textbox = ctk.CTkTextbox(self, wrap="word", font=("Consolas", 11))
        self.textbox.pack(expand=True, fill="both", padx=10, pady=10)
        self.textbox.configure(state="disabled")

        self.after(100, self.process_log_queue)
        self.apply_theme()

    def toggle_on_top(self):
        """Toggles the always-on-top status of the log viewer."""
        is_on_top = self.on_top_var.get()
        self.attributes("-topmost", is_on_top)

    def process_log_queue(self):
        """Checks the queue for new output and displays it."""
        try:
            while True:
                line = self.log_queue.get_nowait()
                self.textbox.configure(state="normal")
                self.textbox.insert("end", line)
                self.textbox.see("end")
                self.textbox.configure(state="disabled")
        except queue.Empty:
            pass
        finally:
            self.after(100, self.process_log_queue)


class StructuredChatLogger:
    """Handles the creation and appending of structured chat logs for automation."""
    def __init__(self, chat_dir: str):
        self.chat_dir = Path(chat_dir)
        self.chat_dir.mkdir(parents=True, exist_ok=True)
        self.current_log_path = None

    def start_log(self) -> str:
        """
        Starts a new log file with a timestamp and returns the path.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"chat_{timestamp}.txt"
        self.current_log_path = self.chat_dir / filename
        # Create the file immediately to establish its existence
        with open(self.current_log_path, 'w', encoding='utf-8') as f:
            f.write("") # Write an empty string to create the file
        return str(self.current_log_path)

    def append_log(self, role: str, content: str):
        """
        Appends a new section to the current log file.
        Role can be 'USER', 'THINKING', or 'RESPONSE'.
        """
        if not self.current_log_path:
            print("Error: start_log() must be called before appending.")
            return

        role_upper = role.upper()
        start_tag = f"#{role_upper}_START#"
        end_tag = f"#{role_upper}_END#"

        formatted_content = f"{start_tag}\n{content}\n{end_tag}\n\n"

        try:
            with open(self.current_log_path, 'a', encoding='utf-8') as f:
                f.write(formatted_content)
        except Exception as e:
            print(f"Error appending to log file {self.current_log_path}: {e}")

    def new_log_session(self):
        """Resets the current_log_path to ensure the next write starts a new file."""
        self.current_log_path = None

class ModelSelectorPopup(ThemedPopup):
    """A popup window to select a model and configure settings on startup."""
    def __init__(self, parent, settings_manager: SettingsManager, theme_manager: ThemeManager):
        super().__init__(parent=parent, theme_manager=theme_manager)
        self.settings_manager = settings_manager

        self.title("Model Settings")
        self.geometry("600x450")
        self.minsize(500, 400)
        self.grab_set() # Modal - prevent interaction with main window

        self.model_path = ""
        self.model_settings = {}
        self.dont_show_again = ctk.BooleanVar(value=False)

        self.create_widgets()
        self.load_models()
        self.load_current_settings()
        self.apply_theme()

    def create_widgets(self):
        """Create widgets for the popup."""
        main_frame = self

        try:
            title_font = ctk.CTkFont(family="Consolas", size=16, weight="bold")
            font = ctk.CTkFont(family="Consolas", size=12)
        except:
            title_font = ("Consolas", 16, "bold")
            font = ("Consolas", 12)

        ctk.CTkLabel(main_frame, text="Select a Model to Load", font=title_font).pack(pady=(0, 20))

        # Model selection dropdown
        model_frame = ctk.CTkFrame(main_frame)
        model_frame.pack(fill="x", padx=10, pady=10)
        ctk.CTkLabel(model_frame, text="Model File:", font=font).pack(side="left", padx=10)
        self.model_dropdown = ctk.CTkComboBox(model_frame, values=[""], font=font)
        self.model_dropdown.set("")
        self.model_dropdown.pack(side="left", expand=True, fill="x", padx=10)

        # Model parameters
        params_frame = ctk.CTkFrame(main_frame)
        params_frame.pack(fill="x", padx=10, pady=10)
        ctk.CTkLabel(params_frame, text="Model Parameters", font=font).pack()

        grid_frame = ctk.CTkFrame(params_frame)
        grid_frame.pack(pady=10)

        params = [
            ("Context Size:", "n_ctx", 0, 0), ("Threads:", "n_threads", 0, 2),
            ("GPU Layers:", "n_gpu_layers", 1, 0), ("Max Tokens:", "max_tokens", 1, 2),
            ("Chat Format:", "chat_format", 2, 0)
        ]

        self.model_entries = {}
        for label, key, row, col in params:
            ctk.CTkLabel(grid_frame, text=label, font=font).grid(row=row, column=col, padx=10, pady=5, sticky="e")
            entry = ctk.CTkEntry(grid_frame, width=120, font=font)
            entry.grid(row=row, column=col+1, padx=10, pady=5, sticky="w")
            self.model_entries[key] = entry

        # Warning Label
        warning_label = ctk.CTkLabel(
            main_frame,
            text="Warning: You must reload the model for any changes to take effect.",
            text_color=LYRN_WARNING,
            font=font,
            wraplength=550, # Ensure text wraps nicely
            justify="center"
        )
        warning_label.pack(pady=(15, 0), padx=20)

        # Bottom frame for checkbox and buttons
        bottom_frame = ctk.CTkFrame(main_frame)
        bottom_frame.pack(fill="x", padx=10, pady=(15, 0))

        self.dont_show_checkbox = ctk.CTkCheckBox(
            bottom_frame, text="Don't show this again on startup",
            font=font, variable=self.dont_show_again
        )
        self.dont_show_checkbox.pack(side="left", padx=10)

        self.load_button = ctk.CTkButton(bottom_frame, text="Load Model", font=font, command=self.load_model)
        self.load_button.pack(side="right", padx=10)

        # --- Preset Management ---
        preset_frame = ctk.CTkFrame(main_frame)
        preset_frame.pack(fill="x", padx=10, pady=10)
        ctk.CTkLabel(preset_frame, text="Presets:", font=font).pack(side="left", padx=10)

        save_preset_button = ctk.CTkButton(preset_frame, text="Save", width=50, font=font, command=self.save_preset)
        save_preset_button.pack(side="left", padx=5)

        for i in range(1, 6):
            preset_button = ctk.CTkButton(preset_frame, text=str(i), width=30, font=font, command=lambda num=i: self.load_preset(num))
            preset_button.pack(side="left", padx=5)

    def save_preset(self):
        """Saves the current model settings as a numbered preset."""
        dialog = ctk.CTkInputDialog(text="Enter preset number to save (1-5):", title="Save Preset")
        preset_num_str = dialog.get_input()

        if not preset_num_str or not preset_num_str.isdigit() or not 1 <= int(preset_num_str) <= 5:
            print("Invalid preset number. Please enter a number between 1 and 5.")
            # Optionally, show a message to the user
            return

        preset_num = preset_num_str

        # Gather current settings from the UI
        selected_model_file = self.model_dropdown.get()
        if not selected_model_file:
            print("Cannot save preset without a selected model.")
            return

        preset_data = {
            "model_path": os.path.join(SCRIPT_DIR, "models", selected_model_file)
        }
        for key, entry in self.model_entries.items():
            value = entry.get()
            if key in ["n_ctx", "n_threads", "n_gpu_layers", "max_tokens"]:
                try:
                    preset_data[key] = int(value)
                except (ValueError, TypeError):
                    preset_data[key] = 0
            elif key == "chat_format":
                preset_data[key] = None if not value else value
            else:
                preset_data[key] = value

        # Save to settings.json
        if "model_presets" not in self.settings_manager.settings:
            self.settings_manager.settings["model_presets"] = {}

        self.settings_manager.settings["model_presets"][preset_num] = preset_data
        self.settings_manager.save_settings()
        print(f"Preset '{preset_num}' saved successfully.")
        # Optionally, update a status label in the popup
        self.parent_app.update_status(f"Preset {preset_num} saved.", LYRN_SUCCESS)


    def load_preset(self, preset_num: int):
        """Loads a model settings preset and populates the UI."""
        preset_num_str = str(preset_num)
        presets = self.settings_manager.settings.get("model_presets", {})

        if preset_num_str not in presets:
            print(f"Preset '{preset_num_str}' not found.")
            self.parent_app.update_status(f"Preset {preset_num_str} not found.", LYRN_WARNING)
            return

        preset_data = presets[preset_num_str]

        # Populate UI fields
        for key, entry in self.model_entries.items():
            entry.delete(0, "end")
            value = preset_data.get(key)
            if key == "chat_format":
                 entry.insert(0, "" if value is None else str(value))
            elif value is not None:
                entry.insert(0, str(value))

        model_path = preset_data.get("model_path", "")
        if model_path:
            model_filename = os.path.basename(model_path)
            if model_filename in self.model_dropdown.cget("values"):
                self.model_dropdown.set(model_filename)
                self.model_dropdown.update() # Force UI to process the change immediately

        print(f"Preset '{preset_num_str}' loaded.")
        self.parent_app.update_status(f"Preset {preset_num_str} loaded.", LYRN_INFO)
        self.apply_theme()

    def load_models(self):
        """Scan the models directory and populate the dropdown."""
        models_dir = os.path.join(SCRIPT_DIR, "models")
        if not os.path.exists(models_dir):
            os.makedirs(models_dir)
            self.model_dropdown.configure(values=["'models' folder created."])
            return

        try:
            model_files = [f for f in os.listdir(models_dir) if f.endswith((".gguf", ".bin"))]
            if model_files:
                self.model_dropdown.configure(values=model_files)
                self.model_dropdown.set(model_files[0])
            else:
                self.model_dropdown.configure(values=[""])
                self.model_dropdown.set("")
        except Exception as e:
            self.model_dropdown.configure(values=[f"Error: {e}"])
            print(f"Error scanning for models: {e}")

    def load_current_settings(self):
        """Load current model settings from settings manager."""
        if not self.settings_manager.settings:
            return

        active_settings = self.settings_manager.settings.get("active", {})
        for key, entry in self.model_entries.items():
            entry.delete(0, "end")
            if key == "chat_format":
                # Default to None if missing. Show empty string for None, otherwise the value.
                val = active_settings.get(key, None)
                entry.insert(0, "" if val is None else str(val))
            else:
                # Keep original behavior for other settings for now
                default_value = ""
                entry.insert(0, str(active_settings.get(key, default_value)))

        # Pre-select model in dropdown if it exists
        current_model_path = active_settings.get("model_path", "")
        if current_model_path:
            model_filename = os.path.basename(current_model_path)
            if model_filename in self.model_dropdown.cget("values"):
                self.model_dropdown.set(model_filename)

    def load_model(self):
        """Save settings, trigger model load in parent, and close popup."""
        # 1. Get settings from UI
        selected_model_file = self.model_dropdown.get()
        if not selected_model_file or "No models found" in selected_model_file:
            # Maybe show an error label in the popup
            print("No valid model selected.")
            return

        self.model_path = os.path.join(SCRIPT_DIR, "models", selected_model_file)

        new_active_settings = self.settings_manager.settings.get("active", {}).copy()
        new_active_settings["model_path"] = self.model_path

        for key, entry in self.model_entries.items():
            value = entry.get()
            if key in ["n_ctx", "n_threads", "n_gpu_layers", "max_tokens"]:
                try:
                    new_active_settings[key] = int(value)
                except (ValueError, TypeError):
                    print(f"Warning: Could not parse '{value}' for '{key}'. Using 0.")
                    new_active_settings[key] = 0
            elif key == "chat_format":
                # If the value is an empty string, save None. Otherwise, save the string.
                new_active_settings[key] = None if not value else value
            else:
                new_active_settings[key] = value

        # 2. Save settings
        self.settings_manager.settings["active"] = new_active_settings
        if self.dont_show_again.get():
            self.settings_manager.ui_settings["show_model_selector"] = False

        self.settings_manager.save_settings()

        # 3. Trigger load in parent
        self.parent_app.update_status("Loading selected model...", LYRN_INFO)
        threading.Thread(target=self.parent_app.setup_model, daemon=True).start()

        # 4. Close popup
        self.grab_release()
        self.destroy()

class CommandPalette(ThemedPopup):
    def __init__(self, parent, commands: List[Dict[str, any]], theme_manager: ThemeManager):
        super().__init__(parent=parent, theme_manager=theme_manager)
        self.all_commands = commands
        self.filtered_commands = commands

        self.title("Command Palette")
        self.geometry("600x350")
        self.minsize(400, 300)
        self.grab_set()

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        try:
            font = ctk.CTkFont(family="Consolas", size=14)
        except:
            font = ("Consolas", 14)

        self.search_entry = ctk.CTkEntry(self, placeholder_text="Type a command...", font=font)
        self.search_entry.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        self.search_entry.bind("<KeyRelease>", self._filter_commands)
        self.search_entry.focus()

        self.results_frame = ctk.CTkScrollableFrame(self, label_text="")
        self.results_frame.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")

        self.bind("<Escape>", lambda e: self.destroy())

        self._populate_command_list()
        self.apply_theme()

    def _filter_commands(self, event=None):
        search_term = self.search_entry.get().lower()
        if not search_term:
            self.filtered_commands = self.all_commands
        else:
            self.filtered_commands = [
                cmd for cmd in self.all_commands
                if search_term in cmd["name"].lower()
            ]
        self._populate_command_list()

    def _populate_command_list(self):
        # Clear previous results
        for widget in self.results_frame.winfo_children():
            widget.destroy()

        # Add new results
        for i, cmd in enumerate(self.filtered_commands):
            btn = ctk.CTkButton(
                self.results_frame,
                text=cmd["name"],
                anchor="w",
                command=lambda c=cmd: self._execute_command(c["command"])
            )
            btn.pack(fill="x", padx=5, pady=3)
            if i == 0: # Select the first item
                btn.focus()
                self.bind("<Return>", lambda e, c=cmd: self._execute_command(c["command"]))


    def _execute_command(self, command_func):
        self.destroy()
        self.parent_app.after(50, command_func) # Use after to ensure palette closes first

class TabbedSettingsDialog(ThemedPopup):
    """Enhanced settings dialog with tabs"""

    def __init__(self, parent, settings_manager: SettingsManager, theme_manager: ThemeManager, language_manager: LanguageManager):
        super().__init__(parent=parent, theme_manager=theme_manager)
        self.settings_manager = settings_manager
        self.language_manager = language_manager

        self.title(self.language_manager.get("settings_window_title"))
        self.geometry("900x700")
        self.minsize(800, 600)

        self.show_model_selector_var = ctk.BooleanVar()

        self.create_widgets()
        self.load_current_settings()
        self.apply_theme()

    def open_theme_builder(self):
        """Opens the coming soon popup for the theme builder."""
        popup = ComingSoonPopup(self.parent_app, self.theme_manager)
        popup.focus()

    def create_widgets(self):
        """Create tabbed interface"""
        # Main tabview
        self.tabview = ctk.CTkTabview(self, width=850, height=600)
        self.tabview.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        # Create tabs
        self.tab_paths = self.tabview.add(self.language_manager.get("tab_directory_paths"))
        # self.tab_prompt = self.tabview.add(self.language_manager.get("tab_prompt_manager")) # Tab is being removed
        self.tab_personality = self.tabview.add("Personality")
        self.tab_ui_settings = self.tabview.add("UI Settings")
        self.tab_advanced = self.tabview.add(self.language_manager.get("tab_advanced"))

        self.create_paths_tab()
        # self.create_prompt_manager_tab() # Logic moved to popup
        self.create_personality_tab()
        self.create_ui_settings_tab()
        self.create_advanced_tab()

        # Button frame
        button_frame = ctk.CTkFrame(self)
        button_frame.pack(fill="x", padx=20, pady=(0, 20))

        self.save_button = ctk.CTkButton(button_frame, text=self.language_manager.get("button_save_all"),
                                        command=self.save_all_settings)
        self.save_button.pack(side="left", padx=10, pady=10)
        Tooltip(self.save_button, self.parent_app.tooltips.get("save_all_settings_button", ""))

        self.cancel_button = ctk.CTkButton(button_frame, text=self.language_manager.get("button_cancel"),
                                          command=self.destroy)
        self.cancel_button.pack(side="right", padx=10, pady=10)
        Tooltip(self.cancel_button, self.parent_app.tooltips.get("cancel_settings_button", ""))

    def create_paths_tab(self):
        """Create directory paths tab"""
        try:
            font = ctk.CTkFont(family="Consolas", size=12)
        except:
            font = ("Consolas", 12)

        # Scrollable frame for paths
        scroll_frame = ctk.CTkScrollableFrame(self.tab_paths)
        scroll_frame.pack(fill="both", expand=True, padx=20, pady=20)

        self.path_entries = {}
        path_labels = {
            "static_snapshots": "Static Snapshots Directory",
            "dynamic_snapshots": "Dynamic Snapshots Directory",
            "active_jobs": "Active Jobs Directory",
            "deltas": "Deltas Directory",
            "chat": "Chat Directory",
            "output": "Output Directory",
            "metrics_logs": "Metrics Logs Directory"
        }

        for key, label in path_labels.items():
            ctk.CTkLabel(scroll_frame, text=f"{label}:", font=font).pack(
                anchor="w", padx=10, pady=(10, 0))
            entry = ctk.CTkEntry(scroll_frame, font=font)
            entry.pack(fill="x", padx=10, pady=(0, 5))
            self.path_entries[key] = entry

    def create_ui_settings_tab(self):
        """Create the UI settings tab."""
        try:
            font = ctk.CTkFont(family="Consolas", size=12)
            title_font = ctk.CTkFont(family="Consolas", size=14, weight="bold")
        except:
            font = ("Consolas", 12)
            title_font = ("Consolas", 14, "bold")

        self.tab_ui_settings.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self.tab_ui_settings, text="User Interface Customization",
                    font=title_font).pack(pady=20)

        # --- Language Settings ---
        language_frame = ctk.CTkFrame(self.tab_ui_settings)
        language_frame.pack(fill="x", padx=20, pady=10)
        ctk.CTkLabel(language_frame, text="Language", font=title_font).pack(pady=10, anchor="w", padx=10)

        lang_select_frame = ctk.CTkFrame(language_frame)
        lang_select_frame.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(lang_select_frame, text="Display Language:", font=font).pack(side="left", padx=5)

        available_languages = self.language_manager.get_available_languages()
        self.language_var = ctk.StringVar(value=self.language_manager.language)
        self.language_selector = ctk.CTkComboBox(lang_select_frame, values=available_languages, variable=self.language_var, font=font)
        self.language_selector.pack(side="left", padx=5, expand=True, fill="x")

        # We will add functionality later. For now, just save the setting.
        # A restart will be required to see changes.
        ctk.CTkLabel(language_frame, text="Language changes require an application restart.", font=font).pack(padx=20, pady=5, anchor="w")

        # --- Font and Theme Settings ---
        display_frame = ctk.CTkFrame(self.tab_ui_settings)
        display_frame.pack(fill="x", padx=20, pady=10)
        ctk.CTkLabel(display_frame, text="Display & Theme", font=title_font).pack(pady=10, anchor="w", padx=10)

        # Theme selection
        theme_frame = ctk.CTkFrame(display_frame)
        theme_frame.pack(fill="x", padx=10, pady=10)
        ctk.CTkLabel(theme_frame, text="Theme:", font=font).pack(side="left", padx=5)
        theme_selector = ctk.CTkComboBox(
            theme_frame,
            values=self.parent_app.theme_manager.get_theme_names(),
            command=self.parent_app.on_theme_selected
        )
        theme_selector.pack(side="left", expand=True, fill="x", padx=5)
        theme_selector.set(self.parent_app.theme_manager.get_current_theme_name())
        Tooltip(theme_selector, self.parent_app.tooltips.get("theme_dropdown", ""))

        # Font size controls
        font_frame = ctk.CTkFrame(display_frame)
        font_frame.pack(fill="x", padx=10, pady=10)
        ctk.CTkLabel(font_frame, text="Font Size:", font=font).pack(side="left", padx=5)

        self.font_size_label = ctk.CTkLabel(font_frame, text=str(self.parent_app.current_font_size), font=font)
        self.font_size_label.pack(side="left", padx=5)

        font_decrease_button = ctk.CTkButton(font_frame, text="A-", width=30, height=25,
                     font=font,
                     command=self.decrease_font_in_settings)
        font_decrease_button.pack(side="left", padx=2)

        font_increase_button = ctk.CTkButton(font_frame, text="A+", width=30, height=25,
                     font=font,
                     command=self.increase_font_in_settings)
        font_increase_button.pack(side="left", padx=2)


        # --- Moved Buttons ---
        moved_buttons_frame = ctk.CTkFrame(self.tab_ui_settings)
        moved_buttons_frame.pack(fill="x", padx=20, pady=10)
        ctk.CTkLabel(moved_buttons_frame, text="Chat Controls", font=title_font).pack(pady=10, anchor="w", padx=10)

        clear_chat_button = ctk.CTkButton(moved_buttons_frame, text="🗑️ Clear Display Text",
                                             font=font, command=self.parent_app.clear_chat)
        clear_chat_button.pack(padx=10, pady=5, anchor="w")
        Tooltip(clear_chat_button, self.parent_app.tooltips.get("clear_chat_button", ""))

        # --- Terminal Settings ---
        terminal_frame = ctk.CTkFrame(self.tab_ui_settings)
        terminal_frame.pack(fill="x", padx=20, pady=10)
        ctk.CTkLabel(terminal_frame, text="Terminal", font=title_font).pack(pady=10, anchor="w", padx=10)

        path_frame = ctk.CTkFrame(terminal_frame)
        path_frame.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(path_frame, text="Terminal Start Path:", font=font).pack(side="left", padx=5)
        self.terminal_start_path_entry = ctk.CTkEntry(path_frame, font=font)
        self.terminal_start_path_entry.pack(side="left", expand=True, fill="x", padx=5)

    def increase_font_in_settings(self):
        self.parent_app.increase_font_size()
        self.font_size_label.configure(text=str(self.parent_app.current_font_size))

    def decrease_font_in_settings(self):
        self.parent_app.decrease_font_size()
        self.font_size_label.configure(text=str(self.parent_app.current_font_size))

    def create_advanced_tab(self):
        """Create advanced settings tab"""
        try:
            font = ctk.CTkFont(family="Consolas", size=12)
            title_font = ctk.CTkFont(family="Consolas", size=14, weight="bold")
        except:
            font = ("Consolas", 12)
            title_font = ("Consolas", 14, "bold")

        ctk.CTkLabel(self.tab_advanced, text="Advanced Operations",
                    font=title_font).pack(pady=20)

        # System maintenance section
        maint_frame = ctk.CTkFrame(self.tab_advanced)
        maint_frame.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(maint_frame, text="System Maintenance", font=title_font).pack(pady=10)

        # Clear operations
        clear_frame = ctk.CTkFrame(maint_frame)
        clear_frame.pack(fill="x", padx=10, pady=10)

        clear_chat_dir_button = ctk.CTkButton(clear_frame, text="Clear Chat Directory",
                     font=font, command=self.clear_chat_directory)
        clear_chat_dir_button.pack(side="left", padx=5, pady=5)
        Tooltip(clear_chat_dir_button, self.parent_app.tooltips.get("clear_chat_directory_button", ""))

        clear_deltas_dir_button = ctk.CTkButton(clear_frame, text="Clear Deltas Directory",
                        font=font, command=self.clear_deltas_directory)
        clear_deltas_dir_button.pack(side="left", padx=5, pady=5)
        Tooltip(clear_deltas_dir_button, self.parent_app.tooltips.get("clear_deltas_directory_button", ""))

        clear_metrics_logs_button = ctk.CTkButton(clear_frame, text="Clear Metrics Logs",
                        font=font, command=self.clear_metrics_logs)
        clear_metrics_logs_button.pack(side="left", padx=5, pady=5)
        Tooltip(clear_metrics_logs_button, self.parent_app.tooltips.get("clear_metrics_logs_button", ""))

        # Model operations
        model_frame = ctk.CTkFrame(maint_frame)
        model_frame.pack(fill="x", padx=10, pady=10)

        force_cleanup_button = ctk.CTkButton(model_frame, text="🧹 Force Memory Cleanup",
                        font=font, command=self.force_memory_cleanup)
        force_cleanup_button.pack(side="left", padx=5, pady=5)
        Tooltip(force_cleanup_button, self.parent_app.tooltips.get("force_memory_cleanup_button", ""))

        # Testing utilities
        test_frame = ctk.CTkFrame(self.tab_advanced)
        test_frame.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(test_frame, text="Testing Utilities", font=title_font).pack(pady=10)

        util_frame = ctk.CTkFrame(test_frame)
        util_frame.pack(fill="x", padx=10, pady=10)

        export_info_button = ctk.CTkButton(util_frame, text="Export System Info",
                        font=font, command=self.export_system_info)
        export_info_button.pack(side="left", padx=5, pady=5)
        Tooltip(export_info_button, self.parent_app.tooltips.get("export_system_info_button", ""))

        test_perf_button = ctk.CTkButton(util_frame, text="Test Model Performance",
                        font=font, command=self.test_model_performance)
        test_perf_button.pack(side="left", padx=5, pady=5)
        Tooltip(test_perf_button, self.parent_app.tooltips.get("test_model_performance_button", ""))

        validate_dirs_button = ctk.CTkButton(util_frame, text="Validate Directories",
                        font=font, command=self.validate_directories)
        validate_dirs_button.pack(side="left", padx=5, pady=5)
        Tooltip(validate_dirs_button, self.parent_app.tooltips.get("validate_directories_button", ""))

        open_theme_builder_button = ctk.CTkButton(util_frame, text="Open Theme Builder",
                        font=font, command=self.open_theme_builder)
        open_theme_builder_button.pack(side="left", padx=5, pady=5)
        Tooltip(open_theme_builder_button, "Open the live theme editor popup.")

        # Add checkbox for re-enabling model selector
        # Model Loading Control Section
        model_loading_frame = ctk.CTkFrame(self.tab_advanced)
        model_loading_frame.pack(fill="x", padx=20, pady=10)
        ctk.CTkLabel(model_loading_frame, text="Model Loading Control", font=title_font).pack(pady=10)

        self.autoload_model_var = ctk.BooleanVar()
        self.show_model_selector_var = ctk.BooleanVar()
        self.llm_log_visible_var = ctk.BooleanVar()
        self.llm_log_on_top_var = ctk.BooleanVar()

        ctk.CTkCheckBox(model_loading_frame, text="Autoload model on GUI start", font=font, variable=self.autoload_model_var).pack(anchor="w", padx=10, pady=5)
        ctk.CTkCheckBox(model_loading_frame, text="Show model selector on startup", font=font, variable=self.show_model_selector_var).pack(anchor="w", padx=10, pady=5)
        ctk.CTkCheckBox(model_loading_frame, text="LLM log default visibility", font=font, variable=self.llm_log_visible_var).pack(anchor="w", padx=10, pady=5)
        ctk.CTkCheckBox(model_loading_frame, text="LLM log always on top", font=font, variable=self.llm_log_on_top_var).pack(anchor="w", padx=10, pady=5)

    def create_personality_tab(self):
        """Creates the personality tab UI."""
        self.personality_file = Path(SCRIPT_DIR) / "personality.json"
        self.personality_data = self._load_personality_data()
        self.initial_traits = self.personality_data.get("active_traits", {}).copy()
        self.current_traits = self.initial_traits.copy()
        self.personality_sliders = {}
        self.personality_labels = {}
        self.personality_preset_var = ctk.StringVar(value="")

        # Preset management frame
        preset_frame = ctk.CTkFrame(self.tab_personality)
        preset_frame.pack(fill="x", padx=10, pady=10)
        ctk.CTkLabel(preset_frame, text="Presets:").pack(side="left", padx=5)
        self.personality_preset_menu = ctk.CTkComboBox(preset_frame, variable=self.personality_preset_var, command=self.load_personality_preset)
        self.personality_preset_menu.pack(side="left", expand=True, fill="x", padx=5)

        save_preset_button = ctk.CTkButton(preset_frame, text="Save Preset", width=100, command=self.save_personality_preset)
        save_preset_button.pack(side="left", padx=5)

        self.personality_main_frame = ctk.CTkScrollableFrame(self.tab_personality, label_text="Active Traits")
        self.personality_main_frame.pack(expand=True, fill="both", padx=10, pady=0)

        # Bottom button frame
        button_frame = ctk.CTkFrame(self.tab_personality)
        button_frame.pack(fill="x", padx=10, pady=10)

        apply_button = ctk.CTkButton(button_frame, text="Apply Changes", command=self.apply_personality_changes)
        apply_button.pack(side="right")

        self.populate_personality_sliders()
        self.populate_personality_presets()

    def _load_personality_data(self):
        """Loads personality data from the JSON file."""
        if self.personality_file.exists():
            try:
                with open(self.personality_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"Error loading or parsing personality.json: {e}. Using default values.")
                return {"presets": {}, "active_traits": {"creativity": 500}}
        else:
            print("Warning: personality.json not found. Creating with default values.")
            default_data = {
                "presets": {
                    "Default": {
                        "description": "The standard, balanced LYRN personality.",
                        "traits": { "creativity": 500, "consistency": 750, "verbosity": 400, "assertiveness": 600, "curiosity": 800 }
                    }
                },
                "active_traits": { "creativity": 500, "consistency": 750, "verbosity": 400, "assertiveness": 600, "curiosity": 800 }
            }
            try:
                with open(self.personality_file, 'w', encoding='utf-8') as f:
                    json.dump(default_data, f, indent=2)
            except IOError as e:
                print(f"Error creating default personality.json: {e}")
            return default_data

    def _save_personality_data(self):
        """Saves the current personality data to the JSON file."""
        try:
            with open(self.personality_file, 'w', encoding='utf-8') as f:
                json.dump(self.personality_data, f, indent=2)
        except IOError as e:
            print(f"Error saving personality file: {e}")

    def populate_personality_sliders(self):
        """Creates or updates sliders based on the data in active_traits."""
        for widget in self.personality_main_frame.winfo_children():
            widget.destroy()

        for trait, value in self.current_traits.items():
            frame = ctk.CTkFrame(self.personality_main_frame)
            frame.pack(fill="x", pady=5, padx=5)

            label_text = f"{trait.capitalize()}: {value}"
            label = ctk.CTkLabel(frame, text=label_text, width=150, anchor="w")
            label.pack(side="left", padx=10)
            self.personality_labels[trait] = label

            slider = ctk.CTkSlider(frame, from_=0, to=1000, number_of_steps=1000,
                                   command=lambda v, t=trait: self._on_personality_slider_change(t, v))
            slider.set(value)
            slider.pack(side="left", expand=True, fill="x", padx=10)
            self.personality_sliders[trait] = slider

    def populate_personality_presets(self):
        """Populates the preset dropdown menu."""
        presets = list(self.personality_data.get("presets", {}).keys())
        self.personality_preset_menu.configure(values=["Custom"] + presets)

        active_preset_name = "Custom"
        for name, preset_data in self.personality_data.get("presets", {}).items():
            if preset_data.get("traits") == self.current_traits:
                active_preset_name = name
                break
        self.personality_preset_var.set(active_preset_name)

    def _on_personality_slider_change(self, trait_name: str, new_value: float):
        """Callback when a slider value changes, updates the label and current_traits."""
        int_value = int(new_value)
        self.personality_labels[trait_name].configure(text=f"{trait_name.capitalize()}: {int_value}")
        self.current_traits[trait_name] = int_value
        self.populate_personality_presets()

    def apply_personality_changes(self):
        """Applies the changes made to the sliders."""
        changes_applied = False
        for trait, value in self.current_traits.items():
            if self.initial_traits.get(trait) != value:
                print(f"Delta: {trait} changed from {self.initial_traits.get(trait)} to {value}")
                self.parent_app.delta_manager.create_delta(
                    "P-001", "personality", "traits", "update",
                    trait, str(value)
                )
                changes_applied = True

        if changes_applied:
            self.personality_data["active_traits"] = self.current_traits
            self._save_personality_data()
            self.initial_traits = self.current_traits.copy()
            self.parent_app.update_status("Personality changes applied.", LYRN_SUCCESS)
        else:
            self.parent_app.update_status("No changes to apply.", LYRN_INFO)

    def load_personality_preset(self, preset_name: str):
        """Loads a selected preset's traits into the active sliders."""
        if preset_name == "Custom":
            return
        preset_traits = self.personality_data.get("presets", {}).get(preset_name, {}).get("traits")
        if preset_traits:
            self.current_traits = preset_traits.copy()
            self.populate_personality_sliders()
            self.populate_personality_presets()

    def save_personality_preset(self):
        """Saves the current active traits as a new preset."""
        dialog = ctk.CTkInputDialog(text="Enter a name for the new preset:", title="Save Preset")
        preset_name = dialog.get_input()

        if preset_name and preset_name not in ["Custom"]:
            self.personality_data["presets"][preset_name] = {
                "description": "User-saved preset.",
                "traits": self.current_traits.copy()
            }
            self._save_personality_data()
            self.populate_personality_presets()
            self.personality_preset_var.set(preset_name)

    def load_current_settings(self):
        """Load current settings into all tabs"""
        if not self.settings_manager.settings:
            return

        settings = self.settings_manager.settings
        active = settings.get("active", {})
        paths = settings.get("paths", {})

        # Model settings are managed in the main UI now.

        # Load paths
        for key, entry in self.path_entries.items():
            if key in paths:
                entry.insert(0, paths[key])

        # Load UI settings
        self.show_model_selector_var.set(self.settings_manager.ui_settings.get("show_model_selector", True))
        self.autoload_model_var.set(self.settings_manager.ui_settings.get("autoload_model", False))
        self.llm_log_visible_var.set(self.settings_manager.ui_settings.get("llm_log_visible", False))
        self.llm_log_on_top_var.set(self.settings_manager.ui_settings.get("llm_log_on_top", False))
        self.terminal_start_path_entry.insert(0, self.settings_manager.ui_settings.get("terminal_start_path", ""))

    def apply_theme(self):
        """Applies the current theme colors to all widgets in this dialog."""
        tm = self.theme_manager
        primary_color = tm.get_color("primary")
        accent_color = tm.get_color("accent")
        frame_bg = tm.get_color("frame_bg")
        textbox_bg = tm.get_color("textbox_bg")
        textbox_fg = tm.get_color("textbox_fg")
        label_text = tm.get_color("label_text")
        border_color = tm.get_color("border_color")

        # Theme background
        self.configure(fg_color=frame_bg)

        # Theme the tabview
        self.tabview.configure(
            segmented_button_selected_color=primary_color,
            segmented_button_selected_hover_color=accent_color,
            fg_color=frame_bg
        )

        # Theme all widgets recursively
        for widget_type, config in [
            (ctk.CTkButton, {"fg_color": primary_color}),
            (ctk.CTkComboBox, {"button_color": primary_color, "button_hover_color": accent_color}),
            (ctk.CTkFrame, {"fg_color": frame_bg, "border_color": border_color}),
            (ctk.CTkLabel, {"text_color": label_text}),
            (ctk.CTkEntry, {"fg_color": textbox_bg, "text_color": textbox_fg, "border_color": border_color}),
            (ctk.CTkTextbox, {"fg_color": textbox_bg, "text_color": textbox_fg, "border_color": border_color}),
            (ctk.CTkScrollableFrame, {"fg_color": frame_bg, "label_fg_color": primary_color}),
            (ctk.CTkCheckBox, {"fg_color": primary_color}),
        ]:
            for widget in self.find_widgets_recursively(self, widget_type):
                try:
                    widget.configure(**config)
                except Exception as e:
                    # print(f"Could not configure {widget} with {config}: {e}")
                    pass # Ignore if a widget doesn't support a property

        # Explicitly theme some items that might be missed
        self.save_button.configure(fg_color=primary_color)
        self.cancel_button.configure(fg_color=primary_color)

    def find_widgets_recursively(self, widget, widget_type):
        widgets = []
        if isinstance(widget, widget_type):
            widgets.append(widget)
        for child in widget.winfo_children():
            widgets.extend(self.find_widgets_recursively(child, widget_type))
        return widgets

    def clear_chat_directory(self):
        """Clear chat directory after confirmation."""
        from confirmation_dialog import ConfirmationDialog

        prefs = self.parent_app.settings_manager.ui_settings.get("confirmation_preferences", {})
        if prefs.get("clear_chat_directory"):
            confirmed = True
        else:
            confirmed, dont_ask_again = ConfirmationDialog.show(
                self,
                self.theme_manager,
                title="Confirm Clear Directory",
                message="Are you sure you want to permanently delete all files in the chat directory?"
            )
            if dont_ask_again:
                prefs["clear_chat_directory"] = True
                self.parent_app.settings_manager.ui_settings["confirmation_preferences"] = prefs
                self.parent_app.settings_manager.save_settings()

        if not confirmed:
            self.parent_app.update_status("Clear chat directory cancelled.", LYRN_INFO)
            return

        if not self.settings_manager.settings:
            return

        chat_dir = self.settings_manager.settings["paths"].get("chat", "")
        if chat_dir and os.path.exists(chat_dir):
            try:
                count = 0
                for filename in os.listdir(chat_dir):
                    file_path = os.path.join(chat_dir, filename)
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                        count += 1
                print(f"Cleared chat directory: {chat_dir}")
                self.parent_app.update_status(f"Cleared {count} files from chat directory.", LYRN_SUCCESS)
            except Exception as e:
                print(f"Error clearing chat directory: {e}")
                self.parent_app.update_status("Error clearing chat directory.", LYRN_ERROR)

    def clear_deltas_directory(self):
        """Clear deltas directory after confirmation."""
        from confirmation_dialog import ConfirmationDialog

        prefs = self.parent_app.settings_manager.ui_settings.get("confirmation_preferences", {})
        if prefs.get("clear_deltas_directory"):
            confirmed = True
        else:
            confirmed, dont_ask_again = ConfirmationDialog.show(
                self,
                self.theme_manager,
                title="Confirm Clear Directory",
                message="Are you sure you want to permanently delete all files in the deltas directory?"
            )
            if dont_ask_again:
                prefs["clear_deltas_directory"] = True
                self.parent_app.settings_manager.ui_settings["confirmation_preferences"] = prefs
                self.parent_app.settings_manager.save_settings()

        if not confirmed:
            self.parent_app.update_status("Clear deltas directory cancelled.", LYRN_INFO)
            return

        if not self.settings_manager.settings:
            return

        deltas_dir = self.settings_manager.settings["paths"].get("deltas", "")
        if deltas_dir and os.path.exists(deltas_dir):
            try:
                count = 0
                for filename in os.listdir(deltas_dir):
                    file_path = os.path.join(deltas_dir, filename)
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                        count += 1
                print(f"Cleared deltas directory: {deltas_dir}")
                self.parent_app.update_status(f"Cleared {count} files from deltas directory.", LYRN_SUCCESS)
            except Exception as e:
                print(f"Error clearing deltas directory: {e}")
                self.parent_app.update_status("Error clearing deltas directory.", LYRN_ERROR)

    def clear_metrics_logs(self):
        """Clear metrics logs directory after confirmation."""
        from confirmation_dialog import ConfirmationDialog

        prefs = self.parent_app.settings_manager.ui_settings.get("confirmation_preferences", {})
        if prefs.get("clear_metrics_logs"):
            confirmed = True
        else:
            confirmed, dont_ask_again = ConfirmationDialog.show(
                self,
                self.theme_manager,
                title="Confirm Clear Directory",
                message="Are you sure you want to permanently delete all files in the metrics_logs directory?"
            )
            if dont_ask_again:
                prefs["clear_metrics_logs"] = True
                self.parent_app.settings_manager.ui_settings["confirmation_preferences"] = prefs
                self.parent_app.settings_manager.save_settings()

        if not confirmed:
            self.parent_app.update_status("Clear metrics logs cancelled.", LYRN_INFO)
            return

        metrics_dir = os.path.join(SCRIPT_DIR, "metrics_logs")
        if os.path.exists(metrics_dir):
            try:
                count = 0
                for filename in os.listdir(metrics_dir):
                    file_path = os.path.join(metrics_dir, filename)
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                        count += 1
                print(f"Cleared metrics logs: {metrics_dir}")
                self.parent_app.update_status(f"Cleared {count} files from metrics logs.", LYRN_SUCCESS)
            except Exception as e:
                print(f"Error clearing metrics logs: {e}")
                self.parent_app.update_status("Error clearing metrics logs.", LYRN_ERROR)

    def reload_model_full(self):
        """Trigger full model reload in parent"""
        if hasattr(self.parent_app, 'reload_model_full'):
            self.parent_app.reload_model_full()

    def force_memory_cleanup(self):
        """Force memory cleanup"""
        if hasattr(self.parent_app, 'force_memory_cleanup'):
            self.parent_app.force_memory_cleanup()

    def export_system_info(self):
        """Export system information"""
        try:
            info_dir = os.path.join(SCRIPT_DIR, "system_info")
            os.makedirs(info_dir, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            info_file = os.path.join(info_dir, f"system_info_{timestamp}.txt")

            with open(info_file, 'w', encoding='utf-8') as f:
                f.write("LYRN-AI System Information\n")
                f.write(f"Generated: {datetime.now()}\n")
                f.write("="*50 + "\n\n")
                f.write(f"Python Version: {sys.version}\n")
                f.write(f"CustomTkinter Version: {ctk.__version__}\n")
                f.write(f"Script Directory: {SCRIPT_DIR}\n")
                # Add more system info as needed

            print(f"System info exported to: {info_file}")

        except Exception as e:
            print(f"Error exporting system info: {e}")

    def test_model_performance(self):
        """Test model performance"""
        if hasattr(self.parent_app, 'test_model_performance'):
            self.parent_app.test_model_performance()

    def validate_directories(self):
        """Validate all configured directories"""
        if not self.settings_manager.settings:
            print("No settings to validate")
            return

        paths = self.settings_manager.settings.get("paths", {})
        missing_dirs = []

        for key, path in paths.items():
            if path and not os.path.exists(path):
                missing_dirs.append(f"{key}: {path}")

        if missing_dirs:
            print("Missing directories:")
            for missing in missing_dirs:
                print(f"  - {missing}")
        else:
            print("All directories validated successfully")

    def save_all_settings(self):
        """Save all settings from all tabs"""
        try:
            if not self.settings_manager.settings:
                self.settings_manager.settings = self.settings_manager.create_empty_settings_structure()

            settings = self.settings_manager.settings.copy()

            # Model settings are managed in the main UI now.

            # Save paths
            for key, entry in self.path_entries.items():
                settings["paths"][key] = entry.get()

            # Update UI setting from checkbox
            self.settings_manager.ui_settings["show_model_selector"] = self.show_model_selector_var.get()
            self.settings_manager.ui_settings["autoload_model"] = self.autoload_model_var.get()
            self.settings_manager.ui_settings["llm_log_visible"] = self.llm_log_visible_var.get()
            self.settings_manager.ui_settings["llm_log_on_top"] = self.llm_log_on_top_var.get()
            self.settings_manager.ui_settings["language"] = self.language_var.get()
            self.settings_manager.ui_settings["terminal_start_path"] = self.terminal_start_path_entry.get()


            # Save all settings
            self.settings_manager.save_settings(settings)

            print("All settings saved successfully")
            self.destroy()

        except Exception as e:
            print(f"Error saving settings: {e}")


class SystemPromptBuilderPopup(ThemedPopup):
    """A popup window for building and managing the system prompt with a tabbed interface."""
    def __init__(self, parent, theme_manager: ThemeManager, language_manager: LanguageManager, snapshot_loader: SnapshotLoader):
        super().__init__(parent=parent, theme_manager=theme_manager)
        self.language_manager = language_manager
        self.snapshot_loader = snapshot_loader
        self.build_prompt_dir = Path(SCRIPT_DIR) / "build_prompt"
        self.config_path = self.build_prompt_dir / "builder_config.json"

        self.title("System Prompt Builder")
        self.geometry("1200x700")
        self.minsize(600, 500)

        self.on_top_var = ctk.BooleanVar(value=False)
        self.config = self._load_json(self.config_path)

        self.create_widgets()
        self.toggle_on_top() # Set initial state
        self.apply_theme()

    def _load_json(self, path: Path) -> dict:
        """Loads a JSON file."""
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"Error loading {path}: {e}")
        return {}

    def _save_json(self, path: Path, data: dict):
        """Saves data to a JSON file."""
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except IOError as e:
            print(f"Error saving {path}: {e}")

    def _load_text(self, path: Path) -> str:
        """Loads a text file."""
        if path.exists():
            try:
                return path.read_text(encoding='utf-8')
            except IOError as e:
                print(f"Error loading {path}: {e}")
        return ""

    def _save_text(self, path: Path, content: str):
        """Saves content to a text file."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
        except IOError as e:
            print(f"Error saving {path}: {e}")

    def save_all_changes(self):
        """Saves all changes from all tabs."""
        self.save_prompt_order()
        for config_key in self.editor_tabs.keys():
            self.save_component_config(config_key)
        self.save_personality_config()
        self.save_heartbeat_config()
        self.parent_app.update_status("All changes saved.", LYRN_SUCCESS)

    def load_mode(self):
        """Loads a saved mode, overwriting the current component configurations."""
        mode_name = self.mode_selector.get()
        if not mode_name or mode_name == "No modes":
            self.parent_app.update_status("No mode selected to load.", LYRN_WARNING)
            return

        modes_dir = self.build_prompt_dir / "modes"
        mode_path = modes_dir / mode_name

        if not mode_path.is_dir():
            self.parent_app.update_status(f"Mode '{mode_name}' not found.", LYRN_ERROR)
            return

        try:
            # List of component items to load
            component_items = [
                "system_instructions", "personality", "heartbeat",
                "user_preferences", "ai_preferences", "system_rules",
                "prompt_order.json"
            ]

            for item_name in component_items:
                source_path = mode_path / item_name
                dest_path = self.build_prompt_dir / item_name

                # Remove existing destination before copying
                if dest_path.exists():
                    if dest_path.is_dir():
                        shutil.rmtree(dest_path)
                    else:
                        dest_path.unlink()

                if source_path.exists():
                    if source_path.is_dir():
                        shutil.copytree(source_path, dest_path)
                    elif source_path.is_file():
                        shutil.copy2(source_path, dest_path)

            # This part will be implemented in the next step
            self.refresh_ui_from_loaded_mode()

            self.parent_app.update_status(f"Mode '{mode_name}' loaded successfully.", LYRN_SUCCESS)

        except Exception as e:
            self.parent_app.update_status(f"Error loading mode: {e}", LYRN_ERROR)
            print(f"Error loading mode: {e}")

    def refresh_ui_from_loaded_mode(self):
        """Destroys and recreates all tab content to reflect loaded data."""
        self.create_prompt_order_tab()
        self.create_editor_tab(self.tab_system_instructions, "system_instructions", "instructions.txt")
        self.create_personality_tab()
        self.create_editor_tab(self.tab_heartbeat, "heartbeat", "config.txt")
        self.create_editor_tab(self.tab_user_prefs, "user_preferences", "tone.txt")
        self.create_editor_tab(self.tab_ai_prefs, "ai_preferences", "verbosity.txt")
        self.create_editor_tab(self.tab_system_rules, "system_rules", "safety.txt")
        self.apply_theme()

    def save_mode(self):
        """Saves the current configuration of all components as a new named mode."""
        # First, ensure all current edits are saved to the base component files
        self.save_all_changes()

        dialog = ctk.CTkInputDialog(text="Enter a name for the new mode:", title="Save Mode")
        mode_name = dialog.get_input()

        if not mode_name:
            self.parent_app.update_status("Mode saving cancelled.", LYRN_INFO)
            return

        modes_dir = self.build_prompt_dir / "modes"
        new_mode_path = modes_dir / mode_name

        if new_mode_path.exists():
            self.parent_app.update_status(f"Mode '{mode_name}' already exists.", LYRN_ERROR)
            return

        try:
            new_mode_path.mkdir(parents=True)

            # List of component items (dirs and files) to snapshot
            component_items = [
                "system_instructions", "personality", "heartbeat",
                "user_preferences", "ai_preferences", "system_rules",
                "prompt_order.json"
            ]

            for item_name in component_items:
                source_path = self.build_prompt_dir / item_name
                dest_path = new_mode_path / item_name
                if source_path.is_dir():
                    shutil.copytree(source_path, dest_path)
                elif source_path.is_file():
                    shutil.copy2(source_path, dest_path)
                else:
                    print(f"Warning: Component item not found, skipping: {source_path}")

            self.populate_modes_dropdown()
            self.mode_selector.set(mode_name)
            self.parent_app.update_status(f"Mode '{mode_name}' saved successfully.", LYRN_SUCCESS)

        except Exception as e:
            self.parent_app.update_status(f"Error saving mode: {e}", LYRN_ERROR)
            print(f"Error saving mode: {e}")

    def populate_modes_dropdown(self):
        modes_dir = self.build_prompt_dir / "modes"
        modes_dir.mkdir(exist_ok=True)
        mode_names = [d.name for d in modes_dir.iterdir() if d.is_dir()]
        self.mode_selector.configure(values=mode_names if mode_names else ["No modes"])
        if mode_names:
            self.mode_selector.set(mode_names[0])
        else:
            self.mode_selector.set("No modes")

    def create_widgets(self):
        """Create the tabbed interface."""
        top_frame = ctk.CTkFrame(self, fg_color="transparent")
        top_frame.pack(fill="x", padx=10, pady=(10, 0))

        save_all_button = ctk.CTkButton(top_frame, text="Save All Changes", command=self.save_all_changes)
        save_all_button.pack(side="left", padx=5, pady=5)

        rebuild_prompt_button = ctk.CTkButton(top_frame, text="Rebuild Master Prompt", command=self.parent_app.refresh_prompt_from_mode)
        rebuild_prompt_button.pack(side="left", padx=5, pady=5)

        # Mode management frame
        mode_frame = ctk.CTkFrame(top_frame)
        mode_frame.pack(side="left", padx=20, pady=5)

        ctk.CTkLabel(mode_frame, text="Mode:").pack(side="left", padx=5)
        self.mode_selector = ctk.CTkComboBox(mode_frame, values=[])
        self.mode_selector.pack(side="left", padx=5)

        load_mode_button = ctk.CTkButton(mode_frame, text="Load", command=self.load_mode)
        load_mode_button.pack(side="left", padx=5)

        save_mode_button = ctk.CTkButton(mode_frame, text="Save", command=self.save_mode)
        save_mode_button.pack(side="left", padx=5)

        on_top_checkbox = ctk.CTkCheckBox(top_frame, text="Keep on Top", variable=self.on_top_var, command=self.toggle_on_top)
        on_top_checkbox.pack(side="right", padx=5, pady=5)

        self.populate_modes_dropdown()

        self.tabview = ctk.CTkTabview(self, width=750, height=650)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=10)

        self.tab_prompt_order = self.tabview.add("Prompt Build Order")
        self.tab_system_instructions = self.tabview.add("System Instructions")
        self.tab_personality = self.tabview.add("Personality")
        self.tab_heartbeat = self.tabview.add("Heartbeat")
        self.tab_user_prefs = self.tabview.add("User Preferences")
        self.tab_ai_prefs = self.tabview.add("AI Preferences")
        self.tab_system_rules = self.tabview.add("System Rules")

        # Create content for each tab
        self.create_prompt_order_tab()
        self.create_editor_tab(self.tab_system_instructions, "system_instructions", "instructions.txt")
        self.create_personality_tab()
        self.create_editor_tab(self.tab_heartbeat, "heartbeat", "config.txt")
        self.create_editor_tab(self.tab_user_prefs, "user_preferences", "tone.txt")
        self.create_editor_tab(self.tab_ai_prefs, "ai_preferences", "verbosity.txt")
        self.create_editor_tab(self.tab_system_rules, "system_rules", "safety.txt")

    def create_prompt_order_tab(self):
        """Creates the UI for the Prompt Build Order tab."""
        for widget in self.tab_prompt_order.winfo_children():
            widget.destroy()
        self.prompt_order_list = DraggableListbox(self.tab_prompt_order, command=self.save_prompt_order)
        self.prompt_order_list.pack(expand=True, fill="both", padx=10, pady=10)
        self.update_prompt_order_list()

    def update_prompt_order_list(self):
        """Populates the draggable list with the current prompt order."""
        self.prompt_order_list.clear()
        prompt_order_path = self.build_prompt_dir / "prompt_order.json"
        order = self._load_json(prompt_order_path)
        if isinstance(order, list):
            for item_name in order:
                # The "path" key is what DraggableListbox expects
                self.prompt_order_list.add_item({"path": item_name, "pinned": False})

    def save_prompt_order(self, new_item_objects: Optional[List[dict]] = None):
        """Saves the new prompt order. Can be called from button (no args) or listbox command (with args)."""
        if new_item_objects is None:
            new_item_objects = self.prompt_order_list.get_item_objects()

        new_order = [item["path"] for item in new_item_objects]
        prompt_order_path = self.build_prompt_dir / "prompt_order.json"
        self._save_json(prompt_order_path, new_order)
        self.parent_app.update_status("Prompt order saved.", LYRN_SUCCESS)

    def create_editor_tab(self, tab, config_key: str, filename: str):
        """Creates a generic editor tab with brackets, content, and save button."""
        for widget in tab.winfo_children():
            widget.destroy()
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        # Store widgets for this tab to access them later
        if not hasattr(self, 'editor_tabs'):
            self.editor_tabs = {}
        self.editor_tabs[config_key] = {}
        widgets = self.editor_tabs[config_key]

        # --- Special UI for the new Heartbeat Tab ---
        if config_key == 'heartbeat':
            self.heartbeat_widgets = {}
            heartbeat_config_path = self.build_prompt_dir / "heartbeat" / "heartbeat_config.json"

            main_frame = ctk.CTkScrollableFrame(tab, fg_color="transparent")
            main_frame.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=10, pady=5)
            main_frame.grid_columnconfigure(0, weight=1)

            self.heartbeat_widgets['enabled_var'] = ctk.BooleanVar()
            enabled_switch = ctk.CTkSwitch(main_frame, text="Enable Heartbeat in System Prompt", variable=self.heartbeat_widgets['enabled_var'])
            enabled_switch.pack(anchor="w", pady=(5, 15))

            ctk.CTkLabel(main_frame, text="Begin Bracket Text").pack(anchor="w")
            self.heartbeat_widgets['begin_bracket_text'] = ctk.CTkTextbox(main_frame, height=30)
            self.heartbeat_widgets['begin_bracket_text'].pack(fill="x", pady=(0, 10))

            ctk.CTkLabel(main_frame, text="Heartbeat Instruction Body").pack(anchor="w")
            self.heartbeat_widgets['body_text'] = ctk.CTkTextbox(main_frame, height=150)
            self.heartbeat_widgets['body_text'].pack(fill="both", expand=True, pady=(0, 10))

            ctk.CTkLabel(main_frame, text="End Bracket Text").pack(anchor="w")
            self.heartbeat_widgets['end_bracket_text'] = ctk.CTkTextbox(main_frame, height=30)
            self.heartbeat_widgets['end_bracket_text'].pack(fill="x", pady=(0, 10))

            ctk.CTkLabel(main_frame, text="Trigger Phrase (for user reference)").pack(anchor="w")
            self.heartbeat_widgets['trigger_text'] = ctk.CTkTextbox(main_frame, height=30)
            self.heartbeat_widgets['trigger_text'].pack(fill="x", pady=(0, 10))

            self.load_heartbeat_config()
            return

        # --- New Generic UI for components with config.json ---
        main_frame = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        main_frame.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=10, pady=5)
        main_frame.grid_columnconfigure(0, weight=1)

        # Toggle Switch
        widgets['toggle_var'] = ctk.BooleanVar(value=self.config.get(config_key, True))
        toggle = ctk.CTkSwitch(
            main_frame,
            text=f"Enable {config_key.replace('_', ' ').title()}",
            variable=widgets['toggle_var'],
            command=lambda: self.toggle_component(config_key, widgets['toggle_var'].get())
        )
        toggle.pack(anchor="w", pady=(5, 15))

        # Begin Bracket
        ctk.CTkLabel(main_frame, text="Begin Bracket").pack(anchor="w")
        widgets['begin_bracket_entry'] = ctk.CTkEntry(main_frame)
        widgets['begin_bracket_entry'].pack(fill="x", pady=(0, 10))

        # Content
        ctk.CTkLabel(main_frame, text="Instructions").pack(anchor="w")
        widgets['content_textbox'] = ctk.CTkTextbox(main_frame, height=200, wrap="word")
        widgets['content_textbox'].pack(fill="both", expand=True, pady=(0, 10))

        # End Bracket
        ctk.CTkLabel(main_frame, text="End Bracket").pack(anchor="w")
        widgets['end_bracket_entry'] = ctk.CTkEntry(main_frame)
        widgets['end_bracket_entry'].pack(fill="x", pady=(0, 10))

        # Load data into the new widgets
        self.load_component_config(config_key)

    def load_component_config(self, config_key: str):
        """Loads data from a component's config.json and content file."""
        widgets = self.editor_tabs[config_key]
        component_dir = self.build_prompt_dir / config_key
        config_path = component_dir / "config.json"

        config = self._load_json(config_path)
        if not config:
            # Fallback for components that might not have a config file yet
            widgets['begin_bracket_entry'].insert("0", f"###{config_key.upper()}_START###")
            widgets['end_bracket_entry'].insert("0", f"###{config_key.upper()}_END###")
            return

        widgets['begin_bracket_entry'].insert("0", config.get("begin_bracket", ""))
        widgets['end_bracket_entry'].insert("0", config.get("end_bracket", ""))

        content_filename = config.get("content_file")
        if content_filename:
            content_path = component_dir / content_filename
            content = self._load_text(content_path)
            widgets['content_textbox'].insert("1.0", content)

    def save_component_config(self, config_key: str):
        """Saves the component's brackets and content."""
        widgets = self.editor_tabs[config_key]
        component_dir = self.build_prompt_dir / config_key
        config_path = component_dir / "config.json"

        config = self._load_json(config_path) or {}

        config["begin_bracket"] = widgets['begin_bracket_entry'].get()
        config["end_bracket"] = widgets['end_bracket_entry'].get()

        self._save_json(config_path, config)

        content_filename = config.get("content_file")
        if content_filename:
            content_path = component_dir / content_filename
            content = widgets['content_textbox'].get("1.0", "end-1c")
            self._save_text(content_path, content)

        self.parent_app.update_status(f"{config_key.title()} settings saved.", LYRN_SUCCESS)

    def create_personality_tab(self):
        """Creates the UI for the Personality tab with trait text boxes."""
        for widget in self.tab_personality.winfo_children():
            widget.destroy()
        self.personality_widgets = {}
        tab = self.tab_personality
        config_key = "personality"

        main_frame = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=10, pady=5)

        # Enable/Disable Toggle
        prompt_order_path = self.build_prompt_dir / "prompt_order.json"
        current_order = self._load_json(prompt_order_path) or []
        is_enabled = config_key in current_order
        toggle_var = ctk.BooleanVar(value=is_enabled)
        toggle_switch = ctk.CTkSwitch(
            main_frame,
            text="Enable Personality Component",
            variable=toggle_var,
            command=lambda: self.toggle_component(config_key, toggle_var.get())
        )
        toggle_switch.pack(anchor="w", pady=(5, 15))
        self.personality_widgets['toggle_var'] = toggle_var

        # Brackets
        ctk.CTkLabel(main_frame, text="Begin Bracket").pack(anchor="w")
        self.personality_widgets['begin_bracket_entry'] = ctk.CTkEntry(main_frame)
        self.personality_widgets['begin_bracket_entry'].pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(main_frame, text="End Bracket").pack(anchor="w")
        self.personality_widgets['end_bracket_entry'] = ctk.CTkEntry(main_frame)
        self.personality_widgets['end_bracket_entry'].pack(fill="x", pady=(0, 10))

        # Traits Frame
        traits_frame = ctk.CTkFrame(main_frame)
        traits_frame.pack(fill="x", expand=True, pady=10)
        self.personality_widgets['traits_frame'] = traits_frame
        self.personality_widgets['trait_entries'] = []

        self.load_personality_config()

    def load_personality_config(self):
        """Loads the personality configuration and populates the UI."""
        config_path = self.build_prompt_dir / "personality" / "config.json"
        config = self._load_json(config_path)
        if not config:
            return

        self.personality_widgets['begin_bracket_entry'].insert("0", config.get("begin_bracket", ""))
        self.personality_widgets['end_bracket_entry'].insert("0", config.get("end_bracket", ""))

        traits = config.get("traits", [])
        for trait_data in traits:
            self.add_trait_widget(trait_data)

    def add_trait_widget(self, trait_data):
        """Adds a widget set for a single trait to the UI."""
        traits_frame = self.personality_widgets['traits_frame']

        trait_frame = ctk.CTkFrame(traits_frame)
        trait_frame.pack(fill="x", pady=5, padx=5)

        # Trait Name and Value
        name_value_frame = ctk.CTkFrame(trait_frame, fg_color="transparent")
        name_value_frame.pack(fill="x", pady=(0, 5))

        ctk.CTkLabel(name_value_frame, text=trait_data.get("name", "Unknown Trait")).pack(side="left", padx=5)

        value_entry = ctk.CTkEntry(name_value_frame, width=80)
        value_entry.insert("0", str(trait_data.get("value", "500")))
        value_entry.pack(side="left", padx=5)

        ctk.CTkLabel(name_value_frame, text="(0-1000)").pack(side="left", padx=5)

        # Instructions Textbox
        instructions_box = ctk.CTkTextbox(trait_frame, height=80)
        instructions_box.insert("1.0", trait_data.get("instructions", ""))
        instructions_box.pack(fill="x", expand=True, padx=5)

        self.personality_widgets['trait_entries'].append({
            "name": trait_data.get("name"),
            "value_entry": value_entry,
            "instructions_box": instructions_box
        })

    def save_personality_config(self):
        """Saves the personality configuration to JSON and the formatted text file."""
        config_path = self.build_prompt_dir / "personality" / "config.json"
        config = self._load_json(config_path) or {}

        # Save brackets
        config["begin_bracket"] = self.personality_widgets['begin_bracket_entry'].get()
        config["end_bracket"] = self.personality_widgets['end_bracket_entry'].get()

        # Save traits and build output text
        output_parts = [config["begin_bracket"]]
        updated_traits = []
        for trait_widget_set in self.personality_widgets['trait_entries']:
            name = trait_widget_set["name"]
            value = trait_widget_set["value_entry"].get()
            instructions = trait_widget_set["instructions_box"].get("1.0", "end-1c")

            # Validate value
            try:
                val_int = int(value)
                if not 0 <= val_int <= 1000:
                    raise ValueError()
                value_str = f"{val_int:04d}"
            except ValueError:
                self.parent_app.update_status(f"Invalid value for {name}. Must be 0-1000.", LYRN_ERROR)
                return

            updated_traits.append({
                "name": name,
                "value": val_int,
                "instructions": instructions
            })

            output_parts.append(f'"{name} = {value_str}"')
            output_parts.append(f'"{instructions}"')

        config["traits"] = updated_traits
        output_parts.append(config["end_bracket"])

        # Save the structured data
        self._save_json(config_path, config)

        # Save the formatted output file
        output_filename = config.get("output_file", "personality.txt")
        output_path = self.build_prompt_dir / "personality" / output_filename
        self._save_text(output_path, "\n\n".join(output_parts))

        self.parent_app.update_status("Personality settings saved.", LYRN_SUCCESS)

    def load_heartbeat_config(self):
        """Loads data from heartbeat_config.json into the UI widgets."""
        heartbeat_config_path = self.build_prompt_dir / "heartbeat" / "heartbeat_config.json"
        config = self._load_json(heartbeat_config_path)
        if not config: return

        self.heartbeat_widgets['enabled_var'].set(config.get("enabled", False))

        self.heartbeat_widgets['begin_bracket_text'].delete("1.0", "end")
        self.heartbeat_widgets['begin_bracket_text'].insert("1.0", config.get("begin_bracket", ""))

        self.heartbeat_widgets['body_text'].delete("1.0", "end")
        self.heartbeat_widgets['body_text'].insert("1.0", config.get("body", ""))

        self.heartbeat_widgets['end_bracket_text'].delete("1.0", "end")
        self.heartbeat_widgets['end_bracket_text'].insert("1.0", config.get("end_bracket", ""))

        self.heartbeat_widgets['trigger_text'].delete("1.0", "end")
        self.heartbeat_widgets['trigger_text'].insert("1.0", config.get("trigger", ""))

    def save_heartbeat_config(self):
        """Saves the current state of the heartbeat UI widgets to the JSON file."""
        heartbeat_config_path = self.build_prompt_dir / "heartbeat" / "heartbeat_config.json"

        config_data = {
            "enabled": self.heartbeat_widgets['enabled_var'].get(),
            "begin_bracket": self.heartbeat_widgets['begin_bracket_text'].get("1.0", "end-1c"),
            "body": self.heartbeat_widgets['body_text'].get("1.0", "end-1c"),
            "end_bracket": self.heartbeat_widgets['end_bracket_text'].get("1.0", "end-1c"),
            "trigger": self.heartbeat_widgets['trigger_text'].get("1.0", "end-1c")
        }

        self._save_json(heartbeat_config_path, config_data)
        self.parent_app.update_status("Heartbeat settings saved.", LYRN_SUCCESS)


    def toggle_component(self, key: str, is_enabled: bool):
        """Adds or removes a component from the prompt_order.json file."""
        current_order = self._load_json(self.prompt_order_path) or []

        if is_enabled:
            if key not in current_order:
                # Add the key back in a sensible position if possible
                # For now, just append it. The user can reorder it.
                current_order.append(key)
        else:
            if key in current_order:
                current_order.remove(key)

        self._save_json(self.prompt_order_path, current_order)
        self.update_prompt_order_list() # Refresh the draggable list
        self.parent_app.update_status(f"{key.title()} {'enabled' if is_enabled else 'disabled'}", LYRN_INFO)

    def toggle_on_top(self):
        """Toggles the always-on-top status of the window."""
        is_on_top = self.on_top_var.get()
        self.attributes("-topmost", is_on_top)



class ThemeBuilderPopup(ThemedPopup):
    """A popup window for creating and editing themes."""
    def __init__(self, parent, theme_manager, language_manager):
        super().__init__(parent=parent.parent_app, theme_manager=theme_manager)
        self.language_manager = language_manager

        self.title("Theme Builder")
        self.geometry("800x650")
        self.minsize(700, 500)

        # self.grab_set() # Removed to make non-modal

        self.create_theme_builder_widgets()
        self.load_selected_theme(self.theme_manager.get_current_theme_name())
        self.preview_theme()
        self.apply_theme()


    def create_theme_builder_widgets(self):
        """Create the theme builder tab UI with an advanced preview."""
        try:
            font = ctk.CTkFont(family="Consolas", size=12)
            title_font = ctk.CTkFont(family="Consolas", size=14, weight="bold")
        except:
            font = ("Consolas", 12)
            title_font = ("Consolas", 14, "bold")

        # Main frame for the builder
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(expand=True, fill="both", padx=20, pady=10)
        main_frame.grid_columnconfigure(0, weight=1)
        main_frame.grid_columnconfigure(1, weight=1)

        # Left side for color pickers
        left_frame = ctk.CTkScrollableFrame(main_frame, label_text="Color Settings")
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        # Right side for preview
        right_frame = ctk.CTkFrame(main_frame)
        right_frame.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        # --- Theme Management ---
        manage_frame = ctk.CTkFrame(left_frame)
        manage_frame.pack(fill="x", padx=10, pady=10)

        self.theme_selector_combo = ctk.CTkComboBox(manage_frame, values=self.theme_manager.get_theme_names(), command=self.load_selected_theme)
        self.theme_selector_combo.pack(side="left", expand=True, fill="x", padx=(0,5))
        Tooltip(self.theme_selector_combo, "Select a theme to edit or delete.")

        delete_button = ctk.CTkButton(manage_frame, text="Delete", width=60, command=self.delete_selected_theme)
        delete_button.pack(side="left")
        Tooltip(delete_button, "Deletes the currently selected theme.")

        # --- Color Pickers ---
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

            # Bind click events to both swatch and label for better UX
            for widget in [color_swatch, hex_label]:
                widget.bind("<Button-1>", lambda e, k=key: self.choose_color(k))

        # --- Buttons ---
        button_frame = ctk.CTkFrame(left_frame)
        button_frame.pack(fill="x", padx=10, pady=10)

        apply_theme_button = ctk.CTkButton(button_frame, text="Apply", font=font, command=self.apply_preview_theme)
        apply_theme_button.pack(side="left", padx=10)
        Tooltip(apply_theme_button, "Apply the current theme settings for preview.")

        save_theme_button = ctk.CTkButton(button_frame, text="Save Theme", font=font, command=self.save_theme)
        save_theme_button.pack(side="right", padx=10)
        Tooltip(save_theme_button, self.parent_app.tooltips.get("save_theme_button", ""))

        # --- Advanced Preview Area ---
        self.preview_frame = ctk.CTkFrame(right_frame, border_width=2)
        self.preview_frame.pack(expand=True, fill="both", padx=10, pady=10)

        ctk.CTkLabel(self.preview_frame, text="Theme Preview", font=title_font).pack(pady=5)

        self.preview_widgets = {}

        # Label
        self.preview_widgets["label"] = ctk.CTkLabel(self.preview_frame, text="This is a label.")
        self.preview_widgets["label"].pack(pady=5, padx=10)

        # Button
        self.preview_widgets["button"] = ctk.CTkButton(self.preview_frame, text="Click Me")
        self.preview_widgets["button"].pack(pady=5, padx=10)

        # Textbox
        self.preview_widgets["textbox"] = ctk.CTkTextbox(self.preview_frame, height=50)
        self.preview_widgets["textbox"].insert("0.0", "This is a textbox for longer text.\nIt can have multiple lines.")
        self.preview_widgets["textbox"].pack(pady=5, padx=10, fill="x")

        # ComboBox
        self.preview_widgets["combobox"] = ctk.CTkComboBox(self.preview_frame, values=["Option 1", "Option 2"])
        self.preview_widgets["combobox"].pack(pady=5, padx=10)

        # ProgressBar
        self.preview_widgets["progressbar"] = ctk.CTkProgressBar(self.preview_frame)
        self.preview_widgets["progressbar"].set(0.7)
        self.preview_widgets["progressbar"].pack(pady=5, padx=10, fill="x")

        # Switch
        self.preview_widgets["switch"] = ctk.CTkSwitch(self.preview_frame, text="A switch")
        self.preview_widgets["switch"].pack(pady=5, padx=10)
        self.preview_widgets["switch"].select()

    def choose_color(self, key):
        """Opens a color chooser and updates the widgets for the given color key."""
        initial_color = self.color_widgets[key]['label'].cget("text")
        picker = CustomColorPickerPopup(self, initial_color=initial_color)
        new_color = picker.get_color()
        if new_color:
            self.color_widgets[key]['label'].configure(text=new_color)
            self.color_widgets[key]['swatch'].configure(fg_color=new_color)
            self.preview_theme()

    def apply_preview_theme(self):
        """Applies the current settings in the theme builder for a live preview."""
        theme_name = self.theme_name_entry.get()
        if not theme_name:
            print("Please enter a theme name to apply a preview.")
            return

        preview_colors = {key: widgets['label'].cget("text") for key, widgets in self.color_widgets.items()}
        self.theme_manager.current_theme_name = f"{theme_name} (Preview)"
        self.theme_manager.current_colors = preview_colors
        self.parent_app.apply_color_theme()
        # No need to apply theme to self, as it's a separate window now
        self.parent_app.update_status(f"Previewing theme: {theme_name}", LYRN_INFO)

    def preview_theme(self):
        """Updates the advanced preview area with the current colors."""
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
        self.preview_widgets["combobox"].configure(fg_color=textbox_bg, text_color=textbox_fg, border_color=border, button_color=primary)
        self.preview_widgets["progressbar"].configure(progress_color=primary)
        self.preview_widgets["switch"].configure(progress_color=accent, text_color=label_text)

    def load_selected_theme(self, theme_name: str):
        """Loads a theme's properties into the editor fields."""
        if not theme_name or theme_name not in self.theme_manager.themes:
            return
        theme_data = self.theme_manager.themes[theme_name]
        self.theme_name_entry.delete(0, "end")
        self.theme_name_entry.insert(0, theme_data.get("name", ""))
        theme_colors = theme_data.get("colors", {})
        for key, widgets in self.color_widgets.items():
            color = theme_colors.get(key, "#ffffff")
            widgets['label'].configure(text=color)
            widgets['swatch'].configure(fg_color=color)
        self.preview_theme()
        self.parent_app.update_status(f"Loaded '{theme_name}' for editing", LYRN_INFO)

    def delete_selected_theme(self):
        """Deletes the currently selected theme after confirmation."""
        from confirmation_dialog import ConfirmationDialog

        theme_name = self.theme_selector_combo.get()
        if not theme_name or theme_name not in self.theme_manager.themes:
            return

        prefs = self.parent_app.settings_manager.ui_settings.get("confirmation_preferences", {})
        if prefs.get("delete_theme"):
            confirmed = True
        else:
            confirmed, dont_ask_again = ConfirmationDialog.show(
                self,
                self.theme_manager,
                title="Confirm Deletion",
                message=f"Are you sure you want to permanently delete the theme '{theme_name}'?"
            )
            if dont_ask_again:
                prefs["delete_theme"] = True
                self.parent_app.settings_manager.ui_settings["confirmation_preferences"] = prefs
                self.parent_app.settings_manager.save_settings()

        if not confirmed:
            self.parent_app.update_status("Theme deletion cancelled", LYRN_WARNING)
            return

        filename = f"{theme_name.lower().replace(' ', '_')}.json"
        filepath = os.path.join(self.theme_manager.themes_dir, filename)
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
                self.theme_manager.load_available_themes()
                new_theme_names = self.theme_manager.get_theme_names()
                self.theme_selector_combo.configure(values=new_theme_names)
                self.parent_app.theme_dropdown.configure(values=new_theme_names)
                safe_theme = new_theme_names[0] if new_theme_names else "LYRN Dark"
                self.theme_selector_combo.set(safe_theme)
                self.parent_app.theme_dropdown.set(safe_theme)
                self.parent_app.on_theme_selected(safe_theme)
                self.parent_app.update_status(f"Theme '{theme_name}' deleted", LYRN_SUCCESS)
            except Exception as e:
                self.parent_app.update_status(f"Error deleting theme: {e}", LYRN_ERROR)
        else:
            self.parent_app.update_status(f"Theme file not found for '{theme_name}'", LYRN_ERROR)

    def save_theme(self):
        """Saves the current theme to a JSON file."""
        theme_name = self.theme_name_entry.get()
        if not theme_name:
            return
        theme_data = {
            "name": theme_name,
            "appearance_mode": "dark",
            "colors": {}
        }
        for key, widgets in self.color_widgets.items():
            theme_data["colors"][key] = widgets['label'].cget("text")
        themes_dir = os.path.join(self.parent_app.SCRIPT_DIR, "themes")
        os.makedirs(themes_dir, exist_ok=True)
        filename = f"{theme_name.lower().replace(' ', '_')}.json"
        filepath = os.path.join(themes_dir, filename)
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(theme_data, f, indent=4)
            self.parent_app.theme_manager.load_available_themes()
            new_theme_names = self.parent_app.theme_manager.get_theme_names()
            self.parent_app.theme_dropdown.configure(values=new_theme_names)
            self.theme_selector_combo.configure(values=new_theme_names)
            self.parent_app.theme_dropdown.set(theme_name)
            self.theme_selector_combo.set(theme_name)
            self.parent_app.update_status(f"Theme '{theme_name}' saved", LYRN_SUCCESS)
        except Exception as e:
            print(f"Error saving theme: {e}")
            self.parent_app.update_status("Error saving theme", LYRN_ERROR)


class ComingSoonPopup(ThemedPopup):
    """A simple popup to inform the user that a feature is not yet available."""
    def __init__(self, parent, theme_manager):
        super().__init__(parent=parent, theme_manager=theme_manager)

        self.title("Coming Soon")
        self.geometry("300x150")
        self.grab_set() # Make it modal

        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(expand=True, fill="both", padx=20, pady=20)

        message_label = ctk.CTkLabel(
            main_frame,
            text="This feature is unfinished and will be coming soon.",
            wraplength=260,
            justify="center"
        )
        message_label.pack(expand=True)

        ok_button = ctk.CTkButton(main_frame, text="OK", command=self.destroy)
        ok_button.pack(pady=(10, 0))

        self.apply_theme()


class DaySchedulePopup(ThemedPopup):
    """A popup to manage schedules for a specific day."""
    def __init__(self, parent, theme_manager, language_manager, scheduler_manager, automation_controller: AutomationController, date_obj: datetime, calendar_refresh_callback):
        super().__init__(parent=parent, theme_manager=theme_manager)
        self.language_manager = language_manager
        self.scheduler_manager = scheduler_manager
        self.automation_controller = automation_controller
        self.date_obj = date_obj
        self.calendar_refresh_callback = calendar_refresh_callback
        self.selected_schedule_id = None

        self.title(f"Schedules for {self.date_obj.strftime('%Y-%m-%d')}")
        self.geometry("700x500")
        self.grab_set()

        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Left pane for existing schedules
        left_frame = ctk.CTkFrame(self)
        left_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        left_frame.grid_rowconfigure(0, weight=1)
        left_frame.grid_columnconfigure(0, weight=1)

        self.schedule_list_frame = ctk.CTkScrollableFrame(left_frame, label_text=f"Scheduled Jobs")
        self.schedule_list_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        delete_button = ctk.CTkButton(left_frame, text="Delete Selected", command=self.delete_schedule)
        delete_button.grid(row=1, column=0, padx=5, pady=10)

        # Right pane for adding new schedules
        right_frame = ctk.CTkFrame(self)
        right_frame.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)

        ctk.CTkLabel(right_frame, text="Add New Schedule").pack(pady=5)

        # Job selection
        ctk.CTkLabel(right_frame, text="Job:").pack(anchor="w", padx=10)
        job_names = list(self.automation_controller.job_definitions.keys())
        self.job_selector = ctk.CTkComboBox(right_frame, values=job_names if job_names else ["No jobs available"])
        if job_names:
            self.job_selector.set(job_names[0])
        self.job_selector.pack(fill="x", padx=10, pady=(0, 10))

        # Time inputs
        time_frame = ctk.CTkFrame(right_frame)
        time_frame.pack(fill="x", padx=10, pady=10)

        self.time_entries = {}
        for unit in ["Hour", "Minute", "Second"]:
            ctk.CTkLabel(time_frame, text=unit).pack(side="left", padx=5)
            entry = ctk.CTkEntry(time_frame, width=60)
            entry.pack(side="left", padx=5)
            self.time_entries[unit] = entry

        schedule_button = ctk.CTkButton(right_frame, text="Schedule Job", command=self.schedule_job)
        schedule_button.pack(pady=20)

        self.refresh_schedule_list()
        self.apply_theme()

    def refresh_schedule_list(self):
        for widget in self.schedule_list_frame.winfo_children():
            widget.destroy()

        self.selected_schedule_id = None
        all_schedules = self.scheduler_manager.get_all_schedules()
        day_schedules = [s for s in all_schedules if s.scheduled_datetime.date() == self.date_obj.date()]

        if not day_schedules:
            ctk.CTkLabel(self.schedule_list_frame, text="No jobs scheduled for this day.").pack()
            return

        for schedule in sorted(day_schedules, key=lambda s: s.scheduled_datetime):
            time_str = schedule.scheduled_datetime.strftime('%H:%M:%S.%f')[:-3]
            label_text = f"{time_str} - {schedule.job_name}"
            label = ctk.CTkLabel(self.schedule_list_frame, text=label_text, anchor="w", cursor="hand2")
            label.pack(fill="x", padx=5, pady=2)
            label.bind("<Button-1>", lambda e, s_id=schedule.id, l=label: self.on_schedule_selected(s_id, l))

    def on_schedule_selected(self, schedule_id: str, selected_label: ctk.CTkLabel):
        self.selected_schedule_id = schedule_id
        for child in self.schedule_list_frame.winfo_children():
            if isinstance(child, ctk.CTkLabel):
                child.configure(fg_color="transparent")
        selected_label.configure(fg_color=self.theme_manager.get_color("accent"))

    def schedule_job(self):
        job_name = self.job_selector.get()
        if "No jobs available" in job_name:
            # Show error
            return

        try:
            hour = int(self.time_entries["Hour"].get() or 0)
            minute = int(self.time_entries["Minute"].get() or 0)
            second = int(self.time_entries["Second"].get() or 0)

            scheduled_dt = self.date_obj.replace(hour=hour, minute=minute, second=second, microsecond=0)

            self.scheduler_manager.add_schedule(job_name, scheduled_dt)
            self.refresh_schedule_list()
            self.calendar_refresh_callback()

        except ValueError:
            # Show error popup for invalid time
            print("Invalid time format")
            pass

    def delete_schedule(self):
        if not self.selected_schedule_id:
            # Show error
            return

        self.scheduler_manager.delete_schedule(self.selected_schedule_id)
        self.refresh_schedule_list()
        self.calendar_refresh_callback()


class JobBuilderPopup(ThemedPopup):
    """A popup for creating and editing jobs."""
    def __init__(self, parent, automation_controller: AutomationController, theme_manager: ThemeManager, language_manager: LanguageManager, refresh_callback, job_name: Optional[str] = None):
        super().__init__(parent=parent, theme_manager=theme_manager)
        self.automation_controller = automation_controller
        self.language_manager = language_manager
        self.refresh_callback = refresh_callback
        self.editing_job_name = job_name

        # This needs to be fixed in the next step. It currently gets a string, but will get a dict.
        job_definition = self.automation_controller.job_definitions.get(self.editing_job_name) if self.editing_job_name else {}
        if isinstance(job_definition, str): # Temp backwards compatibility
            self.job_data = {"instructions": job_definition, "trigger": ""}
        else:
            self.job_data = job_definition or {}


        self.title("Job Editor" if self.editing_job_name else "Create New Job")
        self.geometry("700x600")
        self.grab_set()

        self.create_widgets()
        if self.job_data:
            self.load_job_data()

        self.apply_theme()

    def create_widgets(self):
        """Create the UI elements for the popup."""
        main_frame = ctk.CTkScrollableFrame(self)
        main_frame.pack(fill="both", expand=True, padx=15, pady=15)
        main_frame.grid_columnconfigure(0, weight=1)

        # Job Name
        ctk.CTkLabel(main_frame, text="Job Name").pack(anchor="w")
        self.job_name_entry = ctk.CTkEntry(main_frame)
        self.job_name_entry.pack(fill="x", pady=(0, 10))
        if self.editing_job_name:
            self.job_name_entry.insert(0, self.editing_job_name)
            self.job_name_entry.configure(state="disabled")

        # Job Instructions
        ctk.CTkLabel(main_frame, text="Job Instructions (for build_prompt)").pack(anchor="w")
        self.job_instructions_text = ctk.CTkTextbox(main_frame, height=200)
        self.job_instructions_text.pack(fill="both", pady=(0, 10), expand=True)

        # Trigger Prompt
        ctk.CTkLabel(main_frame, text="Trigger Prompt (for LLM execution)").pack(anchor="w")
        self.trigger_prompt_text = ctk.CTkTextbox(main_frame, height=100)
        self.trigger_prompt_text.pack(fill="both", pady=(0, 10), expand=True)

        # Save Button
        save_button = ctk.CTkButton(self, text="Save Job", command=self.save_job)
        save_button.pack(pady=15, padx=15)

    def load_job_data(self):
        """Populates the fields with data from an existing job."""
        if not self.job_data:
            return
        self.job_instructions_text.insert("1.0", self.job_data.get("instructions", ""))
        self.trigger_prompt_text.insert("1.0", self.job_data.get("trigger", ""))

    def save_job(self):
        """Saves the job data to the central jobs.json file."""
        job_name = self.job_name_entry.get().strip()
        instructions = self.job_instructions_text.get("1.0", "end-1c").strip()
        trigger = self.trigger_prompt_text.get("1.0", "end-1c").strip()

        if not all([job_name, instructions, trigger]):
            self.parent.parent_app.update_status("Job Name, Instructions, and Trigger must be filled.", LYRN_ERROR)
            return

        # Call the new method in the automation controller to handle saving.
        self.automation_controller.save_job_definition(job_name, instructions, trigger)

        self.parent.parent_app.update_status(f"Job '{job_name}' saved.", LYRN_SUCCESS)

        if self.refresh_callback:
            self.refresh_callback()

        self.destroy()

class JobWatcherPopup(ThemedPopup):
    """A popup window for managing watcher jobs."""
    def __init__(self, parent, automation_controller: AutomationController, theme_manager: ThemeManager, language_manager: LanguageManager, cycle_manager: CycleManager):
        super().__init__(parent=parent, theme_manager=theme_manager)
        self.automation_controller = automation_controller
        self.language_manager = language_manager
        self.cycle_manager = cycle_manager
        self.selected_job_name = None
        self.job_checkboxes = {}
        self.selected_cycle_name = None
        self.selected_trigger_name = None
        self.reflection_job_output = ""

        self.active_jobs_index_path = Path(SCRIPT_DIR) / "build_prompt" / "active_jobs" / "_index.json"
        self.active_jobs_dir = self.active_jobs_index_path.parent
        self._ensure_active_jobs_index()

        self.title("Automation")
        self.geometry("900x700")

        # Main tab view
        self.tabview = ctk.CTkTabview(self, width=850, height=600)
        self.tabview.pack(fill="both", expand=True, padx=20, pady=10)

        self.tab_viewer = self.tabview.add("Job Viewer")
        self.tab_scheduler = self.tabview.add("Scheduler")
        self.tab_reflection = self.tabview.add("Reflection Cycle")
        self.tab_cycle_builder = self.tabview.add("Cycle Builder")

        self.create_viewer_tab()
        self.create_scheduler_tab()
        self.create_reflection_tab()
        self.create_cycle_builder_tab()

        self.refresh_job_list()
        self.tabview.set("Job Viewer")
        self.apply_theme()

    def create_viewer_tab(self):
        self.tab_viewer.grid_columnconfigure(0, weight=1)
        self.tab_viewer.grid_rowconfigure(0, weight=1)

        viewer_content_frame = ctk.CTkFrame(self.tab_viewer)
        viewer_content_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        viewer_content_frame.grid_columnconfigure(0, weight=1)
        viewer_content_frame.grid_rowconfigure(0, weight=1)

        self.job_list_frame = ctk.CTkScrollableFrame(viewer_content_frame, label_text="Available Jobs")
        self.job_list_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        button_frame = ctk.CTkFrame(viewer_content_frame)
        button_frame.grid(row=0, column=1, sticky="ns", padx=5, pady=5)

        new_button = ctk.CTkButton(button_frame, text="New Job", command=self.open_new_job_popup)
        new_button.pack(padx=10, pady=10, anchor="n")

        edit_button = ctk.CTkButton(button_frame, text="Edit", command=self.edit_selected_job)
        edit_button.pack(padx=10, pady=10, anchor="n")

        run_button = ctk.CTkButton(button_frame, text="Run", command=self.run_selected_job)
        run_button.pack(padx=10, pady=10, anchor="n")

        delete_button = ctk.CTkButton(button_frame, text="Delete", command=self.delete_selected_job)
        delete_button.pack(padx=10, pady=10, anchor="n")

    def open_new_job_popup(self):
        """Opens the job builder popup for creating a new job."""
        popup = JobBuilderPopup(
            parent=self,
            automation_controller=self.automation_controller,
            theme_manager=self.theme_manager,
            language_manager=self.language_manager,
            refresh_callback=self.refresh_job_list
        )
        popup.focus()

    def edit_selected_job(self):
        """Opens the job builder popup for editing the selected job."""
        if not self.selected_job_name:
            self.parent_app.update_status("No job selected to edit.", LYRN_WARNING)
            return

        popup = JobBuilderPopup(
            parent=self,
            automation_controller=self.automation_controller,
            theme_manager=self.theme_manager,
            language_manager=self.language_manager,
            refresh_callback=self.refresh_job_list,
            job_name=self.selected_job_name
        )
        popup.focus()

    def create_cycle_builder_tab(self):
        """Creates the UI for the Cycle Builder tab."""
        self.tab_cycle_builder.grid_columnconfigure(0, weight=1)
        self.tab_cycle_builder.grid_columnconfigure(1, weight=2)
        self.tab_cycle_builder.grid_rowconfigure(1, weight=1)

        # --- Left Pane: Cycle Management and Trigger List ---
        left_pane = ctk.CTkFrame(self.tab_cycle_builder)
        left_pane.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=10, pady=10)
        left_pane.grid_rowconfigure(1, weight=1)
        left_pane.grid_columnconfigure(0, weight=1)

        # Cycle selection and management
        cycle_manage_frame = ctk.CTkFrame(left_pane)
        cycle_manage_frame.grid(row=0, column=0, sticky="ew", padx=5, pady=5)
        self.cycle_selector = ctk.CTkComboBox(cycle_manage_frame, values=[], command=self.on_cycle_selected)
        self.cycle_selector.pack(side="left", expand=True, fill="x", padx=(0, 5))
        new_cycle_button = ctk.CTkButton(cycle_manage_frame, text="New", width=50, command=self.new_cycle)
        new_cycle_button.pack(side="left", padx=(0, 5))
        delete_cycle_button = ctk.CTkButton(cycle_manage_frame, text="Delete", width=60, command=self.delete_cycle)
        delete_cycle_button.pack(side="left")

        # Draggable list for triggers
        self.trigger_list = DraggableListbox(left_pane, command=self.on_trigger_list_reorder)
        self.trigger_list.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)

        # --- Right Pane: Trigger Editor ---
        right_pane = ctk.CTkFrame(self.tab_cycle_builder)
        right_pane.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=10, pady=10)
        right_pane.grid_rowconfigure(1, weight=1)
        right_pane.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(right_pane, text="Trigger Editor").grid(row=0, column=0, pady=5)

        editor_frame = ctk.CTkFrame(right_pane)
        editor_frame.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        editor_frame.grid_columnconfigure(0, weight=1)
        editor_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(editor_frame, text="Trigger Name:").pack(anchor="w", padx=5)
        self.trigger_name_entry = ctk.CTkEntry(editor_frame)
        self.trigger_name_entry.pack(fill="x", padx=5, pady=(0, 10))

        ctk.CTkLabel(editor_frame, text="Trigger Prompt:").pack(anchor="w", padx=5)
        self.trigger_prompt_text = ctk.CTkTextbox(editor_frame, wrap="word")
        self.trigger_prompt_text.pack(expand=True, fill="both", padx=5, pady=(0, 10))

        # Buttons for the editor
        button_frame = ctk.CTkFrame(right_pane)
        button_frame.grid(row=2, column=0, sticky="ew", padx=5, pady=5)
        add_trigger_button = ctk.CTkButton(button_frame, text="Add/Update Trigger", command=self.save_trigger)
        add_trigger_button.pack(side="left", padx=5)
        delete_trigger_button = ctk.CTkButton(button_frame, text="Delete Trigger", command=self.delete_trigger)
        delete_trigger_button.pack(side="right", padx=5)

        self.refresh_cycle_list()

    def refresh_cycle_list(self):
        """Refreshes the list of available cycles in the combobox."""
        cycle_names = self.cycle_manager.get_cycle_names()
        self.cycle_selector.configure(values=cycle_names if cycle_names else [""])
        if cycle_names:
            self.cycle_selector.set(cycle_names[0])
            self.on_cycle_selected(cycle_names[0])
        else:
            self.cycle_selector.set("")
            self.on_cycle_selected(None)

    def on_cycle_selected(self, cycle_name: Optional[str]):
        """Callback when a cycle is selected from the dropdown."""
        self.selected_cycle_name = cycle_name
        self.refresh_trigger_list()
        self.clear_trigger_editor()

    def refresh_trigger_list(self):
        """Refreshes the draggable list of triggers for the selected cycle."""
        self.trigger_list.clear()
        if self.selected_cycle_name:
            cycle_data = self.cycle_manager.get_cycle(self.selected_cycle_name)
            if cycle_data:
                for trigger in cycle_data.get("triggers", []):
                    # DraggableListbox expects a dict with a "path" key for the text
                    self.trigger_list.add_item({"path": trigger["name"], "pinned": False})

    def on_trigger_list_reorder(self, new_item_objects: List[dict]):
        """Saves the new order of triggers when the list is reordered."""
        if not self.selected_cycle_name:
            return

        cycle_data = self.cycle_manager.get_cycle(self.selected_cycle_name)
        if not cycle_data:
            return

        # Create a map of trigger names to their prompts to preserve them
        prompt_map = {t["name"]: t["prompt"] for t in cycle_data.get("triggers", [])}

        new_triggers = []
        for item in new_item_objects:
            trigger_name = item["path"]
            if trigger_name in prompt_map:
                new_triggers.append({"name": trigger_name, "prompt": prompt_map[trigger_name]})

        self.cycle_manager.update_cycle_triggers(self.selected_cycle_name, new_triggers)
        self.parent_app.update_status(f"Trigger order for '{self.selected_cycle_name}' saved.", LYRN_SUCCESS)

    def new_cycle(self):
        """Prompts for a new cycle name and creates it."""
        dialog = ctk.CTkInputDialog(text="Enter name for the new cycle:", title="New Cycle")
        name = dialog.get_input()
        if name:
            if self.cycle_manager.create_cycle(name):
                self.parent_app.update_status(f"Cycle '{name}' created.", LYRN_SUCCESS)
                self.refresh_cycle_list()
                self.cycle_selector.set(name)
            else:
                self.parent_app.update_status(f"Cycle '{name}' already exists.", LYRN_ERROR)

    def delete_cycle(self):
        """Deletes the selected cycle after confirmation."""
        if not self.selected_cycle_name:
            self.parent_app.update_status("No cycle selected to delete.", LYRN_WARNING)
            return

        from confirmation_dialog import ConfirmationDialog
        confirmed, _ = ConfirmationDialog.show(
            self, self.theme_manager,
            title="Confirm Deletion",
            message=f"Are you sure you want to permanently delete the cycle '{self.selected_cycle_name}'?"
        )
        if confirmed:
            self.cycle_manager.delete_cycle(self.selected_cycle_name)
            self.parent_app.update_status(f"Cycle '{self.selected_cycle_name}' deleted.", LYRN_SUCCESS)
            self.refresh_cycle_list()

    def save_trigger(self):
        """Saves the trigger from the editor to the selected cycle."""
        if not self.selected_cycle_name:
            self.parent_app.update_status("No cycle selected to add a trigger to.", LYRN_WARNING)
            return

        trigger_name = self.trigger_name_entry.get().strip()
        trigger_prompt = self.trigger_prompt_text.get("1.0", "end-1c").strip()

        if not trigger_name or not trigger_prompt:
            self.parent_app.update_status("Trigger name and prompt cannot be empty.", LYRN_ERROR)
            return

        self.cycle_manager.add_trigger_to_cycle(self.selected_cycle_name, trigger_name, trigger_prompt)
        self.parent_app.update_status(f"Trigger '{trigger_name}' saved to cycle '{self.selected_cycle_name}'.", LYRN_SUCCESS)
        self.refresh_trigger_list()
        self.clear_trigger_editor()

    def delete_trigger(self):
        """Deletes the selected trigger from the current cycle."""
        selected_item_frame = self.trigger_list.get_selected_item()
        if not selected_item_frame:
            self.parent_app.update_status("No trigger selected to delete.", LYRN_WARNING)
            return

        # The text is on a label which is a child of the frame
        trigger_name = selected_item_frame.winfo_children()[1].cget("text")

        from confirmation_dialog import ConfirmationDialog
        confirmed, _ = ConfirmationDialog.show(
            self, self.theme_manager,
            title="Confirm Deletion",
            message=f"Are you sure you want to delete the trigger '{trigger_name}' from this cycle?"
        )
        if confirmed:
            self.cycle_manager.delete_trigger_from_cycle(self.selected_cycle_name, trigger_name)
            self.parent_app.update_status(f"Trigger '{trigger_name}' deleted.", LYRN_SUCCESS)
            self.refresh_trigger_list()


    def clear_trigger_editor(self):
        """Clears the trigger name and prompt fields."""
        self.trigger_name_entry.delete(0, "end")
        self.trigger_prompt_text.delete("1.0", "end")

    def _ensure_active_jobs_index(self):
        """Ensures the active jobs directory and index file exist."""
        self.active_jobs_dir.mkdir(parents=True, exist_ok=True)
        if not self.active_jobs_index_path.exists():
            with open(self.active_jobs_index_path, 'w', encoding='utf-8') as f:
                json.dump([], f)

    def _load_active_jobs(self) -> List[str]:
        """Loads the list of active (pinned) job names from the index file."""
        if not self.active_jobs_index_path.exists():
            return []
        try:
            with open(self.active_jobs_index_path, 'r', encoding='utf-8') as f:
                # The index contains file paths, e.g., "active_jobs/some_job/instructions.txt"
                paths = json.load(f)
            job_names = []
            if isinstance(paths, list):
                for path_str in paths:
                    # Extract the job name, which is the directory name
                    parts = Path(path_str).parts
                    if len(parts) > 1:
                        job_names.append(parts[-2])
            return job_names
        except (json.JSONDecodeError, IOError):
            return []

    def toggle_job_pin(self, job_name: str):
        """Handles the logic when a job's pin checkbox is toggled."""
        is_active = self.job_checkboxes[job_name][1].get()
        active_jobs = self._load_active_jobs()

        if is_active:
            if job_name not in active_jobs:
                active_jobs.append(job_name)
        else:
            if job_name in active_jobs:
                active_jobs.remove(job_name)

        self.update_active_job_files(active_jobs)
        self.parent_app.update_status(f"Job '{job_name}' toggled {'on' if is_active else 'off'}.", LYRN_INFO)

    def update_active_job_files(self, active_job_names: List[str]):
        """
        Synchronizes the files in the build_prompt/active_jobs directory
        with the list of active jobs.
        """
        # Ensure the active jobs directory exists
        self.active_jobs_dir.mkdir(parents=True, exist_ok=True)

        # Remove files/dirs for jobs that are no longer active
        for item in self.active_jobs_dir.iterdir():
            if item.name == "_index.json":
                continue
            if item.is_dir() and item.name not in active_job_names:
                print(f"Removing inactive job directory: {item.name}")
                shutil.rmtree(item)

        # Add files for newly activated jobs
        for job_name in active_job_names:
            job_definition = self.automation_controller.job_definitions.get(job_name)
            if not job_definition:
                print(f"Warning: Could not find definition for active job '{job_name}'.")
                continue

            # Instructions are now in a dictionary
            instructions = job_definition.get("instructions", "")
            if not instructions:
                print(f"Warning: Job '{job_name}' has no instructions to write to build_prompt.")
                continue

            job_dir = self.active_jobs_dir / job_name
            job_dir.mkdir(exist_ok=True)

            instructions_path = job_dir / "instructions.txt"
            with open(instructions_path, 'w', encoding='utf-8') as f:
                f.write(instructions) # Write verbatim instructions as requested

        # Update the local index for the active_jobs directory
        active_job_files = []
        for job_name in active_job_names:
            # We assume the file is always named instructions.txt inside the job's folder
            relative_path = Path("active_jobs") / job_name / "instructions.txt"
            active_job_files.append(str(relative_path).replace("\\", "/"))

        local_index_path = self.active_jobs_dir / "_index.json"
        try:
            with open(local_index_path, 'w', encoding='utf-8') as f:
                json.dump(sorted(active_job_files), f, indent=2)
            print("Active jobs index updated.")
        except IOError as e:
            print(f"Error writing active jobs index: {e}")

        # Trigger a rebuild of the master prompt
        if hasattr(self.parent_app, 'snapshot_loader'):
            self.parent_app.snapshot_loader.generate_master_index()

    def create_reflection_tab(self):
        """Creates the UI for the Reflection Cycle tab."""
        reflection_frame = ctk.CTkScrollableFrame(self.tab_reflection)
        reflection_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # Job selection for reflection
        job_selection_frame = ctk.CTkFrame(reflection_frame, fg_color="transparent")
        job_selection_frame.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(job_selection_frame, text="Job to Reflect On:").pack(anchor="w")
        job_names = list(self.automation_controller.job_definitions.keys())
        self.reflection_job_selector = ctk.CTkComboBox(job_selection_frame, values=job_names if job_names else ["No jobs available"])
        if job_names:
            self.reflection_job_selector.set(job_names[0])
        self.reflection_job_selector.pack(side="left", expand=True, fill="x")

        run_job_button = ctk.CTkButton(job_selection_frame, text="Run Job", command=self.run_job_for_reflection)
        run_job_button.pack(side="left", padx=5)

        # Reflection Instructions
        ctk.CTkLabel(reflection_frame, text="Reflection Instructions").pack(anchor="w")
        self.reflection_instructions_text = ctk.CTkTextbox(reflection_frame, height=100)
        self.reflection_instructions_text.pack(fill="x", pady=(0, 10), expand=True)

        # Gold-Standard Example
        ctk.CTkLabel(reflection_frame, text="Gold-Standard Example").pack(anchor="w")
        self.reflection_gold_standard_text = ctk.CTkTextbox(reflection_frame, height=100)
        self.reflection_gold_standard_text.pack(fill="x", pady=(0, 10), expand=True)

        # Reflection Iterations
        iterations_frame = ctk.CTkFrame(reflection_frame, fg_color="transparent")
        iterations_frame.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(iterations_frame, text="Reflection Iterations:").pack(side="left")
        self.reflection_iterations_entry = ctk.CTkEntry(iterations_frame, width=50)
        self.reflection_iterations_entry.pack(side="left", padx=5)

        # Reflection Batch Size
        batch_size_frame = ctk.CTkFrame(reflection_frame, fg_color="transparent")
        batch_size_frame.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(batch_size_frame, text="Reflect after N outputs:").pack(side="left")
        self.reflection_batch_size_entry = ctk.CTkEntry(batch_size_frame, width=50)
        self.reflection_batch_size_entry.pack(side="left", padx=5)

        # Checkboxes
        self.reflection_auto_update_prompt_var = ctk.BooleanVar()
        self.reflection_auto_continue_var = ctk.BooleanVar()

        auto_update_checkbox = ctk.CTkCheckBox(reflection_frame, text="Automatically update job prompt", variable=self.reflection_auto_update_prompt_var)
        auto_update_checkbox.pack(anchor="w", pady=5)

        auto_continue_checkbox = ctk.CTkCheckBox(reflection_frame, text="Auto-continue job after prompt update", variable=self.reflection_auto_continue_var)
        auto_continue_checkbox.pack(anchor="w", pady=5)

        # Manual Trigger Button
        manual_trigger_button = ctk.CTkButton(reflection_frame, text="Run Reflection Manually", command=self.run_reflection_manually)
        manual_trigger_button.pack(pady=20)

    def run_job_for_reflection(self):
        """Runs the selected job and stores its output for reflection."""
        selected_job_name = self.reflection_job_selector.get()
        if "No jobs available" in selected_job_name:
            self.parent_app.update_status("No job selected to run.", LYRN_WARNING)
            return

        trigger_prompt = self.automation_controller.get_job_trigger(selected_job_name)
        if not trigger_prompt:
            self.parent_app.update_status(f"Could not load trigger for job '{selected_job_name}'.", LYRN_ERROR)
            return

        self.parent_app.update_status(f"Running job '{selected_job_name}' for reflection...", LYRN_INFO)

        # This will block, which is ok for this button.
        response = self.parent_app.get_response_for_job(trigger_prompt)

        self.reflection_job_output = response

        self.parent_app.update_status(f"Job '{selected_job_name}' finished. Output is ready for reflection.", LYRN_SUCCESS)

    def run_reflection_manually(self):
        """Triggers the reflection process manually based on the UI settings."""
        instructions = self.reflection_instructions_text.get("1.0", "end-1c")
        gold_standard = self.reflection_gold_standard_text.get("1.0", "end-1c")
        iterations = self.reflection_iterations_entry.get()
        auto_update = self.reflection_auto_update_prompt_var.get()
        auto_continue = self.reflection_auto_continue_var.get()
        selected_job_for_reflection = self.reflection_job_selector.get()

        if not instructions:
            self.parent_app.update_status("Reflection instructions are required.", LYRN_WARNING)
            return

        if "No jobs available" in selected_job_for_reflection:
            self.parent_app.update_status("No job selected for reflection.", LYRN_WARNING)
            return

        job_output = self.reflection_job_output
        if not job_output.strip():
            self.parent_app.update_status("Job output is empty. Run a job first.", LYRN_WARNING)
            return

        # The 'reflection_cycle_job' expects these arguments.
        job_args = {
            "instructions": instructions,
            "gold_standard": gold_standard,
            "job_output": job_output,
            "iterations": iterations,
            "auto_update": auto_update,
            "auto_continue": auto_continue,
            "original_job_name": selected_job_for_reflection or "manual" # Track which job this reflection is for
        }

        # Add the reflection job to the queue
        self.parent_app.automation_controller.add_job(
            name="reflection_cycle_job",
            args=job_args
        )

        self.parent_app.update_status(f"Reflection job for '{job_args['original_job_name']}' added to the queue.", LYRN_SUCCESS)

    def create_scheduler_tab(self):
        """Creates the UI for the Scheduler tab."""
        self.current_date = datetime.now()

        # Main frame for the calendar
        calendar_frame = ctk.CTkFrame(self.tab_scheduler)
        calendar_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Header for navigation
        header_frame = ctk.CTkFrame(calendar_frame)
        header_frame.pack(fill="x", pady=5)

        prev_month_button = ctk.CTkButton(header_frame, text="<", width=30, command=self.prev_month)
        prev_month_button.pack(side="left", padx=10)

        self.month_year_label = ctk.CTkLabel(header_frame, text="", font=("", 16, "bold"))
        self.month_year_label.pack(side="left", expand=True)

        next_month_button = ctk.CTkButton(header_frame, text=">", width=30, command=self.next_month)
        next_month_button.pack(side="right", padx=10)

        # Frame for the calendar grid
        self.grid_frame = ctk.CTkFrame(calendar_frame)
        self.grid_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.update_calendar()

    def update_calendar(self):
        """Renders the calendar for the current month and year."""
        for widget in self.grid_frame.winfo_children():
            widget.destroy()

        self.month_year_label.configure(text=self.current_date.strftime('%B %Y'))

        cal = calendar.Calendar(firstweekday=calendar.SUNDAY)
        month_days = cal.monthdatescalendar(self.current_date.year, self.current_date.month)

        # Get theme colors
        tm = self.theme_manager
        label_text_color = tm.get_color("label_text")
        button_color = tm.get_color("primary")
        today_color = tm.get_color("info")
        other_month_color = tm.get_color("border_color")
        schedule_border_color = tm.get_color("success")

        # Day headers
        days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        for i, day in enumerate(days):
            ctk.CTkLabel(self.grid_frame, text=day, font=("", 10, "bold"), text_color=label_text_color).grid(row=0, column=i, padx=1, pady=1)
            self.grid_frame.grid_columnconfigure(i, weight=1)

        # Get all schedules to check for highlights
        all_schedules = self.parent_app.scheduler_manager.get_all_schedules()
        scheduled_dates = {s.scheduled_datetime.date() for s in all_schedules}

        for r, week in enumerate(month_days):
            self.grid_frame.grid_rowconfigure(r + 1, weight=1)
            for c, date_obj in enumerate(week):
                is_today = (date_obj == datetime.now().date())
                has_schedule = date_obj in scheduled_dates

                day_button = ctk.CTkButton(
                    self.grid_frame,
                    text=str(date_obj.day),
                    command=lambda d=date_obj: self.open_day_schedule_popup(d)
                )

                # Set default button color
                day_button.configure(fg_color=button_color)

                if date_obj.month != self.current_date.month:
                    day_button.configure(fg_color=other_month_color)
                elif is_today:
                    day_button.configure(fg_color=today_color)

                if has_schedule:
                    day_button.configure(border_width=2, border_color=schedule_border_color)

                day_button.grid(row=r + 1, column=c, sticky="nsew", padx=1, pady=1)

    def prev_month(self):
        self.current_date = self.current_date.replace(day=1) - timedelta(days=1)
        self.update_calendar()

    def next_month(self):
        _, num_days = calendar.monthrange(self.current_date.year, self.current_date.month)
        self.current_date = self.current_date.replace(day=1) + timedelta(days=num_days)
        self.update_calendar()

    def open_day_schedule_popup(self, date_obj):
        """Opens the popup for managing a specific day's schedule."""
        # We need to pass a datetime object, not just a date
        dt_obj = datetime.combine(date_obj, datetime.min.time())

        popup = DaySchedulePopup(
            parent=self,
            theme_manager=self.theme_manager,
            language_manager=self.language_manager,
            scheduler_manager=self.parent_app.scheduler_manager,
            automation_controller=self.parent_app.automation_controller,
            date_obj=dt_obj,
            calendar_refresh_callback=self.update_calendar
        )
        popup.focus()

    def refresh_job_list(self):
        for widget in self.job_list_frame.winfo_children():
            widget.destroy()

        self.job_checkboxes.clear()
        active_jobs = self._load_active_jobs()
        all_jobs = self.automation_controller.job_definitions
        self.selected_job_name = None

        if not all_jobs:
            ctk.CTkLabel(self.job_list_frame, text="No watcher jobs created yet.").pack()
            return

        for job_name in sorted(all_jobs.keys()):
            var = ctk.BooleanVar(value=(job_name in active_jobs))

            # A frame to hold the checkbox and the selection label
            job_frame = ctk.CTkFrame(self.job_list_frame, fg_color="transparent")
            job_frame.pack(fill="x", padx=5, pady=2)

            checkbox = ctk.CTkCheckBox(
                job_frame,
                text=job_name,
                variable=var,
                command=lambda name=job_name: self.toggle_job_pin(name)
            )
            checkbox.pack(side="left")

            # We bind the selection for edit/delete to the frame itself
            job_frame.bind("<Button-1>", lambda e, name=job_name: self.on_job_selected(name))

            self.job_checkboxes[job_name] = (checkbox, var, job_frame)

    def on_job_selected(self, job_name):
        self.selected_job_name = job_name
        for name, (_, _, frame) in self.job_checkboxes.items():
            # Highlight the entire frame for selection
            if name == job_name:
                frame.configure(fg_color=self.theme_manager.get_color("accent"))
            else:
                frame.configure(fg_color="transparent")

    def run_selected_job(self):
        if not self.selected_job_name:
            self.parent_app.update_status("No job selected to run.", LYRN_WARNING)
            return

        trigger_prompt = self.automation_controller.get_job_trigger(self.selected_job_name)
        if trigger_prompt:
            self.parent_app.insert_job_text(trigger_prompt)
            self.parent_app.update_status(f"Manual job trigger loaded: {self.selected_job_name}", LYRN_ACCENT)
        else:
            self.parent_app.update_status(f"Could not load trigger for job '{self.selected_job_name}'.", LYRN_ERROR)

    def delete_selected_job(self):
        """Deletes the selected job after confirmation."""
        from confirmation_dialog import ConfirmationDialog

        if not self.selected_job_name:
            self.parent_app.update_status("No job selected to delete.", LYRN_WARNING)
            return

        job_name = self.selected_job_name

        prefs = self.parent_app.settings_manager.ui_settings.get("confirmation_preferences", {})
        if prefs.get("delete_watcher_job"):
            confirmed = True
        else:
            confirmed, dont_ask_again = ConfirmationDialog.show(
                self,
                self.theme_manager,
                title="Confirm Deletion",
                message=f"Are you sure you want to permanently delete the job '{job_name}'?"
            )
            if dont_ask_again:
                prefs["delete_watcher_job"] = True
                self.parent_app.settings_manager.ui_settings["confirmation_preferences"] = prefs
                self.parent_app.settings_manager.save_settings()

        if confirmed:
            job_path = self.automation_controller.job_definitions_path / f"{job_name}.txt"
            try:
                if job_path.exists():
                    job_path.unlink()
                # Also remove from the in-memory dictionary
                if job_name in self.automation_controller.job_definitions:
                    del self.automation_controller.job_definitions[job_name]

                self.parent_app.update_status(f"Job '{job_name}' deleted.", LYRN_SUCCESS)
                self.refresh_job_list()
            except Exception as e:
                self.parent_app.update_status(f"Error deleting job file: {e}", LYRN_ERROR)
        else:
            self.parent_app.update_status("Deletion cancelled.", LYRN_INFO)

    def select_output_path(self):
        path = filedialog.askdirectory(title="Select Output Directory")
        if path:
            self.output_path_label.configure(text=path)


class AffordancePopup(ThemedPopup):
    """A popup window for managing internal affordances with dynamic UI."""
    def __init__(self, parent, affordance_manager: AffordanceManager, theme_manager: ThemeManager, language_manager: LanguageManager):
        super().__init__(parent=parent, theme_manager=theme_manager)
        self.affordance_manager = affordance_manager
        self.language_manager = language_manager
        self.selected_affordance_name = None
        self.editing_affordance_name = None

        # --- UI Widgets ---
        self.editor_widgets = {}
        self.system_action_frames = {}
        self.system_action_widgets = {}

        self.title("Affordance Editor")
        self.geometry("800x600")

        self.tabview = ctk.CTkTabview(self, width=750, height=500)
        self.tabview.pack(fill="both", expand=True, padx=20, pady=10)

        self.tab_viewer = self.tabview.add("Affordance Viewer")
        self.tab_editor = self.tabview.add("Affordance Editor")

        self.create_viewer_tab()
        self.create_editor_tab()

        self.refresh_affordance_list()
        self.tabview.set("Affordance Viewer")
        self.apply_theme()

    def create_viewer_tab(self):
        self.tab_viewer.grid_columnconfigure(0, weight=1)
        self.tab_viewer.grid_rowconfigure(0, weight=1)

        viewer_content_frame = ctk.CTkFrame(self.tab_viewer)
        viewer_content_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        viewer_content_frame.grid_columnconfigure(0, weight=1)
        viewer_content_frame.grid_rowconfigure(0, weight=1)

        self.affordance_list_frame = ctk.CTkScrollableFrame(viewer_content_frame, label_text="Available Affordances")
        self.affordance_list_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        button_frame = ctk.CTkFrame(viewer_content_frame)
        button_frame.grid(row=0, column=1, sticky="ns", padx=5, pady=5)

        edit_button = ctk.CTkButton(button_frame, text="Edit", command=self.edit_selected_affordance)
        edit_button.pack(padx=10, pady=10, anchor="n")

        delete_button = ctk.CTkButton(button_frame, text="Delete", command=self.delete_selected_affordance)
        delete_button.pack(padx=10, pady=10, anchor="n")

        new_button = ctk.CTkButton(button_frame, text="New", command=self.new_affordance)
        new_button.pack(padx=10, pady=10, anchor="n")

    def refresh_affordance_list(self):
        for widget in self.affordance_list_frame.winfo_children():
            widget.destroy()

        all_affordances = self.affordance_manager.get_all_affordances()
        self.selected_affordance_name = None

        if not all_affordances:
            ctk.CTkLabel(self.affordance_list_frame, text="No affordances created yet.").pack()
            return

        for affordance in sorted(all_affordances, key=lambda a: a.name):
            label = ctk.CTkLabel(self.affordance_list_frame, text=affordance.name, anchor="w", cursor="hand2")
            label.pack(fill="x", padx=10, pady=2)
            label.bind("<Button-1>", lambda e, name=affordance.name: self.on_affordance_selected(name))

    def on_affordance_selected(self, name):
        self.selected_affordance_name = name
        for child in self.affordance_list_frame.winfo_children():
            if isinstance(child, ctk.CTkLabel):
                if child.cget("text") == name:
                    child.configure(fg_color=self.theme_manager.get_color("accent"))
                else:
                    child.configure(fg_color="transparent")

    def edit_selected_affordance(self):
        if not self.selected_affordance_name:
            self.parent_app.update_status("No affordance selected to edit.", LYRN_WARNING)
            return

        affordance = self.affordance_manager.get_affordance(self.selected_affordance_name)
        if not affordance:
            self.parent_app.update_status(f"Affordance '{self.selected_affordance_name}' not found.", LYRN_ERROR)
            return

        self.clear_builder_fields()
        self.editing_affordance_name = affordance.name

        # --- Populate common fields ---
        self.editor_widgets["name_entry"].insert(0, affordance.name)
        self.editor_widgets["name_entry"].configure(state="disabled")
        self.editor_widgets["type_selector"].set(affordance.type)

        # --- Populate type-specific fields ---
        if affordance.type == "text_parser":
            self.editor_widgets["start_trigger_entry"].insert(0, affordance.params.get("start_trigger", ""))
            self.editor_widgets["end_trigger_entry"].insert(0, affordance.params.get("end_trigger", ""))
            self.editor_widgets["output_path_label"].configure(text=affordance.params.get("output_path", "No directory selected"))
            self.editor_widgets["output_filename_entry"].insert(0, affordance.params.get("output_filename", ""))

        elif affordance.type == "system_action":
            action = affordance.params.get("action", "")
            self.system_action_widgets["action_selector"].set(action)

            target = affordance.params.get("target", "")
            self.system_action_widgets["target_entry"].insert(0, target)

            action_params = affordance.params.get("params", {})
            if action == "send_keys":
                self.system_action_widgets["send_keys_keys_entry"].insert(0, action_params.get("keys", ""))
                self.system_action_widgets["send_keys_delay_entry"].insert(0, str(action_params.get("delay", "0.0")))
            elif action in ["click", "move_mouse", "window_resize"]:
                self.system_action_widgets["x_entry"].insert(0, str(action_params.get("x", "")))
                self.system_action_widgets["y_entry"].insert(0, str(action_params.get("y", "")))
                if action == "window_resize":
                    self.system_action_widgets["width_entry"].insert(0, str(action_params.get("width", "")))
                    self.system_action_widgets["height_entry"].insert(0, str(action_params.get("height", "")))

        # Switch to editor tab and update UI
        self.on_type_selected(affordance.type)
        if affordance.type == "system_action":
            self.on_system_action_selected(action)
        self.tabview.set("Affordance Editor")

    def delete_selected_affordance(self):
        from confirmation_dialog import ConfirmationDialog
        if not self.selected_affordance_name:
            self.parent_app.update_status("No affordance selected to delete.", LYRN_WARNING)
            return

        affordance_name = self.selected_affordance_name
        prefs = self.parent_app.settings_manager.ui_settings.get("confirmation_preferences", {})
        if prefs.get("delete_affordance"):
            confirmed = True
        else:
            confirmed, dont_ask_again = ConfirmationDialog.show(
                self, self.theme_manager,
                title="Confirm Deletion",
                message=f"Are you sure you want to permanently delete the affordance '{affordance_name}'?"
            )
            if dont_ask_again:
                prefs["delete_affordance"] = True
                self.parent_app.settings_manager.ui_settings["confirmation_preferences"] = prefs
                self.parent_app.settings_manager.save_settings()

        if confirmed:
            self.affordance_manager.delete_affordance(affordance_name)
            self.parent_app.update_status(f"Affordance '{affordance_name}' deleted.", LYRN_SUCCESS)
            self.refresh_affordance_list()
        else:
            self.parent_app.update_status("Deletion cancelled.", LYRN_INFO)

    def new_affordance(self):
        self.clear_builder_fields()
        self.tabview.set("Affordance Editor")

    def clear_builder_fields(self):
        self.editing_affordance_name = None
        self.editor_widgets["name_entry"].configure(state="normal")
        self.editor_widgets["name_entry"].delete(0, "end")
        self.editor_widgets["type_selector"].set("text_parser")

        # Clear text_parser fields
        self.editor_widgets["start_trigger_entry"].delete(0, "end")
        self.editor_widgets["end_trigger_entry"].delete(0, "end")
        self.editor_widgets["output_path_label"].configure(text="No directory selected")
        self.editor_widgets["output_filename_entry"].delete(0, "end")

        # Clear system_action fields
        self.system_action_widgets["action_selector"].set("open_app")
        self.system_action_widgets["target_entry"].delete(0, "end")
        self.system_action_widgets["send_keys_keys_entry"].delete(0, "end")
        self.system_action_widgets["send_keys_delay_entry"].delete(0, "end")
        self.system_action_widgets["x_entry"].delete(0, "end")
        self.system_action_widgets["y_entry"].delete(0, "end")
        self.system_action_widgets["width_entry"].delete(0, "end")
        self.system_action_widgets["height_entry"].delete(0, "end")

        self.on_type_selected("text_parser")

    def create_editor_tab(self):
        editor_frame = ctk.CTkScrollableFrame(self.tab_editor)
        editor_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # --- Common Fields ---
        ctk.CTkLabel(editor_frame, text="Affordance Name").pack(anchor="w")
        self.editor_widgets["name_entry"] = ctk.CTkEntry(editor_frame)
        self.editor_widgets["name_entry"].pack(fill="x", pady=(0, 10))
        Tooltip(self.editor_widgets["name_entry"], "A unique name for this affordance.")

        ctk.CTkLabel(editor_frame, text="Affordance Type").pack(anchor="w")
        self.editor_widgets["type_selector"] = ctk.CTkComboBox(
            editor_frame,
            values=["text_parser", "system_action"],
            command=self.on_type_selected
        )
        self.editor_widgets["type_selector"].pack(fill="x", pady=(0, 15))
        self.editor_widgets["type_selector"].set("text_parser")

        # --- Frame for Text Parser ---
        self.editor_widgets["text_parser_frame"] = ctk.CTkFrame(editor_frame, fg_color="transparent")
        self.editor_widgets["text_parser_frame"].pack(fill="x", expand=True)

        ctk.CTkLabel(self.editor_widgets["text_parser_frame"], text="Start Trigger").pack(anchor="w")
        self.editor_widgets["start_trigger_entry"] = ctk.CTkEntry(self.editor_widgets["text_parser_frame"])
        self.editor_widgets["start_trigger_entry"].pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(self.editor_widgets["text_parser_frame"], text="End Trigger").pack(anchor="w")
        self.editor_widgets["end_trigger_entry"] = ctk.CTkEntry(self.editor_widgets["text_parser_frame"])
        self.editor_widgets["end_trigger_entry"].pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(self.editor_widgets["text_parser_frame"], text="Output Path").pack(anchor="w")
        path_frame = ctk.CTkFrame(self.editor_widgets["text_parser_frame"], fg_color="transparent")
        path_frame.pack(fill="x", pady=(0, 10))
        self.editor_widgets["output_path_label"] = ctk.CTkLabel(path_frame, text="No directory selected", anchor="w")
        self.editor_widgets["output_path_label"].pack(side="left", expand=True, fill="x")
        select_path_button = ctk.CTkButton(path_frame, text="Select...", width=80, command=self.select_output_path)
        select_path_button.pack(side="right")

        ctk.CTkLabel(self.editor_widgets["text_parser_frame"], text="Output Filename").pack(anchor="w")
        self.editor_widgets["output_filename_entry"] = ctk.CTkEntry(self.editor_widgets["text_parser_frame"])
        self.editor_widgets["output_filename_entry"].pack(fill="x", pady=(0, 10))

        # --- Frame for System Action ---
        self.editor_widgets["system_action_frame"] = ctk.CTkFrame(editor_frame, fg_color="transparent")
        # Packed/unpacked in on_type_selected

        ctk.CTkLabel(self.editor_widgets["system_action_frame"], text="Action").pack(anchor="w")
        action_values = ["open_app", "send_keys", "click", "move_mouse", "window_focus", "window_resize"]
        self.system_action_widgets["action_selector"] = ctk.CTkComboBox(self.editor_widgets["system_action_frame"], values=action_values, command=self.on_system_action_selected)
        self.system_action_widgets["action_selector"].pack(fill="x", pady=(0, 10))
        self.system_action_widgets["action_selector"].set("open_app")

        ctk.CTkLabel(self.editor_widgets["system_action_frame"], text="Target (App Name or Window Title)").pack(anchor="w")
        self.system_action_widgets["target_entry"] = ctk.CTkEntry(self.editor_widgets["system_action_frame"])
        self.system_action_widgets["target_entry"].pack(fill="x", pady=(0, 15))

        # --- Parameter Frames for each System Action ---
        self.create_system_action_param_frames(self.editor_widgets["system_action_frame"])

        # --- Save Button ---
        save_button = ctk.CTkButton(self.tab_editor, text="Save Affordance", command=self.save_affordance)
        save_button.pack(pady=20)

        # Initial UI state
        self.on_type_selected("text_parser")

    def create_system_action_param_frames(self, parent_frame):
        # Frame for send_keys
        sk_frame = ctk.CTkFrame(parent_frame, fg_color="transparent")
        ctk.CTkLabel(sk_frame, text="Keys to Send:").pack(anchor="w")
        self.system_action_widgets["send_keys_keys_entry"] = ctk.CTkEntry(sk_frame)
        self.system_action_widgets["send_keys_keys_entry"].pack(fill="x", pady=(0, 5))
        ctk.CTkLabel(sk_frame, text="Delay (seconds):").pack(anchor="w")
        self.system_action_widgets["send_keys_delay_entry"] = ctk.CTkEntry(sk_frame)
        self.system_action_widgets["send_keys_delay_entry"].pack(fill="x", pady=(0, 5))
        self.system_action_frames["send_keys"] = sk_frame

        # Frame for click, move_mouse, window_resize (coordinates)
        coords_frame = ctk.CTkFrame(parent_frame, fg_color="transparent")
        ctk.CTkLabel(coords_frame, text="X Coordinate:").pack(anchor="w")
        self.system_action_widgets["x_entry"] = ctk.CTkEntry(coords_frame)
        self.system_action_widgets["x_entry"].pack(fill="x", pady=(0, 5))
        ctk.CTkLabel(coords_frame, text="Y Coordinate:").pack(anchor="w")
        self.system_action_widgets["y_entry"] = ctk.CTkEntry(coords_frame)
        self.system_action_widgets["y_entry"].pack(fill="x", pady=(0, 5))
        self.system_action_frames["click"] = coords_frame
        self.system_action_frames["move_mouse"] = coords_frame

        # Frame for window_resize (size)
        resize_frame = ctk.CTkFrame(parent_frame, fg_color="transparent")
        # It shares the coords_frame, so we just need to add width/height
        ctk.CTkLabel(resize_frame, text="Width:").pack(anchor="w")
        self.system_action_widgets["width_entry"] = ctk.CTkEntry(resize_frame)
        self.system_action_widgets["width_entry"].pack(fill="x", pady=(0, 5))
        ctk.CTkLabel(resize_frame, text="Height:").pack(anchor="w")
        self.system_action_widgets["height_entry"] = ctk.CTkEntry(resize_frame)
        self.system_action_widgets["height_entry"].pack(fill="x", pady=(0, 5))
        # This frame will be packed alongside the coords_frame for resize action
        self.system_action_frames["window_resize"] = resize_frame


    def on_type_selected(self, selected_type: str):
        if selected_type == "text_parser":
            self.editor_widgets["text_parser_frame"].pack(fill="x", expand=True)
            self.editor_widgets["system_action_frame"].pack_forget()
        elif selected_type == "system_action":
            self.editor_widgets["text_parser_frame"].pack_forget()
            self.editor_widgets["system_action_frame"].pack(fill="x", expand=True)
            self.on_system_action_selected(self.system_action_widgets["action_selector"].get())
        else:
            self.editor_widgets["text_parser_frame"].pack_forget()
            self.editor_widgets["system_action_frame"].pack_forget()

    def on_system_action_selected(self, selected_action: str):
        # Hide all parameter frames first
        for frame in self.system_action_frames.values():
            frame.pack_forget()

        # Show the relevant frame(s)
        if selected_action == "send_keys":
            self.system_action_frames["send_keys"].pack(fill="x", expand=True, pady=5)
        elif selected_action in ["click", "move_mouse"]:
            self.system_action_frames["click"].pack(fill="x", expand=True, pady=5)
        elif selected_action == "window_resize":
            # Show both coordinate and size frames
            self.system_action_frames["click"].pack(fill="x", expand=True, pady=5)
            self.system_action_frames["window_resize"].pack(fill="x", expand=True, pady=5)

    def select_output_path(self):
        path = filedialog.askdirectory(title="Select Output Directory for Affordance")
        if path:
            self.editor_widgets["output_path_label"].configure(text=path)

    def save_affordance(self):
        name = self.editor_widgets["name_entry"].get().strip()
        aff_type = self.editor_widgets["type_selector"].get()
        params = {}

        if not name:
            self.parent_app.update_status("Affordance Name is required.", LYRN_ERROR)
            return

        if self.editing_affordance_name is None and name in self.affordance_manager.affordances:
            self.parent_app.update_status(f"Affordance name '{name}' already exists.", LYRN_ERROR)
            return

        if aff_type == "text_parser":
            params = {
                "start_trigger": self.editor_widgets["start_trigger_entry"].get(),
                "end_trigger": self.editor_widgets["end_trigger_entry"].get(),
                "output_path": self.editor_widgets["output_path_label"].cget("text"),
                "output_filename": self.editor_widgets["output_filename_entry"].get()
            }
            if not all(params.values()) or params["output_path"] == "No directory selected":
                 self.parent_app.update_status("All fields must be filled for text_parser.", LYRN_ERROR)
                 return

        elif aff_type == "system_action":
            action = self.system_action_widgets["action_selector"].get()
            target = self.system_action_widgets["target_entry"].get()
            action_params = {}

            params["action"] = action
            params["target"] = target

            if action == "open_app":
                if not target:
                    self.parent_app.update_status("Target application path is required for open_app.", LYRN_ERROR)
                    return
            elif action == "send_keys":
                action_params["keys"] = self.system_action_widgets["send_keys_keys_entry"].get()
                try:
                    action_params["delay"] = float(self.system_action_widgets["send_keys_delay_entry"].get() or 0.0)
                except ValueError:
                    self.parent_app.update_status("Invalid delay value for send_keys.", LYRN_ERROR)
                    return
            elif action in ["click", "move_mouse", "window_resize"]:
                try:
                    x = self.system_action_widgets["x_entry"].get()
                    y = self.system_action_widgets["y_entry"].get()
                    if x: action_params["x"] = int(x)
                    if y: action_params["y"] = int(y)

                    if action == "window_resize":
                        width = self.system_action_widgets["width_entry"].get()
                        height = self.system_action_widgets["height_entry"].get()
                        if width: action_params["width"] = int(width)
                        if height: action_params["height"] = int(height)
                except ValueError:
                    self.parent_app.update_status("Invalid coordinate/size value.", LYRN_ERROR)
                    return

            params["params"] = action_params

        affordance = Affordance(name=name, type=aff_type, params=params)
        self.affordance_manager.add_affordance(affordance)
        self.parent_app.update_status(f"Affordance '{name}' saved.", LYRN_SUCCESS)
        self.refresh_affordance_list()
        self.clear_builder_fields()
        self.tabview.set("Affordance Viewer")


class TasksGoalsPopup(ThemedPopup):
    """A popup window for managing tasks and goals."""
    def __init__(self, parent, theme_manager: ThemeManager, language_manager: LanguageManager):
        super().__init__(parent=parent, theme_manager=theme_manager)
        self.language_manager = language_manager
        self.tasks_dir = Path(SCRIPT_DIR) / "build_prompt" / "tasks"
        self.goals_dir = Path(SCRIPT_DIR) / "build_prompt" / "goals"
        self.selected_item = {"tasks": None, "goals": None}

        self.title("Tasks and Goals Manager")
        self.geometry("800x600")

        self.tabview = ctk.CTkTabview(self, width=750, height=500)
        self.tabview.pack(fill="both", expand=True, padx=20, pady=10)

        self.tab_tasks = self.tabview.add("Tasks")
        self.tab_goals = self.tabview.add("Goals")

        self.create_task_goal_tab(self.tab_tasks, "tasks")
        self.create_task_goal_tab(self.tab_goals, "goals")

        self.apply_theme()

    def _update_index(self, item_type: str):
        """Updates the _index.json file for the given item type (tasks or goals)."""
        data_dir = self.tasks_dir if item_type == "tasks" else self.goals_dir
        index_path = data_dir / "_index.json"
        try:
            # The local index just needs the filenames.
            files = sorted([p.name for p in data_dir.glob("*.txt")])
            with open(index_path, 'w', encoding='utf-8') as f:
                json.dump(files, f, indent=2)
            print(f"GUI updated index file: {index_path}")
        except Exception as e:
            print(f"GUI Error updating index file for {item_type}: {e}")

    def create_task_goal_tab(self, tab, item_type: str):
        """Creates the content for a single tab (either tasks or goals)."""
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_columnconfigure(1, weight=2)
        tab.grid_rowconfigure(0, weight=1)

        left_frame = ctk.CTkFrame(tab)
        left_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        left_frame.grid_rowconfigure(0, weight=1)
        left_frame.grid_columnconfigure(0, weight=1)

        list_frame = ctk.CTkScrollableFrame(left_frame, label_text=f"Available {item_type.capitalize()}")
        list_frame.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=5, pady=5)
        setattr(self, f"{item_type}_list_frame", list_frame)

        new_button = ctk.CTkButton(left_frame, text="New", command=lambda: self.add_item(item_type))
        new_button.grid(row=1, column=0, padx=5, pady=10, sticky="ew")

        delete_button = ctk.CTkButton(left_frame, text="Delete", command=lambda: self.delete_item(item_type))
        delete_button.grid(row=1, column=1, padx=5, pady=10, sticky="ew")

        right_frame = ctk.CTkFrame(tab)
        right_frame.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        right_frame.grid_rowconfigure(1, weight=1)
        right_frame.grid_columnconfigure(0, weight=1)

        selected_label = ctk.CTkLabel(right_frame, text=f"No {item_type[:-1]} selected", anchor="w")
        selected_label.grid(row=0, column=0, padx=10, pady=5, sticky="ew")
        setattr(self, f"selected_{item_type}_label", selected_label)

        content_textbox = ctk.CTkTextbox(right_frame, wrap="word")
        content_textbox.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        setattr(self, f"{item_type}_content_textbox", content_textbox)

        save_button = ctk.CTkButton(right_frame, text="Save Changes", command=lambda: self.save_item_content(item_type))
        save_button.grid(row=2, column=0, padx=10, pady=10, sticky="e")

        self.refresh_list(item_type)

    def refresh_list(self, item_type: str):
        list_frame = getattr(self, f"{item_type}_list_frame")
        for widget in list_frame.winfo_children():
            widget.destroy()

        data_dir = self.tasks_dir if item_type == "tasks" else self.goals_dir
        data_dir.mkdir(parents=True, exist_ok=True)

        # Also ensure the index file exists on refresh
        self._update_index(item_type)

        files = sorted(p.name for p in data_dir.glob("*.txt"))

        for filename in files:
            label = ctk.CTkLabel(list_frame, text=filename, anchor="w", cursor="hand2")
            label.pack(fill="x", padx=5, pady=2)
            label.bind("<Button-1>", lambda e, name=filename, type=item_type: self.on_item_selected(name, type))

    def on_item_selected(self, item_name: str, item_type: str):
        self.selected_item[item_type] = item_name
        selected_label = getattr(self, f"selected_{item_type}_label")
        selected_label.configure(text=item_name)

        content_textbox = getattr(self, f"{item_type}_content_textbox")
        data_dir = self.tasks_dir if item_type == "tasks" else self.goals_dir
        filepath = data_dir / item_name

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            content_textbox.delete("1.0", "end")
            content_textbox.insert("1.0", content)
        except Exception as e:
            print(f"Error reading {item_type} file: {e}")
            content_textbox.delete("1.0", "end")
            content_textbox.insert("1.0", f"Error loading file: {e}")

    def add_item(self, item_type: str):
        dialog = ctk.CTkInputDialog(text=f"Enter name for the new {item_type[:-1]}:", title=f"New {item_type[:-1].capitalize()}")
        name = dialog.get_input()
        if not name:
            return

        filename = f"{name}.txt"
        data_dir = self.tasks_dir if item_type == "tasks" else self.goals_dir
        filepath = data_dir / filename

        if filepath.exists():
            self.parent_app.update_status(f"{item_type[:-1].capitalize()} '{name}' already exists.", LYRN_ERROR)
            return

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write("")
            self.refresh_list(item_type)
            # self._update_index(item_type) is called by refresh_list
            self.parent_app.update_status(f"Created new {item_type[:-1]} '{name}'.", LYRN_SUCCESS)
        except Exception as e:
            self.parent_app.update_status(f"Error creating file: {e}", LYRN_ERROR)

    def delete_item(self, item_type: str):
        from confirmation_dialog import ConfirmationDialog

        selected_filename = self.selected_item.get(item_type)
        if not selected_filename:
            self.parent_app.update_status(f"No {item_type[:-1]} selected to delete.", LYRN_WARNING)
            return

        confirmed, _ = ConfirmationDialog.show(
            self, self.theme_manager,
            title="Confirm Deletion",
            message=f"Are you sure you want to permanently delete '{selected_filename}'?"
        )
        if not confirmed:
            return

        data_dir = self.tasks_dir if item_type == "tasks" else self.goals_dir
        filepath = data_dir / selected_filename

        try:
            os.remove(filepath)
            self.refresh_list(item_type)
            # self._update_index(item_type) is called by refresh_list
            getattr(self, f"{item_type}_content_textbox").delete("1.0", "end")
            getattr(self, f"selected_{item_type}_label").configure(text=f"No {item_type[:-1]} selected")
            self.selected_item[item_type] = None
            self.parent_app.update_status(f"Deleted '{selected_filename}'.", LYRN_SUCCESS)
        except Exception as e:
            self.parent_app.update_status(f"Error deleting file: {e}", LYRN_ERROR)

    def save_item_content(self, item_type: str):
        selected_filename = self.selected_item.get(item_type)
        if not selected_filename:
            self.parent_app.update_status(f"No {item_type[:-1]} selected to save.", LYRN_WARNING)
            return

        content_textbox = getattr(self, f"{item_type}_content_textbox")
        content = content_textbox.get("1.0", "end-1c")

        data_dir = self.tasks_dir if item_type == "tasks" else self.goals_dir
        filepath = data_dir / selected_filename

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            self.parent_app.update_status(f"Saved changes to '{selected_filename}'.", LYRN_SUCCESS)
        except Exception as e:
            self.parent_app.update_status(f"Error saving file: {e}", LYRN_ERROR)


class EpisodicMemoryPopup(ThemedPopup):
    """A popup window for managing episodic memory entries."""
    def __init__(self, parent, episodic_memory_manager: EpisodicMemoryManager, theme_manager: ThemeManager, language_manager: LanguageManager):
        super().__init__(parent=parent, theme_manager=theme_manager)
        self.parent_app = parent
        self.episodic_memory_manager = episodic_memory_manager
        self.language_manager = language_manager
        self.selected_entries = []
        self.entry_widgets = [] # To keep track of created widgets

        self.title("Episodic Memory")
        self.geometry("950x750")
        self.minsize(700, 500)

        self.create_widgets()
        self.load_entries()
        self.apply_theme()

    def create_widgets(self):
        """Create the UI elements for the popup."""
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Top frame for search and controls
        top_frame = ctk.CTkFrame(self)
        top_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=10)

        self.search_entry = ctk.CTkEntry(top_frame, placeholder_text="Search memories...")
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.search_entry.bind("<KeyRelease>", self.filter_entries)

        # Main frame for the list
        self.list_frame = ctk.CTkScrollableFrame(self)
        self.list_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=0)

        # Bottom frame for actions
        bottom_frame = ctk.CTkFrame(self)
        bottom_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=10)

        add_to_context_button = ctk.CTkButton(bottom_frame, text="Add Selected to Context", command=self.add_selected_to_context)
        add_to_context_button.pack(side="right")

    def load_entries(self):
        """Loads all entries from the manager and populates the list."""
        # Clear existing widgets
        for widget in self.list_frame.winfo_children():
            widget.destroy()
        self.entry_widgets.clear()

        all_entries = self.episodic_memory_manager.get_all_entries()

        for entry_data in all_entries:
            self.create_entry_widget(entry_data)

    def create_entry_widget(self, entry_data: dict):
        """Creates a single entry widget in the list."""
        entry_frame = ctk.CTkFrame(self.list_frame, border_width=1)
        entry_frame.pack(fill="x", padx=5, pady=(2, 3))

        # Checkbox for selection
        var = ctk.BooleanVar(value=(entry_data['filepath'] in self.selected_entries))
        checkbox = ctk.CTkCheckBox(entry_frame, text="", variable=var, width=28,
                                   command=lambda path=entry_data['filepath'], v=var: self.toggle_selection(path, v))
        checkbox.pack(side="left", padx=5)

        # Main content of the entry
        content_frame = ctk.CTkFrame(entry_frame, fg_color="transparent")
        content_frame.pack(side="left", fill="x", expand=True, pady=4)

        summary_heading = entry_data.get('summary_heading', 'No summary heading')
        try:
            # Attempt to parse ISO 8601 timestamp
            dt_obj = datetime.fromisoformat(entry_data.get('time', ''))
            timestamp = dt_obj.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            timestamp = entry_data.get('time', 'Invalid time')

        mode = entry_data.get('mode', 'N/A')
        links = entry_data.get('links', '')

        # Top line: Summary heading and timestamp
        top_line_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
        top_line_frame.pack(fill="x")

        summary_label = ctk.CTkLabel(top_line_frame, text=summary_heading, anchor="w", font=ctk.CTkFont(weight="bold"))
        summary_label.pack(side="left", padx=5)

        timestamp_label = ctk.CTkLabel(top_line_frame, text=timestamp, anchor="e")
        timestamp_label.pack(side="right", padx=5)

        # Bottom line: Mode and tags
        bottom_line_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
        bottom_line_frame.pack(fill="x")

        mode_label = ctk.CTkLabel(bottom_line_frame, text=f"Mode: {mode}", anchor="w")
        mode_label.pack(side="left", padx=5)

        if links:
            tags_label = ctk.CTkLabel(bottom_line_frame, text=f"Tags: {links}", anchor="w", text_color="gray")
            tags_label.pack(side="left", padx=5)

        self.entry_widgets.append((entry_frame, entry_data))

    def toggle_selection(self, filepath: str, var: ctk.BooleanVar):
        """Adds or removes an entry's filepath from the selection list."""
        if var.get():
            if filepath not in self.selected_entries:
                self.selected_entries.append(filepath)
        else:
            if filepath in self.selected_entries:
                self.selected_entries.remove(filepath)

    def add_selected_to_context(self):
        """Calls the manager to add the content of selected entries to the review file."""
        if not self.selected_entries:
            self.parent_app.update_status("No entries selected.", LYRN_WARNING)
            return

        self.episodic_memory_manager.add_to_chat_review(self.selected_entries)
        self.parent_app.update_status(f"Added {len(self.selected_entries)} entries to chat_review.txt", LYRN_SUCCESS)

        # Clear selection and reset checkboxes
        self.selected_entries.clear()
        self.filter_entries()

    def filter_entries(self, event=None):
        """Filters the displayed entries based on the search term."""
        search_term = self.search_entry.get().lower()

        for widget, data in self.entry_widgets:
            if not search_term:
                widget.pack(fill="x", padx=5, pady=(2, 3))
                continue

            searchable_content = (
                data.get('summary_heading', '') + ' ' +
                data.get('summary', '') + ' ' +
                str(data.get('keywords', '')) + ' ' +
                str(data.get('topics', '')) + ' ' +
                data.get('input', '') + ' ' +
                data.get('output', '')
            ).lower()

            if search_term in searchable_content:
                widget.pack(fill="x", padx=5, pady=(2, 3))
            else:
                widget.pack_forget()


class MemoryPopup(ThemedPopup):
    """A popup window for managing different types of memory."""
    def __init__(self, parent, theme_manager: ThemeManager, language_manager: LanguageManager):
        super().__init__(parent=parent, theme_manager=theme_manager)
        self.parent_app = parent
        self.language_manager = language_manager

        self.title("Memory Manager")
        self.geometry("400x200")
        self.minsize(300, 150)

        self.create_widgets()
        self.apply_theme()

    def create_widgets(self):
        """Create the UI elements for the popup."""
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Main tab view
        tabview = ctk.CTkTabview(self)
        tabview.pack(fill="both", expand=True, padx=10, pady=10)

        tab_episodic = tabview.add("Episodic Memory")
        tab_topic = tabview.add("Topic Index")

        # Populate Episodic Tab
        episodic_button = ctk.CTkButton(tab_episodic, text="Open Episodic Memory", command=self.parent_app.open_episodic_memory_popup)
        episodic_button.pack(expand=True, padx=20, pady=20)

        # Populate Topic Tab
        topic_button = ctk.CTkButton(tab_topic, text="Open Topic Index", command=self.parent_app.open_topic_index_popup)
        topic_button.pack(expand=True, padx=20, pady=20)


class LyrnAIInterface(ctk.CTkToplevel):
    """Main LYRN-AI interface with enhanced features"""

    def __init__(self, master, log_queue: queue.Queue):
        super().__init__(master)

        self.log_queue = log_queue

        # --- Phase 1: Immediate, Non-Blocking UI Setup ---
        self.llm = None
        self.is_thinking = False
        self.stop_generation = False
        self.stream_queue = queue.Queue()

        # Initialize only the managers essential for the initial UI
        self.settings_manager = SettingsManager()
        self.theme_manager = ThemeManager()

        # Perform system checks on startup
        system_checker = SystemChecker(self.settings_manager)
        system_checker.check_and_create_folders()
        missing_files = system_checker.check_essential_files()

        self.language_manager = LanguageManager(language=self.settings_manager.ui_settings.get("language", "en"))
        self.episodic_memory_manager = EpisodicMemoryManager()
        self.current_font_size = self.settings_manager.ui_settings.get("font_size", 12)

        # Initialize other managers to None. They will be loaded in the background.
        self.snapshot_loader = None
        self.delta_manager = None
        self.automation_controller = None
        self.metrics = None
        self.chat_logger = None
        self.affordance_manager = None
        self.scheduler_manager = None
        self.cycle_manager = None
        self.resource_monitor = None

        # Set taskbar icon
        try:
            ICON_PATH = os.path.join(SCRIPT_DIR, "favicon.ico")
            if os.path.exists(ICON_PATH):
                icon = ImageTk.PhotoImage(Image.open(ICON_PATH))
                self.iconphoto(False, icon)
        except Exception:
            pass

        # Apply saved theme or default before creating widgets
        self.theme_manager.apply_theme(self.settings_manager.ui_settings.get("theme", "LYRN Dark"))

        # Basic window setup
        self.setup_window()
        self.load_tooltips()
        self.create_widgets()
        self.apply_color_theme()

        # Handle window closing and keybinds
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.bind("<Control-Shift-P>", self.open_command_palette)

        # Create context menu for chat display
        self.create_chat_context_menu()
        self.chat_display.bind("<Button-3>", self.show_chat_context_menu)

        # --- Phase 2: Start Background Initialization ---
        threading.Thread(target=self._initialize_background_services, daemon=True).start()
        self.after(100, self.process_queue)

        # Show missing files popup if any
        if missing_files:
            self.after(200, lambda: system_checker.show_missing_files_popup(self, missing_files, self.theme_manager))

    def show_loading_indicator(self):
        """Shows the indeterminate loading progress bar."""
        if hasattr(self, 'loading_progressbar'):
            self.loading_progressbar.pack(fill="x", pady=5, padx=10)
            self.loading_progressbar.start()
            self.update_status("Loading model...", LYRN_INFO)

    def hide_loading_indicator(self):
        """Hides the indeterminate loading progress bar."""
        if hasattr(self, 'loading_progressbar'):
            self.loading_progressbar.stop()
            self.loading_progressbar.pack_forget()

    def _initialize_background_services(self):
        """
        Initializes all managers and services that involve file I/O or other
        potentially blocking operations. Runs in a background thread.
        """
        print("Starting background initialization...")
        self.snapshot_loader = SnapshotLoader(self.settings_manager)
        self.delta_manager = DeltaManager()
        self.automation_controller = AutomationController()
        self.metrics = EnhancedPerformanceMetrics()
        self.chat_logger = StructuredChatLogger(self.settings_manager.settings["paths"].get("chat", "chat"))
        self.affordance_manager = AffordanceManager()
        self.scheduler_manager = SchedulerManager()
        self.cycle_manager = CycleManager()
        self.resource_monitor = SystemResourceMonitor(self.stream_queue)
        self.resource_monitor.start()

        # Start watcher scripts
        watcher_scripts = ["task_goal_watcher.py", "scheduler_watcher.py", "cycle_watcher.py", "topic_watcher.py"]
        for script_name in watcher_scripts:
            try:
                watcher_path = os.path.join(SCRIPT_DIR, "automation", script_name)
                if os.path.exists(watcher_path):
                    subprocess.Popen([sys.executable, watcher_path])
                    print(f"{script_name} started.")
            except Exception as e:
                print(f"Failed to start {script_name}: {e}")

        # Signal the main thread that initialization is complete
        self.stream_queue.put(('initialization_complete', None))
        print("Background initialization complete.")

    def _on_initialization_complete(self):
        """
        This method is called on the main UI thread after background services
        are loaded. It populates the UI with the loaded data.
        """
        print("Finalizing UI with loaded data...")
        self.update_status("Systems loaded.", LYRN_SUCCESS)

        # Show VRAM monitor only if NVML was successfully initialized
        if self.resource_monitor and self.resource_monitor.nvml_initialized:
            self.vram_frame.pack(fill="x", padx=10, pady=2)

        # Refresh UI elements that depend on the loaded managers
        self.refresh_active_cycle_selector()
        self.update_job_dropdown()

        # Now, handle the logic that was in start_application_logic
        if self.settings_manager.ui_settings.get("autoload_model", False) and self.settings_manager.settings.get("active", {}).get("model_path"):
            self.update_status("Autoloading model...", LYRN_INFO)
            threading.Thread(target=self.setup_model, daemon=True).start()
        elif self.settings_manager.first_boot or self.settings_manager.ui_settings.get("show_model_selector", True):
            self.open_model_selector()

        if self.settings_manager.ui_settings.get("llm_log_visible", False):
            self.toggle_log_viewer()


        # Model Status Indicator
        self.model_status = "Off"
        self.status_animation_after_id = None
        self.status_pulse_state = False
        self.status_definitions = {
            "Off": {"color": "#FF0000", "blink": False},
            "Model Error": {"color": "#FF0000", "blink": True},
            "Thinking": {"color": "#3B82F6", "blink": True},
            "Reasoning": {"color": "#3B82F6", "blink": False},
            "HB CYCLE": {"color": "#10B981", "blink": True},
            "Ready": {"color": "#10B981", "blink": False},
            "Automation": {"color": "#F59E0B", "blink": True},
            "Loading": {"color": LYRN_WARNING, "blink": False},
        }

        self.set_model_status("Off") # Start in Off state
        self.update_datetime()

    def update_datetime(self):
        """Updates the time and date labels."""
        now = datetime.now()
        if hasattr(self, 'datetime_label'):
            self.datetime_label.configure(text=now.strftime("%Y-%m-%d  %H:%M:%S"))
        self.after(1000, self.update_datetime)

    def set_model_status(self, status: str):
        if status not in self.status_definitions:
            print(f"Warning: Unknown model status '{status}'")
            return

        self.model_status = status
        status_info = self.status_definitions[status]

        # Cancel any ongoing animation
        if self.status_animation_after_id:
            self.after_cancel(self.status_animation_after_id)
            self.status_animation_after_id = None

        # Set initial color
        self.model_status_progress_bar.configure(progress_color=status_info["color"])

        # Start new animation if required
        if status_info["blink"]:
            self.status_pulse_state = True # Start with the main color
            self._animate_status_indicator()

    def _animate_status_indicator(self):
        status_info = self.status_definitions.get(self.model_status)
        if not status_info or not status_info["blink"]:
            return # Stop animation if status changed or is no longer blinking

        # Determine colors for the pulse
        main_color = status_info["color"]
        # The light-off color is the same as the system resources background
        off_color = self.theme_manager.get_color("status_bg_color", "#242424")

        # Set color based on pulse state
        target_color = main_color if self.status_pulse_state else off_color
        if hasattr(self, 'model_status_progress_bar'):
             self.model_status_progress_bar.configure(progress_color=target_color)

        # Toggle state for next pulse
        self.status_pulse_state = not self.status_pulse_state

        # Schedule next animation frame
        self.status_animation_after_id = self.after(500, self._animate_status_indicator)

    def load_tooltips(self):
        """Loads tooltips from the JSON file."""
        try:
            with open(os.path.join(SCRIPT_DIR, "hover_tooltip.json"), 'r', encoding='utf-8') as f:
                self.tooltips = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Warning: Could not load tooltips: {e}")
            self.tooltips = {}

    def on_closing(self):
        """Handle cleanup on window close."""
        if hasattr(self, 'resource_monitor'):
            self.resource_monitor.stop()
        self.master.destroy() # Destroy the root window to exit the app

    def _get_app_commands(self):
        commands = []
        # Add theme commands
        if hasattr(self, 'theme_manager'):
            for theme_name in self.theme_manager.get_theme_names():
                commands.append({
                    "name": f"Theme: Switch to {theme_name}",
                    "command": lambda t=theme_name: self.on_theme_selected(t)
                })

        # Add other commands
        commands.extend([
            {"name": "Model: Reload (Full)", "command": self.reload_model_full},
            {"name": "Model: Offload", "command": self.offload_model},
            {"name": "Chat: Clear Display", "command": self.clear_chat},
            {"name": "Chat: Clear Chat Folder", "command": self.clear_chat_folder},
            {"name": "System: Open Settings", "command": self.open_settings},
            {"name": "System: View Logs", "command": self.toggle_log_viewer},
            {"name": "System: Force Memory Cleanup", "command": self.force_memory_cleanup},
            {"name": "Font: Increase Size", "command": self.increase_font_size},
            {"name": "Font: Decrease Size", "command": self.decrease_font_size},
        ])
        return commands

    def open_command_palette(self, event=None):
        commands = self._get_app_commands()
        if hasattr(self, 'cmd_palette') and self.cmd_palette.winfo_exists():
            self.cmd_palette.focus()
        else:
            self.cmd_palette = CommandPalette(self, commands=commands, theme_manager=self.theme_manager)
            self.cmd_palette.focus()

    def open_model_selector(self):
        """Opens the model selector popup window."""
        if hasattr(self, 'model_selector_popup') and self.model_selector_popup.winfo_exists():
            self.model_selector_popup.lift()
            self.model_selector_popup.focus()
        else:
            self.model_selector_popup = ModelSelectorPopup(self, self.settings_manager, self.theme_manager)
            self.model_selector_popup.focus()

    def setup_window(self):
        """Configure main window with LYRN-AI branding"""
        self.title("LYRN-AI Dashboard v4.0.8")
        size = self.settings_manager.ui_settings.get("window_size", "1400x900")
        self.geometry(size)
        self.minsize(1200, 800)

    def handle_first_boot(self):
        """Handle first boot scenario"""
        print("Handling first boot...")

        def on_first_boot_complete():
            self.first_boot_complete = True
            self.initialize_application()

        # Show simplified first boot dialog (implement as needed)
        self.after(100, lambda: self.initialize_application())


    def setup_model(self):
        """Initialize LLM model with proper cleanup"""
        if not self.settings_manager.settings:
            print("No settings available for model setup")
            self.llm = None
            return

        self.stream_queue.put(('show_loading',))
        self.set_model_status("Loading")
        active = self.settings_manager.settings["active"]

        try:
            print(f"Loading LYRN-AI model: {active['model_path']}")

            # Ensure previous model is properly cleaned up
            if hasattr(self, 'llm') and self.llm is not None:
                print("Cleaning up previous model...")
                del self.llm
                gc.collect()

            self.llm = Llama(
                model_path=active["model_path"],
                n_ctx=active["n_ctx"],
                n_threads=active["n_threads"],
                n_gpu_layers=active["n_gpu_layers"],
                use_mlock=True,
                use_mmap=False,
                chat_format=active.get("chat_format"),
                add_bos=True,
                add_eos=True,
                verbose=True
            )
            print("LYRN-AI model loaded successfully")
            self.stream_queue.put(('status_update', 'Model Loaded', LYRN_SUCCESS))
            self.set_model_status("Ready")
            # Update toggle button on success
            if hasattr(self, 'model_toggle_button'):
                self.model_toggle_button.configure(text="Offload Model", fg_color="#35215f")

        except Exception as e:
            print(f"Error loading model: {e}")
            self.llm = None
            # Update toggle button on failure
            if hasattr(self, 'model_toggle_button'):
                self.model_toggle_button.configure(text="Load Model", fg_color=self.theme_manager.get_color("primary"))
            self.stream_queue.put(('status_update', f'Model Load Failed', LYRN_ERROR))
            self.set_model_status("Model Error")

        finally:
            self.stream_queue.put(('hide_loading',))

    def create_widgets(self):
        """Create main interface widgets with LYRN-AI styling"""
        self.grid_rowconfigure(0, weight=0) # Top bar
        self.grid_rowconfigure(1, weight=1) # Main content
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=0)

        self.create_left_sidebar().grid(row=1, column=0, sticky="nsew", padx=(10, 5), pady=(0, 10))
        self.create_chat_area().grid(row=1, column=1, sticky="nsew", padx=(0, 5), pady=(0, 10))
        self.create_right_sidebar().grid(row=1, column=2, sticky="nsew", padx=(5, 10), pady=(0, 10))

    def create_left_sidebar(self):
        """Creates the left sidebar for controls."""
        self.left_sidebar = ctk.CTkFrame(self, width=320, corner_radius=38)
        self.left_sidebar.grid_propagate(False)

        # LYRN-AI Header with logo placeholder
        header_frame = ctk.CTkFrame(self.left_sidebar, fg_color=LYRN_PURPLE, corner_radius=38)
        header_frame.pack(fill="x", padx=10, pady=(10, 20))
        header_frame.pack_propagate(False)
        header_frame.grid_columnconfigure((0, 2), weight=1) # Give weight to side columns for centering
        header_frame.grid_columnconfigure(1, weight=0)


        try:
            title_font = ctk.CTkFont(family="Consolas", size=26, weight="bold")
            section_font = ctk.CTkFont(family="Consolas", size=14, weight="bold")
            normal_font = ctk.CTkFont(family="Consolas", size=self.current_font_size)
            datetime_font = ctk.CTkFont(family="Consolas", size=18, weight="bold")
        except:
            title_font = ("Consolas", 26, "bold")
            section_font = ("Consolas", 14, "bold")
            normal_font = ("Consolas", self.current_font_size)
            datetime_font = ("Consolas", 18, "bold")

        # Logo placeholder and title
        logo_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        logo_frame.grid(row=0, column=1, pady=10) # Place logo in the center column

        # Attempt to load and display the logo
        try:
            if Image and ImageTk:
                logo_path = os.path.join(SCRIPT_DIR, "images/lyrn_logo.png")
                if os.path.exists(logo_path):
                    logo_image = Image.open(logo_path)
                    ctk_logo_image = ctk.CTkImage(light_image=logo_image, dark_image=logo_image, size=(48, 48))
                    logo_label = ctk.CTkLabel(logo_frame, image=ctk_logo_image, text="")
                    logo_label.pack(side="left", padx=(0, 10))
                else:
                    # Fallback to emoji if logo not found
                    ctk.CTkLabel(logo_frame, text="🧠", font=("Arial", 48)).pack(side="left", padx=(0, 10))
            else:
                # Fallback if Pillow is not installed
                ctk.CTkLabel(logo_frame, text="🧠", font=("Arial", 48)).pack(side="left", padx=(0, 10))
        except Exception as e:
            print(f"Error loading logo: {e}")
            ctk.CTkLabel(logo_frame, text="🧠", font=("Arial", 48)).pack(side="left", padx=(0, 10))


        title_label = ctk.CTkLabel(logo_frame, text="LYRN-AI", font=title_font,
                    text_color="white")
        title_label.pack(side="left", pady=(10,0))


        # Enhanced Status Section
        self.create_enhanced_status()

        # Quick controls frame
        self.quick_frame = ctk.CTkFrame(self.left_sidebar, fg_color="transparent", border_width=0)
        self.quick_frame.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(self.quick_frame, text="Quick Controls", font=section_font).pack(pady=10)

        # Reordered as per user request
        self.show_llm_log_button = ctk.CTkButton(self.quick_frame, text="📋 View Logs",
                                                 font=normal_font, command=self.toggle_log_viewer)
        self.show_llm_log_button.pack(fill="x", padx=10, pady=3)
        Tooltip(self.show_llm_log_button, self.tooltips.get("show_llm_log_button", ""))

        chat_folder_frame = ctk.CTkFrame(self.quick_frame)
        chat_folder_frame.pack(fill="x", padx=10, pady=3)

        self.clear_chat_folder_button = ctk.CTkButton(chat_folder_frame, text="Clear Chat Folder",
                                                      font=normal_font, command=self.clear_chat_folder)
        self.clear_chat_folder_button.pack(side="left", expand=True, fill="x", padx=(0, 5))
        Tooltip(self.clear_chat_folder_button, "Deletes all saved chat log files from the chat directory.")

        self.open_chat_folder_button = ctk.CTkButton(chat_folder_frame, text="📂", width=40,
                                                     font=normal_font, command=self.open_chat_folder)
        self.open_chat_folder_button.pack(side="left")
        Tooltip(self.open_chat_folder_button, "Open chat folder in file explorer.")

        self.terminal_button = ctk.CTkButton(self.quick_frame, text="📟 Code Terminal", command=self.open_terminal)
        self.terminal_button.pack(fill="x", padx=10, pady=3)
        Tooltip(self.terminal_button, "Opens a new terminal in the specified directory.")

        self.clear_chat_button = ctk.CTkButton(self.quick_frame, text="🗑️ Clear Display", command=self.clear_chat)
        self.clear_chat_button.pack(fill="x", padx=10, pady=3)
        Tooltip(self.clear_chat_button, "Clears the main chat display.")

        self.settings_button = ctk.CTkButton(self.quick_frame, text="⚙️ Settings", command=self.open_settings)
        self.settings_button.pack(fill="x", padx=10, pady=3)
        Tooltip(self.settings_button, self.tooltips.get("settings_button", "Open the settings window"))

        self.tasks_goals_button = ctk.CTkButton(self.quick_frame, text="🎯 Tasks/Goals", command=self.open_tasks_goals_popup)
        self.tasks_goals_button.pack(fill="x", padx=10, pady=3)
        Tooltip(self.tasks_goals_button, "Open the Tasks and Goals manager.")


        # Add a spacer to push content to the top
        spacer = ctk.CTkFrame(self.left_sidebar, fg_color="transparent")
        spacer.pack(expand=True, fill="both")

        return self.left_sidebar

    def create_right_sidebar(self):
        """Creates the right sidebar for monitoring and gauges."""
        self.right_sidebar = ctk.CTkFrame(self, width=320, corner_radius=38)
        self.right_sidebar.grid_propagate(False)

        # Datetime display
        try:
            datetime_font = ctk.CTkFont(family="Consolas", size=24, weight="bold")
        except:
            datetime_font = ("Consolas", 24, "bold")

        datetime_frame = ctk.CTkFrame(self.right_sidebar, fg_color="transparent")
        datetime_frame.pack(pady=(20, 10), padx=10, anchor="n")

        # Combine date and time into a single label for guaranteed one-line display
        self.datetime_label = ctk.CTkLabel(datetime_frame, text="", font=datetime_font)
        self.datetime_label.pack()

        # Enhanced Performance Metrics Section
        self.create_enhanced_metrics()

        # Job Automation Section
        self.job_frame = ctk.CTkFrame(self.right_sidebar, fg_color="transparent", border_width=0)
        self.job_frame.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(self.job_frame, text="Job Automation", font=ctk.CTkFont(family="Consolas", size=14, weight="bold")).pack(pady=10)

        # Cycle Control
        cycle_frame = ctk.CTkFrame(self.job_frame)
        cycle_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(cycle_frame, text="Active Cycle:").pack(side="left", padx=(0, 5))
        self.active_cycle_selector = ctk.CTkComboBox(cycle_frame, values=[], command=None)
        self.active_cycle_selector.pack(side="left", expand=True, fill="x")
        self.cycle_toggle_button = ctk.CTkButton(cycle_frame, text="Start", width=60, command=self.toggle_cycle)
        self.cycle_toggle_button.pack(side="left", padx=5)

        # Job selection dropdown for manual testing
        ctk.CTkLabel(self.job_frame, text="Manual Job Selection", font=ctk.CTkFont(family="Consolas", size=self.current_font_size)).pack(pady=(10, 5))
        self.job_dropdown = ctk.CTkComboBox(
            self.job_frame, values=["Loading..."],
            command=self.on_job_selected, font=ctk.CTkFont(family="Consolas", size=self.current_font_size),
            button_color=LYRN_PURPLE, button_hover_color=LYRN_ACCENT
        )
        self.job_dropdown.set("Loading...")
        self.job_dropdown.pack(padx=10, pady=(0, 15), fill="x")
        Tooltip(self.job_dropdown, self.tooltips.get("job_dropdown", ""))

        self.job_watcher_button = ctk.CTkButton(self.job_frame, text="Automation", command=self.open_job_watcher_popup)
        self.job_watcher_button.pack(fill="x", padx=10, pady=5)
        Tooltip(self.job_watcher_button, "Open the Job Automation Watcher popup.")

        self.affordance_button = ctk.CTkButton(self.job_frame, text="Affordances", command=self.open_affordance_popup)
        self.affordance_button.pack(fill="x", padx=10, pady=5)
        Tooltip(self.affordance_button, "Open the Affordance Editor to manage internal triggers.")

        self.memory_button = ctk.CTkButton(self.job_frame, text="Memory", command=self.open_memory_popup)
        self.memory_button.pack(fill="x", padx=10, pady=5)
        Tooltip(self.memory_button, "Open the Memory management popup.")

        return self.right_sidebar

    def open_heartbeat_logs_folder(self):
        """Opens the heartbeat logs directory in the system's file explorer."""
        logs_dir = os.path.join(SCRIPT_DIR, "automation", "heartbeat_outputs")
        if not os.path.isdir(logs_dir):
            os.makedirs(logs_dir, exist_ok=True)
            self.update_status("Heartbeat logs directory created.", LYRN_INFO)

        try:
            if sys.platform == "win32":
                os.startfile(os.path.realpath(logs_dir))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", logs_dir])
            else:
                subprocess.Popen(["xdg-open", logs_dir])
            self.update_status("Opened heartbeat logs folder.", LYRN_INFO)
        except Exception as e:
            self.update_status(f"Error opening folder: {e}", LYRN_ERROR)
            print(f"Error opening folder: {e}")

    def create_enhanced_metrics(self):
        """Create enhanced performance metrics with gauges"""
        self.metrics_frame = ctk.CTkFrame(self.right_sidebar, fg_color="transparent", border_width=0, corner_radius=38)
        self.metrics_frame.pack(fill="x", padx=10, pady=10)

        try:
            section_font = ctk.CTkFont(family="Consolas", size=14, weight="bold")
            normal_font = ctk.CTkFont(family="Consolas", size=self.current_font_size)
        except:
            section_font = ("Consolas", 14, "bold")
            normal_font = ("Consolas", self.current_font_size)

        ctk.CTkLabel(self.metrics_frame, text="Performance Metrics", font=section_font).pack(pady=10)

        # KV Cache with progress bar
        kv_frame = ctk.CTkFrame(self.metrics_frame)
        kv_frame.pack(fill="x", padx=10, pady=2)
        self.kv_label = ctk.CTkLabel(kv_frame, text="KV Cache: 0 tokens", font=normal_font)
        self.kv_label.pack(pady=(0,2))
        self.kv_progress = ctk.CTkProgressBar(kv_frame, height=8)
        self.kv_progress.pack(fill="x", padx=5, pady=(0,5))
        self.kv_progress.set(0)

        # Prompt tokens
        self.prompt_label = ctk.CTkLabel(self.metrics_frame, text="Prompt: 0 tokens", font=normal_font)
        self.prompt_label.pack(pady=2)

        # Generation speed
        self.eval_label = ctk.CTkLabel(self.metrics_frame, text="Generation: 0 tok/s", font=normal_font)
        self.eval_label.pack(pady=2)

        # Total tokens
        total_frame = ctk.CTkFrame(self.metrics_frame)
        total_frame.pack(fill="x", padx=10, pady=2)
        self.total_label = ctk.CTkLabel(total_frame, text="Total: 0 tokens", font=normal_font)
        self.total_label.pack(pady=(0,2))
        self.total_progress = ctk.CTkProgressBar(total_frame, height=8)
        self.total_progress.pack(fill="x", padx=5, pady=(0,5))
        self.total_progress.set(0)

        # Save metrics button
        ctk.CTkButton(self.metrics_frame, text="💾 Save Metrics",
                     font=normal_font, height=25, command=self.save_metrics_log).pack(
                         padx=10, pady=(10, 10), fill="x")

        # System Resource Gauges
        ctk.CTkLabel(self.metrics_frame, text="System Resources", font=section_font).pack(pady=(10,5))

        # CPU
        cpu_frame = ctk.CTkFrame(self.metrics_frame)
        cpu_frame.pack(fill="x", padx=10, pady=2)
        self.cpu_label = ctk.CTkLabel(cpu_frame, text="CPU: 0.0% (N/A)", font=normal_font)
        self.cpu_label.pack(pady=(0,2))
        self.cpu_progress = ctk.CTkProgressBar(cpu_frame, height=8, progress_color="#F59E0B")
        self.cpu_progress.pack(fill="x", padx=5, pady=(0,5))
        self.cpu_progress.set(0)

        # RAM
        ram_frame = ctk.CTkFrame(self.metrics_frame)
        ram_frame.pack(fill="x", padx=10, pady=2)
        self.ram_label = ctk.CTkLabel(ram_frame, text="RAM: 0.0%", font=normal_font)
        self.ram_label.pack(pady=(0,2))
        self.ram_progress = ctk.CTkProgressBar(ram_frame, height=8, progress_color="#3B82F6")
        self.ram_progress.pack(fill="x", padx=5, pady=(0,5))
        self.ram_progress.set(0)

        # Disk
        disk_frame = ctk.CTkFrame(self.metrics_frame)
        disk_frame.pack(fill="x", padx=10, pady=2)
        self.disk_label = ctk.CTkLabel(disk_frame, text="Disk: 0.0%", font=normal_font)
        self.disk_label.pack(pady=(0,2))
        self.disk_progress = ctk.CTkProgressBar(disk_frame, height=8, progress_color=LYRN_SUCCESS)
        self.disk_progress.pack(fill="x", padx=5, pady=(0,5))
        self.disk_progress.set(0)

        # VRAM (only if NVIDIA GPU is detected)
        # Create the widgets but keep them hidden. They will be shown in _on_initialization_complete if needed.
        self.vram_frame = ctk.CTkFrame(self.metrics_frame)
        self.vram_label = ctk.CTkLabel(self.vram_frame, text="VRAM: 0.0%", font=normal_font)
        self.vram_label.pack(pady=(0,2))
        self.vram_progress = ctk.CTkProgressBar(self.vram_frame, height=8, progress_color="#EF4444")
        self.vram_progress.pack(fill="x", padx=5, pady=(0,5))
        self.vram_progress.set(0)

    def update_system_gauges(self, stats: Dict[str, any]):
        """Update system resource gauges with new data."""
        if not hasattr(self, 'cpu_label'): return # Widgets not ready

        # CPU
        self.cpu_label.configure(text=f"CPU: {stats['cpu']:.1f}% ({stats['cpu_temp']})")
        self.cpu_progress.set(stats['cpu'] / 100)

        # RAM
        ram_text = f"RAM: {stats['ram_used_gb']:.1f}/{stats['ram_total_gb']:.1f} GB ({stats['ram_percent']:.1f}%)"
        self.ram_label.configure(text=ram_text)
        self.ram_progress.set(stats['ram_percent'] / 100)

        # Disk
        disk_text = f"Disk: {stats['disk_used_gb']:.1f}/{stats['disk_total_gb']:.1f} GB ({stats['disk_percent']:.1f}%)"
        if hasattr(self, 'disk_label'):
            self.disk_label.configure(text=disk_text)
            self.disk_progress.set(stats['disk_percent'] / 100)

        # VRAM
        if self.resource_monitor and self.resource_monitor.nvml_initialized:
            vram_text = f"VRAM: {stats['vram_used_gb']:.1f}/{stats['vram_total_gb']:.1f} GB ({stats['vram_percent']:.1f}%)"
            self.vram_label.configure(text=vram_text)
            self.vram_progress.set(stats['vram_percent'] / 100)

    def create_enhanced_status(self):
        """Create enhanced status display with better organization."""
        self.status_frame = ctk.CTkFrame(self.left_sidebar, fg_color="transparent", border_width=0)
        self.status_frame.pack(fill="x", padx=10, pady=(0, 10))

        try:
            section_font = ctk.CTkFont(family="Consolas", size=14, weight="bold")
            status_font = ctk.CTkFont(family="Consolas", size=12, weight="bold")
            normal_font = ctk.CTkFont(family="Consolas", size=self.current_font_size)
        except:
            section_font = ("Consolas", 14, "bold")
            status_font = ("Consolas", 12, "bold")
            normal_font = ("Consolas", self.current_font_size)

        # Frame for title and status light
        title_frame = ctk.CTkFrame(self.status_frame, fg_color="transparent")
        title_frame.pack(pady=(10, 5))

        ctk.CTkLabel(title_frame, text="System Status", font=section_font).pack(side="left", padx=(0, 10))

        self.model_status_progress_bar = ctk.CTkProgressBar(title_frame, width=80, height=15)
        self.model_status_progress_bar.set(1) # Set to 100%
        self.model_status_progress_bar.pack(side="left")

        # Restored textbox for general status messages
        self.status_textbox = ctk.CTkTextbox(self.status_frame, height=50, wrap="char", font=status_font)
        self.status_textbox.pack(fill="x", padx=10, pady=5)
        self.status_textbox.insert("end", "System ready.")
        self.status_textbox.configure(state="disabled")

        # Loading Progress Bar (hidden by default)
        self.loading_progressbar = ctk.CTkProgressBar(self.status_frame, mode='indeterminate')

        # Model Control Buttons
        self.model_toggle_button = ctk.CTkButton(self.status_frame, text="Load Model", font=normal_font, command=self.toggle_model_load)
        self.model_toggle_button.pack(fill="x", padx=10, pady=(5, 2))
        Tooltip(self.model_toggle_button, "Load or Offload the model.")

        # --- Relocated Controls ---
        self.change_model_button = ctk.CTkButton(self.status_frame, text="⚙️ Model Settings", command=self.open_model_selector)
        self.change_model_button.pack(fill="x", padx=10, pady=(10, 5))
        Tooltip(self.change_model_button, "Open the model settings to change the loaded model.")


        self.prompt_builder_button = ctk.CTkButton(self.status_frame, text="📝 System Prompt", command=self.open_prompt_builder)
        self.prompt_builder_button.pack(fill="x", padx=10, pady=3)
        Tooltip(self.prompt_builder_button, "Open the System Prompt Builder window.")


        # --- End Relocated Controls ---

    def create_chat_area(self):
        """Create enhanced chat interface with colored text support"""
        chat_frame = ctk.CTkFrame(self, corner_radius=38)
        # chat_frame.grid(row=1, column=1, sticky="nsew", padx=(0, 5), pady=(0, 10))
        chat_frame.grid_rowconfigure(0, weight=1)
        chat_frame.grid_columnconfigure(0, weight=1)

        # Chat display with enhanced text handling
        try:
            chat_font = ctk.CTkFont(family="Consolas", size=self.current_font_size)
        except:
            chat_font = ("Consolas", self.current_font_size)

        self.chat_display = ctk.CTkTextbox(chat_frame, font=chat_font, wrap="word", border_width=2, text_color=self.theme_manager.get_color("display_text_color"))
        self.chat_display.grid(row=0, column=0, sticky="nsew", padx=20, pady=(20, 10))

        # Configure tags for colored text
        self.chat_display.tag_config("system_text", foreground=self.theme_manager.get_color("system_text"))
        self.chat_display.tag_config("user_text", foreground=self.theme_manager.get_color("user_text"))
        self.chat_display.tag_config("assistant_text", foreground=self.theme_manager.get_color("assistant_text"))
        self.chat_display.tag_config("thinking_text", foreground=self.theme_manager.get_color("thinking_text"))
        self.chat_display.tag_config("error", foreground=self.theme_manager.get_color("error"))
        self.chat_display.tag_config("success", foreground=self.theme_manager.get_color("success"))

        # Input area
        input_frame = ctk.CTkFrame(chat_frame)
        input_frame.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 20))
        input_frame.grid_columnconfigure(0, weight=1)

        # Add hint label for sending message
        hint_label = ctk.CTkLabel(input_frame, text="Use Ctrl+Enter to send", font=("Consolas", 10))
        hint_label.grid(row=0, column=0, sticky="nw", padx=5, pady=2)

        self.input_box = ctk.CTkTextbox(input_frame, height=100, font=chat_font, border_width=2)
        self.input_box.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        input_frame.grid_rowconfigure(1, weight=1)

        # Button Frame for Send and Copy
        button_vframe = ctk.CTkFrame(input_frame, fg_color="transparent")
        button_vframe.grid(row=1, column=1, padx=(5,0))

        # Send button with LYRN styling
        self.send_btn = ctk.CTkButton(button_vframe, text="Send", width=80,
                                     font=chat_font,
                                     command=self.send_message)
        self.send_btn.pack(pady=(0, 5), fill="x")
        Tooltip(self.send_btn, self.tooltips.get("send_button", ""))

        # Copy last response button
        self.copy_btn = ctk.CTkButton(button_vframe, text="Copy", width=80,
                                     font=chat_font,
                                     command=self.copy_last_response)
        self.copy_btn.pack(pady=(5, 0), fill="x")
        Tooltip(self.copy_btn, "Copies the last assistant response to the clipboard.")

        # Stop button
        self.stop_btn = ctk.CTkButton(button_vframe, text="Stop", width=80,
                                     font=chat_font,
                                     command=self.stop_generation_process,
                                     state="disabled")
        self.stop_btn.pack(pady=(5, 0), fill="x")
        Tooltip(self.stop_btn, "Stops the current generation.")

        # Bind keyboard shortcut
        self.input_box.bind("<Control-Return>", lambda e: self.send_message())

        # Welcome message with LYRN branding
        welcome_msg = f"""
╔═══════════════════════════════════════════════════════╗
║                   LYRN-AI v3.9.6                      ║
║              Advanced Language Interface              ║
║                                                       ║
║ • Enhanced performance monitoring                     ║
║ • Multi-colored text display                          ║
║ • Live theme switching                                ║
║ • Advanced job coordination                           ║
║ • Memory-optimized model handling                     ║
║ • LYRN-AI branded experience                          ║
║                                                       ║
║ Status: {'🟢 ONLINE' if self.llm else '🔴 MODEL NOT LOADED'}                               ║
╚═══════════════════════════════════════════════════════╝

Ready for interaction. Use Ctrl+Enter to send messages.
Enhanced LYRN-AI system with advanced features active.
"""
        # Welcome message removed as per request
        # self.display_colored_message(f"{welcome_msg}\n\n", "system_text")
        return chat_frame

    def display_colored_message(self, message: str, tag: str):
        """Appends a message to the chat display with a specific color tag."""
        self.chat_display.configure(state="normal")
        self.chat_display.insert("end", message, tag)
        self.chat_display.see("end")
        self.chat_display.configure(state="disabled")

    def on_theme_selected(self, theme_name: str):
        """Callback for when a new theme is selected from the dropdown."""
        self.theme_manager.apply_theme(theme_name)

        # Save the new theme setting
        self.settings_manager.ui_settings["theme"] = theme_name
        self.settings_manager.save_settings()

        # Re-apply colors to all relevant widgets
        self.apply_color_theme()

        # Also re-apply to settings dialog if it's open
        if hasattr(self, 'settings_dialog') and self.settings_dialog.winfo_exists():
            self.settings_dialog.apply_theme()

        self.update_status(f"Theme changed to {theme_name}", self.theme_manager.get_color("info"))

    def increase_font_size(self):
        """Increase font size"""
        if self.current_font_size < 20:
            self.current_font_size += 1
            self.settings_manager.ui_settings["font_size"] = self.current_font_size
            self.settings_manager.save_settings()
            self.apply_font_changes()

    def decrease_font_size(self):
        """Decrease font size"""
        if self.current_font_size > 8:
            self.current_font_size -= 1
            self.settings_manager.ui_settings["font_size"] = self.current_font_size
            self.settings_manager.save_settings()
            self.apply_font_changes()

    def apply_font_changes(self):
        """Apply font size changes to relevant widgets"""
        try:
            new_font = ctk.CTkFont(family="Consolas", size=self.current_font_size)

            # Update chat display and input
            self.chat_display.configure(font=new_font)
            self.input_box.configure(font=new_font)

            # Update other elements as needed
            self.update_status(f"Font size: {self.current_font_size}", LYRN_INFO)

        except Exception as e:
            print(f"Error applying font changes: {e}")


    def apply_color_theme(self):
        """Apply colors from the current theme to all relevant widgets."""
        try:
            tm = self.theme_manager
            primary_color = tm.get_color("primary")
            accent_color = tm.get_color("accent")
            frame_bg = tm.get_color("frame_bg")
            textbox_bg = tm.get_color("textbox_bg")
            textbox_fg = tm.get_color("textbox_fg")
            label_text = tm.get_color("label_text")
            button_hover_color = tm.get_color("button_hover", fallback=accent_color)
            border_color = tm.get_color("border_color")

            # Theme background
            self.configure(fg_color=frame_bg)

            # --- Update all widgets recursively ---
            for widget_type, config in [
                (ctk.CTkButton, {"fg_color": primary_color, "hover_color": button_hover_color}),
                (ctk.CTkComboBox, {"button_color": primary_color, "button_hover_color": button_hover_color}),
                (ctk.CTkFrame, {"fg_color": frame_bg, "border_color": border_color}),
                (ctk.CTkLabel, {"text_color": label_text}),
                (ctk.CTkTextbox, {"fg_color": textbox_bg, "text_color": textbox_fg, "border_color": border_color}),
                (ctk.CTkScrollableFrame, {"fg_color": frame_bg, "label_fg_color": primary_color})
            ]:
                for widget in self.find_widgets_recursively(self, widget_type):
                    try:
                        widget.configure(**config)
                    except Exception:
                        # Ignore if a widget doesn't support a property, e.g. a specific button
                        pass

            # --- Update specific labels ---
            if hasattr(self, 'chat_display'):
                self.chat_display.configure(text_color=tm.get_color("display_text_color"))
            if hasattr(self, 'kv_label'):
                self.kv_label.configure(text_color=tm.get_color("info"))
            if hasattr(self, 'prompt_label'):
                self.prompt_label.configure(text_color=tm.get_color("system_text"))
            if hasattr(self, 'eval_label'):
                self.eval_label.configure(text_color=accent_color)
            if hasattr(self, 'total_label'):
                self.total_label.configure(text_color=tm.get_color("success"))

            # Update border colors
            border_color = tm.get_color("border_color")
            if hasattr(self, 'job_frame'):
                self.job_frame.configure(border_color=border_color)
            if hasattr(self, 'system_frame'):
                self.system_frame.configure(border_color=border_color)
            if hasattr(self, 'quick_frame'):
                self.quick_frame.configure(border_color=border_color)
            if hasattr(self, 'metrics_frame'):
                self.metrics_frame.configure(border_color=border_color)
            if hasattr(self, 'hwinfo_frame'):
                self.hwinfo_frame.configure(border_color=border_color)
            if hasattr(self, 'status_frame'):
                self.status_frame.configure(border_color=border_color)

            print("Color theme re-applied to main window widgets.")

        except Exception as e:
            print(f"Error applying color theme: {e}")

    def find_widgets_recursively(self, widget, widget_type):
        widgets = []
        if isinstance(widget, widget_type):
            widgets.append(widget)
        for child in widget.winfo_children():
            widgets.extend(self.find_widgets_recursively(child, widget_type))
        return widgets

    def save_metrics_log(self):
        """Save current metrics to log file"""
        if hasattr(self, 'metrics'):
            log_file = self.metrics.save_metrics_log(self.settings_manager)
            if log_file:
                self.update_status(f"Metrics saved to log", LYRN_SUCCESS)
            else:
                self.update_status("Failed to save metrics", LYRN_ERROR)

    # open_personality_popup removed, functionality moved to settings dialog

    def open_terminal(self):
        """Opens a new terminal window in the specified path."""
        start_path = self.settings_manager.ui_settings.get("terminal_start_path", SCRIPT_DIR)
        if not os.path.isdir(start_path):
            start_path = SCRIPT_DIR
            self.update_status(f"Terminal path not found, defaulting to script dir.", LYRN_WARNING)

        try:
            if sys.platform == "win32":
                subprocess.Popen(f'start cmd', shell=True, cwd=start_path)
            elif sys.platform == "darwin":
                # For macOS, 'open -a Terminal .' works well from a specific directory
                subprocess.Popen(['open', '-a', 'Terminal', start_path])
            else:  # Assuming Linux
                try:
                    # Tries to open gnome-terminal, common on many Linux distros
                    subprocess.Popen(['gnome-terminal', '--working-directory', start_path])
                except FileNotFoundError:
                    try:
                        # Fallback to xterm, which is more likely to be installed
                        subprocess.Popen(['xterm', '-e', f'cd "{start_path}" && bash'])
                    except FileNotFoundError:
                        self.update_status("Could not find a terminal to open.", LYRN_ERROR)
        except Exception as e:
            self.update_status(f"Failed to open terminal: {e}", LYRN_ERROR)
            print(f"Failed to open terminal: {e}")

    def open_settings(self):
        """Open enhanced tabbed settings dialog"""
        if not hasattr(self, 'settings_dialog') or not self.settings_dialog.winfo_exists():
            self.settings_dialog = TabbedSettingsDialog(self, self.settings_manager, self.theme_manager, self.language_manager)
            self.settings_dialog.focus()
        else:
            self.settings_dialog.lift()
            self.settings_dialog.focus()

    def open_prompt_builder(self):
        """Opens the prompt builder popup window."""
        if not hasattr(self, 'prompt_builder_popup') or not self.prompt_builder_popup.winfo_exists():
            self.prompt_builder_popup = SystemPromptBuilderPopup(self, self.theme_manager, self.language_manager, self.snapshot_loader)
            self.prompt_builder_popup.focus()
        else:
            self.prompt_builder_popup.lift()
            self.prompt_builder_popup.focus()

    def refresh_prompt_from_mode(self):
        """Rebuilds the master prompt from components and reloads it."""
        if self.snapshot_loader:
            self.snapshot_loader.build_master_prompt_from_components()
            self.update_status("Master prompt rebuilt from current components.", LYRN_SUCCESS)
        else:
            self.update_status("Snapshot loader not initialized.", LYRN_ERROR)

    def open_job_watcher_popup(self):
        """Opens the job watcher popup window."""
        if not hasattr(self, 'job_watcher_popup') or not self.job_watcher_popup.winfo_exists():
            self.job_watcher_popup = JobWatcherPopup(self, self.automation_controller, self.theme_manager, self.language_manager, self.cycle_manager)
            # Refresh the cycle list in the main UI when opening the popup
            self.refresh_active_cycle_selector()
            self.job_watcher_popup.focus()
        else:
            self.refresh_active_cycle_selector()
            self.job_watcher_popup.lift()
            self.job_watcher_popup.focus()

    def open_affordance_popup(self):
        """Opens the affordance editor popup window."""
        if not hasattr(self, 'affordance_popup') or not self.affordance_popup.winfo_exists():
            self.affordance_popup = AffordancePopup(self, self.affordance_manager, self.theme_manager, self.language_manager)
            self.affordance_popup.focus()
        else:
            self.affordance_popup.lift()
            self.affordance_popup.focus()

    def open_memory_popup(self):
        """Opens the memory manager popup window."""
        if not hasattr(self, 'memory_popup') or not self.memory_popup.winfo_exists():
            self.memory_popup = MemoryPopup(self, self.theme_manager, self.language_manager)
            self.memory_popup.focus()
        else:
            self.memory_popup.lift()
            self.memory_popup.focus()

    def open_tasks_goals_popup(self):
        """Opens the tasks and goals manager popup window."""
        if not hasattr(self, 'tasks_goals_popup') or not self.tasks_goals_popup.winfo_exists():
            self.tasks_goals_popup = TasksGoalsPopup(self, self.theme_manager, self.language_manager)
            self.tasks_goals_popup.focus()
        else:
            self.tasks_goals_popup.lift()
            self.tasks_goals_popup.focus()

    def open_episodic_memory_popup(self):
        """Opens the episodic memory manager popup window."""
        if not hasattr(self, 'episodic_memory_popup') or not self.episodic_memory_popup.winfo_exists():
            self.episodic_memory_popup = EpisodicMemoryPopup(self, self.episodic_memory_manager, self.theme_manager, self.language_manager)
            self.episodic_memory_popup.focus()
        else:
            self.episodic_memory_popup.lift()
            self.episodic_memory_popup.focus()

    def open_topic_index_popup(self):
        """Opens the topic index manager popup window."""
        if not hasattr(self, 'topic_index_popup') or not self.topic_index_popup.winfo_exists():
            self.topic_index_popup = TopicIndexPopup(self, self.theme_manager, self.settings_manager)
            self.topic_index_popup.focus()
        else:
            self.topic_index_popup.lift()
            self.topic_index_popup.focus()

    def toggle_log_viewer(self):
        """Creates, shows, or focuses the LLM log viewer window."""
        # If the popup doesn't exist or has been destroyed, create it.
        if not hasattr(self, 'log_viewer_popup') or not self.log_viewer_popup.winfo_exists():
            self.log_viewer_popup = LogViewerPopup(self, self.log_queue, self.settings_manager, self.theme_manager)
            self.log_viewer_popup.focus()
        else:
            # If it exists, bring it to the front and show it if it was withdrawn.
            self.log_viewer_popup.deiconify()
            self.log_viewer_popup.lift()
            self.log_viewer_popup.focus()

    def toggle_model_load(self):
        """Toggles between loading and offloading the model."""
        if self.llm is None:
            self.reload_model_full()
        else:
            self.offload_model()

    def reload_model_full(self):
        """Full model reload with proper memory cleanup"""
        self.update_status("Reloading model (full cleanup)...", LYRN_WARNING)
        threading.Thread(target=self._reload_model_full_thread, daemon=True).start()

    def offload_model(self):
        """Offloads the model to free up system resources."""
        if self.llm is None:
            self.update_status("Model is already offloaded.", LYRN_INFO)
            return

        self.update_status("Offloading model...", LYRN_WARNING)
        self.set_model_status("Off")

        del self.llm
        self.llm = None
        gc.collect() # Force garbage collection

        # Update toggle button
        if hasattr(self, 'model_toggle_button'):
            self.model_toggle_button.configure(text="Load Model", fg_color=self.theme_manager.get_color("primary"))

        self.stream_queue.put(('status_update', 'Model Offloaded', LYRN_SUCCESS))

    def _reload_model_full_thread(self):
        """Full model reload in separate thread with cleanup"""
        try:
            # Force cleanup of existing model
            if hasattr(self, 'llm') and self.llm is not None:
                print("Performing full model cleanup...")
                del self.llm
                self.llm = None

                # Force garbage collection and memory cleanup
                gc.collect()

                # Additional cleanup for llama-cpp-python
                import ctypes
                libc = ctypes.CDLL("libc.so.6")
                libc.malloc_trim(0)

                # Wait a moment for cleanup
                time.sleep(2)

            # Reset metrics
            if hasattr(self, 'metrics'):
                self.metrics.reset_metrics()

            # Reload model
            self.setup_model()

            # Update UI
            self.stream_queue.put(('status_update', 'Model reloaded successfully', LYRN_SUCCESS))
            self.stream_queue.put(('metrics_reset', ''))

        except Exception as e:
            self.stream_queue.put(('status_update', f'Model reload failed: {e}', LYRN_ERROR))

    def force_memory_cleanup(self):
        """Force memory cleanup"""
        try:
            gc.collect()

            # Additional system-specific cleanup
            try:
                import ctypes
                if sys.platform == "linux":
                    libc = ctypes.CDLL("libc.so.6")
                    libc.malloc_trim(0)
                elif sys.platform == "win32":
                    kernel32 = ctypes.windll.kernel32
                    kernel32.SetProcessWorkingSetSize(-1, -1, -1)
            except:
                pass

            self.update_status("Memory cleanup completed", LYRN_SUCCESS)

        except Exception as e:
            print(f"Memory cleanup error: {e}")
            self.update_status("Memory cleanup failed", LYRN_ERROR)

    def test_model_performance(self):
        """
        Test model performance.
        NOTE: This function is temporarily disabled pending a refactor to support the new IPC model.
        """
        if True:
            self.update_status("Performance test is temporarily disabled.", LYRN_WARNING)
            return

    def on_job_selected(self, job_name: str):
        """Handle manual job selection for testing."""
        if hasattr(self, 'automation_controller'):
            # Get the full job prompt with headers
            job_prompt = self.automation_controller.get_job_prompt(job_name, args={})
            if job_prompt:
                self.insert_job_text(job_prompt)
                self.update_status(f"Manual job loaded: {job_name}", LYRN_ACCENT)

    def _execute_reflection_job(self, job: Job):
        """Executes the reflection job, handling file saving and versioning."""
        args = job.args
        original_job_name = args.get("original_job_name", "unknown_job")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 1. Create the reflections directory
        reflections_dir = Path(SCRIPT_DIR) / "reflections" / f"{original_job_name}_{timestamp}"
        reflections_dir.mkdir(parents=True, exist_ok=True)

        # 2. Save original outputs and reflection notes
        try:
            # Save the original job output that was reflected upon
            with open(reflections_dir / "original_output.txt", "w", encoding="utf-8") as f:
                f.write(args.get("job_output", ""))

            # The 'reflection_cycle_job' itself is run by the main generation logic.
            # We need to get the *result* of that job here. For now, we'll simulate this
            # by running the LLM again. In a future refactor, this should be more integrated.
            self.display_colored_message(f"\n--- Running Reflection For: {original_job_name} ---\n", "system_text")

            # This is where we call the LLM to perform the reflection.
            # We'll construct a prompt similar to how the main chat works.
            reflection_prompt = self.automation_controller.get_job_prompt("reflection_cycle_job", args)

            messages = [
                {"role": "system", "content": self.snapshot_loader.load_base_prompt()},
                {"role": "user", "content": reflection_prompt}
            ]

            active = self.settings_manager.settings["active"]
            handler = StreamHandler(self.stream_queue, self.metrics)

            stream = self.llm.create_chat_completion(
                prompt=your_prompt,
                max_tokens=active["max_tokens"],
                temperature=active["temperature"],
                top_p=active["top_p"],
                stream=True
            )

            response_parts = []
            for token_data in stream:
                if 'choices' in token_data and len(token_data['choices']) > 0:
                    delta = token_data['choices'][0].get('delta', {})
                    content = delta.get('content', '')
                    if content:
                        response_parts.append(content)

            reflection_result = ''.join(response_parts)

            with open(reflections_dir / "reflection_notes.txt", "w", encoding="utf-8") as f:
                f.write(reflection_result)

            self.display_colored_message(f"Reflection complete. Notes saved to {reflections_dir}\n", "system_text")

        except Exception as e:
            print(f"Error during reflection file saving: {e}")
            self.update_status("Error saving reflection files.", LYRN_ERROR)

        # 3. Handle automatic prompt updates
        if args.get("auto_update", False):
            self.display_colored_message("Attempting to automatically update prompt...\n", "system_text")

            # This would be another LLM call to generate a new prompt.
            # For now, we'll simulate it.
            new_prompt_content = f"# Prompt for {original_job_name} v2\n" + self.automation_controller.job_definitions.get(original_job_name, "") + "\n# Updated by reflection."

            # Save new prompt with versioning
            jobs_dir = Path(SCRIPT_DIR) / "automation" / "jobs"
            new_prompt_path = jobs_dir / f"{original_job_name}_v2.txt" # Simplified versioning

            try:
                with open(new_prompt_path, "w", encoding="utf-8") as f:
                    f.write(new_prompt_content)

                # Save changelog
                changelog_path = Path(SCRIPT_DIR) / "reflections" / "reflection_changelog.txt"
                with open(changelog_path, "a", encoding="utf-8") as f:
                    f.write(f"[{timestamp}] Job '{original_job_name}' updated to v2. See folder: {reflections_dir.name}\n")

                self.display_colored_message(f"Prompt updated and saved to {new_prompt_path.name}\n", "success")

                # 4. Handle auto-continuation
                if args.get("auto_continue", False):
                    self.display_colored_message("Auto-continuing job with updated prompt...\n", "system_text")
                    # Re-add the original job to the queue, which will now use the new prompt if named correctly.
                    # This part needs careful implementation to ensure the right version is picked up.
                    # For now, we assume the system will just use the latest file for a given job name.
                    self.automation_controller.add_job(name=original_job_name)


            except Exception as e:
                print(f"Error updating prompt: {e}")
                self.update_status("Error updating prompt.", LYRN_ERROR)


    def _maybe_run_automated_job(self):
        """Checks for and runs the next job in the queue if the system is idle."""
        if self.is_thinking: # Don't run a job if the model is already running
            return

        if self.automation_controller.has_pending_jobs():
            next_job = self.automation_controller.get_next_job()
            if next_job:
                print(f"Executing automated job: {next_job.name}")

                if next_job.name == "reflection_cycle_job":
                    self._execute_reflection_job(next_job)
                else:
                    # For now, this just displays the job prompt for verification.
                    # Later, this will trigger a full LLM cycle for the job.
                    self.display_colored_message(f"\n--- Running Automated Job: {next_job.name} ---\n", "system_text")
                    self.display_colored_message(next_job.prompt, "system_text")
                    self.display_colored_message(f"\n--- Job Complete: {next_job.name} ---\n", "system_text")
                    self._handle_job_completion(next_job.name)

                # Check if more jobs are pending and run them if so
                self.after(100, self._maybe_run_automated_job)

    def _get_job_run_counts(self) -> Dict[str, int]:
        """Reads the job run counts from the JSON file."""
        counts_path = Path(SCRIPT_DIR) / "automation" / "job_run_counts.json"
        if not counts_path.exists():
            return {}
        try:
            with open(counts_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}

    def _save_job_run_counts(self, counts: Dict[str, int]):
        """Saves the job run counts to the JSON file."""
        counts_path = Path(SCRIPT_DIR) / "automation" / "job_run_counts.json"
        try:
            with open(counts_path, 'w', encoding='utf-8') as f:
                json.dump(counts, f, indent=2)
        except IOError as e:
            print(f"Error saving job run counts: {e}")

    def _handle_job_completion(self, job_name: str):
        """Increments the run count for a job and triggers reflection if the batch size is met."""
        # This function should only be called for non-reflection jobs.
        if job_name == "reflection_cycle_job":
            return

        counts = self._get_job_run_counts()
        new_count = counts.get(job_name, 0) + 1
        counts[job_name] = new_count
        self._save_job_run_counts(counts)

        try:
            batch_size_str = self.job_watcher_popup.reflection_batch_size_entry.get()
            batch_size = int(batch_size_str)
        except (ValueError, AttributeError):
            # If the entry is invalid or the popup isn't open, don't trigger reflection.
            return

        if batch_size > 0 and new_count >= batch_size:
            print(f"Job '{job_name}' has reached its batch size of {batch_size}. Triggering reflection.")
            # Reset the counter
            counts[job_name] = 0
            self._save_job_run_counts(counts)

            # Queue the reflection job
            # We need to gather the necessary data from the UI again.
            if hasattr(self, 'job_watcher_popup') and self.job_watcher_popup.winfo_exists():
                self.job_watcher_popup.run_reflection_manually()
            else:
                print("Warning: Job watcher popup is not open. Cannot trigger automated reflection.")

    def insert_job_text(self, text: str):
        """Insert job text into input box"""
        self.input_box.delete("0.0", "end")
        self.input_box.insert("0.0", text)

    def copy_last_response(self):
        """Copies the last assistant response to the clipboard."""
        if hasattr(self, 'last_assistant_response') and self.last_assistant_response:
            self.clipboard_clear()
            self.clipboard_append(self.last_assistant_response)
            self.update_status("Last response copied to clipboard", LYRN_SUCCESS)
        else:
            self.update_status("No response to copy yet", LYRN_WARNING)

    def create_chat_context_menu(self):
        """Creates the right-click context menu for the chat display."""
        self.chat_context_menu = tk.Menu(self, tearoff=0)
        self.chat_context_menu.add_command(label="Quote to Context", command=self.quote_selected_text)

    def show_chat_context_menu(self, event):
        """Shows the chat context menu if text is selected."""
        if self.chat_display.tag_ranges("sel"):
            self.chat_context_menu.tk_popup(event.x_root, event.y_root)

    def quote_selected_text(self):
        """Gets the selected text and saves it to quotes.txt."""
        try:
            selected_text = self.chat_display.get("sel.first", "sel.last")
            if selected_text:
                self.episodic_memory_manager.add_to_quotes(selected_text)
                self.update_status("Text quoted to quotes.txt", LYRN_SUCCESS)
        except tk.TclError:
            self.update_status("No text selected to quote.", LYRN_WARNING)


    def send_message(self):
        """Send user message and generate response"""
        user_text = self.input_box.get("0.0", "end").strip()
        if not user_text:
            return

        self.last_user_input = user_text

        if not self.llm:
            self.update_status("No model loaded", LYRN_ERROR)
            return

        # Start a new structured log for this interaction
        self.chat_logger.start_log()
        self.chat_logger.append_log("USER", user_text)

        # Display user message
        self.display_colored_message(f"You: {user_text}\n\n", "user_text")

        # Clear input and disable send
        self.input_box.delete("0.0", "end")
        self.send_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.stop_generation = False # Reset flag at the start of a new generation
        self._write_llm_status("busy")

        # The old save_chat_message is now deprecated.
        # self.save_chat_message("user", user_text)

        # Display thinking message and start response generation
        self.display_colored_message("Assistant: Thinking...\n\n", "thinking_text")
        self.is_thinking = True
        self.set_model_status("Thinking") # Blue for generating
        threading.Thread(target=self.generate_response, args=(user_text,), daemon=True).start()
        self.update_status("Generating response...", LYRN_INFO)

    def get_response_for_job(self, user_text: str) -> str:
        """Generate AI response for a job and return it as a string."""
        try:
            # Build prompt
            full_prompt = self.snapshot_loader.load_base_prompt()

            messages = [
                {"role": "system", "content": full_prompt},
                {"role": "user", "content": user_text}
            ]

            active = self.settings_manager.settings["active"]

            # Start streaming with enhanced metrics capture
            stream = self.llm.create_chat_completion(
                messages=messages,
                max_tokens=active.get("max_tokens", 2048),
                temperature=active["temperature"],
                top_p=active["top_p"],
                top_k=active.get("top_k", 40),
                stream=True
            )

            response_parts = []
            for token_data in stream:
                if 'choices' in token_data and len(token_data['choices']) > 0:
                    delta = token_data['choices'][0].get('delta', {})
                    content = delta.get('content', '')
                    if content:
                        response_parts.append(content)

            # Save complete response
            complete_response = ''.join(response_parts)
            return complete_response

        except Exception as e:
            self.stream_queue.put(('error', str(e)))
            return f"Error generating response: {e}"

    def stop_generation_process(self):
        """Sets the flag to stop the generation thread."""
        self.stop_generation = True
        self.update_status("Stopping generation...", LYRN_WARNING)

    def remove_thinking_message(self):
        """Finds and removes the 'Thinking...' message from the chat display."""
        self.chat_display.configure(state="normal")
        # Search for the "Thinking..." message starting from the end.
        pos = self.chat_display.search("Assistant: Thinking...", "end", backwards=True, stopindex="1.0")
        if pos:
            # If found, delete from that position to the end of the textbox.
            # This is robust enough to clear the message even if other text arrived.
            self.chat_display.delete(pos, "end")
        self.chat_display.configure(state="disabled")

    def generate_response(self, user_text: str):
        """Generate AI response with enhanced handling and metrics capture."""
        try:
            # Build prompt
            full_prompt = self.snapshot_loader.load_base_prompt()

            messages = [
                {"role": "system", "content": full_prompt},
                {"role": "user", "content": user_text}
            ]

            active = self.settings_manager.settings["active"]
            handler = StreamHandler(self.stream_queue, self.metrics)

            # Setup stderr capture
            log_capture_buffer = io.StringIO()

            with contextlib.redirect_stderr(log_capture_buffer):
                # Start streaming with enhanced metrics capture
                stream = self.llm.create_chat_completion(
                    messages=messages,
                    max_tokens=active.get("max_tokens", 2048),
                    temperature=active["temperature"],
                    top_p=active["top_p"],
                    top_k=active.get("top_k", 40),
                    stream=True
                )

                response_parts = []
                for token_data in stream:
                    if self.stop_generation:
                        print("Generation stopped by user.")
                        break
                    handler.handle_token(token_data)
                    if 'choices' in token_data and len(token_data['choices']) > 0:
                        delta = token_data['choices'][0].get('delta', {})
                        content = delta.get('content', '')
                        if content:
                            response_parts.append(content)

            # After stream, parse the captured logs
            log_output = log_capture_buffer.getvalue()
            if log_output:
                self.metrics.parse_llama_logs(log_output)
                self.stream_queue.put(('metrics_update', ''))

                # Send token count info to the queue
                prompt_tokens = self.metrics.prompt_tokens
                response_tokens = self.metrics.eval_tokens
                token_info = f"\n(Prompt: {prompt_tokens} tokens, Response: {response_tokens} tokens)\n\n"
                self.stream_queue.put(('token_count_info', token_info))

            # Save complete response
            complete_response = ''.join(response_parts)
            self.last_assistant_response = complete_response
            self.chat_logger.append_log("RESPONSE", complete_response)
            # The old save_chat_message is now deprecated.
            # self.save_chat_message("assistant", complete_response)

        except Exception as e:
            self.stream_queue.put(('error', str(e)))
        finally:
            self.stream_queue.put(('enable_send', ''))

    # def save_chat_message(self, role: str, content: str) -> Optional[str]:
    #     """
    #     Saves a chat message to a file in the format expected by the system
    #     and returns the full path to the file.
    #     """
    #     if not self.settings_manager.settings:
    #         return None

    #     chat_dir = self.settings_manager.settings["paths"].get("chat", "")
    #     if not chat_dir:
    #         print("Chat directory not configured in settings.")
    #         return None

    #     os.makedirs(chat_dir, exist_ok=True)
    #     timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    #     filename = f"chat_{timestamp}.txt"
    #     filepath = os.path.join(chat_dir, filename)

    #     try:
    #         with open(filepath, 'w', encoding='utf-8') as f:
    #             if role == "user":
    #                 # The 'model' header acts as a marker for where the response begins
    #                 f.write(f"user\n{content}\n\nmodel\n")
    #             else:
    #                 # Assistant messages are just saved directly for logging
    #                 f.write(f"assistant\n{content}\n")
    #         return filepath
    #     except Exception as e:
    #         print(f"Error saving chat message: {e}")
    #         return None

    def process_queue(self):
        """Process messages from stream queue with enhanced handling"""
        try:
            while True:
                try:
                    message = self.stream_queue.get_nowait()

                    if message[0] == 'token':
                        if self.is_thinking:
                            self.remove_thinking_message()
                            self.is_thinking = False

                        _, content, msg_type = message
                        tag = f"{msg_type}_text"

                        if not hasattr(self, '_assistant_started'):
                            self.display_colored_message("Assistant: ", "assistant_text")
                            self._assistant_started = True

                        self.display_colored_message(content, tag)

                    elif message[0] == 'thinking':
                        # This handles the model's internal monologue, separate from the UI's "Thinking..."
                        _, thinking_content = message
                        self.chat_logger.append_log("THINKING", thinking_content)
                        self.display_colored_message(f"🤔 Thinking Log: {thinking_content[:150]}...\n\n", "thinking_text")

                    elif message[0] == 'finished':
                        if self.is_thinking: # Handles empty responses
                            self.remove_thinking_message()
                            self.is_thinking = False

                        self.update_status("Response complete", LYRN_SUCCESS)
                        self.set_model_status("Ready")
                        if hasattr(self, '_assistant_started'):
                            # The newline is now handled by the 'token_count_info' message
                            delattr(self, '_assistant_started')


                        # Check for pending jobs now that the model is idle
                        self._maybe_run_automated_job()

                    elif message[0] == 'show_loading':
                        self.show_loading_indicator()

                    elif message[0] == 'hide_loading':
                        self.hide_loading_indicator()

                    elif message[0] == 'token_count_info':
                        _, info_text = message
                        self.display_colored_message(info_text, "system_text")

                    elif message[0] == 'metrics_update':
                        self.update_enhanced_metrics()

                    elif message[0] == 'metrics_reset':
                        self.reset_metrics_display()

                    elif message[0] == 'error':
                        if self.is_thinking:
                            self.remove_thinking_message()
                            self.is_thinking = False
                        self.display_colored_message(f"Error: {message[1]}\n\n", "error")
                        self.update_status("Error occurred", LYRN_ERROR)

                    elif message[0] == 'enable_send':
                        self.send_btn.configure(state="normal")
                        self.stop_btn.configure(state="disabled")
                        if self.stop_generation:
                             self.update_status("Generation stopped.", LYRN_WARNING)
                             self.set_model_status("Ready")
                        self._write_llm_status("idle")
                        # Also check for jobs when the send button is re-enabled
                        self._maybe_run_automated_job()

                    elif message[0] == 'inject_trigger':
                        _, content = message
                        self.input_box.delete("1.0", "end")
                        self.input_box.insert("1.0", content)
                        self.send_message()

                    elif message[0] == 'status_update':
                        self.update_status(message[1], message[2])

                    elif message[0] == 'system_stats':
                        if hasattr(self, 'update_system_gauges'):
                            self.update_system_gauges(message[1])

                    elif message[0] == 'initialization_complete':
                        self._on_initialization_complete()

                except queue.Empty:
                    break

        except Exception as e:
            print(f"Error processing queue: {e}")

        self.after(50, self.process_queue)

    def update_job_dropdown(self):
        """Populates the manual job selection dropdown."""
        if hasattr(self, 'job_dropdown') and self.automation_controller:
            job_names = list(self.automation_controller.job_definitions.keys())
            self.job_dropdown.configure(values=job_names if job_names else ["No jobs loaded"])
            if not job_names:
                self.job_dropdown.set("No jobs loaded")
            else:
                self.job_dropdown.set(job_names[0])
        elif hasattr(self, 'job_dropdown'):
            self.job_dropdown.configure(values=["Loading..."])
            self.job_dropdown.set("Loading...")



    def update_enhanced_metrics(self):
        """Update enhanced metrics display with visual indicators"""
        if not hasattr(self, 'metrics'):
            return

        try:
            # Update labels
            self.kv_label.configure(text=f"KV Cache: {self.metrics.kv_cache_reused:,} tokens")
            self.prompt_label.configure(text=f"Prompt: {self.metrics.prompt_tokens:,} tokens")
            self.eval_label.configure(text=f"Generation: {self.metrics.eval_speed:.1f} tok/s")
            self.total_label.configure(text=f"Total: {self.metrics.total_tokens:,} tokens")

            # Update progress bar for KV cache and Total Tokens
            n_ctx = self.settings_manager.settings.get("active", {}).get("n_ctx", 1)
            if n_ctx > 0:
                kv_ratio = min(self.metrics.kv_cache_reused / n_ctx, 1.0)
                self.kv_progress.set(kv_ratio)

                total_ratio = min(self.metrics.total_tokens / n_ctx, 1.0)
                self.total_progress.set(total_ratio)

        except Exception as e:
            print(f"Error updating metrics: {e}")

    def reset_metrics_display(self):
        """Reset metrics display"""
        try:
            self.kv_label.configure(text="KV Cache: 0 tokens")
            self.prompt_label.configure(text="Prompt: 0 tokens")
            self.eval_label.configure(text="Generation: 0 tok/s")
            self.total_label.configure(text="Total: 0 tokens")
            self.kv_progress.set(0)
            self.speed_indicator.configure(text_color="#666666")
        except Exception as e:
            print(f"Error resetting metrics: {e}")

    def update_status(self, message: str, color: str = None):
        """Update enhanced status display"""
        if not hasattr(self, 'status_textbox'):
            return

        try:
            color = color or LYRN_SUCCESS

            self.status_textbox.configure(state="normal")
            self.status_textbox.delete("1.0", "end")
            self.status_textbox.insert("1.0", message)
            self.status_textbox.configure(state="disabled", text_color=color)

        except Exception as e:
            print(f"Error updating status: {e}")

    def clear_chat(self):
        """Clear chat display"""
        try:
            self.chat_display.configure(state="normal")
            self.chat_display.delete("0.0", "end")
            self.chat_display.configure(state="disabled")
            self.update_status("Chat display cleared", LYRN_INFO)
        except Exception as e:
            print(f"Error clearing chat: {e}")

    def open_chat_folder(self):
        """Opens the configured chat directory in the system's file explorer."""
        if not self.settings_manager.settings:
            self.update_status("Settings not loaded.", LYRN_ERROR)
            return

        chat_dir = self.settings_manager.settings["paths"].get("chat", "")
        if not chat_dir or not os.path.isdir(chat_dir):
            self.update_status("Chat directory not configured or found.", LYRN_WARNING)
            return

        try:
            if sys.platform == "win32":
                os.startfile(os.path.realpath(chat_dir))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", chat_dir])
            else:
                subprocess.Popen(["xdg-open", chat_dir])
            self.update_status("Opened chat folder.", LYRN_INFO)
        except Exception as e:
            self.update_status(f"Error opening folder: {e}", LYRN_ERROR)
            print(f"Error opening folder: {e}")

    def clear_chat_folder(self):
        """Deletes all files in the chat directory after confirmation."""
        from confirmation_dialog import ConfirmationDialog

        prefs = self.settings_manager.ui_settings.get("confirmation_preferences", {})
        if prefs.get("clear_chat_folder"):
            confirmed = True
        else:
            confirmed, dont_ask_again = ConfirmationDialog.show(
                self,
                self.theme_manager,
                title="Confirm Clear Directory",
                message="Are you sure you want to permanently delete all saved chat logs?"
            )
            if dont_ask_again:
                prefs["clear_chat_folder"] = True
                self.settings_manager.ui_settings["confirmation_preferences"] = prefs
                self.settings_manager.save_settings()

        if not confirmed:
            self.update_status("Clear chat folder cancelled.", LYRN_INFO)
            return

        if not self.settings_manager.settings:
            self.update_status("Settings not loaded.", LYRN_ERROR)
            return

        chat_dir = self.settings_manager.settings["paths"].get("chat", "")
        if not chat_dir or not os.path.exists(chat_dir):
            self.update_status("Chat directory not configured or found.", LYRN_WARNING)
            return

        try:
            file_count = 0
            for filename in os.listdir(chat_dir):
                file_path = os.path.join(chat_dir, filename)
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    file_count += 1
            self.update_status(f"Cleared {file_count} files from chat folder.", LYRN_SUCCESS)
            print(f"Cleared chat directory: {chat_dir}")
        except Exception as e:
            self.update_status("Error clearing chat folder.", LYRN_ERROR)
            print(f"Error clearing chat directory: {e}")

    def _watch_cycle_trigger_file(self):
        """Watches for the cycle trigger file and injects its content."""
        trigger_path = Path(SCRIPT_DIR) / "ipc" / "cycle_trigger.txt"
        while True:
            try:
                if trigger_path.exists():
                    content = trigger_path.read_text(encoding='utf-8')
                    trigger_path.unlink()
                    self.stream_queue.put(('inject_trigger', content))
            except Exception as e:
                print(f"Error in cycle trigger watcher: {e}")
            time.sleep(0.2)

    def _write_llm_status(self, status: str):
        """Writes the LLM's current status to the flag file."""
        path = Path(SCRIPT_DIR) / "global_flags" / "llm_status.txt"
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(status)
        except IOError:
            pass

    def refresh_active_cycle_selector(self):
        """Refreshes the active cycle selector dropdown in the main UI."""
        if hasattr(self, 'active_cycle_selector'):
            cycle_names = self.cycle_manager.get_cycle_names()
            self.active_cycle_selector.configure(values=cycle_names if cycle_names else [""])
            if not cycle_names:
                self.active_cycle_selector.set("")

    def toggle_cycle(self):
        """Starts or stops the selected cycle."""
        selected_cycle = self.active_cycle_selector.get()
        if not selected_cycle:
            self.update_status("No cycle selected to start.", LYRN_WARNING)
            return

        flag_path = Path(SCRIPT_DIR) / "global_flags" / "active_cycle.json"

        # Read current state
        current_state = {}
        if flag_path.exists():
            try:
                with open(flag_path, 'r', encoding='utf-8') as f:
                    current_state = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass

        # If the selected cycle is running, stop it. Otherwise, start it.
        if current_state.get("name") == selected_cycle and current_state.get("status") == "running":
            # Stop the cycle
            new_state = {"name": selected_cycle, "status": "stopped"}
            self.cycle_toggle_button.configure(text="Start")
            self.update_status(f"Cycle '{selected_cycle}' stopped.", LYRN_INFO)
        else:
            # Start the cycle
            new_state = {"name": selected_cycle, "status": "running", "current_step": 0}
            self.cycle_toggle_button.configure(text="Stop")
            self.update_status(f"Cycle '{selected_cycle}' started.", LYRN_SUCCESS)

        # Write the new state
        try:
            with open(flag_path, 'w', encoding='utf-8') as f:
                json.dump(new_state, f, indent=2)
        except IOError as e:
            self.update_status(f"Error updating cycle state: {e}", LYRN_ERROR)


def main():
    """Main entry point for LYRN-AI v7.0"""
    log_queue = queue.Queue()
    redirector = ConsoleRedirector(log_queue)
    redirector.start()

    try:
        print("Starting LYRN-AI Interface v7.0...")
        print("Enhanced features: Multi-colored text, Live theming, Advanced metrics")
        print(f"CustomTkinter version: {ctk.__version__}")

        root = ctk.CTk()
        root.withdraw()

        app = LyrnAIInterface(master=root, log_queue=log_queue)
        root.mainloop()

    except ImportError as e:
        # Stop redirection to print to the actual console
        redirector.stop()
        print(f"Import error: {e}")
        print("Please install required packages:")
        print("pip install customtkinter llama-cpp-python pillow psutil pynvml")
        input("Press Enter to exit...")

    except Exception as e:
        # Stop redirection to print to the actual console
        redirector.stop()
        print(f"Application error: {e}")
        import traceback
        traceback.print_exc()
        input("Press Enter to exit...")

    finally:
        redirector.stop()
        print("Application closed.")

if __name__ == "__main__":
    main()
