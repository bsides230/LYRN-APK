# Rebuild Notes — Model Execution Path

## Files Changed

### 1. `model_runner.py`
**Why changed:** Core of the rebuild. The model runner was writing output to the same file as input and receiving job instructions (not user text) as the "user" message.

**New role:** Reads structured input from `jobs/job_input.json`, builds correct LLM context with user message as the user turn, writes raw generation output to a **separate** intermediate file (`jobs/job_raw_output.txt`). Never writes to the input file. Never formats output for chat display.

**Logic restored from deprecated runner:** Context assembly order (system → history → deltas → user) was already correct in both versions. The deprecated runner's clean separation of concerns (read → process → write) was the guiding principle, though the actual code is new.

**Old behavior intentionally NOT restored:** The deprecated runner also wrote to the input file (same problem as current). That behavior was not restored. The deprecated runner also lacked DSManager — the current DSManager integration is kept.

### 2. `start_lyrn.py`
**Why changed:** `trigger_chat_generation()` wrote job instructions as the user message. `chat_endpoint()` used dynamic snapshots as the input transport mechanism. `_monitor_job_completion()` watched the wrong file.

**New role:**
- `chat_endpoint()`: Writes structured JSON input (`jobs/job_input.json`) with the actual user message, source type, and timestamp. No longer saves to dynamic snapshot.
- `trigger_chat_generation()`: For jobs, reads existing input JSON (from chat_endpoint), merges job instructions, clears stale raw output, writes trigger.
- `_monitor_job_completion()`: Monitors `jobs/job_raw_output.txt` for completion instead of the old combined file.

**Logic restored from deprecated runner:** N/A — these functions are server-side, not part of the model runner.

**Old behavior intentionally NOT restored:** Dynamic snapshot-based chat input transport was removed for the chat flow. It added unnecessary indirection (user text in snapshot → system message → model must "find" it).

### 3. `automation/job_scripts/chat_watcher_bg.py`
**Why changed:** Was reading from `jobs/job_model_output.txt` which mixed input and output. Marker extraction fallback grabbed the entire file including user input prefix.

**New role:** The authoritative capture layer. Reads raw model output from `jobs/job_raw_output.txt` (contains ONLY model generation). Reads user input from `jobs/job_input.json`. Writes final `user\n{input}\n\nmodel\n{response}` to `chat/chat_*.txt`. Clears processing lock. This is the ONLY path that writes to the chat-visible directory.

**Logic restored from deprecated runner:** N/A — the watcher is not part of the model runner.

**Old behavior intentionally NOT restored:** The snapshot-active-file cleanup (`chat_input_context.active`) was removed since we no longer use dynamic snapshots for chat input transport.

### 4. `automation/jobs/jobs.json`
**Why changed:** `chat_response_job` instructions required the model to use `##Response_START##`/`##Response_END##` markers. This was unreliable with small models and consumed prompt tokens on meta-instructions.

**New role:** Simplified instructions that guide natural response behavior without requiring markers.

**Logic restored from deprecated runner:** N/A.

**Old behavior intentionally NOT restored:** Mandatory marker requirement removed. Marker extraction still works if the model happens to use them, but is no longer required for correct operation.

## Assumptions Made

1. **All chat flows go through the job system.** There is no direct chat-to-model path that bypasses jobs. This was already true before the rebuild.

2. **`jobs/job_input.json` is written before the job triggers model execution.** The timing is guaranteed by the job chain: chat_endpoint writes the JSON → chat_input_job runs route_chat.py → chat_response_job triggers model. The JSON exists before trigger_chat_generation merges instructions into it.

3. **Only one chat job runs at a time.** The `chat_processing.txt` lock prevents concurrent chat processing. This means `jobs/job_input.json` and `jobs/job_raw_output.txt` are not contested by multiple jobs simultaneously.

4. **Non-chat jobs (automation jobs with instructions but no chat_endpoint call) still work.** When `trigger_chat_generation` is called for a job that didn't go through `chat_endpoint`, no `job_input.json` exists yet. The function creates one with the job instructions as both `user_message` and `job_instructions`, with source="job". This preserves backward compatibility.

5. **The model runner supports both JSON and legacy text input formats.** Legacy triggers (if any exist outside the job system) continue to work through the text-format fallback in `_read_input_payload()`.
