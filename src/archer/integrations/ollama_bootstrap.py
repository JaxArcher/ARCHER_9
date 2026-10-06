"""
ARCHER Ollama Bootstrap (2026-09-16).

ARCHER depends on TWO separate Ollama server instances:
  - main (config.ollama_base_url, default 127.0.0.1:11434) -- gemma4:e4b,
    the conversational/tool-calling model.
  - observer (config.observer_ollama_url, default 127.0.0.1:11435) --
    moondream, webcam scene analysis. Runs as a second instance
    specifically so it can be queried independently of whatever the main
    instance is doing mid-conversation.

Until now, both had to be started by hand every session: `ollama serve`
for the main one (or the Ollama tray app), and
scripts/start_observer_ollama.ps1 (whose own comment says "run this in
its own window each session, it does not exit") for the observer one.
Col asked for this to be automatic instead of a manual pre-flight step.

start_ollama_instances() below checks whether each instance is already
reachable and, if not, launches `ollama serve` itself with the right
OLLAMA_HOST for that instance -- as a background thread, so it doesn't
block ARCHER's own startup while Ollama loads. The main instance runs on
GPU (CUDA_VISIBLE_DEVICES left unset/stripped so a persistently-set
system value can't silently force it onto CPU). The observer instance
(moondream) is forced CPU-only again as of 2026-09-19 (Col's call,
reverting the 2026-09-16 GPU move) -- GPU headroom matters more now that
the observer can actually pause its own CPU-bound analysis while
ARCHER's GUI/browser session is active (see RedisBuffer.mark_gui_active
and observer/pipeline.py's _analysis_loop), which is what made the
original CPU-vs-STT contention problem possible in the first place.

Best-effort and non-fatal throughout, same as __main__.py's existing
docker-compose auto-start for the observer containers: if `ollama` isn't
on PATH, or a port is already in use for some unrelated reason, this logs
a warning and ARCHER keeps starting -- it just won't have working local-
model features until Ollama is reachable by whatever means.

The standalone observer service (observer_service.py) does NOT call
start_ollama_instances() as of 2026-10-06. Its Ollama is a Windows service
of its own (ArcherObserverOllama, see scripts/install_observer_service.ps1)
that starts at boot before the observer; the observer calls
wait_for_observer_ollama() instead, which never spawns anything. The
front-end apps keep calling start_ollama_instances(): with that service
running, port 11435 is already reachable and nothing is spawned; without
it, they still start their own observer instance as before.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
from loguru import logger


def _find_ollama_exe() -> str | None:
    """Locate the ollama executable, falling back to well-known Windows
    install locations when bare PATH lookup fails.

    2026-09-22 finding: `subprocess.Popen(["ollama", "serve"], ...)` relies
    on Windows resolving "ollama" against the CURRENT PROCESS's PATH. That
    works fine for ARCHER's desktop GUI, launched interactively under Col's
    own user session -- but the Observer runs as a Windows Service under
    NSSM, which gets a minimal machine-level PATH, not Col's interactive
    user PATH. The Ollama Windows installer adds itself to the per-user
    PATH at install time (installing to %LOCALAPPDATA%\\Programs\\Ollama by
    default), so a service never sees it -- confirmed live via
    observer_service_stderr.log repeating "`ollama` not found on PATH"
    indefinitely even though the main ARCHER process's own Ollama instance
    was reachable the whole time. shutil.which() still checks the current
    (possibly-restricted) PATH first, so this only changes behavior when
    that lookup would otherwise fail."""
    found = shutil.which("ollama")
    if found:
        return found

    if sys.platform != "win32":
        return None

    candidates = []
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(Path(local_appdata) / "Programs" / "Ollama" / "ollama.exe")
    for env_var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        base = os.environ.get(env_var)
        if base:
            candidates.append(Path(base) / "Ollama" / "ollama.exe")

    for candidate in candidates:
        if candidate.is_file():
            logger.info(f"Found ollama at {candidate} (not on this process's PATH).")
            return str(candidate)

    return None


def _ollama_reachable(base_url: str, timeout: float = 1.5) -> bool:
    """Cheap liveness check -- /api/version responds instantly on a real
    Ollama server and requires no model to be loaded."""
    try:
        resp = httpx.get(f"{base_url}/api/version", timeout=timeout)
        return resp.status_code == 200
    except Exception:
        return False


def _host_from_url(url: str) -> str:
    """OLLAMA_HOST has no scheme -- "http://127.0.0.1:11434" -> "127.0.0.1:11434"."""
    return url.split("://", 1)[-1]


def _spawn_ollama_serve(host: str, log_path: Path, force_cpu: bool = False) -> bool:
    """Launch `ollama serve` bound to `host`, detached, no visible console
    window. Returns whether the process was launched at all (not whether
    it came up successfully -- the caller polls _ollama_reachable for
    that).

    force_cpu (2026-09-19): moondream moved back to CPU-only -- see
    start_ollama_instances' call site and RedisBuffer.mark_gui_active's
    docstring for why this is safe again now that the observer can pause
    itself while ARCHER's GUI/browser session is active.

    Uses CUDA_VISIBLE_DEVICES="-1" rather than "" -- confirmed live
    2026-09-19 that an empty string was NOT reliably hiding the GPU
    (ollama_observer.log still showed a real CUDA0 compute buffer being
    reserved after a clean restart). Likely cause: Windows can drop an
    empty-valued env var from a child process's environment block
    entirely rather than passing it through as empty, which leaves
    CUDA_VISIBLE_DEVICES effectively unset -- and unset means "no
    restriction," the opposite of what force_cpu wants. "-1" is an
    unambiguous, always-invalid device index that can't collapse into
    "unset" the same way."""
    env = os.environ.copy()
    env["OLLAMA_HOST"] = host
    if force_cpu:
        env["CUDA_VISIBLE_DEVICES"] = "-1"
    else:
        env.pop("CUDA_VISIBLE_DEVICES", None)  # see module docstring

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = open(log_path, "a", encoding="utf-8")
    except OSError as e:
        logger.warning(f"Could not open Ollama log file {log_path}: {e}")
        log_file = subprocess.DEVNULL

    popen_kwargs: dict = {}
    if sys.platform == "win32":
        # No visible terminal window -- this replaces what used to be a
        # PowerShell window Col kept open for the whole session.
        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    ollama_exe = _find_ollama_exe()
    if ollama_exe is None:
        logger.warning(
            "`ollama` not found on PATH (or any well-known install location) "
            "-- can't auto-start it. Install Ollama (https://ollama.com) or "
            "start it manually; ARCHER's local model features won't work "
            "until it's reachable."
        )
        return False

    try:
        subprocess.Popen(
            [ollama_exe, "serve"],
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            **popen_kwargs,
        )
        return True
    except FileNotFoundError:
        logger.warning(
            f"ollama executable resolved to {ollama_exe} but launching it "
            "failed (FileNotFoundError) -- can't auto-start it. ARCHER's "
            "local model features won't work until it's reachable."
        )
        return False
    except Exception as e:
        logger.warning(f"Failed to auto-start Ollama (OLLAMA_HOST={host}): {e}")
        return False


def _ensure_instance(
    label: str, base_url: str, log_filename: str, log_dir: Path, force_cpu: bool = False
) -> None:
    if _ollama_reachable(base_url):
        logger.info(f"Ollama ({label}) already running at {base_url}.")
        return

    logger.info(f"Ollama ({label}) not reachable at {base_url} -- starting it...")
    log_path = log_dir / log_filename
    if not _spawn_ollama_serve(_host_from_url(base_url), log_path, force_cpu=force_cpu):
        return

    # Poll rather than assume it's instantly ready -- binding the port and
    # (for some setups) an initial model load can take a few seconds.
    for _ in range(20):
        time.sleep(1.0)
        if _ollama_reachable(base_url):
            logger.info(f"Ollama ({label}) is up at {base_url}.")
            return
    logger.warning(
        f"Ollama ({label}) still not reachable at {base_url} after 20s -- "
        f"check {log_path} for details."
    )


def _same_model(a: str, b: str) -> bool:
    """'moondream' and 'moondream:latest' are the same model to Ollama."""
    def norm(name: str) -> str:
        return name if ":" in name else f"{name}:latest"
    return norm(a) == norm(b)


def _model_placement(base_url: str, model: str) -> str | None:
    """Ask Ollama where `model` actually landed, from /api/ps's size vs
    size_vram (2026-10-06). The warm-up message used to say "resident in
    VRAM" unconditionally on any 200 -- including for moondream, which is
    deliberately CPU-only -- which read as proof it was on the GPU when it
    wasn't."""
    try:
        resp = httpx.get(f"{base_url}/api/ps", timeout=5.0)
        resp.raise_for_status()
        for m in resp.json().get("models", []) or []:
            name = m.get("name") or m.get("model") or ""
            if not _same_model(name, model):
                continue
            size = m.get("size") or 0
            vram = m.get("size_vram") or 0

            def gb(n: int) -> str:
                return f"{n / 1024 ** 3:.1f} GB"

            if vram <= 0:
                return f"loaded on CPU/RAM ({gb(size)}, no VRAM)"
            if vram >= size:
                return f"loaded fully in VRAM ({gb(vram)})"
            return f"loaded split: {gb(vram)} in VRAM, {gb(size - vram)} on CPU"
    except Exception:
        return None
    return None


