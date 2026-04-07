# LYRN-AI Chat Flow — Complete Technical Report

## Overview

This document traces the full lifecycle of a chat message in LYRN-AI, from the moment
the user submits text in the chat UI to the moment the final response is streamed live
to their screen.

The system uses **file-based inter-process communication** (IPC): a FastAPI server
(`start_lyrn.py`) writes trigger files and flag files; a long-running worker process
(`model_runner.py`) watches for those files and drives the LLM; a short-lived background
watcher (`chat_watcher_bg.py`) captures and routes the output.

---

## Architecture at a Glance

```
[Browser / Chat UI]
        |
        | HTTP POST /api/chat
        v
[start_lyrn.py]  ──writes──> jobs/job_input.json
        |                      global_flags/chat_processing.txt
        |
        | automation system reads job queue
        v
[route_chat.py]  ──writes──> automation/job_queue.json
        |                     (queues: chat_response_job)
        |
        | automation system pops chat_response_job, runs scripts[]
        v
[spawn_chat_watcher.py]  ──reads──>  jobs/job_input.json (at spawn time)
        |                ──spawns──> chat_watcher_bg.py  (detached process)
        |
        v
[model_runner.py]  ──reads──>  chat_trigger.txt (from automation)
        |           ──writes──> jobs/job_raw_output.txt (token stream)
        |           ──writes──> global_flags/llm_status.txt
        |           ──writes──> global_flags/final_output_mode.txt (on ##AF:##)
        |
        v
[chat_watcher_bg.py]  ──tails──>  jobs/job_raw_output.txt
        |              ──writes──> global_flags/chat_stream_buffer.txt
        |              ──writes──> chat/chat_TIMESTAMP.txt
        |              ──writes──> global_flags/output_log.jsonl
        |
        v
[start_lyrn.py /api/chat/stream]  ──reads──> chat_stream_buffer.txt
        |
        v
[Browser: SSE stream]  → user sees text appearing live
```

---

## Step-by-Step Flow

### Step 1 — User Submits a Message

The chat module in the browser POSTs to `/api/chat`:

```json
{ "message": "What is recursion?" }
```

**`start_lyrn.py`** handles the request:
1. Writes `jobs/job_input.json`:
   ```json
   { "user_message": "What is recursion?", "source": "chat", "timestamp": "..." }
   ```
2. Creates `global_flags/chat_processing.txt` (lock file — signals "processing in progress").
3. Writes `chat_trigger.txt` pointing at `jobs/job_input.json` so `model_runner.py` picks it up.
4. Returns `{ "status": "processing" }` to the browser.

---

### Step 2 — Automation System Routes the Request

The automation framework reads `chat_trigger.txt` and the job queue.

**`route_chat.py`** is executed as part of `chat_input_job`:
1. Defines a `PROCESSING_CHAIN` list — currently just `["chat_response_job"]`.
2. Appends each job in the chain to `automation/job_queue.json` using `SimpleFileLock`
   (atomic write via a `.tmp` → `os.replace()` pattern).
3. Exits 0.

The `PROCESSING_CHAIN` list is the extension point for multi-step pipelines:
```python
PROCESSING_CHAIN = [
    # "intent_analysis_job",   # add internal jobs here
    "chat_response_job",       # always last — handles affordance + streaming
]
```

---

### Step 3 — Watcher is Spawned (Race Condition Fix)

`chat_response_job` has `"scripts": ["spawn_chat_watcher.py"]`. The automation
system runs that script immediately — **before** the LLM starts generating.

**`spawn_chat_watcher.py`**:
1. Resolves `root_dir` (two levels up from its own location).
2. **Reads `jobs/job_input.json` immediately** and captures `user_message`.
   - This is the race-condition fix: by the time the LLM finishes, the file may
     have been overwritten by a new request. Capturing here ensures the correct
     user message is always attributed to the correct response.
3. Checks whether `global_flags/final_output_mode.txt` already exists
   (indicates recursion — a previous job in the chain set the flag).
4. Spawns `chat_watcher_bg.py` as a fully detached background process:
   - Unix: `subprocess.Popen(..., start_new_session=True)`
   - Windows: `CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS`
   - Stdout/stderr are discarded (the watcher logs to its own stdout which the
     automation system may capture separately).
5. Passes `root_dir` and `user_message` as `argv[1]` and `argv[2]`.
6. Exits 0 immediately — the LLM generation can now proceed in parallel.

---

### Step 4 — LLM Generates the Response

**`model_runner.py`** runs continuously, polling for `chat_trigger.txt`.

When the trigger fires:
1. Reads `jobs/job_input.json` for the prompt.
2. Builds the full context window:
   - System prompt (from `snapshot_loader`)
   - Active dynamic snapshots (from `ds_manager` — includes `chat_response_job` instructions)
   - Chat history (from `chat_manager`)
   - Deltas (from `delta_manager`)
   - **If `global_flags/final_output_mode.txt` exists**: injects a system message:
     `[STATUS: FINAL OUTPUT MODE ACTIVE] Your output is streaming live to the user right now.`
     This is the recursion signal — the model knows it is in final-output mode.
   - Current user message
