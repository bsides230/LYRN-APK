"""
LYRN-AI Interface v6.5 - GUI UPDATE

Major Updates:
- GUI UPDATE v6.4 to v6.5
- Update the perform updates
- always check the AGENTS.md for system messages
- use the feature_suggestions.md for the to build this update
- use the images/lyrn_logo.jpg to create a logo and replace the brain emoji
- system status needs to have more information and be arranged a little cleaner
- the theme settings
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
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from pathlib import Path
import shutil
from tkinter import colorchooser
from delta_manager import DeltaManager
from automation_controller import AutomationController
from heartbeat import get_heartbeat_job_prompt
from file_lock import SimpleFileLock

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
LYRN_PURPLE = "#880ED4"
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
    """A scrollable frame that supports drag-and-drop reordering of items."""
    def __init__(self, master, command=None, **kwargs):
        super().__init__(master, **kwargs)
        self.command = command
        self.items = []
        self.item_map = {}
        self.dragged_item = None

    def add_item(self, text, **kwargs):
        """Adds a new draggable item to the list."""
        item_frame = ctk.CTkFrame(self, corner_radius=3)
        item_frame.pack(fill="x", padx=5, pady=3)

        label = ctk.CTkLabel(item_frame, text=text, **kwargs)
        label.pack(side="left", padx=10, pady=5)

        # Bind events to the frame and the label
        for widget in [item_frame, label]:
            widget.bind("<ButtonPress-1>", lambda e, frame=item_frame: self._on_press(e, frame))
            widget.bind("<B1-Motion>", self._on_drag)
            widget.bind("<ButtonRelease-1>", self._on_release)

        self.items.append(item_frame)
        self.item_map[item_frame] = text

    def clear(self):
        """Removes all items from the list."""
        for item in self.items:
            item.destroy()
        self.items.clear()
        self.item_map.clear()

    def get_item_texts(self) -> List[str]:
        """Returns the list of item texts in their current order."""
        return [self.item_map[item] for item in self.items]

    def _on_press(self, event, widget):
        """Callback for when a mouse button is pressed on an item."""
        self.dragged_item = widget
        self.dragged_item.configure(fg_color=self.cget("fg_color")[0]) # Use the darker hover color
        self.dragged_item.lift()

    def _on_drag(self, event):
        """Callback for when an item is being dragged."""
        if not self.dragged_item:
            return

        # Move the item with the mouse
        y = self.dragged_item.winfo_y() + event.y
        self.dragged_item.place(x=0, y=y, anchor="nw")

    def _on_release(self, event):
        """Callback for when the mouse button is released."""
        if not self.dragged_item:
            return

        self.dragged_item.configure(fg_color="transparent") # Reset color

        # Determine the new index based on the drop position
        drop_y = self.dragged_item.winfo_y()

        # Find the target index
        target_index = 0
        for i, item in enumerate(self.items):
            if item == self.dragged_item:
                continue
            if drop_y > item.winfo_y():
                target_index = i + 1

        # Remove the dragged item and insert it at the new position
        original_item = self.dragged_item
        self.items.remove(original_item)
        self.items.insert(target_index, original_item)

        # Forget the 'place' geometry and repack all items in the new order
        original_item.place_forget()
        for item in self.items:
            item.pack_forget()
        for item in self.items:
            item.pack(fill="x", padx=5, pady=3)

        self.dragged_item = None

        # Execute the callback command if provided
        if self.command:
            self.command(self.get_item_texts())

class ThemeManager:
    """Discovers, loads, and applies themes from the 'themes' directory."""
    def __init__(self):
        self.themes_dir = os.path.join(SCRIPT_DIR, "themes")
        self.themes = {}
        self.current_theme_name = "LYRN Dark"  # Fallback default
        self.current_colors = {}
        self.load_available_themes()

    def load_available_themes(self):
        """Scans the themes directory and loads all valid .json theme files."""
        if not os.path.exists(self.themes_dir):
            print(f"Warning: Themes directory not found at {self.themes_dir}. Creating it.")
            os.makedirs(self.themes_dir)
            # Potentially create a default theme file here if needed
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
            print("FATAL: No themes found in the 'themes' directory. The application cannot start without a theme.")
            # In a real-world scenario, you might want to create a default theme file here.
            # For now, we will exit or let it fail gracefully.
            return

    def get_theme_names(self) -> List[str]:
        """Returns a list of available theme names."""
        return sorted(list(self.themes.keys()))

    def get_current_theme_name(self) -> str:
        return self.current_theme_name

    def get_color(self, color_name: str, fallback: str = "#FF00FF") -> str:
        """Gets a color from the current theme, with a bright pink fallback for easy debugging."""
        return self.current_colors.get(color_name, fallback)

    def apply_theme(self, theme_name: str):
        """Applies a theme by name, setting appearance mode and updating colors."""
        if theme_name not in self.themes:
            print(f"Error: Theme '{theme_name}' not found. Applying default.")
            if not self.get_theme_names():
                # This should not happen if fallback in load_available_themes works
                print("FATAL: No themes available to apply.")
                return
            theme_name = self.get_theme_names()[0]

        theme_data = self.themes[theme_name]
        self.current_theme_name = theme_name
        self.current_colors = theme_data.get("colors", {})

        appearance_mode = theme_data.get("appearance_mode", "dark")
        ctk.set_appearance_mode(appearance_mode)

        print(f"Theme '{theme_name}' applied with {appearance_mode} mode.")

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
            "window_size": "1400x900"
        }
        self.load_or_detect_first_boot()

    def load_or_detect_first_boot(self):
        """Load settings or detect first boot scenario"""
        if os.path.exists(SETTINGS_PATH):
            try:
                with open(SETTINGS_PATH, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.settings = data.get('settings', {})
                    self.ui_settings.update(data.get('ui_settings', {}))

                # Resolve relative paths
                if "paths" in self.settings:
                    for key, path in self.settings["paths"].items():
                        if path and not os.path.isabs(path):
                            self.settings["paths"][key] = os.path.join(SCRIPT_DIR, path)

                print("Settings loaded successfully")
                self.ensure_automation_flag()
                self.ensure_next_job_flag()
            except Exception as e:
                print(f"Error loading settings: {e}")
                self.first_boot = True
        else:
            print("No settings.json found - First boot detected")
            self.first_boot = True

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
        self.master_index_path = os.path.join(self.build_prompt_dir, "build_prompt_index.json")
        self.master_prompt_path = os.path.join(self.build_prompt_dir, "master_prompt.txt")

    def _load_json_file(self, path: str) -> Optional[List[str]]:
        """Safely loads a JSON file and returns its content."""
        if not os.path.exists(path):
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error reading JSON file {path}: {e}")
            return None

    def _save_json_file(self, path: str, data: List[str]):
        """Safely saves data to a JSON file."""
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            print(f"Master index saved to {path}")
        except IOError as e:
            print(f"Error writing JSON file {path}: {e}")

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

    def _build_master_prompt_file(self, master_index: List[str]):
        """Builds the master prompt file from the index."""
        print(f"Building master prompt file at {self.master_prompt_path}")
        prompt_parts = []
        for relative_path in master_index:
            full_path = os.path.join(self.build_prompt_dir, relative_path)
            content = self._load_text_file(full_path)
            if content:
                header = f"--- START OF {relative_path} ---\n"
                footer = f"\n--- END OF {relative_path} ---"
                prompt_parts.append(header + content + footer)

        full_prompt_text = "\n\n".join(prompt_parts)
        try:
            with open(self.master_prompt_path, 'w', encoding='utf-8') as f:
                f.write(full_prompt_text)
            print("Master prompt file built successfully.")
        except IOError as e:
            print(f"Error writing master prompt file: {e}")

    def generate_master_index(self) -> List[str]:
        """
        Scans for local indexes, aggregates them, saves the master index,
        and then builds the master prompt file.
        """
        print("Generating master prompt index...")
        master_index = []
        if not os.path.exists(self.build_prompt_dir):
            os.makedirs(self.build_prompt_dir)
            print(f"Created 'build_prompt' directory at {self.build_prompt_dir}")

        for root, _, files in os.walk(self.build_prompt_dir):
            if "_index.json" in files:
                index_path = os.path.join(root, "_index.json")
                local_index = self._load_json_file(index_path)

                if local_index and isinstance(local_index, list):
                    # Get the relative path of the directory from 'build_prompt'
                    relative_dir = os.path.relpath(root, self.build_prompt_dir)
                    for item in local_index:
                        # Join the relative directory with the item path
                        # If relative_dir is '.', it means the root of build_prompt, so don't prepend it.
                        if relative_dir == ".":
                            full_item_path = item
                        else:
                            full_item_path = os.path.join(relative_dir, item)
                        master_index.append(full_item_path.replace('\\', '/')) # Normalize path separators

        self._save_json_file(self.master_index_path, master_index)
        self._build_master_prompt_file(master_index)
        return master_index

    def load_base_prompt(self) -> str:
        """
        Loads the master prompt file. If it doesn't exist, generates it first.
        This represents the static part of the context.
        """
        print("Loading base prompt...")
        if not os.path.exists(self.master_prompt_path):
            print("Master prompt file not found. Generating a new one.")
            self.generate_master_index()

        return self._load_text_file(self.master_prompt_path)

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

class LogViewerPopup(ctk.CTkToplevel):
    """A popup window that displays redirected console output."""
    def __init__(self, parent, log_queue: queue.Queue, settings_manager: SettingsManager, theme_manager: ThemeManager):
        super().__init__(parent)
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

class ModelSelectorPopup(ctk.CTkToplevel):
    """A popup window to select a model and configure settings on startup."""
    def __init__(self, parent, settings_manager: SettingsManager, theme_manager: ThemeManager):
        super().__init__(parent)
        self.parent_app = parent
        self.settings_manager = settings_manager

        self.title("LYRN-AI Model Selector")
        self.geometry("600x450")
        self.minsize(500, 400)
        self.transient(parent) # Keep popup on top of main window
        self.grab_set() # Modal - prevent interaction with main window

        self.model_path = ""
        self.model_settings = {}
        self.dont_show_again = ctk.BooleanVar(value=False)

        self.create_widgets()
        self.load_models()
        self.load_current_settings()
        self.apply_theme()

    def apply_theme(self):
        """Applies the current theme colors to widgets in this popup."""
        primary_color = self.parent_app.theme_manager.get_color("primary")
        self.load_button.configure(fg_color=primary_color)
        # Apply theme to the top bar as well
        self.configure(fg_color=self.parent_app.theme_manager.get_color("frame_bg"))


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
        self.model_dropdown = ctk.CTkComboBox(model_frame, values=["No models found"], font=font)
        self.model_dropdown.pack(side="left", expand=True, fill="x", padx=10)

        # Model parameters
        params_frame = ctk.CTkFrame(main_frame)
        params_frame.pack(fill="x", padx=10, pady=10)
        ctk.CTkLabel(params_frame, text="Model Parameters", font=font).pack()

        grid_frame = ctk.CTkFrame(params_frame)
        grid_frame.pack(pady=10)

        params = [
            ("Context Size:", "n_ctx", 0, 0), ("Threads:", "n_threads", 0, 2),
            ("GPU Layers:", "n_gpu_layers", 1, 0)
        ]

        self.model_entries = {}
        for label, key, row, col in params:
            ctk.CTkLabel(grid_frame, text=label, font=font).grid(row=row, column=col, padx=10, pady=5, sticky="e")
            entry = ctk.CTkEntry(grid_frame, width=120, font=font)
            entry.grid(row=row, column=col+1, padx=10, pady=5, sticky="w")
            self.model_entries[key] = entry

        # Bottom frame for checkbox and buttons
        bottom_frame = ctk.CTkFrame(main_frame)
        bottom_frame.pack(fill="x", padx=10, pady=(20, 0))

        self.dont_show_checkbox = ctk.CTkCheckBox(
            bottom_frame, text="Don't show this again on startup",
            font=font, variable=self.dont_show_again
        )
        self.dont_show_checkbox.pack(side="left", padx=10)

        self.load_button = ctk.CTkButton(bottom_frame, text="Load Model", font=font, command=self.load_model)
        self.load_button.pack(side="right", padx=10)

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
                self.model_dropdown.configure(values=["No models found in 'models' folder"])
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
            entry.insert(0, str(active_settings.get(key, "")))

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
            try:
                new_active_settings[key] = int(value)
            except (ValueError, TypeError):
                print(f"Warning: Could not parse '{value}' for '{key}'. Using 0.")
                new_active_settings[key] = 0

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

class CommandPalette(ctk.CTkToplevel):
    def __init__(self, parent, commands: List[Dict[str, any]], theme_manager: ThemeManager):
        super().__init__(parent)
        self.parent_app = parent
        self.all_commands = commands
        self.filtered_commands = commands

        self.title("Command Palette")
        self.geometry("600x350")
        self.minsize(400, 300)
        self.transient(parent)
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

    def apply_theme(self):
        """Applies the current theme colors to widgets in this popup."""
        tm = self.parent_app.theme_manager
        self.configure(fg_color=tm.get_color("frame_bg"))
        self.results_frame.configure(fg_color=tm.get_color("frame_bg"))
        self.search_entry.configure(fg_color=tm.get_color("textbox_bg"), text_color=tm.get_color("textbox_fg"))

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

class TabbedSettingsDialog(ctk.CTkToplevel):
    """Enhanced settings dialog with tabs"""

    def __init__(self, parent, settings_manager: SettingsManager, theme_manager: ThemeManager, language_manager: LanguageManager):
        super().__init__(parent)
        self.settings_manager = settings_manager
        self.theme_manager = theme_manager
        self.language_manager = language_manager
        self.parent_app = parent

        self.title(self.language_manager.get("settings_window_title"))
        self.geometry("900x700")
        self.minsize(800, 600)

        self.transient(parent)
        self.grab_set()

        self.show_model_selector_var = ctk.BooleanVar()

        self.create_widgets()
        self.load_current_settings()
        self.apply_theme()
        self.refresh_prompt_index()

    def open_theme_builder(self):
        """Opens the theme builder popup."""
        if not hasattr(self, 'theme_builder_popup') or not self.theme_builder_popup.winfo_exists():
            self.theme_builder_popup = ThemeBuilderPopup(self, self.theme_manager, self.language_manager)
            self.theme_builder_popup.focus()
        else:
            self.theme_builder_popup.lift()
            self.theme_builder_popup.focus()

    def create_widgets(self):
        """Create tabbed interface"""
        # Main tabview
        self.tabview = ctk.CTkTabview(self, width=850, height=600)
        self.tabview.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        # Create tabs
        self.tab_model = self.tabview.add(self.language_manager.get("tab_model_config"))
        self.tab_paths = self.tabview.add(self.language_manager.get("tab_directory_paths"))
        self.tab_prompt = self.tabview.add(self.language_manager.get("tab_prompt_manager"))
        self.tab_theme_builder = self.tabview.add("Theme Builder")
        self.tab_ui_settings = self.tabview.add("UI Settings")
        self.tab_advanced = self.tabview.add(self.language_manager.get("tab_advanced"))

        self.create_model_tab()
        self.create_paths_tab()
        self.create_prompt_manager_tab()
        self.create_theme_builder_tab()
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

    def create_model_tab(self):
        """Create model configuration tab"""
        # Use Consolas font
        try:
            font = ctk.CTkFont(family="Consolas", size=12)
            title_font = ctk.CTkFont(family="Consolas", size=16, weight="bold")
        except:
            font = ("Consolas", 12)
            title_font = ("Consolas", 16, "bold")

        ctk.CTkLabel(self.tab_model, text="LYRN-AI Model Configuration",
                    font=title_font).pack(pady=20)

        # Model path
        ctk.CTkLabel(self.tab_model, text="Model Path:", font=font).pack(anchor="w", padx=20)
        self.model_path_entry = ctk.CTkEntry(self.tab_model, width=500, font=font)
        self.model_path_entry.pack(padx=20, pady=5, fill="x")

        # Parameters frame
        params_frame = ctk.CTkFrame(self.tab_model)
        params_frame.pack(fill="x", padx=20, pady=20)

        # Grid layout for parameters
        params = [
            ("Context Size:", "n_ctx", 0, 0), ("Threads:", "n_threads", 0, 2),
            ("GPU Layers:", "n_gpu_layers", 1, 0), ("Max Tokens:", "max_tokens", 1, 2),
            ("Temperature:", "temperature", 2, 0), ("Top P:", "top_p", 2, 2)
        ]

        self.model_entries = {}
        for label, key, row, col in params:
            ctk.CTkLabel(params_frame, text=label, font=font).grid(
                row=row, column=col, padx=10, pady=5, sticky="w")
            entry = ctk.CTkEntry(params_frame, width=100, font=font)
            entry.grid(row=row, column=col+1, padx=10, pady=5)
            self.model_entries[key] = entry

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

        reload_model_button = ctk.CTkButton(model_frame, text="🔄 Reload Model (Full)",
                        font=font, command=self.reload_model_full)
        reload_model_button.pack(side="left", padx=5, pady=5)
        Tooltip(reload_model_button, self.parent_app.tooltips.get("reload_model_full_button", ""))

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

    def create_prompt_manager_tab(self):
        """Create the prompt manager tab UI."""
        try:
            font = ctk.CTkFont(family="Consolas", size=12)
            title_font = ctk.CTkFont(family="Consolas", size=14, weight="bold")
        except:
            font = ("Consolas", 12)
            title_font = ("Consolas", 14, "bold")

        ctk.CTkLabel(self.tab_prompt, text="Prompt Build Order", font=title_font).pack(pady=10)

        # Frame for buttons
        button_frame = ctk.CTkFrame(self.tab_prompt)
        button_frame.pack(fill="x", padx=20, pady=10)

        refresh_button = ctk.CTkButton(button_frame, text="🔄 Refresh Index from Subfolders",
                        font=font, command=self.refresh_prompt_index)
        refresh_button.pack(side="left", padx=10)
        Tooltip(refresh_button, self.parent_app.tooltips.get("refresh_prompt_index_button", ""))

        save_mode_button = ctk.CTkButton(button_frame, text="💾 Save as Mode",
                        font=font, command=self.save_as_mode)
        save_mode_button.pack(side="left", padx=10)
        Tooltip(save_mode_button, self.parent_app.tooltips.get("save_as_mode_button", ""))

        # Frame for the list
        list_frame = ctk.CTkFrame(self.tab_prompt)
        list_frame.pack(expand=True, fill="both", padx=20, pady=10)

        self.prompt_dnd_list = DraggableListbox(list_frame, label_text="Indexed Files (drag to reorder)", command=self.on_prompt_list_reorder)
        self.prompt_dnd_list.pack(expand=True, fill="both", padx=5, pady=5)

        self.update_prompt_file_list()


    def on_prompt_list_reorder(self, new_order: List[str]):
        """Callback function to save the new prompt order."""
        print(f"New prompt order: {new_order}")
        # Save the new order to the master index file
        master_index_path = self.parent_app.snapshot_loader.master_index_path
        try:
            with open(master_index_path, 'w', encoding='utf-8') as f:
                json.dump(new_order, f, indent=2)
            print(f"Master index saved to {master_index_path}")
            # Rebuild the master prompt file using the new order
            self.parent_app.snapshot_loader._build_master_prompt_file(new_order)
            self.parent_app.update_status("Prompt order saved and rebuilt", LYRN_SUCCESS)
        except IOError as e:
            print(f"Error writing master index file {master_index_path}: {e}")
            self.parent_app.update_status("Error saving prompt order", LYRN_ERROR)

    def create_theme_builder_tab(self):
        """Create the theme builder tab UI with an advanced preview."""
        try:
            font = ctk.CTkFont(family="Consolas", size=12)
            title_font = ctk.CTkFont(family="Consolas", size=14, weight="bold")
        except:
            font = ("Consolas", 12)
            title_font = ("Consolas", 14, "bold")

        ctk.CTkLabel(self.tab_theme_builder, text="Theme Builder", font=title_font).pack(pady=10)

        # Main frame for the builder
        main_frame = ctk.CTkFrame(self.tab_theme_builder)
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
        color_code = colorchooser.askcolor(initialcolor=initial_color, title="Choose color")
        if color_code and color_code[1]:
            new_color = color_code[1]
            self.color_widgets[key]['label'].configure(text=new_color)
            self.color_widgets[key]['swatch'].configure(fg_color=new_color)
            self.preview_theme()

    def apply_preview_theme(self):
        """Applies the current settings in the theme builder for a live preview."""
        theme_name = self.theme_name_entry.get()
        if not theme_name:
            # Maybe show a small error label? For now, just print.
            print("Please enter a theme name to apply a preview.")
            return

        # 1. Collect the colors from the widgets
        preview_colors = {key: widgets['label'].cget("text") for key, widgets in self.color_widgets.items()}

        # 2. Update the theme manager's state directly
        self.theme_manager.current_theme_name = f"{theme_name} (Preview)"
        self.theme_manager.current_colors = preview_colors
        # Note: We are not changing the appearance mode here, just colors.

        # 3. Trigger the main application to re-apply the theme from the manager's current state
        self.parent_app.apply_color_theme()

        # 4. Also re-apply to the settings dialog itself
        self.apply_theme()

        self.parent_app.update_status(f"Previewing theme: {theme_name}", LYRN_INFO)

    def preview_theme(self):
        """Updates the advanced preview area with the current colors."""
        colors = {key: widgets['label'].cget("text") for key, widgets in self.color_widgets.items()}

        # Get all the colors with fallbacks
        primary = colors.get("primary", "#007BFF")
        accent = colors.get("accent", "#28A745")
        frame_bg = colors.get("frame_bg", "#F8F9FA")
        textbox_bg = colors.get("textbox_bg", "#FFFFFF")
        textbox_fg = colors.get("textbox_fg", "#212529")
        label_text = colors.get("label_text", "#495057")
        border = colors.get("border_color", "#DEE2E6")
        # A reasonable default for button text color is the textbox background
        button_text_color = colors.get("textbox_bg", "#FFFFFF")


        # Apply colors to preview widgets
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
        """Deletes the currently selected theme."""
        theme_name = self.theme_selector_combo.get()
        if not theme_name or theme_name not in self.theme_manager.themes:
            return

        # Simple confirmation dialog
        dialog = ctk.CTkInputDialog(text=f"Type DELETE to confirm deleting theme '{theme_name}':", title="Confirm Deletion")
        confirmation = dialog.get_input()

        if confirmation != "DELETE":
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
            # TODO: Show an error message
            return

        theme_data = {
            "name": theme_name,
            "appearance_mode": "dark", # TODO: Add a way to select this
            "colors": {}
        }

        for key, widgets in self.color_widgets.items():
            theme_data["colors"][key] = widgets['label'].cget("text")

        themes_dir = os.path.join(SCRIPT_DIR, "themes")
        os.makedirs(themes_dir, exist_ok=True)

        filename = f"{theme_name.lower().replace(' ', '_')}.json"
        filepath = os.path.join(themes_dir, filename)

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(theme_data, f, indent=4)

            # Refresh themes and update all dropdowns
            self.parent_app.theme_manager.load_available_themes()
            new_theme_names = self.parent_app.theme_manager.get_theme_names()

            self.parent_app.theme_dropdown.configure(values=new_theme_names)
            self.theme_selector_combo.configure(values=new_theme_names)

            # Select the newly saved theme
            self.parent_app.theme_dropdown.set(theme_name)
            self.theme_selector_combo.set(theme_name)

            self.parent_app.update_status(f"Theme '{theme_name}' saved", LYRN_SUCCESS)
        except Exception as e:
            print(f"Error saving theme: {e}")
            self.parent_app.update_status("Error saving theme", LYRN_ERROR)

    def update_prompt_file_list(self):
        """Reads the master index and displays it in the draggable list."""
        # Clear existing widgets
        self.prompt_dnd_list.clear()

        # Get the master index from the snapshot_loader instance
        master_index_path = self.parent_app.snapshot_loader.master_index_path
        try:
            with open(master_index_path, 'r', encoding='utf-8') as f:
                index_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            index_data = [] # If file doesn't exist or is invalid, show an empty list

        if not index_data:
            ctk.CTkLabel(self.prompt_dnd_list, text="No files in index. Click Refresh to generate.").pack(pady=10)
            return

        for filepath in index_data:
            self.prompt_dnd_list.add_item(filepath)

    def refresh_prompt_index(self):
        """Calls the prompt builder to regenerate the index and updates the UI."""
        print("UI triggered prompt index refresh.")
        self.parent_app.snapshot_loader.generate_master_index()
        self.update_prompt_file_list()
        self.parent_app.update_status("Prompt index refreshed", LYRN_SUCCESS)

    def save_as_mode(self):
        """Saves the current master prompt as a new mode."""
        dialog = ctk.CTkInputDialog(text="Enter a name for this mode:", title="Save Mode")
        mode_name = dialog.get_input()

        if mode_name:
            # Sanitize the mode name to be a valid filename
            safe_mode_name = "".join(c for c in mode_name if c.isalnum() or c in (' ', '_')).rstrip()
            if not safe_mode_name:
                print("Invalid mode name provided.")
                # Optionally, show an error to the user
                return

            modes_dir = os.path.join(SCRIPT_DIR, "build_prompt", "modes")
            os.makedirs(modes_dir, exist_ok=True)

            master_prompt_path = self.parent_app.snapshot_loader.master_prompt_path
            mode_filepath = os.path.join(modes_dir, f"{safe_mode_name}.txt")

            try:
                with open(master_prompt_path, 'r', encoding='utf-8') as f_read:
                    content = f_read.read()

                with open(mode_filepath, 'w', encoding='utf-8') as f_write:
                    f_write.write(content)

                print(f"Mode '{safe_mode_name}' saved successfully to {mode_filepath}")
                self.parent_app.update_status(f"Mode '{safe_mode_name}' saved", LYRN_SUCCESS)

                # Refresh the mode dropdown in the main GUI
                if hasattr(self.parent_app, 'update_modes_dropdown'):
                    self.parent_app.update_modes_dropdown()

            except FileNotFoundError:
                print(f"Error: Master prompt file not found at {master_prompt_path}")
                self.parent_app.update_status("Error: Master prompt not found", LYRN_ERROR)
            except Exception as e:
                print(f"Error saving mode: {e}")
                self.parent_app.update_status(f"Error saving mode", LYRN_ERROR)

    def load_current_settings(self):
        """Load current settings into all tabs"""
        if not self.settings_manager.settings:
            return

        settings = self.settings_manager.settings
        active = settings.get("active", {})
        paths = settings.get("paths", {})

        # Load model settings
        self.model_path_entry.insert(0, active.get("model_path", ""))
        for key, entry in self.model_entries.items():
            entry.insert(0, str(active.get(key, "")))

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
            (ctk.CTkEntry, {"fg_color": textbox_bg, "text_color": textbox_fg, "border_color": accent_color}),
            (ctk.CTkTextbox, {"fg_color": textbox_bg, "text_color": textbox_fg, "border_color": accent_color}),
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
        """Clear chat directory"""
        if not self.settings_manager.settings:
            return

        chat_dir = self.settings_manager.settings["paths"].get("chat", "")
        if chat_dir and os.path.exists(chat_dir):
            try:
                for filename in os.listdir(chat_dir):
                    file_path = os.path.join(chat_dir, filename)
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                print(f"Cleared chat directory: {chat_dir}")
            except Exception as e:
                print(f"Error clearing chat directory: {e}")

    def clear_deltas_directory(self):
        """Clear deltas directory"""
        if not self.settings_manager.settings:
            return

        deltas_dir = self.settings_manager.settings["paths"].get("deltas", "")
        if deltas_dir and os.path.exists(deltas_dir):
            try:
                for filename in os.listdir(deltas_dir):
                    file_path = os.path.join(deltas_dir, filename)
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                print(f"Cleared deltas directory: {deltas_dir}")
            except Exception as e:
                print(f"Error clearing deltas directory: {e}")

    def clear_metrics_logs(self):
        """Clear metrics logs directory"""
        metrics_dir = os.path.join(SCRIPT_DIR, "metrics_logs")
        if os.path.exists(metrics_dir):
            try:
                for filename in os.listdir(metrics_dir):
                    file_path = os.path.join(metrics_dir, filename)
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                print(f"Cleared metrics logs: {metrics_dir}")
            except Exception as e:
                print(f"Error clearing metrics logs: {e}")

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

            # Save model settings
            settings["active"]["model_path"] = self.model_path_entry.get()
            for key, entry in self.model_entries.items():
                value = entry.get()
                if key in ["temperature", "top_p"]:
                    settings["active"][key] = float(value) if value else 0.0
                else:
                    settings["active"][key] = int(value) if value else 0

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

class PersonalityPopup(ctk.CTkToplevel):
    """A popup window for adjusting personality traits with sliders."""

    def __init__(self, parent, delta_manager):
        super().__init__(parent)
        self.parent_app = parent
        self.delta_manager = delta_manager
        self.personality_file = Path(SCRIPT_DIR) / "personality.json"
        self.data = self._load_data()

        self.title("Personality Sliders")
        self.geometry("450x550")
        self.transient(parent)
        # self.grab_set() # Removed to allow other windows to be opened

        self.initial_traits = self.data.get("active_traits", {}).copy()
        self.current_traits = self.initial_traits.copy()

        self.sliders = {}
        self.labels = {}
        self.preset_var = ctk.StringVar()

        self.create_widgets()
        self.populate_sliders()
        self.populate_presets()

    def _load_data(self):
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
                        "traits": {
                            "creativity": 500,
                            "consistency": 750,
                            "verbosity": 400,
                            "assertiveness": 600,
                            "curiosity": 800
                        }
                    }
                },
                "active_traits": {
                    "creativity": 500,
                    "consistency": 750,
                    "verbosity": 400,
                    "assertiveness": 600,
                    "curiosity": 800
                }
            }
            try:
                with open(self.personality_file, 'w', encoding='utf-8') as f:
                    json.dump(default_data, f, indent=2)
            except IOError as e:
                print(f"Error creating default personality.json: {e}")
            return default_data

    def _save_data(self):
        """Saves the current personality data to the JSON file."""
        try:
            with open(self.personality_file, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2)
        except IOError as e:
            print(f"Error saving personality file: {e}")

    def create_widgets(self):
        """Create the main widgets for the popup."""
        # Preset management frame
        preset_frame = ctk.CTkFrame(self)
        preset_frame.pack(fill="x", padx=10, pady=10)
        ctk.CTkLabel(preset_frame, text="Presets:").pack(side="left", padx=5)
        self.preset_menu = ctk.CTkComboBox(preset_frame, variable=self.preset_var, command=self.load_preset)
        self.preset_menu.pack(side="left", expand=True, fill="x", padx=5)

        save_preset_button = ctk.CTkButton(preset_frame, text="Save", width=60, command=self.save_preset)
        save_preset_button.pack(side="left", padx=5)

        self.main_frame = ctk.CTkScrollableFrame(self, label_text="Active Traits")
        self.main_frame.pack(expand=True, fill="both", padx=10, pady=0)

        # Bottom button frame
        button_frame = ctk.CTkFrame(self)
        button_frame.pack(fill="x", padx=10, pady=10)

        ctk.CTkButton(button_frame, text="Cancel", command=self.destroy).pack(side="right", padx=(10,0))
        ctk.CTkButton(button_frame, text="Apply", command=self.apply_changes).pack(side="right")


    def populate_sliders(self):
        """Creates or updates sliders based on the data in active_traits."""
        for widget in self.main_frame.winfo_children():
            widget.destroy()

        for trait, value in self.current_traits.items():
            frame = ctk.CTkFrame(self.main_frame)
            frame.pack(fill="x", pady=5, padx=5)

            label_text = f"{trait.capitalize()}: {value}"
            label = ctk.CTkLabel(frame, text=label_text, width=150, anchor="w")
            label.pack(side="left", padx=10)
            self.labels[trait] = label

            slider = ctk.CTkSlider(frame, from_=0, to=1000, number_of_steps=1000,
                                   command=lambda v, t=trait: self._on_slider_change(t, v))
            slider.set(value)
            slider.pack(side="left", expand=True, fill="x", padx=10)
            self.sliders[trait] = slider

    def populate_presets(self):
        """Populates the preset dropdown menu."""
        presets = list(self.data.get("presets", {}).keys())
        self.preset_menu.configure(values=["Custom"] + presets)

        active_preset_name = "Custom"
        for name, preset_data in self.data.get("presets", {}).items():
            if preset_data.get("traits") == self.current_traits:
                active_preset_name = name
                break
        self.preset_var.set(active_preset_name)

    def _on_slider_change(self, trait_name: str, new_value: float):
        """Callback when a slider value changes, updates the label and current_traits."""
        int_value = int(new_value)
        self.labels[trait_name].configure(text=f"{trait_name.capitalize()}: {int_value}")
        self.current_traits[trait_name] = int_value
        self.populate_presets()

    def apply_changes(self):
        """Applies the changes made to the sliders and keeps the window open."""
        changes_applied = False
        for trait, value in self.current_traits.items():
            if self.initial_traits.get(trait) != value:
                print(f"Delta: {trait} changed from {self.initial_traits.get(trait)} to {value}")
                self.delta_manager.create_delta(
                    "P-001", "personality", "traits", "update",
                    trait, str(value)
                )
                changes_applied = True

        if changes_applied:
            self.data["active_traits"] = self.current_traits
            self._save_data()
            # Update the initial traits to the newly applied ones
            self.initial_traits = self.current_traits.copy()
            self.parent_app.update_status("Personality changes applied.", LYRN_SUCCESS)
        else:
            self.parent_app.update_status("No changes to apply.", LYRN_INFO)
        # self.destroy() is removed to keep the window open

    def load_preset(self, preset_name: str):
        """Loads a selected preset's traits into the active sliders."""
        if preset_name == "Custom":
            return
        preset_traits = self.data.get("presets", {}).get(preset_name, {}).get("traits")
        if preset_traits:
            self.current_traits = preset_traits.copy()
            self.populate_sliders()
            self.populate_presets()

    def save_preset(self):
        """Saves the current active traits as a new preset."""
        dialog = ctk.CTkInputDialog(text="Enter a name for the new preset:", title="Save Preset")
        preset_name = dialog.get_input()

        if preset_name and preset_name not in ["Custom"]:
            self.data["presets"][preset_name] = {
                "description": "User-saved preset.",
                "traits": self.current_traits.copy()
            }
            self._save_data()
            self.populate_presets()
            self.preset_var.set(preset_name)


