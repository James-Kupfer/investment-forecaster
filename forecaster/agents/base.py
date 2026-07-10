import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import anthropic

from forecaster.db import db_cursor

# (input_per_mtok, output_per_mtok, cached_input_per_mtok)
_PRICING: dict[str, tuple[float, float, float]] = {
    'claude-sonnet-4-6':          (3.00, 15.00, 0.30),
    'claude-haiku-4-5-20251001':  (1.00,  5.00, 0.10),
}


@dataclass
class AgentResult:
    agent_id: str
    model_id: str
    prompt_version_id: int
    tokens_in: int
    tokens_out: int
    tokens_cached: int
    call_cost_usd: float
    duration_ms: int
    output: dict
    error: Optional[str] = None
    response_text: Optional[str] = None


class BaseAgent(ABC):
    agent_id: str
    model: str

    def __init__(self) -> None:
        from forecaster.agents.model_config import AGENT_MODELS
        if self.agent_id in AGENT_MODELS:
            self.model = AGENT_MODELS[self.agent_id]
        self.client = anthropic.Anthropic()

    def get_active_prompt(self) -> tuple[int, str]:
        with db_cursor() as cursor:
            cursor.execute(
                'SELECT id, prompt_text FROM prompt_registry '
                'WHERE agent_id = %s AND is_active = TRUE',
                (self.agent_id,),
            )
            row = cursor.fetchone()
        if not row:
            raise ValueError(f'No active prompt for agent "{self.agent_id}"')
        return row[0], row[1]

    def call(
        self,
        messages: list,
        system: Optional[str] = None,
        max_tokens: int = 1024,
    ) -> AgentResult:
        prompt_version_id, _ = self.get_active_prompt()
        start = time.monotonic()
        response = None
        error = None

        raw_text = None
        try:
            params: dict = {'model': self.model, 'max_tokens': max_tokens, 'messages': messages}
            if system:
                params['system'] = system
            response = self.client.messages.create(**params)
            raw_text = response.content[0].text if response.content else None
            output = self._parse_response(response)
        except Exception as exc:
            error = str(exc)
            output = {}

        duration_ms = int((time.monotonic() - start) * 1000)
        tokens_in = response.usage.input_tokens if response else 0
        tokens_out = response.usage.output_tokens if response else 0
        tokens_cached = (
            getattr(response.usage, 'cache_read_input_tokens', 0) if response else 0
        )

        return AgentResult(
            agent_id=self.agent_id,
            model_id=self.model,
            prompt_version_id=prompt_version_id,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            tokens_cached=tokens_cached,
            call_cost_usd=self._compute_cost(tokens_in, tokens_out, tokens_cached),
            duration_ms=duration_ms,
            output=output,
            error=error,
            response_text=raw_text,
        )

    def log_call(
        self,
        result: AgentResult,
        forecast_id: Optional[int] = None,
        macro_state_id: Optional[int] = None,
    ) -> None:
        """Write to llm_call_log before returning — never batch this write."""
        with db_cursor() as cursor:
            cursor.execute(
                'INSERT INTO llm_call_log '
                '(forecast_id, macro_state_id, agent_id, prompt_version_id, '
                ' executing_model, tokens_in, tokens_out, tokens_cached, '
                ' call_cost_usd, duration_ms, error, response_text) '
                'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
                (forecast_id, macro_state_id, result.agent_id, result.prompt_version_id,
                 result.model_id, result.tokens_in, result.tokens_out, result.tokens_cached,
                 result.call_cost_usd, result.duration_ms, result.error, result.response_text),
            )

    @abstractmethod
    def _parse_response(self, response) -> dict:
        ...

    def _compute_cost(self, tokens_in: int, tokens_out: int, tokens_cached: int) -> float:
        rates = _PRICING.get(self.model, (3.00, 15.00, 0.30))
        non_cached = max(0, tokens_in - tokens_cached)
        return (non_cached * rates[0] + tokens_out * rates[1] + tokens_cached * rates[2]) / 1_000_000
