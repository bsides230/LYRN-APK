"""
chat_watcher_bg.py - Background chat output watcher with affordance support.

Runs as a detached background process spawned by spawn_chat_watcher.py.
Responsibilities:
  1. Wait for the raw output file to appear (model started generating).
  2. Tail the file in real-time, scanning for affordance markers.
     - Thinking blocks (<think>...</think>) are EXCLUDED from affordance detection.
       The wizard only triggers on regular (non-thinking) output.
  3. When ##AF: FINAL_OUTPUT## is detected in non-thinking text:
       - Set global_flags/final_output_mode.txt
       - Write subsequent tokens (post-marker, thinking stripped) to
         global_flags/chat_stream_buffer.txt so the SSE endpoint can forward
         them live to the chat module.
  4. Once LLM status returns to idle/stopped/error:
       - Extract the final response (post-marker content, thinking stripped).
       - Save user/model pair to chat history (for LLM context).
       - Save clean chat pair to output_history/ (audit log, never seen by LLM).
       - Clean up all processing flags.

Affordance marker: ##AF: FINAL_OUTPUT##
Thinking tags:     <think>...</think>  — excluded from wizard + final output
"""

import sys
import os
import time
import re
import json
from pathlib import Path


AFFORDANCE_START     = "##AF: FINAL_OUTPUT##"
POLL_INTERVAL_STREAM = 0.1   # seconds between read ticks while streaming
POLL_INTERVAL_WAIT   = 0.5   # seconds between ticks while waiting for file to appear
TIMEOUT_WAIT_FILE    = 300   # 5 min: max wait for raw output file to appear
TIMEOUT_GENERATION   = 1800  # 30 min: max total generation time


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_llm_status(llm_status_path: str) -> str:
    try:
        with open(llm_status_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return "idle"
    except Exception as e:
        print(f"[Watcher] Error reading LLM status: {e}")
        return "idle"  # assume done if unreadable


def _strip_thinking(text: str) -> str:
    """Remove all <think>...</think> blocks from text (case-insensitive tags)."""
    return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL | re.IGNORECASE)


def _append_stream_buffer(stream_buffer_file: str, content: str):
    """Append tokens to the live chat stream buffer."""
    try:
        os.makedirs(os.path.dirname(stream_buffer_file), exist_ok=True)
        with open(stream_buffer_file, "a", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"[Watcher] Error writing to stream buffer: {e}")


def _extract_final_response(raw_text: str) -> str | None:
    """
    Extract the user-visible response from raw model output.

    Priority:
      1. Content after ##AF: FINAL_OUTPUT## (thinking stripped from both sides)
      2. Content between ##Response_START## / ##Response_END## (legacy markers)
      3. Full raw output, thinking stripped, as last-resort fallback

    Thinking blocks (<think>...</think>) are always removed from the result
    before it is saved to chat history or shown to the user.
    """
    raw_text = raw_text.strip()
    if not raw_text:
        return None

    # 1. Affordance-based extraction
    if AFFORDANCE_START in raw_text:
        after = raw_text.split(AFFORDANCE_START, 1)[1]
        # Strip thinking from final output — model may still think after the marker
        after = _strip_thinking(after).strip()
        print("[Watcher] Extracted response using AFFORDANCE marker (thinking stripped).")
        return after  # Return immediately, even if empty

    # 2. Legacy marker extraction
    start_m = "##Response_START##"
    end_m   = "##Response_END##"
    if start_m in raw_text and end_m in raw_text:
        match = re.search(f"{start_m}(.*?){end_m}", raw_text, re.DOTALL)
        if match:
            extracted = _strip_thinking(match.group(1)).strip()
            print("[Watcher] Extracted response using legacy markers (thinking stripped).")
            return extracted  # Return immediately, even if empty

    # 3. Fallback: full raw output with thinking stripped
    clean = _strip_thinking(raw_text).strip()
    if clean:
        print("[Watcher] Using thinking-stripped raw output as response (no markers found).")
        return clean

    # 4. Absolute fallback: raw output as-is
    print("[Watcher] Using full raw output as response (thinking strip yielded nothing).")
    return raw_text.strip()


