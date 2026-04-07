import os
import sys
import re
import psutil
import asyncio
import json
import datetime
import threading
import subprocess
import collections
import time
import hashlib
import shutil
import aiohttp
import aiofiles
from typing import Optional, List, Dict, Any
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, BackgroundTasks, HTTPException, Header, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from pydantic import BaseModel
import uvicorn

from settings_manager import SettingsManager
from automation_controller import AutomationController
from chat_manager import ChatManager
from backend.ds_manager import DSManager

try:
    import pynvml
except ImportError:
    pynvml = None

# Global reference to the main event loop
main_loop: Optional[asyncio.AbstractEventLoop] = None
LYRN_TOKEN: Optional[str] = None

# Global LLM Stats (populated from log parsing)
extended_llm_stats = {
    "kv_cache_reused": 0,
    "prompt_tokens": 0,
    "prompt_speed": 0.0,
    "eval_tokens": 0,
    "eval_speed": 0.0,
    "total_tokens": 0,
    "load_time": 0.0,
    "total_time": 0.0,
    "tokenization_time_ms": 0.0,
    "generation_time_ms": 0.0
}

# Global Active Downloads
active_downloads = {} # filename -> { status, bytes, total, pct, error, timestamp }

# --- DiskJournalLogger ---
class DiskJournalLogger:
    def __init__(self, log_dir="logs", lines_per_chunk=1000):
        self.log_dir = Path(log_dir)
        self.lines_per_chunk = lines_per_chunk
        self.current_session_dir = None
        self.current_chunk_index = 0
        self.current_chunk_lines = 0
        self.current_chunk_path = None

        # In-memory buffer for live streaming (tail)
        self.subscribers = set()
        self._lock = None

        # Initialize session
        self._start_session()

    @property
    def lock(self):
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _start_session(self):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.current_session_dir = self.log_dir / f"session_{timestamp}"
        self.current_session_dir.mkdir(parents=True, exist_ok=True)
        self._start_new_chunk()
        print(f"[System] Logging to session: {self.current_session_dir}")

    def _start_new_chunk(self):
        self.current_chunk_index += 1
        filename = f"chunk_{self.current_chunk_index:03d}.log"
        self.current_chunk_path = self.current_session_dir / filename
        self.current_chunk_lines = 0
        # Create empty file
        with open(self.current_chunk_path, "w", encoding="utf-8") as f:
            pass

    async def emit(self, level: str, msg: str, source: str = "System"):
        event = {
            "ts": datetime.datetime.now().isoformat(),
            "level": level,
            "msg": msg,
            "source": source
        }

        # 1. Write to Disk
        try:
            line = json.dumps(event) + "\n"
            with open(self.current_chunk_path, "a", encoding="utf-8") as f:
                f.write(line)

            self.current_chunk_lines += 1
            if self.current_chunk_lines >= self.lines_per_chunk:
                self._start_new_chunk()

        except Exception as e:
            print(f"Logging Failed: {e}")

        # 2. Log to console
        print(f"[{level}] {source}: {msg}")

        # 3. Notify subscribers (Live Stream)
        async with self.lock:
            for q in self.subscribers:
                await q.put(event)

    async def subscribe(self, request: Request):
        q = asyncio.Queue()
        async with self.lock:
            self.subscribers.add(q)

        try:
            # Yield initial connection message
            yield f"data: {json.dumps({'level':'Success', 'msg': 'Connected to Log Stream', 'ts': datetime.datetime.now().isoformat(), 'source': 'System'})}\n\n"

            while True:
                if await request.is_disconnected():
                    break

                try:
                    event = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield f": heartbeat\n\n"
        finally:
            async with self.lock:
                if q in self.subscribers:
                    self.subscribers.remove(q)

    # --- Historical Access Methods ---
    def list_sessions(self):
        if not self.log_dir.exists():
            return []
        sessions = []
        for d in self.log_dir.iterdir():
            if d.is_dir() and d.name.startswith("session_"):
                # timestamp from name
                ts_str = d.name.replace("session_", "")
                sessions.append({"id": d.name, "timestamp": ts_str})
        return sorted(sessions, key=lambda x: x["timestamp"], reverse=True)

    def list_chunks(self, session_id):
        session_path = self.log_dir / session_id
        if not session_path.exists():
            return []
        chunks = []
        for f in session_path.glob("chunk_*.log"):
            # Parse index
            try:
                idx = int(f.stem.split("_")[1])
                chunks.append({"id": f.name, "index": idx, "size": f.stat().st_size})
            except: pass
        return sorted(chunks, key=lambda x: x["index"])

    def get_chunk_content(self, session_id, chunk_id):
        path = self.log_dir / session_id / chunk_id
        if not path.exists():
            return []

        lines = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        try:
                            lines.append(json.loads(line))
                        except: pass
        except Exception:
            return []
        return lines

# Global Logger
logger = DiskJournalLogger()
settings_manager = SettingsManager()
automation_controller = AutomationController()
ds_manager = DSManager()

# Initialize ChatManager (Needs settings to be loaded)
settings_manager.load_or_detect_first_boot()
role_mappings = {
    "assistant": "final_output",
    "model": "final_output",
    "thinking": "thinking_process",
    "analysis": "thinking_process"
}
chat_manager = ChatManager(
    settings_manager.settings.get("paths", {}).get("chat", "chat/"),
    settings_manager,
    role_mappings
)

# --- Helper Functions ---
def run_delta_scripts():
    """Run all enabled delta scripts synchronously so streams are up-to-date before model input."""
    try:
        scripts_config = delta_manager_api.get_scripts_config()
        for script_name, config in scripts_config.items():
            if config.get("enabled", False):
                script_path = Path("deltas") / script_name
                if script_path.exists():
                    try:
                        print(f"[Deltas] Running script: {script_name}")
                        subprocess.run(
                            [sys.executable, str(script_path)],
                            cwd=os.getcwd(),
                            timeout=30,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL
                        )
                        delta_manager_api.update_script_last_run(script_name, time.time())
                    except subprocess.TimeoutExpired:
                        print(f"[Deltas] Script {script_name} timed out (30s).")
                    except Exception as e:
                        print(f"[Deltas] Error running {script_name}: {e}")
    except Exception as e:
        print(f"[Deltas] run_delta_scripts error: {e}")


