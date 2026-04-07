import os
import sys
import json
import time
import asyncio
import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import uvicorn

app = FastAPI(title="LYRN Anthropic Proxy")

TRIGGER_FILE = "chat_trigger.txt"
CHAT_DIR = Path("chat")

def get_port():
    try:
        with open("port.txt", "r") as f:
            val = f.read().strip()
            if val.isdigit():
                return int(val) + 1
    except:
        pass
    return 8001

def trigger_generation(messages):
    """Writes the chat context to a file and triggers model_runner.py"""
    CHAT_DIR.mkdir(exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"chat/claude_{timestamp}.txt"
    filepath = os.path.abspath(filename)

    # Format messages for the prompt
    prompt = ""
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        # Handle cases where content might be a list (Claude Code format)
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            content = "\n".join(text_parts)
        prompt += f"{role}\n{content}\n\n"

    prompt += "assistant\n"

    # Write the user content format for model_runner to pick up.
    # It expects: user\n{message}\n
    # Since Claude sends the entire history, we inject the formatted history as the "user message"
    # model_runner.py will treat this as a single large user turn if we don't format it right,
    # but since it evaluates history based on chat_manager (which reads files),
    # writing a custom file might bypass standard history.
    # Let's format it as a single file containing the full transcript.
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(prompt)

    with open(TRIGGER_FILE, "w", encoding="utf-8") as f:
        f.write(filepath)

    return filepath

async def read_and_stream(filepath: str, request: Request):
    """Polls the file and yields Anthropic-compatible SSE events."""
    last_pos = 0
    started = False

    # Send initial event
    yield f"event: message_start\ndata: {json.dumps({'type': 'message_start', 'message': {'id': 'msg_1', 'type': 'message', 'role': 'assistant', 'content': [], 'model': 'lyrn', 'stop_reason': None, 'stop_sequence': None, 'usage': {'input_tokens': 0, 'output_tokens': 0}}})}\n\n"
    yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}})}\n\n"

    while True:
        if await request.is_disconnected():
            # Stop generation if client disconnects
            with open("stop_trigger.txt", "w", encoding="utf-8") as f:
                f.write("stop")
            break

        if not os.path.exists(filepath):
            await asyncio.sleep(0.1)
            continue

        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

            if not started:
                # Look for model turn marker
                start_idx = content.find("model\n")
                if start_idx != -1:
                    last_pos = start_idx + 6
                    started = True
                else:
                    await asyncio.sleep(0.1)
                    continue

            if started:
                current_len = len(content)
                if current_len > last_pos:
                    new_text = content[last_pos:]
                    last_pos = current_len

                    if "[Stopped]" in new_text or "[Error" in new_text:
                        new_text = new_text.replace("[Stopped]", "").replace("\n\nmodel\n", "")
                        # Yield remaining text before stopping
                        if new_text:
                           yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': new_text}})}\n\n"
                        break

                    yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': new_text}})}\n\n"

                else:
                    # Check if worker is idle indicating generation is complete
                    status = "unknown"
                    try:
                        with open("global_flags/llm_status.txt", "r") as sf:
                            status = sf.read().strip()
                    except:
                        pass

                    if status in ["idle", "error", "stopped"]:
                        break

        await asyncio.sleep(0.05)

    yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': 0})}\n\n"
    yield f"event: message_delta\ndata: {json.dumps({'type': 'message_delta', 'delta': {'stop_reason': 'end_turn', 'stop_sequence': None}, 'usage': {'output_tokens': 1}})}\n\n"
    yield f"event: message_stop\ndata: {json.dumps({'type': 'message_stop'})}\n\n"

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.get("/v1/models")
async def list_models():
    # Return a dummy model so tools like jq can detect it
    return {"data": [{"id": "lyrn-model"}]}

@app.post("/v1/messages")
async def messages(request: Request):
    body = await request.json()
    messages_list = body.get("messages", [])

    filepath = trigger_generation(messages_list)

    return StreamingResponse(
        read_and_stream(filepath, request),
        media_type="text/event-stream"
    )

if __name__ == "__main__":
    port = get_port()
    print(f"Starting Anthropic proxy on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
