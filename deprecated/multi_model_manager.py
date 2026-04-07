import sys
import subprocess
import time
import shutil
from pathlib import Path

class MultiModelManager:
    def __init__(self, script_dir):
        self.script_dir = script_dir
        self.ipc_base_dir = Path(script_dir) / "ipc"
        self.active_models = {}  # key: tab_name, value: { 'process': Popen, 'ipc_path': Path, 'ipc_id': str }

    def launch_model(self, tab_name: str, model_settings: dict):
        if tab_name in self.active_models:
            print(f"Model for '{tab_name}' is already running.")
            return False, "Model for this tab is already running."

        # Generate a unique IPC ID based on the tab name or a counter
        ipc_id = f"agent_{tab_name.replace(' ', '_')}_{int(time.time())}"
        ipc_path = self.ipc_base_dir / ipc_id
        prompts_path = ipc_path / "prompts"
        responses_path = ipc_path / "responses"

        try:
            prompts_path.mkdir(parents=True, exist_ok=True)
            responses_path.mkdir(parents=True, exist_ok=True)

            model_path = model_settings.get("model_path")
            if not model_path or not Path(model_path).exists():
                raise ValueError(f"Model path is invalid or does not exist: {model_path}")

            command = [
                sys.executable, "model_loader.py",
                "--model-path", str(model_path),
                "--n_ctx", str(model_settings.get("n_ctx", 8192)),
                "--n_threads", str(model_settings.get("n_threads", 8)),
                "--n_gpu_layers", str(model_settings.get("n_gpu_layers", 0)),
                "--ipc-id", ipc_id
            ]

            print(f"Launching model for '{tab_name}' with command: {' '.join(command)}")

            creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=creation_flags
            )

            time.sleep(4)
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                raise RuntimeError(f"Model loader process for '{tab_name}' failed to start.\nStderr: {stderr}\nStdout: {stdout}")

            self.active_models[tab_name] = {
                'process': process,
                'ipc_path': ipc_path,
                'ipc_id': ipc_id,
                'settings': model_settings
            }
            print(f"Model for '{tab_name}' launched successfully. PID: {process.pid}")
            return True, "Model launched successfully."

        except Exception as e:
            error_message = f"Error launching model for '{tab_name}': {e}"
            print(error_message)
            if 'ipc_path' in locals() and ipc_path.exists():
                shutil.rmtree(ipc_path)
            return False, error_message

    def terminate_model(self, tab_name: str):
        if tab_name not in self.active_models:
            print(f"No model found for tab '{tab_name}'.")
            return

        model_info = self.active_models[tab_name]
        process = model_info['process']
        ipc_path = model_info['ipc_path']

        print(f"Terminating model for '{tab_name}' (PID: {process.pid})...")
        try:
            process.terminate()
            process.wait(timeout=5)
            print(f"Model for '{tab_name}' terminated.")
        except Exception as e:
            print(f"Could not terminate model for '{tab_name}' gracefully, killing. Error: {e}")
            process.kill()

        if ipc_path.exists():
            try:
                shutil.rmtree(ipc_path)
                print(f"Cleaned up IPC directory: {ipc_path}")
            except Exception as e:
                print(f"Error cleaning up IPC directory {ipc_path}: {e}")

        del self.active_models[tab_name]

    def terminate_all_models(self):
        print("Terminating all active models...")
        for tab_name in list(self.active_models.keys()):
            self.terminate_model(tab_name)

    def get_model_info(self, tab_name: str) -> dict:
        return self.active_models.get(tab_name)