class ThemeBuilderPopup(ctk.CTkToplevel):
    """A popup window for creating and editing themes."""
    def __init__(self, parent, theme_manager, language_manager):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self.language_manager = language_manager
        self.parent_app = parent.parent_app # Get the main app reference

        self.title("Theme Builder")
        self.geometry("800x650")
        self.minsize(700, 500)

        self.transient(parent)
        self.grab_set()

        self.create_theme_builder_widgets()
        self.load_selected_theme(self.theme_manager.get_current_theme_name())
        self.preview_theme()


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
        color_code = colorchooser.askcolor(initialcolor=initial_color, title="Choose color")
        if color_code and color_code[1]:
            new_color = color_code[1]
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
        """Deletes the currently selected theme."""
        theme_name = self.theme_selector_combo.get()
        if not theme_name or theme_name not in self.theme_manager.themes:
            return
        dialog = ctk.CTkInputDialog(text=f"Type DELETE to confirm deleting theme '{theme_name}':", title="Confirm Deletion")
        confirmation = dialog.get_input()
        if confirmation != "DELETE":
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


class LyrnAIInterface(ctk.CTkToplevel):
    """Main LYRN-AI interface with enhanced features"""

    def __init__(self, master, log_queue: queue.Queue):
        super().__init__(master)

        self.log_queue = log_queue

        # Initialize core components
        self.settings_manager = SettingsManager()
        self.theme_manager = ThemeManager()
        saved_language = self.settings_manager.ui_settings.get("language", "en")
        self.language_manager = LanguageManager(language=saved_language)

        # Apply saved theme or default
        saved_theme = self.settings_manager.ui_settings.get("theme", "LYRN Dark")
        self.theme_manager.apply_theme(saved_theme)

        self.llm = None
        self.first_boot_complete = False
        self.is_thinking = False
        self.is_minimized = False
        self.current_assistant_message_label = None
        self.stream_queue = queue.Queue()
        self.resource_monitor = SystemResourceMonitor(self.stream_queue)
        self.last_assistant_response = ""
        self._maximized = False
        self._geom_before_maximize = ""

        # Initialize font size
        self.current_font_size = self.settings_manager.ui_settings.get("font_size", 12)

        # Setup GUI
        self.setup_window()
        self.load_tooltips()
        self.create_widgets()
        self.apply_color_theme()

        # Handle window closing
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.bind("<Control-Shift-P>", self.open_command_palette)

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

    def start_application_logic(self):
        if self.settings_manager.ui_settings.get("autoload_model", False) and self.settings_manager.settings.get("active", {}).get("model_path"):
            self.update_status("Autoloading model...", LYRN_INFO)
            threading.Thread(target=self.setup_model, daemon=True).start()
        elif self.settings_manager.first_boot or self.settings_manager.ui_settings.get("show_model_selector", True):
            self.open_model_selector()

        if self.settings_manager.ui_settings.get("llm_log_visible", False):
            self.toggle_log_viewer()

        self.initialize_application()

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
        self.title("LYRN-AI Interface v6.7")
        size = self.settings_manager.ui_settings.get("window_size", "1400x900")
        self.geometry(size)
        self.minsize(1200, 800)

        # Set taskbar icon
        try:
            icon_path = os.path.join(SCRIPT_DIR, "images", "favicon.ico")
            if os.path.exists(icon_path):
                self.iconbitmap(icon_path)
            else:
                print("Warning: favicon.ico not found.")
        except Exception as e:
            print(f"Error setting taskbar icon: {e}")

    def handle_first_boot(self):
        """Handle first boot scenario"""
        print("Handling first boot...")

        def on_first_boot_complete():
            self.first_boot_complete = True
            self.initialize_application()

        # Show simplified first boot dialog (implement as needed)
        self.after(100, lambda: self.initialize_application())

    def initialize_application(self):
        """Initialize application after settings are configured"""
        if not self.settings_manager.settings:
            print("ERROR: No settings available for initialization!")
            return

        # Initialize remaining components
        self.snapshot_loader = SnapshotLoader(self.settings_manager)
        self.delta_manager = DeltaManager()
        self.automation_controller = AutomationController()
        self.metrics = EnhancedPerformanceMetrics()

        # Start background services
        self.resource_monitor.start()
        self.after(100, self.process_queue)

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
                chat_format="qwen",
                add_bos=True,
                add_eos=True,
                verbose=True
            )
            print("LYRN-AI model loaded successfully")
            self.stream_queue.put(('status_update', 'Model Loaded', LYRN_SUCCESS))
            self.set_model_status("Ready")

        except Exception as e:
            print(f"Error loading model: {e}")
            self.llm = None
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

        # Job Automation Section
        self.job_frame = ctk.CTkFrame(self.left_sidebar, fg_color="transparent", border_width=0)
        self.job_frame.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(self.job_frame, text="Job Automation", font=section_font).pack(pady=10)

        # Job selection dropdown for manual testing
        ctk.CTkLabel(self.job_frame, text="Manual Job Selection", font=normal_font).pack(pady=(10, 5))
        job_names = list(self.automation_controller.job_definitions.keys()) if hasattr(self, 'automation_controller') else []
        self.job_dropdown = ctk.CTkComboBox(
            self.job_frame, values=job_names,
            command=self.on_job_selected, font=normal_font,
            button_color=LYRN_PURPLE, button_hover_color=LYRN_ACCENT
        )
        self.job_dropdown.pack(padx=10, pady=(0, 15), fill="x")
        Tooltip(self.job_dropdown, self.tooltips.get("job_dropdown", ""))

        # Quick controls frame
        self.quick_frame = ctk.CTkFrame(self.left_sidebar, fg_color="transparent", border_width=0)
        self.quick_frame.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(self.quick_frame, text="Quick Controls", font=section_font).pack(pady=10)

        self.settings_button = ctk.CTkButton(self.quick_frame, text="⚙️ Settings", command=self.open_settings)
        self.settings_button.pack(fill="x", padx=10, pady=(0, 5))
        Tooltip(self.settings_button, self.tooltips.get("settings_button", "Open the settings window"))

        self.change_model_button = ctk.CTkButton(self.quick_frame, text="🔄 Change Model", command=self.open_model_selector)
        self.change_model_button.pack(fill="x", padx=10, pady=(0, 5))
        Tooltip(self.change_model_button, "Open the model selector to change the loaded model.")

        # Theme selection
        theme_frame = ctk.CTkFrame(self.quick_frame)
        theme_frame.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(theme_frame, text="Theme:", font=normal_font).pack(side="left", padx=5)
        self.theme_dropdown = ctk.CTkComboBox(
            theme_frame,
            values=self.theme_manager.get_theme_names(),
            command=self.on_theme_selected
        )
        self.theme_dropdown.pack(side="right", padx=5, expand=True, fill="x")
        self.theme_dropdown.set(self.theme_manager.get_current_theme_name())
        Tooltip(self.theme_dropdown, self.tooltips.get("theme_dropdown", ""))

        # Font size controls
        font_frame = ctk.CTkFrame(self.quick_frame)
        font_frame.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(font_frame, text="Font Size:", font=normal_font).pack(side="left", padx=5)
        self.font_decrease_button = ctk.CTkButton(font_frame, text="A-", width=30, height=25,
                     font=normal_font,
                     command=self.decrease_font_size)
        self.font_decrease_button.pack(side="right", padx=2)
        Tooltip(self.font_decrease_button, self.tooltips.get("font_decrease_button", ""))

        self.font_increase_button = ctk.CTkButton(font_frame, text="A+", width=30, height=25,
                     font=normal_font,
                     command=self.increase_font_size)
        self.font_increase_button.pack(side="right", padx=2)
        Tooltip(self.font_increase_button, self.tooltips.get("font_increase_button", ""))

        # Mode selection
        mode_frame = ctk.CTkFrame(self.quick_frame)
        mode_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(mode_frame, text="Mode:", font=normal_font).pack(side="left", padx=5)
        self.mode_dropdown = ctk.CTkComboBox(
            mode_frame,
            values=[],
            command=self.on_mode_selected
        )
        self.mode_dropdown.pack(side="left", expand=True, fill="x", padx=5)
        Tooltip(self.mode_dropdown, self.tooltips.get("mode_dropdown", ""))

        self.refresh_prompt_button = ctk.CTkButton(mode_frame, text="🔄", width=30, height=25,
                                         font=normal_font,
                                         command=self.refresh_prompt_from_mode)
        self.refresh_prompt_button.pack(side="right", padx=2)
        Tooltip(self.refresh_prompt_button, self.tooltips.get("refresh_prompt_button", ""))

        self.update_modes_dropdown()

        # Other controls moved from System Controls
        self.show_llm_log_button = ctk.CTkButton(self.quick_frame, text="📋 View Logs",
                                                 font=normal_font, command=self.toggle_log_viewer)
        self.show_llm_log_button.pack(padx=10, pady=3, fill="x")
        Tooltip(self.show_llm_log_button, self.tooltips.get("show_llm_log_button", ""))

        self.clear_chat_folder_button = ctk.CTkButton(self.quick_frame, text="📁 Clear Chat Folder",
                                                      font=normal_font, command=self.clear_chat_folder)
        self.clear_chat_folder_button.pack(padx=10, pady=3, fill="x")
        Tooltip(self.clear_chat_folder_button, "Deletes all saved chat log files from the chat directory.")

        self.personality_button = ctk.CTkButton(self.quick_frame, text="🧠 Personality", command=self.open_personality_popup)
        self.personality_button.pack(fill="x", padx=10, pady=3)
        Tooltip(self.personality_button, "Adjust the AI's personality traits.")

        self.terminal_button = ctk.CTkButton(self.quick_frame, text="📟 Code Terminal", command=self.open_terminal)
        self.terminal_button.pack(fill="x", padx=10, pady=3)
        Tooltip(self.terminal_button, "Opens a new terminal in the specified directory.")

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

        return self.right_sidebar

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

        self.kv_label = ctk.CTkLabel(kv_frame, text="KV Cache: 0 tokens",
                                    font=normal_font)
        self.kv_label.pack(side="left", padx=5)

        self.kv_progress = ctk.CTkProgressBar(kv_frame, width=100, height=8)
        self.kv_progress.pack(side="right", padx=5)
        self.kv_progress.set(0)

        # Prompt tokens
        self.prompt_label = ctk.CTkLabel(self.metrics_frame, text="Prompt: 0 tokens",
                                        font=normal_font)
        self.prompt_label.pack(pady=2)

        # Generation speed
        self.eval_label = ctk.CTkLabel(self.metrics_frame, text="Generation: 0 tok/s",
                                     font=normal_font)
        self.eval_label.pack(pady=2)

        # Total tokens
        total_frame = ctk.CTkFrame(self.metrics_frame)
        total_frame.pack(fill="x", padx=10, pady=2)

        self.total_label = ctk.CTkLabel(total_frame, text="Total: 0 tokens",
                                       font=normal_font)
        self.total_label.pack(side="left", padx=5)

        self.total_progress = ctk.CTkProgressBar(total_frame, width=100, height=8)
        self.total_progress.pack(side="right", padx=5)
        self.total_progress.set(0)

        # Save metrics button
        ctk.CTkButton(self.metrics_frame, text="💾 Save Metrics",
                     font=normal_font, height=25, command=self.save_metrics_log).pack(
                         padx=10, pady=(5, 10), fill="x")

        # System Resource Gauges
        ctk.CTkLabel(self.metrics_frame, text="System Resources", font=section_font).pack(pady=(10,5))

        # CPU
        cpu_frame = ctk.CTkFrame(self.metrics_frame)
        cpu_frame.pack(fill="x", padx=10, pady=2)
        self.cpu_label = ctk.CTkLabel(cpu_frame, text="CPU: 0.0% (N/A)", font=normal_font)
        self.cpu_label.pack(side="left", padx=5)
        self.cpu_progress = ctk.CTkProgressBar(cpu_frame, width=100, height=8, progress_color="#F59E0B")
        self.cpu_progress.pack(side="right", padx=5)
        self.cpu_progress.set(0)

        # RAM
        ram_frame = ctk.CTkFrame(self.metrics_frame)
        ram_frame.pack(fill="x", padx=10, pady=2)
        self.ram_label = ctk.CTkLabel(ram_frame, text="RAM: 0.0%", font=normal_font)
        self.ram_label.pack(side="left", padx=5)
        self.ram_progress = ctk.CTkProgressBar(ram_frame, width=100, height=8, progress_color="#3B82F6")
        self.ram_progress.pack(side="right", padx=5)
        self.ram_progress.set(0)

        # Disk
        disk_frame = ctk.CTkFrame(self.metrics_frame)
        disk_frame.pack(fill="x", padx=10, pady=2)
        self.disk_label = ctk.CTkLabel(disk_frame, text="Disk: 0.0%", font=normal_font)
        self.disk_label.pack(side="left", padx=5)
        self.disk_progress = ctk.CTkProgressBar(disk_frame, width=100, height=8, progress_color=LYRN_SUCCESS)
        self.disk_progress.pack(side="right", padx=5)
        self.disk_progress.set(0)

        # VRAM (only if NVIDIA GPU is detected)
        if self.resource_monitor.nvml_initialized:
            vram_frame = ctk.CTkFrame(self.metrics_frame)
            vram_frame.pack(fill="x", padx=10, pady=2)
            self.vram_label = ctk.CTkLabel(vram_frame, text="VRAM: 0.0%", font=normal_font)
            self.vram_label.pack(side="left", padx=5)
            self.vram_progress = ctk.CTkProgressBar(vram_frame, width=100, height=8, progress_color="#EF4444")
            self.vram_progress.pack(side="right", padx=5)
            self.vram_progress.set(0)
        else:
            # Create dummy attributes so update method doesn't fail
            self.vram_label = None
            self.vram_progress = None

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
        if self.resource_monitor.nvml_initialized and self.vram_label is not None:
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
        self.status_textbox.pack(fill="x", pady=5)
        self.status_textbox.insert("end", "System ready.")
        self.status_textbox.configure(state="disabled")

        # New frame for the buttons
        button_frame = ctk.CTkFrame(self.status_frame, fg_color="transparent")
        button_frame.pack(fill="x", pady=5)

        # Model Control Buttons that fill the space
        self.offload_model_button = ctk.CTkButton(button_frame, text="Offload", font=normal_font, command=self.offload_model)
        self.offload_model_button.pack(side="left", expand=True, fill="x", padx=(0, 5))
        Tooltip(self.offload_model_button, self.tooltips.get("offload_model_button", ""))

        self.load_model_button = ctk.CTkButton(button_frame, text="Load", font=normal_font, command=self.reload_model_full)
        self.load_model_button.pack(side="left", expand=True, fill="x", padx=(5, 0))
        Tooltip(self.load_model_button, self.tooltips.get("load_model_button", ""))

        # Loading Progress Bar (hidden by default)
        self.loading_progressbar = ctk.CTkProgressBar(self.status_frame, mode='indeterminate')

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

        # Bind keyboard shortcut
        self.input_box.bind("<Control-Return>", lambda e: self.send_message())

        # Welcome message with LYRN branding
        welcome_msg = f"""
╔═══════════════════════════════════════════════════════╗
║                    LYRN-AI v6.5                       ║
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

    def update_modes_dropdown(self):
        """Scans the modes directory and updates the dropdown."""
        modes_dir = os.path.join(SCRIPT_DIR, "build_prompt", "modes")
        if not os.path.exists(modes_dir):
            self.mode_dropdown.configure(values=["No modes found"])
            self.mode_dropdown.set("No modes found")
            return

        try:
            mode_files = [f for f in os.listdir(modes_dir) if f.endswith(".txt")]
            mode_names = [os.path.splitext(f)[0] for f in mode_files]

            if mode_names:
                self.mode_dropdown.configure(values=mode_names)
                self.mode_dropdown.set(mode_names[0])
            else:
                self.mode_dropdown.configure(values=["No modes found"])
                self.mode_dropdown.set("No modes found")
        except Exception as e:
            print(f"Error loading modes: {e}")
            self.mode_dropdown.configure(values=["Error"])
            self.mode_dropdown.set("Error")

    def on_mode_selected(self, mode_name: str):
        """Loads the selected mode's prompt into the master prompt file."""
        if "No modes found" in mode_name or "Error" in mode_name:
            return

        modes_dir = os.path.join(SCRIPT_DIR, "build_prompt", "modes")
        mode_filepath = os.path.join(modes_dir, f"{mode_name}.txt")
        master_prompt_path = self.snapshot_loader.master_prompt_path

        try:
            with open(mode_filepath, 'r', encoding='utf-8') as f_read:
                content = f_read.read()

            with open(master_prompt_path, 'w', encoding='utf-8') as f_write:
                f_write.write(content)

            self.update_status(f"Mode '{mode_name}' loaded", LYRN_SUCCESS)
        except Exception as e:
            print(f"Error loading mode '{mode_name}': {e}")
            self.update_status(f"Error loading mode", LYRN_ERROR)

    def refresh_prompt_from_mode(self):
        """Refreshes the master prompt from the build index."""
        self.snapshot_loader.load_base_prompt()
        self.update_status("Prompt refreshed from index", LYRN_SUCCESS)

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
                (ctk.CTkTextbox, {"fg_color": textbox_bg, "text_color": textbox_fg, "border_color": accent_color}),
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

    def open_personality_popup(self):
        """Opens the personality editor popup."""
        if not hasattr(self, 'personality_popup') or not self.personality_popup.winfo_exists():
            self.personality_popup = PersonalityPopup(self, self.delta_manager)
            self.personality_popup.focus()
        else:
            self.personality_popup.lift()
            self.personality_popup.focus()

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

    def _maybe_run_automated_job(self):
        """Checks for and runs the next job in the queue if the system is idle."""
        if self.is_thinking: # Don't run a job if the model is already running
            return

        if self.automation_controller.has_pending_jobs():
            next_job = self.automation_controller.get_next_job()
            if next_job:
                print(f"Executing automated job: {next_job.name}")

                # For now, this just displays the job prompt for verification.
                # Later, this will trigger a full LLM cycle for the job.
                self.display_colored_message(f"\n--- Running Automated Job: {next_job.name} ---\n", "system_text")
                self.display_colored_message(next_job.prompt, "system_text")
                self.display_colored_message(f"\n--- Job Complete: {next_job.name} ---\n", "system_text")

                # Check if more jobs are pending and run them if so
                self.after(100, self._maybe_run_automated_job)

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

    def send_message(self):
        """Send user message and generate response"""
        user_text = self.input_box.get("0.0", "end").strip()
        if not user_text:
            return

        if not self.llm:
            self.update_status("No model loaded", LYRN_ERROR)
            return

        # Display user message
        self.display_colored_message(f"You: {user_text}\n\n", "user_text")

        # Clear input and disable send
        self.input_box.delete("0.0", "end")
        self.send_btn.configure(state="disabled")

        # Save chat message
        self.save_chat_message("user", user_text)

        # Display thinking message and start response generation
        self.display_colored_message("Assistant: Thinking...\n\n", "thinking_text")
        self.is_thinking = True
        self.set_model_status("Thinking") # Blue for generating
        threading.Thread(target=self.generate_response, args=(user_text,), daemon=True).start()
        self.update_status("Generating response...", LYRN_INFO)

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
                    max_tokens=active["max_tokens"],
                    temperature=active["temperature"],
                    top_p=active["top_p"],
                    top_k=active.get("top_k", 40),
                    stream=True
                )

                response_parts = []
                for token_data in stream:
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
            self.save_chat_message("assistant", complete_response)

        except Exception as e:
            self.stream_queue.put(('error', str(e)))
        finally:
            self.stream_queue.put(('enable_send', ''))

    def save_chat_message(self, role: str, content: str) -> Optional[str]:
        """
        Saves a chat message to a file in the format expected by the system
        and returns the full path to the file.
        """
        if not self.settings_manager.settings:
            return None

        chat_dir = self.settings_manager.settings["paths"].get("chat", "")
        if not chat_dir:
            log("Chat directory not configured in settings.")
            return None

        os.makedirs(chat_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"chat_{timestamp}.txt"
        filepath = os.path.join(chat_dir, filename)

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                if role == "user":
                    # The 'model' header acts as a marker for where the response begins
                    f.write(f"user\n{content}\n\nmodel\n")
                else:
                    # Assistant messages are just saved directly for logging
                    f.write(f"assistant\n{content}\n")
            return filepath
        except Exception as e:
            print(f"Error saving chat message: {e}")
            return None

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
                        # Also check for jobs when the send button is re-enabled
                        self._maybe_run_automated_job()

                    elif message[0] == 'status_update':
                        self.update_status(message[1], message[2])

                    elif message[0] == 'system_stats':
                        if hasattr(self, 'update_system_gauges'):
                            self.update_system_gauges(message[1])

                except queue.Empty:
                    break

        except Exception as e:
            print(f"Error processing queue: {e}")

        self.after(50, self.process_queue)

    def _run_heartbeat_cycle(self, user_input: str, assistant_output: str):
        """
        Runs the LLM's "internal dialog" pass and saves the raw output
        to a file for the heartbeat_watcher to process.
        NOTE: This function is temporarily disabled pending a refactor to support the new IPC model.
        """
        if True:
            print("Heartbeat cycle is temporarily disabled.")
            return


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

    def clear_chat_folder(self):
        """Deletes all files in the chat directory."""
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
        app.start_application_logic()
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
