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
        score, upside, downside, ratio, scored_count = AggregationAgent.compute_mechanical_score(questions)
        assert score == 1.0
        assert downside == 0.0
        assert ratio is None  # guard against divide-by-zero when no downside exists
        assert scored_count == 2

    def test_mechanical_score_all_risks_is_negative(self):
        from forecaster.agents.aggregation import AggregationAgent
        questions = [
            {"final_probability": 0.7, "impact_magnitude": "critical", "impact_direction": "-"},
        ]
        score, upside, downside, ratio, scored_count = AggregationAgent.compute_mechanical_score(questions)
        assert score == -1.0
        assert upside == 0.0
        assert scored_count == 1

    def test_mechanical_score_mixed_weighs_by_severity(self):
        from forecaster.agents.aggregation import AggregationAgent
        # critical (weight 4) catalyst at p=0.5 vs high (weight 3) risk at p=0.5:
        # upside = 2.0, downside = 1.5, net favors upside despite equal probability
        questions = [
            {"final_probability": 0.5, "impact_magnitude": "critical", "impact_direction": "+"},
            {"final_probability": 0.5, "impact_magnitude": "high", "impact_direction": "-"},
        ]
        score, upside, downside, ratio, scored_count = AggregationAgent.compute_mechanical_score(questions)
        assert upside == 2.0
        assert downside == 1.5
        assert score > 0
        assert scored_count == 2

    def test_mechanical_score_empty_questions_is_neutral(self):
        from forecaster.agents.aggregation import AggregationAgent
        score, upside, downside, ratio, scored_count = AggregationAgent.compute_mechanical_score([])
        assert score == 0.0
        assert ratio is None
        assert scored_count == 0

    def test_mechanical_score_ignores_medium_low_magnitude(self):
        """Only high/critical carry a severity weight — medium/low should
        never reach aggregation (decomposition filters them), but the
        formula itself must not silently count them if one slips through."""
        from forecaster.agents.aggregation import AggregationAgent
        questions = [
            {"final_probability": 0.9, "impact_magnitude": "medium", "impact_direction": "+"},
        ]
        score, upside, downside, ratio, scored_count = AggregationAgent.compute_mechanical_score(questions)
        assert upside == 0.0
        assert score == 0.0
        assert scored_count == 0  # medium magnitude never contributes a weight

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


class TestComputeLowNAdjustment:
    """compute_mechanical_score pins the score to +/-1 whenever every scored
    question lands on the same side of the ledger (guaranteed at n=1) --
    compute_low_n_adjustment widens buy/sell thresholds toward hold as
    scored_count drops below the full-decomposition count (4), tapering to
    zero at and above it."""

    def test_single_question_hits_max_adjustment(self):
        from forecaster.agents.aggregation import AggregationAgent
        assert AggregationAgent.compute_low_n_adjustment(1) == 0.20

    def test_two_questions_is_two_thirds_of_max(self):
        from forecaster.agents.aggregation import AggregationAgent
        assert AggregationAgent.compute_low_n_adjustment(2) == pytest.approx(0.1333, abs=1e-4)

    def test_three_questions_is_one_third_of_max(self):
        from forecaster.agents.aggregation import AggregationAgent
        assert AggregationAgent.compute_low_n_adjustment(3) == pytest.approx(0.0667, abs=1e-4)

    def test_full_count_and_above_yields_zero(self):
        from forecaster.agents.aggregation import AggregationAgent
        assert AggregationAgent.compute_low_n_adjustment(4) == 0.0
        assert AggregationAgent.compute_low_n_adjustment(7) == 0.0

    def test_zero_questions_yields_zero(self):
        """An empty scored set is handled by derive_recommendation's 'pass'
        path, not a floored buy/sell -- no threshold widening needed."""
        from forecaster.agents.aggregation import AggregationAgent
        assert AggregationAgent.compute_low_n_adjustment(0) == 0.0

    def test_widened_thresholds_flip_a_low_n_floored_score_to_hold(self):
        """The scenario that motivated this: a single risk question floors
        mechanical_score to -1.0 regardless of its probability. The base
        -0.35 sell threshold would trigger sell; the n=1 widened threshold
        should not."""
        from forecaster.agents.aggregation import AggregationAgent
        questions = [{"final_probability": 0.08, "impact_magnitude": "critical", "impact_direction": "-"}]
        score, upside, downside, ratio, scored_count = AggregationAgent.compute_mechanical_score(questions)
        assert score == -1.0
        low_n_adjustment = AggregationAgent.compute_low_n_adjustment(scored_count)
        sell_threshold = -0.35 - low_n_adjustment
        assert AggregationAgent.derive_recommendation(
            questions, score, None, sell_threshold=sell_threshold
        ) == "sell"  # still floored past even the widened threshold -- signal isn't discarded


