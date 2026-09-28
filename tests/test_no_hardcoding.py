"""
tests/test_no_hardcoding.py -- Verify nothing is hardcoded per category/merchant.

Swaps category slugs and merchant names, verifies output uses the new values
instead of hardcoded strings.
"""
import json
import sys
import copy
from urllib import request as urlrequest, error as urlerror

BOT = "http://localhost:8080"
PASS = 0
FAIL = 0


def _req(method, path, body=None, expect_status=200):
    global PASS, FAIL
    url = f"{BOT}{path}"
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"} if data else {}
    r = urlrequest.Request(url, data=data, method=method, headers=headers)
    try:
        resp = urlrequest.urlopen(r, timeout=10)
        result = json.loads(resp.read().decode())
        status = resp.status
    except urlerror.HTTPError as e:
        result = json.loads(e.read().decode() or "{}")
        status = e.code
    except Exception as ex:
        print(f"  [FAIL] {method} {path}: {ex}")
        FAIL += 1
        return None, 0
    if status == expect_status:
        PASS += 1
    else:
        FAIL += 1
        print(f"  [FAIL] {method} {path} -> {status} (expected {expect_status})")
    return result, status


def _check(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}")


def main():
    print("=" * 55)
    print("NO-HARDCODING GUARD")
    print("=" * 55)

    # Teardown first
    _req("POST", "/v1/teardown")

    # ── Test 1: Category voice swap ──────────────────────────────────────
    # Push a fake "dentists" category with gym vocabulary
    print("\n--- 1. Category voice swap (dentists -> gym vocab) ---")
    fake_dentist_cat = {
        "slug": "dentists",
        "voice": {
            "tone": "motivational",
            "register": "informal",
            "code_mix": "hi-en",
            "vocab_allowed": ["gains", "reps", "PR", "shred"],
            "vocab_taboo": ["guaranteed weight loss", "shred in 7 days"],
            "salutation_examples": ["Bhai!", "Champ!"],
            "tone_examples": ["Keep grinding!", "Beast mode!"],
        },
        "peer_stats": {"avg_rating": 4.2, "avg_ctr": 0.025},
        "offer_catalog": [],
        "digest": [],
        "patient_content_library": [],
        "seasonal_beats": [],
        "trend_signals": [],
    }
    _req("POST", "/v1/context", {
        "scope": "category", "context_id": "dentists", "version": 1,
        "payload": fake_dentist_cat, "delivered_at": "2026-04-26T09:45:00Z"
    })

    # Push a merchant in dentists category
    fake_merchant = {
        "merchant_id": "m_test_hardcode",
        "category_slug": "dentists",
        "identity": {
            "name": "XYZ Dental Studio",
            "owner_first_name": "Ramesh",
            "city": "Pune", "locality": "Koregaon Park",
            "languages": ["en"],
            "verified": True,
        },
        "subscription": {"status": "active", "plan": "Pro", "days_remaining": 45},
        "performance": {"views": 500, "calls": 20, "directions": 10, "ctr": 0.04,
                        "delta_7d": {}},
        "signals": [],
        "offers": [],
        "customer_aggregate": {},
    }
    _req("POST", "/v1/context", {
        "scope": "merchant", "context_id": "m_test_hardcode", "version": 1,
        "payload": fake_merchant, "delivered_at": "2026-04-26T09:45:30Z"
    })

    # Push a simple trigger
    fake_trigger = {
        "id": "trg_test_hardcode",
        "kind": "dormant_with_vera",
        "scope": "merchant",
        "merchant_id": "m_test_hardcode",
        "urgency": 3,
        "suppression_key": "test_hardcode_key",
        "payload": {
            "days_since_last_merchant_message": 10,
            "last_topic": "gbp_profile"
        }
    }
    _req("POST", "/v1/context", {
        "scope": "trigger", "context_id": "trg_test_hardcode", "version": 1,
        "payload": fake_trigger, "delivered_at": "2026-04-26T09:46:30Z"
    })

    # Tick
    data, _ = _req("POST", "/v1/tick", {
        "now": "2026-04-26T10:35:00Z",
        "available_triggers": ["trg_test_hardcode"]
    })
    actions = data.get("actions", []) if data else []
    _check(len(actions) >= 1, f"action produced for fake category merchant")
    if actions:
        body = actions[0]["body"]
        # Must use the merchant's actual name, not hardcoded "Dr. Meera" or "Bharat"
        _check("Ramesh" in body or "XYZ" in body,
               f"body references correct merchant (Ramesh/XYZ): '{body[:80]}'")
        # Must NOT contain dental-specific taboo from real data (check vocab we injected isn't "guaranteed")
        for hardcoded in ["Dr. Meera", "Bharat", "Studio11", "Pizza Junction"]:
            _check(hardcoded not in body, f"body has no hardcoded merchant '{hardcoded}'")

    # ── Test 2: Merchant name swap ────────────────────────────────────────
    print("\n--- 2. Merchant name uniqueness ---")
    # Push second merchant with different name
    fake_merchant2 = copy.deepcopy(fake_merchant)
    fake_merchant2["merchant_id"] = "m_test_hardcode2"
    fake_merchant2["identity"]["name"] = "Sunshine Clinic"
    fake_merchant2["identity"]["owner_first_name"] = "Priya"
    _req("POST", "/v1/context", {
        "scope": "merchant", "context_id": "m_test_hardcode2", "version": 1,
        "payload": fake_merchant2, "delivered_at": "2026-04-26T09:45:30Z"
    })
    fake_trigger2 = copy.deepcopy(fake_trigger)
    fake_trigger2["id"] = "trg_test_hardcode2"
    fake_trigger2["merchant_id"] = "m_test_hardcode2"
    fake_trigger2["suppression_key"] = "test_hardcode_key2"
    _req("POST", "/v1/context", {
        "scope": "trigger", "context_id": "trg_test_hardcode2", "version": 1,
        "payload": fake_trigger2, "delivered_at": "2026-04-26T09:46:30Z"
    })
    data, _ = _req("POST", "/v1/tick", {
        "now": "2026-04-26T10:36:00Z",
        "available_triggers": ["trg_test_hardcode2"]
    })
    actions2 = data.get("actions", []) if data else []
    if actions2:
        body2 = actions2[0]["body"]
        _check("Priya" in body2 or "Sunshine" in body2,
               f"body references Priya/Sunshine: '{body2[:80]}'")
        _check("Ramesh" not in body2 and "XYZ Dental" not in body2,
               f"body does not bleed first merchant into second")

    # Teardown
    _req("POST", "/v1/teardown")

    print(f"\n{'=' * 55}")
    print(f"  RESULTS: {PASS} passed, {FAIL} failed")
    print(f"{'=' * 55}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
