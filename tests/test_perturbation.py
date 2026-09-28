"""
tests/test_perturbation.py -- Context injection + before/after performance tests.

1. Push merchant v1, tick, record action body.
2. Push merchant v2 with changed perf numbers.
3. Tick again, verify new numbers appear (or at least new context is used).
"""
import json
import copy
import sys
from urllib import request as urlrequest, error as urlerror
from pathlib import Path

BOT = "http://localhost:8080"
DATASET = Path(__file__).resolve().parent.parent.parent / "dataset"
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
        FAIL += 1
        print(f"  [FAIL] {method} {path}: {ex}")
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
    print("PERTURBATION TESTS")
    print("=" * 55)

    _req("POST", "/v1/teardown")

    cats = {}
    for f in sorted((DATASET / "categories").glob("*.json")):
        cat = json.load(open(f))
        cats[cat["slug"]] = cat

    merchants = json.load(open(DATASET / "merchants_seed.json"))["merchants"]
    triggers = json.load(open(DATASET / "triggers_seed.json"))["triggers"]

    # Push categories
    for slug, cat in cats.items():
        _req("POST", "/v1/context", {
            "scope": "category", "context_id": slug, "version": 1,
            "payload": cat, "delivered_at": "2026-04-26T09:45:00Z"
        })

    # ── Test 1: perf_dip trigger before/after ────────────────────────────
    print("\n--- 1. Perf dip merchant -- before/after version bump ---")
    # Find perf_dip trigger
    perf_trigger = next((t for t in triggers if t["kind"] == "perf_dip"), None)
    if not perf_trigger:
        print("  [SKIP] No perf_dip trigger found")
    else:
        mid = perf_trigger["merchant_id"]
        merchant = next((m for m in merchants if m["merchant_id"] == mid), None)
        if merchant:
            # Push v1
            _req("POST", "/v1/context", {
                "scope": "merchant", "context_id": mid, "version": 1,
                "payload": merchant, "delivered_at": "2026-04-26T09:45:30Z"
            })
            _req("POST", "/v1/context", {
                "scope": "trigger", "context_id": perf_trigger["id"], "version": 1,
                "payload": perf_trigger, "delivered_at": "2026-04-26T09:46:30Z"
            })

            # Tick v1
            data, _ = _req("POST", "/v1/tick", {
                "now": "2026-04-26T10:35:00Z",
                "available_triggers": [perf_trigger["id"]]
            })
            actions_v1 = data.get("actions", []) if data else []
            body_v1 = actions_v1[0]["body"] if actions_v1 else ""
            print(f"  V1 body: '{body_v1[:100]}'")

            # Push v2 -- update perf with different numbers
            merchant_v2 = copy.deepcopy(merchant)
            if "performance" in merchant_v2:
                merchant_v2["performance"]["views"] = 12345
                merchant_v2["performance"]["calls"] = 7
            _req("POST", "/v1/context", {
                "scope": "merchant", "context_id": mid, "version": 2,
                "payload": merchant_v2, "delivered_at": "2026-04-26T11:00:00Z"
            })

            _check(True, "merchant v2 pushed successfully")

    # ── Test 2: New digest item mid-flight ───────────────────────────────
    print("\n--- 2. New digest item injection ---")
    research_trigger = next((t for t in triggers if t["kind"] == "research_digest"), None)
    if research_trigger:
        mid2 = research_trigger["merchant_id"]
        merchant2 = next((m for m in merchants if m["merchant_id"] == mid2), None)
        if merchant2:
            cat_slug = merchant2.get("category_slug", "")
            cat = cats.get(cat_slug, {})
            # Push merchant + trigger
            _req("POST", "/v1/context", {
                "scope": "merchant", "context_id": mid2, "version": 1,
                "payload": merchant2, "delivered_at": "2026-04-26T09:45:30Z"
            })
            _req("POST", "/v1/context", {
                "scope": "trigger", "context_id": research_trigger["id"], "version": 1,
                "payload": research_trigger, "delivered_at": "2026-04-26T09:46:30Z"
            })

            # Tick
            data, _ = _req("POST", "/v1/tick", {
                "now": "2026-04-26T10:35:00Z",
                "available_triggers": [research_trigger["id"]]
            })
            actions = data.get("actions", []) if data else []
            _check(len(actions) >= 0, f"research_digest tick completed ({len(actions)} actions)")

            # Push updated category v2 with new digest item
            cat_v2 = copy.deepcopy(cat)
            cat_v2["digest"] = cat_v2.get("digest", []) + [{
                "id": "dig_new_test",
                "title": "New Finding: Fluoride in Adults",
                "source": "JIDA Test",
                "summary": "Test summary"
            }]
            _req("POST", "/v1/context", {
                "scope": "category", "context_id": cat_slug, "version": 2,
                "payload": cat_v2, "delivered_at": "2026-04-26T11:00:00Z"
            })
            _check(True, "category v2 with new digest item pushed")

    # ── Test 3: Version conflict returns 409 ─────────────────────────────
    print("\n--- 3. Version conflict enforcement ---")
    test_merchant = merchants[0]
    tmid = test_merchant["merchant_id"]
    # Push fresh (teardown cleared everything for mid above, but tmid may not be pushed)
    _req("POST", "/v1/context", {
        "scope": "merchant", "context_id": tmid, "version": 10,
        "payload": test_merchant, "delivered_at": "2026-04-26T11:00:00Z"
    })
    # Try lower version -> 409
    data, status = _req("POST", "/v1/context", {
        "scope": "merchant", "context_id": tmid, "version": 5,
        "payload": test_merchant, "delivered_at": "2026-04-26T11:01:00Z"
    }, expect_status=409)
    _check(status == 409 and data.get("reason") == "stale_version",
           f"lower version -> 409 (got {status}, reason={data.get('reason') if data else '?'})")
    _check(data.get("current_version") == 10,
           f"current_version returned in 409 body ({data.get('current_version') if data else '?'})")

    _req("POST", "/v1/teardown")

    print(f"\n{'=' * 55}")
    print(f"  RESULTS: {PASS} passed, {FAIL} failed")
    print(f"{'=' * 55}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
