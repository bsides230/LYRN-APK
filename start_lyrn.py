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

import platform
import struct
if platform.system() != "Windows":
    import pty
    import termios
    import fcntl

from fastapi import WebSocket, WebSocketDisconnect


from settings_manager import SettingsManager
from automation_controller import AutomationController
from chat_manager import ChatManager

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
def trigger_chat_generation(message: str, folder: str = "chat"):
    """Creates a chat file and triggers the worker."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{folder}/{folder}_{timestamp}.txt"
    filepath = os.path.abspath(filename)

    # Ensure directory
    os.makedirs(folder, exist_ok=True)

    # Write User Message
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
                if scripts_ok:
                    if job.prompt:
                        # Use "jobs" folder for automated tasks
                        filepath, _ = trigger_chat_generation(job.prompt, folder="jobs")

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

            await asyncio.sleep(5) # Check every 5 seconds
        except Exception as e:
            print(f"[Scheduler] Error in loop: {e}")
            await asyncio.sleep(5)

# --- Worker Controller ---
class ProxyController:
    """Manages the anthropic proxy process."""
    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self.proxy_script = "anthropic_proxy.py"
        self.port = 8001

    def get_status(self):
        with self._lock:
            running = self.process is not None and self.process.poll() is None

            # Determine port from port.txt + 1
            try:
                if os.path.exists("port.txt"):
                    with open("port.txt", "r") as f:
                        val = f.read().strip()
                        if val.isdigit():
                            self.port = int(val) + 1
            except: pass

            return {
                "running": running,
                "pid": self.process.pid if running else None,
                "port": self.port
            }

    def start_proxy(self):
        with self._lock:
            if self.process is not None and self.process.poll() is None:
                return {"success": False, "message": "Proxy already running.", "port": self.port}

            try:
                # Start the proxy process
                self.process = subprocess.Popen(
                    [sys.executable, "-u", self.proxy_script],
                    cwd=os.getcwd(),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )

                # Start threads to forward output to logger
                threading.Thread(target=self._monitor_output, args=(self.process.stdout, "ProxyOut"), daemon=True).start()
                threading.Thread(target=self._monitor_output, args=(self.process.stderr, "ProxyErr"), daemon=True).start()

                # Determine port
                try:
                    if os.path.exists("port.txt"):
                        with open("port.txt", "r") as f:
                            val = f.read().strip()
                            if val.isdigit():
                                self.port = int(val) + 1
                except: pass

                return {"success": True, "message": "Proxy started.", "port": self.port}
            except Exception as e:
                return {"success": False, "message": f"Failed to start proxy: {e}"}

    def stop_proxy(self):
        with self._lock:
            if self.process is None or self.process.poll() is not None:
                return {"success": False, "message": "Proxy not running."}

            try:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()

                self.process = None
                return {"success": True, "message": "Proxy stopped."}
            except Exception as e:
                return {"success": False, "message": f"Error stopping proxy: {e}"}

    def _monitor_output(self, stream, source):
        """Reads output from the subprocess and logs it."""
        try:
            for line in iter(stream.readline, ''):
                if line:
                    clean_line = line.strip()
                    if main_loop and clean_line:
                        asyncio.run_coroutine_threadsafe(logger.emit("Info", clean_line, source), main_loop)
                    elif clean_line:
                        print(f"[{source}] {clean_line}")
        except Exception:
            pass
        finally:
            stream.close()

proxy_controller = ProxyController()


# =====================================================================
# Claude Code Orchestrator
# ---------------------------------------------------------------------
# Self-contained, additive orchestration layer for the Claude Code GUI
# module. Stores per-run metadata, transcripts, and git snapshots under
# claude_runs/. Does NOT touch any other LYRN subsystem.
# =====================================================================

class ClaudeRunManager:
    """Tracks Claude Code runs: lifecycle, transcript, git diff snapshot."""

    STORE_DIR = Path("claude_runs")
    VALID_MODES = ("oneshot", "inspect", "patch")

    def __init__(self):
        self.STORE_DIR.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._index_path = self.STORE_DIR / "index.json"
        self._procs: Dict[str, subprocess.Popen] = {}
        self._log_handles: Dict[str, Any] = {}
        self.runs: Dict[str, Dict[str, Any]] = self._load_index()
        # Any runs left in 'running' state from a prior server process are
        # orphaned -- the subprocess is gone. Mark them so the UI is honest.
        for run in self.runs.values():
            if run.get("status") == "running":
                run["status"] = "interrupted"
                run["ended_at"] = run.get("ended_at") or time.time()
        self._save_index()

    # ---------- Claude CLI resolution ----------
    def _resolve_claude_binary(self) -> Optional[str]:
        """Resolve a concrete claude executable path for non-interactive
        backend execution. Avoids relying on shell init files."""
        env = os.environ
        explicit = (env.get("LYRN_CLAUDE_BIN") or env.get("CLAUDE_BIN") or "").strip()
        candidates: List[Path] = []
        if explicit:
            candidates.append(Path(explicit).expanduser())

        via_path = shutil.which("claude")
        if via_path:
            candidates.append(Path(via_path))

        home = Path(env.get("HOME", "~")).expanduser()
        candidates += [
            home / ".local/bin/claude",
            home / ".npm-global/bin/claude",
            Path("/usr/local/bin/claude"),
            Path("/opt/homebrew/bin/claude"),
        ]

        for c in candidates:
            try:
                p = c.expanduser().resolve()
                if p.exists() and os.access(p, os.X_OK):
                    return str(p)
            except Exception:
                continue
        return None

    def _claude_env(self) -> Dict[str, str]:
        env = os.environ.copy()
        claude_bin = self._resolve_claude_binary()
        if claude_bin:
            env["LYRN_CLAUDE_BIN"] = claude_bin
            bin_dir = str(Path(claude_bin).parent)
            path_val = env.get("PATH", "")
            if bin_dir not in path_val.split(os.pathsep):
                env["PATH"] = bin_dir + (os.pathsep + path_val if path_val else "")

        # Set Anthropic Proxy Environment Variables
        # Attempt to read port from port.txt + 1
        default_port = 8001
        try:
            if os.path.exists("port.txt"):
                with open("port.txt", "r") as f:
                    val = f.read().strip()
                    if val.isdigit():
                        default_port = int(val) + 1
        except:
            pass

        host = os.environ.get("LCC_HOST", "127.0.0.1")
        port = os.environ.get("LCC_PORT", str(default_port))
        base_url = f"http://{host}:{port}"

        env["ANTHROPIC_BASE_URL"] = base_url
        env["ANTHROPIC_AUTH_TOKEN"] = "lyrn"
        env["ANTHROPIC_API_KEY"] = ""
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"

        return env

    # ---------- Persistence ----------
    def _load_index(self) -> Dict[str, Dict[str, Any]]:
        if self._index_path.exists():
            try:
                return json.loads(self._index_path.read_text())
            except Exception:
                return {}
        return {}

    def _save_index(self):
        try:
            self._index_path.write_text(json.dumps(self.runs, indent=2))
        except Exception as e:
            print(f"[ClaudeRun] Failed to save index: {e}")

    # ---------- Git helpers (best-effort, no-op if not a git repo) ----------
    def _git(self, cwd: str, *args: str, capture: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args], cwd=cwd, capture_output=capture, text=True, timeout=30
        )

    def _is_git_repo(self, cwd: str) -> bool:
        try:
            r = self._git(cwd, "rev-parse", "--is-inside-work-tree")
            return r.returncode == 0 and r.stdout.strip() == "true"
        except Exception:
            return False

    def _snapshot_baseline(self, cwd: str) -> Optional[str]:
        """Use 'git stash create' to capture the working tree as a commit
        object without altering anything. Returns the SHA, or None."""
        if not self._is_git_repo(cwd):
            return None
        try:
            # Make sure untracked are included by adding them to a temp index.
            # Simpler: stash create only captures tracked. We accept that.
            r = self._git(cwd, "stash", "create")
            sha = r.stdout.strip()
            return sha or self._git(cwd, "rev-parse", "HEAD").stdout.strip()
        except Exception as e:
            print(f"[ClaudeRun] snapshot error: {e}")
            return None

    def _compute_diff(self, cwd: str, baseline_sha: str) -> Dict[str, Any]:
        """Diff working tree against the baseline SHA."""
        try:
            raw = self._git(cwd, "diff", "--no-color", baseline_sha).stdout
            stat = self._git(cwd, "diff", "--numstat", baseline_sha).stdout
            files = []
            for line in stat.strip().splitlines():
                parts = line.split("\t")
                if len(parts) == 3:
                    add, delete, path = parts
                    files.append({
                        "path": path,
                        "additions": int(add) if add.isdigit() else 0,
                        "deletions": int(delete) if delete.isdigit() else 0,
                    })
            return {"raw": raw, "files": files}
        except Exception as e:
            return {"raw": "", "files": [], "error": str(e)}

    def _revert_to_baseline(self, cwd: str, baseline_sha: str) -> bool:
        """Restore working tree to the baseline snapshot (destructive)."""
        try:
            # Hard reset tracked files to the snapshot tree.
            r = self._git(cwd, "checkout", baseline_sha, "--", ".")
            return r.returncode == 0
        except Exception as e:
            print(f"[ClaudeRun] revert error: {e}")
            return False

    # ---------- Validation / argv (single source of truth) ----------
    def resolve_cwd(self, cwd: Optional[str]) -> Dict[str, Any]:
        """Validate a user-supplied cwd. Returns a result dict with either
        ``path`` (resolved) or ``error`` (human-readable)."""
        raw = (cwd or "").strip()
        if not raw:
            return {"ok": False, "error": "Working directory is required."}
        try:
            p = Path(raw).expanduser()
            if not p.exists():
                return {"ok": False, "error": f"Path does not exist: {raw}"}
            if not p.is_dir():
                return {"ok": False, "error": f"Not a directory: {raw}"}
            resolved = str(p.resolve())
        except Exception as e:
            return {"ok": False, "error": f"Invalid path: {e}"}
        return {
            "ok": True,
            "path": resolved,
            "is_git_repo": self._is_git_repo(resolved),
        }

    def build_argv(self, payload: Dict[str, Any]) -> List[str]:
        """Backend is the source of truth for the actual command. The
        frontend preview is informational only."""
        mode = payload.get("mode") or "oneshot"
        argv: List[str] = ["claude"]
        if mode == "oneshot":
            argv.append("--print")
        elif mode == "inspect":
            argv.append("--read-only")
        elif mode == "patch":
            argv.append("--patch-only")

        if payload.get("model"):
            argv += ["--model", str(payload["model"])]
        if payload.get("effort"):
            argv += ["--effort", str(payload["effort"])]
        if payload.get("system_prompt"):
            argv += ["--system-prompt", str(payload["system_prompt"])]
        if payload.get("auto"):
            argv.append("--enable-auto-mode")
        if payload.get("perms"):
            argv.append("--dangerously-skip-permissions")

        task = (payload.get("task") or "").strip()
        if task:
            argv.append(task)
        return argv

    def preview(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        argv = self.build_argv(payload)
        cwd_check = self.resolve_cwd(payload.get("cwd"))
        return {
            "argv": argv,
            "cwd": cwd_check,
            "claude_bin": self._resolve_claude_binary(),
        }

    # ---------- Auth ----------
    def auth_status(self) -> Dict[str, Any]:
        claude_bin = self._resolve_claude_binary()
        if not claude_bin:
            return {
                "available": False,
                "authenticated": False,
                "raw": "claude CLI not installed or not visible in backend PATH",
                "claude_bin": None,
            }
        try:
            r = subprocess.run(
                [claude_bin, "auth", "status"],
                capture_output=True, text=True, timeout=10,
                env=self._claude_env(),
            )
            output = (r.stdout + r.stderr).strip()
            low = output.lower()
            authed = r.returncode == 0 and any(
                marker in low for marker in (
                    "logged in", "authenticated", "account:", "you are signed in",
                )
            )
            return {
                "available": True,
                "authenticated": authed,
                "raw": output,
                "claude_bin": claude_bin,
            }
        except FileNotFoundError:
            return {
                "available": False,
                "authenticated": False,
                "raw": "claude CLI not installed",
                "claude_bin": claude_bin,
            }
        except subprocess.TimeoutExpired:
            return {
                "available": True,
                "authenticated": False,
                "raw": "auth status timed out",
                "claude_bin": claude_bin,
            }
        except Exception as e:
            return {
                "available": False,
                "authenticated": False,
                "raw": str(e),
                "claude_bin": claude_bin,
            }

    # ---------- Run lifecycle ----------
    def list_runs(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._refresh_statuses()
            return sorted(
                [self._summary(r) for r in self.runs.values()],
                key=lambda r: r.get("started_at", 0),
                reverse=True,
            )

    def _summary(self, run: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": run["id"],
            "label": run.get("label", ""),
            "mode": run.get("mode", ""),
            "cwd": run.get("cwd", ""),
            "status": run.get("status", "unknown"),
            "started_at": run.get("started_at", 0),
            "ended_at": run.get("ended_at"),
            "exit_code": run.get("exit_code"),
            "approved": run.get("approved"),
            "has_diff": bool(run.get("baseline_sha")),
        }

    def _refresh_statuses(self):
        for run_id, proc in list(self._procs.items()):
            if proc.poll() is not None:
                run = self.runs.get(run_id)
                if run and run.get("status") == "running":
                    run["status"] = "completed" if proc.returncode == 0 else "failed"
                    run["exit_code"] = proc.returncode
                    run["ended_at"] = time.time()
                    self._save_index()
                self._procs.pop(run_id, None)
                fh = self._log_handles.pop(run_id, None)
                if fh is not None:
                    try: fh.close()
                    except Exception: pass

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._refresh_statuses()
            run = self.runs.get(run_id)
            if not run:
                return None
            return dict(run)

    def get_transcript(self, run_id: str) -> str:
        run = self.runs.get(run_id)
        if not run:
            return ""
        path = Path(run.get("transcript_path", ""))
        if path.exists():
            try:
                return path.read_text(errors="replace")
            except Exception:
                return ""
        return ""

    def get_diff(self, run_id: str) -> Dict[str, Any]:
        run = self.runs.get(run_id)
        if not run or not run.get("baseline_sha"):
            return {"raw": "", "files": [], "error": "no baseline snapshot"}
        return self._compute_diff(run["cwd"], run["baseline_sha"])

    def approve(self, run_id: str) -> Dict[str, Any]:
        with self._lock:
            run = self.runs.get(run_id)
            if not run:
                return {"success": False, "message": "run not found"}
            run["approved"] = True
            self._save_index()
            return {"success": True}

    def reject(self, run_id: str) -> Dict[str, Any]:
        with self._lock:
            run = self.runs.get(run_id)
            if not run:
                return {"success": False, "message": "run not found"}
            sha = run.get("baseline_sha")
            if not sha:
                return {"success": False, "message": "no baseline to revert to"}
            ok = self._revert_to_baseline(run["cwd"], sha)
            run["approved"] = False if ok else None
            run["reverted"] = ok
            self._save_index()
            return {"success": ok}

    def delete_run(self, run_id: str) -> Dict[str, Any]:
        with self._lock:
            self._refresh_statuses()
            existing = self.runs.get(run_id)
            if not existing:
                return {"success": False, "message": "run not found"}
            if existing.get("status") == "running":
                return {"success": False, "message": "cannot delete a running run"}
            self.runs.pop(run_id, None)
            try:
                d = self.STORE_DIR / run_id
                if d.exists():
                    shutil.rmtree(d)
            except Exception:
                pass
            self._save_index()
            return {"success": True}

    def start_run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        mode = payload.get("mode") or "oneshot"
        if mode not in self.VALID_MODES:
            return {"success": False, "message": f"unsupported mode: {mode}"}

        cwd_check = self.resolve_cwd(payload.get("cwd"))
        if not cwd_check["ok"]:
            return {"success": False, "message": cwd_check["error"]}
        cwd_resolved = cwd_check["path"]

        task = (payload.get("task") or "").strip()
        if mode == "oneshot" and not task:
            return {"success": False, "message": "Task is required for one-shot runs."}

        argv = self.build_argv({**payload, "mode": mode, "task": task})
        claude_bin = self._resolve_claude_binary()
        if not claude_bin:
            return {
                "success": False,
                "message": (
                    "claude CLI not found. Set LYRN_CLAUDE_BIN/CLAUDE_BIN or "
                    f"ensure PATH includes claude. PATH={os.environ.get('PATH','')}"
                ),
            }
        argv[0] = claude_bin

        run_id = "run_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + os.urandom(2).hex()
        run_dir = self.STORE_DIR / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        transcript_path = run_dir / "transcript.log"

        baseline = self._snapshot_baseline(cwd_resolved)

        try:
            log_fh = open(transcript_path, "w", buffering=1)
            proc = subprocess.Popen(
                argv,
                cwd=cwd_resolved,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                text=True,
                env=self._claude_env(),
            )
        except FileNotFoundError:
            try: log_fh.close()
            except Exception: pass
            return {"success": False, "message": "claude CLI not found in backend runtime environment"}
        except Exception as e:
            try: log_fh.close()
            except Exception: pass
            return {"success": False, "message": f"failed to start: {e}"}

        run = {
            "id": run_id,
            "label": (payload.get("label") or "").strip(),
            "mode": mode,
            "cwd": cwd_resolved,
            "argv": argv,
            "task": task,
            "baseline_sha": baseline,
            "transcript_path": str(transcript_path),
            "status": "running",
            "started_at": time.time(),
            "ended_at": None,
            "exit_code": None,
            "approved": None,
            "reverted": False,
            "pid": proc.pid,
        }

        with self._lock:
            self.runs[run_id] = run
            self._procs[run_id] = proc
            self._log_handles[run_id] = log_fh
            self._save_index()

        return {"success": True, "run": self._summary(run), "argv": argv}


claude_run_manager = ClaudeRunManager()

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
                    text=True
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
class FileTreeSelectionModel(BaseModel):
    root_path: str
    root_name: str
    selections: Dict[str, Dict[str, Any]]

class FileTreeProfileModel(BaseModel):
    name: str
    root_path: str
    selections: Dict[str, Dict[str, Any]]

class InjectArtifactModel(BaseModel):
    artifact: str

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

# --- App Setup ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    global main_loop, LYRN_TOKEN
    main_loop = asyncio.get_running_loop()

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
        else:
            print("[System] Warning: No admin token found (admin_token.txt or LYRN_MODEL_TOKEN). Model management will be unavailable.")

    await logger.emit("Info", "Backend started.", "System")

    # Start Scheduler
    asyncio.create_task(scheduler_loop())

    yield

app = FastAPI(title="LYRN v6 Backend", lifespan=lifespan)

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
        "proxy": proxy_controller.get_status(),
        "llm_stats": llm_stats
    }

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

    try:
        filepath, filename = trigger_chat_generation(request.message)
    except Exception as e:
         raise HTTPException(status_code=500, detail=f"Failed to trigger chat: {e}")

    async def event_generator():
        # Yield the filename first for UI tracking
        yield json.dumps({"filename": filename}) + "\n"
        last_pos = 0
        retries = 0
        started = False

        while True:
            await asyncio.sleep(0.1)
            try:
                if not os.path.exists(filepath):
                    continue

                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()

                    if not started:
                        # Check for "model" marker. Worker writes "\n\nmodel\n"
                        # We look for "model" preceded by newlines or start of file
                        start_idx = -1
                        match = re.search(r'(?:^|\n)model\n', content)
                        if match:
                            start_idx = match.start()
                            # Start reading from end of match
                            last_pos = match.end()
                            started = True

                        if not started:
                            # Check for error
                            if "[Error:" in content:
                                print("[API] Detected error in chat file.")
                                yield json.dumps({"response": "Error in worker."}) + "\n"
                                return

                            retries += 1
                            # Load timeout from settings (default 1800s = 30 mins)
                            # Loop sleeps 0.1s, so 1800s = 18000 iterations
                            timeout_seconds = settings_manager.settings.get("worker_timeout_seconds", 1800)
                            max_retries = timeout_seconds * 10

                            if retries > max_retries:
                                print(f"[API] Timeout waiting for worker response ({timeout_seconds}s).")
                                yield json.dumps({"response": "Timeout waiting for worker."}) + "\n"
                                return
                            continue

                    if started:
                        # Read from last_pos
                        current_len = len(content)
                        if current_len > last_pos:
                            new_text = content[last_pos:]

                            # Stream what we have
                            yield json.dumps({"response": new_text}) + "\n"
                            last_pos = current_len

                        # Check if worker is done
                        status_info = worker_controller.get_status()
                        llm_status = status_info.get("llm_status", "unknown")

                        # If idle or error or stopped, and we have consumed everything (which we just did), we are done.
                        # Note: We rely on the fact that the worker writes content THEN sets status to idle.
                        if llm_status in ["idle", "error", "stopped"]:
                            return

            except Exception as e:
                print(f"Error in stream: {e}")
                yield json.dumps({"response": f"Error: {e}"}) + "\n"
                return

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")

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

        max_retries = 5
        base_delay = 2

        for attempt in range(max_retries):
            try:
                existing_bytes = 0
                if part_file.exists():
                    existing_bytes = part_file.stat().st_size

                headers = {}
                if existing_bytes > 0:
                    headers['Range'] = f'bytes={existing_bytes}-'

                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers) as resp:
                        if resp.status not in (200, 206):
                            raise ValueError(f"HTTP {resp.status}")

                        is_partial = (resp.status == 206)
                        if not is_partial and existing_bytes > 0:
                            existing_bytes = 0 # Server didn't respect Range header
                            # In this case we have to truncate the part file
                            mode = "wb"
                        else:
                            mode = "ab" if is_partial else "wb"

                        content_len = resp.headers.get("Content-Length")
                        total_size = int(content_len) + existing_bytes if content_len else existing_bytes

                        if max_bytes > 0 and total_size > max_bytes:
                             raise ValueError("File too large")

                        downloaded = existing_bytes

                        # We need to compute hash of the whole file at the end
                        last_log_time = time.time()

                        # Update total
                        active_downloads[filename]["total"] = total_size

                        async with aiofiles.open(part_file, mode) as f:
                            async for chunk in resp.content.iter_chunked(1024 * 1024): # 1MB chunks
                                downloaded += len(chunk)
                                if max_bytes > 0 and downloaded > max_bytes:
                                     raise ValueError("File limit exceeded")

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

                # If successful, break the retry loop
                break
            except ValueError as e:
                # Fatal errors, no retry
                raise e
            except Exception as e:
                err_msg = str(e) or e.__class__.__name__
                if attempt < max_retries - 1:
                    await logger.emit("Warning", f"Download interrupted: {err_msg}. Retrying in {base_delay}s... (Attempt {attempt+1}/{max_retries})", "ModelManager")
                    await asyncio.sleep(base_delay)
                    base_delay *= 2
                else:
                    raise e

        # Hash Verification
        active_downloads[filename]["status"] = "verifying"

        # Compute hash from the full downloaded file
        sha256 = hashlib.sha256()
        async with aiofiles.open(part_file, "rb") as f:
            while chunk := await f.read(1024 * 1024):
                sha256.update(chunk)

        computed_hash = sha256.hexdigest()
        if expected_sha256 and computed_hash.lower() != expected_sha256.lower():
            if part_file.exists(): part_file.unlink()
            raise ValueError(f"Hash mismatch. Computed: {computed_hash}")

        # Atomic Move
        shutil.move(str(part_file), str(final_staging))
        shutil.move(str(final_staging), str(dest_file))

        await logger.emit("Success", f"Downloaded model: {filename} ({downloaded} bytes)", "ModelManager")

        # Mark done
        active_downloads[filename]["status"] = "completed"
        active_downloads[filename]["bytes"] = downloaded

    except Exception as e:
        err_msg = str(e) or e.__class__.__name__
        print(f"Download error: {err_msg}")
        await logger.emit("Error", f"Download failed: {err_msg}", "ModelManager")
        active_downloads[filename]["status"] = "error"
        active_downloads[filename]["error"] = err_msg

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

@app.post("/api/system/start_claude_proxy", dependencies=[Depends(verify_token)])
async def start_claude_proxy():
    return proxy_controller.start_proxy()

@app.post("/api/system/stop_claude_proxy", dependencies=[Depends(verify_token)])
async def stop_claude_proxy():
    return proxy_controller.stop_proxy()

@app.get("/api/system/proxy_status", dependencies=[Depends(verify_token)])
async def get_proxy_status():
    return proxy_controller.get_status()

# --- Claude Code Orchestrator Endpoints ---

@app.get("/api/claude/auth", dependencies=[Depends(verify_token)])
async def claude_auth():
    return claude_run_manager.auth_status()

@app.post("/api/claude/validate_cwd", dependencies=[Depends(verify_token)])
async def claude_validate_cwd(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    return claude_run_manager.resolve_cwd((body or {}).get("cwd"))

@app.post("/api/claude/preview", dependencies=[Depends(verify_token)])
async def claude_preview(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    return claude_run_manager.preview(body or {})

@app.get("/api/claude/runs", dependencies=[Depends(verify_token)])
async def claude_list_runs():
    return {"runs": claude_run_manager.list_runs()}

@app.post("/api/claude/runs", dependencies=[Depends(verify_token)])
async def claude_start_run(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    return claude_run_manager.start_run(body or {})

@app.get("/api/claude/runs/{run_id}", dependencies=[Depends(verify_token)])
async def claude_get_run(run_id: str):
    run = claude_run_manager.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    return run

@app.get("/api/claude/runs/{run_id}/transcript", dependencies=[Depends(verify_token)])
async def claude_get_transcript(run_id: str):
    run = claude_run_manager.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    text = claude_run_manager.get_transcript(run_id)
    return {"run_id": run_id, "transcript": text}

@app.get("/api/claude/runs/{run_id}/transcript/download", dependencies=[Depends(verify_token)])
async def claude_download_transcript(run_id: str):
    run = claude_run_manager.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    path = run.get("transcript_path", "")
    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail="transcript file missing")
    return FileResponse(path, filename=f"{run_id}.log", media_type="text/plain")

@app.get("/api/claude/runs/{run_id}/diff", dependencies=[Depends(verify_token)])
async def claude_get_diff(run_id: str):
    run = claude_run_manager.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    return claude_run_manager.get_diff(run_id)

@app.post("/api/claude/runs/{run_id}/approve", dependencies=[Depends(verify_token)])
async def claude_approve(run_id: str):
    return claude_run_manager.approve(run_id)

@app.post("/api/claude/runs/{run_id}/reject", dependencies=[Depends(verify_token)])
async def claude_reject(run_id: str):
    return claude_run_manager.reject(run_id)

@app.delete("/api/claude/runs/{run_id}", dependencies=[Depends(verify_token)])
async def claude_delete_run(run_id: str):
    return claude_run_manager.delete_run(run_id)

# --- Automation Endpoints ---

@app.get("/api/automation/jobs", dependencies=[Depends(verify_token)])
async def get_jobs():
    return automation_controller.job_definitions

@app.post("/api/automation/jobs", dependencies=[Depends(verify_token)])
async def save_job(job: JobDefinitionModel):
    automation_controller.save_job_definition(job.name, job.instructions, job.trigger, job.scripts)
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

# --- File Tree Viewer Endpoints ---

@app.get("/api/fs/list", dependencies=[Depends(verify_token)])
async def fs_list(path: str):
    """Returns directory contents for the given path."""
    try:
        req_path = Path(path).resolve()
        if not req_path.exists() or not req_path.is_dir():
            raise HTTPException(status_code=404, detail="Directory not found or is not a directory.")

        children = []

        # Default ignore list
        ignore_dirs = {'node_modules', '__pycache__', 'dist', 'build', 'target', 'venv', 'env', '.venv', '.git'}

        for entry in os.scandir(req_path):
            # Skip hidden files and some common huge directories
            if entry.name.startswith('.') or entry.name in ignore_dirs:
                continue

            is_dir = entry.is_dir()
            children.append({
                "name": entry.name,
                "path": entry.path,
                "is_dir": is_dir
            })

        return {
            "name": req_path.name,
            "path": str(req_path),
            "children": children
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def _get_file_explanation(filepath: Path) -> str:
    """Heuristic logic to generate a short file explanation."""
    name = filepath.name.lower()
    ext = filepath.suffix.lower()

    if ext == '.py':
        if 'test' in name: return "Python test script"
        if 'manager' in name or 'controller' in name: return "Python management/controller logic"
        return "Python source file"
    if ext == '.js': return "JavaScript file"
    if ext == '.html': return "HTML structure"
    if ext == '.css': return "CSS stylesheet"
    if ext == '.json': return "JSON configuration/data file"
    if ext == '.csv': return "CSV data file"
    if ext == '.md': return "Markdown documentation"
    if ext == '.txt': return "Text file"
    if ext in ['.png', '.jpg', '.jpeg', '.gif', '.ico']: return "Image file"

    return "Unknown file type"

@app.post("/api/fs/compile", dependencies=[Depends(verify_token)])
async def fs_compile(payload: FileTreeSelectionModel):
    """Compiles the selected tree into a repo-RWI artifact."""
    root_path = Path(payload.root_path)
    selections = payload.selections

    # Exclusions
    ignore_exts = {'.pyc', '.exe', '.dll', '.so', '.dylib', '.png', '.jpg', '.jpeg', '.gif', '.ico', '.pdf', '.zip', '.tar', '.gz'}
    max_file_size = 500 * 1024  # 500 KB limit for expansion

    artifact_lines = []

    # 1. Header
    artifact_lines.append("==================================================================")
    artifact_lines.append(f"REPOSITORY CONTEXT: {payload.root_name}")
    artifact_lines.append(f"LOCAL PATH: {root_path}")
    artifact_lines.append(f"GENERATED: {datetime.datetime.now().isoformat()}")
    artifact_lines.append("==================================================================\n")

    # 2. Structured Tree Listing
    artifact_lines.append("### REPOSITORY STRUCTURE ###")
    artifact_lines.append("The following files and directories are present in the repository:")

    expanded_files = [] # Tuples of (relative_path, full_path, explanation)

    for rel_path_str, state in selections.items():
        if state.get("include"):
            is_dir = state.get("is_dir", False)
            icon = "📁" if is_dir else "📄"
            depth = len(rel_path_str.replace('\\', '/').split('/')) - 1
            indent = "  " * depth

            # Simple explanation
            full_path = root_path / rel_path_str
            explanation = _get_file_explanation(full_path) if not is_dir else "Folder"

            expand_mark = "[EXPANDED]" if state.get("expand") and not is_dir else ""
            artifact_lines.append(f"{indent}- {icon} {rel_path_str} : {explanation} {expand_mark}")

        if state.get("expand"):
            # If it's a directory, we could recursively expand, but for phase 1 we trust the user selected files directly
            # or we expand files inside. For now, let's just expand explicitly selected files.
            is_dir = state.get("is_dir", False)
            if not is_dir:
                full_path = root_path / rel_path_str
                expanded_files.append((rel_path_str, full_path, _get_file_explanation(full_path)))
            else:
                # Recursively add files in the expanded directory
                dir_path = root_path / rel_path_str
                if dir_path.exists() and dir_path.is_dir():
                    for root, _, files in os.walk(dir_path):
                        for file in files:
                            if file.startswith('.'): continue
                            fpath = Path(root) / file
                            rpath = str(fpath.relative_to(root_path)).replace('\\', '/')
                            expanded_files.append((rpath, fpath, _get_file_explanation(fpath)))


    # Deduplicate expanded files (in case a file AND its parent dir were marked 'expand')
    seen = set()
    unique_expanded = []
    for r, f, e in expanded_files:
        if r not in seen:
            seen.add(r)
            unique_expanded.append((r, f, e))

    # 3. Content Expansion
    artifact_lines.append("\n### FILE CONTENTS ###")
    artifact_lines.append("The following files have been expanded for detailed inspection:\n")

    for rel_path, full_path, explanation in unique_expanded:
        if not full_path.exists():
            continue

        if full_path.suffix.lower() in ignore_exts:
            continue

        try:
            stat = full_path.stat()
            if stat.st_size > max_file_size:
                artifact_lines.append(f"--- FILE: {rel_path} ---")
                artifact_lines.append(f"Explanation: {explanation}")
                artifact_lines.append(f"[CONTENT SKIPPED: File size ({stat.st_size} bytes) exceeds {max_file_size} bytes limit]\n")
                continue

            content = full_path.read_text(encoding='utf-8')

            artifact_lines.append(f"--- FILE: {rel_path} ---")
            artifact_lines.append(f"Explanation: {explanation}")
            artifact_lines.append("Content:")
            artifact_lines.append("```")
            artifact_lines.append(content)
            artifact_lines.append("```\n")

        except UnicodeDecodeError:
            artifact_lines.append(f"--- FILE: {rel_path} ---")
            artifact_lines.append(f"Explanation: {explanation}")
            artifact_lines.append("[CONTENT SKIPPED: Binary file detected]\n")
        except Exception as e:
            artifact_lines.append(f"--- FILE: {rel_path} ---")
            artifact_lines.append(f"[ERROR READING FILE: {e}]\n")

    return {"artifact": "\n".join(artifact_lines)}

@app.post("/api/fs/inject", dependencies=[Depends(verify_token)])
async def fs_inject(payload: InjectArtifactModel):
    """Saves the artifact to be injected on the next run."""
    try:
        flags_dir = Path("global_flags")
        flags_dir.mkdir(exist_ok=True)
        with open(flags_dir / "repo_context.txt", "w", encoding="utf-8") as f:
            f.write(payload.artifact)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/fs/inject", dependencies=[Depends(verify_token)])
async def fs_clear_inject():
    """Clears the injected repo context."""
    try:
        context_file = Path("global_flags/repo_context.txt")
        if context_file.exists():
            context_file.unlink()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/fs/profiles", dependencies=[Depends(verify_token)])
async def get_fs_profiles():
    try:
        profiles_dir = Path("repo_profiles")
        if not profiles_dir.exists(): return []
        return [f.stem for f in profiles_dir.glob("*.json")]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/fs/profiles/{name}", dependencies=[Depends(verify_token)])
async def load_fs_profile(name: str):
    try:
        file_path = Path("repo_profiles") / f"{name}.json"
        if not file_path.exists(): raise HTTPException(status_code=404, detail="Profile not found")
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/fs/profiles", dependencies=[Depends(verify_token)])
async def save_fs_profile(payload: FileTreeProfileModel):
    try:
        profiles_dir = Path("repo_profiles")
        profiles_dir.mkdir(exist_ok=True)
        file_path = profiles_dir / f"{payload.name}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(payload.dict(), f, indent=2)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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




# --- Terminal Logic ---

import platform
import struct
if platform.system() != "Windows":
    import pty
    import termios
    import fcntl

from fastapi import WebSocket, WebSocketDisconnect

class WebTerminalSession:
    def __init__(self, session_id: str, cwd: Optional[str] = None):
        self.id = session_id
        self.created_at = time.time()
        self.cwd = cwd
        self.cols = 80
        self.rows = 24
        self.process = None
        self.master_fd = None
        self.os_type = platform.system()
        self.loop = asyncio.get_running_loop()
        self.history = []
        self.subscribers: set[WebSocket] = set()
        self.reader_task = None
        self.closed = False
        self._start()

    def _start(self):
        if self.os_type == "Windows":
            self.process = subprocess.Popen(
                ["cmd.exe"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                shell=False,
                cwd=self.cwd
            )
            self.reader_task = asyncio.create_task(self._read_loop())
        else:
            self.closed = True
            self.history.append("Internal Error: WebTerminalSession used on Linux. Use LocalPTYSession.\r\n")

    async def _read_loop(self):
        while not self.closed:
            data = await self._read_output()
            if not data:
                break
            try:
                text = data.decode(errors="replace")
                self.history.append(text)
                if len(self.history) > 1000:
                     self.history = self.history[-1000:]
                await self._broadcast(text)
            except Exception as e:
                break
        if not self.closed:
             msg = "\r\n\x1b[1;31m[Process terminated]\x1b[0m\r\n"
             self.history.append(msg)
             await self._broadcast(msg)
        self.close()

    async def _broadcast(self, text: str):
        msg = json.dumps({"type": "output", "data": text})
        to_remove = []
        for ws in self.subscribers:
            try:
                await ws.send_text(msg)
            except:
                to_remove.append(ws)
        for ws in to_remove:
            self.subscribers.discard(ws)

    async def _read_output(self):
        if self.os_type == "Windows":
            return await self.loop.run_in_executor(None, self._read_windows)
        else:
            return await self.loop.run_in_executor(None, self._read_linux)

    def _read_windows(self):
        if self.process and self.process.stdout:
            return self.process.stdout.read(1024)
        return b""

    def _read_linux(self):
        if self.master_fd:
            try:
                return os.read(self.master_fd, 1024)
            except OSError:
                return b""
        return b""

    def write_input(self, data: str):
        if self.closed: return
        if self.os_type == "Windows":
            if self.process and self.process.stdin:
                try:
                    self.process.stdin.write(data.encode())
                    self.process.stdin.flush()
                except: pass
        else:
            if self.master_fd:
                try:
                    os.write(self.master_fd, data.encode())
                except: pass

    def resize(self, cols, rows):
        self.cols = cols
        self.rows = rows
        if self.os_type != "Windows" and self.master_fd is not None:
            try:
                winsize = struct.pack("HHHH", rows, cols, 0, 0)
                fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
            except: pass

    def close(self):
        self.closed = True
        if self.process:
            self.process.terminate()
        if self.os_type != "Windows" and self.master_fd:
            try: os.close(self.master_fd)
            except: pass


class LocalPTYSession(WebTerminalSession):
    def _start(self):
        if self.os_type == "Windows":
            self.closed = True
            self.history.append("Local PTY mode is not supported on Windows.\r\n")
            return

        shell = os.environ.get("SHELL", "/bin/bash")
        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        claude_bin = claude_run_manager._resolve_claude_binary()
        if claude_bin:
            env["LYRN_CLAUDE_BIN"] = claude_bin
            bin_dir = str(Path(claude_bin).parent)
            path_val = env.get("PATH", "")
            if bin_dir not in path_val.split(os.pathsep):
                env["PATH"] = bin_dir + (os.pathsep + path_val if path_val else "")

        # Set Anthropic Proxy Environment Variables
        # Attempt to read port from port.txt + 1
        default_port = 8001
        try:
            if os.path.exists("port.txt"):
                with open("port.txt", "r") as f:
                    val = f.read().strip()
                    if val.isdigit():
                        default_port = int(val) + 1
        except:
            pass

        host = os.environ.get("LCC_HOST", "127.0.0.1")
        port = os.environ.get("LCC_PORT", str(default_port))
        base_url = f"http://{host}:{port}"

        env["ANTHROPIC_BASE_URL"] = base_url
        env["ANTHROPIC_AUTH_TOKEN"] = "lyrn"
        env["ANTHROPIC_API_KEY"] = ""
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"


        try:
            pid, master_fd = pty.fork()
            if pid == 0:
                if self.cwd:
                    try: os.chdir(self.cwd)
                    except: pass
                try:
                    os.execve(shell, [shell], env)
                except Exception as e:
                    os._exit(1)
            else:
                self.pid = pid
                self.master_fd = master_fd
                self.reader_task = asyncio.create_task(self._read_loop())
        except Exception as e:
            self.history.append(f"Error: Failed to start PTY. {str(e)}\r\n")
            self.close()

    def close(self):
        self.closed = True
        if hasattr(self, 'pid') and self.pid:
            try:
                os.kill(self.pid, 9)
                os.waitpid(self.pid, os.WNOHANG)
            except: pass
        if self.master_fd:
            try: os.close(self.master_fd)
            except: pass

terminal_sessions: Dict[str, WebTerminalSession] = {}
terminal_sessions_lock = asyncio.Lock()

async def get_or_create_terminal_session(sid: str, cwd: Optional[str]) -> WebTerminalSession:
    async with terminal_sessions_lock:
        existing = terminal_sessions.get(sid)
        if existing and not getattr(existing, "closed", True):
            return existing

        if platform.system() == "Windows":
            session = WebTerminalSession(sid, cwd=cwd)
        else:
            session = LocalPTYSession(sid, cwd=cwd)
        terminal_sessions[sid] = session
        return session

async def maybe_cleanup_terminal_session(sid: str):
    await asyncio.sleep(15)
    async with terminal_sessions_lock:
        session = terminal_sessions.get(sid)
        if not session:
            return
        if session.subscribers:
            return
        try:
            session.close()
        finally:
            terminal_sessions.pop(sid, None)


@app.websocket("/api/terminal/{sid}")
async def terminal_stream_ws(sid: str, websocket: WebSocket, token: Optional[str] = None, cwd: Optional[str] = None):
    try:
        # Auth check
        if not Path("global_flags/no_auth").exists():
            if not LYRN_TOKEN or not token or token != LYRN_TOKEN:
                print(f"[Terminal] Denied access. Expected: {LYRN_TOKEN} Got: {token}")
                await websocket.close(code=4003)
                return

        # Validate optional cwd
        safe_cwd: Optional[str] = None
        if cwd:
            try:
                p = Path(cwd).expanduser()
                if p.is_dir():
                    safe_cwd = str(p.resolve())
                else:
                    print(f"[Terminal] Ignoring invalid cwd: {cwd}")
            except Exception as e:
                print(f"[Terminal] cwd validation error: {e}")

        await websocket.accept()
        session = await get_or_create_terminal_session(sid, safe_cwd)

        session.subscribers.add(websocket)
        print(f"[Terminal] Connected {sid}")

        for chunk in session.history:
             await websocket.send_text(json.dumps({"type": "output", "data": chunk}))

        while True:
            msg_text = await websocket.receive_text()
            msg = json.loads(msg_text)

            if msg["type"] == "input":
                session.write_input(msg["data"])
            elif msg["type"] == "resize":
                session.resize(msg.get("cols", 80), msg.get("rows", 24))

    except WebSocketDisconnect:
        print(f"[Terminal] Disconnected {sid}")
    except Exception as e:
        print(f"[Terminal] Error: {e}")
    finally:
        if 'session' in locals():
            session.subscribers.discard(websocket)
            if not session.subscribers:
                asyncio.create_task(maybe_cleanup_terminal_session(sid))

# Serve dashboard at root

@app.get("/")
async def read_root():
    return FileResponse('LYRN_v6/dashboard.html')

# Serve Static Files
app.mount("/", StaticFiles(directory="LYRN_v6", html=True), name="static")

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
