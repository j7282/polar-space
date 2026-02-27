import os
import requests
import time
import json

# Twitter App Bearer Token Provided by User
TWITTER_BEARER_TOKEN = "AAAAAAAAAAAAAAAAAAAAAJWT7wEAAAAATcLasrDtUEcIiFRFDlNog8JdKz0%3DSrpZWAx59d8AqNopevERhajTcZr6hWD72Sg7pYwzmFxweFYm0N"

# The Webhook URL of your Render application that triggers the ASTERA scan
RENDER_WAKEUP_URL = "https://searchgood123.onrender.com/api/twitter-wakeup"

# The specific Twitter User ID you want to monitor (e.g., your own secret account)
# For now, we listen to a specific hashtag rule for testing
TRIGGER_KEYWORD = "#AsteraScanWakeup"

def setup_rules():
    print("🧹 Cleaning old rules...")
    headers = {"Authorization": f"Bearer {TWITTER_BEARER_TOKEN}"}
    
    # Get current rules
    response = requests.get("https://api.twitter.com/2/tweets/search/stream/rules", headers=headers)
    if response.status_code == 200 and "data" in response.json():
        rules = response.json()["data"]
        ids = [rule["id"] for rule in rules]
        # Delete them
        requests.post("https://api.twitter.com/2/tweets/search/stream/rules", headers=headers, json={"delete": {"ids": ids}})
        
    print(f"✨ Setting new rule to listen for: {TRIGGER_KEYWORD}")
    rule_payload = {"add": [{"value": TRIGGER_KEYWORD, "tag": "astera_trigger"}]}
    requests.post("https://api.twitter.com/2/tweets/search/stream/rules", headers=headers, json=rule_payload)

def listen_for_tweets():
    print("🎧 Conectando al stream en vivo de X (Twitter)...")
    headers = {"Authorization": f"Bearer {TWITTER_BEARER_TOKEN}"}
    
    while True:
        try:
            with requests.get("https://api.twitter.com/2/tweets/search/stream", headers=headers, stream=True) as response:
                if response.status_code != 200:
                    print(f"❌ Error en la conexión a Twitter: {response.status_code} - {response.text}")
                    time.sleep(15)
                    continue
                    
                print("✅ Escuchando activamente. Pista: tuitea algo con el hashtag para probar.")
                
                for line in response.iter_lines():
                    if line:
                        tweet_data = json.loads(line)
                        text = tweet_data.get("data", {}).get("text", "")
                        print(f"🐦 [TWEET DETECTADO]: {text}")
                        
                        # TRIGGER THE RENDER SERVER
                        print(f"🚀 Enviando pulso de despertador a Render: {RENDER_WAKEUP_URL}")
                        try:
                            res = requests.post(RENDER_WAKEUP_URL, timeout=10)
                            print(f"☁️ Respuesta de Render: {res.status_code} - {res.text}")
                        except Exception as e:
                            print(f"⚠️ Render no respondió a tiempo: {e}")
        except Exception as e:
            print(f"☠️ Conexión caída, reconectando en 5s... Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    setup_rules()
    listen_for_tweets()
