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
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
from loguru import logger


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
    itself while ARCHER's GUI/browser session is active. Explicitly SETS
    CUDA_VISIBLE_DEVICES="" (rather than leaving it unset) so a
    persistently-set system value can't accidentally hand it a GPU."""
    env = os.environ.copy()
    env["OLLAMA_HOST"] = host
    if force_cpu:
        env["CUDA_VISIBLE_DEVICES"] = ""
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

    try:
        subprocess.Popen(
            ["ollama", "serve"],
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            **popen_kwargs,
        )
        return True
    except FileNotFoundError:
        logger.warning(
            "`ollama` not found on PATH -- can't auto-start it. Install "
            "Ollama (https://ollama.com) or start it manually; ARCHER's "
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


def _warm_up_model(label: str, base_url: str, model: str) -> None:
    """Force `model` into VRAM now, in the background, instead of letting
    the user's first real question eat the cold-load cost.

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
    """
    try:
        resp = httpx.post(f"{base_url}/api/generate", json={"model": model}, timeout=120.0)
        if resp.status_code == 200:
            logger.info(f"Ollama ({label}) model '{model}' warmed up and resident in VRAM.")
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
        _warm_up_model("observer / moondream", config.observer_ollama_url, config.observer_model)

    threading.Thread(target=_run, daemon=True, name="archer-ollama-bootstrap").start()
