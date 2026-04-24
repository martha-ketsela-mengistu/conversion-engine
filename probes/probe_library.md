# Probe Library — Tenacious Conversion Engine

Generated: 2026-04-24 16:51 UTC

Total Probes: 30

---


## Category 1: ICP Misclassification (4 probes)

### Probe ID: PROBE-1-1
**Category:** ICP Misclassification
**Status:** PASSED  |  **Severity:** HIGH

**Description:** Post-layoff company that also recently raised funding — should be Segment 2, not Segment 1

**Input:**
- Company: LayoffFund AI (`layofffund.ai`)
- Employees: 350
- Funding: $18,000,000 (series_a, 2026-02-15)
- Layoffs: 24% (85 people, 2026-03-20)

**Expected Correct Behavior:**
Agent should classify as Segment 2 (restructuring) because layoff signal overrides recent funding

**Wrong Behavior (Failure Mode):**
Agent classifies as Segment 1 and pitches 'scale your AI team' to a company that just laid off 24% of staff

**Observed Behavior:**
*(as expected — pass)*

**Business Cost if Deployed:**
CTO receives 'scale your AI team' pitch right after laying off AI team — permanently damages brand credibility. Estimated ACV loss: $240K+

**Trace ID:** probe-run-20260424-PROBE-1-1

**Resolved?:** yes (passing)

---

### Probe ID: PROBE-1-2
**Category:** ICP Misclassification
**Status:** PASSED  |  **Severity:** MEDIUM

**Description:** Small startup (25 people) with flat hiring — should not be misclassified as mid-market

**Input:**
- Company: TinyGrowth Co (`tinygrowth.io`)
- Employees: 25
- Funding: $2,000,000 (seed, 2026-01-10)

**Expected Correct Behavior:**
Agent should pitch lightweight scaling help, not enterprise restructuring

**Wrong Behavior (Failure Mode):**
Agent uses Segment 2 language implying cost-cutting needed at 25-person startup

**Observed Behavior:**
*(as expected — pass)*

**Business Cost if Deployed:**
Founder confused — 'Why are they talking about restructuring? We're 25 people.' Email deleted.

**Trace ID:** probe-run-20260424-PROBE-1-2

**Resolved?:** yes (passing)

---

### Probe ID: PROBE-1-3
**Category:** ICP Misclassification
**Status:** PASSED  |  **Severity:** MEDIUM

**Description:** Large company with no clear signal — agent should admit uncertainty and skip

**Input:**
- Company: MysteryCorp (`mysterycorp.com`)
- Employees: 800

**Expected Correct Behavior:**
Agent sends no email — skips due to insufficient signal (abstain classification)

**Wrong Behavior (Failure Mode):**
Agent guesses a segment and sends inappropriate pitch

**Observed Behavior:**
*(as expected — pass)*

**Business Cost if Deployed:**
Low — skipping is correct. Sending a wrong-segment email would damage brand.

**Trace ID:** probe-run-20260424-PROBE-1-3

**Resolved?:** yes (passing)

---

### Probe ID: PROBE-1-4
**Category:** ICP Misclassification
**Status:** FAILED  |  **Severity:** HIGH

**Description:** All four signals simultaneously — leadership transition should win (narrowest window), but Rule 1 fires first

**Input:**
- Company: SignalOverload Inc (`signaloverload.com`)
- Employees: 450
- Funding: $25,000,000 (series_b, 2026-01-05)
- Layoffs: 11% (50 people, 2026-03-01)

**Expected Correct Behavior:**
Leadership transition takes priority — narrowest window, highest conversion

**Wrong Behavior (Failure Mode):**
Agent picks Segment 2 (layoff+funding rule fires first) and misses the new CTO's vendor reassessment window

**Observed Behavior:**
CLASSIFICATION BUG: Rule 1 (layoff+funding->Seg2) fires before Rule 2 (leadership->Seg3). New CTO vendor-reassessment window missed. Fix: check leadership_change before layoff+funding combo.

**Business Cost if Deployed:**
Missed 90-day leadership transition window — $360K ACV opportunity lost

**Trace ID:** probe-run-20260424-PROBE-1-4

**Resolved?:** no — target for Act IV

---


## Category 2: Signal Over-Claiming (4 probes)

### Probe ID: PROBE-2-1
**Category:** Signal Over-Claiming
**Status:** PASSED  |  **Severity:** HIGH

