"""
ARCHER Terminal Manager (Phase 6, Spec Section 9).

Provides a real interactive PowerShell session via pywinpty:
- Shared between Col (direct keyboard typing via xterm.js) and ARCHER.
- ARCHER commands run visibly in the same session, marked with cyan [ARCHER] tag.
- Output streams live to all connected WebSocket clients.
- Non-blocking daemon reader thread with queue and timeouts (never hangs).
- Full HALT integration (sends Ctrl+C to abort running command).
- Session survives tab switching and reconnects.
"""

from __future__ import annotations

import collections
import queue
import re
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from loguru import logger
from winpty import PtyProcess

from archer.core.event_bus import Event, EventType, get_event_bus


# ANSI regex to clean terminal escape codes when summarizing for the agent
_ANSI_ESCAPE_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


class _TerminalStreamReader:
    """Daemon thread reading PTY output into a queue and broadcast handler without blocking."""

    def __init__(self, pty: PtyProcess, on_chunk: Optional[Callable[[str], None]] = None) -> None:
        self.pty = pty
        self.on_chunk = on_chunk
        self.q: queue.Queue[str] = queue.Queue(maxsize=10000)
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True, name="Terminal-StreamReader")
        self.thread.start()

    def _run(self) -> None:
        while not self.stopped.is_set():
            try:
                if not self.pty.isalive():
                    break
                chunk = self.pty.read(1024)
                if not chunk:
                    break
                self.q.put(chunk)
                if self.on_chunk:
                    try:
                        self.on_chunk(chunk)
                    except Exception as e:
                        logger.debug(f"[TerminalStreamReader] Broadcast error: {e}")
            except (EOFError, Exception):
                break

    def stop(self) -> None:
        self.stopped.set()


