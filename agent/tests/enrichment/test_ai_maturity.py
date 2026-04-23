"""Tests for AIMaturityScorer."""

import pytest
from enrichment.ai_maturity import AIMaturityScorer, AIMaturityScore


@pytest.fixture
def scorer() -> AIMaturityScorer:
    return AIMaturityScorer()


def _make_score(score: int, confidence: float = 0.5) -> AIMaturityScore:
    return AIMaturityScore(score=score, confidence=confidence)


class TestScoreEmptyInput:
    def test_all_empty_gives_score_zero(self, scorer):
        result = scorer.score(
            job_posts=[], team_page=None, github_org=None,
            executive_posts=[], tech_stack=[], press_mentions=[],
        )
        assert result.score == 0

    def test_empty_confidence_is_high(self, scorer):
        result = scorer.score(
            job_posts=[], team_page=None, github_org=None,
            executive_posts=[], tech_stack=[], press_mentions=[],
        )
        assert result.confidence == 0.8

    def test_empty_evidence_list_is_empty(self, scorer):
        result = scorer.score(
            job_posts=[], team_page=None, github_org=None,
            executive_posts=[], tech_stack=[], press_mentions=[],
        )
        assert result.evidence == []


class TestAIRoleSignal:
    def test_one_ai_role_increases_score(self, scorer):
        result = scorer.score(
            job_posts=[{"title": "ML Engineer"}],
            team_page=None, github_org=None,
            executive_posts=[], tech_stack=[], press_mentions=[],
        )
        assert result.score >= 1
        assert any("AI/ML" in e for e in result.evidence)

    def test_three_ai_roles_gives_high_contribution(self, scorer):
        posts = [
            {"title": "ML Engineer"},
            {"title": "AI Engineer"},
            {"title": "Machine Learning Researcher"},
        ]
        result = scorer.score(
            job_posts=posts, team_page=None, github_org=None,
            executive_posts=[], tech_stack=[], press_mentions=[],
        )
        assert result.signals["ai_open_roles"] == 3

    def test_non_ai_roles_not_counted(self, scorer):
        result = scorer.score(
            job_posts=[{"title": "Sales Manager"}, {"title": "Marketing Lead"}],
            team_page=None, github_org=None,
            executive_posts=[], tech_stack=[], press_mentions=[],
        )
        assert result.signals["ai_open_roles"] == 0


class TestAILeadershipSignal:
    def test_team_page_with_ai_leader(self, scorer):
        result = scorer.score(
            job_posts=[], team_page="Our Head of AI oversees all ML initiatives",
            github_org=None, executive_posts=[], tech_stack=[], press_mentions=[],
        )
        assert result.signals["ai_leadership"] is True
        assert any("AI/ML leadership" in e for e in result.evidence)

    def test_exec_post_with_vp_of_ai(self, scorer):
        result = scorer.score(
            job_posts=[], team_page=None, github_org=None,
            executive_posts=[{"title": "VP of AI joins our team", "content": ""}],
            tech_stack=[], press_mentions=[],
        )
        assert result.signals["ai_leadership"] is True

    def test_no_ai_leadership_signal(self, scorer):
        result = scorer.score(
            job_posts=[], team_page="Engineering team page",
            github_org=None, executive_posts=[], tech_stack=[], press_mentions=[],
        )
        assert result.signals["ai_leadership"] is False


class TestGitHubSignal:
    def test_github_org_with_ai_keyword(self, scorer):
        result = scorer.score(
            job_posts=[], team_page=None, github_org="https://github.com/acme-ai",
            executive_posts=[], tech_stack=[], press_mentions=[],
        )
        assert result.signals["github_ai_activity"] is True

    def test_github_org_without_ai_keyword(self, scorer):
        result = scorer.score(
            job_posts=[], team_page=None, github_org="https://github.com/acmecorp",
            executive_posts=[], tech_stack=[], press_mentions=[],
        )
        assert result.signals["github_ai_activity"] is False

    def test_no_github_org(self, scorer):
        result = scorer.score(
            job_posts=[], team_page=None, github_org=None,
            executive_posts=[], tech_stack=[], press_mentions=[],
        )
        assert result.signals["github_ai_activity"] is False


