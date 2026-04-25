"""Email subject lines, angle text, LLM prompt builders, and discovery brief generator."""

from __future__ import annotations
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from agent.enrichment.pipeline import HiringSignalBrief

_SUBJECTS: dict[str | None, str] = {
    "segment_1_series_a_b": "Your AI hiring strategy post-raise",
    "segment_2_mid_market_restructure": "Restructuring window and AI capacity",
    "segment_3_leadership_transition": "Your AI roadmap entering the new chapter",
    "segment_4_specialized_capability": "Discussing {gap_area} at {company}",
    None: "AI capability signals in {industry} — {company}",
}

# Angles are grounded and non-condescending — no fabricated stats, no assertions about prospect failures.
_ANGLES: dict[str | None, str] = {
    "segment_1_series_a_b": (
        "Series A/B companies often hit a recruiting-capacity wall around month four — "
        "the gap between headcount approval and qualified hires closes slower than the runway burns. "
        "Worth a quick call to share what that pattern looks like for teams at your stage?"
    ),
    "segment_2_mid_market_restructure": (
        "Restructuring creates a narrow window to redesign team architecture around AI. "
        "Companies at your size that move during that window tend to come out with a leaner, "
        "higher-leverage engineering org. "
        "Curious whether that framing resonates with how you're thinking about the next 90 days."
    ),
    "segment_3_leadership_transition": (
        "New CTO and VP Eng roles have roughly 100 days to set technical direction that sticks. "
        "The question is usually not capability — it's speed of execution. "
        "Happy to share what that transition looks like for teams in a similar position."
    ),
    "segment_4_specialized_capability": (
        "Three of your peers in {industry} have posted AI-platform-engineer roles in the last 90 days. "
        "Curious whether you've made a deliberate choice not to follow that sector consensus, "
        "or whether {gap_area} is still being scoped."
    ),
    None: (
        "I've been tracking AI adoption patterns across {industry}, and there are a few signals "
        "in your peer group worth discussing — specifically around {gap_area}. "
        "Would 20 minutes to compare notes make sense?"
    ),
}

_SIGNATURE = (
    "<p>Martha<br>"
    "Research Partner<br>"
    "Tenacious Intelligence Corporation<br>"
    "gettenacious.com</p>"
)

_CAL_LINK = "https://cal.com/tenacious/discovery"


def build_subject(brief: "HiringSignalBrief") -> str:
    template = _SUBJECTS.get(brief.primary_segment_match, _SUBJECTS[None])
    return template.format(
        company=brief.prospect_name,
        industry=_primary_industry(brief),
        gap_area=_gap_area(brief),
    )


def build_email_prompt(brief: "HiringSignalBrief", prospect_name: str) -> str:
    """Return an LLM prompt that produces a Tenacious-style cold outreach email in HTML."""
    segment = brief.primary_segment_match
    angle = _ANGLES.get(segment, _ANGLES[None]).format(
        company=brief.prospect_name,
        industry=_primary_industry(brief),
        gap_area=_gap_area(brief),
    )
    greeting = f"Hi {prospect_name.split()[0].rstrip(',.')}," if prospect_name else "Hi,"

    return (
        f"You are a Delivery Lead at Tenacious Intelligence writing a research-grounded outreach email.\n\n"
        f"Prospect: {brief.prospect_name}\n"
        f"Segment: {segment or 'abstain'}\n"
        f"Angle: {angle}\n\n"
        f"Grounded Signals (Hiring Signal Brief):\n{_format_signals(brief)}\n\n"
        f"Competitor Gap Insight:\n{_format_gap(brief)}\n\n"
        f"TENACIOUS TONE MARKERS (Mandatory):\n"
        f"1. Direct: No filler words, no 'just', 'quick', 'hey'.\n"
        f"2. Grounded: Every claim must cite a signal above. No invented stats.\n"
        f"3. Honest: If signal is weak, ASK rather than ASSERT. Never claim 'aggressive hiring' if < 5 open roles.\n"
        f"4. Professional: Use 'engineering team' or 'available capacity', never 'bench'. No offshore clichés.\n"
        f"5. Non-condescending: Frame gaps as research findings or roadmap questions, never as failures.\n\n"
        f"CONSTRAINTS:\n"
        f"- Format: Plain HTML (<p> tags only). No emojis.\n"
        f"- Length: Max 120 words in body.\n"
        f"- Goal: Book a 20-min call at {_CAL_LINK}\n"
        f"- Structure: First <p> must be ONLY the greeting. Body in a separate <p>. CTA in its own <p>. Signature last.\n"
        f"- Greeting: {greeting}\n"
        f"- Signature:\n{_SIGNATURE}"
    )