class TerminalManager:
    """Manages the single persistent interactive PowerShell terminal session."""

    _instance: Optional[TerminalManager] = None
    _singleton_lock = threading.Lock()

    def __new__(cls) -> TerminalManager:
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return

        self._lock = threading.Lock()
        self._pty: Optional[PtyProcess] = None
        self._reader: Optional[_TerminalStreamReader] = None
        self._history_buffer: collections.deque[str] = collections.deque(maxlen=100000)
        self._broadcast_cb: Optional[Callable[[str], None]] = None
        self._bus = get_event_bus()
        self._in_flight_cmd_id: Optional[str] = None
        self._in_flight_lock = threading.Lock()

        # Subscribe to HALT event to interrupt running command
        self._bus.subscribe_halt(self.on_halt)

        self._initialized = True

    def set_broadcast_callback(self, cb: Optional[Callable[[str], None]]) -> None:
        """Register the WebSocket broadcast callback to push chunks to clients."""
        self._broadcast_cb = cb

    def _on_chunk_received(self, chunk: str) -> None:
        """Handle new chunk from reader thread: store in history and broadcast."""
        for ch in chunk:
            self._history_buffer.append(ch)

        if self._broadcast_cb:
            try:
                self._broadcast_cb(chunk)
            except Exception as e:
                logger.debug(f"[TerminalManager] Broadcast callback failed: {e}")

    def is_alive(self) -> bool:
        """Check if the PowerShell session is currently running."""
        with self._lock:
            return self._pty is not None and self._pty.isalive()

    def start(self, cols: int = 80, rows: int = 24) -> bool:
        """Start or ensure the single persistent PowerShell session is running."""
        with self._lock:
            if self._pty is not None and self._pty.isalive():
                return True

            try:
                repo_root = str(Path(__file__).resolve().parents[3])
                # Spawn PowerShell in repository root
                self._pty = PtyProcess.spawn(
                    ["powershell.exe", "-NoLogo"],
                    dimensions=(rows, cols),
                    cwd=repo_root,
                )
                self._reader = _TerminalStreamReader(self._pty, on_chunk=self._on_chunk_received)
                logger.info(f"[TerminalManager] PowerShell session started (PID: {self._pty.pid}) in {repo_root}")
                return True
            except Exception as e:
                logger.error(f"[TerminalManager] Failed starting PowerShell PTY: {e}")
                self._pty = None
                self._reader = None
                return False

    def stop(self) -> None:
        """Terminate the running PowerShell session."""
        with self._lock:
            if self._reader:
                self._reader.stop()
                self._reader = None

            if self._pty:
                try:
                    if self._pty.isalive():
                        self._pty.terminate(force=True)
                except Exception as e:
                    logger.debug(f"[TerminalManager] Terminate exception: {e}")
                self._pty = None

    def restart(self, cols: int = 80, rows: int = 24) -> bool:
        """Restart the PowerShell session."""
        self.stop()
        time.sleep(0.1)
        return self.start(cols=cols, rows=rows)

    def write(self, data: str) -> None:
        """Write raw keyboard input directly to the PTY (used by Col)."""
        with self._lock:
            if not self._pty or not self._pty.isalive():
                self.start()

            if self._pty and self._pty.isalive():
                try:
                    self._pty.write(data)
                except Exception as e:
                    logger.error(f"[TerminalManager] Write error: {e}")

    def resize(self, cols: int, rows: int) -> None:
        """Resize terminal dimensions to match xterm.js viewport."""
        with self._lock:
            if self._pty and self._pty.isalive():
                try:
                    cols = max(10, min(cols, 500))
                    rows = max(5, min(rows, 200))
                    self._pty.setwinsize(rows, cols)
                except Exception as e:
                    logger.debug(f"[TerminalManager] Resize error: {e}")

    def get_history(self) -> str:
        """Return buffered terminal output for newly connected clients."""
        return "".join(self._history_buffer)

    def on_halt(self, event: Optional[Event] = None) -> None:
        """Interrupt any running command on HALT by sending Ctrl+C."""
        with self._lock:
            if self._pty and self._pty.isalive():
                try:
                    logger.warning("[TerminalManager] HALT received: sending Ctrl+C to terminal.")
                    self._pty.write("\x03")
                except Exception as e:
                    logger.debug(f"[TerminalManager] Failed sending Ctrl+C on HALT: {e}")

        with self._in_flight_lock:
            self._in_flight_cmd_id = None

    def execute_archer_command(self, command: str, timeout: float = 30.0) -> Dict[str, Any]:
        """
        Execute an agent command inside the visible PowerShell terminal.
        - Clearly marks the command in cyan [ARCHER] tag.
        - Streams output live to the terminal.
        - Collects and returns the text output to the agent.
        - Gated by timeouts and respects HALT.
        """
        if not command or not command.strip():
            return {"error": "Empty command"}

        cmd_clean = command.strip()

        # Ensure terminal is running
        if not self.is_alive():
            started = self.start()
            if not started:
                return {"error": "Could not start terminal session"}
            time.sleep(0.5)

        cmd_id = uuid.uuid4().hex[:8]
        start_marker = f"__ARCHER_START__:{cmd_id}"
        end_marker = f"__ARCHER_END__:{cmd_id}"

        with self._in_flight_lock:
            self._in_flight_cmd_id = cmd_id

        # Wrap command with cyan [ARCHER] tag and completion markers.
        # Note: Markers are split ("__ARCHER_" + "...") in the PowerShell string
        # so the interactive PTY's input echo does not trigger marker matching prematurely.
        cmd_display = cmd_clean.replace("'", "''")
        full_script = (
            f'Write-Host ("__ARCHER_" + "START__:{cmd_id}"); '
            f'Write-Host -ForegroundColor Cyan "[ARCHER]" -NoNewline; Write-Host (\' \' + \'{cmd_display}\'); '
            f'{cmd_clean}; '
            f'Write-Host ("`n__ARCHER_" + "END__:{cmd_id}:exit=" + $?)\r\n'
        )

        # Clear reader queue before execution to capture only this command's output
        if self._reader:
            while not self._reader.q.empty():
                try:
                    self._reader.q.get_nowait()
                except queue.Empty:
                    break

        # Send command into visible PTY
        self.write(full_script)

        # Read output with timeout
        collected_chunks: list[str] = []
        start_t = time.time()
        completed = False
        exit_success = True

        while time.time() - start_t < timeout:
            with self._in_flight_lock:
                if self._in_flight_cmd_id != cmd_id:
                    # Cancelled by HALT
                    return {
                        "status": "halted",
                        "error": "Command interrupted by HALT",
                        "output": "".join(collected_chunks),
                    }

            if not self._reader:
                break

            try:
                chunk = self._reader.q.get(timeout=0.1)
                collected_chunks.append(chunk)

                combined = "".join(collected_chunks)
                if end_marker in combined:
                    completed = True
                    # Check exit status
                    if f"{end_marker}:exit=False" in combined:
                        exit_success = False
                    break
            except queue.Empty:
                continue

        with self._in_flight_lock:
            if self._in_flight_cmd_id == cmd_id:
                self._in_flight_cmd_id = None

        raw_output = "".join(collected_chunks)

        # Extract content between start_marker and end_marker if present
        if start_marker in raw_output and end_marker in raw_output:
            raw_slice = raw_output.split(start_marker, 1)[1].split(end_marker, 1)[0]
        else:
            raw_slice = raw_output

        # Clean text for agent reading (strip ANSI control sequences)
        clean_text = _ANSI_ESCAPE_RE.sub("", raw_slice)

        # Remove header/tag line and empty lines from clean text
        clean_lines = [
            line for line in clean_text.splitlines()
            if end_marker not in line and start_marker not in line and "[ARCHER]" not in line and line.strip()
        ]
        summary_text = "\n".join(clean_lines).strip()

        if not completed:
            # Timed out — send Ctrl+C to cancel command
            self.write("\x03")
            return {
                "status": "timeout",
                "error": f"Command timed out after {int(timeout)} seconds",
                "output": summary_text,
                "raw": raw_output,
            }

        return {
            "status": "success" if exit_success else "failed",
            "command": cmd_clean,
            "output": summary_text,
            "success": exit_success,
        }


_terminal_manager: Optional[TerminalManager] = None


def get_terminal_manager() -> TerminalManager:
    """Get the singleton TerminalManager instance."""
    global _terminal_manager
    if _terminal_manager is None:
        _terminal_manager = TerminalManager()
    return _terminal_manager