def _save_chat_history(root_dir: str, user_input: str, model_response: str):
    """
    Write the user/model exchange to a timestamped file in chat/.
    This file IS read by the LLM as conversation context on future turns.
    """
    try:
        chat_dir = os.path.join(root_dir, "chat")
        os.makedirs(chat_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S_") + str(int(time.time() * 1000) % 1000)
        filepath = os.path.join(chat_dir, f"chat_{timestamp}.txt")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"user\n{user_input}\n\nmodel\n{model_response}\n")
        print(f"[Watcher] Saved chat history to {filepath}")
    except Exception as e:
        print(f"[Watcher] Error saving chat history: {e}")


def _save_output_history(root_dir: str, user_message: str, response: str):
    """
    Write a clean chat pair to output_history/ as a user-visible audit log.
    This folder is NEVER read by the LLM and NEVER cleared by chat history operations.
    Each file contains one complete exchange: the user's message + the clean final response.
    """
    try:
        hist_dir = os.path.join(root_dir, "output_history")
        os.makedirs(hist_dir, exist_ok=True)
        timestamp = time.strftime("%Y-%m-%dT%H-%M-%S") + f"_{int(time.time() * 1000) % 1000:03d}"
        filepath = os.path.join(hist_dir, f"{timestamp}.json")
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "user_message": user_message,
            "response": response,
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(entry, f, indent=2, ensure_ascii=False)
        print(f"[Watcher] Saved output history to {filepath}")
    except Exception as e:
        print(f"[Watcher] Error saving output history: {e}")


def _append_output_log(root_dir: str, user_message: str, raw_output: str,
                       final_output: str, marker_detected: bool):
    """Append one generation record to global_flags/output_log.jsonl (legacy log)."""
    MAX_ENTRIES = 100
    try:
        log_path = os.path.join(root_dir, "global_flags", "output_log.jsonl")
        entry = json.dumps({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "user_message": user_message,
            "raw_output": raw_output,
            "final_output": final_output or "",
            "marker_detected": marker_detected,
        })
        lines = []
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                lines = [l for l in f.read().splitlines() if l.strip()]
        except FileNotFoundError:
            pass
        lines.append(entry)
        if len(lines) > MAX_ENTRIES:
            lines = lines[-MAX_ENTRIES:]
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception as e:
        print(f"[Watcher] Error writing output log: {e}")


def _get_user_message_from_json(root_dir: str) -> str | None:
    """Fallback: read user_message from job_input.json (may be stale)."""
    try:
        path = os.path.join(root_dir, "jobs", "job_input.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("user_message", "").strip() or None
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"[Watcher] Error reading job_input.json: {e}")
    return None


