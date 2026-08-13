import requests
import json

url = "http://127.0.0.1:11434/api/chat"
payload = {
    "model": "qwen3.5:4b",
    "messages": [{"role": "user", "content": "hi"}],
    "stream": False
}

try:
    response = requests.post(url, json=payload, timeout=5)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.text}")
except Exception as e:
    print(f"Error: {e}")

url_gen = "http://127.0.0.1:11434/api/generate"
payload_gen = {
    "model": "qwen3.5:4b",
    "prompt": "hi",
    "stream": False
}

try:
    response = requests.post(url_gen, json=payload_gen, timeout=5)
    print(f"\nGenerate Status Code: {response.status_code}")
    print(f"Generate Response: {response.text}")
except Exception as e:
    print(f"Generate Error: {e}")
