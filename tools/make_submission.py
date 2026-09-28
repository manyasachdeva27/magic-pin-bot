"""
tools/make_submission.py -- Generate submission.jsonl from the full dataset.

Runs the bot against every seed trigger (and optionally generated triggers)
and writes the actions to a JSONL file for submission.

Usage:
    python tools/make_submission.py [--output submission.jsonl] [--all-triggers]
"""
import argparse
import json
import sys
from pathlib import Path
from urllib import request as urlrequest, error as urlerror

BOT = "http://localhost:8080"
DATASET = Path(__file__).resolve().parent.parent.parent / "dataset"


def _req(method, path, body=None):
    url = f"{BOT}{path}"
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"} if data else {}
    r = urlrequest.Request(url, data=data, method=method, headers=headers)
    try:
        resp = urlrequest.urlopen(r, timeout=30)
        return json.loads(resp.read().decode()), resp.status
    except urlerror.HTTPError as e:
        return json.loads(e.read().decode() or "{}"), e.code
    except Exception as e:
        print(f"ERROR: {method} {path}: {e}", file=sys.stderr)
        return None, 0


def main():
    parser = argparse.ArgumentParser(description="Generate Vera submission JSONL")
    parser.add_argument("--output", default="submission.jsonl")
    parser.add_argument("--all-triggers", action="store_true",
                        help="Include generated triggers (not just seed)")
    parser.add_argument("--teardown-first", action="store_true", default=True,
                        help="Wipe state before loading (default: True)")
    args = parser.parse_args()

    # ── 1. Teardown first for clean state ─────────────────────────────────
    if args.teardown_first:
        print("Wiping state...")
        _req("POST", "/v1/teardown")

    # ── 2. Push all categories ─────────────────────────────────────────────
    print("Pushing categories...")
    for f in sorted((DATASET / "categories").glob("*.json")):
        cat = json.load(open(f))
        data, status = _req("POST", "/v1/context", {
            "scope": "category",
            "context_id": cat["slug"],
            "version": 1,
            "payload": cat,
            "delivered_at": "2026-04-26T09:45:00Z",
        })
        if status == 200 and data.get("accepted"):
            print(f"  category/{cat['slug']} OK")
        else:
            print(f"  category/{cat['slug']} WARN status={status}")

    # ── 3. Push all seed merchants ─────────────────────────────────────────
    print("Pushing merchants...")
    merchants = json.load(open(DATASET / "merchants_seed.json"))["merchants"]
    for m in merchants:
        mid = m["merchant_id"]
        data, status = _req("POST", "/v1/context", {
            "scope": "merchant",
            "context_id": mid,
            "version": 1,
            "payload": m,
            "delivered_at": "2026-04-26T09:45:30Z",
        })
        ok = status in (200,) and data.get("accepted")
        print(f"  {mid} {'OK' if ok else f'WARN status={status}'}")

    # ── 4. Push all seed customers ─────────────────────────────────────────
    print("Pushing customers...")
    customers = json.load(open(DATASET / "customers_seed.json"))["customers"]
    for c in customers:
        cid = c["customer_id"]
        _req("POST", "/v1/context", {
            "scope": "customer",
            "context_id": cid,
            "version": 1,
            "payload": c,
            "delivered_at": "2026-04-26T09:46:00Z",
        })

    # ── 5. Push triggers ───────────────────────────────────────────────────
    print("Pushing triggers...")
    triggers_seed = json.load(open(DATASET / "triggers_seed.json"))["triggers"]
    triggers = list(triggers_seed)

    if args.all_triggers:
        triggers_gen_path = DATASET / "triggers_generated.json"
        if triggers_gen_path.exists():
            triggers_gen = json.load(open(triggers_gen_path)).get("triggers", [])
            triggers += triggers_gen
            print(f"  (+{len(triggers_gen)} generated triggers)")

    trigger_ids = []
    for t in triggers:
        tid = t["id"]
        data, status = _req("POST", "/v1/context", {
            "scope": "trigger",
            "context_id": tid,
            "version": 1,
            "payload": t,
            "delivered_at": "2026-04-26T09:46:30Z",
        })
        ok = status in (200,) and data.get("accepted")
        if ok:
            trigger_ids.append(tid)

    print(f"  {len(trigger_ids)} triggers ready")

    # ── 6. Tick in batches of 5 ───────────────────────────────────────────
    print(f"\nRunning tick in batches of 5 across {len(trigger_ids)} triggers...")
    all_actions = []

    for i in range(0, len(trigger_ids), 5):
        batch = trigger_ids[i:i + 5]
        data, status = _req("POST", "/v1/tick", {
            "now": "2026-04-26T10:35:00Z",
            "available_triggers": batch,
        })
        if status == 200 and data:
            actions = data.get("actions", [])
            all_actions.extend(actions)
            print(f"  Batch {i // 5 + 1}: {len(actions)} actions")
        else:
            print(f"  Batch {i // 5 + 1}: WARN status={status}")

    # ── 7. Write JSONL ────────────────────────────────────────────────────
    output_path = Path(args.output)
    with open(output_path, "w", encoding="utf-8") as f:
        for action in all_actions:
            f.write(json.dumps(action, ensure_ascii=False) + "\n")

    print(f"\nWrote {len(all_actions)} actions to {output_path}")
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
