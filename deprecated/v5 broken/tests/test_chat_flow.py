"""
test_chat_flow.py — End-to-end test harness for the LYRN chat flow loop.

Mocks the LLM by writing tokens directly to job_raw_output.txt and
managing llm_status.txt, then verifies every script in the chain fires
correctly:

  chat_endpoint mock  →  route_chat.py  →  spawn_chat_watcher.py
  →  chat_watcher_bg.py  →  (mock LLM output)  →  chat history saved

Run from the repo root:
    python tests/test_chat_flow.py

All tests use a temporary working directory so they don't pollute the
real runtime state.
"""

import sys
import os
import json
import time
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

# Repo root
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

PASS = 0
FAIL = 0


def log(msg, level="INFO"):
    prefix = {"INFO": "  ", "OK": "  ✓", "FAIL": "  ✗", "SECTION": "\n==="}
    print(f"{prefix.get(level, '  ')} {msg}")


def assert_true(condition, description):
    global PASS, FAIL
    if condition:
        log(description, "OK")
        PASS += 1
    else:
        log(description, "FAIL")
        FAIL += 1


def assert_file_exists(path, description):
    assert_true(os.path.exists(path), f"{description} — {os.path.basename(path)} exists")


def assert_file_contains(path, substring, description):
    try:
        content = Path(path).read_text(encoding="utf-8", errors="replace")
        assert_true(substring in content, f"{description} — contains '{substring[:40]}...'")
    except Exception as e:
        assert_true(False, f"{description} — error reading file: {e}")


def setup_sandbox():
    """Create a temporary sandbox that mirrors the directory structure the scripts expect."""
    sandbox = tempfile.mkdtemp(prefix="lyrn_test_")
    for d in ["jobs", "chat", "global_flags", "automation/jobs", "automation/job_scripts",
              "automation/dynamic_snapshots/jobs", "deltas"]:
        os.makedirs(os.path.join(sandbox, d), exist_ok=True)

    # Copy the actual scripts into the sandbox
    scripts_src = os.path.join(REPO_ROOT, "automation", "job_scripts")
    scripts_dst = os.path.join(sandbox, "automation", "job_scripts")
    for fname in os.listdir(scripts_src):
        if fname.endswith(".py"):
            shutil.copy2(os.path.join(scripts_src, fname), os.path.join(scripts_dst, fname))

    # Copy jobs.json
    shutil.copy2(
        os.path.join(REPO_ROOT, "automation", "jobs", "jobs.json"),
        os.path.join(sandbox, "automation", "jobs", "jobs.json"),
    )

    # Copy file_lock.py (needed by route_chat.py)
    shutil.copy2(
        os.path.join(REPO_ROOT, "file_lock.py"),
        os.path.join(sandbox, "file_lock.py"),
    )

    # Create empty queue file
    Path(os.path.join(sandbox, "automation", "job_queue.json")).write_text("[]")

    return sandbox


def teardown_sandbox(sandbox):
    try:
        shutil.rmtree(sandbox, ignore_errors=True)
    except Exception:
        pass


def write_llm_status(sandbox, status):
    Path(os.path.join(sandbox, "global_flags", "llm_status.txt")).write_text(status)


def write_job_input(sandbox, user_message, source="chat"):
    payload = {
        "user_message": user_message,
        "source": source,
        "timestamp": "2026-03-23T12:00:00",
    }
    Path(os.path.join(sandbox, "jobs", "job_input.json")).write_text(
        json.dumps(payload, indent=2)
    )


