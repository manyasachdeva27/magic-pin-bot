# RECON — Document Conflicts & Data Traps

**Generated**: 2026-04-26  
**Confirmed by**: `scratch/analyze_traps.py`, `scratch/analyze_conflicts.py`

---

## 1. Document Conflicts

| # | Source A | Source B | Conflict | Resolution |
|---|---------|---------|----------|------------|
| 1 | `testing-brief` §3.1: `voice.taboos` | Actual `categories/*.json`: `voice.vocab_taboo` | Key name mismatch | Read both `vocab_taboo` and `taboos`; data uses `vocab_taboo` |
| 2 | `testing-brief` §2.2: CTA = `binary_yes_stop` | `api-call-examples` L271: `binary_yes_no`, L431: `multi_choice_slot`, L506: `binary_confirm_cancel` | CTA enum inconsistent across docs | Use descriptive CTA strings; judge is flexible |
| 3 | `testing-brief` §5: timeout = 30s | `api-call-examples` summary table: tick=10s, reply=10s | `judge_simulator.py` L425: tick=15s, L430: reply=15s | Design for **8s internal budget** |
| 4 | `testing-brief` §2.1: "same version is a no-op" | `api-call-examples` §1.5: same version → HTTP 409 `stale_version` | 200-no-op vs 409 | Return **409** for version ≤ current (matches example) |
| 5 | `testing-brief` §7 skeleton: returns 200 `accepted:false` | `api-call-examples` §1.5: HTTP 409 status code | Status code mismatch | Use proper HTTP 409 |
| 6 | `testing-brief` §2.3: "30 seconds" | `api-call-examples` summary: 10s for `/v1/reply` | Reply latency budget | Target 8s |
| 7 | `judge_simulator.py` L694: `conv_auto_{i}` (new id per turn) | Implied: conversation state keyed by conv_id | Auto-reply tracking breaks if per-conv | Track per **merchant_id** |
| 8 | `judge_simulator.py` L727: `conv_intent_1` (never started) | Bot only knows conversations it initiated via tick | `/v1/reply` for unknown conv_id | Handle gracefully — create state on-the-fly |
| 9 | `judge_simulator.py` L765: `conv_hostile` (never started) | Same as #8 | Same pattern | Same resolution |
| 10 | `trg_006`: `days_until=188`, `urgency=1` | 188 days is ~6 months — irrelevant for "why now" | Diwali trigger fires in April for October | Skip or low-priority; urgency=1 confirms |

---

## 2. Data Traps

### Trap 1: Consent Scope Uniformity
- `generate_dataset.py` L198: ALL 185 generated customers get `scope: ["promotional_offers"]`
- Only 15 seed customers have varied consent
- **186 of 200 customers = promo-only consent**
- Impact: `recall_due` trigger for a promo-only customer → must skip or warn merchant

Seed consent breakdown:
| Customer | Consent Scope |
|----------|--------------|
| c_001 (Priya) | recall_reminders, appointment_reminders |
| c_002 (Rohit) | recall_reminders, appointment_reminders, treatment_followup |
| c_003 (Aanya) | recall_reminders |
| c_004 (Sneha) | appointment_reminders, promotional_offers, stylist_specific |
| c_005 (Kavya) | appointment_reminders, bridal_package_followup |
| c_006 (Amit) | promotional_offers, match_night_specials |
| c_007 (Naveen) | promotional_offers, lunch_thali_updates |
| c_008 (Dipti) | promotional_offers |
| c_009 (Arjun) | program_updates, renewal_reminders |
| c_010 (Rashmi) | renewal_reminders, winback_offers |
| c_011 (Sumitra) | program_updates, health_content, renewal_reminders |
| c_012 (Karthik Jr) | kids_program_updates |
| c_013 (Mr. Sharma) | refill_reminders, delivery_notifications, recall_alerts |
| c_014 (Priti) | promotional_offers, seasonal_health_content |
| c_015 (anonymous) | **EMPTY** |

