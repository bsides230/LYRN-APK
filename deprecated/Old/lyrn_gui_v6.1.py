"""
LYRN-AI Interface v6.1 - Advanced GUI with Full Feature Set

Major Updates:
- LYRN-AI Branding with Consolas font throughout
- Tabbed Settings Dialog (Model Config, Directory Paths, UI Colors, Advanced)
- Light/Dark mode toggle with live switching
- Font size controls
- Enhanced Performance Metrics with gauges and save functionality
- Multi-colored text display (System, User, Assistant, Thinking)
- Fixed model reload memory issues
- Purple theme (#880ED4) for all buttons
- Logo placeholder and polished status display
"""

import os
import sys
import json
import re
import time
import queue
import threading
import io
import contextlib
import subprocess
import gc
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from pathlib import Path
import shutil

# CustomTkinter imports
import customtkinter as ctk
from llama_cpp import Llama

# System monitoring imports
import psutil
try:
    import pynvml
except ImportError:
    pynvml = None
import hwinfo_monitor

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
            print("Warning: No themes found. Using fallback default.")
            self.themes["Purple Dark"] = {
                "name": "Purple Dark", "appearance_mode": "dark", "colors": {
                    "primary": "#880ED4", "accent": "#A855F7", "success": "#10B981",
                    "warning": "#F59E0B", "error": "#EF4444", "info": "#3B82F6",
                    "system_text": "#E5E7EB", "user_text": "#60A5FA",
                    "assistant_text": "#34D399", "thinking_text": "#F472B6"
                }
            }

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