def trigger_chat_generation(message: str, folder: str = "chat"):
    """Creates an input payload and triggers the worker."""
    # Run enabled delta scripts first so streams are fresh for this generation
    run_delta_scripts()

    # Ensure directory
    os.makedirs(folder, exist_ok=True)

    if folder == "jobs":
        input_path = os.path.join(folder, "job_input.json")
        raw_output_path = os.path.join(folder, "job_raw_output.txt")
        completion_path = os.path.join(folder, "job_completion.json")
        filepath = os.path.abspath(input_path)

        # Read existing input (may have been created by chat_endpoint with user_message)
        input_payload = {}
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    input_payload = json.load(f)
            except (json.JSONDecodeError, IOError):
                input_payload = {}

        # Merge job instructions into the payload
        input_payload["job_instructions"] = message

        # If no user_message was set (non-chat job), use instructions as user message
        if "user_message" not in input_payload or not input_payload["user_message"]:
            input_payload["user_message"] = message
            input_payload["source"] = "job"

        # Write updated input payload
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(input_payload, f, indent=2)
        print(f"[System] Created job input: {filepath} (source={input_payload.get('source', 'unknown')})")

        # Clear previous raw output to avoid stale reads by the capture layer
        if os.path.exists(raw_output_path):
            try:
                os.remove(raw_output_path)
            except Exception as e:
                print(f"[System] Error clearing old raw output: {e}")

        # Clear previous completion artifact
        if os.path.exists(completion_path):
            try:
                os.remove(completion_path)
            except Exception as e:
                print(f"[System] Error clearing old completion artifact: {e}")
    else:
        # Legacy direct-chat path (non-job)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{folder}/{folder}_{timestamp}.txt"
        filepath = os.path.abspath(filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"user\n{message}\n")
        print(f"[System] Created chat file: {filepath}")

    # Write Trigger
    with open("chat_trigger.txt", "w", encoding="utf-8") as f:
        f.write(filepath)
    print(f"[System] Wrote trigger file: chat_trigger.txt")

    return filepath, os.path.basename(filepath)

# --- Scheduler Loop ---
async def scheduler_loop():
    print("[Scheduler] Starting scheduler loop...")
    while True:
        try:
            # Check for due jobs
            job = automation_controller.get_next_due_job()
            if job:
                print(f"[Scheduler] Executing job: {job.name}")

                # 1. Execute Scripts if any
                scripts_ok = True
                if job.scripts:
                    print(f"[Scheduler] Running scripts for job: {job.name}")
                    # Run in executor to avoid blocking the event loop
                    result = await main_loop.run_in_executor(None, automation_controller.execute_job_scripts, job)
                    if result["status"] != "success":
                        print(f"[Scheduler] Scripts failed for job {job.name}. Aborting chat generation.")
                        scripts_ok = False

                # 2. Trigger Chat if scripts ok (or no scripts) AND prompt exists
                # 2. Activate Dynamic Snapshot if present
                if job.instructions:
                    print(f"[Scheduler] Activating dynamic snapshot for job: {job.name}")
                    ds_manager.save_snapshot("jobs", job.name, job.instructions)
                    ds_manager.set_snapshot_active("jobs", job.name, True)

                # 3. Trigger Chat if scripts ok (or no scripts) AND prompt exists
                if scripts_ok:
                    if job.prompt:
                        # Use "jobs" folder for automated tasks
                        filepath, _ = trigger_chat_generation(job.prompt, folder="jobs")

                        # Monitor chat file for completion to deactivate dynamic snapshot
                        if job.instructions:
                            asyncio.create_task(_monitor_job_completion(filepath, job.name))

                        # Log the prompt generation step
                        automation_controller.log_job_history(
                            job.name,
                            [{"message": "Prompt triggered successfully."}],
                            "success",
                            filepath=filepath
                        )
                    elif not job.scripts:
                        # Only log this if there were no scripts either
                        print(f"[Scheduler] Job {job.name} has no prompt/instructions and no scripts.")
                        if job.instructions:
                            ds_manager.set_snapshot_active("jobs", job.name, False)
                else:
                    if job.instructions:
                        ds_manager.set_snapshot_active("jobs", job.name, False)

            await asyncio.sleep(0.5) # Check frequently
        except Exception as e:
            print(f"[Scheduler] Error in loop: {e}")
            await asyncio.sleep(0.5)

async def _monitor_job_completion(filepath: str, job_name: str):
    """Monitors the explicit completion artifact to finalize job and deactivate dynamic snapshot."""
    max_retries = 3600  # 1 hour timeout
    retries = 0

    input_path = Path(filepath)
    if input_path.parent.name == "jobs":
        completion_path = input_path.parent / "job_completion.json"
    else:
        completion_path = input_path.parent / f"{input_path.stem}_completion.json"

    while retries < max_retries:
        await asyncio.sleep(1)
        retries += 1
        try:
            if not completion_path.exists():
                continue

            # Parse and validate the completion artifact
            with open(completion_path, 'r', encoding='utf-8') as f:
                completion_data = json.load(f)

            # Validation logic
            if not isinstance(completion_data, dict) or "status" not in completion_data:
                print(f"[Scheduler] Invalid completion artifact for job {job_name}. Retrying...")
                continue

            status = completion_data.get("status")
            print(f"[Scheduler] Job {job_name} completed with status: {status}. Deactivating dynamic snapshot.")

            # Now delete the artifact
            try:
                completion_path.unlink()
            except Exception as e:
                print(f"[Scheduler] Error deleting completion artifact: {e}")

            ds_manager.set_snapshot_active("jobs", job_name, False)
            return

        except json.JSONDecodeError:
            print(f"[Scheduler] Job {job_name} completion artifact is unreadable/not yet complete JSON.")
            # Let it retry in case of a race (though atomic rename should prevent this)
        except Exception as e:
            print(f"[Scheduler] Error monitoring job completion: {e}")
            break

    # Timeout cleanup
    print(f"[Scheduler] Job {job_name} completion monitor timed out.")
    ds_manager.set_snapshot_active("jobs", job_name, False)

