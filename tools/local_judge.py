"""
tools/local_judge.py -- Mini judge lifecycle rehearsal.

Runs the full judge scenario sequence against a running bot:
1. Warmup (healthz + metadata)
2. Context push (all categories + seed merchants + customers + triggers)
3. Tick (batches of 5) + score each action
4. Auto-reply test (3 turns, different conv_ids)
5. Intent test (commitment + question + defer)
6. Hostile test
7. Off-topic test
8. Consent-gated trigger test
9. Version bump + before/after test
10. Teardown verification
"""
import json
import sys
import time
from pathlib import Path
from urllib import request as urlrequest, error as urlerror

BOT = "http://localhost:8080"
DATASET = Path(__file__).resolve().parent.parent.parent / "dataset"

PASS = 0
FAIL = 0
WARN = 0


def _req(method, path, body=None, expect_status=200):
    global PASS, FAIL
    url = f"{BOT}{path}"
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"} if data else {}
    r = urlrequest.Request(url, data=data, method=method, headers=headers)
    try:
        resp = urlrequest.urlopen(r, timeout=15)
        result = json.loads(resp.read().decode())
        status = resp.status
    except urlerror.HTTPError as e:
        result = json.loads(e.read().decode() or "{}")
        status = e.code
    except Exception as e:
        print(f"  [FAIL] {method} {path}: {e}")
        FAIL += 1
        return None, 0

    if status == expect_status:
        PASS += 1
        print(f"  [PASS] {method} {path} -> {status}")
    else:
        FAIL += 1
        print(f"  [FAIL] {method} {path} -> {status} (expected {expect_status}): {result}")
    return result, status


def _check(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}")


def _warn(cond, label):
    global WARN
    if not cond:
        WARN += 1
        print(f"  [WARN] {label}")
    else:
        print(f"  [PASS] {label}")


def _section(title):
    print(f"\n{'=' * 55}")
    print(f"  {title}")
    print(f"{'=' * 55}")


# ── Load dataset ─────────────────────────────────────────────────────────────
cats = {}
for f in sorted((DATASET / "categories").glob("*.json")):
    cat = json.load(open(f))
    cats[cat["slug"]] = cat

merchants = json.load(open(DATASET / "merchants_seed.json"))["merchants"]
customers = json.load(open(DATASET / "customers_seed.json"))["customers"]
triggers  = json.load(open(DATASET / "triggers_seed.json"))["triggers"]


def _push_all_contexts(version_offset=0):
    """Push all seed contexts. version_offset allows pushing as v1 after teardown."""
    v = 1 + version_offset
    for slug, cat in cats.items():
        _req("POST", "/v1/context", {
            "scope": "category", "context_id": slug, "version": v,
            "payload": cat, "delivered_at": "2026-04-26T09:45:00Z"
        })
    for m in merchants:
        _req("POST", "/v1/context", {
            "scope": "merchant", "context_id": m["merchant_id"], "version": v,
            "payload": m, "delivered_at": "2026-04-26T09:45:30Z"
        })
    for c in customers:
        _req("POST", "/v1/context", {
            "scope": "customer", "context_id": c["customer_id"], "version": v,
            "payload": c, "delivered_at": "2026-04-26T09:46:00Z"
        })
    for t in triggers:
        _req("POST", "/v1/context", {
            "scope": "trigger", "context_id": t["id"], "version": v,
            "payload": t, "delivered_at": "2026-04-26T09:46:30Z"
        })


