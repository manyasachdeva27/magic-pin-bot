#!/usr/bin/env python3
"""Quick smoke test -- hits all 6 endpoints against the running bot."""
import json
import sys
from urllib import request as urlrequest, error as urlerror
from pathlib import Path

BOT = "http://localhost:8080"
DATASET = Path(__file__).resolve().parent.parent.parent / "dataset"
PASS = 0
FAIL = 0

def req(method, path, body=None, expect_status=200):
    global PASS, FAIL
    url = f"{BOT}{path}"
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"} if data else {}
    r = urlrequest.Request(url, data=data, method=method, headers=headers)
    try:
        resp = urlrequest.urlopen(r, timeout=10)
        result = json.loads(resp.read().decode())
        if resp.status == expect_status:
            PASS += 1
            print(f"  [PASS] {method} {path} -> {resp.status}")
        else:
            FAIL += 1
            print(f"  [FAIL] {method} {path} -> {resp.status} (expected {expect_status})")
        return result, resp.status
    except urlerror.HTTPError as e:
        body_text = e.read().decode()
        try:
            result = json.loads(body_text)
        except:
            result = {"raw": body_text}
        if e.code == expect_status:
            PASS += 1
            print(f"  [PASS] {method} {path} -> {e.code}")
        else:
            FAIL += 1
            print(f"  [FAIL] {method} {path} -> {e.code} (expected {expect_status})")
        return result, e.code
    except Exception as e:
        FAIL += 1
        print(f"  [FAIL] {method} {path} -> {e}")
        return None, 0

print("=" * 60)
print("SMOKE TEST -- Vera Bot")
print("=" * 60)

# 1. Healthz
print("\n--- 1. Healthz ---")
data, _ = req("GET", "/v1/healthz")
assert data["status"] == "ok"
assert data["contexts_loaded"]["category"] == 0

# 2. Metadata
print("\n--- 2. Metadata ---")
data, _ = req("GET", "/v1/metadata")
assert "team_name" in data
assert "model" in data

# 3. Context push -- categories
print("\n--- 3. Context Push ---")
cat_dir = DATASET / "categories"
for f in sorted(cat_dir.glob("*.json")):
    cat = json.load(open(f))
    slug = cat.get("slug", f.stem)
    data, _ = req("POST", "/v1/context", {
        "scope": "category", "context_id": slug, "version": 1,
        "payload": cat, "delivered_at": "2026-04-26T09:45:00Z"
    })
    assert data["accepted"] == True

# 4. Context push -- merchants (first 5 seeds)
merchants_seed = json.load(open(DATASET / "merchants_seed.json"))["merchants"]
for m in merchants_seed[:5]:
    mid = m["merchant_id"]
    data, _ = req("POST", "/v1/context", {
        "scope": "merchant", "context_id": mid, "version": 1,
        "payload": m, "delivered_at": "2026-04-26T09:45:30Z"
    })
    assert data["accepted"] == True

# 5. Stale version -> 409
print("\n--- 4. Stale Version (409) ---")
data, status = req("POST", "/v1/context", {
    "scope": "category", "context_id": "dentists", "version": 1,
    "payload": {}, "delivered_at": "2026-04-26T09:46:00Z"
}, expect_status=409)
assert data["accepted"] == False
assert data["reason"] == "stale_version"

# 6. Invalid scope -> 400
print("\n--- 5. Invalid Scope (400) ---")
data, status = req("POST", "/v1/context", {
    "scope": "bogus", "context_id": "x", "version": 1,
    "payload": {}, "delivered_at": "2026-04-26T09:46:00Z"
}, expect_status=400)
assert data["accepted"] == False

# 7. Push triggers
print("\n--- 6. Trigger Push + Tick ---")
triggers_seed = json.load(open(DATASET / "triggers_seed.json"))["triggers"]
trg_ids = []
for t in triggers_seed[:3]:
    tid = t["id"]
    trg_ids.append(tid)
    req("POST", "/v1/context", {
        "scope": "trigger", "context_id": tid, "version": 1,
        "payload": t, "delivered_at": "2026-04-26T10:32:00Z"
    })

