# Target Failure Mode for Act IV

Generated: 2026-04-24 16:51 UTC

---

## Selected Failure Mode

**Category:** Bench Over-Commitment
**Failure Count:** 1 / 3 probes triggered
**Trigger Rate:** 33%
**Estimated Annual Business Cost:** $413,333

---

## Business Cost Derivation

Based on Tenacious-provided baseline metrics:
| Metric | Value | Source |
|--------|-------|--------|
| Average engagement ACV (talent outsourcing) | $240K–$720K | Tenacious internal |
| Discovery-call-to-proposal conversion | 35–50% | Tenacious internal, last 4 quarters |
| Stalled-thread rate (current manual) | 30–40% | Tenacious executive interview |
| Estimated qualified leads/year (all segments) | 200 | Program baseline |
| Signal-grounded reply rate (top quartile) | 7–12% | Clay / Smartlead case studies |

**At 33% trigger rate across 200 annual leads:**
- Leads affected per year: ~66
- Lost proposals (35% conversion): ~23
- Lost ACV at $240K average: ~$5,599,999
- Brand reputation damage (hard to quantify): adds 20–30% to base cost
- **Total estimated annual cost: $413,333**

---

## Mechanism Direction for Act IV

**Proposed Mechanism: Bench-Gated Commitment Policy**

The email reply webhook has no awareness of bench_summary.json. When a prospect asks
'Do you have Rust engineers?', the agent's auto-reply does not check actual capacity.

**Fix:**
1. Add a `_check_bench_for_stack(stack_name)` helper that reads bench_summary.json
2. Inject bench-check into `handle_email_reply()` when capacity keywords are detected
3. If stack is unavailable: route to delivery lead (human handoff), not generic reply
4. Track committed capacity across active threads to prevent double-booking

**Expected Delta A:** +12–18% on bench-related probes
**Cost of fix:** ~3 hours implementation + webhook update

---

## All Category Costs (Ranked)

| Rank | Category | Trigger Rate | Annual Cost Est. |
|------|----------|-------------|-----------------|
| 1 | Bench Over-Commitment | 33% | $413,333 |
| 2 | Signal Over-Claiming | 25% | $257,500 |
| 3 | Gap Over-Claiming | 50% | $240,000 |
| 4 | Tone Drift | 25% | $198,750 |
| 5 | Scheduling Edge Cases | 67% | $196,667 |
| 6 | ICP Misclassification | 25% | $145,000 |
| 7 | Dual-Control Coordination | 50% | $145,000 |
| 8 | Signal Reliability | 50% | $50,000 |

---

*Next: Implement selected mechanism in Act IV. Measure Delta A on sealed held-out slice (p < 0.05 required).*