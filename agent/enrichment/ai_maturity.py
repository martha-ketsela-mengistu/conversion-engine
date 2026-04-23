"""AI Maturity scoring (0-3) from public signals."""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from observability.tracing import observe


@dataclass
class AIMaturityScore:
    """0-3 score with evidence and confidence."""
    score: int
    confidence: float
    evidence: List[str] = field(default_factory=list)
    signals: Dict[str, Any] = field(default_factory=dict)


class AIMaturityScorer:
    """
    Score AI maturity from public signals.

    Scoring rubric:
    - 0: No public signal of AI engagement
    - 1: Weak signals (1-2 medium-weight inputs)
    - 2: Moderate signals (multiple medium or one high-weight)
    - 3: Strong signals (multiple high-weight inputs)
    """

    SIGNAL_WEIGHTS = {
        "ai_open_roles": "high",
        "ai_leadership": "high",
        "github_ai_activity": "medium",
        "executive_commentary": "medium",
        "modern_ml_stack": "low",
        "strategic_comms": "low",
    }

    AI_ROLE_KEYWORDS = [
        "ml engineer", "machine learning", "ai engineer", "llm engineer",
        "applied scientist", "data scientist", "ai product manager",
        "data platform engineer", "ml ops", "ml infrastructure",
    ]

    AI_LEADERSHIP_KEYWORDS = [
        "head of ai", "vp of ai", "chief ai", "director of ai",
        "head of ml", "vp of data", "chief data scientist", "director of data science",
    ]

    @observe(name="ai_maturity.score")
    def score(
        self,
        job_posts: List[Dict],
        team_page: Optional[str],
        github_org: Optional[str],
        executive_posts: List[Dict],
        tech_stack: List[str],
        press_mentions: List[Dict],
    ) -> AIMaturityScore:
        """Compute AI maturity score from available signals."""
        evidence = []
        signals = {}
        weighted_score = 0.0
        max_possible = 0.0

        ai_role_count = self._count_ai_roles(job_posts)
        signals["ai_open_roles"] = ai_role_count
        if ai_role_count >= 3:
            weighted_score += 3 * self._weight_value("high")
            evidence.append(f"{ai_role_count} AI/ML roles open")
        elif ai_role_count >= 1:
            weighted_score += 1.5 * self._weight_value("high")
            evidence.append(f"{ai_role_count} AI/ML role(s) open")
        max_possible += self._weight_value("high")

        has_ai_leader = self._detect_ai_leadership(team_page, executive_posts)
        signals["ai_leadership"] = has_ai_leader
        if has_ai_leader:
            weighted_score += 3 * self._weight_value("high")
            evidence.append("Has dedicated AI/ML leadership")
        max_possible += self._weight_value("high")

        github_ai = self._check_github_ai_activity(github_org)
        signals["github_ai_activity"] = github_ai
        if github_ai:
            weighted_score += 2 * self._weight_value("medium")
            evidence.append("AI-related GitHub activity detected")
        max_possible += self._weight_value("medium")

        ai_commentary = self._check_executive_commentary(executive_posts)
        signals["executive_commentary"] = ai_commentary
        if ai_commentary:
            weighted_score += 2 * self._weight_value("medium")
            evidence.append("Executive commentary mentions AI strategy")
        max_possible += self._weight_value("medium")

        ml_stack = self._check_ml_stack(tech_stack)
        signals["modern_ml_stack"] = ml_stack
        if ml_stack:
            weighted_score += 1 * self._weight_value("low")
            evidence.append(f"Modern ML tools detected: {ml_stack[:3]}")
        max_possible += self._weight_value("low")

        strat_ai = self._check_strategic_comms(press_mentions)
        signals["strategic_comms"] = strat_ai
        if strat_ai:
            weighted_score += 1 * self._weight_value("low")
            evidence.append("AI mentioned in strategic communications")
        max_possible += self._weight_value("low")

        normalized = (weighted_score / max_possible) * 3 if max_possible > 0 else 0
        score = int(round(normalized))
        confidence = self._calculate_confidence(signals)

        return AIMaturityScore(
            score=min(3, max(0, score)),
            confidence=confidence,
            evidence=evidence,
            signals=signals,
        )

    def get_pitch_language_modifier(self, score: AIMaturityScore, segment: str) -> Optional[str]:
        """Get language modifier for outreach based on AI maturity and ICP segment."""
        if segment == "segment_1":
            if score.score >= 2:
                return "scale your AI team faster than in-house hiring can support"
            return "stand up your first AI function with a dedicated squad"
        elif segment == "segment_2":
            if score.score >= 2:
                return "optimize your existing AI delivery capacity"
            return "build AI capabilities while reducing burn"
        elif segment == "segment_4":
            if score.score >= 2:
                return "accelerate specialized AI initiatives"
            return None
        return None

    def _weight_value(self, weight: str) -> float:
        return {"high": 3.0, "medium": 2.0, "low": 1.0}.get(weight, 1.0)

    def _calculate_confidence(self, signals: Dict) -> float:
        present = sum(1 for v in signals.values() if v)
        if present == 0:
            return 0.8
        base_confidence = min(1.0, present / 4)
        if signals.get("ai_open_roles") and signals.get("ai_leadership"):
            base_confidence = min(1.0, base_confidence + 0.15)
        return base_confidence

    def _count_ai_roles(self, job_posts: List[Dict]) -> int:
        count = 0
        for post in job_posts:
            text = (post.get("title", "") + " " + post.get("description", "")).lower()
            if any(kw in text for kw in self.AI_ROLE_KEYWORDS):
                count += 1
        return count

    def _detect_ai_leadership(self, team_page: Optional[str], executive_posts: List[Dict]) -> bool:
        sources = []
        if team_page:
            sources.append(team_page.lower())
        for post in executive_posts:
            sources.append(post.get("content", "").lower())
            sources.append(post.get("title", "").lower())
        combined = " ".join(sources)
        return any(kw in combined for kw in self.AI_LEADERSHIP_KEYWORDS)

    def _check_github_ai_activity(self, github_org: Optional[str]) -> bool:
        if github_org:
            ai_indicators = ["ai", "ml", "llm", "data", "model", "inference"]
            return any(ind in github_org.lower() for ind in ai_indicators)
        return False

    def _check_executive_commentary(self, executive_posts: List[Dict]) -> bool:
        ai_keywords = ["artificial intelligence", "machine learning", "llm",
                       "generative ai", "ai strategy", "ai transformation"]
        for post in executive_posts:
            if any(kw in post.get("content", "").lower() for kw in ai_keywords):
                return True
        return False

    def _check_ml_stack(self, tech_stack: List[str]) -> List[str]:
        ml_tools = [
            "dbt", "snowflake", "databricks", "weights and biases",
            "ray", "vllm", "hugging face", "langchain", "llamaindex",
            "pinecone", "weaviate", "chroma", "mlflow", "kubeflow",
        ]
        stack_text = " ".join(t.lower() for t in tech_stack)
        return [tool for tool in ml_tools if tool in stack_text]

    def _check_strategic_comms(self, press_mentions: List[Dict]) -> bool:
        ai_keywords = ["ai", "artificial intelligence", "machine learning"]
        for mention in press_mentions:
            text = (mention.get("title", "") + " " + mention.get("content", "")).lower()
            if any(kw in text for kw in ai_keywords):
                return True
        return False
