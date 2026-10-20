"""
One set of model settings for every request to ARCHER's main Ollama instance.

Ollama reloads a model whenever a request asks for a different context size
(num_ctx) than the one it's loaded with: about 13 s on Col's PC. Until
2026-10-20 ARCHER's requests disagreed. The main chat and the classifier asked
for 4096, while the warm-up, the filler line and the background jobs sent none
and so got Ollama's own default (262,144 on Col's PC, from its app setting).
Ollama's log showed two reloads on most turns: most of the 25-33 s before
ARCHER's first word. At 4096, Ollama also cut every chat prompt (about 4,700
tokens with the tool list) to its last 2,051 tokens. That dropped the start of
the system prompt: the date and time, ARCHER's guidelines and most of the tool
descriptions, which is why "What time is it?" got "I don't have access to the
time" and replies after a tool drifted to asking about tasks.

Every request to the main instance goes through main_model_request(), so they
all ask for the same context size and keep the model loaded for the same time.
"""

from __future__ import annotations

from typing import Any, Optional

# A model load longer than this is reported as a reload in the log.
RELOAD_SECONDS = 2.0


def main_model_request(payload: dict, config: Any = None, **options: Any) -> dict:
    """
    Add the shared settings to a request body for the main Ollama instance:
    the context size, the keep-alive, and any extra `options` given (for
    example temperature). Returns the same dict.
    """
    if config is None:
        from archer.config import get_config

        config = get_config()
    merged = dict(payload.get("options") or {})
    merged.update(options)
    merged["num_ctx"] = int(config.ollama_num_ctx)
    payload["options"] = merged
    payload["keep_alive"] = config.ollama_keep_alive
    return payload


def prompt_limit(config: Any = None) -> int:
    """About how many prompt tokens Ollama keeps before cutting the start off (half the context)."""
    if config is None:
        from archer.config import get_config

        config = get_config()
    return int(config.ollama_num_ctx) // 2


def timing_summary(final: dict) -> Optional[str]:
    """
    One line from the timings in Ollama's last reply chunk, or None if it
    has none: load time, prompt tokens and time, reply tokens and time.
    """
    if not isinstance(final, dict) or "eval_count" not in final and "prompt_eval_count" not in final:
        return None

    def seconds(key: str) -> float:
        return float(final.get(key) or 0) / 1e9

    load = seconds("load_duration")
    text = (
        f"load {load:.1f} s, prompt {int(final.get('prompt_eval_count') or 0)} tokens "
        f"in {seconds('prompt_eval_duration'):.1f} s, reply {int(final.get('eval_count') or 0)} tokens "
        f"in {seconds('eval_duration'):.1f} s, total {seconds('total_duration'):.1f} s"
    )
    if load >= RELOAD_SECONDS:
        text += " (the model was reloaded)"
    return text


def prompt_was_cut(final: dict, config: Any = None) -> bool:
    """Whether the prompt Ollama evaluated reached its limit, so its start was likely cut off."""
    try:
        return int(final.get("prompt_eval_count") or 0) >= prompt_limit(config) - 8
    except Exception:
        return False