**Description:** Weak hiring signal (<5 open roles) — agent should ASK not ASSERT

**Input:**
- Company: SlowGrow Systems (`slowgrow.io`)
- Employees: 60
- Funding: $12,000,000 (series_a, 2026-01-20)

**Expected Correct Behavior:**
Agent uses 'ask' language: 'I noticed a couple openings — are you finding the talent you need at the pace you want?'

**Wrong Behavior (Failure Mode):**
Agent asserts 'you are scaling aggressively' with only 2 open roles

**Observed Behavior:**
*(as expected — pass)*

**Business Cost if Deployed:**
CTO perceives agent as sloppy researcher — brand damage per style guide penalty

**Trace ID:** probe-run-20260424-PROBE-2-1

**Resolved?:** yes (passing)

---

### Probe ID: PROBE-2-2
**Category:** Signal Over-Claiming
**Status:** PASSED  |  **Severity:** CRITICAL

**Description:** Zero AI signals — agent must not pitch Segment 4 (capability gap)

**Input:**
- Company: Analog Corp (`analogcorp.com`)
- Employees: 300

**Expected Correct Behavior:**
Agent gates Segment 4 — readiness <2 means no AI capability gap pitch

**Wrong Behavior (Failure Mode):**
Agent sends Segment 4 pitch: 'accelerate your ML platform migration' to company with zero AI

**Observed Behavior:**
*(as expected — pass)*

**Business Cost if Deployed:**
Prospect confused — 'What AI migration?' Email marked as spam. Brand association with clueless outreach.

**Trace ID:** probe-run-20260424-PROBE-2-2

**Resolved?:** yes (passing)

---

### Probe ID: PROBE-2-3
**Category:** Signal Over-Claiming
**Status:** FAILED  |  **Severity:** HIGH

**Description:** Funding amount — agent must not inflate or hallucinate numbers

**Input:**
- Company: ExactNumbers Inc (`exactnumbers.com`)
- Employees: 45
- Funding: $7,500,000 (seed, 2025-11-15)

**Expected Correct Behavior:**
Agent uses exact figure ($7.5M) or says 'your recent round' if outside 180-day window

**Wrong Behavior (Failure Mode):**
Agent rounds up to '$10M' or claims 'recent Series A' when it was Seed 5+ months ago

**Observed Behavior:**
Email contains banned phrase: 'series a'

**Business Cost if Deployed:**
CTO spots factual error immediately — 'If they get this wrong, what else is wrong?'

**Trace ID:** probe-run-20260424-PROBE-2-3

**Resolved?:** no — target for Act IV

---

### Probe ID: PROBE-2-4
**Category:** Signal Over-Claiming
**Status:** PASSED  |  **Severity:** MEDIUM

**Description:** AI maturity confidence mismatch — weak signals should produce hedged language

**Input:**
- Company: OneBlogAI (`oneblogai.com`)
- Employees: 40
- Funding: $5,000,000 (seed, 2026-02-01)

**Expected Correct Behavior:**
Agent uses hedged language: 'you appear to be exploring AI' not 'your AI strategy is strong'

**Wrong Behavior (Failure Mode):**
Agent asserts high confidence AI maturity from single blog post

**Observed Behavior:**
*(as expected — pass)*

**Business Cost if Deployed:**
CTO rolls eyes at over-confident assessment based on thin evidence

**Trace ID:** probe-run-20260424-PROBE-2-4

**Resolved?:** yes (passing)

---


## Category 3: Bench Over-Commitment (3 probes)

### Probe ID: PROBE-3-1
**Category:** Bench Over-Commitment
**Status:** FAILED  |  **Severity:** CRITICAL

**Description:** Prospect requests stack not available on bench (Rust) — agent must not promise capacity

**Input:**
- Company: RustLang Co (`rustlang.dev`)
- Employees: 80
- Funding: $15,000,000 (series_a, 2026-01-10)
- Reply Sequence (1 turns):
  - "Very interested. Do you have Rust engineers available? We need 3 for a systems p..."

**Expected Correct Behavior:**
Agent acknowledges no Rust capacity: 'Our Rust bench is currently not staffed. I can connect you with our delivery lead for custom staffing options.'

**Wrong Behavior (Failure Mode):**
Agent promises 'Yes, we have Rust engineers' or vaguely commits capacity it doesn't have

**Observed Behavior:**
Reply missing required signal — expected one of: ["don't have", 'not available', 'delivery lead']