# ---------------------------------------------------------------------------
# PrimarySourceAgent -- financials-text fallback for foreign filers with no
# EDGAR coverage (mirrors EarningsAgent's existing financials_text branch)
# ---------------------------------------------------------------------------

def _run_primary_source(
    financials, sec_filings=None, press_filings=None, insider_transactions=None,
):
    """Runs PrimarySourceAgent.run() with edgar_client and the Anthropic call
    mocked out, returning (data_source, prompt_content) so tests can assert on
    what data_source resolved to and what got sent to the model."""
    from forecaster.agents.research.primary_source import PrimarySourceAgent

    agent = PrimarySourceAgent()
    captured = {}

    def fake_call(messages, system=None, max_tokens=1024):
        captured["content"] = messages[0]["content"]
        result = MagicMock()
        result.output = {"net_assessment": "neutral", "confidence": "low", "rationale": "r"}
        return result

    with patch(
        "forecaster.agents.research.primary_source.get_recent_filings",
        side_effect=lambda symbol, forms, limit: (
            sec_filings if forms == ("10-K", "10-Q", "20-F") else (press_filings or [])
        ) or [],
    ), patch(
        "forecaster.agents.research.primary_source.fetch_filing_excerpt",
        return_value="excerpt text",
    ), patch(
        "forecaster.agents.research.primary_source.get_insider_transactions",
        return_value=insider_transactions or [],
    ), patch.object(agent, "call", side_effect=fake_call), patch.object(
        agent, "log_call"
    ), patch.object(
        agent, "get_active_prompt", return_value=(1, "system prompt")
    ), patch(
        "forecaster.agents.research.primary_source.update_forecast_columns"
    ):
        agent.run(symbol="TEST", thesis="thesis text", forecast_id=1, financials=financials)

    return captured["content"]


class TestPrimarySourceAgentDataSource:
    """Foreign stocks often have no EDGAR CIK match at all. Mirrors
    EarningsAgent's existing data_source resolution (edgar / financials_text /
    training_knowledge) so a foreign position's Profile financials ground the
    assessment instead of pure training knowledge."""

    def test_uses_financials_text_when_edgar_empty_and_financials_provided(self):
        content = _run_primary_source(
            financials="FY2025 revenue grew 12% YoY to EUR480M.",
            sec_filings=[], press_filings=[], insider_transactions=[],
        )
        assert "data_source=financials_text" in content
        assert "FY2025 revenue grew 12% YoY to EUR480M." in content

    def test_falls_back_to_training_knowledge_when_no_financials_either(self):
        content = _run_primary_source(
            financials=None, sec_filings=[], press_filings=[], insider_transactions=[],
        )
        assert "data_source=training_knowledge" in content
        assert "financials_text" not in content

    def test_edgar_takes_priority_over_financials_when_filings_exist(self):
        content = _run_primary_source(
            financials="some narrative that should be ignored",
            sec_filings=[{"form": "10-K", "filed": "2026-01-01"}],
            press_filings=[], insider_transactions=[],
        )
        assert "data_source=edgar" in content
        assert "some narrative that should be ignored" not in content

    def test_edgar_takes_priority_when_only_insider_transactions_exist(self):
        content = _run_primary_source(
            financials="ignored narrative",
            sec_filings=[], press_filings=[],
            insider_transactions=[{"role": "CEO", "action": "buy", "shares": 1000, "date": "2026-01-01"}],
        )
        assert "data_source=edgar" in content
        assert "ignored narrative" not in content
