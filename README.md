# Vera Bot — magicpin AI Challenge Submission

## Architecture

```
POST /v1/context  →  context_store.py  (versioned, 409/400 on conflict)
POST /v1/tick     →  composer.py       (trigger-anchored, 8s budget, circuit breaker)
POST /v1/reply    →  conversation_handlers.py  (intent → auto-reply / hostile / off-topic / commit)
POST /v1/teardown →  wipe all state
GET  /v1/healthz  →  context counts + uptime
GET  /v1/metadata →  team info + model
```

### Composition Pipeline

```
trigger (anchor) + merchant + category + customer?
  → fact_sheet.py          (builds verifiable fact sheet; selects signals in code)
  → response_cache.py      (keyed by prompt_version + model + canonical fact sheet)
  → trigger_router.py      (reality check: skip if contradicted by data)
  → LLM (6s deadline)      (temperature=0, provider-agnostic via LLM_PROVIDER env)
  → provenance_verifier.py (every number + no taboo words + no URLs)
  → fallback_templates.py  (deterministic per trigger kind, <1ms, no LLM)
```

### Key Design Decisions

| Problem | Solution |
|---------|----------|
| Trigger is "why now" anchor | Fact sheet leads with TRIGGER section; merchant facts are supporting evidence |
| No fabricated numbers | provenance_verifier blocks any number not in fact sheet |
| Auto-reply tracking per simulator | State per merchant_id (simulator uses new conv_id per turn) |
| 75 placeholder triggers | Template fallback detects `payload.placeholder=True`, no LLM wasted |
| Hostile vs off-topic split | Hostile → end (or sorry+won't); Off-topic → one-line decline + redirect |
| Commitment → inline delivery | Delivers actual content, not "draft ready, say go" |
| Consent gating | 186/200 customers are promo-only; consent_resolver.py gates per trigger kind |
| 8s tick budget | Circuit breaker + per-action 6s deadline + template fallback |
| Determinism | Response cache + temperature=0 |

## Configuration (env vars)

```bash
LLM_PROVIDER=anthropic   # anthropic | openai | gemini | deepseek | none
LLM_API_KEY=sk-...
COMPOSE_MODEL=           # optional override, defaults to provider default
FAST_MODEL=              # optional override
TEAM_NAME=               # for /v1/metadata
TEAM_MEMBERS=            # comma-separated
CONTACT_EMAIL=           # for /v1/metadata
```

`LLM_PROVIDER=none` = template-only mode. All tests pass without an API key.

## Running Locally

```bash
cd vera-bot
pip install -r requirements.txt

# Template-only mode (no LLM needed):
LLM_PROVIDER=none python -m uvicorn bot:app --host 0.0.0.0 --port 8080

# With Anthropic:
LLM_PROVIDER=anthropic LLM_API_KEY=sk-... python -m uvicorn bot:app --port 8080
```

## Testing

```bash
# Smoke test (25 checks, all endpoints)
python tools/smoke_test.py

# Mini judge lifecycle (13 scenarios)
python tools/local_judge.py

# Generate submission JSONL
python tools/make_submission.py --output submission.jsonl
```

## Deployment

### Cloud Run (asia-south1)
```bash
gcloud builds submit --tag gcr.io/PROJECT/vera-bot
gcloud run deploy vera-bot \
  --image gcr.io/PROJECT/vera-bot \
  --region asia-south1 \
  --min-instances 1 --max-instances 1 \
  --no-cpu-throttling \
  --concurrency 1 \
  --set-env-vars "LLM_PROVIDER=anthropic,LLM_API_KEY=sk-..."
```

### Fly.io (bom)
```bash
fly launch --name vera-bot --region bom --no-deploy
fly secrets set LLM_PROVIDER=anthropic LLM_API_KEY=sk-...
fly deploy
```

Set `min_machines_running = 1` and `auto_stop_machines = false` in `fly.toml`.

## File Map

```
bot.py                       FastAPI app — 6 endpoints
config.py                    Env-var-driven LLM + timing config
models.py                    Pydantic schemas
context_store.py             Versioned context (409/400 on conflict, before/after deltas)
conversation_state.py        Per-merchant state (not per-conv)
suppression.py               Global suppression_key + fatigue caps
composer.py                  Core pipeline: fact_sheet → LLM → verify → fallback
fact_sheet.py                Builds verifiable fact sheet from 4 contexts
trigger_router.py            Trigger → prompt + reality check
provenance_verifier.py       Post-LLM number + taboo check
response_cache.py            Determinism cache
auto_reply_detector.py       40+ patterns, per-merchant state machine
intent_classifier.py         Precedence: opt-out → auto-reply → question → commit
conversation_handlers.py     Reply routing for /v1/reply
consent_resolver.py          Consent gating + parent-proxy name parsing
language_resolver.py         Language detection, no hardcoded Hindi
templates/fallback_templates.py  Deterministic templates, all 25 trigger kinds
docs/RECON.md                Document conflicts + data traps
tools/smoke_test.py          25-check endpoint smoke test
tools/local_judge.py         13-scenario mini judge lifecycle
tools/make_submission.py     Generate submission.jsonl
```
