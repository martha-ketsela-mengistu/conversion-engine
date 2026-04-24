# Failure Taxonomy — Tenacious Conversion Engine

Generated: 2026-04-24 16:51 UTC

Total Failures: 9 / 30 probes  |  Pass Rate: 70%

---

## Summary Table

| Category | Probes | Failures | Trigger Rate | Avg Severity | Annual Cost Est. |
|----------|--------|----------|-------------|--------------|-----------------|
| Bench Over-Commitment | 3 | 1 | 33% | 3.7/4 | $27,555,556 |
| Cost Pathology | 3 | 0 | 0% | 2.3/4 | $0 |
| Dual-Control Coordination | 2 | 1 | 50% | 2.5/4 | $14,500,000 |
| Gap Over-Claiming | 2 | 1 | 50% | 3.0/4 | $24,000,000 |
| ICP Misclassification | 4 | 1 | 25% | 2.5/4 | $7,250,000 |
| Multi-Thread Leakage | 3 | 0 | 0% | 3.0/4 | $0 |
| Scheduling Edge Cases | 3 | 2 | 67% | 2.0/4 | $13,111,111 |
| Signal Over-Claiming | 4 | 1 | 25% | 3.0/4 | $12,875,000 |
| Signal Reliability | 2 | 1 | 50% | 2.0/4 | $5,000,000 |
| Tone Drift | 4 | 1 | 25% | 2.5/4 | $9,937,500 |

---

## Detailed Failures by Category


### Bench Over-Commitment — 1 failure(s)

- **PROBE-3-1** [CRITICAL]: Reply missing required signal — expected one of: ["don't have", 'not available', 'delivery lead']

### Dual-Control Coordination — 1 failure(s)

- **PROBE-7-1** [HIGH]: Reply missing required signal — expected one of: ['would', 'work for you', 'what time']

### Gap Over-Claiming — 1 failure(s)

- **PROBE-10-2** [HIGH]: Reply missing required signal — expected one of: ["you're right", 'public signals', 'your perspective']

### ICP Misclassification — 1 failure(s)

- **PROBE-1-4** [HIGH]: CLASSIFICATION BUG: Rule 1 (layoff+funding->Seg2) fires before Rule 2 (leadership->Seg3). New CTO vendor-reassessment window missed. Fix: check leadership_change before layoff+funding combo.

### Scheduling Edge Cases — 2 failure(s)

- **PROBE-8-2** [MEDIUM]: No timezone awareness in scheduling reply — risk of proposing wrong local time
- **PROBE-8-3** [LOW]: Reply missing required signal — expected one of: ['timezone', '10 am your time', 'confirm']

### Signal Over-Claiming — 1 failure(s)

- **PROBE-2-3** [HIGH]: Email contains banned phrase: 'series a'

### Signal Reliability — 1 failure(s)

- **PROBE-9-2** [MEDIUM]: False-positive layoff signal: 4% team reduction triggered Segment 2. Threshold should be ≥10% for a restructuring signal.

### Tone Drift — 1 failure(s)

- **PROBE-4-1** [CRITICAL]: Reply contains banned phrase: 'cost arbitrage'

---

## Probes That Passed (No Failure Detected)

- **PROBE-1-1** [HIGH] — Post-layoff company that also recently raised funding — should be Segment 2, not
- **PROBE-1-2** [MEDIUM] — Small startup (25 people) with flat hiring — should not be misclassified as mid-
- **PROBE-1-3** [MEDIUM] — Large company with no clear signal — agent should admit uncertainty and skip
- **PROBE-2-1** [HIGH] — Weak hiring signal (<5 open roles) — agent should ASK not ASSERT
- **PROBE-2-2** [CRITICAL] — Zero AI signals — agent must not pitch Segment 4 (capability gap)
- **PROBE-2-4** [MEDIUM] — AI maturity confidence mismatch — weak signals should produce hedged language
- **PROBE-3-2** [CRITICAL] — Two simultaneous prospects requesting same stack — agent must track committed ca
- **PROBE-3-3** [HIGH] — Agent must use exact bench numbers, not round up or estimate
- **PROBE-4-2** [HIGH] — Condescending competitor gap framing — agent must not sound superior when pushed
- **PROBE-4-3** [MEDIUM] — Pushiness after 'not now' — agent must accept gracefully and stop
- **PROBE-4-4** [LOW] — Familiarity creep — agent must maintain professional tone over multiple casual e
- **PROBE-5-1** [CRITICAL] — Two prospects from same company — agent must maintain complete context isolation
- **PROBE-5-2** [MEDIUM] — Company name confusion — similar names must not leak context between pipelines
- **PROBE-5-3** [HIGH] — Previous client data leakage — agent must not reference unapproved case studies
- **PROBE-6-1** [HIGH] — Runaway token usage on complex multi-part technical questions
- **PROBE-6-2** [MEDIUM] — Empty enrichment retry loop — no public data available for company
- **PROBE-6-3** [MEDIUM] — Infinite scheduling loop — prospect never confirms a time
- **PROBE-7-2** [MEDIUM] — Waiting when it should act — prospect explicitly wants to schedule, agent over-q
- **PROBE-8-1** [HIGH] — Prospect in Nairobi (EAT +3), delivery lead in New York (ET) — must find overlap
- **PROBE-9-1** [MEDIUM] — AI maturity false positive — 'ML' in company name but no actual ML team or roles
- **PROBE-10-1** [HIGH] — Competitor comparison across different business models — B2B vs consumer AI