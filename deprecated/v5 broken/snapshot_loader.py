import os
import json
from pathlib import Path
from typing import Optional, List, Dict
from settings_manager import SettingsManager
from automation_controller import AutomationController

# Script directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

class SnapshotLoader:
    """Loads the static base prompt from the 'build_prompt' directory."""

    def __init__(self, settings_manager: SettingsManager, automation_controller: AutomationController):
        self.settings_manager = settings_manager
        self.automation_controller = automation_controller
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
        config = self._load_json_file(self.config_path)
        if config and config.get("master_prompt_locked", False):
            print("Master prompt is locked. Loading directly from file.")
            return self._load_text_file(self.master_prompt_path)

        print("Building master prompt from components...")

        prompt_parts = []

        components_path = os.path.join(self.build_prompt_dir, "components.json")
        components = self._load_json_file(components_path) or []

        # Filter for active components and sort by order
        active_components = sorted([c for c in components if c.get('active', True)], key=lambda x: x.get('order', 0))

        # --- Build the Static RWI block first ---
        rwi_config_path = os.path.join(self.build_prompt_dir, "rwi_config.json")
        rwi_config = self._load_json_file(rwi_config_path) or {}
        rwi_start_bracket = rwi_config.get("begin_bracket", "###RWI_INSTRUCTIONS_START###")
        rwi_end_bracket = rwi_config.get("end_bracket", "###RWI_INSTRUCTIONS_END###")

        rwi_parts = []
        rwi_intro = self._load_text_file(os.path.join(self.build_prompt_dir, "rwi_intro.txt"))

        for component in active_components:
            component_name = component['name']
            if component_name == "RWI": continue # Skip the RWI meta-component itself

            config_path = os.path.join(self.build_prompt_dir, component_name, "config.json")

            config = self._load_json_file(config_path)
            if config and "rwi_text" in config and config["rwi_text"]:
                rwi_parts.append(config["rwi_text"])

        if rwi_intro or rwi_parts:
            full_rwi_content = "\n\n".join([rwi_intro] + rwi_parts if rwi_intro else rwi_parts)
            full_rwi_block = f"{rwi_start_bracket}\n{full_rwi_content}\n{rwi_end_bracket}"
            prompt_parts.append(full_rwi_block)

        # --- Build the rest of the prompt components ---
        for component in active_components:
            component_name = component['name']
            if component_name == "RWI":
                continue

            component_dir = os.path.join(self.build_prompt_dir, component_name)

            # Generic component handling
            config_path = os.path.join(component_dir, "config.json")
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
        Loads the master prompt file.
        If the file exists, it is read directly to preserve the stable prefix for KV cache.
        If it does not exist, it is rebuilt from components.
        """
        print("Loading base prompt...")
        if os.path.exists(self.master_prompt_path):
            # Read from cache to avoid rebuilding and potentially changing the prefix
            return self._load_text_file(self.master_prompt_path)
        else:
            # First run or missing file: build it
            print("Master prompt not found. Building from components...")
            return self.build_master_prompt_from_components()