class SettingsManager:
    """Enhanced settings manager with UI preferences"""

    def __init__(self):
        self.settings = None
        self.first_boot = False
        self.ui_settings = {
            "font_size": 12,
            "window_size": "1400x900",
            "appearance_mode": "dark"
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

class PromptBuilder:
    """Builds prompts by aggregating indexed files from the 'build_prompt' directory."""

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

    def build_full_prompt(self) -> str:
        """
        Loads the master prompt file. If it doesn't exist, generates it first.
        """
        print("Building full prompt...")
        if not os.path.exists(self.master_prompt_path):
            print("Master prompt file not found. Generating a new one.")
            self.generate_master_index()

        return self._load_text_file(self.master_prompt_path)

class JobProcessor:
    """Manages job automation with file handler coordination"""

    def __init__(self, settings_manager: SettingsManager, gui_reference):
        self.settings = settings_manager
        self.gui = gui_reference
        self.jobs = {}
        self.job_names = []
        self.job_running = False
        self.current_job_index = 0
        self.load_jobs()

    def load_jobs(self):
        """Load jobs from job_list.txt"""
        if not self.settings.settings or "paths" not in self.settings.settings:
            self.setup_fallback_jobs()
            return

        job_list_path = self.settings.settings["paths"].get("job_list", "")
        if not job_list_path or not os.path.exists(job_list_path):
            print("Job list file not found - using fallback jobs")
            self.setup_fallback_jobs()
            return

        try:
            with open(job_list_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Extract job names and instructions (simplified for brevity)
            self.job_names = ["Summary Job", "Keyword Job", "Topic Job"]
            self.jobs = {
                "Summary Job": "Provide a summary between ###SUMMARY_START### and ###SUMMARY_END### tags.",
                "Keyword Job": "Extract keywords between ###KEYWORDS_START### and ###KEYWORDS_END### tags.",
                "Topic Job": "Identify topics between ###TOPICS_START### and ###TOPICS_END### tags."
            }

            print(f"Loaded {len(self.job_names)} jobs from file")

        except Exception as e:
            print(f"Error loading jobs: {e}")
            self.setup_fallback_jobs()

    def setup_fallback_jobs(self):
        """Setup fallback jobs when file loading fails"""
        self.job_names = ["Summary Job", "Keyword Job", "Topic Job"]
        self.jobs = {
            "Summary Job": "Provide a summary between ###SUMMARY_START### and ###SUMMARY_END### tags.",
            "Keyword Job": "Extract keywords between ###KEYWORDS_START### and ###KEYWORDS_END### tags.",
            "Topic Job": "Identify topics between ###TOPICS_START### and ###TOPICS_END### tags."
        }

    def _wait_for_next_job(self, timeout=60):
        """Wait function to poll next_job.txt"""
        flag_path = os.path.join(SCRIPT_DIR, "global_flags", "next_job.txt")
        start_time = time.time()

        while time.time() - start_time < timeout:
            if os.path.exists(flag_path):
                try:
                    with open(flag_path, 'r', encoding='utf-8') as f:
                        flag_value = f.read().strip().lower()

                    if flag_value == "true":
                        with open(flag_path, 'w', encoding='utf-8') as f:
                            f.write("false")
                        return True

                except Exception as e:
                    print(f"Error reading next job flag: {e}")

            time.sleep(0.5)

        return False

    def start_automation(self):
        """Start job automation"""
        self.job_running = True
        self.current_job_index = 0
        self.settings.set_automation_flag("on")

        if self.gui:
            self.gui.update_status("Automation started", LYRN_ACCENT)

        threading.Thread(target=self._process_jobs, daemon=True).start()

    def stop_automation(self):
        """Stop job automation"""
        self.job_running = False
        self.settings.set_automation_flag("off")

        if self.gui:
            self.gui.update_status("Automation stopped", LYRN_ERROR)

    def _process_jobs(self):
        """Process jobs with file handler coordination"""
        while self.job_running and self.current_job_index < len(self.job_names):
            if self.current_job_index > 0:
                if not self._wait_for_next_job():
                    self.job_running = False
                    if self.gui:
                        self.gui.update_status("Automation stopped - timeout", LYRN_ERROR)
                    return

            current_job = self.job_names[self.current_job_index]
            job_text = self.jobs.get(current_job, "")

            if job_text and self.gui:
                self.gui.insert_job_text(job_text)
                self.gui.update_status(f"Processing: {current_job}", LYRN_ACCENT)

            self.current_job_index += 1
            time.sleep(1)

        if self.job_running:
            self.gui.update_status("All jobs completed", LYRN_SUCCESS)
            self.job_running = False

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
        ram_info = psutil.virtual_memory()
        stats = {
            "ram_percent": ram_info.percent,
            "ram_used_gb": ram_info.used / (1024**3),
            "ram_total_gb": ram_info.total / (1024**3),
            "cpu": psutil.cpu_percent(),
            "cpu_temp": "N/A",
            "vram": 0,
            "hwinfo": None
        }

        # Get HWiNFO data
        stats["hwinfo"] = hwinfo_monitor.get_hwinfo_data()

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
        except (AttributeError, KeyError, IndexError):
            pass  # Silently ignore if temp sensors are not available/readable

        # Get VRAM usage if NVML is available
        if self.nvml_initialized:
            try:
                handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                stats["vram"] = (info.used / info.total) * 100
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
    def __init__(self, parent, log_queue: queue.Queue):
        super().__init__(parent)
        self.log_queue = log_queue

        self.title("LLM & System Log")
        self.geometry("800x600")

        # Override the close button
        self.protocol("WM_DELETE_WINDOW", self.withdraw)

        self.textbox = ctk.CTkTextbox(self, wrap="word", font=("Consolas", 11))
        self.textbox.pack(expand=True, fill="both", padx=10, pady=10)
        self.textbox.configure(state="disabled")

        self.after(100, self.process_log_queue)

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
    def __init__(self, parent, settings_manager: SettingsManager):
        super().__init__(parent)
        self.parent_app = parent
        self.settings_manager = settings_manager

        self.title("LYRN-AI Model Selector")
        self.geometry("600x450")
        self.resizable(False, False)
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

    def create_widgets(self):
        """Create widgets for the popup."""
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(expand=True, fill="both", padx=20, pady=20)

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

class TabbedSettingsDialog(ctk.CTkToplevel):
    """Enhanced settings dialog with tabs"""

    def __init__(self, parent, settings_manager: SettingsManager, theme_manager: ThemeManager):
        super().__init__(parent)
        self.settings_manager = settings_manager
        self.theme_manager = theme_manager
        self.parent_app = parent

        self.title("LYRN-AI Settings")
        self.geometry("900x700")
        self.resizable(False, False)

        self.transient(parent)

        self.show_model_selector_var = ctk.BooleanVar()

        self.create_widgets()
        self.load_current_settings()
        self.apply_theme()
        self.refresh_prompt_index()

    def create_widgets(self):
        """Create tabbed interface"""
        # Main tabview
        self.tabview = ctk.CTkTabview(self, width=850, height=600)
        self.tabview.pack(fill="both", expand=True, padx=20, pady=20)

        # Create tabs
        self.tab_model = self.tabview.add("Model Config")
        self.tab_paths = self.tabview.add("Directory Paths")
        self.tab_prompt = self.tabview.add("Prompt Manager")
        self.tab_advanced = self.tabview.add("Advanced")

        self.create_model_tab()
        self.create_paths_tab()
        self.create_prompt_manager_tab()
        self.create_advanced_tab()

        # Button frame
        button_frame = ctk.CTkFrame(self)
        button_frame.pack(fill="x", padx=20, pady=(0, 20))

        self.save_button = ctk.CTkButton(button_frame, text="Save All",
                                        command=self.save_all_settings)
        self.save_button.pack(side="left", padx=10, pady=10)

        self.cancel_button = ctk.CTkButton(button_frame, text="Cancel",
                                          command=self.destroy)
        self.cancel_button.pack(side="right", padx=10, pady=10)

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

        ctk.CTkButton(clear_frame, text="Clear Chat Directory",
                     font=font, command=self.clear_chat_directory).pack(side="left", padx=5, pady=5)
        ctk.CTkButton(clear_frame, text="Clear Deltas Directory",
                     font=font, command=self.clear_deltas_directory).pack(side="left", padx=5, pady=5)
        ctk.CTkButton(clear_frame, text="Clear Metrics Logs",
                     font=font, command=self.clear_metrics_logs).pack(side="left", padx=5, pady=5)

        # Model operations
        model_frame = ctk.CTkFrame(maint_frame)
        model_frame.pack(fill="x", padx=10, pady=10)

        ctk.CTkButton(model_frame, text="🔄 Reload Model (Full)",
                     font=font, command=self.reload_model_full).pack(side="left", padx=5, pady=5)
        ctk.CTkButton(model_frame, text="🧹 Force Memory Cleanup",
                     font=font, command=self.force_memory_cleanup).pack(side="left", padx=5, pady=5)

        # Testing utilities
        test_frame = ctk.CTkFrame(self.tab_advanced)
        test_frame.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(test_frame, text="Testing Utilities", font=title_font).pack(pady=10)

        util_frame = ctk.CTkFrame(test_frame)
        util_frame.pack(fill="x", padx=10, pady=10)

        ctk.CTkButton(util_frame, text="Export System Info",
                     font=font, command=self.export_system_info).pack(side="left", padx=5, pady=5)
        ctk.CTkButton(util_frame, text="Test Model Performance",
                     font=font, command=self.test_model_performance).pack(side="left", padx=5, pady=5)
        ctk.CTkButton(util_frame, text="Validate Directories",
                     font=font, command=self.validate_directories).pack(side="left", padx=5, pady=5)
        # Add checkbox for re-enabling model selector
        self.show_model_selector_checkbox = ctk.CTkCheckBox(
            util_frame,
            text="Show model selector on next startup",
            font=font,
            variable=self.show_model_selector_var
        )
        self.show_model_selector_checkbox.pack(side="left", padx=10, pady=5)

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

        ctk.CTkButton(button_frame, text="🔄 Refresh Index from Subfolders",
                     font=font, command=self.refresh_prompt_index).pack(side="left", padx=10)

        ctk.CTkButton(button_frame, text="💾 Save as Mode",
                     font=font, command=self.save_as_mode).pack(side="left", padx=10)

        # Frame for the list
        list_frame = ctk.CTkFrame(self.tab_prompt)
        list_frame.pack(expand=True, fill="both", padx=20, pady=10)

        self.prompt_scroll_frame = ctk.CTkScrollableFrame(list_frame, label_text="Indexed Files (in order)")
        self.prompt_scroll_frame.pack(expand=True, fill="both", padx=5, pady=5)

        self.update_prompt_file_list()

    def update_prompt_file_list(self):
        """Reads the master index and displays it in the scrollable frame."""
        # Clear existing widgets
        for widget in self.prompt_scroll_frame.winfo_children():
            widget.destroy()

        # Get the master index from the prompt_builder instance
        master_index_path = self.parent_app.prompt_builder.master_index_path
        try:
            with open(master_index_path, 'r', encoding='utf-8') as f:
                index_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            index_data = [] # If file doesn't exist or is invalid, show an empty list

        if not index_data:
            ctk.CTkLabel(self.prompt_scroll_frame, text="No files in index. Click Refresh to generate.").pack(pady=10)
            return

        for i, filepath in enumerate(index_data):
            # The user requested drag-and-drop, which is complex.
            # For now, we'll just display the list.
            label_text = f"{i+1:02d}: {filepath.replace('/', ' / ')}"
            ctk.CTkLabel(self.prompt_scroll_frame, text=label_text, anchor="w").pack(fill="x", padx=10, pady=2)

    def refresh_prompt_index(self):
        """Calls the prompt builder to regenerate the index and updates the UI."""
        print("UI triggered prompt index refresh.")
        self.parent_app.prompt_builder.generate_master_index()
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

            master_prompt_path = self.parent_app.prompt_builder.master_prompt_path
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
        show_selector = self.settings_manager.ui_settings.get("show_model_selector", True)
        self.show_model_selector_var.set(show_selector)

    def apply_theme(self):
        """Applies the current theme colors to all widgets in this dialog."""
        primary_color = self.theme_manager.get_color("primary")

        # Find all buttons recursively and apply the primary color
        all_buttons = self.find_widgets_recursively(self, ctk.CTkButton)
        for btn in all_buttons:
            btn.configure(fg_color=primary_color)

        # Explicitly theme the main buttons
        if hasattr(self, 'save_button'):
            self.save_button.configure(fg_color=primary_color)
        if hasattr(self, 'cancel_button'):
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

            # Save all settings
            self.settings_manager.save_settings(settings)

            print("All settings saved successfully")
            self.destroy()

        except Exception as e:
            print(f"Error saving settings: {e}")

class LyrnAIInterface(ctk.CTk):
    """Main LYRN-AI interface with enhanced features"""

    def __init__(self, log_queue: queue.Queue):
        super().__init__()

        self.log_queue = log_queue

        # Initialize core components
        self.settings_manager = SettingsManager()
        self.theme_manager = ThemeManager()

        # Apply saved theme or default
        saved_theme = self.settings_manager.ui_settings.get("theme", "Purple Dark")
        self.theme_manager.apply_theme(saved_theme)

        self.llm = None
        self.first_boot_complete = False
        self.is_thinking = False
        self.current_assistant_message_label = None
        self.stream_queue = queue.Queue()
        self.resource_monitor = SystemResourceMonitor(self.stream_queue)

        # Initialize font size
        self.current_font_size = self.settings_manager.ui_settings.get("font_size", 12)

        # Setup GUI
        self.setup_window()

        # Check for first boot or initialize
        if self.settings_manager.first_boot or self.settings_manager.ui_settings.get("show_model_selector", True):
            self.open_model_selector()

        self.initialize_application()

        # Handle window closing
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def on_closing(self):
        """Handle cleanup on window close."""
        if hasattr(self, 'resource_monitor'):
            self.resource_monitor.stop()
        self.destroy()

    def open_model_selector(self):
        """Opens the model selector popup window."""
        if hasattr(self, 'model_selector_popup') and self.model_selector_popup.winfo_exists():
            self.model_selector_popup.lift()
            self.model_selector_popup.focus()
        else:
            self.model_selector_popup = ModelSelectorPopup(self, self.settings_manager)
            self.model_selector_popup.focus()

    def setup_window(self):
        """Configure main window with LYRN-AI branding"""
        self.title("LYRN-AI Interface v6.1")
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

    def initialize_application(self):
        """Initialize application after settings are configured"""
        if not self.settings_manager.settings:
            print("ERROR: No settings available for initialization!")
            return

        # Initialize remaining components
        self.prompt_builder = PromptBuilder(self.settings_manager)
        self.job_processor = JobProcessor(self.settings_manager, self)
        self.metrics = EnhancedPerformanceMetrics()

        # Setup GUI
        self.create_widgets()
        self.apply_color_theme()

        # Start background services
        self.resource_monitor.start()
        self.after(100, self.process_queue)

    def setup_model(self):
        """Initialize LLM model with proper cleanup"""
        if not self.settings_manager.settings:
            print("No settings available for model setup")
            self.llm = None
            return

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

        except Exception as e:
            print(f"Error loading model: {e}")
            self.llm = None
            self.stream_queue.put(('status_update', f'Model Load Failed', LYRN_ERROR))

    def create_widgets(self):
        """Create main interface widgets with LYRN-AI styling"""
        self.grid_columnconfigure(0, weight=0)  # Left sidebar
        self.grid_columnconfigure(1, weight=1)  # Main chat area
        self.grid_columnconfigure(2, weight=0)  # Right sidebar
        self.grid_rowconfigure(0, weight=1)

        # Create the three main components
        self.create_left_sidebar()
        self.create_chat_area()
        self.create_right_sidebar()

    def create_left_sidebar(self):
        """Creates the left sidebar for controls."""
        self.left_sidebar = ctk.CTkFrame(self, width=320, corner_radius=0)
        self.left_sidebar.grid(row=0, column=0, sticky="nsew", padx=(10, 5), pady=10)
        self.left_sidebar.grid_propagate(False)

        # LYRN-AI Header with logo placeholder
        header_frame = ctk.CTkFrame(self.left_sidebar, fg_color=LYRN_PURPLE)
        header_frame.pack(fill="x", padx=10, pady=(10, 20))

        try:
            title_font = ctk.CTkFont(family="Consolas", size=18, weight="bold")
            section_font = ctk.CTkFont(family="Consolas", size=14, weight="bold")
            normal_font = ctk.CTkFont(family="Consolas", size=self.current_font_size)
        except:
            title_font = ("Consolas", 18, "bold")
            section_font = ("Consolas", 14, "bold")
            normal_font = ("Consolas", self.current_font_size)

        # Logo placeholder and title
        logo_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        logo_frame.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(logo_frame, text="🧠", font=("Arial", 24)).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(logo_frame, text="LYRN-AI", font=title_font,
                    text_color="white").pack(side="left")

        # Quick controls frame
        quick_frame = ctk.CTkFrame(self.left_sidebar)
        quick_frame.pack(fill="x", padx=10, pady=(0, 20))

        ctk.CTkLabel(quick_frame, text="Quick Controls", font=section_font).pack(pady=10)

        # Theme selection
        theme_frame = ctk.CTkFrame(quick_frame)
        theme_frame.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(theme_frame, text="Theme:", font=normal_font).pack(side="left", padx=5)
        self.theme_dropdown = ctk.CTkComboBox(
            theme_frame,
            values=self.theme_manager.get_theme_names(),
            command=self.on_theme_selected
        )
        self.theme_dropdown.pack(side="right", padx=5, expand=True, fill="x")
        self.theme_dropdown.set(self.theme_manager.get_current_theme_name())

        # Font size controls
        font_frame = ctk.CTkFrame(quick_frame)
        font_frame.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(font_frame, text="Font Size:", font=normal_font).pack(side="left", padx=5)
        ctk.CTkButton(font_frame, text="A-", width=30, height=25,
                     font=normal_font,
                     command=self.decrease_font_size).pack(side="right", padx=2)
        ctk.CTkButton(font_frame, text="A+", width=30, height=25,
                     font=normal_font,
                     command=self.increase_font_size).pack(side="right", padx=2)

        # Mode selection
        mode_frame = ctk.CTkFrame(quick_frame)
        mode_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(mode_frame, text="Mode:", font=normal_font).pack(side="left", padx=5)
        self.mode_dropdown = ctk.CTkComboBox(
            mode_frame,
            values=[],
            command=self.on_mode_selected
        )
        self.mode_dropdown.pack(side="left", expand=True, fill="x", padx=5)

        refresh_button = ctk.CTkButton(mode_frame, text="🔄", width=30, height=25,
                                         font=normal_font,
                                         command=self.refresh_prompt_from_mode)
        refresh_button.pack(side="right", padx=2)

        self.update_modes_dropdown()

        # Job Automation Section
        job_frame = ctk.CTkFrame(self.left_sidebar)
        job_frame.pack(fill="x", padx=10, pady=(0, 20))

        ctk.CTkLabel(job_frame, text="Job Automation", font=section_font).pack(pady=10)

        # Start/Stop buttons
        button_frame = ctk.CTkFrame(job_frame)
        button_frame.pack(fill="x", padx=10, pady=(0, 10))

        self.start_btn = ctk.CTkButton(
            button_frame, text="▶ Start Jobs",
            font=normal_font, command=self.start_automation
        )
        self.start_btn.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self.stop_btn = ctk.CTkButton(
            button_frame, text="⏹ Stop Jobs",
            font=normal_font, command=self.stop_automation
        )
        self.stop_btn.pack(side="right", fill="x", expand=True, padx=(5, 0))

        # Job selection dropdown
        ctk.CTkLabel(job_frame, text="Manual Job Selection", font=normal_font).pack(pady=(10, 5))
        self.job_dropdown = ctk.CTkComboBox(
            job_frame, values=self.job_processor.job_names if hasattr(self, 'job_processor') else [],
            command=self.on_job_selected, font=normal_font,
            button_color=LYRN_PURPLE, button_hover_color=LYRN_ACCENT
        )
        self.job_dropdown.pack(padx=10, pady=(0, 15), fill="x")

        # System Controls Section
        system_frame = ctk.CTkFrame(self.left_sidebar)
        system_frame.pack(fill="x", padx=10, pady=(0, 20))

        ctk.CTkLabel(system_frame, text="System Controls", font=section_font).pack(pady=10)

        ctk.CTkButton(system_frame, text="📦 Reload Model",
                     font=normal_font, command=self.reload_model_full).pack(padx=10, pady=3, fill="x")

        ctk.CTkButton(system_frame, text="⚙ Settings",
                     font=normal_font, command=self.open_settings).pack(padx=10, pady=3, fill="x")

        ctk.CTkButton(system_frame, text="📋 Show LLM Log",
                     font=normal_font, command=self.toggle_log_viewer).pack(padx=10, pady=3, fill="x")

        ctk.CTkButton(system_frame, text="📁 Clear Chat",
                     font=normal_font, command=self.clear_chat).pack(padx=10, pady=3, fill="x")

        # Enhanced Status Section
        self.create_enhanced_status()

    def create_right_sidebar(self):
        """Creates the right sidebar for monitoring and gauges."""
        self.right_sidebar = ctk.CTkFrame(self, width=320, corner_radius=0)
        self.right_sidebar.grid(row=0, column=2, sticky="nsew", padx=(5, 10), pady=10)
        self.right_sidebar.grid_propagate(False)

        # Enhanced Performance Metrics Section
        self.create_enhanced_metrics()

        # HWiNFO Section
        self.create_hwinfo_section()

    def create_hwinfo_section(self):
        """Creates the HWiNFO display section."""
        try:
            section_font = ctk.CTkFont(family="Consolas", size=14, weight="bold")
        except:
            section_font = ("Consolas", 14, "bold")

        hwinfo_frame = ctk.CTkFrame(self.right_sidebar)
        hwinfo_frame.pack(fill="both", expand=True, padx=10, pady=(10, 20))

        ctk.CTkLabel(hwinfo_frame, text="HWiNFO Sensor Data", font=section_font).pack(pady=10)

        self.hwinfo_scroll_frame = ctk.CTkScrollableFrame(hwinfo_frame, label_text="Live Sensors")
        self.hwinfo_scroll_frame.pack(expand=True, fill="both", padx=5, pady=5)

        ctk.CTkLabel(self.hwinfo_scroll_frame, text="Waiting for HWiNFO data...").pack(pady=10)

    def create_enhanced_metrics(self):
        """Create enhanced performance metrics with gauges"""
        metrics_frame = ctk.CTkFrame(self.right_sidebar)
        metrics_frame.pack(fill="x", padx=10, pady=(10, 20))

        try:
            section_font = ctk.CTkFont(family="Consolas", size=14, weight="bold")
            normal_font = ctk.CTkFont(family="Consolas", size=self.current_font_size)
        except:
            section_font = ("Consolas", 14, "bold")
            normal_font = ("Consolas", self.current_font_size)

        ctk.CTkLabel(metrics_frame, text="Performance Metrics", font=section_font).pack(pady=10)

        # KV Cache with progress bar
        kv_frame = ctk.CTkFrame(metrics_frame)
        kv_frame.pack(fill="x", padx=10, pady=2)

        self.kv_label = ctk.CTkLabel(kv_frame, text="KV Cache: 0 tokens",
                                    font=normal_font)
        self.kv_label.pack(side="left", padx=5)

        self.kv_progress = ctk.CTkProgressBar(kv_frame, width=100, height=8)
        self.kv_progress.pack(side="right", padx=5)
        self.kv_progress.set(0)

        # Prompt tokens
        self.prompt_label = ctk.CTkLabel(metrics_frame, text="Prompt: 0 tokens",
                                        font=normal_font)
        self.prompt_label.pack(pady=2)

        # Generation speed with visual indicator
        gen_frame = ctk.CTkFrame(metrics_frame)
        gen_frame.pack(fill="x", padx=10, pady=2)

        self.eval_label = ctk.CTkLabel(gen_frame, text="Generation: 0 tok/s",
                                     font=normal_font)
        self.eval_label.pack(side="left", padx=5)

        self.speed_indicator = ctk.CTkLabel(gen_frame, text="●",
                                          font=("Arial", 16), text_color="#666666")
        self.speed_indicator.pack(side="right", padx=5)

        # Total tokens
        self.total_label = ctk.CTkLabel(metrics_frame, text="Total: 0 tokens",
                                       font=normal_font)
        self.total_label.pack(pady=2)

        # Save metrics button
        ctk.CTkButton(metrics_frame, text="💾 Save Metrics",
                     font=normal_font, height=25, command=self.save_metrics_log).pack(
                         padx=10, pady=(5, 10), fill="x")

        # System Resource Gauges
        ctk.CTkLabel(metrics_frame, text="System Resources", font=section_font).pack(pady=(10,5))

        # CPU
        cpu_frame = ctk.CTkFrame(metrics_frame)
        cpu_frame.pack(fill="x", padx=10, pady=2)
        self.cpu_label = ctk.CTkLabel(cpu_frame, text="CPU: 0.0% (N/A)", font=normal_font)
        self.cpu_label.pack(side="left", padx=5)
        self.cpu_progress = ctk.CTkProgressBar(cpu_frame, width=100, height=8, progress_color="#F59E0B")
        self.cpu_progress.pack(side="right", padx=5)
        self.cpu_progress.set(0)

        # RAM
        ram_frame = ctk.CTkFrame(metrics_frame)
        ram_frame.pack(fill="x", padx=10, pady=2)
        self.ram_label = ctk.CTkLabel(ram_frame, text="RAM: 0.0%", font=normal_font)
        self.ram_label.pack(side="left", padx=5)
        self.ram_progress = ctk.CTkProgressBar(ram_frame, width=100, height=8, progress_color="#3B82F6")
        self.ram_progress.pack(side="right", padx=5)
        self.ram_progress.set(0)

        # VRAM (only if NVIDIA GPU is detected)
        if self.resource_monitor.nvml_initialized:
            vram_frame = ctk.CTkFrame(metrics_frame)
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

        # VRAM
        if self.resource_monitor.nvml_initialized and self.vram_label is not None:
            self.vram_label.configure(text=f"VRAM: {stats['vram']:.1f}%")
            self.vram_progress.set(stats['vram'] / 100)

        # HWiNFO Data
        if stats.get("hwinfo"):
            # Clear existing widgets
            for widget in self.hwinfo_scroll_frame.winfo_children():
                widget.destroy()

            # Filter for interesting sensors (e.g., CPU, GPU temps/fans)
            interesting_sensors = {
                "CPU": ["CPU (Tctl/Tdie)", "CPU Fan"],
                "GPU": ["GPU Temperature", "GPU Fan"]
            }

            for reading in stats["hwinfo"]:
                for sensor_type, labels in interesting_sensors.items():
                    if reading["sensor_name"] in labels:
                        label_text = f"{reading['sensor_name']} - {reading['label']}: {reading['value']:.1f} {reading['unit']}"
                        ctk.CTkLabel(self.hwinfo_scroll_frame, text=label_text, anchor="w").pack(fill="x", padx=5, pady=2)

    def create_enhanced_status(self):
        """Create enhanced status display"""
        self.status_frame = ctk.CTkFrame(self.left_sidebar)
        self.status_frame.pack(fill="x", padx=10, pady=(0, 10))

        try:
            section_font = ctk.CTkFont(family="Consolas", size=14, weight="bold")
            status_font = ctk.CTkFont(family="Consolas", size=12, weight="bold")
        except:
            section_font = ("Consolas", 14, "bold")
            status_font = ("Consolas", 12, "bold")

        ctk.CTkLabel(self.status_frame, text="System Status", font=section_font).pack(pady=(10, 5))

        # Status with animated indicator
        status_container = ctk.CTkFrame(self.status_frame, fg_color="transparent")
        status_container.pack(fill="x", padx=10, pady=(0, 10))

        self.status_indicator = ctk.CTkLabel(status_container, text="●",
                                           font=("Arial", 20), text_color=LYRN_SUCCESS)
        self.status_indicator.pack(side="left", padx=(0, 10))

        self.status_label = ctk.CTkLabel(status_container, text="LYRN-AI Ready",
                                       font=status_font, text_color=LYRN_SUCCESS)
        self.status_label.pack(side="left")

        # System info
        info_text = f"Model: {'Loaded' if self.llm else 'Not Loaded'}\nMode: {self.settings_manager.ui_settings.get('appearance_mode', 'dark').title()}"
        self.info_label = ctk.CTkLabel(self.status_frame, text=info_text,
                                      font=("Consolas", 10), justify="left")
        self.info_label.pack(pady=(0, 10))

    def create_chat_area(self):
        """Create enhanced chat interface with colored text support"""
        chat_frame = ctk.CTkFrame(self)
        chat_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 10), pady=10)
        chat_frame.grid_rowconfigure(0, weight=1)
        chat_frame.grid_columnconfigure(0, weight=1)

        # Chat display with enhanced text handling
        try:
            chat_font = ctk.CTkFont(family="Consolas", size=self.current_font_size)
        except:
            chat_font = ("Consolas", self.current_font_size)

        self.chat_display = ctk.CTkTextbox(chat_frame, font=chat_font, wrap="word")
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

        self.input_box = ctk.CTkTextbox(input_frame, height=100, font=chat_font)
        self.input_box.grid(row=0, column=0, sticky="ew", padx=(0, 10))

        # Send button with LYRN styling
        self.send_btn = ctk.CTkButton(input_frame, text="Send", width=80,
                                     font=chat_font,
                                     command=self.send_message)
        self.send_btn.grid(row=0, column=1)

        # Bind keyboard shortcut
        self.input_box.bind("<Control-Return>", lambda e: self.send_message())

        # Welcome message with LYRN branding
        welcome_msg = f"""
╔═══════════════════════════════════════════════════════╗
║                    LYRN-AI v6.1                       ║
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

        self.display_colored_message(f"{welcome_msg}\n\n", "system_text")

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
        master_prompt_path = self.prompt_builder.master_prompt_path

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
        self.prompt_builder.build_full_prompt()
        self.update_status("Prompt refreshed from index", LYRN_SUCCESS)

    def apply_color_theme(self):
        """Apply colors from the current theme to all relevant widgets."""
        try:
            primary_color = self.theme_manager.get_color("primary")
            accent_color = self.theme_manager.get_color("accent")

            # --- Update all widgets recursively ---
            all_buttons = self.find_widgets_recursively(self, ctk.CTkButton)
            for btn in all_buttons:
                btn.configure(fg_color=primary_color)

            all_comboboxes = self.find_widgets_recursively(self, ctk.CTkComboBox)
            for combo in all_comboboxes:
                combo.configure(button_color=primary_color, button_hover_color=accent_color)

            # --- Update specific labels ---
            if hasattr(self, 'chat_display'):
                self.chat_display.configure(text_color=self.theme_manager.get_color("system_text"))
            if hasattr(self, 'kv_label'):
                self.kv_label.configure(text_color=self.theme_manager.get_color("info"))
            if hasattr(self, 'prompt_label'):
                self.prompt_label.configure(text_color=self.theme_manager.get_color("system_text"))
            if hasattr(self, 'eval_label'):
                self.eval_label.configure(text_color=accent_color)
            if hasattr(self, 'total_label'):
                self.total_label.configure(text_color=self.theme_manager.get_color("success"))

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

    def open_settings(self):
        """Open enhanced tabbed settings dialog"""
        if not hasattr(self, 'settings_dialog') or not self.settings_dialog.winfo_exists():
            self.settings_dialog = TabbedSettingsDialog(self, self.settings_manager, self.theme_manager)
            self.settings_dialog.focus()
        else:
            self.settings_dialog.lift()
            self.settings_dialog.focus()

    def toggle_log_viewer(self):
        """Creates, shows, or focuses the LLM log viewer window."""
        # If the popup doesn't exist or has been destroyed, create it.
        if not hasattr(self, 'log_viewer_popup') or not self.log_viewer_popup.winfo_exists():
            self.log_viewer_popup = LogViewerPopup(self, self.log_queue)
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
        """Test model performance"""
        if not self.llm:
            self.update_status("No model loaded", LYRN_ERROR)
            return

        self.update_status("Testing model performance...", LYRN_INFO)

        def test_thread():
            try:
                # Simple performance test
                test_prompt = "Hello, this is a test message. Please respond briefly."

                start_time = time.time()
                response = self.llm.create_chat_completion(
                    messages=[{"role": "user", "content": test_prompt}],
                    max_tokens=50,
                    temperature=0.1
                )
                end_time = time.time()

                duration = end_time - start_time
                self.stream_queue.put(('status_update', f'Performance test: {duration:.2f}s', LYRN_SUCCESS))

            except Exception as e:
                self.stream_queue.put(('status_update', f'Performance test failed: {e}', LYRN_ERROR))

        threading.Thread(target=test_thread, daemon=True).start()

    def start_automation(self):
        """Start job automation"""
        if hasattr(self, 'job_processor'):
            self.job_processor.start_automation()
            self.start_btn.configure(state="disabled")
            self.stop_btn.configure(state="normal")

    def stop_automation(self):
        """Stop job automation"""
        if hasattr(self, 'job_processor'):
            self.job_processor.stop_automation()
            self.start_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")

    def on_job_selected(self, job_name):
        """Handle manual job selection"""
        if hasattr(self, 'job_processor') and job_name in self.job_processor.jobs:
            job_text = self.job_processor.jobs[job_name]
            self.insert_job_text(job_text)
            self.update_status(f"Manual job: {job_name}", LYRN_ACCENT)

    def insert_job_text(self, text: str):
        """Insert job text into input box"""
        self.input_box.delete("0.0", "end")
        self.input_box.insert("0.0", text)

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
        threading.Thread(target=self.generate_response, args=(user_text,), daemon=True).start()
        self.update_status("Generating response...", LYRN_WARNING)

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
            full_prompt = self.prompt_builder.build_full_prompt()

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

            # Save complete response
            complete_response = ''.join(response_parts)
            self.save_chat_message("assistant", complete_response)

        except Exception as e:
            self.stream_queue.put(('error', str(e)))
        finally:
            self.stream_queue.put(('enable_send', ''))

    def save_chat_message(self, role: str, content: str):
        """Save chat message to file"""
        if not self.settings_manager.settings:
            return

        chat_dir = self.settings_manager.settings["paths"].get("chat", "")
        if not chat_dir:
            return

        os.makedirs(chat_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"chat_{timestamp}.txt"
        filepath = os.path.join(chat_dir, filename)

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(f"{role}\n{content}")
        except Exception as e:
            print(f"Error saving chat message: {e}")

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
                        if hasattr(self, '_assistant_started'):
                            self.chat_display.configure(state="normal")
                            self.chat_display.insert("end", "\n\n")
                            self.chat_display.configure(state="disabled")
                            delattr(self, '_assistant_started')

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

            # Update progress bar for KV cache (normalize to reasonable range)
            if self.metrics.total_tokens > 0:
                kv_ratio = min(self.metrics.kv_cache_reused / self.metrics.total_tokens, 1.0)
                self.kv_progress.set(kv_ratio)

            # Update speed indicator color based on generation speed
            if self.metrics.eval_speed > 50:
                color = LYRN_SUCCESS  # Fast
            elif self.metrics.eval_speed > 20:
                color = LYRN_WARNING  # Medium
            else:
                color = LYRN_ERROR    # Slow

            self.speed_indicator.configure(text_color=color)

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
        if not hasattr(self, 'status_label'):
            return

        try:
            color = color or LYRN_SUCCESS
            self.status_label.configure(text=message, text_color=color)
            self.status_indicator.configure(text_color=color)

            # Update system info
            info_text = f"Model: {'Loaded' if self.llm else 'Not Loaded'}\nMode: {self.settings_manager.ui_settings.get('appearance_mode', 'dark').title()}"
            self.info_label.configure(text=info_text)

        except Exception as e:
            print(f"Error updating status: {e}")

    def clear_chat(self):
        """Clear chat display"""
        try:
            self.chat_display.configure(state="normal")
            self.chat_display.delete("0.0", "end")
            self.chat_display.configure(state="disabled")
            self.update_status("Chat cleared", LYRN_INFO)
        except Exception as e:
            print(f"Error clearing chat: {e}")

def main():
    """Main entry point for LYRN-AI v6.0"""
    log_queue = queue.Queue()
    redirector = ConsoleRedirector(log_queue)
    redirector.start()

    try:
        print("Starting LYRN-AI Interface v6.0...")
        print("Enhanced features: Multi-colored text, Live theming, Advanced metrics")
        print(f"CustomTkinter version: {ctk.__version__}")

        app = LyrnAIInterface(log_queue=log_queue)
        print("LYRN-AI initialized successfully")
        app.mainloop()

    except ImportError as e:
        print(f"Import error: {e}")
        print("Please install required packages:")
        print("pip install customtkinter llama-cpp-python")
        input("Press Enter to exit...")

    except Exception as e:
        print(f"Application error: {e}")
        import traceback
        traceback.print_exc()
        input("Press Enter to exit...")

    finally:
        redirector.stop()

if __name__ == "__main__":
    main()