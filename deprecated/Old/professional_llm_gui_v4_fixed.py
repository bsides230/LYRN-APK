"""
Professional LLM Interface v4.0 - FIXED VERSION

Fixed CTkFont issues and other compatibility problems.

Key Fixes:
- Removed problematic CTkFont import
- Fixed font parameter usage (weight -> weight)
- Added proper error handling for missing theme
- Fixed path backslashes in Windows paths
- Added fallback font handling
"""

import os
import sys
import json
import re
import time
import queue
import threading
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from pathlib import Path
import shutil

# CustomTkinter imports - FIXED: Remove separate CTkFont import
import customtkinter as ctk
from llama_cpp import Llama

# Set appearance and theme
ctk.set_appearance_mode("dark")

# Script directory and settings path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(SCRIPT_DIR, "settings.json")
THEME_PATH = os.path.join(SCRIPT_DIR, "purple-theme.json")

class SettingsManager:
    """Manages application settings with JSON configuration"""
    
    def __init__(self):
        self.settings = self.load_settings()
        self.ensure_automation_flag()
    
    def load_settings(self) -> dict:
        """Load settings from JSON file or create default if missing"""
        if os.path.exists(SETTINGS_PATH):
            try:
                with open(SETTINGS_PATH, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading settings: {e}")
                return self.get_default_settings()
        else:
            # Auto-generate default settings file
            default = self.get_default_settings()
            self.save_settings(default)
            return default
    
    def get_default_settings(self) -> dict:
        """Return default settings structure - FIXED: Proper path formatting"""
        return {
            "active": {
                "model_path": r"D:\LLMs\LYRN_AGENT_V1\LYRN\models\Qwen.Qwen3-4B-Thinking-2507.Q4_K_M.gguf",
                "n_ctx": 32000,
                "n_threads": 22,
                "n_gpu_layers": 36,
                "max_tokens": 4096,
                "temperature": 0.7,
                "top_p": 0.95,
                "top_k": 40,
                "stream": True
            },
            "defaults": {
                "model_path": r"D:\LLMs\LYRN_AGENT_V1\LYRN\models\default.gguf",
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
                "static_snapshots": r"D:\LLMs\LYRN_AGENT_V1\LYRN\static_snapshots",
                "dynamic_snapshots": r"D:\LLMs\LYRN_AGENT_V1\LYRN\dynamic_snapshots",
                "active_jobs": r"D:\LLMs\LYRN_AGENT_V1\LYRN\active_jobs",
                "deltas": r"D:\LLMs\LYRN_AGENT_V1\LYRN\deltas",
                "chat": r"D:\LLMs\LYRN_AGENT_V1\LYRN\chat",
                "output": r"D:\LLMs\LYRN_AGENT_V1\LYRN\output",
                "keywords": r"D:\LLMs\LYRN_AGENT_V1\LYRN\active_keywords",
                "topics": r"D:\LLMs\LYRN_AGENT_V1\LYRN\active_topics",
                "active_chunk": r"D:\LLMs\LYRN_AGENT_V1\LYRN\active_chunk",
                "chunk_queue": r"D:\LLMs\LYRN_AGENT_V1\LYRN\automation\chunk_queue.json",
                "job_list": r"D:\LLMs\LYRN_AGENT_V1\LYRN\automation\job_list.txt",
                "job_log": r"D:\LLMs\LYRN_AGENT_V1\LYRN\automation\job_log.json",
                "automation_flag_path": r"D:\LLMs\LYRN_AGENT_V1\LYRN\global_flags\automation.txt",
                "chunk_queue_path": r"D:\LLMs\LYRN_AGENT_V1\LYRN\automation\chunk_queue.json",
                "chat_dir": r"D:\LLMs\LYRN_AGENT_V1\LYRN\chat",
                "chat_parsed_dir": r"D:\LLMs\LYRN_AGENT_V1\LYRN\chat_parsed",
                "audit_dir": r"D:\LLMs\LYRN_AGENT_V1\LYRN\automation\job_audit"
            }
        }
    
    def save_settings(self, settings: dict):
        """Save settings to JSON file with backup"""
        try:
            # Create backup if file exists
            if os.path.exists(SETTINGS_PATH):
                backup_path = SETTINGS_PATH + '.bk'
                shutil.copy2(SETTINGS_PATH, backup_path)
            
            with open(SETTINGS_PATH, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            print(f"Error saving settings: {e}")
    
    def restore_from_backup(self):
        """Restore settings from backup file"""
        backup_path = SETTINGS_PATH + '.bk'
        if os.path.exists(backup_path):
            try:
                shutil.copy2(backup_path, SETTINGS_PATH)
                self.settings = self.load_settings()
                return True
            except Exception as e:
                print(f"Error restoring backup: {e}")
                return False
        return False
    
    def reset_to_defaults(self):
        """Reset active settings to defaults"""
        self.settings["active"] = self.settings["defaults"].copy()
        self.save_settings(self.settings)
    
    def ensure_automation_flag(self):
        """Ensure automation flag is set to 'off' on startup"""
        flag_path = self.settings["paths"]["automation_flag_path"]
        os.makedirs(os.path.dirname(flag_path), exist_ok=True)
        
        try:
            with open(flag_path, 'w', encoding='utf-8') as f:
                f.write("off")
        except Exception as e:
            print(f"Warning: Could not set automation flag: {e}")
    
    def set_automation_flag(self, state: str):
        """Set automation flag to 'on' or 'off'"""
        flag_path = self.settings["paths"]["automation_flag_path"]
        try:
            with open(flag_path, 'w', encoding='utf-8') as f:
                f.write(state)
        except Exception as e:
            print(f"Error setting automation flag: {e}")

class PromptBuilder:
    """Builds prompts using new folder structure with rwi.txt files"""
    
    def __init__(self, settings_manager: SettingsManager):
        self.settings = settings_manager
        self.paths = settings_manager.settings["paths"]
    
    def load_from_rwi_folder(self, folder_path: str, rwi_filename: str) -> str:
        """Load text files from folder using rwi.txt for ordering"""
        if not os.path.exists(folder_path):
            return ""
        
        rwi_path = os.path.join(folder_path, rwi_filename)
        if not os.path.exists(rwi_path):
            return ""
        
        try:
            with open(rwi_path, 'r', encoding='utf-8') as f:
                file_list = [line.strip() for line in f.readlines() if line.strip()]
            
            content_parts = []
            for relative_path in file_list:
                full_path = os.path.join(folder_path, relative_path)
                if os.path.exists(full_path) and full_path.endswith('.txt'):
                    try:
                        with open(full_path, 'r', encoding='utf-8') as f:
                            content_parts.append(f.read().strip())
                    except Exception as e:
                        print(f"Error reading {full_path}: {e}")
            
            return "\n\n".join(content_parts) if content_parts else ""
            
        except Exception as e:
            print(f"Error processing rwi folder {folder_path}: {e}")
            return ""
    
    def load_single_file(self, file_path: str) -> str:
        """Load a single text file safely"""
        if not os.path.exists(file_path):
            return ""
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read().strip()
        except Exception as e:
            print(f"Error reading {file_path}: {e}")
            return ""
    
    def load_timestamp_ordered_files(self, *folder_paths: str) -> List[str]:
        """Load files from multiple folders ordered by timestamp in filename"""
        all_files = []
        
        for folder_path in folder_paths:
            if not os.path.exists(folder_path):
                continue
                
            try:
                for filename in os.listdir(folder_path):
                    if filename.endswith('.txt'):
                        full_path = os.path.join(folder_path, filename)
                        all_files.append((filename, full_path))
            except Exception as e:
                print(f"Error listing files in {folder_path}: {e}")
        
        # Sort by filename (which contains timestamp)
        all_files.sort(key=lambda x: x[0])
        
        contents = []
        for filename, full_path in all_files:
            content = self.load_single_file(full_path)
            if content:
                contents.append(content)
        
        return contents
    
    def build_full_prompt(self, manual_mode: bool = False) -> str:
        """Build complete prompt following new folder structure"""
        prompt_parts = []
        
        # 1. Static snapshots
        static_content = self.load_from_rwi_folder(
            self.paths["static_snapshots"], "sta_rwi.txt"
        )
        if static_content:
            prompt_parts.append("=== STATIC KNOWLEDGE BASE ===")
            prompt_parts.append(static_content)
        
        # 2. Dynamic snapshots
        dynamic_content = self.load_from_rwi_folder(
            self.paths["dynamic_snapshots"], "dyn_rwi.txt"
        )
        if dynamic_content:
            prompt_parts.append("=== DYNAMIC CONTEXT ===")
            prompt_parts.append(dynamic_content)
        
        # 3. Active jobs
        jobs_content = self.load_from_rwi_folder(
            self.paths["active_jobs"], "job_rwi.txt"
        )
        if jobs_content:
            prompt_parts.append("=== ACTIVE JOBS ===")
            prompt_parts.append(jobs_content)
        
        # 4. Deltas (optional)
        deltas_files = []
        if os.path.exists(self.paths["deltas"]):
            deltas_files = self.load_timestamp_ordered_files(self.paths["deltas"])
        if deltas_files:
            prompt_parts.append("=== SYSTEM UPDATES ===")
            prompt_parts.extend(deltas_files)
        
        # 5. Active chunk
        chunk_path = os.path.join(self.paths["active_chunk"], "chunk.txt")
        chunk_content = self.load_single_file(chunk_path)
        if chunk_content:
            prompt_parts.append("=== ACTIVE CONVERSATION CHUNK ===")
            prompt_parts.append(chunk_content)
        
        # 6. Manual mode: KV-preserving replay
        if manual_mode:
            replay_files = self.load_timestamp_ordered_files(
                self.paths["chat"], self.paths["deltas"]
            )
            if replay_files:
                prompt_parts.append("=== CONVERSATION HISTORY ===")
                prompt_parts.extend(replay_files)
        
        # 7. Keywords (optional)
        if os.path.exists(self.paths["keywords"]):
            keywords_files = self.load_timestamp_ordered_files(self.paths["keywords"])
            if keywords_files:
                prompt_parts.append("=== ACTIVE KEYWORDS ===")
                prompt_parts.extend(keywords_files)
        
        # 8. Topics (optional)
        if os.path.exists(self.paths["topics"]):
            topics_files = self.load_timestamp_ordered_files(self.paths["topics"])
            if topics_files:
                prompt_parts.append("=== ACTIVE TOPICS ===")
                prompt_parts.extend(topics_files)
        
        return "\n\n".join(prompt_parts)

class JobProcessor:
    """Manages job automation without delays or AutoHotkey"""
    
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
        job_list_path = self.settings.settings["paths"]["job_list"]
        
        if not os.path.exists(job_list_path):
            print("Job list file not found - automation disabled")
            self.job_names = ["Summary Job", "Keyword Job", "Topic Job"]
            self.jobs = {
                "Summary Job": "Provide a summary between ###SUMMARY_START### and ###SUMMARY_END### tags.",
                "Keyword Job": "Extract keywords between ###KEYWORDS_START### and ###KEYWORDS_END### tags.",
                "Topic Job": "Identify topics between ###TOPICS_START### and ###TOPICS_END### tags."
            }
            return
        
        try:
            with open(job_list_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Extract job names
            start_marker = "#*#job_list_start#*#"
            end_marker = "#*#job_list_end#*#"
            start_idx = content.find(start_marker)
            end_idx = content.find(end_marker)
            
            if start_idx != -1 and end_idx != -1:
                job_section = content[start_idx + len(start_marker):end_idx].strip()
                self.job_names = [name.strip() for name in job_section.split('\n') if name.strip()]
            
            # Extract job instructions
            job_pattern = r'JOB_START:\s*(.+?)\n(.*?)(?=JOB_START:|$)'
            matches = re.findall(job_pattern, content, re.DOTALL)
            
            for job_name, instructions in matches:
                self.jobs[job_name.strip()] = instructions.strip()
                
            print(f"Loaded {len(self.job_names)} jobs from file")
            
        except Exception as e:
            print(f"Error loading jobs: {e}")
            # Use fallback jobs
            self.job_names = ["Summary Job", "Keyword Job", "Topic Job"]
            self.jobs = {
                "Summary Job": "Provide a summary between ###SUMMARY_START### and ###SUMMARY_END### tags.",
                "Keyword Job": "Extract keywords between ###KEYWORDS_START### and ###KEYWORDS_END### tags.",
                "Topic Job": "Identify topics between ###TOPICS_START### and ###TOPICS_END### tags."
            }
    
    def start_automation(self):
        """Start job automation"""
        self.job_running = True
        self.current_job_index = 0
        self.settings.set_automation_flag("on")
        
        if self.gui:
            self.gui.update_status("Automation started", "#8B5FBF")
        
        # Start processing thread
        threading.Thread(target=self._process_jobs, daemon=True).start()
    
    def stop_automation(self):
        """Stop job automation"""
        self.job_running = False
        self.settings.set_automation_flag("off")
        
        if self.gui:
            self.gui.update_status("Automation stopped", "#FF6B6B")
    
    def _process_jobs(self):
        """Process jobs without delays - triggered by conditions"""
        while self.job_running and self.current_job_index < len(self.job_names):
            current_job = self.job_names[self.current_job_index]
            job_text = self.jobs.get(current_job, "")
            
            if job_text and self.gui:
                self.gui.insert_job_text(job_text)
                self.gui.update_status(f"Processing: {current_job}", "#8B5FBF")
            
            # Log job completion
            self._log_job_completion(current_job)
            
            self.current_job_index += 1
            
            # Wait for chunk transition or user signal instead of time delay
            # This would be triggered by external conditions
            break
        
        if self.job_running:
            self.gui.update_status("All jobs completed", "#4ECDC4")
            self.job_running = False
    
    def _log_job_completion(self, job_name: str):
        """Log completed job to chunk-based JSON log"""
        log_path = self.settings.settings["paths"]["job_log"]
        
        try:
            # Load existing log or create new
            if os.path.exists(log_path):
                with open(log_path, 'r', encoding='utf-8') as f:
                    log_data = json.load(f)
            else:
                log_data = {
                    "chunk_index": 0,
                    "chunk_path": "",
                    "jobs_performed": []
                }
            
            # Add job if not already logged
            if job_name not in log_data["jobs_performed"]:
                log_data["jobs_performed"].append(job_name)
            
            # Update chunk info from queue if available
            queue_path = self.settings.settings["paths"]["chunk_queue"]
            if os.path.exists(queue_path):
                try:
                    with open(queue_path, 'r', encoding='utf-8') as f:
                        queue_data = json.load(f)
                    
                    idx = queue_data.get('queue_index', 0)
                    if idx < len(queue_data.get('queue', [])):
                        chunk_info = queue_data['queue'][idx]
                        log_data["chunk_index"] = idx
                        log_data["chunk_path"] = chunk_info.get("chunk_path", "")
                        
                except Exception as e:
                    print(f"Error reading chunk queue: {e}")
            
            # Save updated log
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, 'w', encoding='utf-8') as f:
                json.dump(log_data, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            print(f"Error logging job completion: {e}")

class PerformanceMetrics:
    """Tracks and displays LLM performance metrics"""
    
    def __init__(self):
        self.kv_cache_reused = 0
        self.prompt_tokens = 0
        self.prompt_speed = 0.0
        self.eval_tokens = 0
        self.eval_speed = 0.0
        self.total_tokens = 0
        self.total_time = 0.0
        self.load_time = 0.0
    
    def parse_llama_logs(self, log_output: str):
        """Parse llama-cpp performance logs"""
        try:
            # Parse KV cache prefix-match hit
            kv_match = re.search(r'(\d+)\s+prefix-match hit', log_output)
            if kv_match:
                self.kv_cache_reused = int(kv_match.group(1))
            
            # Parse load time
            load_match = re.search(r'load time\s*=\s*([\d.]+)\s*ms', log_output)
            if load_match:
                self.load_time = float(load_match.group(1))
            
            # Parse prompt evaluation
            prompt_match = re.search(
                r'prompt eval time\s*=\s*([\d.]+)\s*ms\s*/\s*(\d+)\s*tokens.*?([\d.]+)\s*ms per token', 
                log_output
            )
            if prompt_match:
                prompt_time = float(prompt_match.group(1))
                self.prompt_tokens = int(prompt_match.group(2))
                ms_per_token = float(prompt_match.group(3))
                self.prompt_speed = 1000.0 / ms_per_token if ms_per_token > 0 else 0.0
            
            # Parse generation/eval
            eval_match = re.search(
                r'eval time\s*=\s*([\d.]+)\s*ms\s*/\s*(\d+)\s*runs.*?([\d.]+)\s*ms per token', 
                log_output
            )
            if eval_match:
                eval_time = float(eval_match.group(1))
                self.eval_tokens = int(eval_match.group(2))
                ms_per_token = float(eval_match.group(3))
                self.eval_speed = 1000.0 / ms_per_token if ms_per_token > 0 else 0.0
            
            # Calculate totals
            self.total_tokens = self.prompt_tokens + self.eval_tokens
            if 'prompt_time' in locals() and 'eval_time' in locals():
                self.total_time = (self.load_time + prompt_time + eval_time) / 1000.0
                
        except Exception as e:
            print(f"Metrics parsing error: {e}")

class StreamHandler:
    """Handles streaming response with metrics capture"""
    
    def __init__(self, gui_queue, metrics: PerformanceMetrics):
        self.gui_queue = gui_queue
        self.metrics = metrics
        self.current_response = ""
        self.is_finished = False
        self.log_buffer = ""
    
    def handle_token(self, token_data):
        """Handle streaming tokens"""
        if 'choices' in token_data and len(token_data['choices']) > 0:
            delta = token_data['choices'][0].get('delta', {})
            content = delta.get('content', '')
            
            if content:
                self.current_response += content
                state = 'reasoning' if self.is_finished else 'thinking'
                self.gui_queue.put(('token', content, state))
            
            # Check if finished
            finish_reason = token_data['choices'][0].get('finish_reason')
            if finish_reason is not None:
                self.is_finished = True
                self.gui_queue.put(('finished', self.current_response))
    
    def capture_logs(self, log_content: str):
        """Capture performance logs"""
        self.log_buffer += log_content
        
        if "llama_perf_context_print" in self.log_buffer:
            self.metrics.parse_llama_logs(self.log_buffer)
            self.gui_queue.put(('metrics_update', ''))
    
    def get_response(self) -> str:
        return self.current_response

class SettingsDialog(ctk.CTkToplevel):
    """Settings configuration dialog - FIXED: Font handling"""
    
    def __init__(self, parent, settings_manager: SettingsManager):
        super().__init__(parent)
        self.settings_manager = settings_manager
        self.title("Application Settings")
        self.geometry("800x600")
        self.resizable(False, False)
        
        # Make modal
        self.transient(parent)
        self.grab_set()
        
        self.create_widgets()
        self.load_current_settings()
    
    def create_widgets(self):
        """Create settings dialog widgets"""
        
        # Main frame with scrollable content
        main_frame = ctk.CTkScrollableFrame(self)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Model Settings Section
        model_frame = ctk.CTkFrame(main_frame)
        model_frame.pack(fill="x", pady=(0, 20))
        
        # FIXED: Use proper font parameters
        try:
            title_font = ctk.CTkFont(size=16, weight="bold")
        except:
            title_font = ("Arial", 16, "bold")  # Fallback
            
        ctk.CTkLabel(model_frame, text="Model Configuration", font=title_font).pack(pady=10)
        
        # Model path
        ctk.CTkLabel(model_frame, text="Model Path:").pack(anchor="w", padx=20)
        self.model_path_entry = ctk.CTkEntry(model_frame, width=500)
        self.model_path_entry.pack(padx=20, pady=(0, 10), fill="x")
        
        # Model parameters in grid
        params_frame = ctk.CTkFrame(model_frame)
        params_frame.pack(fill="x", padx=20, pady=(0, 20))
        
        # Row 1
        ctk.CTkLabel(params_frame, text="Context Size:").grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.n_ctx_entry = ctk.CTkEntry(params_frame, width=100)
        self.n_ctx_entry.grid(row=0, column=1, padx=10, pady=5)
        
        ctk.CTkLabel(params_frame, text="Threads:").grid(row=0, column=2, padx=10, pady=5, sticky="w")
        self.n_threads_entry = ctk.CTkEntry(params_frame, width=100)
        self.n_threads_entry.grid(row=0, column=3, padx=10, pady=5)
        
        # Row 2
        ctk.CTkLabel(params_frame, text="GPU Layers:").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.n_gpu_layers_entry = ctk.CTkEntry(params_frame, width=100)
        self.n_gpu_layers_entry.grid(row=1, column=1, padx=10, pady=5)
        
        ctk.CTkLabel(params_frame, text="Max Tokens:").grid(row=1, column=2, padx=10, pady=5, sticky="w")
        self.max_tokens_entry = ctk.CTkEntry(params_frame, width=100)
        self.max_tokens_entry.grid(row=1, column=3, padx=10, pady=5)
        
        # Row 3
        ctk.CTkLabel(params_frame, text="Temperature:").grid(row=2, column=0, padx=10, pady=5, sticky="w")
        self.temperature_entry = ctk.CTkEntry(params_frame, width=100)
        self.temperature_entry.grid(row=2, column=1, padx=10, pady=5)
        
        ctk.CTkLabel(params_frame, text="Top P:").grid(row=2, column=2, padx=10, pady=5, sticky="w")
        self.top_p_entry = ctk.CTkEntry(params_frame, width=100)
        self.top_p_entry.grid(row=2, column=3, padx=10, pady=5)
        
        # Paths Section
        paths_frame = ctk.CTkFrame(main_frame)
        paths_frame.pack(fill="x", pady=(0, 20))
        
        ctk.CTkLabel(paths_frame, text="Directory Paths", font=title_font).pack(pady=10)
        
        # Create path entries
        self.path_entries = {}
        path_labels = {
            "static_snapshots": "Static Snapshots",
            "dynamic_snapshots": "Dynamic Snapshots", 
            "active_jobs": "Active Jobs",
            "deltas": "Deltas",
            "chat": "Chat Directory",
            "output": "Output Directory",
            "active_chunk": "Active Chunk",
            "automation_flag_path": "Automation Flag",
            "job_list": "Job List File",
            "job_log": "Job Log File"
        }
        
        for key, label in path_labels.items():
            ctk.CTkLabel(paths_frame, text=f"{label}:").pack(anchor="w", padx=20, pady=(5, 0))
            entry = ctk.CTkEntry(paths_frame, width=500)
            entry.pack(padx=20, pady=(0, 5), fill="x")
            self.path_entries[key] = entry
        
        # Buttons
        button_frame = ctk.CTkFrame(self)
        button_frame.pack(fill="x", padx=20, pady=(0, 20))
        
        ctk.CTkButton(button_frame, text="Save", command=self.save_settings).pack(side="left", padx=10, pady=10)
        ctk.CTkButton(button_frame, text="Restore Backup", command=self.restore_backup).pack(side="left", padx=10, pady=10)
        ctk.CTkButton(button_frame, text="Reset to Defaults", command=self.reset_defaults).pack(side="left", padx=10, pady=10)
        ctk.CTkButton(button_frame, text="Cancel", command=self.destroy).pack(side="right", padx=10, pady=10)
    
    def load_current_settings(self):
        """Load current settings into dialog"""
        settings = self.settings_manager.settings
        active = settings["active"]
        paths = settings["paths"]
        
        # Model settings
        self.model_path_entry.insert(0, active["model_path"])
        self.n_ctx_entry.insert(0, str(active["n_ctx"]))
        self.n_threads_entry.insert(0, str(active["n_threads"]))
        self.n_gpu_layers_entry.insert(0, str(active["n_gpu_layers"]))
        self.max_tokens_entry.insert(0, str(active["max_tokens"]))
        self.temperature_entry.insert(0, str(active["temperature"]))
        self.top_p_entry.insert(0, str(active["top_p"]))
        
        # Paths
        for key, entry in self.path_entries.items():
            if key in paths:
                entry.insert(0, paths[key])
    
    def save_settings(self):
        """Save settings and close dialog"""
        try:
            settings = self.settings_manager.settings.copy()
            
            # Update model settings
            settings["active"]["model_path"] = self.model_path_entry.get()
            settings["active"]["n_ctx"] = int(self.n_ctx_entry.get())
            settings["active"]["n_threads"] = int(self.n_threads_entry.get())
            settings["active"]["n_gpu_layers"] = int(self.n_gpu_layers_entry.get())
            settings["active"]["max_tokens"] = int(self.max_tokens_entry.get())
            settings["active"]["temperature"] = float(self.temperature_entry.get())
            settings["active"]["top_p"] = float(self.top_p_entry.get())
            
            # Update paths
            for key, entry in self.path_entries.items():
                settings["paths"][key] = entry.get()
            
            self.settings_manager.settings = settings
            self.settings_manager.save_settings(settings)
            
            self.destroy()
            
        except ValueError as e:
            # Show error dialog
            error_dialog = ctk.CTkToplevel(self)
            error_dialog.title("Invalid Input")
            error_dialog.geometry("300x100")
            ctk.CTkLabel(error_dialog, text=f"Invalid input: {e}").pack(pady=20)
            ctk.CTkButton(error_dialog, text="OK", command=error_dialog.destroy).pack(pady=10)
    
    def restore_backup(self):
        """Restore from backup"""
        if self.settings_manager.restore_from_backup():
            self.destroy()
        else:
            # Show error
            error_dialog = ctk.CTkToplevel(self)
            error_dialog.title("Backup Error")
            error_dialog.geometry("300x100")
            ctk.CTkLabel(error_dialog, text="No backup file found").pack(pady=20)
            ctk.CTkButton(error_dialog, text="OK", command=error_dialog.destroy).pack(pady=10)
    
    def reset_defaults(self):
        """Reset to default settings"""
        self.settings_manager.reset_to_defaults()
        self.destroy()

class ProfessionalLLMInterface(ctk.CTk):
    """Main application class with modern interface - FIXED: Font handling"""
    
    def __init__(self):
        super().__init__()
        
        # FIXED: Better theme handling
        try:
            if os.path.exists(THEME_PATH):
                ctk.set_default_color_theme(THEME_PATH)
                print("Loaded custom purple theme")
            else:
                print("Custom theme not found, using default dark theme")
        except Exception as e:
            print(f"Error loading theme: {e}")
        
        # Initialize core components
        self.settings_manager = SettingsManager()
        self.prompt_builder = PromptBuilder(self.settings_manager)
        self.job_processor = JobProcessor(self.settings_manager, self)
        self.metrics = PerformanceMetrics()
        self.stream_queue = queue.Queue()
        
        # Setup GUI
        self.setup_window()
        self.setup_model()
        self.create_widgets()
        
        # Start queue processing
        self.after(100, self.process_queue)
    
    def setup_window(self):
        """Configure main window"""
        self.title("Professional LLM Interface v4.0")
        self.geometry("1400x900")
        self.minsize(1200, 800)
    
    def setup_model(self):
        """Initialize LLM model"""
        active = self.settings_manager.settings["active"]
        
        try:
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
            print("Model loaded successfully")
        except Exception as e:
            print(f"Error loading model: {e}")
            self.llm = None
    
    def create_widgets(self):
        """Create main interface widgets"""
        
        # Create main layout - side by side
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        # Left sidebar for controls
        self.create_sidebar()
        
        # Main chat area
        self.create_chat_area()
    
    def create_sidebar(self):
        """Create left sidebar with controls"""
        self.sidebar = ctk.CTkFrame(self, width=300, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew", padx=(10, 5), pady=10)
        self.sidebar.grid_propagate(False)
        
        # FIXED: Font handling with fallback
        try:
            title_font = ctk.CTkFont(size=18, weight="bold")
            section_font = ctk.CTkFont(size=14, weight="bold")
        except:
            title_font = ("Arial", 18, "bold")
            section_font = ("Arial", 14, "bold")
        
        # Title
        ctk.CTkLabel(self.sidebar, text="Control Panel", font=title_font).pack(pady=(20, 30))
        
        # Job Automation Section
        job_frame = ctk.CTkFrame(self.sidebar)
        job_frame.pack(fill="x", padx=20, pady=(0, 20))
        
        ctk.CTkLabel(job_frame, text="Job Automation", font=section_font).pack(pady=10)
        
        # Start/Stop buttons
        button_frame = ctk.CTkFrame(job_frame)
        button_frame.pack(fill="x", padx=10, pady=(0, 10))
        
        self.start_btn = ctk.CTkButton(button_frame, text="▶ Start Jobs", 
                                      command=self.start_automation)
        self.start_btn.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        self.stop_btn = ctk.CTkButton(button_frame, text="⏹ Stop Jobs", 
                                     command=self.stop_automation)
        self.stop_btn.pack(side="right", fill="x", expand=True, padx=(5, 0))
        
        # Job selection
        ctk.CTkLabel(job_frame, text="Manual Job Selection").pack(pady=(10, 5))
        self.job_dropdown = ctk.CTkComboBox(job_frame, values=self.job_processor.job_names,
                                           command=self.on_job_selected)
        self.job_dropdown.pack(padx=10, pady=(0, 15), fill="x")
        
        # Performance Metrics Section
        metrics_frame = ctk.CTkFrame(self.sidebar)
        metrics_frame.pack(fill="x", padx=20, pady=(0, 20))
        
        ctk.CTkLabel(metrics_frame, text="Performance Metrics", font=section_font).pack(pady=10)
        
        # Metrics display
        self.kv_label = ctk.CTkLabel(metrics_frame, text="KV Cache: 0 tokens")
        self.kv_label.pack(pady=2)
        
        self.prompt_label = ctk.CTkLabel(metrics_frame, text="Prompt: 0 tokens")
        self.prompt_label.pack(pady=2)
        
        self.eval_label = ctk.CTkLabel(metrics_frame, text="Generation: 0 tok/s", 
                                      text_color="#8B5FBF")
        self.eval_label.pack(pady=2)
        
        self.total_label = ctk.CTkLabel(metrics_frame, text="Total: 0 tokens")
        self.total_label.pack(pady=(2, 15))
        
        # System Controls Section
        system_frame = ctk.CTkFrame(self.sidebar)
        system_frame.pack(fill="x", padx=20, pady=(0, 20))
        
        ctk.CTkLabel(system_frame, text="System Controls", font=section_font).pack(pady=10)
        
        ctk.CTkButton(system_frame, text="⚙ Settings", 
                     command=self.open_settings).pack(padx=10, pady=5, fill="x")
        
        ctk.CTkButton(system_frame, text="🔄 Reload Model", 
                     command=self.reload_model).pack(padx=10, pady=5, fill="x")
        
        ctk.CTkButton(system_frame, text="📁 Clear Chat", 
                     command=self.clear_chat).pack(padx=10, pady=(5, 15), fill="x")
        
        # Status Section
        status_frame = ctk.CTkFrame(self.sidebar)
        status_frame.pack(fill="x", padx=20, pady=(0, 20))
        
        ctk.CTkLabel(status_frame, text="System Status", font=section_font).pack(pady=10)
        
        self.status_label = ctk.CTkLabel(status_frame, text="Ready", 
                                        text_color="#4ECDC4")
        self.status_label.pack(pady=(0, 15))
    
    def create_chat_area(self):
        """Create main chat interface"""
        chat_frame = ctk.CTkFrame(self)
        chat_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 10), pady=10)
        chat_frame.grid_rowconfigure(0, weight=1)
        chat_frame.grid_columnconfigure(0, weight=1)
        
        # FIXED: Font handling with fallback
        try:
            chat_font = ctk.CTkFont(family="Consolas", size=12)
        except:
            chat_font = ("Consolas", 12)  # Fallback
        
        # Chat display
        self.chat_display = ctk.CTkTextbox(chat_frame, font=chat_font)
        self.chat_display.grid(row=0, column=0, sticky="nsew", padx=20, pady=(20, 10))
        
        # Input area
        input_frame = ctk.CTkFrame(chat_frame)
        input_frame.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 20))
        input_frame.grid_columnconfigure(0, weight=1)
        
        self.input_box = ctk.CTkTextbox(input_frame, height=100, font=chat_font)
        self.input_box.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        
        # Send button
        self.send_btn = ctk.CTkButton(input_frame, text="Send", 
                                     width=80, command=self.send_message)
        self.send_btn.grid(row=0, column=1)
        
        # Bind Enter key (Ctrl+Enter to send)
        self.input_box.bind("<Control-Return>", lambda e: self.send_message())
        
        # Welcome message
        welcome_msg = """
╔═══════════════════════════════════════════════════════╗
║              Professional LLM Interface v4.0          ║
║                                                       ║ 
║  • Modern CustomTkinter interface                     ║
║  • Dynamic folder structure loading                   ║
║  • JSON-based settings system                         ║
║  • Chunk-aware job processing                         ║
║  • Manual mode with KV-preserving replay              ║
║                                                       ║
║  Status: System Online                                ║
╚═══════════════════════════════════════════════════════╝

Ready for interaction. Use Ctrl+Enter to send messages.
"""
        self.chat_display.insert("end", welcome_msg)
        self.chat_display.configure(state="disabled")
    
    def start_automation(self):
        """Start job automation"""
        self.job_processor.start_automation()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
    
    def stop_automation(self):
        """Stop job automation"""
        self.job_processor.stop_automation()
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
    
    def on_job_selected(self, job_name):
        """Handle manual job selection"""
        if job_name in self.job_processor.jobs:
            job_text = self.job_processor.jobs[job_name]
            self.insert_job_text(job_text)
            self.update_status(f"Manual job: {job_name}", "#8B5FBF")
    
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
            self.update_status("No model loaded", "#FF6B6B")
            return
        
        # Display user message
        self.display_message(f"User: {user_text}", "#4ECDC4")
        
        # Clear input and disable send
        self.input_box.delete("0.0", "end")
        self.send_btn.configure(state="disabled")
        
        # Save chat message
        self.save_chat_message("user", user_text)
        
        # Generate response in thread
        threading.Thread(target=self.generate_response, args=(user_text,), daemon=True).start()
        
        self.update_status("Generating response...", "#F39C12")
    
    def generate_response(self, user_text: str):
        """Generate AI response"""
        try:
            # Build prompt using new structure
            manual_mode = not self.job_processor.job_running
            full_prompt = self.prompt_builder.build_full_prompt(manual_mode)
            
            messages = [
                {"role": "system", "content": full_prompt},
                {"role": "user", "content": user_text}
            ]
            
            active = self.settings_manager.settings["active"]
            handler = StreamHandler(self.stream_queue, self.metrics)
            
            # Start streaming
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
            
            # Save complete response
            complete_response = ''.join(response_parts)
            self.save_chat_message("assistant", complete_response)
            
        except Exception as e:
            self.stream_queue.put(('error', str(e)))
        finally:
            self.stream_queue.put(('enable_send', ''))
    
    def save_chat_message(self, role: str, content: str):
        """Save chat message to file"""
        chat_dir = self.settings_manager.settings["paths"]["chat"]
        os.makedirs(chat_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"chat_{timestamp}.txt"
        filepath = os.path.join(chat_dir, filename)
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(f"{role}\n{content}")
        except Exception as e:
            print(f"Error saving chat message: {e}")
    
    def display_message(self, message: str, color: str = None):
        """Display message in chat area"""
        self.chat_display.configure(state="normal")
        self.chat_display.insert("end", f"\n{message}\n")
        self.chat_display.see("end")
        self.chat_display.configure(state="disabled")
    
    def process_queue(self):
        """Process messages from stream queue"""
        try:
            while True:
                try:
                    message = self.stream_queue.get_nowait()
                    
                    if message[0] == 'token':
                        _, content, state = message
                        # Display streaming token
                        self.chat_display.configure(state="normal")
                        if not hasattr(self, '_assistant_started'):
                            self.chat_display.insert("end", "\nAssistant: ")
                            self._assistant_started = True
                        self.chat_display.insert("end", content)
                        self.chat_display.see("end")
                        self.chat_display.configure(state="disabled")
                        
                    elif message[0] == 'finished':
                        self.update_status("Response complete", "#4ECDC4")
                        if hasattr(self, '_assistant_started'):
                            delattr(self, '_assistant_started')
                            
                    elif message[0] == 'metrics_update':
                        self.update_metrics()
                        
                    elif message[0] == 'error':
                        self.display_message(f"Error: {message[1]}", "#FF6B6B")
                        self.update_status("Error occurred", "#FF6B6B")
                        
                    elif message[0] == 'enable_send':
                        self.send_btn.configure(state="normal")
                        
                    elif message[0] == 'status_update':
                        self.update_status(message[1], message[2])
                        
                except queue.Empty:
                    break
                    
        except Exception as e:
            print(f"Error processing queue: {e}")
        
        self.after(50, self.process_queue)
    
    def update_metrics(self):
        """Update performance metrics display"""
        self.kv_label.configure(text=f"KV Cache: {self.metrics.kv_cache_reused} tokens")
        self.prompt_label.configure(text=f"Prompt: {self.metrics.prompt_tokens} tokens")
        self.eval_label.configure(text=f"Generation: {self.metrics.eval_speed:.1f} tok/s")
        self.total_label.configure(text=f"Total: {self.metrics.total_tokens} tokens")
    
    def update_status(self, message: str, color: str = "#4ECDC4"):
        """Update status display"""
        self.status_label.configure(text=message, text_color=color)
    
    def open_settings(self):
        """Open settings dialog"""
        try:
            settings_dialog = SettingsDialog(self, self.settings_manager)
        except Exception as e:
            print(f"Error opening settings: {e}")
    
    def reload_model(self):
        """Reload the LLM model"""
        self.update_status("Reloading model...", "#F39C12")
        threading.Thread(target=self._reload_model_thread, daemon=True).start()
    
    def _reload_model_thread(self):
        """Reload model in separate thread"""
        try:
            self.setup_model()
            self.stream_queue.put(('status_update', 'Model reloaded', '#4ECDC4'))
        except Exception as e:
            self.stream_queue.put(('status_update', f'Model reload failed: {e}', '#FF6B6B'))
    
    def clear_chat(self):
        """Clear chat display"""
        self.chat_display.configure(state="normal")
        self.chat_display.delete("0.0", "end")
        self.chat_display.configure(state="disabled")
        self.update_status("Chat cleared", "#F39C12")

def main():
    """Main entry point - FIXED: Better error handling"""
    print("Starting Professional LLM Interface v4.0...")
    
    # Set environment for Vulkan backend
    os.environ["LLAMA_BACKEND"] = "vulkan"
    
    try:
        # Check CustomTkinter version
        print(f"CustomTkinter version: {ctk.__version__}")
        
        app = ProfessionalLLMInterface()
        print("Application initialized successfully")
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

if __name__ == "__main__":
    main()