# 8. Tick
data, _ = req("POST", "/v1/tick", {
    "now": "2026-04-26T10:35:00Z",
    "available_triggers": trg_ids
})
actions = data.get("actions", [])
print(f"  Actions returned: {len(actions)}")
for a in actions:
    print(f"    trigger={a['trigger_id'][:30]} body='{a['body'][:60]}...'")
    assert "conversation_id" in a
    assert "merchant_id" in a
    assert "body" in a
    assert "cta" in a
    assert "suppression_key" in a
    assert "rationale" in a

# 9. Reply -- auto-reply detection
print("\n--- 7. Auto-Reply Detection ---")
mid = merchants_seed[0]["merchant_id"]
auto_msg = "Thank you for contacting Dr. Meera's Dental Clinic! Our team will respond shortly."

for i in range(1, 4):
    data, _ = req("POST", "/v1/reply", {
        "conversation_id": f"conv_auto_{i}",
        "merchant_id": mid,
        "customer_id": None,
        "from_role": "merchant",
        "message": auto_msg,
        "received_at": "2026-04-26T10:42:00Z",
        "turn_number": i + 1
    })
    action = data.get("action", "?")
    print(f"  Turn {i}: action={action}")
    if i == 1:
        assert action == "send", f"Expected send on 1st auto-reply, got {action}"
    elif i == 2:
        assert action == "wait", f"Expected wait on 2nd auto-reply, got {action}"
    elif i == 3:
        assert action == "end", f"Expected end on 3rd auto-reply, got {action}"

# 10. Reply -- hostile
print("\n--- 8. Hostile Handling ---")
data, _ = req("POST", "/v1/reply", {
    "conversation_id": "conv_hostile",
    "merchant_id": mid,
    "customer_id": None,
    "from_role": "merchant",
    "message": "Stop messaging me. This is useless spam.",
    "received_at": "2026-04-26T10:42:00Z",
    "turn_number": 2
})
action = data.get("action", "?")
body = data.get("body", "")
print(f"  Action: {action}, Body: '{body[:60]}'")
ok = action == "end" or (action == "send" and any(w in body.lower() for w in ["sorry", "apolog", "won't"]))
assert ok, f"Hostile check failed: action={action}"
print(f"  [PASS] Hostile handled correctly")

# 11. Reply -- intent transition
print("\n--- 9. Intent Transition ---")
data, _ = req("POST", "/v1/reply", {
    "conversation_id": "conv_intent_1",
    "merchant_id": mid,
    "customer_id": None,
    "from_role": "merchant",
    "message": "Ok lets do it. Whats next?",
    "received_at": "2026-04-26T10:42:00Z",
    "turn_number": 2
})
action = data.get("action", "?")
body = data.get("body", "")
print(f"  Action: {action}, Body: '{body[:80]}'")
actioning = ["done", "sending", "draft", "here", "confirm", "proceed", "next", "prepared"]
qualifying = ["would you", "do you", "can you tell", "what if", "how about"]
body_lower = body.lower()
if any(w in body_lower for w in actioning):
    print(f"  [PASS] Switched to action mode")
else:
    print(f"  [WARN] Response may not show clear action mode")

# 12. Teardown
print("\n--- 10. Teardown ---")
data, _ = req("POST", "/v1/teardown")
assert data["wiped"] == True

# Verify wipe
data, _ = req("GET", "/v1/healthz")
assert data["contexts_loaded"]["category"] == 0
assert data["contexts_loaded"]["merchant"] == 0
print(f"  [PASS] State wiped, contexts back to 0")

# Summary
print(f"\n{'=' * 60}")
print(f"RESULTS: {PASS} passed, {FAIL} failed")
print(f"{'=' * 60}")
sys.exit(1 if FAIL else 0)
