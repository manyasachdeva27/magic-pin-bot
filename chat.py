import json
import time
from pathlib import Path
import urllib.request as request
import urllib.error as error

URL = "https://magicpin-vera-bot-production-cf82.up.railway.app"
DATASET = Path(__file__).resolve().parent.parent / "dataset"

def req(path, body=None):
    url = f"{URL}{path}"
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"}
    r = request.Request(url, data=data, headers=headers, method="POST")
    resp = request.urlopen(r)
    return json.loads(resp.read().decode())

def chat():
    print(f"Connecting to {URL}...")
    
    # 1. Teardown old state
    req("/v1/teardown")
    
    # 2. Push contexts (we will use a Salon for the test)
    print("Loading memory...")
    cat = json.load(open(DATASET / "categories" / "salons.json"))
    req("/v1/context", {"scope": "category", "context_id": "salons", "version": 1, "payload": cat, "delivered_at": "2026-04-26T00:00:00Z"})
    
    merchants = json.load(open(DATASET / "merchants_seed.json"))["merchants"]
    merch = next(m for m in merchants if m["merchant_id"] == "m_003_studio11_salon_hyderabad")
    req("/v1/context", {"scope": "merchant", "context_id": merch["merchant_id"], "version": 1, "payload": merch, "delivered_at": "2026-04-26T00:00:00Z"})
    
    triggers = json.load(open(DATASET / "triggers_seed.json"))["triggers"]
    trigger = next(t for t in triggers if t["id"] == "trg_008_curious_ask_studio11")
    req("/v1/context", {"scope": "trigger", "context_id": trigger["id"], "version": 1, "payload": trigger, "delivered_at": "2026-04-26T00:00:00Z"})

    # 3. Trigger the bot to send the first message
    print("\n--- CHAT STARTED (Type 'exit' to quit) ---\n")
    resp = req("/v1/tick", {"now": "2026-04-26T10:00:00Z", "available_triggers": [trigger["id"]]})
    
    if not resp.get("actions"):
        print("Bot decided not to send a message.")
        return
        
    action = resp["actions"][0]
    conv_id = action["conversation_id"]
    print(f"VERA: {action['body']}")

    # 4. Chat loop
    turn = 1
    while True:
        msg = input("YOU: ")
        if msg.lower() in ["exit", "quit"]:
            break
            
        reply_resp = req("/v1/reply", {
            "conversation_id": conv_id,
            "merchant_id": merch["merchant_id"],
            "from_role": "merchant",
            "message": msg,
            "received_at": "2026-04-26T10:05:00Z",
            "turn_number": turn
        })
        
        # Determine bot's response based on the action it decided
        if reply_resp["action"] == "send":
            print(f"VERA: {reply_resp['body']}")
        elif reply_resp["action"] == "wait":
            print(f"VERA (Silent): *Bot decides to wait {reply_resp.get('wait_seconds', 0)}s*")
        elif reply_resp["action"] == "end":
            print(f"VERA (Silent): *Bot ends conversation*")
            break
            
        turn += 1

if __name__ == "__main__":
    chat()
