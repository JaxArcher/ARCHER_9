"""
Pull required candidate models directly into the active Ollama HTTP service instance.
"""

import httpx

MODELS = ["qwen2.5:7b", "qwen2.5:14b", "gemma2:27b"]

def pull_all():
    url = "http://127.0.0.1:11434/api/pull"
    for model in MODELS:
        print(f"[Pulling {model} into Ollama HTTP service...]")
        try:
            resp = httpx.post(url, json={"name": model, "stream": False}, timeout=600.0)
            if resp.status_code == 200:
                print(f"  [SUCCESS] {model} pulled and ready.")
            else:
                print(f"  [ERROR] Failed to pull {model}: HTTP {resp.status_code}")
        except Exception as e:
            print(f"  [ERROR] Exception pulling {model}: {e}")

if __name__ == "__main__":
    pull_all()
