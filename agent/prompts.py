"""Email subject lines, angle text, LLM prompt builders, and discovery brief generator."""

from __future__ import annotations
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from agent.enrichment.pipeline import HiringSignalBrief

# Subject lines must start with Context/Question/Follow-up/Request per style guide.
_SUBJECTS: dict[str | None, str] = {
    "segment_1": "Context: your AI hiring strategy post-raise",
    "segment_2": "Context: restructuring window and AI capacity",
    "segment_3": "Question: your AI roadmap entering the new chapter",
    None: "Context: AI capability signals in {industry} — {company}",
}

# Angles are grounded and non-condescending — no fabricated stats, no assertions about prospect failures.
_ANGLES: dict[str | None, str] = {
    "segment_1": (
        "Series A/B companies often hit a recruiting-capacity wall around month four — "
        "the gap between headcount approval and qualified hires closes slower than the runway burns. "
        "Worth a quick call to share what that pattern looks like for teams at your stage?"
    ),
    "segment_2": (
        "Restructuring creates a narrow window to redesign team architecture around AI. "
        "Companies at your size that move during that window tend to come out with a leaner, "
        "higher-leverage engineering org. "
        "Curious whether that framing resonates with how you're thinking about the next 90 days."
    ),
    "segment_3": (
        "New CTO and VP Eng roles have roughly 100 days to set technical direction that sticks. "
        "The question is usually not capability — it's speed of execution. "
        "Happy to share what that transition looks like for teams in a similar position."
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
    template = _SUBJECTS.get(brief.icp_segment, _SUBJECTS[None])
    return template.format(
        company=brief.company_name,
        industry=_primary_industry(brief),
    )


def build_email_prompt(brief: "HiringSignalBrief", prospect_name: str) -> str:
    """Return an LLM prompt that produces a Tenacious-style cold outreach email in HTML."""
    segment = brief.icp_segment
    angle = _ANGLES.get(segment, _ANGLES[None]).format(
        company=brief.company_name,
        industry=_primary_industry(brief),
        gap_area=_gap_area(brief),
    )
    greeting = f"Hi {prospect_name.split()[0]}," if prospect_name else "Hi,"

    return (
        f"Write a cold outreach email to a prospect at {brief.company_name}.\n\n"
        f"Prospect name: {prospect_name or 'unknown'}\n"
        f"ICP segment: {segment or 'none'}\n"
        f"Angle to use: {angle}\n\n"
        f"Signals observed (use these to ground every claim):\n{_format_signals(brief)}\n\n"
        f"Tenacious tone rules — all are mandatory:\n"
        f"- Direct: no filler words, no 'just', 'quick', 'hey'. One clear ask only.\n"
        f"- Grounded: every claim must reference a signal above. Ask rather than assert when signal is weak.\n"
        f"- Honest: do not claim 'aggressive hiring' if fewer than 5 open roles. No invented statistics.\n"
        f"- Professional: use 'engineering team', not 'bench'. No clichés ('top talent', 'world-class').\n"
        f"- Non-condescending: frame any gap as a research finding or question, never as a failure.\n\n"
        f"Formatting rules:\n"
        f"- Plain HTML using <p> tags only. No headers, no lists.\n"
        f"- Maximum 120 words in the body (greeting and signature excluded).\n"
        f"- One ask only: book a 20-min call at {_CAL_LINK}\n"
        f"- No emojis.\n"
        f"- Start with exactly: {greeting}\n"
        f"- End with this exact signature block:\n{_SIGNATURE}"
    )


def build_fallback_html(brief: "HiringSignalBrief", prospect_name: str) -> str:
    """Static HTML email used when the LLM call fails. Follows all style-guide constraints."""
    segment = brief.icp_segment
    angle = _ANGLES.get(segment, _ANGLES[None]).format(
        company=brief.company_name,
        industry=_primary_industry(brief),
        gap_area=_gap_area(brief),
    )
    greeting = f"Hi {prospect_name.split()[0]}," if prospect_name else "Hi,"

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
    """Generate the discovery call context brief for the delivery lead.

    This handoff document is attached to the calendar invite so the human
    can pick up the thread immediately without re-reading the full brief.
    """
    _SEGMENT_LABELS = {
        "segment_1": "Recently-funded Series A/B",
        "segment_2": "Mid-market restructuring",
        "segment_3": "Leadership transition",
        "segment_4": "Specialized capability gap",
    }
    segment_label = _SEGMENT_LABELS.get(brief.icp_segment or "", "Unclassified")
    service_match = (
        "Talent Outsourcing"
        if brief.icp_segment in ("segment_1", "segment_3")
        else "Project Consulting"
    )

    ai_score = brief.ai_maturity.get("score", 0)
    pitch_frame = (
        "Scale existing AI function faster than in-house hiring can support"
        if ai_score >= 2
        else "Stand up first dedicated AI function with an external squad"
    )

    gap_insight = ""
    if brief.competitor_gap:
        gap_insight = brief.competitor_gap.get("actionable_insight", "")

    buying_signals_text = "\n".join(
        f"  • {s}" for s in (brief.buying_window_signals or [])
    ) or "  • No strong buying-window signals detected"

    stack_hint = ", ".join(_extract_tech_stack_hint(brief))

    return (
        "DISCOVERY CALL CONTEXT BRIEF\n"
        + "=" * 42 + "\n"
        + f"Prospect:      {brief.company_name}\n"
        + f"Contact:       {prospect_name} | {prospect_email}"
        + (f" | {prospect_phone}" if prospect_phone else "") + "\n\n"
        + "QUALIFICATION SUMMARY\n"
        + f"  Segment:       {segment_label}\n"
        + f"  Service match: {service_match}\n"
        + f"  AI maturity:   {ai_score}/3\n"
        + f"  Confidence:    {brief.segment_confidence:.0%}\n"
        + f"  Bench needed:  {stack_hint}\n\n"
        + "BUYING WINDOW SIGNALS\n"
        + buying_signals_text + "\n\n"
        + "KEY TALKING POINTS\n"
        + f"  Primary urgency:  {_primary_urgency(brief)}\n"
        + f"  Competitive gap:  {gap_insight or 'See competitor_gap_brief.json'}\n"
        + f"  Pitch frame:      {pitch_frame}\n\n"
        + "REQUIRED DISCUSSION ITEMS FOR DELIVERY LEAD\n"
        + "  Pricing:     Confirm public-tier range aligns with budget; do not quote totals.\n"
        + "  Scope:       Clarify talent outsourcing vs. fixed-scope project.\n"
        + f"  Bench match: Verify {stack_hint} availability before committing capacity.\n"
        + "  Next step:   SOW with milestone payments and Phase 1 termination clause.\n"
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _primary_urgency(brief: "HiringSignalBrief") -> str:
    if brief.funding_events_180d:
        return f"Fresh capital ({len(brief.funding_events_180d)} event(s)) — engineering hiring window open"
    if brief.layoff_events_120d and brief.layoff_events_120d.get("has_recent_layoffs"):
        return "Post-layoff restructuring — team redesign window open"
    if brief.leadership_changes_90d:
        return "New engineering leadership — first 100-day direction-setting window"
    return "Capability gap identified via AI maturity signal"


def _extract_tech_stack_hint(brief: "HiringSignalBrief") -> List[str]:
    industries = brief.firmographics.get("industries", [])
    joined = " ".join(industries).lower()
    if "data" in joined:
        return ["Python", "Data Engineering"]
    if "ml" in joined or "ai" in joined:
        return ["ML Engineering", "Python"]
    return ["Python", "Full-stack"]


def _primary_industry(brief: "HiringSignalBrief") -> str:
    industries = brief.firmographics.get("industries", [])
    return industries[0] if industries else "tech"


def _gap_area(brief: "HiringSignalBrief") -> str:
    gap = brief.competitor_gap or {}
    gaps = gap.get("identified_gaps", [])
    if gaps:
        practices = gaps[0].get("missing_practices", [])
        if practices:
            return practices[0]
    return "AI tooling adoption"


def _format_signals(brief: "HiringSignalBrief") -> str:
    parts: list[str] = []
    emp = brief.firmographics.get("employee_count")
    if emp:
        parts.append(f"- {emp} employees")
    if brief.funding_events_180d:
        parts.append(f"- {len(brief.funding_events_180d)} funding event(s) in the last 180 days")
    layoff = brief.layoff_events_120d
    if layoff and layoff.get("has_recent_layoffs"):
        pct = layoff.get("percentage_laid_off")
        parts.append(
            f"- Recent layoffs ({pct}% of headcount)" if pct else "- Recent layoffs reported"
        )
    if brief.leadership_changes_90d:
        parts.append(f"- {len(brief.leadership_changes_90d)} leadership change(s) in the last 90 days")
    score = brief.ai_maturity.get("score", 0)
    conf = brief.ai_maturity.get("confidence", 0)
    parts.append(f"- AI maturity score: {score}/3 (confidence: {conf:.0%})")
    if brief.segment_confidence < 0.5:
        parts.append("- Note: segment signal is weak — ask rather than assert in the email")
    return "\n".join(parts) if parts else "- Limited public signal data available"
