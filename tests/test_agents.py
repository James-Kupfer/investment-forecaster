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

    def test_self_correction_prefers_last_complete_object(self):
        """A model occasionally emits a draft object, narrates a
        self-correction, then emits a second, complete object (observed live
        on a real aggregation call) -- the last one is the intended answer,
        not the abandoned draft."""
        from forecaster.utils import extract_json
        text = (
            '{"recommendation": "sell", "confidence": "low"}\n'
            '... correcting to the required schema:\n'
            '{"recommendation": "hold", "confidence": "medium", "decision_rationale": "full text"}'
        )
        out = extract_json(text)
        assert out["recommendation"] == "hold"
        assert out["decision_rationale"] == "full text"

    def test_truncated_json_falls_back_to_last_complete_candidate(self):
        """If the response is cut off mid-object (token limit hit), there is
        no complete top-level object to recover -- must not silently return a
        spuriously-matched inner fragment; {} signals the caller to treat the
        whole call as failed rather than partially/incorrectly populated."""
        from forecaster.utils import extract_json
        text = '{"question_grades": [{"question_index": 0, "score": 0.5}], "decision_rationale": "cut off mid'
        assert extract_json(text) == {}


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

    def test_gates_on_magnitude_not_sign(self):
        """A strong prior SELL signal (negative adjusted_score) is just as
        much reason to re-forecast as a strong BUY — triage gates on |score|,
        not raw value (v2 decomposition model; see plan)."""
        from forecaster.agents.triage import TriageAgent
        assert TriageAgent().run(-0.50) is True
        assert TriageAgent().run(-0.10) is False


# ---------------------------------------------------------------------------
# QuestionDefinitionAgent
# ---------------------------------------------------------------------------

