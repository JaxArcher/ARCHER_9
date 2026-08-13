import requests
import json

url = "http://127.0.0.1:8200/mobile/chat"
headers = {
    "Authorization": "Bearer NRpAowV3_LSaWlKAJDs_N9oilIsoD6BBXOPhXgwCt_fo",
    "Content-Type": "application/json"
}
payload = {
    "message": "What time is it?",
    "user_id": "col"
}

try:
    response = requests.post(url, json=payload, headers=headers, timeout=60)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")
except Exception as e:
    print(f"Error: {e}")