def main():
    # Always teardown first to get clean suppression state
    _req("POST", "/v1/teardown")

    _section("1. WARMUP")
    data, _ = _req("GET", "/v1/healthz")
    _check(data and data.get("status") == "ok", "healthz returns ok")

    data, _ = _req("GET", "/v1/metadata")
    _check(data and "team_name" in data, "metadata has team_name")
    _check(data and "model" in data, "metadata has model")

    _section("2. CONTEXT PUSH")
    _push_all_contexts(version_offset=0)

    data, _ = _req("GET", "/v1/healthz")
    counts = data.get("contexts_loaded", {})
    _check(counts.get("category", 0) == 5, f"5 categories loaded ({counts.get('category')})")
    _check(counts.get("merchant", 0) == len(merchants), f"{len(merchants)} merchants loaded")

    _section("3. STALE + INVALID CONTEXT")
    data, status = _req("POST", "/v1/context", {
        "scope": "category", "context_id": "dentists", "version": 1,
        "payload": {}, "delivered_at": "2026-04-26T09:47:00Z"
    }, expect_status=409)
    _check(data and data.get("reason") == "stale_version", "409 reason=stale_version")

    data, status = _req("POST", "/v1/context", {
        "scope": "bogus", "context_id": "x", "version": 1,
        "payload": {}, "delivered_at": "2026-04-26T09:47:00Z"
    }, expect_status=400)
    _check(data and data.get("accepted") == False, "400 accepted=false for bad scope")

    _section("4. TICK -- ALL SEED TRIGGERS")
    all_trigger_ids = [t["id"] for t in triggers]
    tick_start = time.time()
    data, _ = _req("POST", "/v1/tick", {
        "now": "2026-04-26T10:35:00Z",
        "available_triggers": all_trigger_ids
    })
    tick_ms = (time.time() - tick_start) * 1000
    actions = data.get("actions", []) if data else []

    _check(tick_ms < 10000, f"tick completed under 10s ({tick_ms:.0f}ms)")
    _check(len(actions) >= 1, f"at least 1 action returned ({len(actions)} total)")
    print(f"  Actions returned: {len(actions)}")

    for a in actions:
        _check("conversation_id" in a, f"action has conversation_id")
        _check("merchant_id" in a, f"action has merchant_id")
        _check("body" in a and len(a["body"]) > 10, f"action body non-empty")
        _check("cta" in a, f"action has cta")
        _check("suppression_key" in a, f"action has suppression_key")
        _check("rationale" in a, f"action has rationale")
        # No URLs in body
        _check("http" not in a["body"].lower(), f"body has no URL")
        print(f"    trigger={a['trigger_id'][:35]} body='{a['body'][:70]}'")

    _section("5. AUTO-REPLY STATE MACHINE")
    mid = merchants[0]["merchant_id"]
    auto_msg = "Thank you for contacting us! Our team will respond shortly."
    expected = ["send", "wait", "end"]

    for i in range(1, 4):
        data, _ = _req("POST", "/v1/reply", {
            "conversation_id": f"conv_auto_{i}",  # NEW conv_id each turn!
            "merchant_id": mid,
            "customer_id": None,
            "from_role": "merchant",
            "message": auto_msg,
            "received_at": "2026-04-26T10:42:00Z",
            "turn_number": i + 1
        })
        action = data.get("action") if data else "?"
        exp = expected[i - 1]
        _check(action == exp, f"auto-reply turn {i}: action={action} (expected {exp})")
        if exp == "wait":
            _check(data.get("wait_seconds") == 86400, "wait_seconds=86400 (24h)")

    _section("6. HOSTILE HANDLING")
    data, _ = _req("POST", "/v1/reply", {
        "conversation_id": "conv_hostile",
        "merchant_id": mid,
        "customer_id": None,
        "from_role": "merchant",
        "message": "Stop messaging me! This is spam and useless.",
        "received_at": "2026-04-26T10:43:00Z",
        "turn_number": 2
    })
    action = data.get("action", "?") if data else "?"
    body = data.get("body", "") if data else ""
    ok = action == "end" or (action == "send" and
         any(w in body.lower() for w in ["sorry", "apolog", "won't", "wont"]))
    _check(ok, f"hostile: action={action} body='{body[:60]}'")

    _section("7. OFF-TOPIC HANDLING")
    data, _ = _req("POST", "/v1/reply", {
        "conversation_id": "conv_offtopic_1",
        "merchant_id": mid,
        "customer_id": None,
        "from_role": "merchant",
        "message": "Can you help me file GST returns?",
        "received_at": "2026-04-26T10:44:00Z",
        "turn_number": 2
    })
    action = data.get("action", "?") if data else "?"
    body = data.get("body", "") if data else ""
    _check(action == "send", f"off-topic: action=send (got {action})")
    declined = any(w in body.lower() for w in ["outside", "can't help", "can not", "leave", "specialist"])
    _warn(declined, f"off-topic body declines and redirects: '{body[:80]}'")

    _section("8. COMMITMENT -- INLINE ARTIFACT")
    # Set up a fresh merchant state
    mid2 = merchants[1]["merchant_id"] if len(merchants) > 1 else mid
    data, _ = _req("POST", "/v1/reply", {
        "conversation_id": "conv_commit_1",
        "merchant_id": mid2,
        "customer_id": None,
        "from_role": "merchant",
        "message": "Yes, let's do it. Go ahead.",
        "received_at": "2026-04-26T10:45:00Z",
        "turn_number": 2
    })
    action = data.get("action", "?") if data else "?"
    body = data.get("body", "") if data else ""
    cta = data.get("cta", "") if data else ""
    _check(action == "send", f"commitment: action=send (got {action})")
    _warn(cta == "binary_yes_stop", f"commitment: cta=binary_yes_stop (got {cta})")
    # Judge checks body contains actual content, not just "draft ready"
    has_content = len(body) > 30 and not body.lower().startswith("draft ready")
    _warn(has_content, f"commitment body has inline content: '{body[:80]}'")

    _section("9. QUESTION HANDLING")
    data, _ = _req("POST", "/v1/reply", {
        "conversation_id": "conv_question_1",
        "merchant_id": mid,
        "customer_id": None,
        "from_role": "merchant",
        "message": "How much does the campaign cost? What's the price?",
        "received_at": "2026-04-26T10:46:00Z",
        "turn_number": 2
    })
    action = data.get("action", "?") if data else "?"
    _check(action == "send", f"question: action=send (got {action})")

    _section("10. DEFER HANDLING")
    data, _ = _req("POST", "/v1/reply", {
        "conversation_id": "conv_defer_1",
        "merchant_id": mid,
        "customer_id": None,
        "from_role": "merchant",
        "message": "Baad mein dekhta hoon, abhi busy hoon",
        "received_at": "2026-04-26T10:47:00Z",
        "turn_number": 2
    })
    action = data.get("action", "?") if data else "?"
    _check(action == "wait", f"defer: action=wait (got {action})")

    _section("11. VERSION BUMP + DELTA")
    # Push merchant v2 with changed performance numbers
    m0 = merchants[0]
    mid0 = m0["merchant_id"]
    m0_v2 = json.loads(json.dumps(m0))  # deep copy
    if "performance" in m0_v2:
        m0_v2["performance"]["views"] = 9999
    data, _ = _req("POST", "/v1/context", {
        "scope": "merchant", "context_id": mid0, "version": 2,
        "payload": m0_v2, "delivered_at": "2026-04-26T11:00:00Z"
    })
    _check(data and data.get("accepted") == True, "version bump v2 accepted")

    # Same version again -> 409
    data, status = _req("POST", "/v1/context", {
        "scope": "merchant", "context_id": mid0, "version": 2,
        "payload": m0_v2, "delivered_at": "2026-04-26T11:01:00Z"
    }, expect_status=409)
    _check(status == 409 and data.get("reason") == "stale_version", "re-push v2 -> 409 stale_version")

    _section("12. CONSENT GATE -- UNREACHABLE CUSTOMER")
    # c_015 has no consent and no phone -- its trigger should produce no action
    unreach_trg = next((t for t in triggers if "c_015" in t.get("id", "")), None)
    if unreach_trg:
        data, _ = _req("POST", "/v1/tick", {
            "now": "2026-04-26T11:05:00Z",
            "available_triggers": [unreach_trg["id"]]
        })
        actions = data.get("actions", []) if data else []
        _check(len(actions) == 0, f"unreachable customer trigger suppressed ({len(actions)} actions)")

    _section("13. TEARDOWN")
    data, _ = _req("POST", "/v1/teardown")
    _check(data and data.get("wiped") == True, "teardown wiped=True")

    data, _ = _req("GET", "/v1/healthz")
    counts = data.get("contexts_loaded", {}) if data else {}
    _check(all(v == 0 for v in counts.values()),
           f"all contexts zero after teardown: {counts}")

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"\n{'=' * 55}")
    print(f"  LOCAL JUDGE RESULTS")
    print(f"  PASS: {PASS}  FAIL: {FAIL}  WARN: {WARN}")
    print(f"{'=' * 55}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