class TestQuestionDefinitionAgent:
    """v2 decomposition agent — emits a list of catalyst/risk sub-questions,
    not a single directional price question (see plan)."""

    def test_parse_response_extracts_decomposition(self):
        from forecaster.agents.question_definition import QuestionDefinitionAgent
        agent = QuestionDefinitionAgent.__new__(QuestionDefinitionAgent)
        payload = json.dumps({
            "questions": [
                {"type": "catalyst", "question_text": "Will X happen?",
                 "impact_magnitude": "critical", "impact_direction": "+"},
            ],
            "monitor_list": [{"description": "Y risk", "reason_excluded": "impact_below_high"}],
            "nearterm_critical_high_count": 1,
            "confidence": "medium",
            "rationale": "x",
        })
        resp = _make_anthropic_response(payload)
        out = agent._parse_response(resp)
        assert len(out["questions"]) == 1
        assert out["nearterm_critical_high_count"] == 1

    def test_parse_response_empty_content(self):
        from forecaster.agents.question_definition import QuestionDefinitionAgent
        agent = QuestionDefinitionAgent.__new__(QuestionDefinitionAgent)
        resp = MagicMock()
        resp.content = []
        assert agent._parse_response(resp) == {}

    def test_cap_questions_enforces_max_seven(self):
        from forecaster.agents.question_definition import QuestionDefinitionAgent
        nine_questions = [{"question_text": f"Q{i}"} for i in range(9)]
        output = QuestionDefinitionAgent.cap_questions({
            "questions": nine_questions,
            "monitor_list": [],
            "nearterm_critical_high_count": 9,
        })
        assert len(output["questions"]) == 7
        assert output["questions"][0]["question_text"] == "Q0"

    def test_cap_questions_under_limit_unchanged(self):
        from forecaster.agents.question_definition import QuestionDefinitionAgent
        three_questions = [{"question_text": f"Q{i}"} for i in range(3)]
        output = QuestionDefinitionAgent.cap_questions({"questions": three_questions})
        assert len(output["questions"]) == 3

    def test_cap_questions_missing_key_defaults_empty(self):
        from forecaster.agents.question_definition import QuestionDefinitionAgent
        output = QuestionDefinitionAgent.cap_questions({})
        assert output["questions"] == []


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

    def test_parse_extracts_scale_adjusted_density_flag(self):
        """New in v2: risk_judge's scale-aware density escalation (decision 5
        in the plan) — a small company hitting the question cap is a stronger
        signal than a conglomerate hitting it."""
        from forecaster.agents.risk_judge import RiskJudgeAgent
        agent = RiskJudgeAgent.__new__(RiskJudgeAgent)
        payload = json.dumps({
            "risks": [],
            "invq2_floor": 0.10,
            "scale_category": "small",
            "scale_basis": "single-market, one segment",
            "scale_adjusted_density_flag": True,
            "confidence": "medium",
            "rationale": "test",
        })
        resp = _make_anthropic_response(payload)
        out = agent._parse_response(resp)
        assert out["scale_adjusted_density_flag"] is True

    def test_parse_extracts_inferred_leverage_and_event_driven_flags(self):
        """market_cap_category/leverage_flag/event_driven_flag were never wired
        as upstream inputs (confirmed dead); risk_judge now infers leverage
        and event-dependence itself from thesis/business/financials text."""
        from forecaster.agents.risk_judge import RiskJudgeAgent
        agent = RiskJudgeAgent.__new__(RiskJudgeAgent)
        payload = json.dumps({
            "risks": [],
            "invq2_floor": 0.15,
            "scale_category": "mid",
            "scale_basis": "regional, two segments",
            "leverage_flag": True,
            "leverage_basis": "financials cite 3.5x net debt/EBITDA",
            "event_driven_flag": False,
            "event_driven_basis": "thesis is a durable multi-year trend, not a binary event",
            "scale_adjusted_density_flag": False,
            "confidence": "medium",
            "rationale": "test",
        })
        resp = _make_anthropic_response(payload)
        out = agent._parse_response(resp)
        assert out["leverage_flag"] is True
        assert out["event_driven_flag"] is False
        assert "net debt" in out["leverage_basis"]


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
    """v2: mechanical expected-value score is always computed in code
    (compute_mechanical_score), never by the LLM — these test the
    deterministic backbone directly. The LLM's role (question_grades,
    adjustment_delta, recommendation) is exercised via _parse_response and
    the bounded clamp_adjustment/derive_recommendation helpers."""

    def test_parse_response_extracts_decision(self):
        from forecaster.agents.aggregation import AggregationAgent
        agent = AggregationAgent.__new__(AggregationAgent)
        resp = _make_anthropic_response(json.dumps({
            "question_grades": [{"question_index": 0, "rationale_quality_score": 0.9,
                                  "rationale_quality_notes": "well-evidenced"}],
            "adjustment_delta": 0.05,
            "score_adjustment_rationale": "minor correlation discount",
            "recommendation": "buy",
            "decision_rationale": "net positive expected impact",
            "confidence": "medium",
        }))
        out = agent._parse_response(resp)
        assert out["recommendation"] == "buy"
        assert out["question_grades"][0]["rationale_quality_score"] == 0.9

    def test_mechanical_score_all_catalysts_is_positive(self):
        from forecaster.agents.aggregation import AggregationAgent
        questions = [
            {"final_probability": 0.8, "impact_magnitude": "critical", "impact_direction": "+"},
            {"final_probability": 0.6, "impact_magnitude": "high", "impact_direction": "+"},
        ]
        score, upside, downside, ratio = AggregationAgent.compute_mechanical_score(questions)
        assert score == 1.0
        assert downside == 0.0
        assert ratio is None  # guard against divide-by-zero when no downside exists

    def test_mechanical_score_all_risks_is_negative(self):
        from forecaster.agents.aggregation import AggregationAgent
        questions = [
            {"final_probability": 0.7, "impact_magnitude": "critical", "impact_direction": "-"},
        ]
        score, upside, downside, ratio = AggregationAgent.compute_mechanical_score(questions)
        assert score == -1.0
        assert upside == 0.0

    def test_mechanical_score_mixed_weighs_by_severity(self):
        from forecaster.agents.aggregation import AggregationAgent
        # critical (weight 4) catalyst at p=0.5 vs high (weight 3) risk at p=0.5:
        # upside = 2.0, downside = 1.5, net favors upside despite equal probability
        questions = [
            {"final_probability": 0.5, "impact_magnitude": "critical", "impact_direction": "+"},
            {"final_probability": 0.5, "impact_magnitude": "high", "impact_direction": "-"},
        ]
        score, upside, downside, ratio = AggregationAgent.compute_mechanical_score(questions)
        assert upside == 2.0
        assert downside == 1.5
        assert score > 0

    def test_mechanical_score_empty_questions_is_neutral(self):
        from forecaster.agents.aggregation import AggregationAgent
        score, upside, downside, ratio = AggregationAgent.compute_mechanical_score([])
        assert score == 0.0
        assert ratio is None

    def test_mechanical_score_ignores_medium_low_magnitude(self):
        """Only high/critical carry a severity weight — medium/low should
        never reach aggregation (decomposition filters them), but the
        formula itself must not silently count them if one slips through."""
        from forecaster.agents.aggregation import AggregationAgent
        questions = [
            {"final_probability": 0.9, "impact_magnitude": "medium", "impact_direction": "+"},
        ]
        score, upside, downside, ratio = AggregationAgent.compute_mechanical_score(questions)
        assert upside == 0.0
        assert score == 0.0

    def test_clamp_adjustment_bounds_large_positive(self):
        from forecaster.agents.aggregation import AggregationAgent
        assert AggregationAgent.clamp_adjustment(0.9) == 0.30

    def test_clamp_adjustment_bounds_large_negative(self):
        from forecaster.agents.aggregation import AggregationAgent
        assert AggregationAgent.clamp_adjustment(-0.9) == -0.30

    def test_clamp_adjustment_passes_through_within_bounds(self):
        from forecaster.agents.aggregation import AggregationAgent
        assert AggregationAgent.clamp_adjustment(0.1) == 0.1

    def test_clamp_adjustment_handles_malformed_input(self):
        from forecaster.agents.aggregation import AggregationAgent
        assert AggregationAgent.clamp_adjustment(None) == 0.0
        assert AggregationAgent.clamp_adjustment("not a number") == 0.0

    def test_recommendation_pass_when_no_questions(self):
        """pass = insufficient scorable signal, distinct from hold = signal
        exists and nets neutral (decision 4)."""
        from forecaster.agents.aggregation import AggregationAgent
        assert AggregationAgent.derive_recommendation([], 0.9, "buy") == "pass"

    def test_recommendation_uses_llm_value_when_valid(self):
        from forecaster.agents.aggregation import AggregationAgent
        questions = [{"final_probability": 0.5}]
        assert AggregationAgent.derive_recommendation(questions, 0.01, "sell") == "sell"

    def test_recommendation_falls_back_to_threshold_when_llm_value_missing(self):
        from forecaster.agents.aggregation import AggregationAgent
        questions = [{"final_probability": 0.5}]
        assert AggregationAgent.derive_recommendation(questions, 0.50, None) == "buy"
        assert AggregationAgent.derive_recommendation(questions, -0.50, None) == "sell"
        assert AggregationAgent.derive_recommendation(questions, 0.0, None) == "hold"

    def test_recommendation_honors_shifted_thresholds(self):
        """An asymmetric position's shifted thresholds should flip a call that
        the base +/-0.35 thresholds would not (James's point: a 10x-upside
        position justifies accepting more mechanical-score risk)."""
        from forecaster.agents.aggregation import AggregationAgent
        questions = [{"final_probability": 0.5}]
        # 0.20 doesn't clear the base 0.35 buy bar...
        assert AggregationAgent.derive_recommendation(questions, 0.20, None) == "hold"
        # ...but does clear a shifted 0.15 buy bar for a highly asymmetric position.
        assert AggregationAgent.derive_recommendation(
            questions, 0.20, None, buy_threshold=0.15, sell_threshold=-0.55
        ) == "buy"
        # symmetric check on the sell side: -0.20 doesn't clear the base -0.35 sell bar...
        assert AggregationAgent.derive_recommendation(questions, -0.20, None) == "hold"
        # ...and a shifted -0.55 sell bar makes it even less likely to trigger sell.
        assert AggregationAgent.derive_recommendation(
            questions, -0.20, None, buy_threshold=0.15, sell_threshold=-0.55
        ) == "hold"


