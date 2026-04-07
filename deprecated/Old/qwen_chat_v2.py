"""
Enhanced Graphical chat interface for interacting with a Qwen chat model via llama-cpp.

This version saves the conversation fully on disk as chat files per turn,
and reconstructs the entire chat context on each generation from those files,
thus avoiding any long-term in-memory chat list and preserving KV cache behavior.
"""

import os
import tkinter as tk
from tkinter import scrolledtext
from threading import Thread
from typing import List
from llama_cpp import Llama
import queue
from datetime import datetime

# -----------------------------------------------------------------------------
# MODEL INITIALISATION

# Use Vulkan GPU backend for llama-cpp
os.environ["LLAMA_BACKEND"] = "vulkan"

llm = Llama(
    model_path="D:\LLMs\models\Qwen.Qwen3-4B-Thinking-2507.Q4_K_M.gguf",
    n_ctx=32000,
    n_threads=22,
    n_gpu_layers=36,
    use_mlock=True,
    use_mmap=False,
    chat_format="qwen",
    add_bos=True,
    add_eos=True,
    verbose=True,
)

# -----------------------------------------------------------------------------
# PROMPT CONSTRUCTION

def safe_read(path: str, label: str, required: bool = True) -> str:
    if not os.path.exists(path):
        if required:
            return f"[⚠️ Missing {label}]"
        else:
            return ""
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read().strip()

def load_chat_files_sorted(chat_folder: str) -> List[str]:
    """Load all chat files sorted chronologically from the chat folder."""
    if not os.path.isdir(chat_folder):
        return []

    files = [f for f in os.listdir(chat_folder) if f.startswith("chat_") and f.endswith(".txt")]
    files.sort()  # Sort by filename which contains timestamp
    contents = []
    for fname in files:
        path = os.path.join(chat_folder, fname)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = fh.read().strip()
                if data:
                    contents.append(data)
        except Exception as e:
            print(f"[Warning] Failed to read chat file `{fname}`: {e}")
    return contents

def build_full_prompt(chat_folder: str) -> str:
    """Construct full prompt from static snapshots + chunk + all chat messages."""
    prompt_lines = []

    prompt_lines.append("=== RELATIONAL INDEX ===")
    prompt_lines.append(safe_read("D:/LLMs/snapshots/static_snapshot.txt", "static snapshot"))
    prompt_lines.append("")

    prompt_lines.append("=== ACTIVE JOB SNAPSHOT ===")
    prompt_lines.append(safe_read("D:/LLMs/snapshots/job_snapshot_01.txt", "job snapshot"))
    prompt_lines.append("")

    chunk_content = safe_read("D:/LLMs/chunk/chunk.txt", "chunk.txt", required=False)
    if chunk_content:
        prompt_lines.append("=== ACTIVE CONVERSATION CHUNK ===")
        prompt_lines.append(chunk_content)
        prompt_lines.append("")

    end_notice = safe_read("D:/LLMs/chunk_notice_end.txt", "chunk_notice_end.txt", required=False)
    if end_notice:
        prompt_lines.append("=== END CHUNK NOTICE ===")
        prompt_lines.append(end_notice)
        prompt_lines.append("")

    chat_contents = load_chat_files_sorted(chat_folder)
    if chat_contents:
        prompt_lines.append("=== CHAT HISTORY ===")
        prompt_lines.extend(chat_contents)
        prompt_lines.append("")
    else:
        prompt_lines.append("[⚠️ No chat history found in chat folder]")
        prompt_lines.append("")

    return "\n".join(prompt_lines)

# -----------------------------------------------------------------------------
# STREAMING QUEUE AND HANDLER

stream_queue = queue.Queue()

class StreamingHandler:
    """Handles streaming tokens and sends updates to GUI queue."""
    def __init__(self, gui_queue):
        self.gui_queue = gui_queue
        self.current_response = ""

    def handle_token(self, token_data):
        # Extract text content from streaming token data
        if 'choices' in token_data and len(token_data['choices']) > 0:
            delta = token_data['choices'][0].get('delta', {})
            content = delta.get('content', '')
            if content:
                self.current_response += content
                # Send new token to GUI queue
                self.gui_queue.put(('token', content))

        # Check if streaming finished
        if 'choices' in token_data and len(token_data['choices']) > 0:
            finish_reason = token_data['choices'][0].get('finish_reason')
            if finish_reason is not None:
                self.gui_queue.put(('finished', self.current_response))

    def get_response(self) -> str:
        return self.current_response

# -----------------------------------------------------------------------------
# GUI EVENT HANDLERS

