"""
Unit tests for agent layer.  Anthropic API calls are mocked so these run
without a live API key or network access.
"""
from __future__ import annotations

import json
import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_anthropic_response(text: str) -> MagicMock:
    """Minimal mock of anthropic.types.Message."""
    block = MagicMock()
    block.text = text
    response = MagicMock()
    response.content = [block]
    response.usage.input_tokens = 100
    response.usage.output_tokens = 50
    response.usage.cache_read_input_tokens = 0
    return response


def _patch_db_and_api(agent_cls, prompt_text: str, api_response_text: str):
    """
    Returns a context manager that patches:
    - db_cursor so the agent can look up its prompt
    - anthropic.Anthropic.messages.create so no real API call is made
    """
    mock_cursor = MagicMock()
    # get_active_prompt returns (prompt_id=1, prompt_text)
    mock_cursor.fetchone.return_value = (1, prompt_text)
    mock_cm = MagicMock()
    mock_cm.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cm.__exit__ = MagicMock(return_value=False)

    return (
        patch("forecaster.agents.base.db_cursor", return_value=mock_cm),
        patch("forecaster.db.db_cursor", return_value=mock_cm),
        patch(
            "anthropic.Anthropic.messages",
            new_callable=lambda: type(
                "_M", (),
                {"create": staticmethod(lambda **kw: _make_anthropic_response(api_response_text))},
            ),
        ),
    )


# ---------------------------------------------------------------------------
# utils
# ---------------------------------------------------------------------------

class TestExtractJson:
    def test_bare_json(self):
        from forecaster.utils import extract_json
        assert extract_json('{"a": 1}') == {"a": 1}

    def test_fenced_json(self):
        from forecaster.utils import extract_json
        text = '```json\n{"a": 2}\n```'
        assert extract_json(text) == {"a": 2}

    def test_embedded_json(self):
        from forecaster.utils import extract_json
        text = 'Here is the result: {"x": 99} done.'
        assert extract_json(text) == {"x": 99}

    def test_no_json_returns_empty(self):
        from forecaster.utils import extract_json
        assert extract_json("no json here") == {}


# ---------------------------------------------------------------------------
# TriageAgent
# ---------------------------------------------------------------------------

class TestTriageAgent:
    def test_first_run_passes(self):
        from forecaster.agents.triage import TriageAgent
        assert TriageAgent().run(None) is True

    def test_above_threshold_passes(self):
        from forecaster.agents.triage import TriageAgent
        assert TriageAgent().run(0.50) is True

    def test_at_threshold_passes(self):
        from forecaster.agents.triage import TriageAgent
        assert TriageAgent().run(0.30) is True

    def test_below_threshold_fails(self):
        from forecaster.agents.triage import TriageAgent
        assert TriageAgent().run(0.10) is False


# ---------------------------------------------------------------------------
# QuestionDefinitionAgent
# ---------------------------------------------------------------------------

class TestQuestionDefinitionAgent:
    def test_parse_response_extracts_question(self):
        from forecaster.agents.question_definition import QuestionDefinitionAgent
        agent = QuestionDefinitionAgent.__new__(QuestionDefinitionAgent)
        resp = _make_anthropic_response('{"question": "Will AAPL hit $200?", "confidence": "high", "rationale": "x"}')
        out = agent._parse_response(resp)
        assert out["question"] == "Will AAPL hit $200?"
        assert out["confidence"] == "high"

    def test_parse_response_empty_content(self):
        from forecaster.agents.question_definition import QuestionDefinitionAgent
        agent = QuestionDefinitionAgent.__new__(QuestionDefinitionAgent)
        resp = MagicMock()
        resp.content = []
        assert agent._parse_response(resp) == {}


# ---------------------------------------------------------------------------
# MacroQ helpers
# ---------------------------------------------------------------------------

class TestMacroQPersistTree:
    """Tests _persist_tree logic without hitting the DB."""

    def test_empty_nodes_returns_none(self):
        from forecaster.agents.macroq import MacroQAgent
        from forecaster.agents.base import AgentResult
        agent = MacroQAgent.__new__(MacroQAgent)
        result = AgentResult(
            agent_id="macroq", model_id="x", prompt_version_id=1,
            tokens_in=0, tokens_out=0, tokens_cached=0,
            call_cost_usd=0.0, duration_ms=0, output={},
        )
        # Empty nodes list — should return None without touching DB
        with patch("forecaster.agents.macroq.db_cursor"):
            root_id = agent._persist_tree(result, 1)
        assert root_id is None


# ---------------------------------------------------------------------------
# Risk Judge
# ---------------------------------------------------------------------------

class TestRiskJudgeAgent:
    def test_parse_extracts_risks(self):
        from forecaster.agents.risk_judge import RiskJudgeAgent
        agent = RiskJudgeAgent.__new__(RiskJudgeAgent)
        payload = json.dumps({
            "risks": [{"description": "competition", "probability": 0.3, "severity": "high"}],
            "invq2_floor": 0.15,
            "confidence": "medium",
            "rationale": "test",
        })
        resp = _make_anthropic_response(payload)
        out = agent._parse_response(resp)
        assert out["invq2_floor"] == 0.15
        assert len(out["risks"]) == 1


# ---------------------------------------------------------------------------
# Technical agents
# ---------------------------------------------------------------------------

class TestMomentumAgent:
    def test_parse_rsi_value(self):
        from forecaster.agents.technical.momentum import _parse_rsi_value
        assert _parse_rsi_value("RSI 62.5 — neutral") == 62.5
        assert _parse_rsi_value("RSI unavailable") is None
        assert _parse_rsi_value("") is None


class TestTechnicalJudgeAgent:
    def test_parse_verdict(self):
        from forecaster.agents.technical.judge import TechnicalJudgeAgent
        agent = TechnicalJudgeAgent.__new__(TechnicalJudgeAgent)
        resp = _make_anthropic_response(
            '{"technical_verdict": "bullish", "confidence": "high", "rationale": "r"}'
        )
        out = agent._parse_response(resp)
        assert out["technical_verdict"] == "bullish"


# ---------------------------------------------------------------------------
# Review Agent flag handling
# ---------------------------------------------------------------------------

class TestReviewAgent:
    def test_flag_bool_true(self):
        from forecaster.agents.review import ReviewAgent
        agent = ReviewAgent.__new__(ReviewAgent)
        resp = _make_anthropic_response(
            '{"review_flag": true, "critique": "overconfident", "confidence": "medium"}'
        )
        out = agent._parse_response(resp)
        assert out["review_flag"] is True

    def test_flag_bool_false(self):
        from forecaster.agents.review import ReviewAgent
        agent = ReviewAgent.__new__(ReviewAgent)
        resp = _make_anthropic_response(
            '{"review_flag": false, "critique": "looks fine", "confidence": "high"}'
        )
        out = agent._parse_response(resp)
        assert out["review_flag"] is False


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

class TestAggregationAgent:
    def test_parse_probabilities(self):
        from forecaster.agents.aggregation import AggregationAgent
        agent = AggregationAgent.__new__(AggregationAgent)
        resp = _make_anthropic_response(json.dumps({
            "upside_probability": 0.65,
            "downside_probability": 0.20,
            "compound_conviction": 0.55,
            "asymmetry_ratio": 3.25,
            "thesis_crux": "margin expansion",
            "summary": "Positive outlook.",
            "confidence": "medium",
        }))
        out = agent._parse_response(resp)
        assert out["upside_probability"] == 0.65
        assert out["compound_conviction"] == 0.55