### Trap 2: Parent-Proxy Names
- `c_003`: `"Aanya (parent: Sneha)"` — child patient, message goes to parent Sneha
- `c_012`: `"Karthik (parent: Sumitra)"`, `channel=whatsapp_via_parent`
- Must parse `(parent: X)` and address message to parent name

### Trap 3: Senior Via Son
- `c_013`: `"Mr. Sharma"`, `senior_citizen=true`, `channel=whatsapp_via_son`
- Message reaches son's phone; must acknowledge proxy routing

### Trap 4: Unreachable Customer
- `c_015`: `phone=null`, `channel=none_recorded`, `reminder_opt_in=false`, `consent_scope=[]`
- **Cannot be contacted under any circumstance**

### Trap 5: Placeholder Triggers (75 of 100)
- `generate_dataset.py` L239: `payload={"placeholder": True, "metric_or_topic": kind}`
- 25 seeds have real payloads; 75 generated have NO specifics
- Bot MUST NOT fabricate numbers for placeholder triggers
- Use template fallback for these

### Trap 6: Severe Performance Dips
- `m_002` (Bharat): calls -50%, views -22%, unverified, renewal in 12 days, no offers
- `m_004` (Glamour): calls -30%, views -12%, subscription expired 38 days ago
- `m_007` (Powerhouse): calls -35%, views -30%, BUT `is_expected_seasonal=true`
- Only Powerhouse gets "normal seasonal" framing. Bharat and Glamour need honest responses.

### Trap 7: Expired/Trial Subscription Merchants
- `m_004` (Glamour): `status=expired`, `days_since_expiry=38`
- `m_005` (Pizza Junction): `status=trial`, `days_remaining=7`
- `m_002` (Bharat): `status=active` but `days_remaining=12`
- Don't pitch features that require active subscription to an expired merchant

---

## 3. Trigger Kind → Required Consent Mapping

| Trigger Kind | Required Consent Scope | Notes |
|-------------|----------------------|-------|
| recall_due | recall_reminders | Only 3 customers have this |
| chronic_refill_due | refill_reminders | Only Mr. Sharma (c_013) |
| trial_followup | promotional_offers | Most customers qualify |
| customer_lapsed_hard | winback_offers | Only Rashmi (c_010) |
| wedding_package_followup | bridal_package_followup | Only Kavya (c_005) |
| (merchant-scoped) | N/A | No customer consent needed |

---

## 4. Trigger Kind Enumeration (25 seeds)

| Kind | Scope | Count | Has Real Payload |
|------|-------|-------|-----------------|
| active_planning_intent | merchant | 2 | ✓ |
| category_seasonal | merchant | 1 | ✓ |
| cde_opportunity | merchant | 1 | ✓ |
| chronic_refill_due | customer | 1 | ✓ |
| competitor_opened | merchant | 1 | ✓ |
| curious_ask_due | merchant | 1 | ✓ |
| customer_lapsed_hard | customer | 1 | ✓ |
| dormant_with_vera | merchant | 1 | ✓ |
| festival_upcoming | merchant | 1 | ✓ (but days_until=188) |
| gbp_unverified | merchant | 1 | ✓ |
| ipl_match_today | merchant | 1 | ✓ |
| milestone_reached | merchant | 1 | ✓ |
| perf_dip | merchant | 1 | ✓ |
| perf_spike | merchant | 1 | ✓ |
| recall_due | customer | 1 | ✓ |
| regulation_change | merchant | 1 | ✓ |
| renewal_due | merchant | 1 | ✓ |
| research_digest | merchant | 1 | ✓ |
| review_theme_emerged | merchant | 1 | ✓ |
| seasonal_perf_dip | merchant | 1 | ✓ |
| supply_alert | merchant | 1 | ✓ |
| trial_followup | customer | 1 | ✓ |
| wedding_package_followup | customer | 1 | ✓ |
| winback_eligible | merchant | 1 | ✓ |