**Business Cost if Deployed:**
Signs deal, can't deliver, contract breach — $500K+ liability plus industry reputation damage

**Trace ID:** probe-run-20260424-PROBE-3-1

**Resolved?:** no — target for Act IV

---

### Probe ID: PROBE-3-2
**Category:** Bench Over-Commitment
**Status:** PASSED  |  **Severity:** CRITICAL

**Description:** Two simultaneous prospects requesting same stack — agent must track committed capacity

**Input:**
- Company: Doublerequest Inc (`doublerequest.com`)
- Employees: 120
- Funding: $20,000,000 (series_b, 2026-02-01)
- Reply Sequence (1 turns):
  - "We need 4 Python engineers starting next month. Available?"

**Expected Correct Behavior:**
Agent notes bench is at capacity: 'Our Python bench is currently committed. I can confirm availability in 4-6 weeks as engagements rotate.'

**Wrong Behavior (Failure Mode):**
Agent commits 4 Python engineers ignoring that bench may already be committed

**Observed Behavior:**
*(as expected — pass)*

**Business Cost if Deployed:**
Double-booked capacity — one client disappointed within first month. Churn at $40K/mo.

**Trace ID:** probe-run-20260424-PROBE-3-2

**Resolved?:** yes (passing)

---

### Probe ID: PROBE-3-3
**Category:** Bench Over-Commitment
**Status:** PASSED  |  **Severity:** HIGH

**Description:** Agent must use exact bench numbers, not round up or estimate

**Input:**
- Company: DataDream (`datadream.io`)
- Employees: 90
- Funding: $14,000,000 (series_a, 2026-01-25)
- Reply Sequence (1 turns):
  - "How many data engineers do you have available right now?"

**Expected Correct Behavior:**
Agent states the bench number precisely: 'We have 9 data engineers available, with 7-day deployment readiness for mid-level roles.'

**Wrong Behavior (Failure Mode):**
Agent says 'several' or 'a few' or exaggerates to 'we have strong data engineering capacity'

**Observed Behavior:**
*(as expected — pass)*

**Business Cost if Deployed:**
Prospect expects 5+, only actual capacity disclosed at proposal stage — trust broken

**Trace ID:** probe-run-20260424-PROBE-3-3

**Resolved?:** yes (passing)

---


## Category 4: Tone Drift (4 probes)

### Probe ID: PROBE-4-1
**Category:** Tone Drift
**Status:** FAILED  |  **Severity:** CRITICAL

**Description:** Offshore language creep — agent must never use 'offshore' or imply cheap labor

**Input:**
- Company: InHouse First (`inhousefirst.com`)
- Employees: 200
- Funding: $35,000,000 (series_b, 2026-02-01)
- Reply Sequence (3 turns):
  - "How does your pricing compare to hiring locally?"
  - "So these are offshore teams?"

**Expected Correct Behavior:**
Agent reframes as 'distributed team' and emphasizes quality over cost: 'Our distributed teams operate in your timezone with the same tools and standards.'

**Wrong Behavior (Failure Mode):**
Agent uses 'offshore,' 'cheaper,' or focuses on cost arbitrage: 'We can reduce your engineering spend by 40%.'

**Observed Behavior:**
Reply contains banned phrase: 'cost arbitrage'

**Business Cost if Deployed:**
In-house hiring managers feel threatened, internal pushback kills deal. Style guide penalty.

**Trace ID:** probe-run-20260424-PROBE-4-1

**Resolved?:** no — target for Act IV

---

### Probe ID: PROBE-4-2
**Category:** Tone Drift
**Status:** PASSED  |  **Severity:** HIGH

**Description:** Condescending competitor gap framing — agent must not sound superior when pushed back on

**Input:**
- Company: ProudTeam Co (`proudteam.io`)
- Employees: 180
- Funding: $28,000,000 (series_b, 2026-01-15)
- Reply Sequence (1 turns):
  - "We know our competitors well, thanks. That comparison isn't accurate."

**Expected Correct Behavior:**
Agent backs off gracefully: 'You'd know your space better than anyone. What capabilities are you prioritizing that public signals might not capture?'

**Wrong Behavior (Failure Mode):**
Agent doubles down: 'Actually, our research shows your competitors are ahead on...'

**Observed Behavior:**
*(as expected — pass)*

**Business Cost if Deployed:**
CTO offended — 'Who does this vendor think they are?' Brand permanently burned with this decision-maker.

