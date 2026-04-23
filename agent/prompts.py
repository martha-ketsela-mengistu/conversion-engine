"""Email subject lines, angle text, and LLM prompt builders per ICP segment."""

from __future__ import annotations
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from enrichment.pipeline import HiringSignalBrief

_SUBJECTS: dict[str | None, str] = {
    "segment_1": "Congrats on the raise — one thought on your AI hiring curve",
    "segment_2": "Restructuring + AI: the timing is better than it looks",
    "segment_3": "New leadership chapter — one question on your AI roadmap",
    None: "AI capability gap in {industry} — quick note for {company}",
}

_ANGLES: dict[str | None, str] = {
    "segment_1": (
        "You just raised a round, which means you're about to hire fast. "
        "The 90-day window post-funding is when AI-native teams compound their advantage. "
        "We helped three Series A companies build this playbook last quarter."
    ),
    "segment_2": (
        "Restructuring is painful — but it's also a rare window to redesign the team around AI. "
        "Companies that get this right reduce headcount costs by 30% while doubling throughput. "
        "Happy to share what that looks like for {industry} specifically."
    ),
    "segment_3": (
        "New CTO/VP Eng roles have about 100 days to set technical direction. "
        "The teams that move fastest on AI in that window own the roadmap for three years. "
        "We've worked with five engineering leaders through this exact transition."
    ),
    None: (
        "I came across {company} while researching AI adoption in {industry}. "
        "Your current stack suggests a gap in {gap_area} — something your direct competitors are moving on. "
        "Worth a 20-min call to compare notes?"
    ),
}

_CAL_LINK = "https://cal.com/tenacious/discovery"


def build_subject(brief: "HiringSignalBrief") -> str:
    template = _SUBJECTS.get(brief.icp_segment, _SUBJECTS[None])
    return template.format(
        company=brief.company_name,
        industry=_primary_industry(brief),
    )


def build_email_prompt(brief: "HiringSignalBrief", prospect_name: str) -> str:
    """Return an LLM prompt that produces a cold outreach email in HTML."""
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
        f"Signals observed:\n{_format_signals(brief)}\n\n"
        f"Instructions:\n"
        f"- Format as plain HTML using <p> tags only (no headers, no <ul>/<li>)\n"
        f"- 3-4 short paragraphs maximum\n"
        f"- Be specific — reference the actual signals above\n"
        f"- Close with a soft CTA to book a 20-min call: {_CAL_LINK}\n"
        f"- Start with exactly: {greeting}\n"
        f"- Sign off as: Martha @ Tenacious"
    )


def build_fallback_html(brief: "HiringSignalBrief", prospect_name: str) -> str:
    """Static HTML email used when the LLM call fails."""
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
        f"<p>{_format_signals(brief)}</p>"
        f"<p>Would a 20-min call make sense? "
        f"<a href='{_CAL_LINK}'>Book here</a></p>"
        f"<p>Best,<br>Martha @ Tenacious</p>"
    )


def _primary_industry(brief: "HiringSignalBrief") -> str:
    industries = brief.firmographics.get("industries", [])
    return industries[0] if industries else "tech"


def _gap_area(brief: "HiringSignalBrief") -> str:
    gap = brief.competitor_gap or {}
    gaps = gap.get("gaps", [])
    return gaps[0].get("capability", "AI tooling") if gaps else "AI tooling"


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
    parts.append(f"- AI maturity score: {score}/3")
    return "\n".join(parts) if parts else "- Limited public signal data available"