3. Sets `llm_status.txt` = `"busy"`.
4. Streams tokens from `llm.create_chat_completion(..., stream=True)` and writes
   each token to `jobs/job_raw_output.txt` (flushed immediately).
5. **In-stream affordance detection** (split-token safe):
   - Maintains a rolling `marker_buf` accumulator (2× marker length).
   - When `##AF: FINAL_OUTPUT##` is found in `marker_buf`, immediately writes
     `global_flags/final_output_mode.txt = "active"`.
   - This sets the flag before the watcher's next poll tick — minimising latency.
6. Sets `llm_status.txt` = `"idle"` when done.

The **job instructions** (from `jobs.json` → `chat_response_job`) tell the model:
```
Answer the user's message.

Use this trigger to start your reply:
##AF: FINAL_OUTPUT##

Once you write it, your output is LIVE — the user sees it as you type.
Anything before the trigger is internal only.
```

---

### Step 5 — Watcher Monitors the Output in Real Time

**`chat_watcher_bg.py`** runs concurrently with the LLM (spawned in Step 3).

#### Phase 1: Wait for `job_raw_output.txt`

Polls every 0.5 s until the file appears (timeout: 5 min). Once detected:
- Checks whether `final_output_mode.txt` was **already set** when it started
  (`flag_was_preset`). If yes, this is a recursion generation — stream everything
  from byte 0, no marker needed.
- Clears the stale `chat_stream_buffer.txt` (but NOT `final_output_mode.txt` if
  it was pre-set).

#### Phase 2: Tail the File, Detect the Marker

Polls every 100 ms, tracking a character-position offset into the file:

```
while True:
    read new_content = file[char_pos:]
    char_pos = len(full)

    if new_content and not in_final_output:
        if AFFORDANCE_START in full:
            → set in_final_output = True
            → write final_output_mode.txt
            → write everything after marker → chat_stream_buffer.txt

    elif new_content and in_final_output:
        → append new_content → chat_stream_buffer.txt

    if llm_status in ("idle", "error", "stopped"):
        break
```

**Split-token detection**: because `model_runner.py` also detects the marker and
writes `final_output_mode.txt` immediately in the token stream, the watcher can
also detect the pre-set flag on the next poll even before it sees the complete marker
text in the file. The watcher additionally re-reads the full file and scans for the
complete marker string on every tick, so it handles cases where the marker arrives
slowly across many small tokens.

#### Phase 3: Save Chat History and Cleanup

After the LLM signals `idle`:
1. Reads the full `job_raw_output.txt`.
2. Extracts the final response using `_extract_final_response()`:
   - **Priority 1**: Content after `##AF: FINAL_OUTPUT##` (affordance marker).
   - **Priority 2**: Content between `##Response_START##` and `##Response_END##` (legacy).
   - **Priority 3**: Full raw output as fallback.
3. Writes `chat/chat_YYYYMMDD_HHMMSS_mmm.txt`:
   ```
   user
   What is recursion?

   model
   Recursion is when a function calls itself...
   ```
4. Appends one JSON line to `global_flags/output_log.jsonl` (capped at 100 entries):
   ```json
   {
     "timestamp": "2026-03-24T12:00:00",
     "user_message": "What is recursion?",
     "raw_output": "...<full raw including preamble>...",
     "final_output": "Recursion is when a function calls itself...",
     "marker_detected": true
   }
   ```
5. Deletes `global_flags/chat_processing.txt` (releases the lock).
6. Deletes `global_flags/final_output_mode.txt` (resets flag for next generation).
7. Exits 0.

---

### Step 6 — Browser Receives the Streamed Response

**`start_lyrn.py`** provides two SSE endpoints:

#### `/api/chat/stream` — Post-marker live stream

The browser connects as soon as it gets the `{ "status": "processing" }` response.
The SSE generator:
1. Polls `chat_stream_buffer.txt` at 100 ms intervals, tracking a byte offset.
2. Sends new content as `data: {"text": "..."}\n\n`.
3. Exits when `chat_processing.txt` is gone (generation complete) and no more
   data is pending.
4. Sends `data: {"done": true}\n\n`.

#### `/api/output/raw_stream` — Full raw stream (Output Viewer module)

Same mechanism but tails `job_raw_output.txt` directly — includes the internal
preamble, the affordance marker, and the final response.

---

## Flag File Reference

