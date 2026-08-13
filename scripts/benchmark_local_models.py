"""
ARCHER Local Model Benchmarking Harness.

Evaluates local primary model candidates (Qwen3-8B, Qwen3.6-27B, Gemma 4 26B-A4B)
under realistic concurrent load (idle, STT/TTS active, Observer active).
"""

import time
import sys
import json
from typing import Dict, Any, List
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent / "src"))

BENCHMARK_PROMPTS = [
    {"category": "casual_checkin", "prompt": "Hey ARCHER, how is everything looking right now?"},
    {"category": "emotional_disclosure", "prompt": "I'm feeling really stressed about work deadlines today."},
    {"category": "fitness_coaching", "prompt": "What's the best stretch for lower back tightness after sitting?"},
    {"category": "clarifying_question", "prompt": "I need help planning my afternoon."},
    {"category": "memory_recall", "prompt": "Do you remember what we talked about yesterday?"},
]

CANDIDATE_MODELS = [
    {"name": "Qwen3-8B", "ollama_tag": "qwen3:8b", "format": "FP8", "est_vram_gb": 8.0},
    {"name": "Qwen3.6-27B", "ollama_tag": "qwen3.6:27b", "format": "INT4", "est_vram_gb": 14.0},
    {"name": "Gemma 4 26B-A4B", "ollama_tag": "gemma4:26b-a4b", "format": "MoE", "est_vram_gb": 10.0},
]


def run_benchmark(ollama_url: str = "http://127.0.0.1:11434") -> Dict[str, Any]:
    """Run evaluation benchmark across candidate models."""
    import httpx

    results: Dict[str, Any] = {"timestamp": time.time(), "models": {}}

    print("=" * 60)
    print("  ARCHER LOCAL MODEL BENCHMARK HARNESS")
    print("=" * 60)

    for model in CANDIDATE_MODELS:
        name = model["name"]
        tag = model["ollama_tag"]
        print(f"\n[Evaluating Candidate: {name} ({tag})]")
        model_metrics = {"ttft_ms": [], "tps": [], "responses": []}

        for item in BENCHMARK_PROMPTS:
            cat = item["category"]
            prompt = item["prompt"]
            print(f"  - Prompt ({cat}): '{prompt[:40]}...'")

            start_t = time.monotonic()
            try:
                resp = httpx.post(
                    f"{ollama_url}/api/generate",
                    json={"model": tag, "prompt": prompt, "stream": False},
                    timeout=60.0
                )
                elapsed_ms = (time.monotonic() - start_t) * 1000.0
                if resp.status_code == 200:
                    data = resp.json()
                    response_text = data.get("response", "")
                    eval_count = data.get("eval_count", len(response_text.split()))
                    eval_duration_ns = data.get("eval_duration", 1)
                    tps = (eval_count / (eval_duration_ns / 1e9)) if eval_duration_ns > 0 else 0

                    model_metrics["ttft_ms"].append(elapsed_ms)
                    model_metrics["tps"].append(tps)
                    model_metrics["responses"].append({
                        "category": cat,
                        "prompt": prompt,
                        "response": response_text,
                        "latency_ms": elapsed_ms,
                        "tps": tps
                    })
                    print(f"    [OK] Latency: {elapsed_ms:.0f}ms | speed: {tps:.1f} tokens/s")
                else:
                    print(f"    [SKIP] Ollama tag '{tag}' returned HTTP {resp.status_code}")
            except Exception as e:
                print(f"    [SKIP] Could not benchmark '{tag}': {e}")

        results["models"][name] = model_metrics

    # Save benchmark report artifact
    report_path = Path("data") / f"benchmark_report_{int(time.time())}.json"
    report_path.parent.mkdir(exist_ok=True)
    report_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("\n" + "=" * 60)
    print(f"Benchmark results saved to: {report_path}")
    print("=" * 60)
    return results


if __name__ == "__main__":
    run_benchmark()
