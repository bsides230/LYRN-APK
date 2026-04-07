import os
import json
import subprocess
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
QUEUE_FILE = os.path.join(SCRIPT_DIR, "automation", "chunk_queue.json")
CHUNK_ROOT = os.path.join(SCRIPT_DIR, "automation", "queued_chunks")  # universal chunk directory

def build_queue():
    queue = []
    for source_folder in sorted(os.listdir(CHUNK_ROOT)):
        source_path = os.path.join(CHUNK_ROOT, source_folder)
        if not os.path.isdir(source_path):
            continue
        for chunk_file in sorted(os.listdir(source_path)):
            if not chunk_file.endswith(".txt"):
                continue
            full_path = os.path.join(source_path, chunk_file)
            chunk_name = os.path.splitext(chunk_file)[0]
            queue.append({
                "chunk_path": full_path.replace("\\", "/"),
                "source_id": source_folder,
                "chunk_name": chunk_name,
                "processed": False
            })
    return {
        "queue_index": 0,
        "queue": queue
    }

def save_queue(data):
    os.makedirs(os.path.dirname(QUEUE_FILE), exist_ok=True)
    with open(QUEUE_FILE, "w") as f:
        json.dump(data, f, indent=2)

def load_queue():
    if not os.path.exists(QUEUE_FILE):
        print("[🆕] No queue found. Creating one.")
        queue_data = build_queue()
        save_queue(queue_data)
        subprocess.run(["python", "update_chunk_file.py"])
        return None
    with open(QUEUE_FILE, "r") as f:
        return json.load(f)

def main():
    queue_data = load_queue()
    if queue_data is None:
        return

    for i, item in enumerate(queue_data["queue"]):
        if not item["processed"]:
            item["processed"] = True
            item["timestamp_processed"] = datetime.now().isoformat()
            queue_data["queue_index"] = i + 1
            print(f"[✔️] Marked: {item['source_id']}/{item['chunk_name']} as processed.")
            save_queue(queue_data)
            subprocess.run(["python", "update_chunk_file.py"])
            return

    print("[✅] All chunks have been processed.")

if __name__ == "__main__":
    main()