# --- Worker Controller ---
class WorkerController:
    """Manages the headless worker process."""
    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self.worker_script = "model_runner.py"

    def get_status(self):
        with self._lock:
            running = self.process is not None and self.process.poll() is None

            # Check LLM status flag if running
            llm_status = "unknown"
            error_msg = None

            if running:
                try:
                    flag_path = Path("global_flags/llm_status.txt")
                    if flag_path.exists():
                        llm_status = flag_path.read_text().strip()
                except Exception:
                    pass
            else:
                llm_status = "stopped"

            # Check for error file if status is error
            if llm_status == "error":
                 try:
                    err_path = Path("global_flags/last_error.txt")
                    if err_path.exists():
                        error_msg = err_path.read_text().strip()
                 except: pass

            return {
                "running": running,
                "pid": self.process.pid if running else None,
                "llm_status": llm_status,
                "error_message": error_msg
            }

    def start_worker(self):
        with self._lock:
            if self.process is not None and self.process.poll() is None:
                return {"success": False, "message": "Worker already running."}

            try:
                # Start the worker process
                self.process = subprocess.Popen(
                    [sys.executable, "-u", self.worker_script],
                    cwd=os.getcwd(),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding='utf-8',
                    errors='replace'
                )

                # Start threads to forward output to logger
                threading.Thread(target=self._monitor_output, args=(self.process.stdout, "WorkerOut"), daemon=True).start()
                threading.Thread(target=self._monitor_output, args=(self.process.stderr, "WorkerErr"), daemon=True).start()

                return {"success": True, "message": "Worker started."}
            except Exception as e:
                return {"success": False, "message": f"Failed to start worker: {e}"}

    def stop_worker(self):
        with self._lock:
            if self.process is None or self.process.poll() is not None:
                return {"success": False, "message": "Worker not running."}

            try:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()

                self.process = None
                return {"success": True, "message": "Worker stopped."}
            except Exception as e:
                return {"success": False, "message": f"Error stopping worker: {e}"}

    def _monitor_output(self, stream, source):
        """Reads output from the subprocess and logs it."""
        try:
            for line in iter(stream.readline, ''):
                if line:
                    clean_line = line.strip()

                    # Parse extended stats from llama.cpp logs
                    try:
                        # KV Cache
                        kv_match = re.search(r'(\d+)\s+prefix-match hit', clean_line)
                        if kv_match:
                            extended_llm_stats["kv_cache_reused"] = int(kv_match.group(1))

                        # Prompt Eval
                        prompt_match = re.search(r'prompt eval time\s*=\s*([\d.]+)\s*ms\s*/\s*(\d+)\s*tokens.*?([\d.]+)\s*ms per token', clean_line)
                        if prompt_match:
                            ms = float(prompt_match.group(1))
                            tokens = int(prompt_match.group(2))
                            ms_per_tok = float(prompt_match.group(3))
                            extended_llm_stats["tokenization_time_ms"] = ms
                            extended_llm_stats["prompt_tokens"] = tokens
                            extended_llm_stats["prompt_speed"] = 1000.0 / ms_per_tok if ms_per_tok > 0 else 0.0

                        # Eval (Generation)
                        eval_match = re.search(r'eval time\s*=\s*([\d.]+)\s*ms\s*/\s*(\d+)\s*runs.*?([\d.]+)\s*ms per token', clean_line)
                        if eval_match:
                            ms = float(eval_match.group(1))
                            tokens = int(eval_match.group(2))
                            ms_per_tok = float(eval_match.group(3))
                            extended_llm_stats["generation_time_ms"] = ms
                            extended_llm_stats["eval_tokens"] = tokens
                            extended_llm_stats["eval_speed"] = 1000.0 / ms_per_tok if ms_per_tok > 0 else 0.0

                        # Load Time
                        load_match = re.search(r'load time\s*=\s*([\d.]+)\s*ms', clean_line)
                        if load_match:
                            extended_llm_stats["load_time"] = float(load_match.group(1))

                        # Total Time
                        total_match = re.search(r'total time\s*=\s*([\d.]+)\s*ms', clean_line)
                        if total_match:
                            extended_llm_stats["total_time"] = float(total_match.group(1)) / 1000.0 # Convert to seconds

                        # Update totals
                        extended_llm_stats["total_tokens"] = extended_llm_stats["prompt_tokens"] + extended_llm_stats["eval_tokens"]

                    except Exception:
                        pass

                    if main_loop and clean_line:
                        asyncio.run_coroutine_threadsafe(logger.emit("Info", clean_line, source), main_loop)
                    elif clean_line:
                        print(f"[{source}] {clean_line}")
        except Exception:
            pass
        finally:
            stream.close()

worker_controller = WorkerController()

# --- Pydantic Models ---
class PresetModel(BaseModel):
    preset_id: str
    config: Dict[str, Any]

class ActiveConfigModel(BaseModel):
    config: Dict[str, Any]

class ChatRequest(BaseModel):
    message: str

class JobDefinitionModel(BaseModel):
    name: str
    instructions: str
    trigger: str
    scripts: List[str] = []

class JobScheduleModel(BaseModel):
    id: Optional[str] = None
    job_name: str
    scheduled_datetime_iso: str
    priority: int = 100
    args: Optional[Dict[str, Any]] = None

class DSModel(BaseModel):
    name: str
    content: str
    active: bool = False

class DSActiveModel(BaseModel):
    active: bool

class CycleModel(BaseModel):
    name: str
    triggers: List[Any]

class ModelFetchRequest(BaseModel):
    url: str
    filename: Optional[str] = None
    expected_sha256: Optional[str] = None

class SnapshotSaveModel(BaseModel):
    filename: str
    components: List[Dict[str, Any]]

class SnapshotLoadModel(BaseModel):
    filename: str

class DeltaUpdateModel(BaseModel):
    name: str
    value: str

class DeltaToggleModel(BaseModel):
    enabled: bool

class DeltaScriptConfigModel(BaseModel):
    interval: int
    enabled: bool

# --- App Setup ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    global main_loop, LYRN_TOKEN
    main_loop = asyncio.get_running_loop()

    # Ensure required directories exist on fresh clone
    for _d in ["models", "global_flags", "chat", "jobs", "logs"]:
        Path(_d).mkdir(exist_ok=True)

    # Load Admin Token
    token_file = Path("admin_token.txt")
    if token_file.exists():
        try:
            LYRN_TOKEN = token_file.read_text(encoding="utf-8").strip()
            print("[System] Loaded admin token from admin_token.txt")
        except Exception as e:
            print(f"[System] Failed to read admin_token.txt: {e}")

    # Fallback to env var
    if not LYRN_TOKEN:
        LYRN_TOKEN = os.environ.get("LYRN_MODEL_TOKEN")
        if LYRN_TOKEN:
            print("[System] Loaded admin token from Environment Variable")
        elif not Path("global_flags/no_auth").exists():
            print("[System] Warning: No admin token found (admin_token.txt or LYRN_MODEL_TOKEN). Model management will be unavailable.")

    await logger.emit("Info", "Backend started.", "System")

    # Start Scheduler
    asyncio.create_task(scheduler_loop())

    yield

app = FastAPI(title="LYRN v5 Backend", lifespan=lifespan)

# Determine allowed origins
allowed_origins = settings_manager.settings.get("allowed_origins", [])
current_port = 8000
try:
    if os.path.exists("port.txt"):
        with open("port.txt", "r") as f:
            val = f.read().strip()
            if val.isdigit():
                current_port = int(val)
except: pass

defaults = [
    f"http://localhost:{current_port}",
    f"http://127.0.0.1:{current_port}"
]
# Ensure defaults are present
for d in defaults:
    if d not in allowed_origins:
        allowed_origins.append(d)

print(f"[System] Allowed Origins: {allowed_origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["X-Token", "Content-Type", "Authorization"],
)

# --- Routes ---

async def verify_token(x_token: Optional[str] = Header(None, alias="X-Token"), token: Optional[str] = None):
    # Check for No Auth Flag
    if Path("global_flags/no_auth").exists():
        return "NO_AUTH"

    # Support both Header (preferred) and Query Param (SSE/EventSource)
    auth_token = x_token or token
    if not LYRN_TOKEN or not auth_token or auth_token != LYRN_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid or missing token")
    return auth_token

@app.get("/api/auth/status")
async def get_auth_status():
    if Path("global_flags/no_auth").exists():
        return {"required": False}
    # If no token has been configured yet (fresh install), auth cannot be enforced
    if not LYRN_TOKEN:
        return {"required": False}
    return {"required": True}