def build_fallback_html(brief: "HiringSignalBrief", prospect_name: str) -> str:
    """Static HTML email used when the LLM call fails. Follows all style-guide constraints."""
    segment = brief.primary_segment_match
    angle = _ANGLES.get(segment, _ANGLES[None]).format(
        company=brief.prospect_name,
        industry=_primary_industry(brief),
        gap_area=_gap_area(brief),
    )
    greeting = f"Hi {prospect_name.split()[0].rstrip(',.')}," if prospect_name else "Hi,"

    return (
        f"<p>{greeting}</p>"
        f"<p>{angle}</p>"
        f"<p>Would 20 minutes to discuss make sense? "
        f"<a href='{_CAL_LINK}'>Book here</a></p>"
        f"{_SIGNATURE}"
    )


def build_discovery_brief(
    brief: "HiringSignalBrief",
    prospect_name: str,
    prospect_email: str,
    prospect_phone: Optional[str] = None,
) -> str:
    """Generate the discovery call context brief for the delivery lead."""
    _SEGMENT_LABELS = {
        "segment_1_series_a_b": "Recently-funded Series A/B",
        "segment_2_mid_market_restructure": "Mid-market restructuring",
        "segment_3_leadership_transition": "Leadership transition",
        "segment_4_specialized_capability": "Specialized capability gap",
    }
    segment_label = _SEGMENT_LABELS.get(brief.primary_segment_match or "", "Unclassified")
    service_match = (
        "Talent Outsourcing"
        if brief.primary_segment_match in ("segment_1_series_a_b", "segment_3_leadership_transition")
        else "Project Consulting"
    )

    ai_score = brief.ai_maturity.get("score", 0)
    pitch_frame = (
        "Scale existing AI function faster than in-house hiring can support"
        if ai_score >= 2
        else "Stand up first dedicated AI function with an external squad"
    )

    gap_summary = "None detected"
    if brief.competitor_gap:
        gaps = brief.competitor_gap.get("gap_findings", [])
        if gaps:
            gap_summary = f"{gaps[0].get('practice')} (Peer evidence: {len(gaps[0].get('peer_evidence', []))} companies)"

    buying_signals = []
    bw = brief.buying_window_signals
    if bw.get("funding_event", {}).get("detected"):
        fe = bw["funding_event"]
        buying_signals.append(f"Funding: {fe['stage'].upper()} (${fe['amount_usd']:,}) closed {fe['closed_at']}")
    if bw.get("layoff_event", {}).get("detected"):
        buying_signals.append(f"Layoff: {bw['layoff_event']['percentage_cut']}% cut on {bw['layoff_event']['date']}")
    if bw.get("leadership_change", {}).get("detected"):
        buying_signals.append(f"Leadership: New {bw['leadership_change']['role'].upper()} started {bw['leadership_change']['started_at']}")

    signals_text = "\n".join(f"  • {s}" for s in buying_signals) or "  • No strong buying-window signals detected"
    stack_hint = ", ".join(brief.tech_stack[:3])

    return (
        f"PROSPECT CONTEXT: {brief.prospect_name} (Call with: {prospect_name})\n\n"
        + "QUALIFICATION SUMMARY\n"
        + f"  Segment:       {segment_label}\n"
        + f"  Service match: {service_match}\n"
        + f"  AI maturity:   {ai_score}/3\n"
        + f"  Bench match:   {'Sufficient' if brief.bench_to_brief_match.get('bench_available') else 'GAP DETECTED'}\n"
        + f"  Needs:         {stack_hint}\n\n"
        + "KEY TALKING POINTS\n"
        + f"  Primary urgency:  {_primary_urgency(brief)}\n"
        + f"  Competitive gap:  {gap_summary}\n"
        + f"  Pitch frame:      {pitch_frame}\n\n"
        + "BUYING WINDOW SIGNALS\n"
        + signals_text + "\n\n"
        + "REQUIRED DISCUSSION ITEMS FOR DELIVERY LEAD\n"
        + "  Pricing:     Confirm public-tier range aligns with budget; do not quote totals.\n"
        + "  Scope:       Clarify talent outsourcing vs. fixed-scope project.\n"
        + f"  Bench match: Verify {stack_hint} availability before committing capacity.\n"
        + "  Next step:   SOW with milestone payments and Phase 1 termination clause.\n"
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _primary_industry(brief: "HiringSignalBrief") -> str:
    industries = brief.firmographics.get("industries", [])
    return industries[0] if industries else "tech"


def _gap_area(brief: "HiringSignalBrief") -> str:
    if not brief.competitor_gap:
        return "AI adoption"
    gaps = brief.competitor_gap.get("gap_findings", [])
    return gaps[0].get("practice", "AI adoption") if gaps else "AI adoption"


def _primary_urgency(brief: "HiringSignalBrief") -> str:
    bw = brief.buying_window_signals
    if bw.get("funding_event", {}).get("detected"):
        return "Fresh capital — engineering hiring window open"
    if bw.get("layoff_event", {}).get("detected"):
        return "Post-layoff restructuring — team redesign window open"
    if bw.get("leadership_change", {}).get("detected"):
        return "New engineering leadership — first 100-day direction-setting window"
    return "Capability gap identified via AI maturity signal"


def _format_signals(brief: "HiringSignalBrief") -> str:
    parts: list[str] = []
    hv = brief.hiring_velocity
    open_roles = hv.get("open_roles_today") or 0
    confidence = hv.get("signal_confidence", 1.0)
    if open_roles > 0 or confidence >= 0.6:
        parts.append(f"- Open engineering roles: {open_roles}")
        parts.append(f"- Hiring velocity: {hv.get('velocity_label').replace('_', ' ')}")
    
    bw = brief.buying_window_signals
    if bw.get("funding_event", {}).get("detected"):
        fe = bw["funding_event"]
        parts.append(f"- Recent {fe['stage'].upper()} funding round (${fe['amount_usd']:,})")
    
    if bw.get("layoff_event", {}).get("detected"):
        parts.append(f"- Recent layoffs ({bw['layoff_event']['percentage_cut']}% cut)")

    if bw.get("leadership_change", {}).get("detected"):
        parts.append(f"- New {bw['leadership_change']['role'].upper()} recently appointed")

    score = brief.ai_maturity.get("score", 0)
    parts.append(f"- AI maturity score: {score}/3")
    
    if brief.segment_confidence < 0.6:
        parts.append("- Note: signal is weak — ask rather than assert in the email")
    
    for flag in brief.honesty_flags:
        parts.append(f"- Honesty check: {flag.replace('_', ' ')}")
        
    return "\n".join(parts)


def _format_gap(brief: "HiringSignalBrief") -> str:
    if not brief.competitor_gap:
        return "No specific competitor gap identified."
    
    gaps = brief.competitor_gap.get("gap_findings", [])
    if not gaps:
        return "No specific competitor gap identified."
    
    gap = gaps[0]
    peers = ", ".join([p["competitor_name"] for p in gap.get("peer_evidence", [])])
    return (
        f"Practice: {gap['practice']}\n"
        f"Peer evidence from: {peers}\n"
        f"Gap: {gap['prospect_state']}"
    )


# Objection Handling Templates
_OBJECTIONS = {
    "price_higher_than_india": (
        "That's a fair point, and we are not the cheapest. Tenacious is specifically designed to solve "
        "the two biggest failure modes of cheaper offshore teams: reliability and time-zone overlap. "
        "We guarantee a minimum of 3 hours of synchronous overlap, and our talent is high-quality "
        "intensive training graduates. We compete on reliability, not just price."
    ),
    "already_working_with_major_vendor": (
        "That's common for companies at your stage. We don't aim to replace your current partner, "
        "but to fill a specific gap. Our value proposition is the research: we ground our work in "
        "verifiable signals like AI maturity gaps that your current vendor might not be addressing."
    ),
    "small_poc_only": (
        "We excel at starting small. Our goal isn't to force a large engagement. We have fixed-scope "
        "starter projects starting from $[PROJECT_ACV_MIN] USD to prove value quickly."
    )
}


def build_objection_response(objection_key: str) -> str:
    return _OBJECTIONS.get(objection_key, "I understand. Would a quick 15-minute call to align on your specific needs make sense?")


def build_capacity_gap_reply(stack_name: str, count: int, deploy_days: int) -> str:
    """Bench-gated capacity reply with exact numbers. No rounding, no vague estimates."""
    if count <= 0:
        return (
            f"<p>Our {stack_name.capitalize()} bench is currently not staffed. "
            "I can connect you with our delivery lead to explore custom staffing options.</p>"
            "<p>Best,<br>Martha @ Tenacious</p>"
        )
    return (
        f"<p>We have {count} {stack_name} engineers available, "
        f"with {deploy_days}-day deployment readiness.</p>"
        "<p>I can connect you with our delivery lead to confirm scope and timing.</p>"
        "<p>Best,<br>Martha @ Tenacious</p>"
    )
