import os
import json
import shutil

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
QUEUE_FILE = os.path.join(SCRIPT_DIR, "automation", "chunk_queue.json")
CHUNK_OUTPUT_PATH = os.path.join(SCRIPT_DIR, "active_chunk", "chunk.txt")

def update_chunk_file():
    if not os.path.exists(QUEUE_FILE):
        print("[❌] Cannot find queue file.")
        return

    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    index = data.get("queue_index", 0)
    queue = data.get("queue", [])

    if index >= len(queue):
        print("[🏁] No more chunks to load.")
        return

    chunk_path = queue[index]["chunk_path"]

    if not os.path.exists(chunk_path):
        print(f"[❌] Missing chunk file: {chunk_path}")
        return

    os.makedirs(os.path.dirname(CHUNK_OUTPUT_PATH), exist_ok=True)
    shutil.copyfile(chunk_path, CHUNK_OUTPUT_PATH)

    print(f"[📥] Loaded chunk: {queue[index]['source_id']}")

if __name__ == "__main__":
    update_chunk_file()
