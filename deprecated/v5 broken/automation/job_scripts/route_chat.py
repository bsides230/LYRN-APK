"""
route_chat.py — Chat job router / recursion loop builder.

This script runs as part of chat_input_job.  Its job is to queue the
chain of processing jobs that will happen between the raw user input and
the final response that gets streamed to the chat module.

--- RECURSION LOOP STRUCTURE ---
Add intermediate job names to PROCESSING_CHAIN to build a pipeline.
The last entry must always be "chat_response_job" — that is the job whose
instructions tell the LLM to emit ##AFFORDANCE: FINAL_OUTPUT_START## when
it is ready to speak to the user.

Example chain with internal reasoning steps:
    PROCESSING_CHAIN = [
        "intent_analysis_job",   # parse & classify the user's intent
        "context_retrieval_job", # pull relevant memory/knowledge
        "draft_response_job",    # draft an answer internally
        "chat_response_job",     # final: streams output to chat module
    ]

For now we go straight to chat_response_job (single-step).
"""

import sys
import json
import time
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Recursion loop definition
# Add intermediate job names here to insert processing steps before the
# final chat_response_job.  Each job must be defined in jobs.json.
# ---------------------------------------------------------------------------
PROCESSING_CHAIN = [
    # "example_analysis_job",   # <- add internal jobs here
    "chat_response_job",        # always last — handles affordance + streaming
]


def _queue_job(queue_path: Path, job_name: str):
    """Append a job entry to the automation queue file."""
    from file_lock import SimpleFileLock

    queue_lock_path = queue_path.with_suffix(f"{queue_path.suffix}.lock")
    new_job = {
        "id": f"job_{int(time.time()*1000)}",
        "name": job_name,
        "priority": 100,
        "when": "now",
        "args": {}
    }

    with SimpleFileLock(queue_lock_path):
        queue_data = []
        if queue_path.exists() and queue_path.stat().st_size > 0:
            with open(queue_path, "r", encoding="utf-8") as f:
                try:
                    queue_data = json.load(f)
                except json.JSONDecodeError:
                    pass

        queue_data.append(new_job)

        temp_path = queue_path.with_suffix(f"{queue_path.suffix}.tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(queue_data, f, indent=2)
        os.replace(temp_path, queue_path)

    print(f"[route_chat] Queued job: {job_name}")


def main():
    print("--- route_chat.py executed ---")
    print(f"[route_chat] CWD: {os.getcwd()}")
    print(f"[route_chat] Processing chain: {PROCESSING_CHAIN}")

    queue_path = Path("automation/job_queue.json")
    print(f"[route_chat] Queue path: {queue_path.resolve()}")
    print(f"[route_chat] Queue exists: {queue_path.exists()}")

    # Queue every job in the processing chain
    for i, job_name in enumerate(PROCESSING_CHAIN):
        print(f"[route_chat] Queuing job {i+1}/{len(PROCESSING_CHAIN)}: '{job_name}'")
        try:
            _queue_job(queue_path, job_name)
        except Exception as e:
            print(f"[route_chat] ERROR: Failed to queue '{job_name}': {e}")
            sys.exit(1)

    # Log the final queue state
    try:
        queue_data = json.loads(queue_path.read_text())
        print(f"[route_chat] Queue now has {len(queue_data)} entry/entries:")
        for entry in queue_data:
            print(f"[route_chat]   - id={entry.get('id')} name={entry.get('name')}")
    except Exception as e:
        print(f"[route_chat] Could not read back queue for verification: {e}")

    print(f"[route_chat] Done — queued {len(PROCESSING_CHAIN)} job(s): {PROCESSING_CHAIN}")
    sys.exit(0)


if __name__ == "__main__":
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
    main()
