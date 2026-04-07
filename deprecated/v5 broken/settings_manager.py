import os
import json
import shutil
from pathlib import Path

# Script directory and settings path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(SCRIPT_DIR, "settings.json")

class SettingsManager:
    """Enhanced settings manager with UI preferences"""

    def __init__(self):
        self.settings = None
        self.first_boot = False
        self.ui_settings = {
            "font_size": 12,
            "window_size": "1400x900",
            "confirmation_preferences": {},
            "save_chat_history": True,
            "chat_history_length": 10,
            "show_thinking_text": True,
            "chat_colors": {
                "user_text": "#00C0A0",
                "assistant_text": "#FFFFFF",
                "thinking_text": "#FFD700",
                "system_text": "#B0B0B0"
            }
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

                # Normalize absolute paths to relative, if they appear to point to old local setups
                needs_save = False
                if "paths" in self.settings:
                    for key, path in self.settings["paths"].items():
                        # Sometimes paths may not trigger os.path.isabs in Linux if it starts with D:,
                        # so we check if it looks like a Windows absolute path or isabs
                        if path and (os.path.isabs(path) or ":" in path or "\\" in path):
                            normalized = path.replace("\\", "/")
                            if "LYRN-SAD/" in normalized:
                                rel_path = normalized.split("LYRN-SAD/")[-1]
                                self.settings["paths"][key] = rel_path
                                needs_save = True
                            elif "LYRN/" in normalized:
                                rel_path = normalized.split("LYRN/")[-1]
                                self.settings["paths"][key] = rel_path
                                needs_save = True

                if needs_save:
                    print("Normalized absolute paths to relative in settings.json.")
                    self.save_settings(self.settings)

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
            "allowed_origins": [],
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
