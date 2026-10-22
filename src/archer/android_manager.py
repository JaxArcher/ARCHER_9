"""
ARCHER Android Emulator Manager (Phase 7b).

Manages lifecycle and gRPC streaming/control of the Google Android Emulator:
- Installation root: D:\\ARCHER_9\\data\\android (SDK in sdk/, AVDs in avd/)
- Isolated environment: ANDROID_HOME and ANDROID_AVD_HOME scoped only to child processes
- Headless execution: -no-window -camera-back none -camera-front none -no-audio
- Hardware acceleration: -gpu host (default) or -gpu software fallback
- gRPC bridge: token-authenticated loopback gRPC interface for screenshots and input events
- Graceful shutdown: Quick Boot snapshots preserved via gRPC SHUTDOWN / adb emu kill
"""

import asyncio
import base64
import glob
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, Any, Optional, Callable

import cv2
import grpc
import numpy as np

from archer.android_grpc import emulator_controller_pb2, emulator_controller_pb2_grpc

logger = logging.getLogger("archer-android")

BASE_DIR = Path(__file__).resolve().parents[2]
ANDROID_DIR = BASE_DIR / "data" / "android"
SDK_DIR = ANDROID_DIR / "sdk"
AVD_DIR = ANDROID_DIR / "avd"
JDK_DIR = ANDROID_DIR / "jdk"
LOGS_DIR = BASE_DIR / "logs"

EMULATOR_EXE = SDK_DIR / "emulator" / "emulator.exe"
ADB_EXE = SDK_DIR / "platform-tools" / "adb.exe"
EMU_LOG = LOGS_DIR / "android_emulator.log"

DEFAULT_GRPC_PORT = 8556
DISPLAY_WIDTH = 1080
DISPLAY_HEIGHT = 2400
STREAM_WIDTH = 400
STREAM_HEIGHT = 888


