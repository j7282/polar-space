import requests
import json

app_id = "srv-cv70g0a3s0qc73eqqnb0"
token = "rnd_I0WqE3OQO6iE9F6uXZA7R8yA8bOQ"

url = f"https://api.render.com/v1/services/{app_id}/logs"
headers = {
    "accept": "application/json",
    "authorization": f"Bearer {token}"
}

print("Fetching latest Render logs...")
response = requests.get(url, headers=headers)
if response.status_code == 200:
    logs = response.json()
    for log in reversed(logs):
        if "message" in log:
            print(log["message"].strip())
else:
    print(f"Failed to fetch logs: {response.status_code}")
    print(response.text)
