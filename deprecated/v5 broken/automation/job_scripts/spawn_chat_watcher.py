import sys
import subprocess
import os
import json


def main():
    print("--- spawn_chat_watcher.py executed ---")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    watcher_script = os.path.join(script_dir, "chat_watcher_bg.py")
    root_dir = os.path.abspath(os.path.join(script_dir, '../..'))

    print(f"[spawn] script_dir:     {script_dir}")
    print(f"[spawn] watcher_script: {watcher_script}")
    print(f"[spawn] root_dir:       {root_dir}")
    print(f"[spawn] watcher exists: {os.path.exists(watcher_script)}")

    # Clear any stale final_output_mode.txt BEFORE spawning the new watcher.
    # A stale flag (from a crashed or incomplete previous generation) would cause
    # the new watcher to start in "recursion mode" (flag_was_preset=True), bypassing
    # affordance detection and streaming everything as final output.
    # Each new chat request must start fresh.
    final_output_flag = os.path.join(root_dir, "global_flags", "final_output_mode.txt")
    if os.path.exists(final_output_flag):
        print(f"[spawn] Clearing stale final_output_mode.txt before spawning watcher.")
        try:
            os.remove(final_output_flag)
            print(f"[spawn] Stale final_output_mode.txt removed — affordance detection will be fresh.")
        except Exception as e:
            print(f"[spawn] Warning: could not clear stale final_output_mode.txt: {e}")
    else:
        print(f"[spawn] final_output_mode.txt not set — normal affordance detection mode.")

    # Capture user_message NOW before job_input.json can be overwritten by the next request.
    # This prevents the race condition where the watcher reads a stale/new user_message
    # from job_input.json after LLM generation finishes.
    user_message = ""
    job_input_path = os.path.join(root_dir, "jobs", "job_input.json")
    print(f"[spawn] Reading user_message from: {job_input_path}")
    try:
        with open(job_input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            user_message = data.get("user_message", "")
        print(f"[spawn] Captured user_message at spawn time: {user_message[:60]}...")
        print(f"[spawn] user_message length: {len(user_message)} chars")
    except Exception as e:
        print(f"[spawn] WARNING: could not read user_message from job_input.json: {e}")
        print(f"[spawn] Watcher will fall back to job_input.json at completion time (race risk)")

    cmd = [sys.executable, watcher_script, root_dir, user_message]
    print(f"[spawn] Spawning command: {sys.executable} chat_watcher_bg.py <root_dir> <user_msg[{len(user_message)}c]>")
    print(f"[spawn] Platform: {os.name}")

    if os.name == 'nt':
        subprocess.Popen(
            cmd,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    else:
        subprocess.Popen(
            cmd,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

    print("[spawn] Background watcher process launched successfully.")
    print("Spawned background watcher.")
    sys.exit(0)


if __name__ == "__main__":
    main()
