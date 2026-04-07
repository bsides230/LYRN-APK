import os
import json
import time
from datetime import datetime
from pathlib import Path
import uuid
from file_lock import SimpleFileLock

class DeltaManager:
    """
    Manages the creation and storage of delta files for non-destructive updates.
    """
    def __init__(self, deltas_base_dir: str = "deltas"):
        self.base_dir = Path(deltas_base_dir)
        self.manifest_path = self.base_dir / "_manifest.json"
        self.manifest_lock = SimpleFileLock(self.base_dir / "_manifest.lock")
        self._ensure_base_dir()
        self._load_manifest()

    def _ensure_base_dir(self):
        """Ensures the base deltas directory exists."""
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _load_manifest(self):
        """Loads the manifest file or creates a new one."""
        with self.manifest_lock:
            if self.manifest_path.exists():
                try:
                    with open(self.manifest_path, 'r', encoding='utf-8') as f:
                        self.manifest = json.load(f)
                except json.JSONDecodeError:
                    print("Warning: Manifest file is corrupted. Creating a new one.")
                    self.manifest = {"deltas": []}
                    # Immediately save the newly created empty manifest
                    with open(self.manifest_path, 'w', encoding='utf-8') as f:
                        json.dump(self.manifest, f, indent=2)
            else:
                self.manifest = {"deltas": []}
                # Immediately save the newly created empty manifest
                with open(self.manifest_path, 'w', encoding='utf-8') as f:
                    json.dump(self.manifest, f, indent=2)

    def _save_manifest(self):
        """Saves the manifest file with crash-safe writing."""
        with self.manifest_lock:
            temp_path = self.manifest_path.with_suffix(f".tmp.{uuid.uuid4().hex}")
            try:
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(self.manifest, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temp_path, self.manifest_path)
            except Exception as e:
                print(f"Error saving manifest: {e}")
                if temp_path.exists():
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass

    def create_delta(self, key: str, scope: str, target: str, op: str, path: str, value: str, value_mode: str = "RAW"):
        """
        Creates, writes, and registers a new delta file.

        Args:
            key (str): The delta key from delta_key.md (e.g., 'P-001').
            scope (str): The high-level category (e.g., 'memory', 'conversation').
            target (str): The specific file or object (e.g., 'user_profile').
            op (str): The operation ('append', 'set', 'upsert', 'remove').
            path (str): The dot-notation path within the target.
            value (str): The value to apply.
            value_mode (str): How the value is encoded ('RAW' or 'EOF').
        """
        now = datetime.utcnow()
        date_path = self.base_dir / now.strftime("%Y/%m/%d")
        date_path.mkdir(parents=True, exist_ok=True)

        delta_id = f"delta_{now.strftime('%Y%m%dT%H%M%S%f')}_{uuid.uuid4().hex[:8]}"
        delta_filename = f"{delta_id}.txt"
        delta_filepath = date_path / delta_filename

        delta_content = f"DELTA|{key}|{scope}|{target}|{op}|{path}|{value_mode}|{value}"

        temp_filepath = delta_filepath.with_suffix(f".tmp.{uuid.uuid4().hex}")
        try:
            with open(temp_filepath, 'w', encoding='utf-8') as f:
                f.write(delta_content)
                f.flush()
                os.fsync(f.fileno())
            os.rename(temp_filepath, delta_filepath)

            print(f"Successfully created delta: {delta_filepath}")

            # Update and save manifest
            # Use forward slashes for cross-platform compatibility in the manifest
            relative_path = delta_filepath.relative_to(self.base_dir).as_posix()
            self.manifest["deltas"].append(relative_path)
            self._save_manifest()

            return str(delta_filepath)

        except Exception as e:
            print(f"Error creating delta file: {e}")
            if temp_filepath.exists():
                os.remove(temp_filepath)
            return None

    def get_streams(self) -> dict:
        """Returns the current streams from the manifest."""
        self._load_manifest()
        return self.manifest.get("streams", {})

    def update_stream(self, name: str, value: str, enabled: bool = True):
        """Updates or creates a stream delta."""
        self._load_manifest()
        if "streams" not in self.manifest:
            self.manifest["streams"] = {}

        self.manifest["streams"][name] = {
            "value": value,
            "enabled": enabled,
            "updated_at": datetime.utcnow().isoformat()
        }
        self._save_manifest()
        print(f"Updated stream delta for '{name}'.")

    def toggle_stream(self, name: str, enabled: bool):
        """Toggles the enabled state of a stream delta."""
        self._load_manifest()
        if "streams" in self.manifest and name in self.manifest["streams"]:
            self.manifest["streams"][name]["enabled"] = enabled
            self._save_manifest()
            print(f"Toggled stream delta '{name}' to {enabled}.")
            return True
        return False

    def delete_stream(self, name: str):
        """Deletes a stream delta."""
        self._load_manifest()
        if "streams" in self.manifest and name in self.manifest["streams"]:
            del self.manifest["streams"][name]
            self._save_manifest()
            print(f"Deleted stream delta '{name}'.")
            return True
        return False

    def get_available_scripts(self) -> list:
        """Returns a list of available python scripts in the deltas directory."""
        scripts = []
        if self.base_dir.exists():
            for f in self.base_dir.glob("*.py"):
                if f.is_file():
                    scripts.append(f.name)
        return scripts

    def update_script_config(self, script_name: str, interval_seconds: int, enabled: bool):
        """Updates the scheduling configuration for a delta script."""
        self._load_manifest()
        if "scripts" not in self.manifest:
            self.manifest["scripts"] = {}

        if script_name not in self.manifest["scripts"]:
             self.manifest["scripts"][script_name] = {}

        self.manifest["scripts"][script_name]["interval"] = interval_seconds
        self.manifest["scripts"][script_name]["enabled"] = enabled
        self._save_manifest()
        print(f"Updated script config for '{script_name}'.")

    def get_scripts_config(self) -> dict:
        """Returns the script configurations."""
        self._load_manifest()
        return self.manifest.get("scripts", {})

    def update_script_last_run(self, script_name: str, last_run: float):
        """Updates the last run time for a script."""
        self._load_manifest()
        if "scripts" in self.manifest and script_name in self.manifest["scripts"]:
             self.manifest["scripts"][script_name]["last_run"] = last_run
             self._save_manifest()

    def get_delta_content(self) -> str:
        """
        Aggregates all enabled stream deltas into a formatted string.
        """
        self._load_manifest()
        streams = self.manifest.get("streams", {})

        content_lines = []
        for name, data in streams.items():
            if data.get("enabled", True):
                content_lines.append(f"{name}: {data.get('value', '')}")

        if not content_lines:
            return ""

        content = "\n".join(content_lines)
        return f"###DELTAS_START###\n{content}\n###DELTAS_END###"
