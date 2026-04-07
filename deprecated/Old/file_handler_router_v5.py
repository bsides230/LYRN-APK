import os
import re
import json
import shutil
import subprocess
from datetime import datetime

# --- Absolute path to script folder ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(SCRIPT_DIR, "settings.json")

# --- Default fallback paths ---
DEFAULTS = {
    "automation_flag_path": os.path.join(SCRIPT_DIR, "global_flags", "automation.txt"),
    "chunk_queue_path": os.path.join(SCRIPT_DIR, "chunk_queue.json"),
    "chat_dir": os.path.join(SCRIPT_DIR, "chat"),
    "chat_parsed_dir": os.path.join(SCRIPT_DIR, "chat_parsed"),
    "audit_dir": os.path.join(SCRIPT_DIR, "job_audit")
}

EXPECTED_JOB_COUNT = 3  # ✅ Number of jobs to process per chunk before advancing

# --- Load settings.json or use defaults ---
def load_settings():
    if not os.path.exists(SETTINGS_PATH):
        print("[⚠️] settings.json not found. Using default paths.")
        return DEFAULTS
    
    with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    
    for key, val in DEFAULTS.items():
        if key not in loaded:
            loaded[key] = val
        if not os.path.isabs(loaded[key]):
            loaded[key] = os.path.join(SCRIPT_DIR, loaded[key])
    
    return loaded

# --- Determine automation mode ---
def get_automation_mode(flag_path):
    if not os.path.exists(flag_path):
        return "off"
    
    with open(flag_path, "r", encoding="utf-8") as f:
        return f.read().strip().lower()

# --- Extract all trigger blocks like ###NAME_START### ... ###NAME_END### ---
def extract_triggers(content):
    pattern = r"###(\w+)_START###(.*?)###\1_END###"
    return re.findall(pattern, content, re.DOTALL)

# --- Save trigger blocks into their folders ---
def save_trigger_blocks(trigger_blocks, prefix, base_dir):
    for name, content in trigger_blocks:
        folder = os.path.join(base_dir, name)
        os.makedirs(folder, exist_ok=True)
        
        with open(os.path.join(folder, f"{prefix}.txt"), "w", encoding="utf-8") as f:
            f.write(content.strip())

# --- Set next job flag ---
def set_next_job_flag(state):
    """Set the next job flag to true or false"""
    next_job_path = os.path.join(SCRIPT_DIR, "global_flags", "next_job.txt")
    os.makedirs(os.path.dirname(next_job_path), exist_ok=True)
    
    try:
        with open(next_job_path, "w", encoding="utf-8") as f:
            f.write(state)
        print(f"[🔄] Next job flag set to: {state}")
    except Exception as e:
        print(f"[⚠️] Error setting next job flag: {e}")

# --- Automated Mode: Process files for the current chunk only ---
def process_automated(chat_dir, audit_dir, queue_path):
    # 🔒 IMMEDIATELY clear the trigger at the start
    print("[🔒] Resetting next job trigger...")
    set_next_job_flag("false")
    
    if not os.path.exists(queue_path):
        print("[💥] Missing chunk_queue.json")
        return

    with open(queue_path, "r", encoding="utf-8") as f:
        queue_data = json.load(f)

    queue_index = queue_data.get("queue_index", 0)
    queue = queue_data.get("queue", [])

    if queue_index >= len(queue):
        print("[✅] All chunks processed.")
        return

    current_chunk = queue[queue_index]
    current_chunk_file = os.path.basename(current_chunk["chunk_path"]).replace(".txt", "")
    matched_files = []

    for chat_file in os.listdir(chat_dir):
        if current_chunk_file not in chat_file:
            continue

        chat_path = os.path.join(chat_dir, chat_file)
        
        with open(chat_path, "r", encoding="utf-8") as f:
            content = f.read()

        job_name = os.path.splitext(chat_file)[0]
        prefix = f"{current_chunk['chunk_name']}_{job_name}"

        os.makedirs(audit_dir, exist_ok=True)
        shutil.copyfile(chat_path, os.path.join(audit_dir, f"{prefix}.txt"))

        triggers = extract_triggers(content)
        save_trigger_blocks(triggers, prefix, SCRIPT_DIR)

        os.remove(chat_path)
        print(f"[🗑️] Routed and deleted: {chat_file}")
        matched_files.append(chat_file)

    # ✅ Check if all expected jobs are matched - signal ready for next job
    if len(matched_files) >= EXPECTED_JOB_COUNT:
        print("[⏭️] All jobs processed — advancing chunk queue...")
        subprocess.run(["python", "chunk_queue_v5.py"])
        
        # ✅ Signal that the system is ready for the next job
        print("[✅] All expected jobs matched - setting next job flag to true")
        set_next_job_flag("true")
    else:
        print(f"[⏳] Waiting for remaining jobs: {len(matched_files)}/{EXPECTED_JOB_COUNT}")
        # Keep flag as false - not ready for next job yet
        set_next_job_flag("false")

# --- Manual Mode: Process only the newest chat file ---
def process_manual(chat_dir, parsed_dir):
    # In manual mode, we don't need to coordinate with job automation
    # But we'll still manage the flag for consistency
    set_next_job_flag("true")  # Manual mode is always ready
    
    chat_files = sorted(
        os.listdir(chat_dir),
        key=lambda x: os.path.getmtime(os.path.join(chat_dir, x))
    )

    if not chat_files:
        print("[ℹ️] No chat files to process.")
        return

    latest = chat_files[-1]
    chat_path = os.path.join(chat_dir, latest)

    with open(chat_path, "r", encoding="utf-8") as f:
        content = f.read()

    input_text = content.split("<thinking>")[0]
    think_match = re.search(r"<thinking>(.*?)</thinking>", content, re.DOTALL)
    output_text = content.split("</thinking>")[-1] if "</thinking>" in content else ""
    thinking_text = think_match.group(1).strip() if think_match else ""

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(parsed_dir, timestamp)
    os.makedirs(out_dir, exist_ok=True)

    with open(os.path.join(out_dir, "input.txt"), "w", encoding="utf-8") as f:
        f.write(input_text.strip())

    with open(os.path.join(out_dir, "thinking.txt"), "w", encoding="utf-8") as f:
        f.write(thinking_text)

    with open(os.path.join(out_dir, "output.txt"), "w", encoding="utf-8") as f:
        f.write(output_text.strip())

    all_text = thinking_text + "\n" + output_text
    triggers = extract_triggers(all_text)
    save_trigger_blocks(triggers, timestamp, SCRIPT_DIR)

    print(f"[✅] Manual parse complete for: {latest}")

# --- Main Entry ---
def main():
    settings = load_settings()
    mode = get_automation_mode(settings["automation_flag_path"])

    if mode == "on":
        print("[🤖] Running in automated mode...")
        process_automated(settings["chat_dir"], settings["audit_dir"], settings["chunk_queue_path"])
    else:
        print("[👤] Running in manual mode...")
        process_manual(settings["chat_dir"], settings["chat_parsed_dir"])

if __name__ == "__main__":
    main()