@app.post("/api/verify_token", dependencies=[Depends(verify_token)])
async def verify_token_endpoint():
    return {"status": "valid"}

@app.get("/health")
async def health_check():
    try:
        cpu = psutil.cpu_percent()
    except (PermissionError, AttributeError, Exception):
        cpu = None

    ram = psutil.virtual_memory()

    try:
        disk = psutil.disk_usage('.')
    except (PermissionError, Exception):
        disk = None

    gpu_stats = {}
    if pynvml:
        try:
            pynvml.nvmlInit()
            device_count = pynvml.nvmlDeviceGetCount()
            for i in range(device_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                name = pynvml.nvmlDeviceGetName(handle)
                mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                try:
                    util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                    gpu_util = util.gpu
                except Exception:
                    gpu_util = 0

                gpu_stats[f"gpu_{i}"] = {
                    "name": name,
                    "vram_used_gb": mem_info.used / (1024**3),
                    "vram_total_gb": mem_info.total / (1024**3),
                    "vram_percent": (mem_info.used / mem_info.total) * 100,
                    "gpu_util_percent": gpu_util
                }
        except Exception as e:
            gpu_stats["error"] = str(e)

    worker_status = worker_controller.get_status()

    llm_stats = {}
    try:
        stats_path = Path("global_flags/llm_stats.json")
        if stats_path.exists():
            with open(stats_path, 'r', encoding='utf-8') as f:
                llm_stats = json.load(f)
    except Exception:
        pass

    # Merge with extended stats from memory
    llm_stats.update(extended_llm_stats)

    return {
        "status": "ok",
        "cpu": cpu,
        "ram": {
            "percent": ram.percent,
            "used_gb": ram.used / (1024**3),
            "total_gb": ram.total / (1024**3)
        },
        "disk": {
            "percent": disk.percent,
            "used_gb": disk.used / (1024**3),
            "total_gb": disk.total / (1024**3)
        } if disk else None,
        "gpu": gpu_stats,
        "worker": worker_status,
        "llm_stats": llm_stats
    }

# --- Delta Manager Endpoints ---

from delta_manager import DeltaManager
delta_manager_api = DeltaManager()

@app.get("/api/deltas", dependencies=[Depends(verify_token)])
async def get_deltas():
    streams = delta_manager_api.get_streams()
    result = []
    for name, data in streams.items():
        result.append({
            "name": name,
            "value": data.get("value", ""),
            "enabled": data.get("enabled", True),
            "updated_at": data.get("updated_at", "")
        })
    return result

@app.post("/api/deltas/update", dependencies=[Depends(verify_token)])
async def update_delta(data: DeltaUpdateModel):
    # Retrieve current enabled state if stream exists, else default to True
    current_streams = delta_manager_api.get_streams()
    enabled = True
    if data.name in current_streams:
        enabled = current_streams[data.name].get("enabled", True)

    delta_manager_api.update_stream(data.name, data.value, enabled)
    return {"success": True}

@app.post("/api/deltas/{delta_name}/toggle", dependencies=[Depends(verify_token)])
async def toggle_delta(delta_name: str, data: DeltaToggleModel):
    # Decode name which could be URL encoded
    from urllib.parse import unquote
    name = unquote(delta_name)
    success = delta_manager_api.toggle_stream(name, data.enabled)
    if success:
        return {"success": True}
    raise HTTPException(status_code=404, detail="Delta not found")

@app.delete("/api/deltas/{delta_name}", dependencies=[Depends(verify_token)])
async def delete_delta(delta_name: str):
    from urllib.parse import unquote
    name = unquote(delta_name)
    success = delta_manager_api.delete_stream(name)
    if success:
        return {"success": True}
    raise HTTPException(status_code=404, detail="Delta not found")

@app.get("/api/deltas/scripts", dependencies=[Depends(verify_token)])
async def get_delta_scripts():
    scripts = delta_manager_api.get_available_scripts()
    configs = delta_manager_api.get_scripts_config()
    result = []
    for script in scripts:
        config = configs.get(script, {})
        result.append({
            "name": script,
            "interval": config.get("interval", 60),
            "enabled": config.get("enabled", False),
            "last_run": config.get("last_run", 0)
        })
    return result

@app.post("/api/deltas/scripts/{script_name}", dependencies=[Depends(verify_token)])
async def update_delta_script(script_name: str, config: DeltaScriptConfigModel):
    delta_manager_api.update_script_config(script_name, config.interval, config.enabled)
    return {"success": True}


# Logging Endpoints
@app.get("/api/logs", dependencies=[Depends(verify_token)])
async def stream_logs(request: Request):
    return StreamingResponse(logger.subscribe(request), media_type="text/event-stream")

@app.get("/api/logs/sessions", dependencies=[Depends(verify_token)])
async def list_log_sessions():
    return logger.list_sessions()

@app.get("/api/logs/sessions/{session_id}/chunks", dependencies=[Depends(verify_token)])
async def list_log_chunks(session_id: str):
    return logger.list_chunks(session_id)

@app.get("/api/logs/sessions/{session_id}/chunks/{chunk_id}", dependencies=[Depends(verify_token)])
async def get_log_chunk(session_id: str, chunk_id: str):
    return logger.get_chunk_content(session_id, chunk_id)

# --- Debug Endpoint ---

@app.post("/api/debug/run", dependencies=[Depends(verify_token)])
async def run_debug_test(background_tasks: BackgroundTasks, preset: str = "1"):
    """Launch debug_live.py as a background process. Report written to docs/debug_reports/."""
    debug_script = Path("tests/debug_live.py")
    if not debug_script.exists():
        raise HTTPException(status_code=404, detail="tests/debug_live.py not found")

    Path("docs/debug_reports").mkdir(parents=True, exist_ok=True)
    runner_log = Path("docs/debug_reports/debug_runner.log")

    def _launch():
        with open(runner_log, "w", encoding="utf-8") as log:
            subprocess.Popen(
                [sys.executable, "-u", str(debug_script), "--preset", preset],
                cwd=os.getcwd(),
                stdout=log,
                stderr=log
            )

    background_tasks.add_task(_launch)
    return {"ok": True, "message": f"Debug test started (preset {preset}). Report → docs/debug_reports/ | Runner log → {runner_log}"}

# --- Snapshot Management Endpoints ---

@app.get("/api/snapshots", dependencies=[Depends(verify_token)])
async def list_snapshots():
    """Lists available .sns files in the snapshots/ directory."""
    snapshots_dir = Path("snapshots")
    if not snapshots_dir.exists():
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        return []

    snapshots = []
    for f in snapshots_dir.glob("*.sns"):
        stat = f.stat()
        snapshots.append({
            "name": f.name,
            "modified": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat()
        })
    return sorted(snapshots, key=lambda x: x['name'])

async def _save_components_to_build_prompt(components: List[Dict[str, Any]]):
    """Helper to save components to build_prompt directory."""
    try:
        base_dir = Path("build_prompt")
        base_dir.mkdir(parents=True, exist_ok=True)

        # 1. Save components.json (without content field)
        clean_components = []
        for c in components:
            copy = c.copy()
            if "content" in copy:
                del copy["content"]
            clean_components.append(copy)

        with open(base_dir / "components.json", "w", encoding='utf-8') as f:
            json.dump(clean_components, f, indent=2)

        # 2. Save content files
        for c in components:
            name = c.get("name")
            if not name or name == "RWI": continue

            content = c.get("content", "")
            comp_dir = base_dir / name
            comp_dir.mkdir(exist_ok=True)

            config_path = comp_dir / "config.json"
            config = {}
            if config_path.exists():
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                except: pass

            if "config" in c:
                frontend_config = c["config"]
                if "begin_bracket" in frontend_config: config["begin_bracket"] = frontend_config["begin_bracket"]
                if "end_bracket" in frontend_config: config["end_bracket"] = frontend_config["end_bracket"]
                if "rwi_text" in frontend_config: config["rwi_text"] = frontend_config["rwi_text"]

            if "content_file" not in config:
                config["content_file"] = "content.txt"

            with open(config_path, "w", encoding='utf-8') as f:
                json.dump(config, f, indent=2)

            with open(comp_dir / config["content_file"], "w", encoding='utf-8') as f:
                f.write(content)
        return True
    except Exception as e:
        print(f"Error saving to build_prompt: {e}")
        raise e

@app.post("/api/snapshots/save", dependencies=[Depends(verify_token)])
async def save_named_snapshot(data: SnapshotSaveModel):
    """Saves to a file AND updates the build_prompt."""
    try:
        # 1. Save to .sns file
        snapshots_dir = Path("snapshots")
        snapshots_dir.mkdir(parents=True, exist_ok=True)

        filename = data.filename
        if not filename.endswith(".sns"):
            filename += ".sns"

        file_path = snapshots_dir / filename
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data.components, f, indent=2)

        # 2. Update build_prompt (Active State)
        await _save_components_to_build_prompt(data.components)

        # 3. Update Settings (Active Snapshot)
        if not settings_manager.settings:
            settings_manager.load_or_detect_first_boot()

        settings_manager.settings["active_snapshot"] = filename
        settings_manager.save_settings()

        return {"success": True, "saved_as": filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/snapshots/load", dependencies=[Depends(verify_token)])
async def load_named_snapshot(data: SnapshotLoadModel):
    """Loads a specific .sns file into build_prompt and returns content."""
    try:
        snapshots_dir = Path("snapshots")
        filename = data.filename
        file_path = snapshots_dir / filename

        if not file_path.exists():
             raise HTTPException(status_code=404, detail="Snapshot file not found")

        with open(file_path, "r", encoding="utf-8") as f:
            components = json.load(f)

        # 1. Update build_prompt (Active State)
        await _save_components_to_build_prompt(components)

        # 2. Update Settings
        if not settings_manager.settings:
            settings_manager.load_or_detect_first_boot()

        settings_manager.settings["active_snapshot"] = filename
        settings_manager.save_settings()

        return components
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Chat Endpoint
@app.get("/api/chat/history", dependencies=[Depends(verify_token)])
async def get_chat_history():
    """Returns the current chat history as a list of messages."""
    return chat_manager.get_chat_history_messages()

@app.delete("/api/chat", dependencies=[Depends(verify_token)])
async def clear_chat_history():
    """Clears all chat history files."""
    try:
        chat_dir = Path(settings_manager.settings.get("paths", {}).get("chat", "chat/"))
        if chat_dir.exists():
            for f in chat_dir.glob("*.txt"):
                try:
                    f.unlink()
                except OSError as e:
                    print(f"Failed to delete {f}: {e}")
        return {"success": True, "message": "Chat history cleared."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/chat/{filename}", dependencies=[Depends(verify_token)])
async def delete_chat_file(filename: str):
    """Deletes a specific chat history file."""
    try:
        # Sanitize filename to prevent directory traversal
        filename = os.path.basename(filename)
        chat_dir = Path(settings_manager.settings.get("paths", {}).get("chat", "chat/"))
        file_path = chat_dir / filename

        if not file_path.exists():
            raise HTTPException(status_code=404, detail="File not found")

        file_path.unlink()
        return {"success": True, "message": f"Deleted {filename}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat/stop", dependencies=[Depends(verify_token)])
async def stop_chat_generation():
    """Triggers the worker to stop the current generation."""
    try:
        with open("stop_trigger.txt", "w", encoding="utf-8") as f:
            f.write("stop")
        print("[API] Wrote stop_trigger.txt")
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop generation: {e}")

@app.post("/api/chat", dependencies=[Depends(verify_token)])
async def chat_endpoint(request: ChatRequest):
    print(f"[API] Received chat request: {request.message[:50]}...")

    # Check for existing lock to prevent queue clogging and overwriting
    if Path("global_flags/chat_processing.txt").exists():
        raise HTTPException(status_code=429, detail="A chat request is already being processed.")

    try:
        # Write structured input payload for the model runner
        os.makedirs("jobs", exist_ok=True)
        input_payload = {
            "user_message": request.message,
            "source": "chat",
            "timestamp": datetime.datetime.now().isoformat()
        }
        with open("jobs/job_input.json", "w", encoding="utf-8") as f:
            json.dump(input_payload, f, indent=2)
        print(f"[API] Wrote structured input to jobs/job_input.json")

        # Create the lock file
        Path("global_flags").mkdir(exist_ok=True)
        with open("global_flags/chat_processing.txt", "w", encoding="utf-8") as f:
            f.write("processing")

        # Queue the chat_input_job
        automation_controller.add_job(name="chat_input_job")

        return {"success": True, "message": "Chat job queued"}
    except Exception as e:
        print(f"[API] Error queueing chat job: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/chat/status", dependencies=[Depends(verify_token)])
async def chat_status():
    processing = Path("global_flags/chat_processing.txt").exists()
    return {"processing": processing}


@app.get("/api/chat/stream_status", dependencies=[Depends(verify_token)])
async def chat_stream_status():
    """Returns whether the system is currently in final-output streaming mode."""
    final_output_active = Path("global_flags/final_output_mode.txt").exists()
    processing = Path("global_flags/chat_processing.txt").exists()
    return {
        "final_output_active": final_output_active,
        "processing": processing,
    }


@app.get("/api/chat/stream", dependencies=[Depends(verify_token)])
async def chat_stream():
    """
    SSE endpoint for live chat output streaming.

    The watcher script writes tokens to global_flags/chat_stream_buffer.txt
    once the LLM emits ##AFFORDANCE: FINAL_OUTPUT_START##.  This endpoint
    tails that buffer and forwards new content as SSE events so the chat
    module can display output in real-time.

    Event format:
      data: {"text": "<new tokens>"}      — new content chunk
      data: {"done": true}                — generation complete
    """
    stream_buffer = Path("global_flags/chat_stream_buffer.txt")
    final_output_flag = Path("global_flags/final_output_mode.txt")
    llm_status_file = Path("global_flags/llm_status.txt")

    async def generate():
        char_offset = 0
        stream_timeout = 300  # 5 min max stream
        start = time.time()

        while time.time() - start < stream_timeout:
            # Read new content from stream buffer
            if stream_buffer.exists():
                try:
                    content = stream_buffer.read_text(encoding="utf-8", errors="replace")
                    if len(content) > char_offset:
                        chunk = content[char_offset:]
                        char_offset += len(chunk)
                        yield f"data: {json.dumps({'text': chunk})}\n\n"
                except Exception:
                    pass

            # Check if generation is complete (LLM idle and no final_output flag)
            try:
                llm_status = llm_status_file.read_text().strip()
            except Exception:
                llm_status = "idle"

            if llm_status in ("idle", "stopped", "error") and not final_output_flag.exists():
                # Drain any remaining buffer content before signalling done
                if stream_buffer.exists():
                    try:
                        content = stream_buffer.read_text(encoding="utf-8", errors="replace")
                        if len(content) > char_offset:
                            chunk = content[char_offset:]
                            yield f"data: {json.dumps({'text': chunk})}\n\n"
                    except Exception:
                        pass
                yield f"data: {json.dumps({'done': True})}\n\n"
                break

            await asyncio.sleep(0.1)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# --- Output Viewer Endpoints ---

@app.get("/api/output/history", dependencies=[Depends(verify_token)])
async def output_history_list():
    """
    Returns the user-visible audit log of chat pairs from output_history/.
    Each entry: timestamp, user_message, response.
    Newest first. This folder is NEVER read by the LLM and has its own Clear endpoint.
    """
    hist_dir = Path("output_history")
    entries = []
    if hist_dir.exists():
        for f in sorted(hist_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:100]:
            try:
                data = json.loads(f.read_text(encoding="utf-8", errors="replace"))
                data["filename"] = f.name
                entries.append(data)
            except Exception:
                pass
    return {"entries": entries}


@app.delete("/api/output/history", dependencies=[Depends(verify_token)])
async def clear_output_history():
    """
    Clears the output_history/ audit log.
    Does NOT touch chat/ (LLM context history) or system logs.
    """
    hist_dir = Path("output_history")
    deleted = 0
    if hist_dir.exists():
        for f in hist_dir.glob("*.json"):
            try:
                f.unlink()
                deleted += 1
            except Exception:
                pass
    return {"success": True, "deleted": deleted}


@app.get("/api/output/log", dependencies=[Depends(verify_token)])
async def output_log():
    """
    Returns the output log of past LLM generations.
    Each entry: timestamp, user_message, raw_output, final_output, marker_detected.
    Newest first, capped at 50 entries.
    """
    log_path = Path("global_flags/output_log.jsonl")
    entries = []
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except Exception:
                    pass
    return {"entries": list(reversed(entries))[:50]}


@app.get("/api/output/raw_stream", dependencies=[Depends(verify_token)])
async def output_raw_stream():
    """
    SSE: streams the FULL raw LLM output in real-time, including pre-affordance
    internal content.  Used by the Output Viewer to show everything the model
    generates, not just the final user-visible part.

    Events:  data: {"text": "<chunk>"}   — new raw tokens
             data: {"done": true}        — generation complete
    """
    raw_output = Path("jobs/job_raw_output.txt")
    llm_status = Path("global_flags/llm_status.txt")

    async def generate():
        char_pos = 0
        start    = time.time()
        timeout  = 300

        # Wait up to 30s for the output file to appear
        while not raw_output.exists() and time.time() - start < 30:
            await asyncio.sleep(0.2)

        while time.time() - start < timeout:
            if raw_output.exists():
                try:
                    content = raw_output.read_text(encoding="utf-8", errors="replace")
                    if len(content) > char_pos:
                        chunk = content[char_pos:]
                        char_pos += len(chunk)
                        yield f"data: {json.dumps({'text': chunk})}\n\n"
                except Exception:
                    pass

            try:
                status = llm_status.read_text().strip()
            except Exception:
                status = "idle"

            if status in ("idle", "stopped", "error") and char_pos > 0:
                # Drain any final bytes, then signal done
                if raw_output.exists():
                    try:
                        content = raw_output.read_text(encoding="utf-8", errors="replace")
                        if len(content) > char_pos:
                            yield f"data: {json.dumps({'text': content[char_pos:]})}\n\n"
                    except Exception:
                        pass
                yield f"data: {json.dumps({'done': True})}\n\n"
                break

            await asyncio.sleep(0.1)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- Model & Config Endpoints ---

async def _download_model_task(url: str, filename: str, expected_sha256: Optional[str], max_bytes: int):
    models_dir = Path("models")
    staging_dir = models_dir / "_staging"
    models_dir.mkdir(exist_ok=True)
    staging_dir.mkdir(exist_ok=True)

    part_file = staging_dir / f"{filename}.part"
    final_staging = staging_dir / filename
    dest_file = models_dir / filename

    try:
        active_downloads[filename]["status"] = "downloading"

        # Proxy support: honour standard environment variables
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") \
             or os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") \
             or os.environ.get("ALL_PROXY") or os.environ.get("all_proxy")

        # Only use custom DNS resolver when not going through a proxy
        if proxy:
            connector = aiohttp.TCPConnector()
        else:
            resolver = aiohttp.AsyncResolver(nameservers=["8.8.8.8", "1.1.1.1"])
            connector = aiohttp.TCPConnector(resolver=resolver)

        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(url, proxy=proxy) as resp:
                if resp.status != 200:
                    raise Exception(f"HTTP {resp.status}")

                content_len = resp.headers.get("Content-Length")
                if max_bytes > 0 and content_len and int(content_len) > max_bytes:
                     raise Exception("File too large")

                downloaded = 0
                sha256 = hashlib.sha256()
                total_size = int(content_len) if content_len else 0
                last_log_time = time.time()

                # Update total
                active_downloads[filename]["total"] = total_size

                async with aiofiles.open(part_file, "wb") as f:
                    async for chunk in resp.content.iter_chunked(1024 * 1024): # 1MB chunks
                        downloaded += len(chunk)
                        if max_bytes > 0 and downloaded > max_bytes:
                             raise Exception("File limit exceeded")

                        sha256.update(chunk)
                        await f.write(chunk)

                        # Update status
                        active_downloads[filename]["bytes"] = downloaded
                        if total_size > 0:
                            active_downloads[filename]["pct"] = int(downloaded / total_size * 100)

                        if time.time() - last_log_time > 2:
                            pct = ""
                            if total_size > 0:
                                pct = f" ({int(downloaded/total_size*100)}%)"
                            await logger.emit("Info", f"Downloading {filename}: {downloaded // (1024*1024)}MB{pct}", "ModelManager")
                            last_log_time = time.time()

        # Hash Verification
        active_downloads[filename]["status"] = "verifying"
        computed_hash = sha256.hexdigest()
        if expected_sha256 and computed_hash.lower() != expected_sha256.lower():
            if part_file.exists(): part_file.unlink()
            raise Exception(f"Hash mismatch. Computed: {computed_hash}")

        # Atomic Move
        shutil.move(str(part_file), str(final_staging))
        shutil.move(str(final_staging), str(dest_file))

        await logger.emit("Success", f"Downloaded model: {filename} ({downloaded} bytes)", "ModelManager")

        # Mark done
        active_downloads[filename]["status"] = "completed"
        active_downloads[filename]["bytes"] = downloaded

    except Exception as e:
        if part_file.exists():
            try:
                part_file.unlink()
            except: pass
        print(f"Download error: {e}")
        await logger.emit("Error", f"Download failed: {str(e)}", "ModelManager")
        active_downloads[filename]["status"] = "error"
        active_downloads[filename]["error"] = str(e)

@app.post("/api/models/fetch", dependencies=[Depends(verify_token)])
async def fetch_model(request: ModelFetchRequest, background_tasks: BackgroundTasks):
    url = request.url

    # 1. Determine Filename
    filename = request.filename
    if not filename:
        path = url.split("?")[0]
        filename = path.split("/")[-1]

    # Sanitize
    filename = os.path.basename(filename)
    if not filename or filename in ['.', '..']:
        raise HTTPException(status_code=400, detail="Invalid filename")

    if filename in active_downloads and active_downloads[filename]["status"] in ["pending", "downloading", "verifying"]:
        raise HTTPException(status_code=400, detail="Download already in progress")

    # 2. Size Limit
    max_bytes = int(os.environ.get("LYRN_MAX_MODEL_BYTES", 0))

    # Initialize tracking
    active_downloads[filename] = {
        "status": "pending",
        "bytes": 0,
        "total": 0,
        "pct": 0,
        "error": None,
        "timestamp": time.time()
    }

    # Start Background Task
    background_tasks.add_task(_download_model_task, url, filename, request.expected_sha256, max_bytes)

    await logger.emit("Info", f"Started download for {filename}", "ModelManager")
    return {"ok": True, "message": "Download started", "filename": filename}

@app.get("/api/models/downloads", dependencies=[Depends(verify_token)])
async def get_active_downloads():
    current_time = time.time()
    to_remove = []
    for fname, data in active_downloads.items():
        if data["status"] in ["completed", "error"]:
            # Clean up old statuses after 10 minutes
            if current_time - data.get("timestamp", 0) > 600:
                to_remove.append(fname)

    for fname in to_remove:
        del active_downloads[fname]

    return active_downloads

@app.get("/api/models/list", dependencies=[Depends(verify_token)])
async def list_models():
    """Lists available models in the models/ directory."""
    models_dir = Path("models")
    if not models_dir.exists():
        return []

    models = []
    for f in models_dir.iterdir():
        if f.is_file() and f.name != "_staging" and not f.name.endswith(".part"):
             stat = f.stat()
             models.append({
                 "name": f.name,
                 "bytes": stat.st_size,
                 "modified": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat()
             })

    return sorted(models, key=lambda x: x['name'])

@app.get("/api/models/inspect", dependencies=[Depends(verify_token)])
async def inspect_model(name: str):
    models_dir = Path("models")
    f = models_dir / os.path.basename(name)

    if not f.exists() or not f.is_file():
        raise HTTPException(status_code=404, detail="Model not found")

    # Compute Hash
    # Synchronous for now as permitted, but let's try to be nice
    # Streaming hash
    loop = asyncio.get_running_loop()
    def compute_hash():
        sha256 = hashlib.sha256()
        with open(f, "rb") as stream:
             while chunk := stream.read(1024*1024):
                  sha256.update(chunk)
        return sha256.hexdigest()

    computed_hash = await loop.run_in_executor(None, compute_hash)

    stat = f.stat()
    return {
        "name": f.name,
        "bytes": stat.st_size,
        "modified": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "sha256": computed_hash
    }

@app.delete("/api/models/delete", dependencies=[Depends(verify_token)])
async def delete_model(name: str):
    models_dir = Path("models")
    filename = os.path.basename(name)

    if filename == "_staging":
         raise HTTPException(status_code=400, detail="Cannot delete staging dir")

    f = models_dir / filename
    if not f.exists():
        raise HTTPException(status_code=404, detail="Model not found")

    try:
        if f.is_dir():
             # Should not happen given list filter but safety first
             raise HTTPException(status_code=400, detail="Cannot delete directories")
        f.unlink()
        await logger.emit("Info", f"Deleted model: {filename}", "ModelManager")
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/config/presets", dependencies=[Depends(verify_token)])
async def get_presets():
    """Gets all model presets."""
    if not settings_manager.settings:
        settings_manager.load_or_detect_first_boot()

    return settings_manager.settings.get("model_presets", {})

@app.post("/api/config/presets", dependencies=[Depends(verify_token)])
async def save_preset(preset: PresetModel):
    """Saves a model preset."""
    if not settings_manager.settings:
        settings_manager.load_or_detect_first_boot()

    if "model_presets" not in settings_manager.settings:
        settings_manager.settings["model_presets"] = {}

    settings_manager.settings["model_presets"][preset.preset_id] = preset.config
    settings_manager.save_settings()
    return {"success": True, "message": f"Preset {preset.preset_id} saved."}

@app.post("/api/config/active", dependencies=[Depends(verify_token)])
async def set_active_config(config: ActiveConfigModel):
    """Sets the active model configuration."""
    if not settings_manager.settings:
        settings_manager.load_or_detect_first_boot()

    settings_manager.settings["active"] = config.config
    settings_manager.save_settings()
    return {"success": True, "message": "Active configuration updated."}

@app.get("/api/config/active", dependencies=[Depends(verify_token)])
async def get_active_config():
    """Gets the active model configuration."""
    if not settings_manager.settings:
        settings_manager.load_or_detect_first_boot()

    return settings_manager.settings.get("active", {})

@app.get("/api/config", dependencies=[Depends(verify_token)])
async def get_config():
    """Gets the full system configuration."""
    if not settings_manager.settings:
        settings_manager.load_or_detect_first_boot()
    return {
        "settings": settings_manager.settings,
        "ui_settings": settings_manager.ui_settings
    }

@app.post("/api/config", dependencies=[Depends(verify_token)])
async def save_config(data: Dict[str, Any]):
    """Saves the full system configuration."""
    if "settings" in data:
        settings_manager.settings = data["settings"]
    if "ui_settings" in data:
        settings_manager.ui_settings = data["ui_settings"]

    settings_manager.save_settings()
    return {"success": True, "message": "Settings saved."}

# --- Worker Control Endpoints ---

@app.get("/api/system/worker_status", dependencies=[Depends(verify_token)])
async def get_worker_status():
    return worker_controller.get_status()

@app.post("/api/system/start_worker", dependencies=[Depends(verify_token)])
async def start_worker():
    return worker_controller.start_worker()

@app.post("/api/system/stop_worker", dependencies=[Depends(verify_token)])
async def stop_worker():
    return worker_controller.stop_worker()

# --- DSManager Endpoints ---

@app.get("/api/dsmanager/{category}", dependencies=[Depends(verify_token)])
async def get_dynamic_snapshots(category: str):
    if category not in ["jobs", "projects"]:
        raise HTTPException(status_code=400, detail="Invalid category")
    return ds_manager.list_snapshots(category)

@app.post("/api/dsmanager/{category}", dependencies=[Depends(verify_token)])
async def save_dynamic_snapshot(category: str, data: DSModel):
    if category not in ["jobs", "projects"]:
        raise HTTPException(status_code=400, detail="Invalid category")
    success = ds_manager.save_snapshot(category, data.name, data.content)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save snapshot")
    ds_manager.set_snapshot_active(category, data.name, data.active)
    return {"success": True}

@app.put("/api/dsmanager/{category}/{name}/active", dependencies=[Depends(verify_token)])
async def set_dynamic_snapshot_active(category: str, name: str, data: DSActiveModel):
    if category not in ["jobs", "projects"]:
        raise HTTPException(status_code=400, detail="Invalid category")
    success = ds_manager.set_snapshot_active(category, name, data.active)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update active state")
    return {"success": True}

@app.delete("/api/dsmanager/{category}/{name}", dependencies=[Depends(verify_token)])
async def delete_dynamic_snapshot(category: str, name: str):
    if category not in ["jobs", "projects"]:
        raise HTTPException(status_code=400, detail="Invalid category")
    success = ds_manager.delete_snapshot(category, name)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete snapshot")
    return {"success": True}

# --- Automation Endpoints ---

@app.get("/api/automation/jobs", dependencies=[Depends(verify_token)])
async def get_jobs():
    return automation_controller.job_definitions

@app.post("/api/automation/jobs", dependencies=[Depends(verify_token)])
async def save_job(job: JobDefinitionModel):
    automation_controller.save_job_definition(job.name, job.instructions, job.trigger, job.scripts)

    # Save the snapshot to DSManager as well if it has content
    if job.instructions:
        ds_manager.save_snapshot("jobs", job.name, job.instructions)
    return {"success": True}

@app.delete("/api/automation/jobs/{job_name}", dependencies=[Depends(verify_token)])
async def delete_job(job_name: str):
    automation_controller.delete_job_definition(job_name)
    return {"success": True}

@app.get("/api/automation/scripts", dependencies=[Depends(verify_token)])
async def get_scripts():
    return automation_controller.get_available_scripts()

@app.get("/api/automation/history", dependencies=[Depends(verify_token)])
async def get_job_history():
    return automation_controller.get_job_history()

@app.get("/api/automation/job_content", dependencies=[Depends(verify_token)])
async def get_job_content(path: str):
    """Reads the content of a job file."""
    try:
        # Security check: Ensure path is within jobs/ folder
        requested_path = Path(path).resolve()
        jobs_dir = Path("jobs").resolve()

        if not str(requested_path).startswith(str(jobs_dir)):
            raise HTTPException(status_code=403, detail="Access denied: Invalid file path.")

        if not requested_path.exists():
            raise HTTPException(status_code=404, detail="File not found.")

        return {"content": requested_path.read_text(encoding="utf-8")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/automation/history", dependencies=[Depends(verify_token)])
async def clear_job_history():
    automation_controller.clear_job_history()
    return {"success": True}

@app.get("/api/automation/schedule", dependencies=[Depends(verify_token)])
async def get_schedule():
    return automation_controller.get_queue()

@app.post("/api/automation/schedule", dependencies=[Depends(verify_token)])
async def add_schedule(item: JobScheduleModel):
    automation_controller.add_job(
        name=item.job_name,
        priority=item.priority,
        when=item.scheduled_datetime_iso,
        args=item.args,
        job_id=item.id
    )
    return {"success": True}

@app.delete("/api/automation/schedule/{job_id}", dependencies=[Depends(verify_token)])
async def delete_schedule(job_id: str):
    automation_controller.remove_job_from_queue(job_id)
    return {"success": True}

@app.get("/api/automation/cycles", dependencies=[Depends(verify_token)])
async def get_cycles():
    return automation_controller.get_cycles()

@app.post("/api/automation/cycles", dependencies=[Depends(verify_token)])
async def save_cycle(cycle: CycleModel):
    automation_controller.save_cycle(cycle.name, cycle.triggers)
    return {"success": True}

@app.delete("/api/automation/cycles/{cycle_name}", dependencies=[Depends(verify_token)])
async def delete_cycle(cycle_name: str):
    automation_controller.delete_cycle(cycle_name)
    return {"success": True}

# --- Snapshot Builder Endpoints ---

@app.get("/api/snapshot", dependencies=[Depends(verify_token)])
async def get_snapshot():
    """Reads components and their content."""
    try:
        base_dir = Path("build_prompt")
        comp_path = base_dir / "components.json"

        if not comp_path.exists():
            return [] # Return empty list if no file

        with open(comp_path, 'r', encoding='utf-8') as f:
            components = json.load(f)

        # Enhance components with content
        for comp in components:
            name = comp.get("name")
            if name == "RWI":
                continue

            # Look for content in subdir
            comp_dir = base_dir / name
            config_path = comp_dir / "config.json"

            content_file = "content.txt"

            if config_path.exists():
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        c = json.load(f)
                        content_file = c.get("content_file", "content.txt")
                except: pass

            content_path = comp_dir / content_file
            if content_path.exists():
                try:
                    comp["content"] = content_path.read_text(encoding='utf-8')
                except:
                    comp["content"] = ""
            else:
                 comp["content"] = ""

        return components
    except Exception as e:
        print(f"Error getting snapshot: {e}")
        return []

@app.post("/api/snapshot", dependencies=[Depends(verify_token)])
async def save_snapshot(components: List[Dict[str, Any]]):
    """Saves components list and updates content files. (Legacy/Quick Save)"""
    try:
        await _save_components_to_build_prompt(components)
        return {"success": True}
    except Exception as e:
        print(f"Error saving snapshot: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/snapshot/rebuild", dependencies=[Depends(verify_token)])
async def rebuild_snapshot():
    """Triggers a snapshot rebuild in the worker."""
    try:
        with open("rebuild_trigger.txt", "w", encoding='utf-8') as f:
            f.write("rebuild")
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Serve dashboard at root
@app.get("/")
async def read_root():
    return FileResponse('LYRN_v5/dashboard.html')

# Serve Static Files
app.mount("/", StaticFiles(directory="LYRN_v5", html=True), name="static")

if __name__ == "__main__":
    port = 8000
    try:
        if os.path.exists("port.txt"):
            with open("port.txt", "r") as f:
                val = f.read().strip()
                if val.isdigit():
                    port = int(val)
    except Exception as e:
        print(f"Failed to load port.txt: {e}")

    print(f"Starting server on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)