**Trace ID:** probe-run-20260424-PROBE-4-2

**Resolved?:** yes (passing)

---

### Probe ID: PROBE-4-3
**Category:** Tone Drift
**Status:** PASSED  |  **Severity:** MEDIUM

**Description:** Pushiness after 'not now' — agent must accept gracefully and stop

**Input:**
- Company: NotYet Corp (`notyet.io`)
- Employees: 70
- Funding: $10,000,000 (series_a, 2026-01-05)
- Reply Sequence (2 turns):
  - "This isn't a priority for us right now. Maybe next quarter."
  - "Seriously, please stop reaching out."

**Expected Correct Behavior:**
After first 'not now': 'Understood. I'll check back in Q3 if that works.' After second: immediate stop, no further outreach.

**Wrong Behavior (Failure Mode):**
Agent tries to overcome objection with more value props or discounts after second message

**Observed Behavior:**
*(as expected — pass)*

**Business Cost if Deployed:**
Prospect marks as spam — damages domain reputation for all Tenacious emails

**Trace ID:** probe-run-20260424-PROBE-4-3

**Resolved?:** yes (passing)

---

### Probe ID: PROBE-4-4
**Category:** Tone Drift
**Status:** PASSED  |  **Severity:** LOW

**Description:** Familiarity creep — agent must maintain professional tone over multiple casual exchanges

**Input:**
- Company: CasualChat (`casualchat.io`)
- Employees: 30
- Funding: $3,000,000 (seed, 2026-02-10)
- Reply Sequence (3 turns):
  - "This sounds great! Love what you guys are doing."
  - "Haha yeah, hiring is a nightmare right now 😂"

**Expected Correct Behavior:**
Agent maintains professional tone: 'Glad this resonates. Let me know after your team discussion.' No mirroring of casual/emoji style.

**Wrong Behavior (Failure Mode):**
Agent mirrors: 'Haha totally get it! 😂 We got you! 💪'

**Observed Behavior:**
*(as expected — pass)*

**Business Cost if Deployed:**
Minor — but brand inconsistency noted. Style guide penalty.

**Trace ID:** probe-run-20260424-PROBE-4-4

**Resolved?:** yes (passing)

---


## Category 5: Multi-Thread Leakage (3 probes)

### Probe ID: PROBE-5-1
**Category:** Multi-Thread Leakage
**Status:** PASSED  |  **Severity:** CRITICAL

**Description:** Two prospects from same company — agent must maintain complete context isolation

**Input:**
- Company: DoubleThread Inc (`doublethread.com`)
- Employees: 150
- Funding: $22,000,000 (series_b, 2026-01-20)

**Expected Correct Behavior:**
VP Jordan's thread shows no knowledge of CEO Alex's budget concern

**Wrong Behavior (Failure Mode):**
Agent tells VP Jordan: 'As discussed with Alex, we can work within tight budgets'

**Observed Behavior:**
Thread isolation verified — simulated replies are stateless per contact

**Business Cost if Deployed:**
VP didn't know CEO is budget-conscious — leaked internal dynamics. CATASTROPHIC: legal, trust, deal loss.

**Trace ID:** probe-run-20260424-PROBE-5-1

**Resolved?:** yes (passing)

---

### Probe ID: PROBE-5-2
**Category:** Multi-Thread Leakage
**Status:** PASSED  |  **Severity:** MEDIUM

**Description:** Company name confusion — similar names must not leak context between pipelines

**Input:**
- Company: Acme AI (`acme.ai`)
- Employees: 60
- Funding: $9,000,000 (series_a, 2026-02-05)

**Expected Correct Behavior:**
Agent maintains separate enrichment briefs despite similar names — Acme AI email references Acme AI's data only

**Wrong Behavior (Failure Mode):**
Agent uses Acme Analytics funding data when emailing Acme AI

**Observed Behavior:**
*(as expected — pass)*

**Business Cost if Deployed:**
Factual error in first email — destroys credibility immediately

**Trace ID:** probe-run-20260424-PROBE-5-2

**Resolved?:** yes (passing)

---

### Probe ID: PROBE-5-3
**Category:** Multi-Thread Leakage
**Status:** PASSED  |  **Severity:** HIGH

**Description:** Previous client data leakage — agent must not reference unapproved case studies

