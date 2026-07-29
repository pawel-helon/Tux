"""Ollama installation, process lifecycle, and model operations."""

import os
import shutil
import signal
import subprocess
import time

from tux.state import ollama_pid_path
from tux.system import LINUX, TERMUX

OLLAMA_INSTALL_URL = "https://ollama.com/install.sh"

class OllamaRuntime:
    """Manage the Ollama CLI and a server process owned by the current tux run."""

    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._system = LINUX
        self._started = False

    def is_installed(self) -> bool:
        return shutil.which("ollama") is not None

    def install(self, system: str) -> None:
        if system == TERMUX:
            subprocess.run(["pkg", "install", "-y", "ollama"], check=True)
            return
        subprocess.run(
            f"curl -fsSL {OLLAMA_INSTALL_URL} | sh",
            shell=True,
            check=True,
        )

    def is_ready(self) -> bool:
        try:
            subprocess.run(
                ["ollama", "list"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=5,
            )
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False
        return True

    def start_server(self, system: str) -> bool:
        """Start Ollama if needed and remember ownership for cleanup."""
        self._system = system
        if self.is_ready():
            return False
        self._process = subprocess.Popen(
            ["ollama", "serve"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self._started = True
        if system == LINUX:
            path = ollama_pid_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(self._process.pid), encoding="utf-8")
        self.wait_until_ready()
        return True

    def wait_until_ready(self) -> None:
        for _ in range(30):
            if self.is_ready():
                return
            if self._process is not None and self._process.poll() is not None:
                raise RuntimeError("Ollama server exited before becoming ready")
            time.sleep(1)
        raise RuntimeError("Ollama did not become ready")

    def stop_server(self) -> None:
        """Stop only an Ollama server started by this runtime instance."""
        if not self._started:
            return
        process = self._process
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
        if self._system == LINUX:
            ollama_pid_path().unlink(missing_ok=True)
        self._started = False
        self._process = None

    def has_model(self, model: str) -> bool:
        result = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, check=True
        )
        names = [line.split()[0] for line in result.stdout.splitlines()[1:] if line.split()]
        return model in names

    def pull(self, model: str) -> None:
        subprocess.run(["ollama", "pull", model], check=True)
