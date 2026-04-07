"""
debug_live.py — Live end-to-end debug runner for the LYRN chat flow.

Runs against the LIVE, running start_lyrn.py server via HTTP API calls so
every step goes through the real scheduler → DSManager → model_runner pipeline.
The affordance marker (##AF: FINAL_OUTPUT##) is exercised exactly as it would
be in production.

Usage (launched automatically by the server via POST /api/debug/run):
    python tests/debug_live.py
    python tests/debug_live.py --preset 2

What it does:
  1. Detects the server URL from port.txt (default: 127.0.0.1:8080).
  2. Applies the chosen preset via POST /api/config/active.
  3. Starts model_runner.py via POST /api/system/start_worker.
  4. Polls GET /health until llm_status == "idle".
  5. Waits 20 s for the model to fully settle.
  6. For each of 3 test prompts:
       a. Clears chat history via DELETE /api/chat (only current-loop pairs).
       b. Waits for model idle, then injects prompt via POST /api/chat.
       c. Polls GET /api/chat/stream_status until final_output_active == true
          (##AF: FINAL_OUTPUT## detected) or generation ends.
       d. Waits for llm_status == "idle" (generation complete).
       e. Clears chat history again (post-gen wipe).
  7. Collects all backend logs from the DiskJournalLogger on disk
     (includes model_runner.py stdout/stderr captured as WorkerOut/WorkerErr).
  8. Writes a timestamped Markdown report to docs/debug_reports/.
"""

import sys
import os
import json
import time
import argparse
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# HTTP client (requests preferred, urllib fallback)
# ---------------------------------------------------------------------------

try:
    import requests as _req
    _HAS_REQUESTS = True
except ImportError:
    import urllib.request as _urlreq
    import urllib.error as _urlerr
    _HAS_REQUESTS = False


class APIClient:
    def __init__(self, base_url: str, token: str):
        self.base = base_url.rstrip("/")
        self.token = token

    def _h(self):
        return {"X-Token": self.token, "Content-Type": "application/json"}

    def get(self, path):
        if _HAS_REQUESTS:
            return _req.get(f"{self.base}{path}", headers=self._h(), timeout=15)
        return self._ureq("GET", path)

    def post(self, path, data=None):
        if _HAS_REQUESTS:
            return _req.post(f"{self.base}{path}", headers=self._h(), json=data, timeout=15)
        return self._ureq("POST", path, data)

    def delete(self, path):
        if _HAS_REQUESTS:
            return _req.delete(f"{self.base}{path}", headers=self._h(), timeout=15)
        return self._ureq("DELETE", path)

    def _ureq(self, method, path, data=None):
        url = f"{self.base}{path}"
        body = json.dumps(data).encode() if data else None
        req = _urlreq.Request(url, data=body, headers=self._h(), method=method)
        try:
            with _urlreq.urlopen(req, timeout=15) as resp:
                payload = json.loads(resp.read().decode())
                class _R:
                    status_code = resp.status
                    @staticmethod
                    def json(): return payload
                return _R()
        except _urlerr.HTTPError as e:
            payload = json.loads(e.read().decode())
            class _E:
                status_code = e.code
                @staticmethod
                def json(): return payload
            return _E()


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT_DIR     = os.path.join(REPO_ROOT, "docs", "debug_reports")
RAW_OUTPUT     = os.path.join(REPO_ROOT, "jobs", "job_raw_output.txt")
STREAM_BUFFER  = os.path.join(REPO_ROOT, "global_flags", "chat_stream_buffer.txt")
OUTPUT_LOG     = os.path.join(REPO_ROOT, "global_flags", "output_log.jsonl")

DEFAULT_PRESET      = "1"
MODEL_LOAD_TIMEOUT  = 300   # seconds to wait for model to reach idle after start
AFFORDANCE_TIMEOUT  = 300   # seconds to wait for ##AF: FINAL_OUTPUT## after inject
GENERATION_TIMEOUT  = 120   # extra seconds after affordance to wait for llm_status idle
POST_LOAD_WAIT      = 20    # seconds to let the model settle after reaching idle

