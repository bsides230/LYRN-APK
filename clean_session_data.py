import os
import shutil
import json
from pathlib import Path

def clean_directory(path, pattern="*"):
    """Deletes files matching pattern in path, or subdirectories if pattern is empty."""
    p = Path(path)
    if not p.exists():
        return

    print(f"Cleaning {path}...")

    # Delete files
    if pattern:
        for f in p.glob(pattern):
            try:
                if f.is_file():
                    f.unlink()
                    print(f"  Deleted: {f.name}")
            except Exception as e:
                print(f"  Error deleting {f.name}: {e}")
    else:
        # Recursive delete subdirs
         for item in p.iterdir():
            if item.is_dir():
                try:
                    shutil.rmtree(item)
                    print(f"  Deleted dir: {item.name}")
                except Exception as e:
                    print(f"  Error deleting dir {item.name}: {e}")

def main():
    print("--- LYRN Session Cleanup ---")

    # 1. Chat History
    clean_directory("chat", "*.txt")

    # 2. Job Output
    clean_directory("jobs", "*.txt")

    # 3. Logs (Sessions)
    clean_directory("logs", "") # Clears all subdirectories/files in logs?
    # Actually, we want to clear session_* folders, but keep backend.log maybe?
    # Backend log is usually in root or not rotated properly.
    # The logger uses logs/session_*. Let's clear those.
    # Pattern matching for dirs is tricky with glob("session_*") on iterdir
    log_dir = Path("logs")
    if log_dir.exists():
        print("Cleaning logs/...")
        for item in log_dir.iterdir():
            if item.is_dir() and item.name.startswith("session_"):
                try:
                    shutil.rmtree(item)
                    print(f"  Deleted session: {item.name}")
                except Exception as e:
                    print(f"  Error deleting {item.name}: {e}")

    # 4. Automation History
    hist_path = Path("automation/job_history.json")
    if hist_path.exists():
        try:
            with open(hist_path, 'w', encoding='utf-8') as f:
                json.dump([], f)
            print("Reset automation/job_history.json")
        except Exception as e:
            print(f"Error resetting history: {e}")

    # 5. Global Flags
    flags = ["llm_stats.json", "last_error.txt", "llm_status.txt"]
    for flag in flags:
        p = Path(f"global_flags/{flag}")
        if p.exists():
            try:
                p.unlink()
                print(f"Deleted {p}")
            except Exception as e:
                print(f"Error deleting {p}: {e}")

    # 6. Chat Trigger
    if os.path.exists("chat_trigger.txt"):
        try:
            os.remove("chat_trigger.txt")
            print("Deleted chat_trigger.txt")
        except: pass

    print("--- Cleanup Complete ---")

if __name__ == "__main__":
    main()
