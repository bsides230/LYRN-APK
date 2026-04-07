import os
import json
import shutil
from pathlib import Path
from typing import List, Dict, Any, Optional

class DSManager:
    """
    Dynamic Snapshot Manager (DSManager)
    Handles the storage, retrieval, and active state of dynamic snapshots
    (e.g., job_instructions.txt, project contexts).
    """

    def __init__(self, base_dir: str = "automation/dynamic_snapshots"):
        self.base_dir = Path(base_dir)
        self.jobs_dir = self.base_dir / "jobs"
        self.projects_dir = self.base_dir / "projects"
        self.active_state_file = self.base_dir / "active_snapshots.json"

        # Ensure directories exist
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.projects_dir.mkdir(parents=True, exist_ok=True)

        # Initialize active state file if not exists
        if not self.active_state_file.exists():
            self._save_active_state({"jobs": [], "projects": []})

        self._ensure_examples()

    def _ensure_examples(self):
        """Creates example snapshots if the directory is empty."""
        example_job = "chat_to_job_example.txt"
        example_path = self.jobs_dir / example_job
        if not any(self.jobs_dir.iterdir()):
            try:
                with open(example_path, 'w', encoding='utf-8') as f:
                    f.write("This is a dynamically injected snapshot for the chat_to_job_example job.\nIt can contain any user-defined instructions, constraints, or previous chat inputs to guide the LLM's response.\n\nInput query: Summarize the current goals of the LYRN project.")
            except Exception as e:
                print(f"Failed to create example DSManager file: {e}")

    def _read_active_state(self) -> Dict[str, List[str]]:
        try:
            with open(self.active_state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {"jobs": [], "projects": []}

    def _save_active_state(self, state: Dict[str, List[str]]):
        temp_path = self.active_state_file.with_suffix(".tmp")
        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
            shutil.move(temp_path, self.active_state_file)
        except IOError as e:
            print(f"Error saving active state: {e}")

    def list_snapshots(self, category: str) -> List[Dict[str, Any]]:
        """Lists all snapshots in a given category ('jobs' or 'projects')."""
        target_dir = self.jobs_dir if category == "jobs" else self.projects_dir
        snapshots = []
        active_state = self._read_active_state()
        active_list = active_state.get(category, [])

        if target_dir.exists():
            for f in target_dir.glob("*.txt"):
                snapshots.append({
                    "name": f.name,
                    "active": f.name in active_list,
                    "content": f.read_text(encoding='utf-8')
                })
        return sorted(snapshots, key=lambda x: x["name"])

    def save_snapshot(self, category: str, name: str, content: str) -> bool:
        """Saves a snapshot to the specified category."""
        target_dir = self.jobs_dir if category == "jobs" else self.projects_dir

        # Ensure name ends with .txt
        if not name.endswith('.txt'):
            name += '.txt'

        file_path = target_dir / name
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True
        except IOError as e:
            print(f"Error saving snapshot {name}: {e}")
            return False

    def delete_snapshot(self, category: str, name: str) -> bool:
        """Deletes a snapshot and removes it from active state."""
        target_dir = self.jobs_dir if category == "jobs" else self.projects_dir
        if not name.endswith('.txt'):
            name += '.txt'

        file_path = target_dir / name
        if file_path.exists():
            try:
                file_path.unlink()
                # Deactivate if it was active
                self.set_snapshot_active(category, name, False)
                return True
            except OSError as e:
                print(f"Error deleting snapshot {name}: {e}")
                return False
        return False

    def set_snapshot_active(self, category: str, name: str, active: bool) -> bool:
        """Sets a snapshot's active state."""
        if not name.endswith('.txt'):
            name += '.txt'

        state = self._read_active_state()
        cat_list = state.get(category, [])

        changed = False
        if active and name not in cat_list:
            cat_list.append(name)
            changed = True
        elif not active and name in cat_list:
            cat_list.remove(name)
            changed = True

        if changed:
            state[category] = cat_list
            self._save_active_state(state)
        return True

    def get_active_snapshots_content(self) -> str:
        """Retrieves the combined content of all currently active dynamic snapshots."""
        state = self._read_active_state()
        combined_content = []

        # Load active jobs
        for name in state.get("jobs", []):
            path = self.jobs_dir / name
            if path.exists():
                combined_content.append(f"--- Job Instruction: {name} ---\n{path.read_text(encoding='utf-8')}")

        # Load active projects
        for name in state.get("projects", []):
            path = self.projects_dir / name
            if path.exists():
                combined_content.append(f"--- Project Context: {name} ---\n{path.read_text(encoding='utf-8')}")

        return "\n\n".join(combined_content)