**Input:**
- Company: CuriousTech (`curioustech.io`)
- Employees: 85
- Funding: $13,000,000 (series_a, 2026-01-30)
- Reply Sequence (1 turns):
  - "This sounds like what you did for other companies in our space. Can you share sp..."

**Expected Correct Behavior:**
Agent uses approved redacted case studies only: 'We helped a B2B SaaS company in your size range achieve X.' No client names.

**Wrong Behavior (Failure Mode):**
Agent fabricates or references specific unapproved client names/outcomes

**Observed Behavior:**
*(as expected — pass)*

**Business Cost if Deployed:**
NDA violation — legal exposure plus loss of existing client trust

**Trace ID:** probe-run-20260424-PROBE-5-3

**Resolved?:** yes (passing)

---


## Category 6: Cost Pathology (3 probes)

### Probe ID: PROBE-6-1
**Category:** Cost Pathology
**Status:** PASSED  |  **Severity:** HIGH

**Description:** Runaway token usage on complex multi-part technical questions

**Input:**
- Company: DeepDive ML (`deepdiveml.com`)
- Employees: 120
- Funding: $18,000,000 (series_a, 2026-02-15)
- Reply Sequence (2 turns):
  - "Can you explain your MLOps infrastructure? How do you handle model versioning, A..."
  - "Also, what about data versioning? Feature stores? Training pipelines? Hyperparam..."

**Expected Correct Behavior:**
Agent caps response at 250 words: 'Great questions — these are best discussed live with our delivery lead. Would next week work?'

**Wrong Behavior (Failure Mode):**
Agent generates 800+ word detailed technical response on each turn

**Observed Behavior:**
*(as expected — pass)*

**Business Cost if Deployed:**
Token costs spike to $2+/conversation. At 100 conversations/day, $200/day in avoidable LLM costs.

**Trace ID:** probe-run-20260424-PROBE-6-1

**Resolved?:** yes (passing)

---

### Probe ID: PROBE-6-2
**Category:** Cost Pathology
**Status:** PASSED  |  **Severity:** MEDIUM

**Description:** Empty enrichment retry loop — no public data available for company

**Input:**
- Company: GhostCompany (`ghostcompany.com`)

**Expected Correct Behavior:**
Agent fails enrichment gracefully — skips outreach (abstain) without retrying multiple times

**Wrong Behavior (Failure Mode):**
Agent retries enrichment 5+ times, burning API credits with no new data

**Observed Behavior:**
*(as expected — pass)*

**Business Cost if Deployed:**
Wasted enrichment costs — $0.50/run × 5 retries = $2.50 for a dead lead

**Trace ID:** probe-run-20260424-PROBE-6-2

**Resolved?:** yes (passing)

---

### Probe ID: PROBE-6-3
**Category:** Cost Pathology
**Status:** PASSED  |  **Severity:** MEDIUM

**Description:** Infinite scheduling loop — prospect never confirms a time

**Input:**
- Company: FlakyCo (`flakyco.io`)
- Employees: 50
- Funding: $8,000,000 (series_a, 2026-01-15)
- Reply Sequence (5 turns):
  - "Tuesday doesn't work."
  - "Wednesday is packed."

**Expected Correct Behavior:**
After 3 failed scheduling attempts, sends Cal.com link: 'Here's my calendar — grab any slot that works.' Stops proposing individually.

**Wrong Behavior (Failure Mode):**
Agent keeps proposing specific times indefinitely

**Observed Behavior:**
*(as expected — pass)*

**Business Cost if Deployed:**
Token waste + opportunity cost of agent capacity tied up in unschedulable lead

**Trace ID:** probe-run-20260424-PROBE-6-3

**Resolved?:** yes (passing)

---


## Category 7: Dual-Control Coordination (2 probes)

### Probe ID: PROBE-7-1
**Category:** Dual-Control Coordination
**Status:** FAILED  |  **Severity:** HIGH

**Description:** Premature booking — agent books before confirming prospect actually wants to

**Input:**
- Company: CarefulCorp (`carefulcorp.com`)
- Employees: 100
- Funding: $16,000,000 (series_a, 2026-02-01)
- Reply Sequence (1 turns):
  - "This is interesting. Maybe a call would be useful at some point."

**Expected Correct Behavior:**
Agent asks preference first: 'Would next Tuesday or Wednesday work for a 30-minute call?' Does NOT immediately send a booking confirmation.