class TestComputeAsymmetryAdjustment:
    """James's point: a stock that can move 10x in a year justifies accepting
    more mechanical-score risk. asymmetric_rating is the investment-profile
    skill's own categorical field (High/Medium/Low/No -- plausible ~1-year
    return path: High=10x, Medium>=5x, Low>=1x, else No), not a boolean."""

    def test_high_rating_hits_max_adjustment(self):
        from forecaster.agents.aggregation import AggregationAgent
        assert AggregationAgent.compute_asymmetry_adjustment("High") == 0.20

    def test_medium_rating_is_half_of_high(self):
        from forecaster.agents.aggregation import AggregationAgent
        # Medium floor is 5x vs High's 10x reference -> half the max adjustment
        assert AggregationAgent.compute_asymmetry_adjustment("Medium") == pytest.approx(0.10)

    def test_low_rating_is_small(self):
        from forecaster.agents.aggregation import AggregationAgent
        # Low floor is 1x vs High's 10x reference -> a tenth of the max adjustment
        assert AggregationAgent.compute_asymmetry_adjustment("Low") == pytest.approx(0.02)

    def test_no_rating_yields_zero(self):
        from forecaster.agents.aggregation import AggregationAgent
        assert AggregationAgent.compute_asymmetry_adjustment("No") == 0.0

    def test_missing_or_unrecognized_rating_yields_zero(self):
        from forecaster.agents.aggregation import AggregationAgent
        assert AggregationAgent.compute_asymmetry_adjustment(None) == 0.0
        assert AggregationAgent.compute_asymmetry_adjustment("") == 0.0
        assert AggregationAgent.compute_asymmetry_adjustment("Yes") == 0.0
        assert AggregationAgent.compute_asymmetry_adjustment(True) == 0.0

    def test_rating_is_case_insensitive(self):
        from forecaster.agents.aggregation import AggregationAgent
        assert AggregationAgent.compute_asymmetry_adjustment("high") == 0.20
        assert AggregationAgent.compute_asymmetry_adjustment(" HIGH ") == 0.20