def _cleanup_flags(*flag_paths):
    for path in flag_paths:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception as e:
            print(f"[Watcher] Error clearing flag {path}: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("[Watcher] Missing root directory argument.")
        sys.exit(1)

    root_dir = sys.argv[1]

    # User message captured at spawn time to avoid the race condition where
    # job_input.json is overwritten before the watcher reads it.
    user_message_arg = sys.argv[2] if len(sys.argv) > 2 else None

    raw_output_file  = os.path.join(root_dir, "jobs", "job_raw_output.txt")
    completion_file  = os.path.join(root_dir, "jobs", "job_completion.json")
    lock_file        = os.path.join(root_dir, "global_flags", "chat_processing.txt")
    llm_status_path  = os.path.join(root_dir, "global_flags", "llm_status.txt")
    final_output_flag= os.path.join(root_dir, "global_flags", "final_output_mode.txt")
    stream_buffer    = os.path.join(root_dir, "global_flags", "chat_stream_buffer.txt")

    print(f"[Watcher] === chat_watcher_bg.py starting ===")
    print(f"[Watcher] PID: {os.getpid()}")
    print(f"[Watcher] root_dir:          {root_dir}")
    print(f"[Watcher] raw_output_file:   {raw_output_file}")
    print(f"[Watcher] completion_file:   {completion_file}")
    print(f"[Watcher] lock_file:         {lock_file}")
    print(f"[Watcher] llm_status_path:   {llm_status_path}")
    print(f"[Watcher] final_output_flag: {final_output_flag}")
    print(f"[Watcher] stream_buffer:     {stream_buffer}")
    print(f"[Watcher] user_message_arg:  {repr(user_message_arg[:60]) if user_message_arg else None}")
    print(f"[Watcher] affordance_marker: {repr(AFFORDANCE_START)}")
    print(f"[Watcher] Watching {raw_output_file} for raw model output...")

    global_start = time.time()

    # -----------------------------------------------------------------------
    # Phase 1: Wait for the raw output file to appear
    # -----------------------------------------------------------------------
    print(f"[Watcher] Phase 1: Waiting for output file to appear (timeout={TIMEOUT_WAIT_FILE}s)...")
    wait_ticks = 0
    while not os.path.exists(raw_output_file):
        elapsed = time.time() - global_start
        if elapsed > TIMEOUT_WAIT_FILE:
            print(f"[Watcher] Phase 1: TIMED OUT after {elapsed:.1f}s waiting for output file.")
            _cleanup_flags(lock_file)
            sys.exit(1)
        wait_ticks += 1
        if wait_ticks % 10 == 0:  # log every ~5s
            print(f"[Watcher] Phase 1: Still waiting... {elapsed:.1f}s elapsed")
        time.sleep(POLL_INTERVAL_WAIT)

    print(f"[Watcher] Phase 1: Output file appeared after {time.time()-global_start:.2f}s")

    # spawn_chat_watcher.py now clears any stale final_output_mode.txt before
    # spawning us, so flag_was_preset should always be False for normal chat flow.
    # We keep the check for safety (e.g. direct invocations or edge cases).
    flag_was_preset = os.path.exists(final_output_flag)
    print(f"[Watcher] Phase 1: final_output_mode.txt pre-set: {flag_was_preset}")

    # Clear stale stream buffer; always clear the flag too (spawn clears it, but be safe).
    _cleanup_flags(stream_buffer)
    if not flag_was_preset:
        _cleanup_flags(final_output_flag)

    if flag_was_preset:
        print("[Watcher] FINAL OUTPUT flag was pre-set — streaming everything from start.")
    else:
        print("[Watcher] Output file detected. Starting real-time affordance monitoring...")

    # -----------------------------------------------------------------------
    # Phase 2: Tail the file, detect affordance marker, stream to buffer
    # -----------------------------------------------------------------------
    print(f"[Watcher] Phase 2: Starting tail loop (poll={POLL_INTERVAL_STREAM}s, timeout={TIMEOUT_GENERATION}s)")
    char_pos        = 0               # character offset read so far
    in_final_output = flag_was_preset  # already live if flag was pre-set

    total_chars_read    = 0
    total_buffer_chars  = 0
    poll_count = 0
    marker_seen_this_run = False

    while True:
        elapsed = time.time() - global_start
        if elapsed > TIMEOUT_GENERATION:
            print(f"[Watcher] Phase 2: TIMED OUT after {elapsed:.1f}s during generation monitoring.")
            break

        poll_count += 1

        # --- Read new content from file (by character position) ---
        new_content = ""
        full = ""
        try:
            with open(raw_output_file, "r", encoding="utf-8", errors="replace") as f:
                full = f.read()
            if len(full) > char_pos:
                new_content = full[char_pos:]
                char_pos = len(full)
                total_chars_read += len(new_content)
        except Exception as e:
            if poll_count == 1:
                print(f"[Watcher] Phase 2: Error reading output file: {e}")

        if new_content:
            print(f"[Watcher] Phase 2: +{len(new_content)} chars (total={total_chars_read}, "
                  f"in_final_output={in_final_output})")
            if not in_final_output:
                # Strip thinking blocks BEFORE checking for the affordance marker.
                # The wizard should not trigger on markers embedded in thinking text.
                text_for_detection = _strip_thinking(full)

                # Find all affordances: ##AF: (.*?)##
                affordances = re.findall(r"##AF:\s*(.*?)\s*##", text_for_detection)
                if affordances:
                    # Check for FINAL_OUTPUT first to preserve exact legacy behavior
                    if "FINAL_OUTPUT" in affordances:
                        marker_pos = text_for_detection.index(AFFORDANCE_START)
                        print(f"[Watcher] Phase 2: ##AF: FINAL_OUTPUT## detected (non-thinking) at "
                              f"stripped-char {marker_pos} — triggering final output job.")
                        marker_seen_this_run = True
                    else:
                        # Non-final affordance detected
                        import csv
                        # Just grab the first non-final affordance found in this pass
                        affordance_name = affordances[0]
                        print(f"[Watcher] Detected affordance: {affordance_name}")

                        jobs_csv_path = os.path.join(root_dir, "automation", "jobs.csv")
                        sequence = None
                        if os.path.exists(jobs_csv_path):
                            try:
                                with open(jobs_csv_path, "r", encoding="utf-8", newline="") as csvf:
                                    reader = csv.DictReader(csvf)
                                    for row in reader:
                                        if row.get("Trigger", "").strip() == affordance_name:
                                            sequence = row.get("Sequence", "").strip()
                                            break
                            except Exception as e:
                                print(f"[Watcher] Error reading jobs.csv: {e}")

                        if sequence:
                            print(f"[Watcher] Found sequence for {affordance_name}: {sequence}")
                            try:
                                # Import execute_sequence dynamically to avoid circular issues
                                sys.path.append(os.path.join(root_dir, "automation"))
                                from sequence_executor import execute_sequence
                                execute_sequence(sequence)
                                # Clean up flag to prevent looping, or exit if needed
                            except Exception as e:
                                print(f"[Watcher] Error executing sequence: {e}")
                        else:
                            print(f"[Watcher] Error: Affordance '{affordance_name}' not found in jobs.csv trigger column.")

                        # To prevent re-triggering the same affordance multiple times in the loop,
                        # we either need to clear it or assume the LLM will stop.
                        # For now, we will mark marker_seen_this_run to true and exit the loop,
                        # allowing phase 3 cleanup to run.
                        marker_seen_this_run = True
                        break
            else:
                # Already past the marker — stream new content (thinking stripped) to buffer
                clean_new = _strip_thinking(new_content)
                if clean_new:
                    _append_stream_buffer(stream_buffer, clean_new)
                    total_buffer_chars += len(clean_new)

        # --- Explicit Completion Handoff ---
        # Instead of guessing Phase 1 or Job completion via sleeps and status,
        # we wait for the explicit completion artifact emitted by the runner.
        if os.path.exists(completion_file):
            # Parse and validate completion artifact
            try:
                # Add a small delay to ensure file is fully written before reading
                time.sleep(0.1)
                with open(completion_file, 'r', encoding='utf-8') as f:
                    completion_data = json.load(f)

                # Check required fields
                if isinstance(completion_data, dict) and "status" in completion_data:
                    completion_status = completion_data.get("status")
                    print(f"[Watcher] Phase/Job complete: valid completion artifact found (status={completion_status}).")

                    # Read the final chunk of output before dealing with completion
                    try:
                        with open(raw_output_file, "r", encoding="utf-8", errors="replace") as f:
                            full = f.read()
                        if len(full) > char_pos:
                            new_content = full[char_pos:]
                            char_pos = len(full)
                            total_chars_read += len(new_content)
                            if in_final_output:
                                clean_new = _strip_thinking(new_content)
                                if clean_new:
                                    _append_stream_buffer(stream_buffer, clean_new)
                                    total_buffer_chars += len(clean_new)
                    except Exception as e:
                        print(f"[Watcher] Warning: failed to read final chunk: {e}")

                    # Delete artifact after confirmed successful read
                    try:
                        os.remove(completion_file)
                        print(f"[Watcher] Cleared completion artifact.")
                    except Exception as e:
                        print(f"[Watcher] Warning: failed to delete completion artifact: {e}")

                    # If this was Phase 1 (marker seen but not in final output yet), trigger Phase 2
                    if marker_seen_this_run and not in_final_output and AFFORDANCE_START in text_for_detection:
                        print(f"[Watcher] Phase 1 completed successfully. Queueing Phase 2 generation.")

                        # Save the Phase 1 thinking state to last_thinking.txt before wiping
                        last_thinking_file = os.path.join(root_dir, "global_flags", "last_thinking.txt")
                        try:
                            os.makedirs(os.path.dirname(last_thinking_file), exist_ok=True)
                            with open(last_thinking_file, "w", encoding="utf-8") as f:
                                f.write(full)
                            print(f"[Watcher] Phase 1 output saved to last_thinking.txt ({len(full)} chars)")
                        except Exception as e:
                            print(f"[Watcher] Error saving last_thinking.txt: {e}")

                        # Update job_input to trigger phase 2
                        input_path = os.path.join(root_dir, "jobs", "job_input.json")
                        try:
                            with open(input_path, "r", encoding="utf-8") as f:
                                input_payload = json.load(f)
                        except Exception:
                            input_payload = {}

                        input_payload["job_instructions"] = ""
                        input_payload["user_message"] = "##RECORD##"
                        input_payload["source"] = "chat_phase2"

                        with open(input_path, "w", encoding="utf-8") as f:
                            json.dump(input_payload, f, indent=2)

                        # Set the final output mode flag
                        try:
                            os.makedirs(os.path.dirname(final_output_flag), exist_ok=True)
                            with open(final_output_flag, "w", encoding="utf-8") as f:
                                f.write("active")
                            print(f"[Watcher] Phase 2: final_output_mode.txt written")
                        except Exception as e:
                            print(f"[Watcher] Phase 2: ERROR setting final_output_mode flag: {e}")

                        # Delete old raw output and trigger runner
                        try:
                            os.remove(raw_output_file)
                        except: pass

                        trigger_path = os.path.join(root_dir, "chat_trigger.txt")
                        with open(trigger_path, "w", encoding="utf-8") as f:
                            f.write(input_path)

                        in_final_output = True
                        char_pos = 0 # reset read pos for Phase 2

                        print(f"[Watcher] Phase 2 triggered. Waiting for Phase 2 raw output...")
                        while not os.path.exists(raw_output_file):
                            time.sleep(POLL_INTERVAL_WAIT)
                            if time.time() - global_start > TIMEOUT_GENERATION:
                                break
                        continue
                    else:
                        # Generation finished (Phase 2 completed or single phase completed)
                        print(f"[Watcher] Phase 2 / Single Phase complete. Total chars read={total_chars_read}, buffer chars={total_buffer_chars}")
                        break
            except json.JSONDecodeError:
                # File is present but unparseable, perhaps still being written. Continue loop.
                pass
            except Exception as e:
                print(f"[Watcher] Error reading completion artifact: {e}")

        time.sleep(POLL_INTERVAL_STREAM)

    # -----------------------------------------------------------------------
    # Phase 3: LLM done — extract final response and save history
    # -----------------------------------------------------------------------
    print(f"[Watcher] Phase 3: Reading final raw output from {raw_output_file}")
    try:
        with open(raw_output_file, "r", encoding="utf-8", errors="replace") as f:
            full_raw = f.read()
        print(f"[Watcher] Phase 3: Raw output length: {len(full_raw)} chars")
    except Exception as e:
        print(f"[Watcher] Phase 3: ERROR reading final output: {e}")
        full_raw = ""

    # ── Two-phase: read phase 1 thinking content ──────────
    last_thinking_file = os.path.join(root_dir, "global_flags", "last_thinking.txt")
    phase1_content = ""
    try:
        with open(last_thinking_file, "r", encoding="utf-8") as f:
            phase1_content = f.read()
        os.remove(last_thinking_file)
        print(f"[Watcher] Phase 3: Read {len(phase1_content)} chars of phase 1 from last_thinking.txt")
    except FileNotFoundError:
        print(f"[Watcher] Phase 3: last_thinking.txt not found (single-phase or fallback mode)")
    except Exception as e:
        print(f"[Watcher] Phase 3: Error reading last_thinking.txt: {e}")

    # Use single source of truth for final-output extraction.
    if phase1_content and AFFORDANCE_START not in full_raw:
        # If in two-phase but the marker isn't in phase 2 raw, prepend it so extraction correctly triggers
        # (This is needed if the marker was in Phase 1 and we want to reliably strip it)
        extraction_target = AFFORDANCE_START + "\n" + full_raw
    else:
        extraction_target = full_raw

    extracted = _extract_final_response(extraction_target)
    response_text = extracted if extracted is not None else ""

    marker_in_log = marker_seen_this_run
    if not marker_in_log:
        # Fallback: check phase 2 raw (single-phase compatibility)
        marker_in_log = AFFORDANCE_START in full_raw

    print(f"[Watcher] Phase 3: Extracted response length: {len(response_text) if response_text else 0} chars")
    if response_text:
        print(f"[Watcher] Phase 3: Response preview: {repr(response_text[:80])}")

    # Determine user_input: argv[2] (pre-captured) > job_input.json fallback > sentinel
    if user_message_arg:
        user_input = user_message_arg
        print(f"[Watcher] Phase 3: Using pre-captured user_message from argv ({len(user_input)} chars)")
    else:
        user_input = _get_user_message_from_json(root_dir) or "Unknown Input"
        print(f"[Watcher] Phase 3: Using user_message from job_input.json (argv not set): "
              f"{repr(user_input[:60])}")

    if response_text:
        # Save to LLM chat history (chat/ folder — read by model on future turns).
        # Only save the clean response; thinking stays out of LLM context.
        _save_chat_history(root_dir, user_input, response_text)

        # Save to user-visible output history (audit log, never read by LLM)
        _save_output_history(root_dir, user_input, response_text)
    else:
        print("[Watcher] Phase 3: No response text extracted — skipping history saves.")

    # Build combined raw for Output Viewer history tab:
    # phase 1 thinking + phase 2 response
    if phase1_content:
        combined_raw = phase1_content.rstrip() + "\n\n" + full_raw
    else:
        combined_raw = full_raw  # single-phase fallback

    # Write to output log (used by Output Viewer history tab)
    log_path = os.path.join(root_dir, "global_flags", "output_log.jsonl")
    print(f"[Watcher] Phase 3: Appending to output log: {log_path}")
    _append_output_log(
        root_dir,
        user_message=user_input,
        raw_output=combined_raw,
        final_output=response_text or "",
        marker_detected=marker_in_log,
    )

    # Clean up ALL processing flags — always delete final_output_mode.txt regardless
    # of flag_was_preset so the next generation always starts clean.
    print(f"[Watcher] Phase 3: Cleaning up flags: chat_processing.txt, final_output_mode.txt")
    _cleanup_flags(lock_file, final_output_flag)

    elapsed_total = time.time() - global_start
    print(f"[Watcher] === Capture complete in {elapsed_total:.2f}s. Exiting. ===")
    sys.exit(0)


if __name__ == "__main__":
    main()