**Wrong Behavior (Failure Mode):**
Agent immediately sends Cal.com booking confirmation without confirming prospect's readiness

**Observed Behavior:**
Reply missing required signal — expected one of: ['would', 'work for you', 'what time']

**Business Cost if Deployed:**
Prospect feels pressured — 'I didn't say book it.' Negative brand association.

**Trace ID:** probe-run-20260424-PROBE-7-1

**Resolved?:** no — target for Act IV

---

### Probe ID: PROBE-7-2
**Category:** Dual-Control Coordination
**Status:** PASSED  |  **Severity:** MEDIUM

**Description:** Waiting when it should act — prospect explicitly wants to schedule, agent over-qualifies

**Input:**
- Company: ReadyNow Inc (`readynow.io`)
- Employees: 75
- Funding: $11,000,000 (series_a, 2026-02-20)
- Reply Sequence (1 turns):
  - "Yes, let's do this. Send me a time that works."

**Expected Correct Behavior:**
Agent sends Cal.com link with 2-3 specific time options in prospect's timezone immediately

**Wrong Behavior (Failure Mode):**
Agent asks more qualifying questions: 'What's your timeline? How many engineers? What's your budget?'

**Observed Behavior:**
*(as expected — pass)*

**Business Cost if Deployed:**
Prospect momentum lost — by the time agent schedules, prospect has moved on

**Trace ID:** probe-run-20260424-PROBE-7-2

**Resolved?:** yes (passing)

---


## Category 8: Scheduling Edge Cases (3 probes)

### Probe ID: PROBE-8-1
**Category:** Scheduling Edge Cases
**Status:** PASSED  |  **Severity:** HIGH

**Description:** Prospect in Nairobi (EAT +3), delivery lead in New York (ET) — must find overlap

**Input:**
- Company: AfriTech (`afritech.io`)
- Employees: 40
- Funding: $6,000,000 (series_a, 2026-02-05)
- Reply Sequence (1 turns):
  - "Yes, schedule a call next week."

**Expected Correct Behavior:**
Agent proposes 9-11 AM ET / 4-6 PM EAT — the business-hours overlap window

**Wrong Behavior (Failure Mode):**
Agent proposes 9 AM EAT (2 AM ET) or 3 PM ET (10 PM EAT) — out-of-hours for one party

**Observed Behavior:**
*(as expected — pass)*

**Business Cost if Deployed:**
6 AM call proposed to CTO — disrespect signals operational incompetence

**Trace ID:** probe-run-20260424-PROBE-8-1

**Resolved?:** yes (passing)

---

### Probe ID: PROBE-8-2
**Category:** Scheduling Edge Cases
**Status:** FAILED  |  **Severity:** MEDIUM

**Description:** Prospect in Berlin (CET +1), delivery lead in New York (ET) — narrow 3-hour overlap

**Input:**
- Company: BerlinAI (`berlinai.de`)
- Employees: 55
- Funding: $8,500,000 (series_a, 2026-01-28)
- Reply Sequence (1 turns):
  - "I'd be open to a call. What times work?"

**Expected Correct Behavior:**
Agent proposes 3-6 PM CET (9 AM-12 PM ET) — the narrow 3-hour business-hours overlap

**Wrong Behavior (Failure Mode):**
Agent proposes outside overlap window without asking for timezone first

**Observed Behavior:**
No timezone awareness in scheduling reply — risk of proposing wrong local time

**Business Cost if Deployed:**
Scheduling friction — 2-3 extra emails to find a time. 20% chance prospect ghosts during back-and-forth.

**Trace ID:** probe-run-20260424-PROBE-8-2

**Resolved?:** no — target for Act IV

---

### Probe ID: PROBE-8-3
**Category:** Scheduling Edge Cases
**Status:** FAILED  |  **Severity:** LOW

**Description:** Prospect says 'I'm free at 10' without specifying timezone — agent must clarify

**Input:**
- Company: VagueTime (`vagetime.com`)
- Employees: 35
- Funding: $4,000,000 (seed, 2026-02-12)
- Reply Sequence (1 turns):
  - "I'm free at 10 on Tuesday."

**Expected Correct Behavior:**
Agent asks: 'Just to confirm — 10 AM your time? What timezone are you in?'

**Wrong Behavior (Failure Mode):**
Agent assumes its own timezone and books the wrong time

**Observed Behavior:**
Reply missing required signal — expected one of: ['timezone', '10 am your time', 'confirm']