class AndroidEmulatorManager:
    """Manages the Android emulator instance, gRPC bridge, and WebSocket broadcast."""

    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.is_running: bool = False
        self.is_starting: bool = False
        self.gpu_mode: str = "host"
        self.grpc_port: int = DEFAULT_GRPC_PORT
        self.grpc_token: Optional[str] = None
        self.last_error: Optional[str] = None
        self.has_last_frame: bool = False

        self.streaming_active: bool = False
        self.target_width: int = STREAM_WIDTH
        self.target_height: int = STREAM_HEIGHT
        self._res_changed_event = threading.Event()
        self.last_frame_bytes: Optional[bytes] = None

        self.step: str = "offline"
        self.step_description: str = "Virtual phone is stopped."
        self.start_time: Optional[float] = None

        self._hypervisor_ok: Optional[bool] = None
        self._grpc_channel: Optional[grpc.Channel] = None
        self._grpc_stub: Optional[emulator_controller_pb2_grpc.EmulatorControllerStub] = None
        self._stream_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._broadcast_cb: Optional[Callable[[Dict[str, Any]], None]] = None
        self._frame_bytes_cb: Optional[Callable[[bytes, int, int], None]] = None
        self._log_file = None

    def get_log_tail(self, lines: int = 20) -> list[str]:
        """Read the last N lines from the emulator log as a list."""
        try:
            if EMU_LOG.exists():
                with open(EMU_LOG, "r", encoding="utf-8", errors="replace") as f:
                    content = f.readlines()
                    return [l.rstrip("\r\n") for l in content[-lines:]]
        except Exception:
            pass
        return []

    def _set_step(self, step: str, desc: str) -> None:
        """Update lifecycle step and broadcast state change."""
        self.step = step
        self.step_description = desc
        logger.info(f"[AndroidManager] Step: {step} - {desc}")
        self._broadcast({"type": "android_state", **self.get_state()})

    def set_broadcast_callback(self, cb: Callable[[Dict[str, Any]], None]) -> None:
        """Register WebSocket broadcast callback for state changes."""
        self._broadcast_cb = cb

    def set_frame_bytes_callback(self, cb: Optional[Callable[[bytes, int, int], None]]) -> None:
        """Register callback for binary JPEG frame delivery over /ws/android."""
        self._frame_bytes_cb = cb

    def set_streaming_active(self, active: bool) -> None:
        """Enable or pause screenshot streaming capture based on ANDROID tab visibility."""
        if self.streaming_active != active:
            self.streaming_active = active
            logger.info(f"[AndroidManager] Frame streaming active: {active}")

    def set_stream_resolution(self, width: int, height: int) -> None:
        """Update stream capture dimensions based on viewport pixel size (capped at 1080x2400)."""
        h = max(400, min(DISPLAY_HEIGHT, int(height)))
        # Pixel 7 aspect ratio is 1080:2400 = 0.45
        w = max(180, min(DISPLAY_WIDTH, int(width if width else h * (DISPLAY_WIDTH / DISPLAY_HEIGHT))))
        if abs(self.target_height - h) > 16 or abs(self.target_width - w) > 16:
            self.target_width = w
            self.target_height = h
            self._res_changed_event.set()
            logger.info(f"[AndroidManager] Target stream resolution set to {w}x{h}")

    def _broadcast(self, msg: Dict[str, Any]) -> None:
        """Dispatch message to registered WebSocket callback."""
        if self._broadcast_cb:
            try:
                self._broadcast_cb(msg)
            except Exception as e:
                logger.debug(f"[AndroidManager] Broadcast callback failed: {e}")

    def is_installed(self) -> bool:
        """Check whether the Android SDK emulator binary is present in data/android."""
        return EMULATOR_EXE.exists() and ADB_EXE.exists()

    def check_hypervisor(self) -> bool:
        """Check whether Windows Hypervisor Platform (WHPX) is active, caching the result."""
        if self._hypervisor_ok is not None:
            return self._hypervisor_ok

        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_OptionalFeature -Filter \"Name='HypervisorPlatform'\").InstallState"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self._hypervisor_ok = (res.stdout.strip() == "1")
        except Exception as e:
            logger.warning(f"[AndroidManager] Hypervisor check failed: {e}")
            self._hypervisor_ok = False

        return self._hypervisor_ok

    def get_state(self) -> Dict[str, Any]:
        """Return the current emulator lifecycle and readiness status."""
        elapsed = round(time.time() - self.start_time, 1) if self.start_time and (self.is_starting or self.is_running) else 0.0
        log_tail = self.get_log_tail(20) if (self.is_starting or self.step == "error" or self.last_error) else []

        if self.is_running:
            return {
                "running": True,
                "starting": False,
                "gpu_mode": self.gpu_mode,
                "step": "online",
                "step_description": f"Online (-gpu {self.gpu_mode})",
                "elapsed_sec": elapsed,
                "message": f"Online (-gpu {self.gpu_mode})",
                "detail": f"Pixel profile active on gRPC port {self.grpc_port}.",
                "has_last_frame": self.has_last_frame,
                "log_tail": log_tail,
            }
        elif self.is_starting:
            return {
                "running": False,
                "starting": True,
                "gpu_mode": self.gpu_mode,
                "step": self.step,
                "step_description": self.step_description,
                "elapsed_sec": elapsed,
                "message": "Starting...",
                "detail": f"{self.step_description} ({elapsed}s elapsed)",
                "has_last_frame": self.has_last_frame,
                "log_tail": log_tail,
            }
        elif not self.is_installed():
            return {
                "running": False,
                "starting": False,
                "gpu_mode": self.gpu_mode,
                "step": "offline",
                "step_description": "SDK Setup Pending",
                "elapsed_sec": 0.0,
                "message": "SDK Setup Pending",
                "detail": "Android SDK command-line tools & emulator pending download into data/android/sdk.",
                "has_last_frame": False,
                "log_tail": [],
            }
        elif not self.check_hypervisor():
            return {
                "running": False,
                "starting": False,
                "gpu_mode": self.gpu_mode,
                "step": "offline",
                "step_description": "Reboot Required",
                "elapsed_sec": 0.0,
                "message": "Reboot Required",
                "detail": "Windows Hypervisor Platform must be enabled in Windows Features, followed by a PC reboot.",
                "has_last_frame": False,
                "log_tail": [],
            }
        elif self.last_error:
            return {
                "running": False,
                "starting": False,
                "gpu_mode": self.gpu_mode,
                "step": "error",
                "step_description": self.last_error,
                "elapsed_sec": 0.0,
                "message": "Stopped (Error)",
                "detail": self.last_error,
                "has_last_frame": self.has_last_frame,
                "log_tail": log_tail,
            }
        else:
            return {
                "running": False,
                "starting": False,
                "gpu_mode": self.gpu_mode,
                "step": "stopped",
                "step_description": "Virtual phone is stopped.",
                "elapsed_sec": 0.0,
                "message": "Offline",
                "detail": "Virtual phone is stopped. Click 'Start Virtual Phone' to launch.",
                "has_last_frame": self.has_last_frame,
                "log_tail": [],
            }

    async def start(self, gpu_mode: str = "host") -> Dict[str, Any]:
        """Start the emulator instance."""
        if self.is_running:
            return self.get_state()
        if self.is_starting:
            return self.get_state()

        if not self.is_installed():
            return {
                "running": False,
                "starting": False,
                "message": "SDK Not Installed",
                "detail": "Android emulator binary not found in data/android/sdk/emulator/emulator.exe.",
            }

        if not self.check_hypervisor():
            return {
                "running": False,
                "starting": False,
                "message": "Reboot Required",
                "detail": "Windows Hypervisor Platform must be enabled in Windows Features, followed by a PC reboot.",
            }

        self.gpu_mode = gpu_mode
        self.is_starting = True
        self.start_time = time.time()
        self.last_error = None
        self._stop_event.clear()
        self._set_step("launching", "Launching emulator process...")

        env = os.environ.copy()
        env["ANDROID_HOME"] = str(SDK_DIR)
        env["ANDROID_SDK_ROOT"] = str(SDK_DIR)
        env["ANDROID_AVD_HOME"] = str(AVD_DIR)
        env["PATH"] = f"{SDK_DIR / 'platform-tools'};{env.get('PATH', '')}"
        if JDK_DIR.exists():
            env["JAVA_HOME"] = str(JDK_DIR)

        cmd = [
            str(EMULATOR_EXE),
            "-avd", "archer_pixel",
            "-no-window",
            "-camera-back", "none",
            "-camera-front", "none",
            "-no-audio",
            "-grpc", str(self.grpc_port),
            "-grpc-use-token",
            "-gpu", self.gpu_mode,
        ]

        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            self._log_file = open(EMU_LOG, "a", encoding="utf-8", errors="replace")
            self._log_file.write(f"\n--- Launching Virtual Phone: {' '.join(cmd)} at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
            self._log_file.flush()

            logger.info(f"[AndroidManager] Launching: {' '.join(cmd)}")
            self.process = subprocess.Popen(
                cmd,
                env=env,
                stdout=self._log_file,
                stderr=subprocess.STDOUT,
            )
        except Exception as e:
            logger.error(f"[AndroidManager] Launch failed: {e}")
            self.is_running = False
            self.is_starting = False
            self.last_error = str(e)
            self._set_step("error", f"Launch failed: {e}")
            return self.get_state()

        # Start background polling and streaming thread
        self._stream_thread = threading.Thread(
            target=self._boot_and_stream_worker,
            daemon=True,
            name="AndroidStreamWorker"
        )
        self._stream_thread.start()

        return self.get_state()

    def _boot_and_stream_worker(self) -> None:
        """Background thread that monitors boot, connects gRPC, and streams screenshot frames."""
        self._set_step("booting", "Android guest OS booting (waiting for gRPC discovery)...")
        token = None
        port = None

        search_dirs = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Temp" / "avd" / "running",
            Path(os.environ.get("TEMP", "")) / "avd" / "running",
            Path.home() / ".android" / "avd" / "running",
        ]

        # Poll for discovery file (up to 45 seconds)
        for _ in range(45):
            if self._stop_event.is_set():
                return
            if self.process and self.process.poll() is not None:
                err_tail = self._read_log_tail(15)
                self.last_error = f"Emulator process exited unexpectedly (code {self.process.returncode}): {err_tail}"
                logger.error(f"[AndroidManager] {self.last_error}")
                self.is_starting = False
                self.is_running = False
                self._set_step("error", self.last_error)
                return

            for d in search_dirs:
                if d.exists():
                    ini_files = glob.glob(str(d / "pid_*.ini"))
                    if ini_files:
                        # Parse the newest ini file
                        newest_ini = max(ini_files, key=os.path.getmtime)
                        try:
                            with open(newest_ini, "r", encoding="utf-8") as f:
                                for line in f:
                                    if "=" in line:
                                        k, v = line.strip().split("=", 1)
                                        if k == "grpc.token":
                                            token = v
                                        elif k == "grpc.port":
                                            port = int(v)
                            if token and port:
                                break
                        except Exception as e:
                            logger.debug(f"[AndroidManager] Error reading discovery file {newest_ini}: {e}")
            if token and port:
                break
            time.sleep(1)

        if not token or not port:
            self.last_error = "Emulator started but gRPC discovery file was not found within 45s."
            logger.error(f"[AndroidManager] {self.last_error}")
            self.is_starting = False
            self.is_running = False
            self._set_step("error", self.last_error)
            return

        self.grpc_token = token
        self.grpc_port = port
        logger.info(f"[AndroidManager] Discovered gRPC port {port}, token {token[:6]}...")

        # Connect gRPC channel
        channel = grpc.insecure_channel(f"127.0.0.1:{port}")
        self._grpc_channel = channel
        stub = emulator_controller_pb2_grpc.EmulatorControllerStub(channel)
        self._grpc_stub = stub
        meta = [("authorization", f"Bearer {token}")]

        # Wait for guest OS to render first frame / boot
        self._set_step("connecting", "Connecting screen stream and guest display...")
        fmt = emulator_controller_pb2.ImageFormat(
            format=emulator_controller_pb2.ImageFormat.RGB888,
            width=STREAM_WIDTH,
            height=STREAM_HEIGHT,
        )

        first_frame = None
        for _ in range(60):
            if self._stop_event.is_set():
                return
            if self.process and self.process.poll() is not None:
                err_tail = self._read_log_tail(15)
                self.last_error = f"Emulator exited during boot: {err_tail}"
                self.is_starting = False
                self.is_running = False
                self._set_step("error", self.last_error)
                return
            try:
                img = stub.getScreenshot(fmt, metadata=meta)
                if img and len(img.image) > 0:
                    first_frame = img
                    break
            except grpc.RpcError as rpc_err:
                logger.debug(f"[AndroidManager] Guest not ready yet: {rpc_err.details()}")
            time.sleep(1)

        if first_frame is None:
            logger.warning("[AndroidManager] First frame timeout — proceeding to stream attempt anyway.")

        # Transition to Online
        self.is_starting = False
        self.is_running = True
        self._set_step("online", f"Virtual phone online (-gpu {self.gpu_mode}).")

        # Broadcast initial boot frame immediately
        if first_frame is not None:
            self._process_and_broadcast_frame(first_frame)

        # Frame streaming loop: captures and streams ONLY when ANDROID tab is visible
        while not self._stop_event.is_set() and self.is_running:
            if not self.streaming_active:
                time.sleep(0.15)
                continue

            current_w = self.target_width
            current_h = self.target_height
            fmt = emulator_controller_pb2.ImageFormat(
                format=emulator_controller_pb2.ImageFormat.RGB888,
                width=current_w,
                height=current_h,
            )
            self._res_changed_event.clear()

            try:
                frame_stream = stub.streamScreenshot(fmt, metadata=meta)
                for img in frame_stream:
                    if self._stop_event.is_set() or not self.is_running:
                        break
                    if not self.streaming_active or self._res_changed_event.is_set():
                        break
                    self._process_and_broadcast_frame(img)

            except grpc.RpcError as e:
                if self._stop_event.is_set():
                    break
                logger.debug(f"[AndroidManager] streamScreenshot error ({e.code()}): {e.details()}, retrying in 2s...")
                time.sleep(2)
            except Exception as ex:
                if self._stop_event.is_set():
                    break
                logger.debug(f"[AndroidManager] Stream loop exception: {ex}")
                time.sleep(2)

        logger.info("[AndroidManager] Stream worker finished.")

    def _process_and_broadcast_frame(self, img) -> bool:
        """Decode raw gRPC frame buffer to JPEG, caching latest bytes and notifying callback."""
        if not img or not img.image:
            return False

        w = (img.format.width if (img.format and img.format.width) else img.width) or self.target_width
        h = (img.format.height if (img.format and img.format.height) else img.height) or self.target_height

        try:
            total_bytes = len(img.image)
            if total_bytes == w * h * 3:
                arr = np.frombuffer(img.image, dtype=np.uint8).reshape((h, w, 3))
            elif h > 0 and total_bytes % (h * 3) == 0:
                actual_w = total_bytes // (h * 3)
                arr = np.frombuffer(img.image, dtype=np.uint8).reshape((h, actual_w, 3))
            elif w > 0 and total_bytes % (w * 3) == 0:
                actual_h = total_bytes // (w * 3)
                arr = np.frombuffer(img.image, dtype=np.uint8).reshape((actual_h, w, 3))
            else:
                logger.debug(f"[AndroidManager] Unexpected image byte size: {total_bytes} for {w}x{h}")
                return False

            bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
            success, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            if success:
                jpeg_bytes = buf.tobytes()
                self.has_last_frame = True
                self.last_frame_bytes = jpeg_bytes

                # Deliver binary JPEG frame to dedicated /ws/android dispatcher
                if self._frame_bytes_cb:
                    try:
                        self._frame_bytes_cb(jpeg_bytes, w, h)
                    except Exception as cb_err:
                        logger.debug(f"[AndroidManager] Binary frame callback error: {cb_err}")

                return True
        except Exception as enc_err:
            logger.debug(f"[AndroidManager] Frame encoding error: {enc_err}")
        return False

    def _read_log_tail(self, lines: int = 15) -> str:
        """Read the last N lines from the emulator log."""
        try:
            if EMU_LOG.exists():
                with open(EMU_LOG, "r", encoding="utf-8", errors="replace") as f:
                    content = f.readlines()
                    return "".join(content[-lines:]).strip()
        except Exception:
            pass
        return "Unknown error."

    def stop(self) -> Dict[str, Any]:
        """Gracefully stop the emulator instance and wait off-loop for snapshot save."""
        self._stop_event.set()
        self.is_running = False
        self.is_starting = False
        self._set_step("stopping", "Stopping virtual phone and saving snapshot...")

        meta = [("authorization", f"Bearer {self.grpc_token}")] if self.grpc_token else []

        # 1. Graceful shutdown via gRPC
        if self._grpc_stub:
            try:
                self._grpc_stub.setVmState(
                    emulator_controller_pb2.VmRunState(state=emulator_controller_pb2.VmRunState.SHUTDOWN),
                    metadata=meta,
                    timeout=3,
                )
                logger.info("[AndroidManager] Sent gRPC SHUTDOWN state to emulator.")
            except Exception as e:
                logger.debug(f"[AndroidManager] gRPC shutdown failed: {e}")

        # 2. Graceful shutdown via adb emu kill
        env = os.environ.copy()
        env["ANDROID_HOME"] = str(SDK_DIR)
        env["PATH"] = f"{SDK_DIR / 'platform-tools'};{env.get('PATH', '')}"
        try:
            subprocess.run([str(ADB_EXE), "emu", "kill"], env=env, capture_output=True, timeout=5)
            logger.info("[AndroidManager] Executed adb emu kill.")
        except Exception as e:
            logger.debug(f"[AndroidManager] adb emu kill failed: {e}")

        # 3. Wait for process exit up to 10 seconds to allow snapshot save
        if self.process:
            try:
                self.process.wait(timeout=10)
                logger.info("[AndroidManager] Emulator process exited cleanly (Quick Boot snapshot saved).")
            except subprocess.TimeoutExpired:
                logger.warning("[AndroidManager] Emulator graceful stop timed out. Terminating...")
                try:
                    self.process.terminate()
                    self.process.wait(timeout=3)
                except Exception:
                    try:
                        self.process.kill()
                    except Exception:
                        pass
            self.process = None

        if self._grpc_channel:
            try:
                self._grpc_channel.close()
            except Exception:
                pass
            self._grpc_channel = None
            self._grpc_stub = None

        if self._log_file and not self._log_file.closed:
            try:
                self._log_file.close()
            except Exception:
                pass
            self._log_file = None

        self._set_step("stopped", "Virtual phone stopped.")
        return self.get_state()

    async def handle_button(self, button: str, rotation: Optional[int] = None):
        """Dispatch hardware navigation button (back, home, overview/recents, rotate)."""
        logger.debug(f"[AndroidManager] Button event: {button} (rot={rotation})")
        meta = [("authorization", f"Bearer {self.grpc_token}")] if self.grpc_token else []

        if button == "back":
            if self._grpc_stub:
                try:
                    self._grpc_stub.sendKey(emulator_controller_pb2.KeyboardEvent(key="Back"), metadata=meta)
                    return
                except Exception:
                    pass
            subprocess.run([str(ADB_EXE), "shell", "input", "keyevent", "4"], capture_output=True)

        elif button == "home":
            if self._grpc_stub:
                try:
                    self._grpc_stub.sendKey(emulator_controller_pb2.KeyboardEvent(key="Home"), metadata=meta)
                    return
                except Exception:
                    pass
            subprocess.run([str(ADB_EXE), "shell", "input", "keyevent", "3"], capture_output=True)

        elif button in ("overview", "recents", "apps"):
            if self._grpc_stub:
                try:
                    self._grpc_stub.sendKey(emulator_controller_pb2.KeyboardEvent(key="AppSwitch"), metadata=meta)
                    return
                except Exception:
                    pass
            subprocess.run([str(ADB_EXE), "shell", "input", "keyevent", "187"], capture_output=True)

        elif button == "rotate":
            env = os.environ.copy()
            env["PATH"] = f"{SDK_DIR / 'platform-tools'};{env.get('PATH', '')}"
            subprocess.run([str(ADB_EXE), "emu", "rotate"], env=env, capture_output=True)

    async def handle_touch(self, action: str, x: float, y: float):
        """Dispatch touch event with normalized coordinates mapped to native resolution."""
        if not self._grpc_stub or not self.is_running:
            return

        px = int(max(0.0, min(1.0, x)) * DISPLAY_WIDTH)
        py = int(max(0.0, min(1.0, y)) * DISPLAY_HEIGHT)
        pressure = 1 if action in ("down", "move") else 0

        touch = emulator_controller_pb2.Touch(
            x=px,
            y=py,
            identifier=0,
            pressure=pressure,
        )
        req = emulator_controller_pb2.TouchEvent(touches=[touch])
        meta = [("authorization", f"Bearer {self.grpc_token}")] if self.grpc_token else []

        try:
            self._grpc_stub.sendTouch(req, metadata=meta)
        except Exception as e:
            logger.debug(f"[AndroidManager] sendTouch error: {e}")

    async def handle_key(self, action: str, key: str, code: str, text: Optional[str] = None):
        """Dispatch keyboard event."""
        if not self._grpc_stub or not self.is_running:
            return

        meta = [("authorization", f"Bearer {self.grpc_token}")] if self.grpc_token else []

        if text and len(text) == 1:
            try:
                self._grpc_stub.sendKey(emulator_controller_pb2.KeyboardEvent(text=text), metadata=meta)
                return
            except Exception as e:
                logger.debug(f"[AndroidManager] sendKey text error: {e}")

        # Common navigation / editing keys
        key_name = key
        if key == "Enter":
            key_name = "Enter"
        elif key in ("Backspace", "Delete"):
            key_name = "Backspace"
        elif key == "Tab":
            key_name = "Tab"
        elif key == "ArrowUp":
            key_name = "ArrowUp"
        elif key == "ArrowDown":
            key_name = "ArrowDown"
        elif key == "ArrowLeft":
            key_name = "ArrowLeft"
        elif key == "ArrowRight":
            key_name = "ArrowRight"

        evt_type = (
            emulator_controller_pb2.KeyboardEvent.keydown
            if action == "down"
            else emulator_controller_pb2.KeyboardEvent.keyup
        )
        req = emulator_controller_pb2.KeyboardEvent(
            key=key_name,
            eventType=evt_type,
        )
        try:
            self._grpc_stub.sendKey(req, metadata=meta)
        except Exception as e:
            logger.debug(f"[AndroidManager] sendKey error: {e}")


_manager: Optional[AndroidEmulatorManager] = None


def get_android_manager() -> AndroidEmulatorManager:
    """Singleton getter for AndroidEmulatorManager."""
    global _manager
    if _manager is None:
        _manager = AndroidEmulatorManager()
    return _manager