def on_send() -> None:
    user_text = input_box.get("1.0", tk.END).strip()
    if not user_text:
        return

    chat_folder = "D:/LLMs/chat"   # Use chat folder for conversation files
    os.makedirs(chat_folder, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    chat_filename = os.path.join(chat_folder, f"chat_{timestamp}.txt")

    # Save user message first to file
    with open(chat_filename, "w", encoding="utf-8") as f:
        f.write("user\n")
        f.write(user_text + "\n\nmodel\n")

    # Display user message in GUI
    context_display.insert(tk.END, f"\n>>> {user_text}\n", "user_input")
    context_display.see(tk.END)
    context_display.update()

    # Clear input and disable send button during generation
    input_box.delete("1.0", tk.END)
    send_button.config(state=tk.DISABLED)

    def generate_stream():
        try:
            # Build the full prompt from static snapshots + all chat files
            full_prompt = build_full_prompt(chat_folder)

            # Prepare messages for llama-cpp with system role
            messages = [{"role": "system", "content": full_prompt}]

            handler = StreamingHandler(stream_queue)

            # Stream response from the model
            stream = llm.create_chat_completion(
                messages=messages,
                max_tokens=4096,
                temperature=0.7,
                top_p=0.95,
                top_k=40,
                stream=True,
            )

            # Append tokens progressively to the chat file while streaming
            with open(chat_filename, "a", encoding="utf-8") as f:
                for token_data in stream:
                    handler.handle_token(token_data)
                    # Append token text to the chat file
                    if 'choices' in token_data and len(token_data['choices']) > 0:
                        delta = token_data['choices'][0].get('delta', {})
                        content = delta.get('content', '')
                        if content:
                            f.write(content)
                            f.flush()

            # Add newline after finishing response for readability
            with open(chat_filename, "a", encoding="utf-8") as f:
                f.write("\n")

        except Exception as e:
            stream_queue.put(('error', str(e)))
        finally:
            stream_queue.put(('enable_button', ''))

    # Run model generation in a background thread
    Thread(target=generate_stream, daemon=True).start()

def process_stream_queue():
    """Process streaming updates from queue on main GUI thread."""
    try:
        while True:
            try:
                message_type, content = stream_queue.get_nowait()
                if message_type == 'token':
                    context_display.insert(tk.END, content, "ai_output")
                    context_display.see(tk.END)
                    context_display.update_idletasks()
                elif message_type == 'finished':
                    context_display.insert(tk.END, "\n", "ai_output")
                    context_display.see(tk.END)
                elif message_type == 'error':
                    context_display.insert(tk.END, f"\n[Error: {content}]\n", "error")
                    context_display.see(tk.END)
                elif message_type == 'enable_button':
                    send_button.config(state=tk.NORMAL)
            except queue.Empty:
                break
    except Exception as e:
        print(f"Error processing stream queue: {e}")
    root.after(50, process_stream_queue)  # Check queue every 50ms

# -----------------------------------------------------------------------------
# GUI LAYOUT

root = tk.Tk()
root.title("LYRN Runtime Console - Enhanced Streaming")
root.geometry("900x750")
root.configure(bg="#1e1e1e")

# Chat display widget
context_display = scrolledtext.ScrolledText(
    root,
    wrap=tk.WORD,
    height=35,
    font=("Consolas", 11),
    bg="#1e1e1e",
    fg="#ffffff",
    insertbackground="white",
)
context_display.tag_config("user_input", foreground="lime")
context_display.tag_config("ai_output", foreground="orange")
context_display.tag_config("error", foreground="red")
context_display.pack(padx=10, pady=(10, 0), fill=tk.BOTH, expand=True)

# Input box
input_box = tk.Text(
    root,
    height=4,
    font=("Consolas", 11),
    bg="#2a2a2a",
    fg="white",
    insertbackground="white",
)
input_box.pack(padx=10, pady=(5, 0), fill=tk.X)

# Bind Enter key (with Shift+Enter for newline)
def on_enter_key(event):
    if event.state & 0x1:  # Shift pressed
        return  # Insert newline normally
    on_send()
    return "break"  # Prevent newline on Enter

input_box.bind("<Return>", on_enter_key)

# Send button
send_button = tk.Button(
    root,
    text="Send",
    command=on_send,
    font=("Arial", 11, "bold"),
    bg="#333",
    fg="white",
)
send_button.pack(padx=10, pady=(5, 10), fill=tk.X)

# Initial welcome text
context_display.insert(
    tk.END,
    "LYRN Runtime Console - Enhanced Streaming Version\n"
    "Features: Real-time streaming output, optional chunk handling\n\n",
    "ai_output",
)

# Start checking the streaming queue
root.after(100, process_stream_queue)

# Run the main event loop
root.mainloop()
