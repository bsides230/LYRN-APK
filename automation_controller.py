import os
import sys
import json
import shutil
import time
import subprocess
import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any, List
from file_lock import SimpleFileLock

@dataclass
class Job:
    """Represents a single job to be executed by the Automation Controller."""
    name: str
    priority: int = 100
    when: str = "now"
    args: Dict[str, Any] = field(default_factory=dict)
    prompt: str = ""
    scripts: List[str] = field(default_factory=list)

class AutomationController:
    """
    Manages the definition, queuing, and execution of automated jobs by
    reading from and writing to a shared job_queue.json file.
    """
    def __init__(self, job_definitions_path: str = "automation/jobs", queue_path: str = "automation/job_queue.json"):
        self.job_definitions_path = Path(job_definitions_path)
        self.queue_path = Path(queue_path)
        self.queue_lock_path = self.queue_path.with_suffix(f"{self.queue_path.suffix}.lock")
        self.history_path = Path("automation/job_history.json")
        self.scripts_path = Path("automation/job_scripts")
        self.job_definitions = {}
        self._load_job_definitions()
        # Ensure the queue file exists
        if not self.queue_path.exists():
            self._write_queue_unsafe([])

    def _load_job_definitions(self):
        """
        Loads job definitions from the jobs.json file.
        """
        jobs_json_path = self.job_definitions_path / "jobs.json"
        if not jobs_json_path.exists():
            print("No jobs.json found. Creating default examples.")
            self._create_default_jobs()
            return

        try:
            with open(jobs_json_path, 'r', encoding='utf-8') as f:
                self.job_definitions = json.load(f)
            print(f"Loaded {len(self.job_definitions)} job definitions from jobs.json: {list(self.job_definitions.keys())}")
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading job definitions from {jobs_json_path}: {e}")
            self.job_definitions = {}

    def _create_default_jobs(self):
        """Creates a default jobs.json file if none is found."""
        default_jobs = {
            "summary_job": {
                "instructions": "Create a concise, factual summary of the provided text. Focus on key decisions, outcomes, and open items."
            },
            "keyword_job": {
                "instructions": "Extract the main keywords from the provided text as a JSON-formatted list. Example: [\"keyword1\", \"keyword2\"]"
            },
            "reflection_job": {
                "instructions": "Reflect on the conversation so far. Identify key insights, contradictions, or areas for future exploration. Propose next steps if applicable."
            }
        }
        self.job_definitions = default_jobs
        jobs_json_path = self.job_definitions_path / "jobs.json"
        try:
            with open(jobs_json_path, 'w', encoding='utf-8') as f:
                json.dump(self.job_definitions, f, indent=2)
            print(f"Created default jobs file at {jobs_json_path}")
        except IOError as e:
            print(f"Could not create default jobs file: {e}")

    def _read_queue_unsafe(self) -> List[Dict]:
        """Unsafely reads the job queue from the JSON file. Assumes lock is held."""
        try:
            if self.queue_path.exists() and self.queue_path.stat().st_size > 0:
                with open(self.queue_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not read job queue file, starting fresh. Error: {e}")
        return []

    def _write_queue_unsafe(self, queue_data: List[Dict]):
        """Unsafely writes the job queue to the JSON file using an atomic operation. Assumes lock is held."""
        try:
            temp_path = self.queue_path.with_suffix(f"{self.queue_path.suffix}.tmp")
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(queue_data, f, indent=2)
            shutil.move(temp_path, self.queue_path)
        except (IOError, OSError) as e:
            print(f"Error writing job queue file: {e}")

    def save_job_definition(self, job_name: str, instructions: str, trigger: str = "", scripts: List[str] = None):
        """Saves a job's instructions to the jobs.json file."""
        job_data = {
            "instructions": instructions,
            # 'trigger' is kept for legacy compatibility but not used
            "trigger": trigger,
            "scripts": scripts or []
        }

        jobs_json_path = self.job_definitions_path / "jobs.json"
        jobs_lock_path = jobs_json_path.with_suffix('.json.lock')

        try:
            with SimpleFileLock(jobs_lock_path):
                # Read existing jobs
                if jobs_json_path.exists():
                    with open(jobs_json_path, 'r', encoding='utf-8') as f:
                        all_jobs = json.load(f)
                else:
                    all_jobs = {}

                # Update or add the new job
                all_jobs[job_name] = job_data

                # Write back to the file
                with open(jobs_json_path, 'w', encoding='utf-8') as f:
                    json.dump(all_jobs, f, indent=2)

            # Update the in-memory dictionary as well
            self.job_definitions[job_name] = job_data
            print(f"Job definition for '{job_name}' saved successfully.")

        except (IOError, TimeoutError, json.JSONDecodeError) as e:
            print(f"Error saving job definition for '{job_name}': {e}")

    def delete_job_definition(self, job_name: str):
        """Deletes a job's definition from the jobs.json file."""
        jobs_json_path = self.job_definitions_path / "jobs.json"
        jobs_lock_path = jobs_json_path.with_suffix('.json.lock')

        try:
            with SimpleFileLock(jobs_lock_path):
                if jobs_json_path.exists():
                    with open(jobs_json_path, 'r', encoding='utf-8') as f:
                        all_jobs = json.load(f)
                else:
                    all_jobs = {}

                if job_name in all_jobs:
                    del all_jobs[job_name]

                with open(jobs_json_path, 'w', encoding='utf-8') as f:
                    json.dump(all_jobs, f, indent=2)

            if job_name in self.job_definitions:
                del self.job_definitions[job_name]
            print(f"Job definition for '{job_name}' deleted successfully.")

        except (IOError, TimeoutError, json.JSONDecodeError) as e:
            print(f"Error deleting job definition for '{job_name}': {e}")

    def add_job(self, name: str, priority: int = 100, when: str = "now", args: Optional[Dict[str, Any]] = None, job_id: Optional[str] = None):
        """Adds a new job to the file-based execution queue in a thread-safe manner."""
        if name not in self.job_definitions:
            print(f"Warning: Job '{name}' not defined. Cannot add to queue.")
            return

        # Use provided ID or generate one if strictly needed (though usually provided by UI)
        # If not provided, we don't force one unless required by get_queue consumers.
        new_job_dict = {
            "id": job_id if job_id else f"job_{int(time.time()*1000)}",
            "name": name,
            "priority": priority,
            "when": when,
            "args": args or {}
        }

        try:
            with SimpleFileLock(self.queue_lock_path):
                queue_data = self._read_queue_unsafe()
                queue_data.append(new_job_dict)
                self._write_queue_unsafe(queue_data)
            print(f"Job '{name}' added to the queue file. Queue size: {len(queue_data)}")
        except TimeoutError as e:
            print(f"Error adding job: {e}")

    def get_queue(self) -> List[Dict]:
        """Returns the current job queue."""
        try:
            with SimpleFileLock(self.queue_lock_path):
                return self._read_queue_unsafe()
        except TimeoutError:
            print("Error getting queue: Timeout")
            return []

    def remove_job_from_queue(self, job_id: str):
        """Removes a job from the queue by ID."""
        try:
            with SimpleFileLock(self.queue_lock_path):
                queue = self._read_queue_unsafe()
                new_queue = [j for j in queue if j.get("id") != job_id]
                self._write_queue_unsafe(new_queue)
        except TimeoutError:
            print("Error removing job: Timeout")

    def get_cycles(self) -> Dict[str, Any]:
        """Loads cycles from cycles.json"""
        path = self.job_definitions_path / "cycles.json"
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error reading cycles.json: {e}")
        return {}

    def save_cycle(self, name: str, triggers: List[Any]):
        """Saves a cycle definition."""
        path = self.job_definitions_path / "cycles.json"
        lock_path = path.with_suffix('.json.lock')

        try:
            with SimpleFileLock(lock_path):
                cycles = {}
                if path.exists():
                    try:
                        with open(path, 'r', encoding='utf-8') as f:
                            cycles = json.load(f)
                    except: pass

                cycles[name] = {"triggers": triggers}

                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(cycles, f, indent=2)
        except Exception as e:
            print(f"Error saving cycle: {e}")

    def delete_cycle(self, name: str):
        """Deletes a cycle definition."""
        path = self.job_definitions_path / "cycles.json"
        lock_path = path.with_suffix('.json.lock')

        try:
            with SimpleFileLock(lock_path):
                cycles = {}
                if path.exists():
                    try:
                        with open(path, 'r', encoding='utf-8') as f:
                            cycles = json.load(f)
                    except: pass

                if name in cycles:
                    del cycles[name]

                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(cycles, f, indent=2)
        except Exception as e:
            print(f"Error deleting cycle: {e}")

    def get_next_due_job(self) -> Optional[Job]:
        """Retrieves and consumes the next DUE job from the queue."""
        import datetime
        try:
            with SimpleFileLock(self.queue_lock_path):
                queue_data = self._read_queue_unsafe()
                if not queue_data:
                    return None

                now = datetime.datetime.now()
                due_idx = -1

                # Check for jobs that are due
                for i, job in enumerate(queue_data):
                    when_str = job.get("when", "now")
                    if when_str == "now":
                        due_idx = i
                        break

                    try:
                        # Handle potential Z suffix or generic ISO
                        clean_iso = when_str.replace("Z", "+00:00")
                        when_dt = datetime.datetime.fromisoformat(clean_iso)
                        # Naive vs Aware check - assume system local time if naive, or just compare
                        if when_dt.tzinfo is None:
                             # Make aware if needed or keep naive. 'now' is naive.
                             pass

                        # Compare
                        if when_dt <= now:
                             due_idx = i
                             break
                    except:
                        # If parsing fails, treat as due to clear it out/run it.
                        print(f"Warning: Invalid date '{when_str}' for job {job.get('name')}")
                        due_idx = i
                        break

                if due_idx != -1:
                    next_job_dict = queue_data.pop(due_idx)
                    self._write_queue_unsafe(queue_data)

                    instruction_prompt = self.get_job_instructions_prompt(next_job_dict["name"], next_job_dict.get("args", {}))
                    if instruction_prompt is None:
                        instruction_prompt = ""

                    # Fetch script list from definition
                    job_def = self.job_definitions.get(next_job_dict["name"], {})
                    scripts = job_def.get("scripts", [])

                    return Job(
                        name=next_job_dict["name"],
                        priority=next_job_dict.get("priority", 100),
                        when=next_job_dict.get("when", "now"),
                        args=next_job_dict.get("args", {}),
                        prompt=instruction_prompt,
                        scripts=scripts
                    )

                return None

        except TimeoutError as e:
            print(f"Error getting next job: {e}")
            return None

    def get_next_job(self) -> Optional[Job]:
        """Deprecated: Use get_next_due_job"""
        return self.get_next_due_job()

    def has_pending_jobs(self) -> bool:
        """
        Checks if there are any jobs in the queue file.
        This is a non-locking read, a small chance of a race condition is acceptable
        for this status check.
        """
        queue_data = self._read_queue_unsafe()
        return len(queue_data) > 0

    def get_job_trigger(self, job_name: str) -> Optional[str]:
        """
        Gets the trigger prompt for a given job.
        """
        if job_name not in self.job_definitions:
            print(f"Error: Cannot get trigger for undefined job '{job_name}'.")
            return None
        return self.job_definitions[job_name].get("trigger")

    def get_job_instructions_prompt(self, job_name: str, args: Dict[str, Any]) -> Optional[str]:
        """
        Constructs the instruction prompt for a given job.
        """
        if job_name not in self.job_definitions:
            print(f"Error: Cannot get instructions for undefined job '{job_name}'.")
            return None

        job_instructions = self.job_definitions[job_name].get("instructions", "")

        for key, value in args.items():
            placeholder = f"{{{key}}}"
            job_instructions = job_instructions.replace(placeholder, str(value))

        # Return raw instructions for chat injection
        return job_instructions

    def get_available_scripts(self) -> List[str]:
        """Lists available python scripts in automation/job_scripts"""
        if not self.scripts_path.exists():
            return []

        scripts = []
        for f in self.scripts_path.glob("*.py"):
            scripts.append(f.name)
        return sorted(scripts)

    def execute_job_scripts(self, job: Job) -> Dict[str, Any]:
        """
        Executes the scripts associated with the job sequentially.
        Passes job.prompt (instructions) as the first argument.
        """
        script_results = []
        all_success = True

        for script_name in job.scripts:
            script_path = self.scripts_path / script_name
            if not script_path.exists():
                print(f"[Job {job.name}] Script not found: {script_name}")
                script_results.append({
                    "script": script_name,
                    "status": "error",
                    "message": "Script file not found",
                    "timestamp": time.time()
                })
                all_success = False
                break

            print(f"[Job {job.name}] Running script: {script_name}")
            try:
                # Run subprocess
                # Pass instructions as argument 1
                cmd = [sys.executable, str(script_path), job.prompt]

                # Run with timeout (e.g. 60s per script)
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    encoding='utf-8' # Ensure UTF-8
                )

                # Check exit code
                if result.returncode == 0:
                    try:
                        # Try parsing last line as JSON if possible, or just store stdout
                        output_data = result.stdout.strip()
                        # Often script prints JSON lines. We might want the last one.
                        # For now, just store the full stdout.
                        script_results.append({
                            "script": script_name,
                            "status": "success",
                            "stdout": result.stdout,
                            "stderr": result.stderr,
                            "timestamp": time.time()
                        })
                    except Exception:
                         script_results.append({
                            "script": script_name,
                            "status": "success",
                            "stdout": result.stdout,
                            "timestamp": time.time()
                        })
                else:
                    print(f"[Job {job.name}] Script {script_name} failed with code {result.returncode}")
                    script_results.append({
                        "script": script_name,
                        "status": "failed",
                        "code": result.returncode,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "timestamp": time.time()
                    })
                    all_success = False
                    break # Stop execution chain on failure

            except subprocess.TimeoutExpired:
                print(f"[Job {job.name}] Script {script_name} timed out.")
                script_results.append({
                    "script": script_name,
                    "status": "timeout",
                    "timestamp": time.time()
                })
                all_success = False
                break
            except Exception as e:
                print(f"[Job {job.name}] Script {script_name} execution error: {e}")
                script_results.append({
                    "script": script_name,
                    "status": "error",
                    "message": str(e),
                    "timestamp": time.time()
                })
                all_success = False
                break

        final_status = "success" if all_success else "failed"
        self.log_job_history(job.name, script_results, final_status)

        return {
            "status": final_status,
            "results": script_results
        }

    def log_job_history(self, job_name: str, results: List[Dict], status: str, filepath: str = None):
        """Logs job execution to history file."""
        entry = {
            "id": f"hist_{int(time.time()*1000)}",
            "job_name": job_name,
            "timestamp": datetime.datetime.now().isoformat(),
            "status": status,
            "scripts_run": len(results),
            "details": results
        }

        if filepath:
            entry["filepath"] = filepath

        try:
            history = []
            if self.history_path.exists():
                with open(self.history_path, 'r', encoding='utf-8') as f:
                    history = json.load(f)

            # Prepend new entry
            history.insert(0, entry)

            # Limit history size (e.g. 100 entries)
            if len(history) > 100:
                history = history[:100]

            with open(self.history_path, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=2)

        except Exception as e:
            print(f"Error logging job history: {e}")

    def get_job_history(self) -> List[Dict]:
        """Returns the job history."""
        if not self.history_path.exists():
            return []
        try:
            with open(self.history_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return []

    def clear_job_history(self):
        """Clears the job history file and deletes job output files."""
        try:
            # Clear JSON
            with open(self.history_path, 'w', encoding='utf-8') as f:
                json.dump([], f)

            # Clear jobs directory
            jobs_dir = Path("jobs")
            if jobs_dir.exists():
                for f in jobs_dir.glob("*.txt"):
                    try:
                        f.unlink()
                    except Exception as e:
                        print(f"Error deleting job file {f}: {e}")

        except Exception as e:
            print(f"Error clearing job history: {e}")