def _warm_up_model(label: str, base_url: str, model: str, force_cpu: bool = False) -> None:
    """Force `model` into VRAM (or RAM, if force_cpu) now, in the
    background, instead of letting the user's first real question eat the
    cold-load cost.

    Added 2026-09-17 after Col's log showed his very first question after
    launch ("What are your capabilities and functions?" -- plain text, no
    image) took ~49s for Ollama to return anything, while every question
    after it in the same session answered in 1-4s. Ollama loads a model
    into memory lazily on its first request; _ensure_instance above only
    checks that the Ollama SERVER process is reachable (/api/version),
    which says nothing about whether the model itself is resident yet.
    Sending a prompt-less /api/generate request is Ollama's documented way
    to load a model without generating anything -- best-effort and
    non-fatal, same as the rest of this module: if it fails, the user just
    eats the cold-start cost on their first real question instead, exactly
    as before this change.

    force_cpu (2026-09-24 finding): CUDA_VISIBLE_DEVICES=-1 on the spawned
    `ollama serve` process (see _spawn_ollama_serve) turned out to NOT be
    reliably keeping moondream off the GPU either -- Col observed it
    resident in VRAM live, the same category of failure as the empty-
    string version of this same env var that got fixed on 2026-09-19.
    Ollama's own /api/generate request body accepts an options.num_gpu
    override that controls GPU layer offload directly, independent of
    however the server process itself detects hardware -- passing 0 here
    is a second, more direct way of pinning this model to CPU that doesn't
    depend on the env var actually working.
    """
    options = {"num_gpu": 0} if force_cpu else None
    payload = {"model": model}
    if options:
        payload["options"] = options
    try:
        resp = httpx.post(f"{base_url}/api/generate", json=payload, timeout=120.0)
        if resp.status_code == 200:
            where = _model_placement(base_url, model) or "placement unknown (/api/ps didn't list it)"
            logger.info(f"Ollama ({label}) model '{model}' warmed up -- {where}.")
        else:
            logger.warning(f"Ollama ({label}) warm-up for '{model}' returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.warning(f"Ollama ({label}) warm-up for '{model}' failed (non-fatal): {e}")


def start_ollama_instances() -> None:
    """Call once from each process entry point (__main__.py, web_main.py),
    before CoreAgent/ObserverPipeline initialize. Runs the actual checks
    and launches on a background daemon thread so it never blocks ARCHER's
    own startup -- neither CoreAgent nor ObserverPipeline talk to Ollama
    until the first real conversation turn / analysis cycle, so there's no
    need to wait here."""
    from archer.config import get_config
    config = get_config()

    def _run():
        _ensure_instance("main / gemma4:e4b", config.ollama_base_url, "ollama_main.log", config.log_dir)
        _ensure_instance(
            "observer / moondream", config.observer_ollama_url, "ollama_observer.log", config.log_dir,
            force_cpu=True,
        )
        # Warm both models into VRAM now rather than on the user's first
        # real question / the observer's first analysis cycle -- see
        # _warm_up_model. Sequential on this same background thread is
        # fine; nothing else is waiting on it.
        _warm_up_model("main / gemma4:e4b", config.ollama_base_url, config.core_primary_model)
        _warm_up_model(
            "observer / moondream", config.observer_ollama_url, config.observer_model,
            force_cpu=True,
        )

    threading.Thread(target=_run, daemon=True, name="archer-ollama-bootstrap").start()


def wait_for_observer_ollama(timeout_s: float = 600.0) -> None:
    """Observer-service counterpart to start_ollama_instances() (2026-10-06).

    Never spawns anything -- see the module docstring and observer_service.py
    for why. On a background thread: waits for the observer instance (the
    ArcherObserverOllama Windows service) to answer, warms moondream on CPU
    and logs where it actually loaded, then reports once whether the main
    instance is up yet (normally not until Col logs in and the Ollama tray
    app starts it). Scene analysis doesn't wait on this -- SceneAnalyzer
    retries on its own every minute -- so this exists for the warm-up and
    for a clear log line either way."""
    from archer.config import get_config
    config = get_config()

    def _run():
        deadline = time.monotonic() + timeout_s
        while not _ollama_reachable(config.observer_ollama_url):
            if time.monotonic() > deadline:
                logger.warning(
                    f"Observer Ollama still not reachable at {config.observer_ollama_url} after "
                    f"{int(timeout_s)}s. Check the ArcherObserverOllama service "
                    r"(nssm status ArcherObserverOllama) and logs\ollama_observer.log. "
                    "Scene analysis keeps retrying on its own."
                )
                return
            time.sleep(2.0)

        logger.info(f"Observer Ollama is up at {config.observer_ollama_url}.")
        _warm_up_model(
            "observer / moondream", config.observer_ollama_url, config.observer_model,
            force_cpu=True,
        )
        if _ollama_reachable(config.ollama_base_url):
            logger.info(f"Main Ollama is up at {config.ollama_base_url}.")
        else:
            logger.info(
                f"Main Ollama not running yet at {config.ollama_base_url} -- normal before login "
                "(the Ollama tray app starts it). The staleness pass retries on its own schedule."
            )

    threading.Thread(target=_run, daemon=True, name="archer-observer-ollama-wait").start()