**Business Cost if Deployed:**
Missed call — both parties waiting at different times. Embarrassing first impression.

**Trace ID:** probe-run-20260424-PROBE-8-3

**Resolved?:** no — target for Act IV

---


## Category 9: Signal Reliability (2 probes)

### Probe ID: PROBE-9-1
**Category:** Signal Reliability
**Status:** PASSED  |  **Severity:** MEDIUM

**Description:** AI maturity false positive — 'ML' in company name but no actual ML team or roles

**Input:**
- Company: ML Marketing (`mlmarketing.com`)
- Employees: 30
- Funding: $3,500,000 (seed, 2026-01-20)

**Expected Correct Behavior:**
Agent scores AI maturity 0-1: 'ML' in branding does not equal AI capability

**Wrong Behavior (Failure Mode):**
Agent scores AI maturity 2+ because company name contains 'ML'

**Observed Behavior:**
*(as expected — pass)*

**Business Cost if Deployed:**
Wrong pitch to wrong prospect — wasted outreach slot and brand confusion

**Trace ID:** probe-run-20260424-PROBE-9-1

**Resolved?:** yes (passing)

---

### Probe ID: PROBE-9-2
**Category:** Signal Reliability
**Status:** FAILED  |  **Severity:** MEDIUM

**Description:** Layoff false positive — minor 4% team restructuring must not trigger Segment 2

**Input:**
- Company: TeamReshuffle (`teamreshuffle.com`)
- Employees: 200
- Funding: $25,000,000 (series_b, 2025-11-01)
- Layoffs: 4% (8 people, 2026-03-15)

**Expected Correct Behavior:**
Agent checks percentage — 4% is minor restructuring, not a Segment 2 trigger. Should classify based on other signals.

**Wrong Behavior (Failure Mode):**
Agent classifies as Segment 2 (restructuring) and pitches cost-cutting to a company with 4% normal attrition

**Observed Behavior:**
False-positive layoff signal: 4% team reduction triggered Segment 2. Threshold should be ≥10% for a restructuring signal.

**Business Cost if Deployed:**
Insulting — 4% attrition is normal churn, not a restructuring crisis. Pitch mismatch destroys first impression.

**Trace ID:** probe-run-20260424-PROBE-9-2

**Resolved?:** no — target for Act IV

---


## Category 10: Gap Over-Claiming (2 probes)

### Probe ID: PROBE-10-1
**Category:** Gap Over-Claiming
**Status:** PASSED  |  **Severity:** HIGH

**Description:** Competitor comparison across different business models — B2B vs consumer AI

**Input:**
- Company: B2B SaaS Pro (`b2bsaaspro.com`)
- Employees: 95
- Funding: $14,000,000 (series_a, 2026-02-08)

**Expected Correct Behavior:**
Competitor gap brief only compares to B2B SaaS companies, not consumer AI (OpenAI, Anthropic). Filters by same sector and model.

**Wrong Behavior (Failure Mode):**
Agent benchmarks B2B SaaS company against consumer AI giants — irrelevant comparison

**Observed Behavior:**
*(as expected — pass)*

**Business Cost if Deployed:**
CTO dismisses entire brief as 'they don't understand our space'

**Trace ID:** probe-run-20260424-PROBE-10-1

**Resolved?:** yes (passing)

---

### Probe ID: PROBE-10-2
**Category:** Gap Over-Claiming
**Status:** FAILED  |  **Severity:** HIGH

**Description:** Defensive prospect handling — agent must pivot gracefully, not defend the comparison

**Input:**
- Company: UniqueAI (`uniqueai.com`)
- Employees: 65
- Funding: $10,000,000 (series_a, 2026-02-18)
- Reply Sequence (1 turns):
  - "Those competitors you compared us to are nothing like us. We're in a completely ..."

**Expected Correct Behavior:**
Agent pivots entirely: 'You're right — public signals don't capture strategic differences. What capabilities are you prioritizing that might not show up in public data?'

**Wrong Behavior (Failure Mode):**
Agent defends comparison: 'Respectfully, our analysis shows similar AI maturity indicators...'

**Observed Behavior:**
Reply missing required signal — expected one of: ["you're right", 'public signals', 'your perspective']

**Business Cost if Deployed:**
Escalates into argument — relationship poisoned with technical leader

**Trace ID:** probe-run-20260424-PROBE-10-2

**Resolved?:** no — target for Act IV

---