def mock_llm_output(sandbox, tokens, delay_per_token=0.05, pre_delay=0.5):
    """
    Simulates the model_runner writing tokens to job_raw_output.txt.
    If affordance marker is in tokens, simulate a 2-phase process.
    Otherwise, simulate single phase.
    """
    def _writer():
        time.sleep(pre_delay)

        output_path = os.path.join(sandbox, "jobs", "job_raw_output.txt")
        completion_path = os.path.join(sandbox, "jobs", "job_completion.json")

        # Check if affordance marker is in any of the tokens
        has_affordance = any("AF: FINAL_OUTPUT" in t for t in tokens)

        if has_affordance:
            # Two-phase mock: find where the marker is to split tokens
            marker_idx = next(i for i, t in enumerate(tokens) if "AF: FINAL_OUTPUT" in t)
            tokens_p1 = tokens[:marker_idx + 1]
            tokens_p2 = tokens[marker_idx + 1:]

            # Phase 1
            write_llm_status(sandbox, "busy")
            with open(output_path, "w", encoding="utf-8") as f:
                for token in tokens_p1:
                    f.write(token)
                    f.flush()
                    time.sleep(delay_per_token)

            time.sleep(0.2)
            write_llm_status(sandbox, "idle")

            with open(completion_path, "w", encoding="utf-8") as f:
                json.dump({"status": "completed", "source": "chat", "raw_output_path": output_path}, f)

            # Wait for watcher to trigger phase 2 by clearing raw output
            # (In reality, runner detects trigger, clears file, starts gen)
            wait_time = 0
            while os.path.exists(output_path) and wait_time < 5.0:
                time.sleep(0.1)
                wait_time += 0.1

            time.sleep(0.2)

            # Phase 2
            write_llm_status(sandbox, "busy")
            with open(output_path, "w", encoding="utf-8") as f:
                for token in tokens_p2:
                    f.write(token)
                    f.flush()
                    time.sleep(delay_per_token)

            time.sleep(0.2)
            write_llm_status(sandbox, "idle")

            with open(completion_path, "w", encoding="utf-8") as f:
                json.dump({"status": "completed", "source": "chat_phase2", "raw_output_path": output_path}, f)

        else:
            # Single phase mock
            write_llm_status(sandbox, "busy")
            with open(output_path, "w", encoding="utf-8") as f:
                for token in tokens:
                    f.write(token)
                    f.flush()
                    time.sleep(delay_per_token)

            time.sleep(0.2)
            write_llm_status(sandbox, "idle")
            with open(completion_path, "w", encoding="utf-8") as f:
                json.dump({"status": "completed", "source": "chat", "raw_output_path": output_path}, f)

    t = threading.Thread(target=_writer, daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------------------
# Test 1: route_chat.py queues chat_response_job
# ---------------------------------------------------------------------------
def test_route_chat(sandbox):
    log("Test 1: route_chat.py queues chat_response_job into job_queue.json", "SECTION")

    script = os.path.join(sandbox, "automation", "job_scripts", "route_chat.py")
    result = subprocess.run(
        [sys.executable, script],
        capture_output=True, text=True, timeout=10,
        cwd=sandbox,
        env={**os.environ, "PYTHONPATH": sandbox},
    )

    assert_true(result.returncode == 0, f"route_chat.py exits 0 (got {result.returncode})")

    # Check queue file
    queue_path = os.path.join(sandbox, "automation", "job_queue.json")
    assert_file_exists(queue_path, "Queue file")

    try:
        queue = json.loads(Path(queue_path).read_text())
        assert_true(len(queue) >= 1, f"Queue has entries (got {len(queue)})")
        assert_true(
            queue[0].get("name") == "chat_response_job",
            f"First queued job is chat_response_job (got {queue[0].get('name')})"
        )
    except Exception as e:
        assert_true(False, f"Queue parseable: {e}")

    if result.stderr:
        log(f"  stderr: {result.stderr.strip()[:200]}")


# ---------------------------------------------------------------------------
# Test 2: spawn_chat_watcher.py captures user_message and spawns watcher
# ---------------------------------------------------------------------------
def test_spawn_chat_watcher(sandbox):
    log("Test 2: spawn_chat_watcher.py captures user_message and spawns watcher", "SECTION")

    user_msg = "Hello from test 2!"
    write_job_input(sandbox, user_msg)
    write_llm_status(sandbox, "busy")

    script = os.path.join(sandbox, "automation", "job_scripts", "spawn_chat_watcher.py")
    result = subprocess.run(
        [sys.executable, script],
        capture_output=True, text=True, timeout=10,
        cwd=sandbox,
    )

    assert_true(result.returncode == 0, f"spawn_chat_watcher.py exits 0 (got {result.returncode})")
    assert_true(
        "Captured user_message at spawn time" in result.stdout,
        "spawn_chat_watcher.py logs that it captured user_message"
    )
    assert_true(
        "Spawned background watcher" in result.stdout,
        "spawn_chat_watcher.py confirms watcher was spawned"
    )

    # The spawned watcher is now running in the background, waiting for output.
    # Create a dummy output file and set LLM idle so it exits cleanly,
    # preventing it from leaking into subsequent tests.
    time.sleep(0.3)
    output_path = os.path.join(sandbox, "jobs", "job_raw_output.txt")
    Path(output_path).write_text("Background watcher cleanup response")
    time.sleep(0.2)
    write_llm_status(sandbox, "idle")
    time.sleep(1.5)  # let watcher finish and save

    # Clean up the chat file it created so it doesn't interfere with later tests
    for f in Path(os.path.join(sandbox, "chat")).glob("chat_*.txt"):
        f.unlink()
    # Clean up the raw output too
    if os.path.exists(output_path):
        os.remove(output_path)


# ---------------------------------------------------------------------------
# Test 3: chat_watcher_bg.py with affordance marker
# ---------------------------------------------------------------------------
def test_watcher_with_affordance(sandbox):
    log("Test 3: chat_watcher_bg.py detects affordance marker and streams to buffer", "SECTION")

    user_msg = "What is the meaning of life?"
    write_job_input(sandbox, user_msg)

    # Clear any leftover files
    for f in ["jobs/job_raw_output.txt", "global_flags/final_output_mode.txt",
              "global_flags/chat_stream_buffer.txt", "global_flags/chat_processing.txt"]:
        p = os.path.join(sandbox, f)
        if os.path.exists(p):
            os.remove(p)

    # Create chat_processing.txt lock (like chat_endpoint does)
    Path(os.path.join(sandbox, "global_flags", "chat_processing.txt")).write_text("processing")

    # Start mock LLM output in background thread
    # Simulates: internal reasoning, then affordance marker, then final response
    tokens = [
        "Let me think about this... ",
        "Analyzing the question. ",
        "I have several perspectives. ",
        "\n##AF: FINAL_OUTPUT##\n",
        "The meaning of life is ",
        "a deeply personal question. ",
        "It varies for each individual, ",
        "but finding purpose and connection ",
        "are common themes.",
    ]

    llm_thread = mock_llm_output(sandbox, tokens, delay_per_token=0.1, pre_delay=0.3)

    # Run the watcher directly (not via spawn) with pre-captured user_message
    watcher_script = os.path.join(sandbox, "automation", "job_scripts", "chat_watcher_bg.py")
    watcher_proc = subprocess.Popen(
        [sys.executable, watcher_script, sandbox, user_msg],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )

    # Wait for watcher to finish (it should exit once LLM goes idle)
    try:
        stdout, stderr = watcher_proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        watcher_proc.kill()
        stdout, stderr = watcher_proc.communicate()
        assert_true(False, f"Watcher timed out\nStdout: {stdout}\nStderr: {stderr}")
        return

    llm_thread.join(timeout=5)

    assert_true(watcher_proc.returncode == 0, f"Watcher exits 0 (got {watcher_proc.returncode})")

    # Check that it detected the affordance
    assert_true(
        "AF: FINAL_OUTPUT" in stdout,
        "Watcher logs affordance detection"
    )

    # Check final_output_mode.txt was created (and then cleaned up)
    # The watcher cleans it up on exit, so it should be gone
    assert_true(
        not os.path.exists(os.path.join(sandbox, "global_flags", "final_output_mode.txt")),
        "final_output_mode.txt cleaned up after completion"
    )

    # Check chat_processing.txt lock was cleared
    assert_true(
        not os.path.exists(os.path.join(sandbox, "global_flags", "chat_processing.txt")),
        "chat_processing.txt lock cleared"
    )

    # Check stream buffer was written
    buffer_path = os.path.join(sandbox, "global_flags", "chat_stream_buffer.txt")
    if os.path.exists(buffer_path):
        buffer_content = Path(buffer_path).read_text()
        assert_true(
            "meaning of life" in buffer_content,
            "Stream buffer contains final output content"
        )
        assert_true(
            "Let me think" not in buffer_content,
            "Stream buffer does NOT contain pre-marker internal reasoning"
        )
    else:
        assert_true(False, "Stream buffer file was created")

    # Check chat history was saved
    chat_dir = os.path.join(sandbox, "chat")
    chat_files = list(Path(chat_dir).glob("chat_*.txt"))
    assert_true(len(chat_files) >= 1, f"Chat history file created (found {len(chat_files)})")

    if chat_files:
        chat_content = chat_files[0].read_text()
        assert_file_contains(
            str(chat_files[0]),
            "user\nWhat is the meaning of life?",
            "Chat history has correct user message"
        )
        assert_true(
            "meaning of life" in chat_content and "deeply personal" in chat_content,
            "Chat history has model response (after affordance marker only)"
        )
        assert_true(
            "Let me think about this" not in chat_content,
            "Chat history does NOT contain pre-marker reasoning"
        )

    if stderr:
        log(f"  watcher stderr: {stderr.strip()[:200]}")


# ---------------------------------------------------------------------------
# Test 4: chat_watcher_bg.py without affordance marker (legacy fallback)
# ---------------------------------------------------------------------------
def test_watcher_legacy_fallback(sandbox):
    log("Test 4: chat_watcher_bg.py falls back to full output when no marker present", "SECTION")

    user_msg = "Tell me a joke"
    write_job_input(sandbox, user_msg)

    # Clear leftover files
    for f in ["jobs/job_raw_output.txt", "global_flags/final_output_mode.txt",
              "global_flags/chat_stream_buffer.txt", "global_flags/chat_processing.txt"]:
        p = os.path.join(sandbox, f)
        if os.path.exists(p):
            os.remove(p)
    for f in Path(os.path.join(sandbox, "chat")).glob("chat_*.txt"):
        f.unlink()

    Path(os.path.join(sandbox, "global_flags", "chat_processing.txt")).write_text("processing")

    # Mock output WITHOUT affordance marker
    tokens = [
        "Why did the chicken cross the road? ",
        "To get to the other side!",
    ]
    llm_thread = mock_llm_output(sandbox, tokens, delay_per_token=0.1, pre_delay=0.3)

    watcher_script = os.path.join(sandbox, "automation", "job_scripts", "chat_watcher_bg.py")
    watcher_proc = subprocess.Popen(
        [sys.executable, watcher_script, sandbox, user_msg],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )

    try:
        stdout, stderr = watcher_proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        watcher_proc.kill()
        stdout, stderr = watcher_proc.communicate()
        assert_true(False, "Watcher timed out")
        return

    llm_thread.join(timeout=5)

    assert_true(watcher_proc.returncode == 0, f"Watcher exits 0 (got {watcher_proc.returncode})")

    # Should NOT have detected the affordance marker (none present in output)
    assert_true(
        "##AF: FINAL_OUTPUT## detected" not in stdout,
        "No affordance detection logged (none present)"
    )

    # Chat history should still be saved with full output as fallback
    chat_files = list(Path(os.path.join(sandbox, "chat")).glob("chat_*.txt"))
    assert_true(len(chat_files) >= 1, "Chat history file created (fallback mode)")

    if chat_files:
        chat_content = chat_files[0].read_text()
        assert_true(
            "chicken cross the road" in chat_content,
            "Chat history contains the full response"
        )
        assert_file_contains(
            str(chat_files[0]),
            "user\nTell me a joke",
            "Chat history has correct user message"
        )


# ---------------------------------------------------------------------------
# Test 5: Race condition — user_message arg overrides stale job_input.json
# ---------------------------------------------------------------------------
def test_race_condition_fix(sandbox):
    log("Test 5: Pre-captured user_message prevents race condition", "SECTION")

    original_msg = "Original question from user A"
    overwrite_msg = "Different question from user B"

    # Write the ORIGINAL message (what spawn_chat_watcher captured)
    write_job_input(sandbox, original_msg)

    # Clear leftovers
    for f in ["jobs/job_raw_output.txt", "global_flags/final_output_mode.txt",
              "global_flags/chat_stream_buffer.txt", "global_flags/chat_processing.txt"]:
        p = os.path.join(sandbox, f)
        if os.path.exists(p):
            os.remove(p)
    for f in Path(os.path.join(sandbox, "chat")).glob("chat_*.txt"):
        f.unlink()

    Path(os.path.join(sandbox, "global_flags", "chat_processing.txt")).write_text("processing")

    # Start mock LLM
    tokens = [
        "##AF: FINAL_OUTPUT##\n",
        "Response to the original question.",
    ]
    llm_thread = mock_llm_output(sandbox, tokens, delay_per_token=0.1, pre_delay=0.5)

    # Simulate the race: overwrite job_input.json AFTER spawning but BEFORE watcher reads it
    # We do this quickly before the watcher exits
    def _overwrite():
        time.sleep(0.3)  # after spawn, before watcher finishes
        write_job_input(sandbox, overwrite_msg)
    overwrite_thread = threading.Thread(target=_overwrite, daemon=True)
    overwrite_thread.start()

    # Run watcher with the ORIGINAL message as arg (as spawn_chat_watcher would)
    watcher_script = os.path.join(sandbox, "automation", "job_scripts", "chat_watcher_bg.py")
    watcher_proc = subprocess.Popen(
        [sys.executable, watcher_script, sandbox, original_msg],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )

    try:
        stdout, stderr = watcher_proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        watcher_proc.kill()
        stdout, stderr = watcher_proc.communicate()
        assert_true(False, f"Watcher timed out\nStdout: {stdout}\nStderr: {stderr}")
        return

    llm_thread.join(timeout=5)
    overwrite_thread.join(timeout=5)

    # The saved chat history should have the ORIGINAL user_message, not the overwritten one
    chat_files = sorted(Path(os.path.join(sandbox, "chat")).glob("chat_*.txt"))
    assert_true(len(chat_files) >= 1, "Chat history file created")

    if chat_files:
        chat_content = chat_files[-1].read_text()
        assert_true(
            "Original question from user A" in chat_content,
            "Chat history has ORIGINAL user_message (pre-captured)"
        )
        assert_true(
            "Different question from user B" not in chat_content,
            "Chat history does NOT have overwritten user_message (race avoided)"
        )


# ---------------------------------------------------------------------------
# Test 6: Full chain integration (route_chat → spawn_watcher → watcher → history)
# ---------------------------------------------------------------------------
def test_full_chain(sandbox):
    log("Test 6: Full chain integration test", "SECTION")

    user_msg = "Explain recursion"
    write_job_input(sandbox, user_msg)
    write_llm_status(sandbox, "idle")

    # Clear leftovers
    for f in ["jobs/job_raw_output.txt", "global_flags/final_output_mode.txt",
              "global_flags/chat_stream_buffer.txt", "global_flags/chat_processing.txt"]:
        p = os.path.join(sandbox, f)
        if os.path.exists(p):
            os.remove(p)
    for f in Path(os.path.join(sandbox, "chat")).glob("chat_*.txt"):
        f.unlink()

    # Reset queue
    Path(os.path.join(sandbox, "automation", "job_queue.json")).write_text("[]")
    Path(os.path.join(sandbox, "global_flags", "chat_processing.txt")).write_text("processing")

    # Step 1: Run route_chat.py
    route_script = os.path.join(sandbox, "automation", "job_scripts", "route_chat.py")
    result = subprocess.run(
        [sys.executable, route_script],
        capture_output=True, text=True, timeout=10,
        cwd=sandbox,
        env={**os.environ, "PYTHONPATH": sandbox},
    )
    assert_true(result.returncode == 0, "Step 1: route_chat.py succeeds")

    # Verify queue
    queue = json.loads(Path(os.path.join(sandbox, "automation", "job_queue.json")).read_text())
    assert_true(
        any(j["name"] == "chat_response_job" for j in queue),
        "Step 1: chat_response_job is in queue"
    )

    # Step 2: Run spawn_chat_watcher.py (spawns watcher in background)
    spawn_script = os.path.join(sandbox, "automation", "job_scripts", "spawn_chat_watcher.py")
    result = subprocess.run(
        [sys.executable, spawn_script],
        capture_output=True, text=True, timeout=10,
        cwd=sandbox,
    )
    assert_true(result.returncode == 0, "Step 2: spawn_chat_watcher.py succeeds")

    # Step 3: Mock LLM output (simulating what model_runner would do)
    # The test needs to mock a two-phase run since the affordance marker triggers phase 2.
    tokens_phase1 = [
        "Thinking about recursion... ",
        "A recursive function calls itself. ",
        "\n##AF: FINAL_OUTPUT##\n",
    ]
    tokens_phase2 = [
        "Recursion is when a function calls itself ",
        "to solve smaller subproblems. ",
        "The key is having a base case that stops the recursion.",
    ]

    output_path = os.path.join(sandbox, "jobs", "job_raw_output.txt")
    completion_path = os.path.join(sandbox, "jobs", "job_completion.json")

    # Phase 1
    write_llm_status(sandbox, "busy")
    time.sleep(0.3)
    with open(output_path, "w", encoding="utf-8") as f:
        for token in tokens_phase1:
            f.write(token)
            f.flush()
            time.sleep(0.1)

    # Emit Phase 1 completion artifact
    time.sleep(0.3)
    write_llm_status(sandbox, "idle")
    completion_data_p1 = {
        "status": "completed",
        "source": "chat",
        "raw_output_path": output_path,
        "timestamp": time.time(),
        "error_message": None
    }
    with open(completion_path, "w", encoding="utf-8") as f:
        json.dump(completion_data_p1, f)

    # Wait for watcher to trigger phase 2
    time.sleep(2)

    # Phase 2
    write_llm_status(sandbox, "busy")
    time.sleep(0.3)
    with open(output_path, "w", encoding="utf-8") as f:
        for token in tokens_phase2:
            f.write(token)
            f.flush()
            time.sleep(0.1)

    # Emit Phase 2 completion artifact
    time.sleep(0.3)
    write_llm_status(sandbox, "idle")
    completion_data_p2 = {
        "status": "completed",
        "source": "chat_phase2",
        "raw_output_path": output_path,
        "timestamp": time.time(),
        "error_message": None
    }
    with open(completion_path, "w", encoding="utf-8") as f:
        json.dump(completion_data_p2, f)

    # Wait for watcher to process and save
    time.sleep(3)

    # Step 4: Verify chat history
    chat_files = list(Path(os.path.join(sandbox, "chat")).glob("chat_*.txt"))
    assert_true(len(chat_files) >= 1, "Step 4: Chat history file created")

    if chat_files:
        chat_content = chat_files[-1].read_text()
        assert_true(
            "Explain recursion" in chat_content,
            "Step 4: Chat history has correct user message"
        )
        assert_true(
            "Recursion is when a function calls itself" in chat_content,
            "Step 4: Chat history has final response"
        )
        assert_true(
            "Thinking about recursion" not in chat_content,
            "Step 4: Chat history excludes pre-marker reasoning"
        )

    # Verify lock was cleared
    assert_true(
        not os.path.exists(os.path.join(sandbox, "global_flags", "chat_processing.txt")),
        "Step 4: chat_processing.txt lock cleared"
    )


# ---------------------------------------------------------------------------
# Test 7: Legacy ##Response_START## / ##Response_END## markers
# ---------------------------------------------------------------------------
def test_legacy_markers(sandbox):
    log("Test 7: Legacy ##Response_START## / ##Response_END## markers work", "SECTION")

    user_msg = "Legacy marker test"
    write_job_input(sandbox, user_msg)

    # Clear leftovers
    for f in ["jobs/job_raw_output.txt", "global_flags/final_output_mode.txt",
              "global_flags/chat_stream_buffer.txt", "global_flags/chat_processing.txt"]:
        p = os.path.join(sandbox, f)
        if os.path.exists(p):
            os.remove(p)
    for f in Path(os.path.join(sandbox, "chat")).glob("chat_*.txt"):
        f.unlink()

    Path(os.path.join(sandbox, "global_flags", "chat_processing.txt")).write_text("processing")

    tokens = [
        "Internal thinking here...\n",
        "##Response_START##\n",
        "This is the legacy extracted response.\n",
        "##Response_END##\n",
        "Post-marker junk.\n",
    ]
    llm_thread = mock_llm_output(sandbox, tokens, delay_per_token=0.05, pre_delay=0.3)

    watcher_script = os.path.join(sandbox, "automation", "job_scripts", "chat_watcher_bg.py")
    watcher_proc = subprocess.Popen(
        [sys.executable, watcher_script, sandbox, user_msg],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )

    try:
        stdout, stderr = watcher_proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        watcher_proc.kill()
        stdout, stderr = watcher_proc.communicate()
        assert_true(False, "Watcher timed out")
        return

    llm_thread.join(timeout=5)

    chat_files = list(Path(os.path.join(sandbox, "chat")).glob("chat_*.txt"))
    assert_true(len(chat_files) >= 1, "Chat history file created (legacy markers)")

    if chat_files:
        chat_content = chat_files[-1].read_text()
        assert_true(
            "legacy extracted response" in chat_content,
            "Chat history has content from between legacy markers"
        )
        assert_true(
            "Internal thinking here" not in chat_content,
            "Chat history excludes pre-marker content"
        )
        assert_true(
            "Post-marker junk" not in chat_content,
            "Chat history excludes post-end-marker content"
        )


# ---------------------------------------------------------------------------
# Test 8: Flag pre-set (recursion scenario) — watcher streams everything from start
# ---------------------------------------------------------------------------
def test_flag_preset_recursion(sandbox):
    log("Test 8: Flag pre-set (recursion) — watcher streams all output from byte 0", "SECTION")

    user_msg = "Recursion final output test"
    write_job_input(sandbox, user_msg)

    # Clear leftovers
    for f in ["jobs/job_raw_output.txt", "global_flags/chat_stream_buffer.txt",
              "global_flags/chat_processing.txt"]:
        p = os.path.join(sandbox, f)
        if os.path.exists(p): os.remove(p)
    for f in Path(os.path.join(sandbox, "chat")).glob("chat_*.txt"):
        f.unlink()

    Path(os.path.join(sandbox, "global_flags", "chat_processing.txt")).write_text("processing")

    # Pre-set the final_output_mode flag — simulates a previous job (e.g. analysis_job)
    # having emitted ##AF: FINAL_OUTPUT## and set the flag.
    Path(os.path.join(sandbox, "global_flags", "final_output_mode.txt")).write_text("active")

    # Mock LLM output with NO marker — because the flag is already set, the watcher
    # should stream everything from byte 0 without waiting for the marker.
    tokens = [
        "This is the ",
        "final answer ",
        "to the user. ",
        "No marker needed here.",
    ]
    llm_thread = mock_llm_output(sandbox, tokens, delay_per_token=0.1, pre_delay=0.3)

    watcher_script = os.path.join(sandbox, "automation", "job_scripts", "chat_watcher_bg.py")
    watcher_proc = subprocess.Popen(
        [sys.executable, watcher_script, sandbox, user_msg],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )

    try:
        stdout, stderr = watcher_proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        watcher_proc.kill()
        stdout, stderr = watcher_proc.communicate()
        assert_true(False, "Watcher timed out")
        return

    llm_thread.join(timeout=5)

    assert_true(watcher_proc.returncode == 0, f"Watcher exits 0 (got {watcher_proc.returncode})")

    assert_true(
        "pre-set" in stdout.lower() or "flag was pre-set" in stdout,
        "Watcher logs that flag was pre-set"
    )

    # Stream buffer should have the FULL output (no marker needed)
    buffer_path = os.path.join(sandbox, "global_flags", "chat_stream_buffer.txt")
    assert_true(os.path.exists(buffer_path), "Stream buffer was created")
    if os.path.exists(buffer_path):
        buf = Path(buffer_path).read_text()
        assert_true("final answer" in buf, "Stream buffer contains full output")
        assert_true("No marker needed here" in buf, "Stream buffer has all tokens")

    # Flag should be cleared after completion
    assert_true(
        not os.path.exists(os.path.join(sandbox, "global_flags", "final_output_mode.txt")),
        "final_output_mode.txt cleared after completion"
    )

    # Chat history should be saved
    chat_files = list(Path(os.path.join(sandbox, "chat")).glob("chat_*.txt"))
    assert_true(len(chat_files) >= 1, "Chat history saved")
    if chat_files:
        content = chat_files[-1].read_text()
        assert_true("final answer" in content, "Chat history has the full response")
        assert_true("Recursion final output test" in content, "Chat history has correct user message")

    if stderr:
        log(f"  watcher stderr: {stderr.strip()[:200]}")


# ---------------------------------------------------------------------------
# Test 9: Split-token affordance marker detection
# The marker arrives spread across several small tokens — must still be detected.
# ---------------------------------------------------------------------------
def test_split_token_marker(sandbox):
    log("Test 9: Affordance marker split across multiple tokens is still detected", "SECTION")

    user_msg = "Split token affordance test"
    write_job_input(sandbox, user_msg)

    for f in ["jobs/job_raw_output.txt", "global_flags/final_output_mode.txt",
              "global_flags/chat_stream_buffer.txt", "global_flags/chat_processing.txt"]:
        p = os.path.join(sandbox, f)
        if os.path.exists(p): os.remove(p)
    for f in Path(os.path.join(sandbox, "chat")).glob("chat_*.txt"):
        f.unlink()

    Path(os.path.join(sandbox, "global_flags", "chat_processing.txt")).write_text("processing")

    # Break the marker into tiny pieces across tokens
    # Note: For our mock to trigger two-phase logic correctly, we need the combined token
    # to be recognized by our mock logic if we want phase 1 -> phase 2 transition in the test.
    # To keep the mock simple while testing the watcher's buffering, we'll write them to file.
    # But wait, our mock_llm_output looks for "AF: FINAL_OUTPUT" in tokens to do the phase switch.
    # Let's adjust the tokens so the mock understands it, or we can just mock a single phase
    # and see if the watcher detects the affordance and triggers phase 2.
    # Actually, if the mock doesn't do two-phase, the watcher will trigger phase 2 and wait forever
    # because the mock won't write the second completion artifact.
    # Let's just use the mock's single token for the affordance, but split it in the mock logic?
    # No, we can just manually run the two phases here for this specific test.
    tokens_p1 = [
        "Internal processing...\n",
        "##AF",          # first fragment
        ": FINA",        # second fragment
        "L_OUTPUT",      # third fragment
        "##\n",          # closing ##
    ]
    tokens_p2 = [
        "Split-token response delivered successfully.",
    ]

    # Custom mock for this test
    def custom_split_mock():
        output_path = os.path.join(sandbox, "jobs", "job_raw_output.txt")
        completion_path = os.path.join(sandbox, "jobs", "job_completion.json")
        time.sleep(0.3)
        # Phase 1
        with open(output_path, "w", encoding="utf-8") as f:
            for token in tokens_p1:
                f.write(token)
                f.flush()
                time.sleep(0.1)
        time.sleep(0.2)
        with open(completion_path, "w", encoding="utf-8") as f:
            json.dump({"status": "completed", "source": "chat", "raw_output_path": output_path}, f)

        wait_time = 0
        while os.path.exists(output_path) and wait_time < 5.0:
            time.sleep(0.1)
            wait_time += 0.1

        time.sleep(0.2)
        # Phase 2
        with open(output_path, "w", encoding="utf-8") as f:
            for token in tokens_p2:
                f.write(token)
                f.flush()
                time.sleep(0.1)
        time.sleep(0.2)
        with open(completion_path, "w", encoding="utf-8") as f:
            json.dump({"status": "completed", "source": "chat_phase2", "raw_output_path": output_path}, f)

    t = threading.Thread(target=custom_split_mock, daemon=True)
    t.start()

    watcher_script = os.path.join(sandbox, "automation", "job_scripts", "chat_watcher_bg.py")
    watcher_proc = subprocess.Popen(
        [sys.executable, watcher_script, sandbox, user_msg],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )

    try:
        stdout, stderr = watcher_proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        watcher_proc.kill()
        stdout, stderr = watcher_proc.communicate()
        assert_true(False, "Watcher timed out")
        return

    t.join(timeout=5)

    assert_true(watcher_proc.returncode == 0, f"Watcher exits 0 (got {watcher_proc.returncode})")
    assert_true(
        "##AF: FINAL_OUTPUT## detected" in stdout,
        "Split-token affordance marker was detected"
    )

    chat_files = list(Path(os.path.join(sandbox, "chat")).glob("chat_*.txt"))
    assert_true(len(chat_files) >= 1, "Chat history saved after split-token detection")
    if chat_files:
        content = chat_files[-1].read_text()
        assert_true("Split-token response delivered" in content,
                    "Chat history has post-marker content")
        assert_true("Internal processing" not in content,
                    "Chat history excludes pre-marker content")


# ---------------------------------------------------------------------------
# Test 10: output_log.jsonl is written with correct structure
# ---------------------------------------------------------------------------
def test_output_log_written(sandbox):
    log("Test 10: output_log.jsonl written with correct fields after generation", "SECTION")

    user_msg = "Output log test question"
    write_job_input(sandbox, user_msg)

    for f in ["jobs/job_raw_output.txt", "global_flags/final_output_mode.txt",
              "global_flags/chat_stream_buffer.txt", "global_flags/chat_processing.txt",
              "global_flags/output_log.jsonl"]:
        p = os.path.join(sandbox, f)
        if os.path.exists(p): os.remove(p)
    for f in Path(os.path.join(sandbox, "chat")).glob("chat_*.txt"):
        f.unlink()

    Path(os.path.join(sandbox, "global_flags", "chat_processing.txt")).write_text("processing")

    tokens = [
        "Thinking...\n",
        "##AF: FINAL_OUTPUT##\n",
        "The log entry answer.",
    ]

    def custom_mock_p1_p2():
        output_path = os.path.join(sandbox, "jobs", "job_raw_output.txt")
        completion_path = os.path.join(sandbox, "jobs", "job_completion.json")
        time.sleep(0.3)
        tokens_p1 = tokens[:2]
        tokens_p2 = tokens[2:]

        # Phase 1
        with open(output_path, "w", encoding="utf-8") as f:
            for token in tokens_p1:
                f.write(token)
                f.flush()
                time.sleep(0.1)
        time.sleep(0.2)
        with open(completion_path, "w", encoding="utf-8") as f:
            json.dump({"status": "completed", "source": "chat", "raw_output_path": output_path}, f)

        wait_time = 0
        while os.path.exists(output_path) and wait_time < 5.0:
            time.sleep(0.1)
            wait_time += 0.1

        time.sleep(0.2)
        # Phase 2
        with open(output_path, "w", encoding="utf-8") as f:
            for token in tokens_p2:
                f.write(token)
                f.flush()
                time.sleep(0.1)
        time.sleep(0.2)
        with open(completion_path, "w", encoding="utf-8") as f:
            json.dump({"status": "completed", "source": "chat_phase2", "raw_output_path": output_path}, f)

    llm_thread = threading.Thread(target=custom_mock_p1_p2, daemon=True)
    llm_thread.start()

    watcher_script = os.path.join(sandbox, "automation", "job_scripts", "chat_watcher_bg.py")
    watcher_proc = subprocess.Popen(
        [sys.executable, watcher_script, sandbox, user_msg],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )

    try:
        stdout, stderr = watcher_proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        watcher_proc.kill()
        stdout, stderr = watcher_proc.communicate()
        assert_true(False, "Watcher timed out")
        return

    llm_thread.join(timeout=5)

    log_path = os.path.join(sandbox, "global_flags", "output_log.jsonl")
    assert_file_exists(log_path, "output_log.jsonl")

    if os.path.exists(log_path):
        lines = [l for l in Path(log_path).read_text().splitlines() if l.strip()]
        assert_true(len(lines) >= 1, f"output_log.jsonl has at least 1 entry (got {len(lines)})")

        if lines:
            try:
                entry = json.loads(lines[-1])
                assert_true("timestamp" in entry, "Log entry has 'timestamp'")
                assert_true("user_message" in entry, "Log entry has 'user_message'")
                assert_true("raw_output" in entry, "Log entry has 'raw_output'")
                assert_true("final_output" in entry, "Log entry has 'final_output'")
                assert_true("marker_detected" in entry, "Log entry has 'marker_detected'")
                assert_true(entry["user_message"] == user_msg,
                            "Log entry user_message matches input")
                assert_true(entry["marker_detected"] is True,
                            "Log entry marker_detected is True")
                assert_true("The log entry answer" in entry["final_output"],
                            "Log entry final_output has response text")
                assert_true("##AF: FINAL_OUTPUT##" in entry["raw_output"],
                            "Log entry raw_output includes full raw content with marker")
            except Exception as e:
                assert_true(False, f"Log entry parseable: {e}")


# ---------------------------------------------------------------------------
# Test 11: Empty LLM output — watcher handles gracefully
# ---------------------------------------------------------------------------
def test_empty_llm_output(sandbox):
    log("Test 11: Empty LLM output handled gracefully (no crash, no history saved)", "SECTION")

    user_msg = "Empty response test"
    write_job_input(sandbox, user_msg)

    for f in ["jobs/job_raw_output.txt", "global_flags/final_output_mode.txt",
              "global_flags/chat_stream_buffer.txt", "global_flags/chat_processing.txt"]:
        p = os.path.join(sandbox, f)
        if os.path.exists(p): os.remove(p)
    for f in Path(os.path.join(sandbox, "chat")).glob("chat_*.txt"):
        f.unlink()

    Path(os.path.join(sandbox, "global_flags", "chat_processing.txt")).write_text("processing")

    # Write an empty file, then set status to idle
    tokens = [""]  # empty token
    llm_thread = mock_llm_output(sandbox, tokens, delay_per_token=0.05, pre_delay=0.3)

    watcher_script = os.path.join(sandbox, "automation", "job_scripts", "chat_watcher_bg.py")
    watcher_proc = subprocess.Popen(
        [sys.executable, watcher_script, sandbox, user_msg],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )

    try:
        stdout, stderr = watcher_proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        watcher_proc.kill()
        stdout, stderr = watcher_proc.communicate()
        assert_true(False, "Watcher timed out")
        return

    llm_thread.join(timeout=5)

    # Watcher should exit 0 (not crash)
    assert_true(watcher_proc.returncode == 0,
                f"Watcher exits 0 on empty output (got {watcher_proc.returncode})")

    # No chat history should be saved (nothing to save)
    chat_files = list(Path(os.path.join(sandbox, "chat")).glob("chat_*.txt"))
    assert_true(len(chat_files) == 0,
                f"No chat history saved for empty output (found {len(chat_files)})")

    # Processing lock should still be cleared
    assert_true(
        not os.path.exists(os.path.join(sandbox, "global_flags", "chat_processing.txt")),
        "chat_processing.txt cleared even for empty output"
    )


# ---------------------------------------------------------------------------
# Test 12: Affordance marker at the very start of output (no internal preamble)
# ---------------------------------------------------------------------------
def test_marker_at_start(sandbox):
    log("Test 12: Affordance marker at the very start of output (no internal preamble)", "SECTION")

    user_msg = "Direct answer please"
    write_job_input(sandbox, user_msg)

    for f in ["jobs/job_raw_output.txt", "global_flags/final_output_mode.txt",
              "global_flags/chat_stream_buffer.txt", "global_flags/chat_processing.txt"]:
        p = os.path.join(sandbox, f)
        if os.path.exists(p): os.remove(p)
    for f in Path(os.path.join(sandbox, "chat")).glob("chat_*.txt"):
        f.unlink()

    Path(os.path.join(sandbox, "global_flags", "chat_processing.txt")).write_text("processing")

    tokens = [
        "##AF: FINAL_OUTPUT##\n",  # marker is the FIRST thing written
        "Here is your direct answer.",
        " No preamble at all.",
    ]

    def custom_mock_p1_p2():
        output_path = os.path.join(sandbox, "jobs", "job_raw_output.txt")
        completion_path = os.path.join(sandbox, "jobs", "job_completion.json")
        time.sleep(0.3)
        tokens_p1 = tokens[:1]
        tokens_p2 = tokens[1:]

        # Phase 1
        with open(output_path, "w", encoding="utf-8") as f:
            for token in tokens_p1:
                f.write(token)
                f.flush()
                time.sleep(0.1)
        time.sleep(0.2)
        with open(completion_path, "w", encoding="utf-8") as f:
            json.dump({"status": "completed", "source": "chat", "raw_output_path": output_path}, f)

        wait_time = 0
        while os.path.exists(output_path) and wait_time < 5.0:
            time.sleep(0.1)
            wait_time += 0.1

        time.sleep(0.2)
        # Phase 2
        with open(output_path, "w", encoding="utf-8") as f:
            for token in tokens_p2:
                f.write(token)
                f.flush()
                time.sleep(0.1)
        time.sleep(0.2)
        with open(completion_path, "w", encoding="utf-8") as f:
            json.dump({"status": "completed", "source": "chat_phase2", "raw_output_path": output_path}, f)

    llm_thread = threading.Thread(target=custom_mock_p1_p2, daemon=True)
    llm_thread.start()

    watcher_script = os.path.join(sandbox, "automation", "job_scripts", "chat_watcher_bg.py")
    watcher_proc = subprocess.Popen(
        [sys.executable, watcher_script, sandbox, user_msg],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )

    try:
        stdout, stderr = watcher_proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        watcher_proc.kill()
        stdout, stderr = watcher_proc.communicate()
        assert_true(False, "Watcher timed out")
        return

    llm_thread.join(timeout=5)

    assert_true(watcher_proc.returncode == 0, f"Watcher exits 0 (got {watcher_proc.returncode})")
    assert_true("##AF: FINAL_OUTPUT## detected" in stdout, "Marker detected even at start of output")

    chat_files = list(Path(os.path.join(sandbox, "chat")).glob("chat_*.txt"))
    assert_true(len(chat_files) >= 1, "Chat history saved")
    if chat_files:
        content = chat_files[-1].read_text()
        assert_true("direct answer" in content, "Chat history has response")
        assert_true("##AF: FINAL_OUTPUT##" not in content,
                    "Affordance marker itself not saved to chat history")


# ---------------------------------------------------------------------------
# Test 13: Debug output content validation — watcher logs all phase transitions
# ---------------------------------------------------------------------------
def test_debug_output_completeness(sandbox):
    log("Test 13: Watcher emits all expected Phase 1/2/3 debug messages", "SECTION")

    user_msg = "Debug output test"
    write_job_input(sandbox, user_msg)

    for f in ["jobs/job_raw_output.txt", "global_flags/final_output_mode.txt",
              "global_flags/chat_stream_buffer.txt", "global_flags/chat_processing.txt"]:
        p = os.path.join(sandbox, f)
        if os.path.exists(p): os.remove(p)
    for f in Path(os.path.join(sandbox, "chat")).glob("chat_*.txt"):
        f.unlink()

    Path(os.path.join(sandbox, "global_flags", "chat_processing.txt")).write_text("processing")

    tokens = [
        "Preamble thinking.\n",
        "##AF: FINAL_OUTPUT##\n",
        "Final response here.",
    ]

    def custom_mock_p1_p2():
        output_path = os.path.join(sandbox, "jobs", "job_raw_output.txt")
        completion_path = os.path.join(sandbox, "jobs", "job_completion.json")
        time.sleep(0.3)
        tokens_p1 = tokens[:2]
        tokens_p2 = tokens[2:]

        # Phase 1
        with open(output_path, "w", encoding="utf-8") as f:
            for token in tokens_p1:
                f.write(token)
                f.flush()
                time.sleep(0.1)
        time.sleep(0.2)
        with open(completion_path, "w", encoding="utf-8") as f:
            json.dump({"status": "completed", "source": "chat", "raw_output_path": output_path}, f)

        wait_time = 0
        while os.path.exists(output_path) and wait_time < 5.0:
            time.sleep(0.1)
            wait_time += 0.1

        time.sleep(0.2)
        # Phase 2
        with open(output_path, "w", encoding="utf-8") as f:
            for token in tokens_p2:
                f.write(token)
                f.flush()
                time.sleep(0.1)
        time.sleep(0.2)
        with open(completion_path, "w", encoding="utf-8") as f:
            json.dump({"status": "completed", "source": "chat_phase2", "raw_output_path": output_path}, f)

    llm_thread = threading.Thread(target=custom_mock_p1_p2, daemon=True)
    llm_thread.start()

    watcher_script = os.path.join(sandbox, "automation", "job_scripts", "chat_watcher_bg.py")
    watcher_proc = subprocess.Popen(
        [sys.executable, watcher_script, sandbox, user_msg],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )

    try:
        stdout, stderr = watcher_proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        watcher_proc.kill()
        stdout, stderr = watcher_proc.communicate()
        assert_true(False, "Watcher timed out")
        return

    llm_thread.join(timeout=5)

    # Check all phase headings are present
    assert_true("Phase 1:" in stdout, "Phase 1 debug messages present")
    assert_true("Phase 2:" in stdout, "Phase 2 debug messages present")
    assert_true("Phase 3:" in stdout, "Phase 3 debug messages present")

    # Check key diagnostic messages
    assert_true("PID:" in stdout, "PID logged at startup")
    assert_true("root_dir:" in stdout, "root_dir logged at startup")
    assert_true("affordance_marker:" in stdout, "affordance_marker logged at startup")
    assert_true("Output file appeared after" in stdout, "Phase 1 file-detected message logged")
    assert_true("pre-set: False" in stdout, "Phase 1 flag pre-set status logged")
    assert_true("Phase/Job complete" in stdout, "Phase 2 explicit completion logged")
    assert_true("Raw output length:" in stdout, "Phase 3 raw output length logged")
    assert_true("Extracted response length:" in stdout, "Phase 3 extracted length logged")
    assert_true("Capture complete" in stdout, "Final completion message logged")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main():
    print("\n" + "=" * 60)
    print("  LYRN Chat Flow Test Harness")
    print("  Mocking LLM — no model required")
    print("=" * 60)

    sandbox = setup_sandbox()
    print(f"\n  Sandbox: {sandbox}")

    try:
        test_route_chat(sandbox)
        test_spawn_chat_watcher(sandbox)
        test_watcher_with_affordance(sandbox)
        test_watcher_legacy_fallback(sandbox)
        test_race_condition_fix(sandbox)
        test_full_chain(sandbox)
        test_legacy_markers(sandbox)
        test_flag_preset_recursion(sandbox)
        test_split_token_marker(sandbox)
        test_output_log_written(sandbox)
        test_empty_llm_output(sandbox)
        test_marker_at_start(sandbox)
        test_debug_output_completeness(sandbox)
    finally:
        teardown_sandbox(sandbox)

    print("\n" + "=" * 60)
    print(f"  Results: {PASS} passed, {FAIL} failed")
    print("=" * 60 + "\n")

    sys.exit(1 if FAIL > 0 else 0)


if __name__ == "__main__":
    main()