TEST_PROMPTS = [
    "Say hello and confirm you are working correctly. Use the affordance trigger to start your reply.",
    "What is 2 + 2? Answer directly with the affordance trigger before your answer.",
    "In one sentence, describe what the ##AF: FINAL_OUTPUT## marker does in this system.",
]


# ---------------------------------------------------------------------------
# Environment detection
# ---------------------------------------------------------------------------

def detect_server_url() -> str:
    port_file = os.path.join(REPO_ROOT, "port.txt")
    try:
        port = Path(port_file).read_text(encoding="utf-8").strip()
        if port.isdigit():
            return f"http://127.0.0.1:{port}"
    except Exception:
        pass
    return "http://127.0.0.1:8080"


def detect_token() -> str:
    if Path(os.path.join(REPO_ROOT, "global_flags", "no_auth")).exists():
        return "no-auth"
    try:
        t = Path(os.path.join(REPO_ROOT, "admin_token.txt")).read_text(encoding="utf-8").strip()
        if t:
            return t
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def read_file_safe(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def list_recent_chat_files() -> list:
    chat_dir = os.path.join(REPO_ROOT, "chat")
    if not os.path.isdir(chat_dir):
        return []
    return sorted(
        [str(p) for p in Path(chat_dir).glob("chat_*.txt")],
        key=os.path.getmtime, reverse=True
    )[:3]


def section(title: str) -> str:
    bar = "=" * 60
    return f"\n{bar}\n  {title}\n{bar}\n"


# ---------------------------------------------------------------------------
# Polling helpers
# ---------------------------------------------------------------------------

def poll_llm_status(client: APIClient, targets: set, timeout: int) -> str | None:
    """Poll GET /health until worker.llm_status is in targets. Returns status or None."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = client.get("/health")
            if r.status_code == 200:
                status = r.json().get("worker", {}).get("llm_status", "unknown")
                if status in targets:
                    return status
        except Exception as exc:
            print(f"[{ts()}] poll_llm_status error: {exc}")
        time.sleep(1)
    return None


def poll_affordance(client: APIClient, timeout: int) -> str:
    """
    Poll /api/chat/stream_status until the affordance marker fires or generation ends.
    Returns: "marker" | "done_no_marker" | "timeout"
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = client.get("/api/chat/stream_status")
            if r.status_code == 200:
                d = r.json()
                if d.get("final_output_active"):
                    return "marker"
                if not d.get("processing"):
                    # Generation ended without triggering the affordance flag.
                    # Give a short grace period in case the flag file is written
                    # just after the lock file disappears.
                    time.sleep(0.8)
                    r2 = client.get("/api/chat/stream_status")
                    if r2.status_code == 200 and r2.json().get("final_output_active"):
                        return "marker"
                    return "done_no_marker"
        except Exception as exc:
            print(f"[{ts()}] poll_affordance error: {exc}")
        time.sleep(0.4)
    return "timeout"


# ---------------------------------------------------------------------------
# Single-test runner
# ---------------------------------------------------------------------------

def run_test(client: APIClient, prompt: str, index: int) -> dict:
    result = {
        "index":             index,
        "prompt":            prompt,
        "started_at":        ts(),
        "marker_detected":   False,
        "affordance_result": "",
        "raw_output":        "",
        "stream_buffer":     "",
        "chat_files":        [],
        "status_at_end":     "",
        "elapsed_s":         0.0,
        "error":             "",
    }
    t0 = time.time()
    print(f"\n[{ts()}] ── Test {index}: {prompt[:60]!r}")

    # A. Clear chat history before this loop (only current-loop pairs shown to LLM)
    try:
        client.delete("/api/chat")
        print(f"[{ts()}]   Pre-test chat history cleared.")
    except Exception as exc:
        print(f"[{ts()}]   WARNING: pre-test clear failed: {exc}")

    # B. Wait for model idle before injecting
    status = poll_llm_status(client, {"idle"}, timeout=60)
    if status != "idle":
        result["error"] = f"Model not idle before inject (status={status!r})"
        result["elapsed_s"] = round(time.time() - t0, 2)
        return result

    # C. Inject the message via API (goes through full scheduler → DSManager pipeline)
    print(f"[{ts()}]   Injecting prompt via /api/chat...")
    try:
        r = client.post("/api/chat", data={"message": prompt})
        if r.status_code not in (200, 201):
            result["error"] = f"/api/chat returned {r.status_code}: {r.json()}"
            result["elapsed_s"] = round(time.time() - t0, 2)
            return result
        print(f"[{ts()}]   Prompt accepted (HTTP {r.status_code}).")
    except Exception as exc:
        result["error"] = f"Failed to inject message: {exc}"
        result["elapsed_s"] = round(time.time() - t0, 2)
        return result

    # D. Wait for the affordance trigger (##AF: FINAL_OUTPUT## marker)
    print(f"[{ts()}]   Waiting for ##AF: FINAL_OUTPUT## (timeout={AFFORDANCE_TIMEOUT}s)...")
    af_result = poll_affordance(client, AFFORDANCE_TIMEOUT)
    result["affordance_result"] = af_result
    result["marker_detected"]   = af_result == "marker"
    print(f"[{ts()}]   Affordance result: {af_result}")

    # E. Wait for generation to fully complete
    print(f"[{ts()}]   Waiting for generation complete (timeout={GENERATION_TIMEOUT}s)...")
    end_status = poll_llm_status(client, {"idle", "error", "stopped"}, GENERATION_TIMEOUT)
    result["status_at_end"] = end_status or "timeout"
    print(f"[{ts()}]   Final LLM status: {result['status_at_end']}")

    # F. Snapshot outputs
    result["raw_output"]   = read_file_safe(RAW_OUTPUT)
    result["stream_buffer"] = read_file_safe(STREAM_BUFFER)
    result["chat_files"]   = list_recent_chat_files()

    # G. Wipe chat history after final gen (loop complete — clear for next cycle)
    try:
        client.delete("/api/chat")
        print(f"[{ts()}]   Post-gen chat history wiped.")
    except Exception as exc:
        print(f"[{ts()}]   WARNING: post-gen clear failed: {exc}")

    result["elapsed_s"] = round(time.time() - t0, 2)
    print(f"[{ts()}]   Test {index} complete in {result['elapsed_s']}s.")
    return result


# ---------------------------------------------------------------------------
# Backend log collector
# ---------------------------------------------------------------------------

def collect_backend_log() -> str:
    """
    Read all log chunks from the most recent DiskJournalLogger session.
    These include model_runner stdout/stderr (source=WorkerOut/WorkerErr)
    as well as all backend API events.
    """
    logs_dir = Path(REPO_ROOT) / "logs"
    if not logs_dir.exists():
        return "(no logs directory)"

    sessions = sorted(logs_dir.glob("session_*"), key=lambda p: p.name, reverse=True)
    if not sessions:
        return "(no log sessions found)"

    session = sessions[0]
    lines = []
    for chunk in sorted(session.glob("chunk_*.log")):
        try:
            for raw in chunk.read_text(encoding="utf-8", errors="replace").splitlines():
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    e = json.loads(raw)
                    lines.append(
                        f"[{e.get('ts','')}] [{e.get('source','?'):10s}] "
                        f"{e.get('level','?'):7s}: {e.get('msg','')}"
                    )
                except Exception:
                    lines.append(raw)
        except Exception:
            pass

    return "\n".join(lines) if lines else "(log sessions found but no content)"


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

def build_report(test_results: list, started_at: str, preset_id: str,
                 preset_cfg: dict, backend_log: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    L = []

    L.append("# LYRN-AI Live Debug Report")
    L.append(
        f"**Generated:** {now}  |  **Started:** {started_at}  "
        f"|  **Preset:** {preset_id}  |  **Model:** {preset_cfg.get('model_path', 'unknown')}"
    )
    L.append("")

    # Summary table
    L.append("## Results Summary")
    L.append("")
    L.append("| # | Prompt (truncated) | Elapsed | Marker | Affordance result | Status | Error |")
    L.append("|---|--------------------|---------|--------|-------------------|--------|-------|")
    for r in test_results:
        marker  = "✓" if r["marker_detected"] else "✗"
        err_str = (r["error"][:38] + "…") if len(r.get("error","")) > 38 else (r.get("error","") or "—")
        L.append(
            f"| {r['index']} | {r['prompt'][:38]!r} | {r['elapsed_s']}s "
            f"| {marker} | {r.get('affordance_result','')} | {r['status_at_end']} | {err_str} |"
        )
    L.append("")

    # Per-test details
    for r in test_results:
        L.append("---")
        L.append(f"## Test {r['index']}: {r['prompt']}")
        L.append(f"**Started:** {r['started_at']}  **Elapsed:** {r['elapsed_s']}s")
        if r.get("error"):
            L.append(f"\n> **ERROR:** {r['error']}\n")
        L.append(f"- Affordance marker detected: `{r['marker_detected']}`  ({r.get('affordance_result','')})")
        L.append(f"- LLM status at end: `{r['status_at_end']}`")

        L.append("\n### Raw LLM Output (pre- and post-marker)")
        raw = r.get("raw_output", "")
        if raw.strip():
            L.append("```")
            L.append(raw.strip()[:3000])
            if len(raw) > 3000:
                L.append(f"… [{len(raw)-3000} more chars truncated]")
            L.append("```")
        else:
            L.append("_(empty — model did not produce output)_")

        L.append("\n### Stream Buffer (post-marker / user-visible output)")
        buf = r.get("stream_buffer", "")
        if buf.strip():
            L.append("```")
            L.append(buf.strip()[:2000])
            if len(buf) > 2000:
                L.append(f"… [{len(buf)-2000} more chars truncated]")
            L.append("```")
        else:
            L.append("_(empty — affordance marker not emitted or not yet detected)_")

        L.append("\n### Chat History Files (should be empty — wiped after each gen)")
        chat_files = r.get("chat_files", [])
        if chat_files:
            for cf in chat_files:
                try:
                    content = Path(cf).read_text(encoding="utf-8", errors="replace")
                    L.append(f"**{os.path.basename(cf)}:**")
                    L.append("```")
                    L.append(content.strip()[:1000])
                    L.append("```")
                except Exception as exc:
                    L.append(f"_(could not read {cf}: {exc})_")
        else:
            L.append("_(none found — history correctly wiped)_")
        L.append("")

    # output_log.jsonl
    L.append("---")
    L.append("## output_log.jsonl (last 5 generation entries)")
    try:
        entries = [ln for ln in Path(OUTPUT_LOG).read_text(encoding="utf-8").splitlines() if ln.strip()]
        for raw_entry in entries[-5:]:
            try:
                e = json.loads(raw_entry)
                L.append(f"\n**{e.get('timestamp','')}** — `{e.get('user_message','')[:60]}`")
                L.append(f"- marker_detected: `{e.get('marker_detected')}`")
                L.append(f"- final_output: `{str(e.get('final_output',''))[:120]}`")
            except Exception:
                L.append(f"  {raw_entry[:120]}")
    except Exception:
        L.append("_(output_log.jsonl not found or empty)_")
    L.append("")

    # Backend log (start_lyrn.py + model_runner.py via DiskJournalLogger)
    L.append("---")
    L.append("## Backend Log  (start_lyrn.py + model_runner.py via DiskJournalLogger)")
    L.append("_WorkerOut/WorkerErr entries are model_runner.py stdout/stderr captured by WorkerController._")
    L.append("")
    log_tail = backend_log[-10000:] if len(backend_log) > 10000 else backend_log
    L.append("```")
    L.append(log_tail)
    if len(backend_log) > 10000:
        L.append(f"\n… [first {len(backend_log)-10000} chars omitted — showing last 10 000]")
    L.append("```")

    return "\n".join(L)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="LYRN-AI Live Debug Runner (API-driven)")
    parser.add_argument("--preset", default=DEFAULT_PRESET,
                        help="Model preset ID to test (default: 1)")
    args, _ = parser.parse_known_args()
    preset_id = args.preset

    print(section("LYRN-AI Live Debug Runner"))
    print(f"Repo root:  {REPO_ROOT}")
    print(f"Preset:     {preset_id}")

    server_url = detect_server_url()
    token = detect_token()
    print(f"Server:     {server_url}")
    print(f"Auth mode:  {'no-auth' if token == 'no-auth' else 'token'}")

    client = APIClient(server_url, token)

    # Verify server is reachable
    try:
        r = client.get("/health")
        if r.status_code != 200:
            print(f"ERROR: Server returned HTTP {r.status_code}. Is start_lyrn.py running?")
            sys.exit(1)
        print(f"Server:     reachable (health check OK)")
    except Exception as exc:
        print(f"ERROR: Cannot reach server at {server_url}: {exc}")
        sys.exit(1)

    # Load and apply preset
    try:
        r = client.get("/api/config/presets")
        presets = r.json()
    except Exception as exc:
        print(f"ERROR: Could not load presets: {exc}")
        sys.exit(1)

    if preset_id not in presets:
        print(f"ERROR: Preset '{preset_id}' not found. Available: {list(presets.keys())}")
        sys.exit(1)

    preset_cfg = presets[preset_id]
    print(f"Model:      {preset_cfg.get('model_path', 'unknown')}")

    try:
        r = client.post("/api/config/active", data={"config": preset_cfg})
        print(f"Preset {preset_id} applied (HTTP {r.status_code}).")
    except Exception as exc:
        print(f"ERROR: Could not apply preset: {exc}")
        sys.exit(1)

    os.makedirs(REPORT_DIR, exist_ok=True)
    started_at   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    test_results = []

    # Start the worker (tolerate "already running")
    try:
        r = client.post("/api/system/start_worker")
        msg = r.json().get("message", "")
        print(f"[{ts()}] start_worker → {msg}")
    except Exception as exc:
        print(f"[{ts()}] start_worker note: {exc}")

    # Wait for model ready
    print(f"[{ts()}] Waiting for model to reach idle (timeout={MODEL_LOAD_TIMEOUT}s)...")
    status = poll_llm_status(client, {"idle"}, MODEL_LOAD_TIMEOUT)
    if status != "idle":
        print(f"[{ts()}] ERROR: Model did not reach idle within {MODEL_LOAD_TIMEOUT}s.")
        backend_log = collect_backend_log()
        report = build_report([], started_at, preset_id, preset_cfg, backend_log)
        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = os.path.join(REPORT_DIR, f"debug_{ts_str}_LOAD_FAILED.md")
        Path(report_path).write_text(report, encoding="utf-8")
        print(f"[{ts()}] Partial failure report → {report_path}")
        sys.exit(1)

    print(f"[{ts()}] Model is idle and ready.")
    print(f"[{ts()}] Settling wait: {POST_LOAD_WAIT}s...")
    time.sleep(POST_LOAD_WAIT)

    # Run 3 test prompts
    for i, prompt in enumerate(TEST_PROMPTS, 1):
        result = run_test(client, prompt, i)
        test_results.append(result)
        if i < len(TEST_PROMPTS):
            print(f"[{ts()}] Pausing 3s before next test...")
            time.sleep(3)

    # Collect backend logs
    print(f"\n[{ts()}] Collecting backend logs from DiskJournalLogger...")
    backend_log = collect_backend_log()
    print(f"[{ts()}] Collected {len(backend_log):,} chars of log data.")

    # Write final report
    ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(REPORT_DIR, f"debug_{ts_str}.md")
    report_text = build_report(test_results, started_at, preset_id, preset_cfg, backend_log)
    Path(report_path).write_text(report_text, encoding="utf-8")

    markers_ok = sum(1 for r in test_results if r["marker_detected"])
    print(f"\n{'='*60}")
    print(f"  Report:          {report_path}")
    print(f"  Markers emitted: {markers_ok}/{len(test_results)}")
    errors = sum(1 for r in test_results if r.get("error"))
    if errors:
        print(f"  Errors:          {errors}/{len(test_results)}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