class TestMLStackSignal:
    def test_snowflake_in_stack(self, scorer):
        result = scorer.score(
            job_posts=[], team_page=None, github_org=None,
            executive_posts=[], tech_stack=["Snowflake", "dbt"], press_mentions=[],
        )
        assert result.signals["modern_ml_stack"]
        assert "snowflake" in result.signals["modern_ml_stack"]

    def test_no_ml_stack(self, scorer):
        result = scorer.score(
            job_posts=[], team_page=None, github_org=None,
            executive_posts=[], tech_stack=["React", "Node.js"], press_mentions=[],
        )
        assert not result.signals["modern_ml_stack"]


class TestExecutiveCommentary:
    def test_ai_strategy_in_post(self, scorer):
        result = scorer.score(
            job_posts=[], team_page=None, github_org=None,
            executive_posts=[{"content": "Our ai strategy is to lead the market", "title": ""}],
            tech_stack=[], press_mentions=[],
        )
        assert result.signals["executive_commentary"] is True

    def test_no_ai_in_posts(self, scorer):
        result = scorer.score(
            job_posts=[], team_page=None, github_org=None,
            executive_posts=[{"content": "We are hiring fast", "title": ""}],
            tech_stack=[], press_mentions=[],
        )
        assert result.signals["executive_commentary"] is False


class TestMaxScore:
    def test_all_signals_yields_score_3(self, scorer):
        result = scorer.score(
            job_posts=[{"title": "ML Engineer"}, {"title": "AI Engineer"}, {"title": "LLM Engineer"}],
            team_page="Head of AI leads all strategy",
            github_org="https://github.com/acme-ml-platform",
            executive_posts=[{"content": "Our generative ai strategy is transforming delivery", "title": ""}],
            tech_stack=["Snowflake", "Databricks"],
            press_mentions=[{"title": "Acme Corp bets big on AI", "content": "artificial intelligence"}],
        )
        assert result.score == 3
        assert len(result.evidence) >= 4


class TestConfidence:
    def test_confidence_increases_with_signals(self, scorer):
        low = scorer.score(
            job_posts=[], team_page=None, github_org=None,
            executive_posts=[], tech_stack=[], press_mentions=[],
        )
        high = scorer.score(
            job_posts=[{"title": "ML Engineer"}],
            team_page="Head of AI",
            github_org="https://github.com/acme-ai",
            executive_posts=[], tech_stack=[], press_mentions=[],
        )
        assert high.confidence >= low.confidence

    def test_both_high_weight_signals_boost_confidence(self, scorer):
        result = scorer.score(
            job_posts=[{"title": "ML Engineer"}],
            team_page="Head of AI leads the team",
            github_org=None, executive_posts=[], tech_stack=[], press_mentions=[],
        )
        assert result.confidence > 0.5


class TestPitchLanguageModifier:
    def test_segment1_low_maturity(self, scorer):
        score = _make_score(1)
        modifier = scorer.get_pitch_language_modifier(score, "segment_1")
        assert "first AI function" in modifier

    def test_segment1_high_maturity(self, scorer):
        score = _make_score(2)
        modifier = scorer.get_pitch_language_modifier(score, "segment_1")
        assert "scale your AI team" in modifier

    def test_segment2_low_maturity(self, scorer):
        score = _make_score(1)
        modifier = scorer.get_pitch_language_modifier(score, "segment_2")
        assert "reducing burn" in modifier

    def test_segment2_high_maturity(self, scorer):
        score = _make_score(2)
        modifier = scorer.get_pitch_language_modifier(score, "segment_2")
        assert "optimize" in modifier

    def test_segment4_low_returns_none(self, scorer):
        score = _make_score(1)
        modifier = scorer.get_pitch_language_modifier(score, "segment_4")
        assert modifier is None

    def test_unknown_segment_returns_none(self, scorer):
        score = _make_score(2)
        modifier = scorer.get_pitch_language_modifier(score, "segment_unknown")
        assert modifier is None