| File | Written by | Read by | Meaning |
|------|-----------|---------|---------|
| `jobs/job_input.json` | `start_lyrn.py` | `model_runner.py`, `spawn_chat_watcher.py` | Current user message + metadata |
| `jobs/job_raw_output.txt` | `model_runner.py` | `chat_watcher_bg.py`, `/api/output/raw_stream` | Token stream from LLM |
| `global_flags/llm_status.txt` | `model_runner.py` | `chat_watcher_bg.py` | `idle` / `busy` / `error` / `stopped` |
| `global_flags/chat_processing.txt` | `start_lyrn.py` | `start_lyrn.py`, `chat_watcher_bg.py` | Lock: processing in flight |
| `global_flags/final_output_mode.txt` | `model_runner.py`, `chat_watcher_bg.py` | `model_runner.py`, `chat_watcher_bg.py` | Affordance marker has fired |
| `global_flags/chat_stream_buffer.txt` | `chat_watcher_bg.py` | `/api/chat/stream` | Post-marker tokens for live stream |
| `global_flags/output_log.jsonl` | `chat_watcher_bg.py` | `/api/output/log`, Output Viewer | Per-generation history log |
| `chat/chat_*.txt` | `chat_watcher_bg.py` | `chat_manager.py` | Persistent chat history |
| `automation/job_queue.json` | `route_chat.py` | automation system | Pending jobs |
| `chat_trigger.txt` | automation system | `model_runner.py` | Path to input file to process |

---

## Affordance System Detail

### Why It Exists

The model generates two types of content in a single generation:
- **Internal reasoning / thinking** — should NOT be shown to the user.
- **Final user-visible response** — should be streamed live.

The affordance marker `##AF: FINAL_OUTPUT##` is the boundary between them.

### How It Works End-to-End

```
model_runner token stream:
  "Let me think... " → raw_output_file
  "Considering options... " → raw_output_file
  "##AF: FINAL_OUTPUT" → rolling marker_buf detects complete marker
                        → writes final_output_mode.txt = "active"  ← IMMEDIATELY
  "##\n" → token stream continues
  "The answer is 42." → raw_output_file

chat_watcher_bg (polling at 100ms):
  poll tick N:   reads "Let me think... Considering options..."
                 → AFFORDANCE_START not in full → skip
  poll tick N+1: reads "...##AF: FINAL_OUTPUT##\nThe answer is 42."
                 → AFFORDANCE_START in full → set in_final_output = True
                 → write "The answer is 42." → chat_stream_buffer.txt

/api/chat/stream SSE:
  tick M:   reads "The answer is 42." from buffer → sends to browser
  tick M+1: LLM idle, processing lock gone → sends {"done": true}
```

### Recursion Loop

If a job earlier in `PROCESSING_CHAIN` emits `##AF: FINAL_OUTPUT##`, the flag is
set before the final job runs. The next watcher instance sees `flag_was_preset = True`
and streams from byte 0 without needing a marker:

```
PROCESSING_CHAIN = ["analysis_job", "chat_response_job"]

analysis_job generation:
  "Analysis complete. ##AF: FINAL_OUTPUT##"
  → final_output_mode.txt written

chat_response_job generation (next):
  spawn_chat_watcher sees flag already set
  → in_final_output = True from the start
  → streams ALL tokens to chat_stream_buffer.txt
```

---

## Error Handling

| Scenario | What happens |
|----------|-------------|
| LLM times out (>30 min) | Watcher breaks loop, still saves partial output and cleans flags |
| No output file appears (>5 min) | Watcher cleans `chat_processing.txt` lock and exits 1 |
| No affordance marker emitted | `_extract_final_response()` falls back to full raw output |
| Empty LLM response | Watcher skips chat history save, cleans flags, exits 0 |
| `job_input.json` overwritten by new request | Race condition avoided — user_message captured at spawn time |
| Marker split across tokens | Watcher re-scans full file content on each tick; model_runner uses rolling buffer |

---

## Test Coverage (82 assertions, 0 model required)

| Test | Validates |
|------|-----------|
| 1 | `route_chat.py` queues `chat_response_job` |
| 2 | `spawn_chat_watcher.py` captures user_message at spawn time |
| 3 | Affordance marker detected, stream buffer written, history saved (no preamble in output) |
| 4 | Legacy fallback — full output saved when no marker present |
| 5 | Race condition fix — pre-captured user_message wins over overwritten `job_input.json` |
| 6 | Full chain integration: route → spawn → mock LLM → history |
| 7 | Legacy `##Response_START##` / `##Response_END##` markers still work |
| 8 | Recursion — flag pre-set, watcher streams from byte 0 without marker |
| 9 | Split-token affordance marker (6 fragments) still detected correctly |
| 10 | `output_log.jsonl` has all required fields with correct values |
| 11 | Empty LLM output: no crash, no history file, lock cleared |
| 12 | Marker at very start of output (no preamble): response saved, marker stripped from history |
| 13 | All Phase 1/2/3 debug messages present in watcher stdout |

Run with:
```bash
python tests/test_chat_flow.py
```
