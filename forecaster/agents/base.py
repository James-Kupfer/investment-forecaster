import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import anthropic

import forecaster.credentials  # noqa: F401 (loads ANTHROPIC_API_KEY into os.environ)
from forecaster.db import db_cursor

# (input_per_mtok, output_per_mtok, cached_input_per_mtok)
# NOTE: claude-sonnet-5 rate below is carried over from the old claude-sonnet-4-6
# entry as a placeholder — verify against Anthropic's current pricing page.
_PRICING: dict[str, tuple[float, float, float]] = {
    'claude-sonnet-5':            (3.00, 15.00, 0.30),
    'claude-haiku-4-5-20251001':  (1.00,  5.00, 0.10),
    # Opus historically prices at ~5x Sonnet on both input and output; cached
    # input follows the same 10%-of-input pattern used for the other two rows.
    # Not yet confirmed against Anthropic's current published rate for this
    # specific model — verify before treating logged costs as exact.
    'claude-opus-4-8':            (15.00, 75.00, 1.50),
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
    """agent_id must be set by every subclass. model is NOT declared by
    subclasses — personas/model_config.py's AGENT_MODELS is the sole owner of
    model assignment; every agent_id must be listed there (see
    C:\\Users\\james\\.claude\\plans\\i-updated-the-list-wise-pnueli.md)."""

    agent_id: str
    model: str

    def __init__(self) -> None:
        from personas.model_config import AGENT_MODELS
        if self.agent_id not in AGENT_MODELS:
            raise ValueError(
                f'No model configured for agent_id "{self.agent_id}" in '
                f'personas/model_config.py — add it before instantiating this agent.'
            )
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

    @staticmethod
    def extract_text_block(response) -> Optional[str]:
        """Return the first actual text block's content. response.content[0]
        is NOT reliably the text block — models with extended thinking
        enabled (observed with claude-sonnet-5) return a ThinkingBlock first,
        which has no .text attribute. Every agent's _parse_response must go
        through this rather than indexing content[0] directly."""
        if not response or not response.content:
            return None
        for block in response.content:
            text = getattr(block, 'text', None)
            if text is not None:
                return text
        return None

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
            # Streaming, not .create() -- the SDK refuses non-streaming requests
            # it estimates could exceed 10 minutes (observed live once max_tokens
            # was raised on Opus: "Streaming is required for operations that may
            # take longer than 10 minutes"). Streaming avoids this unconditionally
            # regardless of model/max_tokens, so every agent uses it, not just the
            # large-budget ones. get_final_message() reassembles the same Message
            # shape .create() would have returned (.content, .usage, etc.).
            with self.client.messages.stream(**params) as stream:
                response = stream.get_final_message()
            raw_text = self.extract_text_block(response)
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
