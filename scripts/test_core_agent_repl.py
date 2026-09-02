"""
ARCHER CoreAgent Standalone Interactive REPL (Terminal Text Interface).

Instantiates CoreAgent (using primary local model 'qwen3:8b') and provides
a simple, direct interactive terminal loop for extended conversation testing.

Usage:
    python scripts/test_core_agent_repl.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Add src to Python path
sys.path.append(str(Path(__file__).parent.parent / "src"))

from archer.agents.core_agent import CoreAgent


def main() -> None:
    # Ensure UTF-8 I/O encoding on Windows terminal
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")

    print("=" * 68)
    print("  ARCHER CoreAgent Standalone Interactive REPL")
    print("=" * 68)

    agent = CoreAgent()
    print(f"[CoreAgent Ready] Primary Local Model: '{agent.primary_model}'")
    print("Type your message below. Type 'exit' or 'quit' to end session.\n")

    turn_count = 1
    while True:
        try:
            user_input = input("Colby> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting REPL session.")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit"):
            print("Session ended. Goodbye!")
            break

        # Display history status prior to prompt assembly and LLM request
        prior_history_count = len(agent._conversation_history)
        print(f"\n[Turn {turn_count} Memory Status] Prior history buffer items: {prior_history_count}")
        if prior_history_count > 0:
            last_msg = agent._conversation_history[-1]
            preview = last_msg['content'][:60] + ("..." if len(last_msg['content']) > 60 else "")
            print(f"  └─ Last stored turn [{last_msg['role']}]: \"{preview}\"")

        print("ARCHER> ", end="", flush=True)
        start_t = time.monotonic()
        sentence_count = 0

        for sentence in agent.process_request_streaming(user_input):
            sentence_count += 1
            if sentence_count == 1:
                print(f"{sentence}", flush=True)
            else:
                print(f"        {sentence}", flush=True)

        elapsed = time.monotonic() - start_t
        updated_history_count = len(agent._conversation_history)
        print(
            f"└─ [Turn {turn_count} Complete] Elapsed: {elapsed:.2f}s | "
            f"Yielded: {sentence_count} sentences | Updated History Items: {updated_history_count}\n"
        )
        turn_count += 1


if __name__ == "__main__":
    main()
